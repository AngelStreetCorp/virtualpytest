"""
parse_events — pure parser for the JSON event stream emitted by
`scripts/atlas_chat.py --json`. Used by run_smoke.py and by the unit test
suite. No I/O, no network, no Atlas dependency: feed it a string of
newline-separated JSON events, get a SmokeResult.

This module exists so the assertion logic can be unit-tested without
spinning up a real Atlas session (the smoke is < 60 s end-to-end, but a
test should not have to wait for a deployed server).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable, List, Optional


# Event types emitted by Atlas on the /agent Socket.IO namespace. Mirrored
# from backend_server/src/agent/core/message_types.py: see EventType.* there.
# We hard-code the few we care about rather than import from the server so
# this module is standalone.
TOOL_CALL   = "tool_call"
MESSAGE     = "message"
SESSION_END = "session_ended"
ERROR       = "error"


@dataclass
class SmokeResult:
    """Outcome of parsing a single atlas_chat.py --json run."""
    reply: str = ""                       # last assistant message content (the final reply)
    tool_names: List[str] = field(default_factory=list)   # unique tool names, in call order
    tool_call_count: int = 0              # total tool_call events (duplicates counted)
    error_events: List[str] = field(default_factory=list)  # type=="error" event contents
    session_ended: bool = False           # type=="session_ended" was seen
    parse_errors: List[str] = field(default_factory=list)  # lines that weren't valid JSON
    # The last message we saw before SESSION_END (or the empty string if
    # none). `reply` and this are usually the same; we keep them separate
    # so the smoke can distinguish "atlas never sent a message" from
    # "atlas sent a message and then errored".
    last_assistant_message: str = ""

    @property
    def ok(self) -> bool:
        """The smoke passes iff we saw a non-empty reply and at least one tool call."""
        return (
            self.session_ended
            and not self.error_events
            and bool(self.reply.strip())
            and self.tool_call_count >= 1
        )

    def why_not_ok(self) -> str:
        if not self.session_ended:
            return "session did not end cleanly (timeout or socket drop)"
        if self.error_events:
            return f"{len(self.error_events)} error event(s); first: {self.error_events[0][:200]}"
        if not self.reply.strip():
            return "no assistant message with non-empty content"
        if self.tool_call_count < 1:
            return "no tool_call events (the prompt did not exercise the tool router)"
        return "ok"


def parse_event_stream(text: str) -> SmokeResult:
    """Parse the stdout of `atlas_chat.py --json` into a SmokeResult.

    Tolerant of:
      * non-JSON lines (logged into parse_errors, the rest still parsed)
      * lines that are valid JSON but not the expected event shape
      * events without a 'type' field
    """
    result = SmokeResult()
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError as e:
            # Quote the offending content (truncated) plus the JSON error
            # so a human can see at a glance which line failed and why.
            preview = stripped[:120] + ("…" if len(stripped) > 120 else "")
            result.parse_errors.append(f"line {lineno}: {e.msg} — {preview!r}")
            continue
        if not isinstance(event, dict):
            result.parse_errors.append(f"line {lineno}: non-object event: {type(event).__name__}")
            continue
        etype = event.get("type", "")
        if etype == TOOL_CALL:
            result.tool_call_count += 1
            name = event.get("tool_name")
            if name and name not in result.tool_names:
                result.tool_names.append(name)
        elif etype == MESSAGE:
            agent = event.get("agent", "")
            # Skip messages from the "user" agent — those are echoes of the
            # prompt. The final assistant reply is the last "message" with
            # non-empty content from a non-user agent.
            if agent == "user":
                continue
            content = event.get("content") or ""
            if isinstance(content, (dict, list)):
                content = json.dumps(content, default=str)
            content = str(content)
            if content.strip():
                result.last_assistant_message = content
        elif etype == SESSION_END:
            result.session_ended = True
            # Atlas emits the final assistant message BEFORE session_ended.
            # Pin the reply to the last one we saw.
            result.reply = result.last_assistant_message
        elif etype == ERROR:
            content = event.get("content") or ""
            if isinstance(content, (dict, list)):
                content = json.dumps(content, default=str)
            result.error_events.append(str(content))
    return result


def parse_event_lines(lines: Iterable[str]) -> SmokeResult:
    """Same as parse_event_stream but takes an iterable of lines (for tests)."""
    return parse_event_stream("\n".join(lines))
