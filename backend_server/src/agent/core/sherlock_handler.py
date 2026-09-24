"""
Sherlock Handler - Script Analysis Background Tasks

Supports two modes:
- direct mode: policy-driven queue processing + direct LLM call + DB update
- legacy mode: build prompt for agent chat loop
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from shared.src.lib.ai.config import get_active_model
from shared.src.lib.utils.ai_utils import call_text_ai
from shared.src.lib.utils.cloudflare_utils import fetch_text_from_storage
from shared.src.lib.utils.supabase_utils import get_supabase_client


CLASSIFICATIONS = {
    "VALID_PASS",
    "VALID_FAIL",
    "BUG",
    "SCRIPT_ISSUE",
    "SYSTEM_ISSUE",
    "EXTERNAL_BLOCK",
}
DISCARD_CLASSIFICATIONS = {"SCRIPT_ISSUE", "SYSTEM_ISSUE"}


class SherlockHandler:
    """Handler for analyzer background tasks."""

    def __init__(self, nickname: str = "Sherlock"):
        self.nickname = nickname
        self.direct_mode = os.getenv("ANALYZER_DIRECT_MODE", "true").lower() in ("1", "true", "yes", "on")
        self.repeat_every_fail = max(2, int(os.getenv("ANALYZER_REPEAT_EVERY_FAIL", "5")))
        self.success_sample_percent = min(100, max(0, int(os.getenv("ANALYZER_SUCCESS_SAMPLE_PERCENT", "10"))))
        self.fail_lookback = max(5, int(os.getenv("ANALYZER_FAIL_LOOKBACK", "20")))
        # Default to the centralized 'text' task model; honour the explicit override.
        self.model = os.getenv("ANALYZER_OPENROUTER_MODEL") or get_active_model(task="text")
        self._supabase = None

    def _get_supabase(self):
        if self._supabase is None:
            self._supabase = get_supabase_client()
        return self._supabase

    def _normalize_error_signature(self, value: str) -> str:
        if not value:
            return "empty-error"
        txt = value.lower()
        txt = re.sub(r"[0-9a-f]{8,}", "<hex>", txt)
        txt = re.sub(r"\d+", "<n>", txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        return txt[:240]

    def _load_script_result(self, script_result_id: str) -> Optional[Dict[str, Any]]:
        try:
            supabase = self._get_supabase()
            result = supabase.table("script_results").select("*").eq("id", script_result_id).single().execute()
            return result.data if result and result.data else None
        except Exception as e:
            print(f"[{self.nickname}] ⚠️ Failed to load script result {script_result_id}: {e}")
            return None

    def _mark_strategy_skip(self, script_result_id: str, reason: str) -> None:
        try:
            supabase = self._get_supabase()
            supabase.table("script_results").update({
                "checked": True,
                "check_type": "ai_strategy_skip",
                "discard": False,
                "discard_comment": f"[STRATEGY_SKIP] {reason[:300]}",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", script_result_id).execute()
        except Exception as e:
            print(f"[{self.nickname}] ⚠️ Failed to mark strategy skip for {script_result_id}: {e}")

    def _mark_ai_error(self, script_result_id: str, error: str) -> None:
        try:
            supabase = self._get_supabase()
            supabase.table("script_results").update({
                "checked": True,
                "check_type": "ai_error",
                "discard": False,
                "discard_comment": f"[AI_ERROR] {error[:300]}",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", script_result_id).execute()
        except Exception as e:
            print(f"[{self.nickname}] ⚠️ Failed to mark ai_error for {script_result_id}: {e}")

    def _should_analyze_by_policy(self, script_result_id: str, record: Dict[str, Any]) -> (bool, str):
        success = bool(record.get("success"))
        script_name = record.get("script_name", "")
        device_name = record.get("device_name", "")
        team_id = record.get("team_id", "")
        current_sig = self._normalize_error_signature(record.get("error_msg") or "")

        # Success sampling: deterministic by result id.
        if success:
            bucket = int(hashlib.md5(script_result_id.encode("utf-8"), usedforsecurity=False).hexdigest(), 16) % 100
            if bucket < self.success_sample_percent:
                return True, f"success sampled in ({bucket} < {self.success_sample_percent})"
            return False, f"success sampled out ({bucket} >= {self.success_sample_percent})"

        # Failures: analyze first occurrence, then every Xth repeated same signature.
        try:
            supabase = self._get_supabase()
            history = (
                supabase.table("script_results")
                .select("id,success,error_msg")
                .eq("team_id", team_id)
                .eq("script_name", script_name)
                .eq("device_name", device_name)
                .order("created_at", desc=True)
                .limit(self.fail_lookback)
                .execute()
            )
            rows = history.data or []
        except Exception as e:
            # Fallback safe path: analyze if policy lookup fails.
            return True, f"policy fallback analyze (history lookup failed: {e})"

        consecutive_same_before = 0
        for row in rows:
            if row.get("id") == script_result_id:
                continue
            if row.get("success"):
                break
            row_sig = self._normalize_error_signature(row.get("error_msg") or "")
            if row_sig != current_sig:
                break
            consecutive_same_before += 1

        occurrence = consecutive_same_before + 1
        if occurrence == 1 or (occurrence % self.repeat_every_fail == 0):
            return True, f"failure occurrence {occurrence} analyzed (repeat_every={self.repeat_every_fail})"
        return False, f"failure occurrence {occurrence} skipped (analyze every {self.repeat_every_fail})"

    def should_process_with_ai(self, task_id: str, task_data: Dict[str, Any]) -> bool:
        """Policy gate called by manager before analysis."""
        record = self._load_script_result(task_id)
        if not record:
            return False
        should_analyze, reason = self._should_analyze_by_policy(task_id, record)
        if not should_analyze:
            self._mark_strategy_skip(task_id, reason)
            print(f"[{self.nickname}] ⏭️ Skip {task_id}: {reason}")
            return False
        print(f"[{self.nickname}] ▶️ Analyze {task_id}: {reason}")
        return True

    def _fetch_markdown(self, record: Dict[str, Any]) -> str:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        md_path = metadata.get("verification_review_r2_path", "")
        md_url = metadata.get("verification_review_r2_url", "")
        md_source = md_path or md_url
        if not md_source:
            return ""

        fetch_result = fetch_text_from_storage(md_source)
        if fetch_result.get("success"):
            return fetch_result.get("text") or ""

        print(
            f"[{self.nickname}] ⚠️ Failed to fetch verification markdown "
            f"(source={md_source}, resolved={fetch_result.get('remote_path')}): "
            f"{fetch_result.get('error')}"
        )
        if md_path and md_url:
            fallback_result = fetch_text_from_storage(md_url)
            if fallback_result.get("success"):
                return fallback_result.get("text") or ""
            print(
                f"[{self.nickname}] ⚠️ Fallback markdown fetch failed "
                f"(source={md_url}, resolved={fallback_result.get('remote_path')}): "
                f"{fallback_result.get('error')}"
            )
            return ""
        return ""

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass

        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _classify_with_llm(self, record: Dict[str, Any], review_markdown: str) -> Dict[str, Any]:
        success_text = "PASSED" if record.get("success") else "FAILED"
        prompt = f"""You are classifying automated test executions for false positives.
