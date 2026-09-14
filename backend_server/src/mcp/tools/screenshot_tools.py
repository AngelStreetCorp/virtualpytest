"""
Screenshot Tools - Capture device screenshots

Capture screenshots for AI vision analysis. The MCP response includes the JPEG
as a base64 image content block so the calling LLM can SEE the pixels — not
just a URL string. Without this, agents with vision capability still can't
read values off a captured frame because the image never reaches the next turn.
"""

import base64
import logging
import os
from typing import Any, Dict

import requests

from shared.src.lib.config.constants import APP_CONFIG, get_team_id
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter

logger = logging.getLogger(__name__)

# Guard: some upstream frames can be large. Skip embedding above this size
# and fall back to URL-only (the caller can still fetch it, but we won't
# blow up the MCP payload).
_MAX_EMBED_BYTES = 2 * 1024 * 1024  # 2 MB

# Vision-LLM (VLM) dispatcher
# ------------------------------------------------------------------
# The capture pipeline injects a text description of the frame alongside the
# JPEG so the calling chat LLM can reason about focus / popups / low-contrast
# values without needing native multimodal support. The chat LLM (Atlas) and
# the VLM are DECOUPLED — the VLM is picked independently via VLM_PROVIDER.
#
# This lets us pair any tool-calling chat LLM (Minimax, Claude, OpenAI,
# OpenRouter-hosted models) with any vision backend (Minimax VLM, OCR-only
# tesseract fallback, future: Gemini/Claude Haiku/self-hosted Florence-2).
#
# Each provider returns the description as 4 labelled sections (a)/(b)/(c)/(d)
# so the pack's observation rules ("read focused item from (b)") are provider-agnostic.

# Multi-approach tesseract OCR
# ------------------------------------------------------------------
# Plain tesseract reads clear white-on-dark text but misses gray-on-dark
# low-contrast values (e.g. Example About modal's "5.02" beneath "BUILD VERSION").
# Advanced OCR mirrors what
# backend_host/src/controllers/verification/text_helpers.py:detect_text_in_area(use_advanced_ocr=True)
# does: CLAHE contrast-boost, then run tesseract on a few thresholded variants,
# pick whichever extracts the most text.
#
# This is the server-side OCR embedded in every capture_screenshot response.
# Runs ~200 ms (a bit faster than plain tesseract because Otsu denoise reduces
# tesseract's search space). No API dependency. Handles the low-contrast cases
# that used to force vlm=true for pure text reads.


def _ocr_advanced(image_bytes: bytes) -> str:
    """
    Multi-approach OCR: CLAHE + Otsu (normal + inverted) + plain grayscale.
    Returns the variant with the most extracted text. Empty string on failure.
    """
    try:
        import io
        import subprocess
        import tempfile
        import cv2
        import numpy as np
        from PIL import Image

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            # fallback: use PIL to decode
            pil = Image.open(io.BytesIO(image_bytes)).convert('RGB')
            img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        _, otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, otsu_inv = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        variants = [("otsu_inv", otsu_inv), ("otsu", otsu), ("gray", gray)]
        best_text = ""
        best_variant = ""
        for name, variant in variants:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                cv2.imwrite(tmp.name, variant)
                tmp_path = tmp.name
            try:
                result = subprocess.run(
                    ['tesseract', tmp_path, 'stdout'],
                    capture_output=True, text=True, timeout=15,
                )
                text = (result.stdout or "").strip() if result.returncode == 0 else ""
            finally:
                try:
                    import os as _os
                    _os.unlink(tmp_path)
                except Exception:
                    pass
            if len(text) > len(best_text):
                best_text = text
                best_variant = name

        logger.debug("ocr_advanced: best=%s len=%d", best_variant, len(best_text))
        return best_text
    except Exception as err:
        logger.warning("ocr_advanced failed: %s", err)
        return ""


_VLM_PROMPT = (
    "Describe the screen concisely. "
    "(a) Which view / screen is visible — give the header or title text and the main UI region. "
    "(b) Which single item is focused — look for red/colored underlines, row highlights, bold, "
    "or a focus ring; name the item. If no focus is visible, say 'no focus'. "
    "(c) Is any popup, modal, or dialog overlaid on the main content? If yes, name it; if no, say 'no modal'. "
    "(d) List EVERY visible labelled field or key-value pair verbatim, one per line in the form "
    "'LABEL: VALUE' (copy text exactly). Include labels where the value is blank, short, or in a "
    "different colour / brightness than the label — especially faint grey values underneath bold "
    "white labels (e.g. version numbers, IDs). If there are none, say 'no fields'."
)

