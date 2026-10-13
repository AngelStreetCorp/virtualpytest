"""
Unit tests for parse_events.parse_event_stream. Run with:
    cd /home/jndoye/vpt-task73-atlas-testing-progressive
    python3 -m pytest scripts/ai-smoke/test_parse_events.py -v
or:
    python3 scripts/ai-smoke/test_parse_events.py
(the file is also a runnable smoke-check via `python3 -m unittest`).
"""
from __future__ import annotations

import unittest

from parse_events import (
    ERROR, MESSAGE, SESSION_END, TOOL_CALL,
    parse_event_lines, parse_event_stream,
)


def _event(type_: str, **kwargs) -> str:
    """Helper: build a JSON event line."""
    import json
    return json.dumps({"type": type_, **kwargs}, default=str)


class ParseEventsTests(unittest.TestCase):

    def test_happy_path_tool_call_then_message_then_session_ended(self):
        stream = "\n".join([
            _event(TOOL_CALL, agent="atlas", tool_name="list_devices", tool_params={}),
            _event(TOOL_CALL, agent="atlas", tool_name="list_analytics_sources", tool_params={}),
            _event(MESSAGE, agent="atlas", content="There are 3 devices and 2 sources."),
            _event(SESSION_END, agent="atlas"),
        ])
        r = parse_event_stream(stream)
        self.assertTrue(r.ok, r.why_not_ok())
        self.assertEqual(r.reply, "There are 3 devices and 2 sources.")
        self.assertEqual(r.tool_call_count, 2)
        self.assertEqual(r.tool_names, ["list_devices", "list_analytics_sources"])
        self.assertTrue(r.session_ended)
        self.assertEqual(r.error_events, [])
        self.assertEqual(r.parse_errors, [])

    def test_no_tool_call_fails_smoke(self):
        # BUG-0265 regression: a pure-text answer with no analytics tool
        # call must NOT pass the smoke.
        stream = "\n".join([
            _event(MESSAGE, agent="atlas", content="I don't have analytics tools."),
            _event(SESSION_END, agent="atlas"),
        ])
        r = parse_event_stream(stream)
        self.assertFalse(r.ok)
        self.assertIn("tool_call", r.why_not_ok())
        self.assertEqual(r.tool_call_count, 0)

    def test_error_event_fails_smoke(self):
        stream = "\n".join([
            _event(TOOL_CALL, agent="atlas", tool_name="list_devices", tool_params={}),
            _event(ERROR, agent="atlas", content="asyncio loop conflict"),
            _event(SESSION_END, agent="atlas"),
        ])
        r = parse_event_stream(stream)
        self.assertFalse(r.ok)
        self.assertIn("error event", r.why_not_ok())

    def test_no_session_ended_fails_smoke(self):
        # Timeout case: SESSION_END never arrived.
        stream = "\n".join([
            _event(TOOL_CALL, agent="atlas", tool_name="list_devices", tool_params={}),
            _event(MESSAGE, agent="atlas", content="partial reply"),
        ])
        r = parse_event_stream(stream)
        self.assertFalse(r.ok)
        self.assertIn("session did not end", r.why_not_ok())

    def test_empty_reply_fails_smoke(self):
        stream = "\n".join([
            _event(TOOL_CALL, agent="atlas", tool_name="list_devices", tool_params={}),
            _event(MESSAGE, agent="atlas", content="   "),  # whitespace only
            _event(SESSION_END, agent="atlas"),
        ])
        r = parse_event_stream(stream)
        self.assertFalse(r.ok)
        self.assertIn("no assistant message", r.why_not_ok())

    def test_user_messages_are_skipped(self):
        # The echoed user prompt should not count as the reply.
        stream = "\n".join([
            _event(MESSAGE, agent="user", content="List the available devices."),
            _event(TOOL_CALL, agent="atlas", tool_name="list_devices", tool_params={}),
            _event(MESSAGE, agent="atlas", content="There are 3 devices."),
            _event(SESSION_END, agent="atlas"),
        ])
        r = parse_event_stream(stream)
        self.assertTrue(r.ok, r.why_not_ok())
        self.assertEqual(r.reply, "There are 3 devices.")

    def test_only_last_message_is_the_reply(self):
        # Multi-turn: the first message is an intermediate thought; the
        # last one (right before SESSION_END) is the reply.
        stream = "\n".join([
            _event(TOOL_CALL, agent="atlas", tool_name="list_devices", tool_params={}),
            _event(MESSAGE, agent="atlas", content="Looking up devices..."),
            _event(TOOL_CALL, agent="atlas", tool_name="list_analytics_sources", tool_params={}),
            _event(MESSAGE, agent="atlas", content="3 devices, 2 sources."),
            _event(SESSION_END, agent="atlas"),
        ])
        r = parse_event_stream(stream)
        self.assertTrue(r.ok, r.why_not_ok())
        self.assertEqual(r.reply, "3 devices, 2 sources.")
        self.assertEqual(r.tool_call_count, 2)

    def test_invalid_json_lines_logged_not_fatal(self):
        # atlas_chat.py prints metadata on stderr but if anything leaks to
        # stdout (or a future version adds a banner), the parser must
        # tolerate it.
        stream = "\n".join([
            "[atlas_chat] connected",  # not JSON
            _event(TOOL_CALL, agent="atlas", tool_name="list_devices", tool_params={}),
            "",                          # blank line
            _event(MESSAGE, agent="atlas", content="ok"),
            _event(SESSION_END, agent="atlas"),
        ])
        r = parse_event_stream(stream)
        self.assertTrue(r.ok, r.why_not_ok())
        self.assertEqual(len(r.parse_errors), 1)
        self.assertIn("connected", r.parse_errors[0])

    def test_dict_content_in_message_is_kept_as_string(self):
        stream = "\n".join([
            _event(TOOL_CALL, agent="atlas", tool_name="list_devices", tool_params={}),
            _event(MESSAGE, agent="atlas", content={"text": "wrapped reply"}),
            _event(SESSION_END, agent="atlas"),
        ])
        r = parse_event_stream(stream)
        self.assertTrue(r.ok, r.why_not_ok())
        self.assertIn("wrapped reply", r.reply)

    def test_duplicate_tool_calls_counted_each_time(self):
        # BUG-0266 used to call list_devices 3x in a row; the count is
        # what surfaces that, the unique name list is for the human.
        stream = "\n".join([
            _event(TOOL_CALL, agent="atlas", tool_name="list_devices", tool_params={}),
            _event(TOOL_CALL, agent="atlas", tool_name="list_devices", tool_params={}),
            _event(TOOL_CALL, agent="atlas", tool_name="list_devices", tool_params={}),
            _event(MESSAGE, agent="atlas", content="done"),
            _event(SESSION_END, agent="atlas"),
        ])
        r = parse_event_stream(stream)
        self.assertTrue(r.ok, r.why_not_ok())
        self.assertEqual(r.tool_call_count, 3)
        self.assertEqual(r.tool_names, ["list_devices"])

    def test_parse_event_lines_iterable(self):
        lines = [
            _event(TOOL_CALL, agent="atlas", tool_name="list_devices", tool_params={}),
            _event(MESSAGE, agent="atlas", content="ok"),
            _event(SESSION_END, agent="atlas"),
        ]
        r = parse_event_lines(lines)
        self.assertTrue(r.ok, r.why_not_ok())


if __name__ == "__main__":
    unittest.main(verbosity=2)
