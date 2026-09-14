#!/usr/bin/env python3
"""Reusable helpers for profile-driven Playwright flows."""

import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from shared.src.lib.utils.local_debug_browser_helpers import (
    append_local_debug_step_result,
    capture_local_debug_screenshot,
)


def render_template(value: Any, variables: Dict[str, Any]) -> Any:
    if isinstance(value, str):
        rendered = value
        for key, replacement in variables.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(replacement))
        return rendered
    if isinstance(value, list):
        return [render_template(item, variables) for item in value]
    if isinstance(value, dict):
        return {k: render_template(v, variables) for k, v in value.items()}
    return value


def normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()


def apply_derived_fields(extracted: Dict[str, Any], derived_fields: List[Dict[str, Any]]) -> None:
    for rule in derived_fields:
        target = rule.get("target")
        source = rule.get("source")
        if not target or not source:
            continue
        if source in extracted and extracted[source] not in (None, ""):
            extracted[target] = extracted[source]


async def is_text_visible(page: Any, text: str) -> bool:
    locator = page.get_by_text(text, exact=False).first
    if await locator.count() == 0:
        return False
    return await locator.is_visible()


async def is_pattern_visible(page: Any, pattern: str) -> bool:
    body_text = await page.locator("body").text_content()
    if not body_text:
        return False
    return re.search(pattern, body_text, re.IGNORECASE) is not None


async def is_selector_visible(page: Any, selector: str) -> bool:
    locator = page.locator(selector).first
    if await locator.count() == 0:
        return False
    return await locator.is_visible()


def selector_candidates(action: Dict[str, Any], variables: Dict[str, Any]) -> List[str]:
    raw_candidates = action.get("selectors")
    if raw_candidates:
        return [render_template(candidate, variables) for candidate in raw_candidates]
    raw_selector = action.get("selector")
    if raw_selector:
        return [render_template(raw_selector, variables)]
    return []


async def find_first_locator(
    page: Any,
    selector_list: List[str],
    *,
    require_visible: bool,
    timeout_ms: int,
) -> Optional[Any]:
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        for candidate in selector_list:
            locator = page.locator(candidate)
            count = await locator.count()
            if count == 0:
                continue
            if not require_visible:
                return locator.first
            for idx in range(min(count, 5)):
                try:
                    candidate_locator = locator.nth(idx)
                    if await candidate_locator.is_visible():
                        return candidate_locator
                except Exception:
                    continue
        await page.wait_for_timeout(250)
    return None


