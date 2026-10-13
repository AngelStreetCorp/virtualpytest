"""
Screenshot Tools - Capture device screenshots

Capture screenshots for AI vision analysis. The MCP response includes the JPEG
as a base64 image content block so the calling LLM can SEE the pixels — not
just a URL string. Without this, agents with vision capability still can't
read values off a captured frame because the image never reaches the next turn.
"""

import base64
import logging
from typing import Any, Dict, Optional, Tuple

import requests

from shared.src.lib.config.constants import APP_CONFIG, get_team_id
from shared.src.lib.utils.build_url_utils import call_host
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from shared.src.lib.utils import cv2_io

logger = logging.getLogger(__name__)

# Guard: some upstream frames can be large. Skip embedding above this size
# and fall back to URL-only (the caller can still fetch it, but we won't
# blow up the MCP payload).
_MAX_EMBED_BYTES = 2 * 1024 * 1024  # 2 MB


def _host_name_from_url(screenshot_url: str) -> Optional[str]:
    """`/host/<name>/stream/...` -> `<name>`; None for any other shape."""
    parts = [p for p in screenshot_url.split('?', 1)[0].split('/') if p]
    if len(parts) >= 3 and parts[0] == 'host' and parts[2] == 'stream':
        return parts[1]
    return None


def _fetch_screenshot_bytes(screenshot_url: str, host_name: Optional[str] = None) -> Tuple[Optional[bytes], Optional[str]]:
    """Fetch a capture's bytes. Returns (bytes, None) or (None, reason).

    A relative `/host/<name>/stream/...` URL is fetched from that host with call_host() —
    the host answers the nginx-shaped path itself and accepts the service key. An absolute
    URL (cloud storage) is fetched as-is, with TLS verification on.
    """
    if not screenshot_url:
        return None, "no screenshot URL"
    try:
        if screenshot_url.startswith(('http://', 'https://')):
            resp = requests.get(screenshot_url, timeout=10, allow_redirects=True)
            if resp.status_code == 200 and resp.content:
                return resp.content, None
            return None, f"HTTP {resp.status_code} from {screenshot_url}"

        name = _host_name_from_url(screenshot_url) or host_name
        if not name:
            return None, f"cannot tell which host serves {screenshot_url}"
        from backend_server.src.lib.utils.server_utils import get_host_manager
        host_info = get_host_manager().get_host(name)
        if not host_info:
            return None, f"host {name} is not registered"
        content, status = call_host(host_info, screenshot_url, method='GET', timeout=10, raw_response=True)
        if status == 200 and isinstance(content, (bytes, bytearray)) and content:
            return bytes(content), None
        detail = content.get('error') if isinstance(content, dict) else ''
        return None, f"HTTP {status} from host {name}{': ' + detail if detail else ''}"
    except Exception as e:  # noqa: BLE001 — embed is best-effort, reported to the caller
        return None, f"{type(e).__name__}: {e}"

# Vision-LLM (VLM) dispatcher
# ------------------------------------------------------------------
# The capture pipeline injects a text description of the frame alongside the
# JPEG so the calling chat LLM can reason about focus / popups / low-contrast
# values without needing native multimodal support. The chat LLM (Atlas) and
# the VLM are DECOUPLED — the VLM is the AI route for usage ``vision.screenshot``
# (TASK-30), picked independently of the agent's model in Settings → AI.
#
# When the AI call fails, the local tesseract OCR description below is used
# instead (no focus/popup reasoning, but never unavailable).
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
                cv2_io.imwrite(tmp.name, variant)
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

def _vlm_tesseract(image_bytes: bytes) -> str | None:
    """
    OCR-only fallback. No focus / popup reasoning — just the raw text.
    Shaped into the same (a)(b)(c)(d) structure so pack observation rules work,
    but (b) always reports 'no focus' (tesseract doesn't see colour indicators),
    and (d) gets the full OCR dump as LABEL: VALUE guesses where possible.

    Used when the vision.screenshot AI call fails (endpoint unreachable, no key,
    empty answer).
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


def _describe_via_vlm(image_bytes: bytes, team_id: str | None = None) -> tuple[str | None, str]:
    """
    Describe a frame with the ``vision.screenshot`` AI route; tesseract OCR if that fails.

    Returns (text, source_label) — the label goes into the Vision block so the agent
    logs / JSONL trace make the VLM source explicit.
    """
    from shared.src.lib.ai import gateway

    result = gateway.complete(
        "vision.screenshot",
        _VLM_PROMPT,
        image_b64=base64.b64encode(image_bytes).decode("ascii"),
        media_type="image/jpeg",
        max_tokens=500,
        temperature=0.0,
        team_id=team_id,
    )
    if result.get("success") and result.get("content"):
        # Packs/skills match the historical 'Vision (minimax vlm)' tag.
        label = "minimax vlm" if result.get("provider_used") == "minimax_vlm" else result.get("profile") or "vlm"
        return result["content"].strip()[:1500], label
    logger.warning("vlm[vision.screenshot] failed: %s — falling back to tesseract", result.get("error"))
    text = _vlm_tesseract(image_bytes)
    return (text, "tesseract(fallback)") if text else (None, "vision.screenshot")


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
                'vlm': bool (OPTIONAL - if true, include a concise vision description from the vision.screenshot AI route. Adds up to 3s latency. Default false. Use true at navigation CHECKPOINTS when you need focus/popup info the OCR cannot see (e.g. which tab is underlined red). Do NOT use between every key press.)
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
        # The screenshot_url is a relative path like /host/<host_name>/stream/<dev>/captures/<file>.
        # It used to be fetched from https://localhost — the server VM's own nginx — which does
        # not exist where the server runs without one (production: connection refused, so no
        # image ever reached the caller, BUG-0388). The host serves that exact path itself
        # (host_stream_routes, service key accepted), so fetch it from the host via call_host().
        image_block = None
        fetch_error: str | None = None
        image_bytes, fetch_error = _fetch_screenshot_bytes(screenshot_url, host_name)
        if image_bytes is not None:
            if len(image_bytes) > _MAX_EMBED_BYTES:
                fetch_error = (
                    f"image too large to embed ({len(image_bytes)} bytes > {_MAX_EMBED_BYTES})"
                )
            else:
                image_block = {
                    "type": "image",
                    "data": base64.b64encode(image_bytes).decode('ascii'),
                    "mimeType": "image/jpeg",
                }

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
            # matters, not between every key press. The model is decoupled from
            # the chat LLM — AI route for usage vision.screenshot.
            if want_vlm:
                try:
                    vlm_text, tag = _describe_via_vlm(img_bytes, team_id)
                    if vlm_text:
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