Return ONLY JSON:
{{
  "classification": "VALID_PASS|VALID_FAIL|BUG|SCRIPT_ISSUE|SYSTEM_ISSUE|EXTERNAL_BLOCK",
  "discard": true_or_false,
  "explanation": "max 240 chars, concrete reason from evidence"
}}

Rules:
- discard=true only for SCRIPT_ISSUE or SYSTEM_ISSUE
- discard=false for VALID_PASS, VALID_FAIL, BUG, EXTERNAL_BLOCK
- BUG means report says fail but visual/log evidence suggests real element/state exists

Execution:
- script_name: {record.get("script_name")}
- result: {success_text}
- error: {record.get("error_msg") or "None"}
- execution_time_ms: {record.get("execution_time_ms")}

Verification review markdown:
{(review_markdown or "No markdown available")[:16000]}
"""
        # 300 was enough for a non-reasoning model. Reasoning models (MiniMax-M2.7,
        # Claude with extended thinking) spend the budget on thinking blocks first and
        # return zero text blocks at 300 — the call then fails as "empty content".
        ai_result = call_text_ai(
            prompt=prompt,
            max_tokens=int(os.getenv("ANALYZER_MAX_TOKENS", "1500")),
            temperature=0.0,
            model=self.model,
        )
        if not ai_result.get("success"):
            raise RuntimeError(ai_result.get("error", "AI call failed"))

        parsed = self._extract_json(ai_result.get("content", ""))
        if not parsed:
            raise RuntimeError("AI output was not valid JSON")

        classification = str(parsed.get("classification", "")).strip().upper()
        if classification not in CLASSIFICATIONS:
            raise RuntimeError(f"Invalid classification: {classification}")

        explanation = str(parsed.get("explanation", "")).strip()[:240] or "No explanation provided"
        discard = bool(parsed.get("discard"))
        expected_discard = classification in DISCARD_CLASSIFICATIONS
        if discard != expected_discard:
            discard = expected_discard

        return {
            "classification": classification,
            "discard": discard,
            "explanation": explanation,
        }

    def _save_analysis(self, script_result_id: str, analysis: Dict[str, Any]) -> None:
        classification = analysis["classification"]
        discard = bool(analysis["discard"])
        explanation = analysis["explanation"]
        discard_comment = f"[{classification}] {explanation}"
        supabase = self._get_supabase()
        supabase.table("script_results").update({
            "checked": True,
            "check_type": "ai_auto_openrouter",
            "discard": discard,
            "discard_comment": discard_comment,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", script_result_id).execute()

    def process_task_direct(self, task_type: str, task_id: str, task_data: Dict[str, Any]) -> bool:
        """
        Direct processing path used by manager.
        Returns True when task is handled (success or failure persisted).
        """
        if not self.direct_mode:
            return False
        if task_type != "script":
            return False

        record = self._load_script_result(task_id)
        if not record:
            return True

        try:
            review_markdown = self._fetch_markdown(record)
            analysis = self._classify_with_llm(record, review_markdown)
            self._save_analysis(task_id, analysis)
            print(
                f"[{self.nickname}] ✅ direct analysis saved: {task_id} "
                f"class={analysis['classification']} discard={analysis['discard']}"
            )
        except Exception as e:
            self._mark_ai_error(task_id, str(e))
            print(f"[{self.nickname}] ❌ direct analysis failed for {task_id}: {e}")

        return True

    def build_task_message(self, task_type: str, task_id: str, task_data: Dict[str, Any]) -> str:
        """Legacy prompt path for non-direct mode/fallback."""
        if task_type == 'script':
            script_name = task_data.get('script_name', 'Unknown')
            success = task_data.get('success', False)
            error_msg = task_data.get('error_msg', 'None')
            execution_time_ms = task_data.get('execution_time_ms', 0)
            report_url = task_data.get('html_report_r2_url', '')
            logs_url = task_data.get('logs_url', '')
            verification_review_url = task_data.get('verification_review_url', '')
            metadata = task_data.get('metadata', {}) if isinstance(task_data.get('metadata'), dict) else {}
            if not verification_review_url:
                verification_review_url = metadata.get('verification_review_r2_url', '')

            msg = f"""Analyze this script execution for false positive detection:

SCRIPT: {script_name}
SCRIPT_RESULT_ID: {task_id}
RESULT: {'PASSED' if success else 'FAILED'}
ERROR: {error_msg}
DURATION: {execution_time_ms}ms
"""

            if verification_review_url:
                msg += f"\n\nVerification Review URL: {verification_review_url}"
            if report_url:
                msg += f"\nReport URL: {report_url}"
            if logs_url:
                msg += f"\nLogs URL: {logs_url}"

            msg += f"""

Based on the report above, classify this execution and call:
update_execution_analysis(script_result_id='{task_id}', discard=<true/false>, classification=<CLASSIFICATION>, explanation=<brief explanation>)

CLASSIFICATIONS:
- VALID_PASS: Test passed, legitimate success (discard=false)
- VALID_FAIL: Test failed, real bug detected (discard=false)
- BUG: Screenshot shows element BUT error says "not found" (discard=false)
- SCRIPT_ISSUE: Test automation problem - bad selector/timing/expected value (discard=true)
- SYSTEM_ISSUE: Infrastructure problem - black screen/no signal/device disconnected (discard=true)
- EXTERNAL_BLOCK: External service or policy prevented the test, such as CAPTCHA or rate limiting (discard=false)"""

            return msg

        return f"Unknown task type: {task_type}"

    def send_to_slack(self, task_type: str, task_id: str, task_data: Dict[str, Any], result: str, success: bool = True):
        """Send analysis result to Slack #sherlock channel (legacy path)."""
        try:
            try:
                from backend_server.src.integrations.agent_slack_hook import send_to_slack_channel
                slack_available = True
            except ImportError:
                slack_available = False
                return

            if not slack_available:
                return

            script_name = task_data.get('script_name', 'Unknown')
            script_success = task_data.get('success', False)
            error_msg = task_data.get('error_msg', 'None')

            status_emoji = "✅" if success else "❌"
            result_emoji = "🟢" if script_success else "🔴"

            slack_message = f"""
{status_emoji} *{self.nickname} Analysis Complete*

*Script*: `{script_name}`
*Result*: {result_emoji} {'PASSED' if script_success else 'FAILED'}
*Error*: {error_msg}

*Analysis*:
```
{result[:500]}...
```

*Task ID*: `{task_id}`
"""

            send_to_slack_channel(
                channel='#sherlock',
                message=slack_message,
                agent_name=self.nickname
            )
            print(f"[{self.nickname}] 📬 Sent result to Slack #sherlock")

        except Exception as e:
            print(f"[{self.nickname}] ⚠️  Failed to send to Slack: {e}")