def _normalize_compare(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


async def _read_locator_value(locator: Any, source: str) -> str:
    """Read either the input value or visible text of a locator."""
    if source == "value":
        try:
            return (await locator.input_value()) or ""
        except Exception:
            pass
    return ((await locator.text_content()) or "").strip()


async def _read_checked_state(locator: Any) -> bool:
    """Best-effort read of a toggle/checkbox/radio/switch on state.

    Tries Playwright's is_checked() (native inputs + ARIA role=checkbox/radio/
    switch), then aria-checked, then a class-name heuristic as a last resort.
    """
    try:
        return await locator.is_checked()
    except Exception:
        pass
    try:
        aria = await locator.get_attribute("aria-checked")
        if aria is not None:
            return str(aria).strip().lower() == "true"
    except Exception:
        pass
    try:
        cls = (await locator.get_attribute("class")) or ""
        tokens = cls.lower().split()
        if any(t in tokens for t in ("checked", "on", "active", "enabled", "selected")):
            return True
    except Exception:
        pass
    return False


async def execute_action(
    page: Any,
    action: Dict[str, Any],
    variables: Dict[str, Any],
    kpis: Optional[Dict[str, Any]] = None,
) -> None:
    action_type = action.get("type")
    timeout_ms = int(action.get("timeout_ms", 15000))

    if action_type == "goto":
        await page.goto(
            render_template(action["url"], variables),
            wait_until=action.get("wait_until", "domcontentloaded"),
            timeout=timeout_ms,
        )
        return
    if action_type == "capture_url_pattern":
        # Extract a regex group from the current URL and store it as a variable.
        # Example: pattern "/(\\d+\\.\\d+)/gui/" on URL "/0.16/gui/#/login/" → "0.16"
        url = page.url
        pattern = action.get("pattern", "")
        variable_name = action.get("variable", "captured")
        fallback = action.get("fallback", "")
        match = re.search(pattern, url)
        if match and match.group(1):
            variables[variable_name] = match.group(1)
        elif fallback:
            variables[variable_name] = fallback
        else:
            raise ValueError(f"capture_url_pattern: pattern '{pattern}' did not match URL '{url}'")
        return
    if action_type == "wait_for_selector":
        locator = await find_first_locator(
            page,
            selector_candidates(action, variables),
            require_visible=action.get("state", "visible") == "visible",
            timeout_ms=timeout_ms,
        )
        if locator is None:
            raise TimeoutError(f"No selector became available: {selector_candidates(action, variables)}")
        return
    if action_type == "wait_for_timeout":
        await page.wait_for_timeout(int(action.get("timeout_ms", 1000)))
        return
    if action_type == "fill":
        locator = await find_first_locator(
            page,
            selector_candidates(action, variables),
            require_visible=True,
            timeout_ms=timeout_ms,
        )
        if locator is None:
            raise TimeoutError(f"No fill target became visible: {selector_candidates(action, variables)}")
        await locator.fill(render_template(action["value"], variables), timeout=timeout_ms)
        return
    if action_type == "click":
        locator = await find_first_locator(
            page,
            selector_candidates(action, variables),
            require_visible=True,
            timeout_ms=timeout_ms,
        )
        if locator is None:
            raise TimeoutError(f"No click target became visible: {selector_candidates(action, variables)}")
        await locator.click(timeout=timeout_ms)
        return
    if action_type == "fail_if_text_visible":
        pattern = action.get("pattern")
        if pattern:
            rendered_pattern = render_template(pattern, variables)
            if await is_pattern_visible(page, rendered_pattern):
                raise RuntimeError(action.get("message") or f"Visible error pattern: {rendered_pattern}")
            return
        target_texts = action.get("texts")
        if target_texts:
            rendered_texts = [render_template(text, variables) for text in target_texts]
        else:
            rendered_texts = [render_template(action["text"], variables)]
        for target_text in rendered_texts:
            if await is_text_visible(page, target_text):
                raise RuntimeError(action.get("message") or action.get("error_code") or f"Visible error text: {target_text}")
        return
    if action_type == "fail_if_selector_visible":
        for selector in selector_candidates(action, variables):
            if await is_selector_visible(page, selector):
                raise RuntimeError(action.get("message") or f"Unexpected selector visible: {selector}")
        return
    if action_type == "click_if_visible":
        # Best-effort click: click the first visible candidate, silently skip if
        # none appear within the (short) timeout. Used for optional gates like the
        # "uncertified" splash or a wizard "Close" button.
        locator = await find_first_locator(
            page,
            selector_candidates(action, variables),
            require_visible=True,
            timeout_ms=int(action.get("timeout_ms", 3000)),
        )
        if locator is not None:
            await locator.click(timeout=timeout_ms)
        return
    if action_type == "press":
        locator = await find_first_locator(
            page,
            selector_candidates(action, variables),
            require_visible=True,
            timeout_ms=timeout_ms,
        )
        if locator is None:
            raise TimeoutError(f"No press target became visible: {selector_candidates(action, variables)}")
        await locator.press(render_template(action["key"], variables), timeout=timeout_ms)
        return
    if action_type == "read_value":
        # Read an input value (source="value", default) or visible text
        # (source="text") into a variable for later assertions / KPIs.
        locator = await find_first_locator(
            page,
            selector_candidates(action, variables),
            require_visible=False,
            timeout_ms=timeout_ms,
        )
        if locator is None:
            raise TimeoutError(f"read_value: no element for {selector_candidates(action, variables)}")
        source = str(action.get("source", "value")).lower()
        deadline = time.time() + (timeout_ms / 1000.0)
        value = ""
        while time.time() < deadline:
            value = (await _read_locator_value(locator, source)).strip()
            if value or not action.get("wait_for_non_empty", True):
                break
            await page.wait_for_timeout(250)
        variables[action.get("variable", "captured")] = value
        return
    if action_type in ("assert_equals", "assert_contains"):
        # Compare either an explicit rendered "actual"/"expected" pair, or read
        # the live value/text from "selectors" and compare against "expected".
        expected = render_template(action.get("expected", ""), variables)
        if action.get("selectors") or action.get("selector"):
            locator = await find_first_locator(
                page,
                selector_candidates(action, variables),
                require_visible=False,
                timeout_ms=timeout_ms,
            )
            if locator is None:
                raise TimeoutError(f"{action_type}: no element for {selector_candidates(action, variables)}")
            actual = await _read_locator_value(locator, str(action.get("source", "value")).lower())
        else:
            actual = render_template(action.get("actual", ""), variables)
        norm_actual = _normalize_compare(actual)
        norm_expected = _normalize_compare(expected)
        ok = (norm_expected in norm_actual) if action_type == "assert_contains" else (norm_actual == norm_expected)
        if not ok:
            raise RuntimeError(
                action.get("message")
                or f"{action_type} failed: expected '{expected}', got '{actual}'"
            )
        return
    if action_type == "expect_text_visible":
        target_texts = action.get("texts") or [action.get("text", "")]
        for target_text in target_texts:
            rendered = render_template(target_text, variables)
            if not await is_text_visible(page, rendered):
                raise RuntimeError(action.get("message") or f"Expected text not visible: {rendered}")
        return
    if action_type == "expect_selector_visible":
        for selector in selector_candidates(action, variables):
            if await is_selector_visible(page, selector):
                return
        raise RuntimeError(action.get("message") or f"Expected selector not visible: {selector_candidates(action, variables)}")
    if action_type == "ensure_checked":
        # Verify a toggle's state and change it ONLY if it isn't already in the
        # desired state (idempotent "enable if not enabled"). Reads state from
        # "selectors" (the control/switch), clicks "click_selectors" if given
        # (e.g. the wrapping label), otherwise clicks the control itself.
        state_selectors = selector_candidates(action, variables)
        state_loc = await find_first_locator(
            page, state_selectors, require_visible=False, timeout_ms=timeout_ms
        )
        if state_loc is None:
            if action.get("optional"):
                return
            raise TimeoutError(f"ensure_checked: no toggle found for {state_selectors}")
        desired = bool(action.get("desired", True))
        current = await _read_checked_state(state_loc)
        if current != desired:
            click_selectors = [
                render_template(c, variables) for c in action.get("click_selectors", [])
            ] or state_selectors
            click_loc = await find_first_locator(
                page, click_selectors, require_visible=True, timeout_ms=timeout_ms
            )
            if click_loc is None:
                raise TimeoutError(f"ensure_checked: no clickable control for {click_selectors}")
            await click_loc.click(timeout=timeout_ms)
            await page.wait_for_timeout(int(action.get("settle_ms", 800)))
            current = await _read_checked_state(state_loc)
            if current != desired and not action.get("allow_unverified", False):
                raise RuntimeError(
                    action.get("message")
                    or f"ensure_checked: could not set toggle to desired={desired}"
                )
            # Persist the change if an Apply control is provided. This only runs
            # when we actually flipped the toggle — an Apply button is typically
            # disabled (and would hang a click) when there is nothing to save.
            apply_selectors = [
                render_template(c, variables) for c in action.get("apply_selectors", [])
            ]
            if apply_selectors:
                apply_loc = await find_first_locator(
                    page, apply_selectors, require_visible=True,
                    timeout_ms=int(action.get("apply_timeout_ms", 8000)),
                )
                if apply_loc is not None:
                    await apply_loc.click(timeout=timeout_ms)
                    await page.wait_for_timeout(int(action.get("apply_settle_ms", 1500)))
        if kpis is not None and action.get("kpi"):
            kpis[action["kpi"]] = current
        return
    if action_type == "set_kpi":
        if kpis is not None:
            rendered = render_template(action.get("value", ""), variables)
            if isinstance(rendered, str) and rendered.strip().lower() in ("true", "false"):
                kpis[action["name"]] = rendered.strip().lower() == "true"
            else:
                kpis[action["name"]] = rendered
        return
    raise ValueError(f"Unsupported action type: {action_type}")


def _describe_action(action: Dict[str, Any], variables: Dict[str, Any]) -> str:
    """One-line human summary of an action for the execution log."""
    action_type = action.get("type", "unknown")
    if action_type == "goto":
        return f"goto {render_template(action.get('url', ''), variables)}"
    if action_type == "wait_for_timeout":
        return f"wait {action.get('timeout_ms', 1000)}ms"
    target = ""
    candidates = action.get("selectors") or ([action["selector"]] if action.get("selector") else [])
    if candidates:
        target = str(candidates[0])
    return f"{action_type} {target}".strip()


async def execute_phase(
    *,
    page: Any,
    phase_name: str,
    actions: List[Dict[str, Any]],
    variables: Dict[str, Any],
    step_results: List[Dict[str, Any]],
    screenshot_paths: List[str],
    screenshots_dir: str,
    from_node: str,
    kpis: Optional[Dict[str, Any]] = None,
) -> None:
    start_time = time.time()
    executed_actions: List[Dict[str, Any]] = []
    total = len(actions)
    print(f"▶️  [{phase_name}] phase start ({total} action{'s' if total != 1 else ''})", flush=True)
    try:
        for idx, action in enumerate(actions, start=1):
            print(f"   → [{phase_name}] {idx}/{total} {_describe_action(action, variables)}", flush=True)
            await execute_action(page, action, variables, kpis)
            executed_actions.append(
                {
                    "command": action.get("type", "unknown"),
                    "params": {k: v for k, v in action.items() if k != "type"},
                }
            )
        print(f"✅ [{phase_name}] phase ok ({time.time() - start_time:.1f}s)", flush=True)
    except Exception as phase_exc:
        # Loud, located failure: the last "→" line above shows the exact action
        # that was running when the browser/page died
        print(f"❌ [{phase_name}] phase FAILED after {time.time() - start_time:.1f}s: "
              f"{type(phase_exc).__name__}: {phase_exc}", flush=True)
        screenshot_path = await capture_local_debug_screenshot(
            page=page,
            screenshots_dir=screenshots_dir,
            screenshot_paths=screenshot_paths,
            name=f"{phase_name}_failed",
        )
        append_local_debug_step_result(
            step_results=step_results,
            message=phase_name.replace("_", " ").title(),
            success=False,
            from_node=from_node,
            to_node=phase_name,
            actions=executed_actions,
            screenshot_path=screenshot_path,
            step_duration_ms=int((time.time() - start_time) * 1000),
        )
        raise

    screenshot_path = await capture_local_debug_screenshot(
        page=page,
        screenshots_dir=screenshots_dir,
        screenshot_paths=screenshot_paths,
        name=phase_name,
    )
    append_local_debug_step_result(
        step_results=step_results,
        message=phase_name.replace("_", " ").title(),
        success=True,
        from_node=from_node,
        to_node=phase_name,
        actions=executed_actions,
        screenshot_path=screenshot_path,
        step_duration_ms=int((time.time() - start_time) * 1000),
    )


async def extract_scope_lines(page: Any, extractor: Dict[str, Any]) -> List[str]:
    payload = await page.evaluate(
        """
        (cfg) => {
          const normalize = (s) => (s || '').replace(/\\s+/g, ' ').trim();
          const headingNeedle = normalize(cfg.scope_heading_text || '').toLowerCase();
          let scope = null;

          if (cfg.scope_selector) {
            scope = document.querySelector(cfg.scope_selector);
          }

          if (!scope && headingNeedle) {
            const all = Array.from(document.querySelectorAll('body *'));
            const heading = all.find((el) => normalize(el.innerText).toLowerCase() === headingNeedle || normalize(el.textContent).toLowerCase() === headingNeedle);
            if (heading) {
              scope = cfg.scope_ancestor_selector ? heading.closest(cfg.scope_ancestor_selector) : null;
              if (!scope) {
                scope = heading.closest('section,article,[role="region"],main,div') || heading.parentElement || heading;
              }
            }
          }

          if (!scope) {
            scope = document.querySelector('main') || document.body;
          }

          const lines = (scope.innerText || '')
            .split('\\n')
            .map((line) => normalize(line))
            .filter(Boolean);

          return { lines };
        }
        """,
        extractor,
    )
    return payload.get("lines", []) if isinstance(payload, dict) else []


def extract_pairs_from_lines(
    *,
    lines: List[str],
    extractor: Dict[str, Any],
    transform_value: Callable[[Any, str], Any],
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    ignore_lines = {normalize_label(line) for line in extractor.get("ignore_lines", [])}
    filtered_lines = [line for line in lines if normalize_label(line) not in ignore_lines]

    raw_pairs: Dict[str, str] = {}
    i = 0
    while i + 1 < len(filtered_lines):
        raw_pairs[filtered_lines[i]] = filtered_lines[i + 1]
        i += 2

    extracted: Dict[str, Any] = {}
    for target_field, field_config in extractor.get("fields", {}).items():
        labels = field_config.get("labels", [])
        transform = field_config.get("transform", "identity")
        matched_value = None
        for raw_label, raw_value in raw_pairs.items():
            if normalize_label(raw_label) in {normalize_label(label) for label in labels}:
                matched_value = transform_value(raw_value, transform)
                break
        if matched_value not in (None, ""):
            extracted[target_field] = matched_value

    return extracted, raw_pairs


async def extract_selector_fields(
    *,
    page: Any,
    extractor: Dict[str, Any],
    transform_value: Callable[[Any, str], Any],
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    extracted: Dict[str, Any] = {}
    raw_pairs: Dict[str, str] = {}

    for target_field, field_config in extractor.get("fields", {}).items():
        selector_list = list(field_config.get("selectors", []))
        if field_config.get("selector"):
            selector_list.append(field_config["selector"])
        timeout_ms = int(field_config.get("timeout_ms", extractor.get("timeout_ms", 10000)))
        locator = await find_first_locator(
            page,
            selector_list,
            require_visible=False,
            timeout_ms=timeout_ms,
        )
        if locator is None:
            continue

        wait_for_non_empty = bool(field_config.get("wait_for_non_empty", True))
        deadline = time.time() + (timeout_ms / 1000.0)
        raw_value = ""
        while time.time() < deadline:
            text_content = await locator.text_content()
            raw_value = (text_content or "").strip()
            if raw_value or not wait_for_non_empty:
                break
            await page.wait_for_timeout(250)

        if not raw_value:
            continue

        extracted[target_field] = transform_value(raw_value, field_config.get("transform", "identity"))
        raw_pairs[target_field] = raw_value

    return extracted, raw_pairs


async def run_extractors(
    *,
    page: Any,
    profile: Dict[str, Any],
    step_results: List[Dict[str, Any]],
    screenshot_paths: List[str],
    screenshots_dir: str,
    from_node: str,
    transform_value: Callable[[Any, str], Any],
) -> Dict[str, Any]:
    extracted: Dict[str, Any] = dict(profile.get("static_metadata", {}))
    raw_sections: Dict[str, Any] = {}

    extractors = profile.get("extractors", [])
    total = len(extractors)
    print(f"▶️  [extract] phase start ({total} section{'s' if total != 1 else ''})", flush=True)
    for idx, extractor in enumerate(extractors, start=1):
        start_time = time.time()
        section = extractor.get("name", "section")
        extractor_type = extractor.get("type", "label_value_pairs")
        print(f"   → [extract] {idx}/{total} {section} ({extractor_type})", flush=True)
        try:
            if extractor_type == "selector_value_map":
                section_data, raw_pairs = await extract_selector_fields(
                    page=page,
                    extractor=extractor,
                    transform_value=transform_value,
                )
            else:
                section_data, raw_pairs = extract_pairs_from_lines(
                    lines=await extract_scope_lines(page, extractor),
                    extractor=extractor,
                    transform_value=transform_value,
                )
        except Exception as extract_exc:
            print(f"❌ [extract] section '{section}' FAILED after {time.time() - start_time:.1f}s: "
                  f"{type(extract_exc).__name__}: {extract_exc}", flush=True)
            raise
        extracted.update(section_data)
        raw_sections[extractor.get("name", "section")] = raw_pairs
        screenshot_path = await capture_local_debug_screenshot(
            page=page,
            screenshots_dir=screenshots_dir,
            screenshot_paths=screenshot_paths,
            name=f"extract_{extractor.get('name', 'section')}",
        )
        append_local_debug_step_result(
            step_results=step_results,
            message=f"Extract {extractor.get('name', 'section').replace('_', ' ')}",
            success=bool(section_data),
            from_node=from_node,
            to_node=extractor.get("name", "section"),
            actions=[{"command": "extract_profile_section", "params": {"extractor": extractor.get("name", "section")}}],
            verifications=[{"success": bool(section_data), "label": "Section parsed", "details": {"fields": list(section_data.keys())}}],
            screenshot_path=screenshot_path,
            step_duration_ms=int((time.time() - start_time) * 1000),
        )

    apply_derived_fields(extracted, profile.get("derived_fields", []))
    print(f"✅ [extract] phase ok ({len(extracted)} field(s))", flush=True)
    return {"extracted": extracted, "raw_sections": raw_sections}