_VLM_TIMEOUT = int(os.environ.get("VLM_TIMEOUT_SECONDS", "15"))

# ---- Per-provider adapters ---------------------------------------------------

_MINIMAX_VLM_URL = "https://api.minimax.io/v1/coding_plan/vlm"


def _vlm_minimax(image_bytes: bytes) -> str | None:
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        return None
    try:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        resp = requests.post(
            _MINIMAX_VLM_URL,
            json={"prompt": _VLM_PROMPT, "image_url": f"data:image/jpeg;base64,{b64}"},
            headers={"content-type": "application/json", "authorization": f"Bearer {api_key}"},
            timeout=_VLM_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning("vlm[minimax] HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        content = (resp.json() or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        return content.strip()[:1500]
    except Exception as err:
        logger.warning("vlm[minimax] failed: %s", err)
        return None


def _vlm_tesseract(image_bytes: bytes) -> str | None:
    """
    OCR-only fallback. No focus / popup reasoning — just the raw text.
    Shaped into the same (a)(b)(c)(d) structure so pack observation rules work,
    but (b) always reports 'no focus' (tesseract doesn't see colour indicators),
    and (d) gets the full OCR dump as LABEL: VALUE guesses where possible.

    Use this when VLM_PROVIDER is unset, when upstream VLM APIs are unreachable,
    or for pack steps that genuinely only need verbatim text (e.g. the About
    modal — which ironically doesn't work with tesseract-only on Example because
    the values are gray-on-dark, but works fine on high-contrast screens).
    """
    try:
        import io
        import pytesseract
        from PIL import Image
        ocr = pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes))).strip()
        if not ocr:
            return None
        # Limit to ~2 KB so we don't flood the tool result
        if len(ocr) > 2000:
            ocr = ocr[:2000] + "\n…(truncated)"
        return (
            "(a) View: (tesseract OCR-only — header/screen identity not inferred)\n"
            "(b) Focused item: no focus (tesseract cannot see colour-based focus indicators)\n"
            "(c) Modal: unknown (tesseract cannot distinguish layers)\n"
            "(d) Visible text (verbatim OCR, best-effort):\n"
            f"{ocr}"
        )
    except Exception as err:
        logger.warning("vlm[tesseract] failed: %s", err)
        return None


