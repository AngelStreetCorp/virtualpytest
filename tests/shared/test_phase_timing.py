"""
tests/shared/test_phase_timing.py -- the execution log is a timeline.

A testcase's uploaded execution.txt had no timestamps and showed nothing of what ran inside a
block, so 65-70 s per TodoMVC test between steps could not be attributed from the log. Two
pieces fix the logging, without changing any result:

  * StdoutCapture (ScriptExecutionContext.start_stdout_capture) stamps every captured line with
    its UTC wall clock and the seconds since the context started;
  * '⏱ <phase> <ms> ms' lines, printed when a phase ends, pass through a block's stdout
    redirect (PhaseLinePassthrough) so they reach that capture.
"""
import io
import os
import re
import sys

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.src.lib.utils import phase_timing  # noqa: E402
from shared.src.lib.utils.phase_timing import (  # noqa: E402
    MARKER,
    PhaseLinePassthrough,
    TimestampedLineBuffer,
    log_duration,
    stamp_lines,
    wall_clock_prefix,
)

PREFIX_RE = re.compile(r'^\d{2}:\d{2}:\d{2}\.\d{3}Z \+ *\d+\.\d{3} ')


# ------------------------------------------------------------------------------------------
# stamp_lines / TimestampedLineBuffer
# ------------------------------------------------------------------------------------------

def test_print_style_writes_stamp_each_line_once():
    """print() writes the text and the newline separately: one prefix per line, not per write."""
    at_start = True
    out = []
    for piece in ['first', '\n', 'second', ' continued', '\n']:
        stamped, at_start = stamp_lines(piece, at_start, 'P ')
        out.append(stamped)
    assert ''.join(out) == 'P first\nP second continued\n'
    assert at_start is True


def test_multi_line_text_stamps_every_line_and_leaves_blank_lines_alone():
    stamped, at_start = stamp_lines('a\n\nb\nc', True, 'P ')
    assert stamped == 'P a\n\nP b\nP c'
    assert at_start is False  # 'c' has not ended its line yet


def test_a_continuation_is_not_stamped():
    stamped, at_start = stamp_lines('rest of line\nnext\n', False, 'P ')
    assert stamped == 'rest of line\nP next\n'
    assert at_start is True


def test_wall_clock_prefix_is_utc_with_offset_from_origin():
    # 2026-09-29 14:39:08.123 UTC
    now = 1790692748.123
    assert wall_clock_prefix(now, now - 22.5) == '14:39:08.123Z +' + f"{22.5:7.3f}" + ' '
    assert wall_clock_prefix(now, None) == '14:39:08.123Z '


def test_timestamped_buffer_appends_stamped_text(monkeypatch):
    monkeypatch.setattr(phase_timing.time, 'time', lambda: 1790692748.5)
    sink = []
    buf = TimestampedLineBuffer(sink, origin=1790692748.0)
    buf.append('hello')
    buf.append('\n')
    buf.append('')
    assert ''.join(sink) == '14:39:08.500Z +  0.500 hello\n'


# ------------------------------------------------------------------------------------------
# ScriptExecutionContext.start_stdout_capture -- the real capture behind execution.txt
# ------------------------------------------------------------------------------------------

def test_stdout_capture_stamps_execution_log_but_not_the_journal():
    from shared.src.lib.executors.script_executor import ScriptExecutionContext

    journal = io.StringIO()
    saved = sys.stdout
    sys.stdout = journal
    try:
        ctx = ScriptExecutionContext('timing-test')
        ctx.start_stdout_capture()
        print('[@x] one')
        print('[@x] two', end='')
        print(' still two')
        ctx.stop_stdout_capture()
    finally:
        sys.stdout = saved

    # The journal (original stream) gets the text unchanged.
    assert journal.getvalue() == '[@x] one\n[@x] two still two\n'

    lines = ctx.get_captured_stdout().splitlines()
    assert lines[0].startswith('[@stdout_capture] line prefix = UTC wall clock')
    body = lines[1:]
    assert len(body) == 2
    for line in body:
        assert PREFIX_RE.match(line), line
    assert body[0].endswith('[@x] one')
    assert body[1].endswith('[@x] two still two')


# ------------------------------------------------------------------------------------------
# PhaseLinePassthrough -- a block's stdout redirect
# ------------------------------------------------------------------------------------------

def test_block_buffer_keeps_everything_and_only_timing_lines_pass_through():
    buffer, outer = io.StringIO(), io.StringIO()
    tee = PhaseLinePassthrough(buffer, outer)
    for piece in [f'{MARKER} nav.probe', ' 20012 ms target=with-todo', '\n',
                  '[@nav] Target is 1 step away\n',
                  f'  {MARKER} indented 5 ms\n',
                  f'not a timing line {MARKER} 5 ms\n',
                  'partial', f' {MARKER} still not\n',
                  f'{MARKER} unterminated 1 ms']:
        tee.write(piece)

    assert buffer.getvalue() == (
        f'{MARKER} nav.probe 20012 ms target=with-todo\n'
        '[@nav] Target is 1 step away\n'
        f'  {MARKER} indented 5 ms\n'
        f'not a timing line {MARKER} 5 ms\n'
        f'partial {MARKER} still not\n'
        f'{MARKER} unterminated 1 ms')
    assert tee.getvalue() == buffer.getvalue()
    # Only complete lines that start (after blanks) with the marker; the unterminated one waits.
    assert outer.getvalue() == (f'{MARKER} nav.probe 20012 ms target=with-todo\n'
                                f'  {MARKER} indented 5 ms\n')


def test_passthrough_failure_never_breaks_the_block():
    class Broken(io.StringIO):
        def write(self, _):
            raise OSError('journal gone')

    buffer = io.StringIO()
    tee = PhaseLinePassthrough(buffer, Broken())
    assert tee.write(f'{MARKER} x 1 ms\n') == len(f'{MARKER} x 1 ms\n')
    tee.flush()
    assert buffer.getvalue() == f'{MARKER} x 1 ms\n'


def test_log_duration_line_shape(capsys):
    assert log_duration('fin.video_extract', 5123.6, 'duration_s=104.6') == 5124
    assert capsys.readouterr().out == f'{MARKER} fin.video_extract 5124 ms duration_s=104.6\n'