def _vlm_openai(image_bytes: bytes) -> str | None:
    """
    OpenAI chat completions with vision (GPT-4o, GPT-4o-mini). Model selected
    via OPENAI_VLM_MODEL (default gpt-4o-mini: fast + cheap + good on UI).
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    model = os.environ.get("OPENAI_VLM_MODEL", "gpt-4o-mini")
    try:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _VLM_PROMPT},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }],
                "max_tokens": 500,
            },
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            timeout=_VLM_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning("vlm[openai] HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
        return content.strip()[:1500] if content.strip() else None
    except Exception as err:
        logger.warning("vlm[openai] failed: %s", err)
        return None


def _vlm_anthropic(image_bytes: bytes) -> str | None:
    """Anthropic Messages API (Claude Haiku by default — fast + cheap)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    model = os.environ.get("ANTHROPIC_VLM_MODEL", "claude-haiku-4-5-20251001")
    try:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            json={
                "model": model,
                "max_tokens": 500,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image",
                         "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                        {"type": "text", "text": _VLM_PROMPT},
                    ],
                }],
            },
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=_VLM_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning("vlm[anthropic] HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        blocks = resp.json().get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return text.strip()[:1500] if text.strip() else None
    except Exception as err:
        logger.warning("vlm[anthropic] failed: %s", err)
        return None


def _vlm_gemini(image_bytes: bytes) -> str | None:
    """Google Gemini (Gemini 2.5 Flash default — strong latency, good on UI)."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    model = os.environ.get("GEMINI_VLM_MODEL", "gemini-2.5-flash")
    try:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        resp = requests.post(
            url,
            json={
                "contents": [{
                    "parts": [
                        {"text": _VLM_PROMPT},
                        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                    ]
                }],
                "generationConfig": {"maxOutputTokens": 500},
            },
            headers={"content-type": "application/json"},
            timeout=_VLM_TIMEOUT,
        )
        if resp.status_code != 200:
            logger.warning("vlm[gemini] HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        cands = resp.json().get("candidates") or []
        if not cands:
            return None
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        return text.strip()[:1500] if text.strip() else None
    except Exception as err:
        logger.warning("vlm[gemini] failed: %s", err)
        return None


# ---- Dispatcher --------------------------------------------------------------

_VLM_PROVIDERS = {
    "minimax":   _vlm_minimax,
    "tesseract": _vlm_tesseract,
    "openai":    _vlm_openai,
    "anthropic": _vlm_anthropic,
    "gemini":    _vlm_gemini,
}


def _describe_via_vlm(image_bytes: bytes) -> tuple[str | None, str]:
    """
    Dispatch to the VLM backend selected by the VLM_PROVIDER env var.
    Default: 'minimax' (the provider we validated end-to-end).

    Returns (text, provider_label) — label goes into the Vision block so the
    agent logs / JSONL trace make the VLM source explicit.

    Fallback chain: if the primary provider returns None (API unreachable,
    no API key, empty response), optionally fall back to VLM_PROVIDER_FALLBACK
    (e.g. 'tesseract' always works because it's local and needs no key).
    """
    primary = os.environ.get("VLM_PROVIDER", "minimax").lower().strip()
    fallback = os.environ.get("VLM_PROVIDER_FALLBACK", "").lower().strip() or None

    fn = _VLM_PROVIDERS.get(primary)
    if fn is None:
        logger.warning("vlm: unknown VLM_PROVIDER=%r, valid=%s", primary, list(_VLM_PROVIDERS))
        fn = _vlm_minimax
        primary = "minimax"

    text = fn(image_bytes)
    if text:
        return text, primary

    if fallback and fallback in _VLM_PROVIDERS and fallback != primary:
        logger.info("vlm: primary=%s returned None, trying fallback=%s", primary, fallback)
        text = _VLM_PROVIDERS[fallback](image_bytes)
        if text:
            return text, f"{fallback}(fallback from {primary})"

    return None, primary


class ScreenshotTools:
    """Device screenshot capture tools"""
    
    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()
    
    def capture_screenshot(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Capture a screenshot of a device (latest frame from its AV stream).

        ⚠ This is a TOP-LEVEL tool — call it directly. NEVER nest it inside
        `execute_device_action.actions[]` (the device controllers do not implement
        a 'capture_screenshot' action and will fail silently with 'no error details').

        Use this after each navigation step to verify the device is on the expected
        screen, and to read text values from the screen via vision.

        Example: capture_screenshot(device_id='device3', host_name='host1')

        Args:
            params: {
                'device_id': str (REQUIRED - device identifier),
                'host_name': str (OPTIONAL - host name where device is connected),
                'include_ui_dump': bool (OPTIONAL - include UI hierarchy dump),
                'vlm': bool (OPTIONAL - if true, include a concise vision description from Minimax VLM. Adds up to 3s latency. Default false. Use true at navigation CHECKPOINTS when you need focus/popup info the OCR cannot see (e.g. which tab is underlined red). Do NOT use between every key press.)
            }

        Returns:
            MCP-formatted response with screenshot URL (HTTPS, served by nginx).
            Pass the URL to your vision capability to read text from the image.
        """
        device_id = params.get('device_id')
        team_id = params.get('team_id', get_team_id())
        include_ui_dump = params.get('include_ui_dump', False)
        host_name = params.get('host_name')
        want_vlm = bool(params.get('vlm', False))
        # fast=true: caller wants ONLY the image bytes (it does its own fingerprint/OCR — the
        # auto-builder). Skip the host-side fingerprint + settle AND the server-side OCR below,
        # turning a 6-14s capture into ~sub-second (2026-07-17 profiling).
        fast = bool(params.get('fast', False))

        # Build request
        data = {
            'device_id': device_id
        }
        if fast:
            data['fast'] = True

        if host_name:
            data['host_name'] = host_name
        
        query_params = {'team_id': team_id}
        
        # Use AV endpoint for all devices (unified screenshot)
        result = self.api.post('/server/av/takeScreenshot', data=data, params=query_params)

        if not result.get('success'):
            return self.formatter.format_api_response(result)

        # AV endpoint returns screenshot_url (relative path served by nginx)
        screenshot_url = result.get('screenshot_url', '')
        device_id_result = result.get('device_id', device_id)

        # Build the text part of the response
        response_text = (
            f"✅ Screenshot captured from device: {device_id_result}\n"
            f"URL: {screenshot_url}"
        )
        if include_ui_dump:
            response_text += "\nNote: UI dump not supported via AV endpoint. Use dump_ui_elements tool separately if needed."

        # Fetch the JPEG bytes and embed as an MCP image content block so the
        # calling LLM actually SEES the pixels (not just a URL string).
        # Without this, Atlas's vision capability is effectively disabled —
        # every 'what's on screen?' question is backfilled by hallucination.
        #
        # The screenshot_url is a relative nginx path like
        #   /host/<host_name>/stream/<capture_dir>/captures/<file>
        # served by nginx (NOT by the backend_server itself on port 5109).
        # Try local URL options in order; first hit wins.
        image_block = None
        fetch_error: str | None = None
        candidate_urls = []
        if screenshot_url.startswith('http'):
            candidate_urls.append(screenshot_url)
        else:
            candidate_urls.extend([
                f"https://localhost{screenshot_url}",  # nginx (every VM) — primary
                f"http://localhost{screenshot_url}",   # in case nginx didn't redirect
            ])
        last_status: str = "no candidate URL"
        for url in candidate_urls:
            try:
                # Only the local nginx uses a self-signed cert; keep TLS verification
                # on for any absolute (possibly remote) screenshot URL.
                verify_tls = not url.startswith('https://localhost')
                img_resp = requests.get(url, timeout=10, verify=verify_tls, allow_redirects=True)
                if img_resp.status_code == 200 and img_resp.content:
                    if len(img_resp.content) > _MAX_EMBED_BYTES:
                        fetch_error = (
                            f"image too large to embed ({len(img_resp.content)} bytes > {_MAX_EMBED_BYTES})"
                        )
                    else:
                        image_block = {
                            "type": "image",
                            "data": base64.b64encode(img_resp.content).decode('ascii'),
                            "mimeType": "image/jpeg",
                        }
                    break
                last_status = f"HTTP {img_resp.status_code} from {url}"
            except Exception as e:
                last_status = f"{type(e).__name__} from {url}: {e}"
        if image_block is None and fetch_error is None:
            fetch_error = last_status

        if fetch_error:
            response_text += f"\n⚠ Image embed failed: {fetch_error} — caller can still GET the URL directly."
            logger.warning("capture_screenshot embed failed for %s: %s", device_id_result, fetch_error)

        # Run server-side OCR on the captured image and inline the text.
        # Multi-approach OCR (CLAHE + Otsu normal/inverted + plain) so
        # gray-on-dark values (e.g. firmware version values under white label
        # headers) come out correctly without needing a VLM round-trip. See
        # _ocr_advanced() above — this is the same preprocessing technique
        # used in backend_host/src/controllers/verification/text_helpers.py.
        #
        # The OCR block is the default text channel for the calling LLM. Use
        # vlm=true ONLY when text isn't the question (focus indicators, modal
        # overlay detection, icon recognition). For pure text reads (field
        # values, menu labels), OCR is enough.
        if image_block is not None and not fast:
            try:
                img_bytes = base64.b64decode(image_block["data"])
                ocr_text = _ocr_advanced(img_bytes)
                if ocr_text:
                    # Cap at ~4 KB to avoid blowing prompt tokens on noisy backgrounds
                    if len(ocr_text) > 4000:
                        ocr_text = ocr_text[:4000] + "\n…(truncated)"
                    response_text += (
                        "\n\n--- OCR (tesseract) ---\n"
                        f"{ocr_text}\n"
                        "--- end OCR ---"
                    )
            except Exception as ocr_err:  # noqa: BLE001 — OCR is best-effort
                logger.warning("capture_screenshot OCR failed: %s", ocr_err)

            # VLM description — captures focus indicators (red underlines, row
            # highlights) that tesseract cannot see. OPT-IN via `vlm: true`
            # param because of 3–15 s latency per call. Agents should only
            # request it at navigation checkpoints where focus info actually
            # matters, not between every key press. Provider is decoupled from
            # the chat LLM — select via VLM_PROVIDER env var. Default: minimax.
            if want_vlm:
                try:
                    vlm_text, vlm_provider = _describe_via_vlm(img_bytes)
                    if vlm_text:
                        # NOTE: pack/skill text matches against the string
                        # 'Vision (minimax vlm)' historically. The new format
                        # writes the actual provider label AND keeps a
                        # backward-compatible 'minimax vlm' tag when the
                        # provider IS minimax, so old packs still recognize it.
                        tag = "minimax vlm" if vlm_provider == "minimax" else vlm_provider
                        response_text += (
                            f"\n\n--- Vision ({tag}) ---\n"
                            f"{vlm_text}\n"
                            "--- end Vision ---"
                        )
                except Exception as vlm_err:  # noqa: BLE001 — never fatal
                    logger.warning("capture_screenshot VLM describe failed: %s", vlm_err)

        content = [{"type": "text", "text": response_text}]
        if image_block is not None:
            content.append(image_block)

        return {
            "content": content,
            "isError": False,
            "screenshot_url": screenshot_url,
            "device_id": device_id_result,
        }

