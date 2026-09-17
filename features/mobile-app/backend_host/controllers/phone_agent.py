"""
features/mobile-app/backend_host/controllers/phone_agent.py — PhoneAgentRemoteController.

Mirrors AndroidMobileRemoteController (backend_host/src/controllers/remote/android_mobile.py)
method-for-method — same return shapes, same execute_command names — so
host_remote_routes.py and the AndroidMobileRemote frontend panel work unchanged
against a paired phone (docs/tasks/TASK-17-mobile-app-phone-agent.md §1.5). Every
operation is an RPC to the phone over Socket.IO (bridge.rpc); there is no ADB, so
no CONTROLLER_VERIFICATION_MAP entry either (see shared/src/lib/config/device_capabilities.py).
"""
import base64
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend_host.src.controllers.base_controller import RemoteControllerInterface
from backend_host.src.controllers.remote.android_mobile import AndroidMobileRemoteController
from backend_host.src.lib.utils.adb_utils import AndroidElement, AndroidApp

from shared.src.lib.utils import ui_dump_capture
from shared.src.lib.utils.ui_dump_capture import get_ui_dump_count, record_ui_dump

from ...lib import protocol  # controllers/ is one level deeper than backend_host/

_BOUNDS_RE = re.compile(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]')


# How long a UI dump may be reused by the find_* helpers. Long enough that the lookups behind
# one click share a dump, short enough that a screen which has moved on is read again.
FIND_CACHE_S = 2.0
# An app launching answers with no nodes for a moment; how hard to try before believing the
# screen really is empty.
EMPTY_DUMP_RETRIES = 4
EMPTY_DUMP_WAIT_S = 0.8
# The dump trace file rolls once past this, so a long-running host keeps at most two.
TRACE_MAX_BYTES = 2_000_000


class PhoneAgentRemoteController(RemoteControllerInterface):
    """Remote controller for a phone paired through features/mobile-app (bridge.rpc),
    not ADB. Same public surface as AndroidMobileRemoteController (TASK-17 §1.5)."""

    def __init__(self, device_id: str, device_name: str = 'Phone', bridge=None, **_ignored):
        super().__init__(device_name, protocol.REMOTE_IMPLEMENTATION)
        self.device_id = device_id
        self.bridge = bridge
        self.last_ui_elements: List[AndroidElement] = []
        self.last_dump_time = 0.0
        self.last_error: Optional[str] = None
        # What the last click actually landed on. A selector is a search term, not an id, so
        # the run log and the report have to say which of the matching nodes was tapped —
        # otherwise "clicked ' seconds'" reads the same whether it hit a video or an ad.
        self.last_click_label: Optional[str] = None
        # Where the host's cumulative dump trace lives, set by the last dump.
        self.last_trace_path: Optional[str] = None
        self.device_resolution: Optional[Dict[str, int]] = None
        # The controller object exists whether or not the phone is currently
        # streaming; get_status()/get_slot reports the real link state.
        self.is_connected = True

    def get_connected_device_name(self) -> str:
        """What the paired phone calls itself, e.g. "samsung SM-G998B".

        Mirrors what PhoneBridge does to the device inside vpt-host on pairing; this is the
        same answer for a process that has no bridge of its own, so a script's results and its
        report name the phone rather than the slot it happens to sit in.

        **Asked of the phone, not of the host's cached slot** — and that is deliberate twice
        over. The phone's answer is current rather than whatever it said when it paired, and
        the round trip is the first thing in a run that the phone hears from us, so its
        "under test" badge comes up while the controllers are still being built instead of
        whenever the first navigation action happens to land. On this tree that is the
        difference between a few seconds and half a minute of a phone sitting there looking
        idle while a run is plainly under way.

        Falls back to the slot summary, which is what answers when the phone is not connected —
        the host replies to that immediately, so an offline phone costs no waiting here.
        """
        if not self.bridge:
            return ''
        ack = self.bridge.rpc(self.device_id, protocol.CMD_DEVICE_INFO, {})
        if ack.get('ok'):
            info = ack.get('result') or {}
            name = f"{info.get('manufacturer', '')} {info.get('model', '')}".strip()
            if name:
                return name

        slot = self.bridge.get_slot(self.device_id)
        phone = getattr(slot, 'phone', None) if slot else None
        if not isinstance(phone, dict):
            return ''
        return f"{phone.get('manufacturer', '')} {phone.get('model', '')}".strip()

    @staticmethod
    def get_remote_config() -> Dict[str, Any]:
        # Genuinely the same JSON the android_mobile panel loads (same tap/dump/
        # apps surface, same frontend layout) — delegate instead of duplicating it.
        return AndroidMobileRemoteController.get_remote_config()

    def connect(self) -> bool:
        self.is_connected = True
        return True

    def disconnect(self) -> bool:
        self.is_connected = False
        return True

    @staticmethod
    def _with_run_label(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Tell the phone which script is driving it, so its badge can say so.

        Carried inside `params` rather than as a new field on the cmd envelope: the payload
        already passes through two bridges and a REST route untouched, and a name that only
        the overlay reads does not justify a change to all four. `_run` is the reserved
        prefix — the agent reads it and no command treats it as an argument.

        VPT_SCRIPT_REF is set by ScriptExecutor on the subprocess it spawns, so it is present
        exactly when a script is driving and absent when the remote panel is.
        """
        run = os.getenv('VPT_SCRIPT_REF', '').strip()
        if not run:
            return params or {}
        merged = dict(params or {})
        merged.setdefault('_run', run)
        return merged

    def _rpc(self, name: str, params: Optional[Dict[str, Any]] = None,
             timeout: Optional[float] = None) -> Dict[str, Any]:
        if not self.bridge:
            self.last_error = 'no bridge configured for this controller'
            return {'ok': False, 'error': self.last_error}
        params = self._with_run_label(params)
        ack = self.bridge.rpc(self.device_id, name, params, timeout)
        # Keep the phone's own reason for saying no. Without this every refused command
        # surfaced as "Action failed (no error details from controller)", which is the same
        # message whether the phone is unreachable or its accessibility service is simply
        # switched off — the one thing the operator can actually fix.
        self.last_error = None if ack.get('ok') else (ack.get('error') or f"{name} failed")
        return ack

    # ---- input ----------------------------------------------------------

    def press_key(self, key: str) -> bool:
        agent_key = protocol.adb_key_to_agent_key(key)
        if not agent_key:
            print(f"Remote[{self.device_type.upper()}]: unknown key '{key}' - phone cannot press it")
            return False
        ack = self._rpc(protocol.CMD_KEY, {'key': agent_key})
        return bool(ack.get('ok'))

    def input_text(self, text: str) -> bool:
        ack = self._rpc(protocol.CMD_TEXT, {'text': text})
        return bool(ack.get('ok'))

    def launch_app(self, package_name: str, reset: bool = False) -> bool:
        """Bring an app to the front; with `reset`, at its entry point rather than where it was.

        Worth knowing before writing a tree: `close_app` on a phone can only press HOME —
        unrooted Android has no force-stop API — so close-then-launch resumes the app exactly
        where it was. On YouTube that is the watch page, not the feed. `reset=True` clears the
        app's task so it starts fresh, which is what "from the app's home screen" actually
        needs. Off by default, and an agent older than 1.0.38 ignores it and launches as before.
        """
        params = {'package': package_name}
        if reset:
            params['reset'] = True
        ack = self._rpc(protocol.CMD_LAUNCH_APP, params)
        return bool(ack.get('ok'))

    def close_app(self, package_name: str) -> bool:
        ack = self._rpc(protocol.CMD_CLOSE_APP, {'package': package_name})
        return bool(ack.get('ok'))

    def tap_coordinates(self, x: int, y: int) -> bool:
        ack = self._rpc(protocol.CMD_TAP, {'x': int(x), 'y': int(y)})
        return bool(ack.get('ok'))

    def swipe(self, from_x: int, from_y: int, to_x: int, to_y: int, duration: int = 300) -> bool:
        ack = self._rpc(protocol.CMD_SWIPE, {
            'x1': int(from_x), 'y1': int(from_y), 'x2': int(to_x), 'y2': int(to_y),
            'duration_ms': int(duration),
        })
        return bool(ack.get('ok'))

    def swipe_up(self, from_x: int = 500, from_y: int = 1500, to_x: int = 500, to_y: int = 500,
                 duration: int = 300) -> bool:
        return self.swipe(from_x, from_y, from_x, to_y, duration)

    def swipe_down(self, from_x: int = 500, from_y: int = 500, to_x: int = 500, to_y: int = 1500,
                   duration: int = 300) -> bool:
        return self.swipe(from_x, from_y, from_x, to_y, duration)

    def swipe_left(self, from_x: int = 800, from_y: int = 1000, to_x: int = 200, to_y: int = 1000,
                   duration: int = 300) -> bool:
        return self.swipe(from_x, from_y, to_x, from_y, duration)

    def swipe_right(self, from_x: int = 200, from_y: int = 1000, to_x: int = 800, to_y: int = 1000,
                    duration: int = 300) -> bool:
        return self.swipe(from_x, from_y, to_x, from_y, duration)

    # ---- apps ----------------------------------------------------------

    def get_installed_apps(self) -> List[AndroidApp]:
        ack = self._rpc(protocol.CMD_LIST_APPS, {}, timeout=protocol.CMD_TIMEOUT_SLOW_S)
        if not ack.get('ok'):
            print(f"Remote[{self.device_type.upper()}]: list_apps failed: {ack.get('error')}")
            return []
        apps = (ack.get('result') or {}).get('apps', [])
        return [AndroidApp(a.get('package', ''), a.get('label', '')) for a in apps]

    # ---- UI dump / click --------------------------------------------------

    def dump_elements(self, reason: str = 'dump') -> Tuple[bool, List[AndroidElement], str]:
        ack = self._rpc(protocol.CMD_DUMP_UI, {}, timeout=protocol.CMD_TIMEOUT_SLOW_S)
        if not ack.get('ok'):
            error = ack.get('error') or 'dump_ui failed'
            print(f"Remote[{self.device_type.upper()}]: UI dump failed: {error}")
            return False, [], error
        raw_elements = (ack.get('result') or {}).get('elements', [])
        elements = [_to_android_element(i, e) for i, e in enumerate(raw_elements)]
        self.last_ui_elements = elements
        self.last_dump_time = time.time()
        # Every dump lands in the trace, labelled with whatever the caller was doing.
        self.last_trace_path = self._write_dump_trace(reason)
        print(f"Remote[{self.device_type.upper()}]: dumped {len(elements)} UI elements")
        return True, elements, ''

    def click_element_by_id(self, element: AndroidElement) -> bool:
        x, y = _bounds_center(element.bounds)
        if x is None:
            self.last_error = f'element {element.id} has no usable bounds'
            return False
        return self.tap_coordinates(x, y)

    def _ensure_fresh_dump(self, reason: str = 'dump') -> None:
        """Re-dump unless the cache is newer than FIND_CACHE_S.

        The find_* helpers read `last_ui_elements`, which nothing filled unless the caller had
        already asked for a dump. A navigation action goes straight to click_element, so it
        searched an EMPTY list and answered "element not found" in 0ms without ever asking the
        phone — the failure read as a missing element rather than a missing dump.
        ADBVerificationController's smart_element_search dumps on every search for this reason;
        the short TTL keeps a multi-step action from dumping once per step.

        An empty tree means the window is mid-transition, not that the screen is empty:
        rootInActiveWindow is null while an app is starting, and a tree's launch_app wait is
        tuned for a warm start. Retry rather than take it at face value.
        """
        if self.last_ui_elements and (time.time() - self.last_dump_time) < FIND_CACHE_S:
            return
        for attempt in range(EMPTY_DUMP_RETRIES):
            ok, elements, _ = self.dump_elements(reason)
            if not ok or elements:
                return
            if attempt + 1 < EMPTY_DUMP_RETRIES:
                print(f"Remote[{self.device_type.upper()}]: empty UI tree "
                      f"(window still settling) - retrying in {EMPTY_DUMP_WAIT_S}s")
                time.sleep(EMPTY_DUMP_WAIT_S)

    @staticmethod
    def _matches(element: AndroidElement, needle: str, include_class: bool = False) -> bool:
        """Does this node carry `needle` (already lowercased) in anything selectable?

        `include_class` is set for EXCLUSIONS only, and the asymmetry is deliberate. A positive
        term names what a person sees on the screen — a label, a description, an id. An
        exclusion is usually about a *kind* of widget instead: "not the scrubber" is a statement
        about a SeekBar, whatever position it happens to be showing. Letting positive terms
        match class names too would quietly widen every selector already saved in a tree —
        'Search' would start matching a SearchView — for no gain.
        """
        return (needle in (element.text or '').lower()
                or needle in (element.content_desc or '').lower()
                or needle in (element.resource_id or '').lower()
                or (include_class and needle in (element.class_name or '').lower()))

    def _blocked_regions(self, unwanted: List[str]) -> List[Tuple[int, int, int, int]]:
        """The screen rectangles an excluded term rules out — children included.

        An exclusion has to cover the whole card, not just the node carrying the word. YouTube
        puts 'Sponsored - ...' on the clickable Button wrapping an ad and the duration on a
        child ViewGroup, so skipping only the labelled node would tap the child and open the
        very ad the selector meant to avoid. Excluding by area needs no parent pointers:
        whatever is drawn inside an excluded element belongs to it.

        Exclusions also match the widget class, which is what lets `!SeekBar` rule out a
        player's scrubber: it describes itself as a duration ("38 minutes 24 seconds of 1 hour
        3 minutes 38 seconds"), so ' seconds' matches it and it is both clickable and the
        shortest label on the screen — exactly what _best_match prefers. A retry on the player
        would seek the video instead of opening one.
        """
        regions: List[Tuple[int, int, int, int]] = []
        for term in unwanted:
            needle = term.lower()
            for element in self.last_ui_elements:
                if self._matches(element, needle, include_class=True):
                    rect = _bounds_rect(element.bounds)
                    if rect:
                        regions.append(rect)
        return regions

    def _best_match(self, term: str,
                    blocked: Sequence[Tuple[int, int, int, int]] = ()) -> Optional[AndroidElement]:
        """The element a person would have tapped for `term`.

        A term matches several nodes on a real screen — YouTube labels a video card's duration
        on a ViewGroup and again on the clickable Button wrapping it — and taking the first hit
        in tree order lands on whichever happened to be dumped first. Prefer a clickable node,
        then the shortest label, which is the most specific one. ADB's smart_element_search
        ranks its hits for the same reason.
        """
        needle = term.lower()
        matches = [e for e in self.last_ui_elements if self._matches(e, needle)]
        if blocked:
            matches = [e for e in matches if not _inside_any(e.bounds, blocked)]
        if not matches:
            return None
        return min(matches, key=lambda e: (0 if e.clickable else 1,
                                           len(e.content_desc or e.text or '')))

    def click_element(self, element_identifier: str) -> bool:
        self._ensure_fresh_dump(f'click_element({element_identifier!r})')
        wanted, unwanted = _parse_selector(element_identifier)
        blocked = self._blocked_regions(unwanted) if unwanted else []
        for term in wanted:
            element = self._best_match(term, blocked)
            if element and self.click_element_by_id(element):
                self.last_error = None
                self.last_click_label = (element.content_desc or element.text
                                         or element.resource_id or '').strip()
                print(f"Remote[{self.device_type.upper()}]: clicked "
                      f"{self.last_click_label!r} for {element_identifier!r}")
                self._note_outcome(
                    f"{element_identifier!r} clicked {self.last_click_label[:80]!r}")
                return True
        self.last_click_label = None
        self.last_error = f"element not found: {element_identifier}"
        self._note_outcome(f"{element_identifier!r} NOT FOUND")
        trace = getattr(self, 'last_trace_path', None)
        print(f"Remote[{self.device_type.upper()}]: {self.last_error}"
              + (f" - what was on screen: {trace}" if trace else ''))
        return False

    def _note_outcome(self, outcome: str) -> None:
        """Annotate the dump we just acted on, in BOTH copies of the trace.

        ui_dump_capture holds the run's copy, which the report uploads; the host file is the
        cumulative one you read over SSH. An outcome that only reached the first would leave
        the file on the host showing trees with no record of what was decided about them.
        """
        ui_dump_capture.note(outcome)
        path = getattr(self, 'last_trace_path', None)
        if not path:
            return
        try:
            with open(path, 'a', encoding='utf-8') as fh:
                fh.write(f"  -> {outcome}\n")
        except OSError as e:
            print("Remote[%s]: could not annotate the dump trace: %s"
                  % (self.device_type.upper(), e))

    def _trace_rows(self):
        """The current tree in the shape ui_dump_capture renders, unlabelled nodes dropped."""
        return [
            {'text': e.text, 'content_desc': e.content_desc,
             'class_name': e.class_name, 'clickable': e.clickable}
            for e in self.last_ui_elements
            if (e.text or '').strip() or (e.content_desc or '').strip()
        ]

    def _write_dump_trace(self, why: str) -> Optional[str]:
        """Record the tree we just read, for this run's report and for the host's own file.

        Called from dump_elements, so **every** dump is in the trace — including the repeats a
        polling verification produces, because "we looked eight times and it never changed" is
        the answer to most questions about a stuck screen. ui_dump_capture collapses a tree
        identical to the one before it into a back-reference, so the repeats cost a line each.

        The host file stays cumulative across runs, because that is the one you read over SSH
        with a phone in front of you. Returns its path so a caller can name it in one log line
        rather than printing a hundred nodes.
        """
        slot = self.bridge.get_slot(self.device_id) if self.bridge else None
        capture_path = getattr(slot, 'capture_path', '') if slot else ''
        path = os.path.join(capture_path, 'ui_dumps.txt') if capture_path else ''

        # Number the sections, so "dump 3" means something when someone refers to one. The host
        # file is the source of the numbering when it exists, so a section in the report and the
        # same section on disk carry the same number.
        index = get_ui_dump_count() + 1
        try:
            if path and os.path.exists(path):
                if os.path.getsize(path) > TRACE_MAX_BYTES:
                    os.replace(path, path + '.1')
                else:
                    with open(path, encoding='utf-8') as fh:
                        index = sum(1 for line in fh if line.startswith('=== dump ')) + 1
        except OSError as e:
            print("Remote[%s]: could not read the dump trace: %s" % (self.device_type.upper(), e))

        rows = self._trace_rows()
        total = len(self.last_ui_elements)
        ui_dump_capture.record(self.device_id, why, rows, total)
        if not path:
            return None
        try:
            with open(path, 'a', encoding='utf-8') as fh:
                fh.write(ui_dump_capture.render_section(index, self.device_id, why, rows, total))
            return path
        except OSError as e:
            print("Remote[%s]: could not write the dump trace: %s" % (self.device_type.upper(), e))
            return None

    def find_element_by_text(self, text: str) -> Optional[AndroidElement]:
        for element in self.last_ui_elements:
            if text.lower() in (element.text or '').lower():
                return element
        return None

    def find_element_by_resource_id(self, resource_id: str) -> Optional[AndroidElement]:
        for element in self.last_ui_elements:
            if resource_id in (element.resource_id or ''):
                return element
        return None

    def find_element_by_content_desc(self, content_desc: str) -> Optional[AndroidElement]:
        for element in self.last_ui_elements:
            if content_desc.lower() in (element.content_desc or '').lower():
                return element
        return None

    def verify_element_exists(self, text: str = '', resource_id: str = '', content_desc: str = '') -> bool:
        self._ensure_fresh_dump(
            f'verify_element_exists({text or resource_id or content_desc!r})')
        if text:
            return self.find_element_by_text(text) is not None
        if resource_id:
            return self.find_element_by_resource_id(resource_id) is not None
        if content_desc:
            return self.find_element_by_content_desc(content_desc) is not None
        return False

    # ---- screenshot / device info -----------------------------------------

    def get_device_resolution(self) -> Optional[Dict[str, int]]:
        if self.device_resolution:
            return self.device_resolution
        self.get_device_info()  # populates self.device_resolution from hello's screen info
        return self.device_resolution

    def get_device_info(self) -> Dict[str, Any]:
        ack = self._rpc(protocol.CMD_DEVICE_INFO, {})
        if not ack.get('ok'):
            return {'device_id': self.device_id, 'error': ack.get('error', 'device_info failed')}
        result = ack.get('result') or {}
        screen = result.get('screen') or {}
        info = {
            'device_id': self.device_id,
            'device_type': self.device_type,
            'device_name': self.device_name,
            'connection_type': 'phone_agent',
            'manufacturer': result.get('manufacturer'),
            'model': result.get('model'),
            'android_version': result.get('android'),
            'battery_level': result.get('battery'),
        }
        if screen.get('w') and screen.get('h'):
            info['width'] = screen['w']
            info['height'] = screen['h']
            info['resolution'] = f"{screen['w']}x{screen['h']}"
            self.device_resolution = {'width': screen['w'], 'height': screen['h']}
        return info

    def take_screenshot(self) -> Tuple[bool, str, str]:
        ack = self._rpc(protocol.CMD_SCREENSHOT, {}, timeout=protocol.CMD_TIMEOUT_SLOW_S)
        if ack.get('ok'):
            b64 = (ack.get('result') or {}).get('jpeg_b64', '')
            if b64:
                return True, b64, ''
        # The phone was slow/unreachable for this round-trip - fall back to the
        # latest frame the stream already has on disk rather than failing outright.
        fallback = self._latest_frame_b64()
        if fallback:
            print(f"Remote[{self.device_type.upper()}]: screenshot cmd failed, used latest streamed frame instead")
            return True, fallback, ''
        return False, '', ack.get('error') or 'screenshot failed'

    def _latest_frame_b64(self) -> str:
        slot = self.bridge.get_slot(self.device_id) if self.bridge else None
        if not slot or not os.path.isfile(slot.frame_path):
            return ''
        try:
            with open(slot.frame_path, 'rb') as fh:
                return base64.b64encode(fh.read()).decode('ascii')
        except OSError:
            return ''

    def get_status(self) -> Dict[str, Any]:
        slot = self.bridge.get_slot(self.device_id) if self.bridge else None
        if not slot:
            return {'success': False, 'error': 'no phone_agent slot for this device'}
        if slot.state != 'connected':
            return {'success': False, 'error': f'phone not connected (slot state: {slot.state})'}
        return {'success': True}

    # ---- actions -----------------------------------------------------

    def get_available_actions(self) -> Dict[str, Any]:
        # Same catalogue as android_mobile minus capture_camera_image, which needs
        # `adb shell am start` + a file pull the agent protocol has no equivalent
        # for (TASK-17 §8 out of scope). get_available_actions() builds a static
        # dict with no `self` access, so borrowing it unbound is safe reuse, not a
        # hack around a real dependency.
        actions = AndroidMobileRemoteController.get_available_actions(self)
        actions['Remote'] = [a for a in actions['Remote'] if a['command'] != 'capture_camera_image']

        # Offered here and not on android_mobile, where `reset` is not implemented: an adb
        # device gets the same effect from `close_app`, which really does force-stop.
        launch_index = next(
            (i for i, a in enumerate(actions['Remote']) if a['command'] == 'launch_app'),
            len(actions['Remote']) - 1,
        )
        actions['Remote'].insert(launch_index + 1, {
            'id': 'restart_app',
            'label': 'Restart App (from its entry point)',
            'command': 'launch_app',
            'action_type': 'remote',
            'params': {'package': '', 'reset': True},
            'description': ("Launch an application at its entry point instead of resuming it. "
                            "Use this where a tree means \"from the app's home screen\": "
                            "close_app on a phone can only press HOME — unrooted Android has no "
                            "force-stop API — so a plain launch puts the app back exactly where "
                            "it was left."),
            'requiresInput': True,
            'inputLabel': 'Package name',
            'inputPlaceholder': 'com.example.app',
            'inputParam': 'package',
        })
        return actions

    def execute_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Mirrors AndroidMobileRemoteController.execute_command's command names/params
        (TASK-17 §1.5) so action blocks recorded against android_mobile also run here."""
        params = params or {}
        wait_time = int(params.get('wait_time', 0))
        print(f"Remote[{self.device_type.upper()}]: executing '{command}' with params: {params}")

        if command == 'press_key':
            key = params.get('key')
            ok = self.press_key(key) if key else False
            result = {'success': ok} if ok else {'success': False, 'error': self.last_error or 'no key given'}
        elif command == 'input_text':
            text = params.get('text')
            ok = self.input_text(text) if text else False
            result = {'success': ok} if ok else {'success': False, 'error': self.last_error or 'no text given'}
        elif command == 'launch_app':
            package = params.get('package')
            reset = str(params.get('reset', '')).lower() in ('1', 'true', 'yes')
            ok = self.launch_app(package, reset) if package else False
            result = {'success': ok} if ok else {'success': False, 'error': self.last_error or 'no package given'}
        elif command == 'close_app':
            package = params.get('package')
            ok = self.close_app(package) if package else False
            result = {'success': ok} if ok else {'success': False, 'error': self.last_error or 'no package given'}
        elif command == 'click_element':
            element_id = params.get('element_id') or params.get('text')
            if not element_id:
                result = {'success': False, 'error': "click_element requires 'element_id' or 'text' parameter"}
            elif self.click_element(element_id):
                label = self.last_click_label
                # The selector is a search term; say which node it landed on, so a run that
                # tapped the wrong card is visible in the report instead of just "click ✓".
                result = {'success': True}
                if label:
                    result['message'] = f"clicked {label[:80]!r}"
            else:
                result = {'success': False, 'error': self.last_error or f"click_element '{element_id}' failed"}
        elif command == 'click_element_by_id':
            element_id = params.get('element_id')
            if not element_id:
                result = {'success': False, 'error': 'element_id parameter required'}
            else:
                dump_success, elements, dump_error = self.dump_elements()
                if not dump_success:
                    result = {'success': False, 'error': f'UI dump failed: {dump_error}'}
                else:
                    element = next((el for el in elements if str(el.id) == str(element_id)), None)
                    if not element:
                        result = {'success': False, 'error': f'Element with ID {element_id} not found in current UI dump'}
                    else:
                        result = {'success': bool(self.click_element_by_id(element))}
        elif command == 'tap_coordinates':
            x, y = params.get('x'), params.get('y')
            result = {'success': self.tap_coordinates(int(x), int(y)) if x is not None and y is not None else False}
        elif command == 'swipe':
            from_x, from_y = params.get('from_x'), params.get('from_y')
            to_x, to_y = params.get('to_x'), params.get('to_y')
            duration = params.get('duration', 300)
            if all(v is not None for v in (from_x, from_y, to_x, to_y)):
                result = {'success': self.swipe(int(from_x), int(from_y), int(to_x), int(to_y), int(duration))}
            else:
                result = {'success': False}
        elif command in ('swipe_up', 'SWIPE_UP'):
            result = {'success': self.swipe_up()}
        elif command in ('swipe_down', 'SWIPE_DOWN'):
            result = {'success': self.swipe_down()}
        elif command in ('swipe_left', 'SWIPE_LEFT'):
            result = {'success': self.swipe_left()}
        elif command in ('swipe_right', 'SWIPE_RIGHT'):
            result = {'success': self.swipe_right()}
        elif command == 'dump_elements':
            success, elements, error = self.dump_elements()
            if not success:
                result = {'success': False, 'error': f'Failed to dump UI: {error}'}
            else:
                element_list = [{'text': e.text, 'content_desc': e.content_desc, 'resource_id': e.resource_id,
                                  'class_name': e.class_name, 'bounds': e.bounds} for e in elements]
                result = {'success': True, 'elements': element_list, 'output_data': {'elements': element_list}}
        elif command == 'get_installed_apps':
            apps = self.get_installed_apps()
            result = {'success': len(apps) > 0, 'apps': apps}
        elif command == 'take_screenshot':
            success, _screenshot_b64, error = self.take_screenshot()
            result = {'success': True} if success else {'success': False, 'error': f'Screenshot failed: {error}'}
        else:
            result = {'success': False, 'error': f"Invalid command '{command}' for phone_agent device"}

        if result.get('success') and wait_time > 0:
            time.sleep(wait_time / 1000.0)
        return result


def _to_android_element(index: int, raw: Dict[str, Any]) -> AndroidElement:
    """protocol dump_ui element -> AndroidElement (adb_utils' shape). `package` here
    carries the same value android_mobile's routes already expose as 'package' in
    the API response (which is actually AndroidElement.resource_id - see
    backend_host/src/routes/host_remote_routes.py) - kept for wire compatibility."""
    l, t, r, b = ((raw.get('bounds') or [0, 0, 0, 0]) + [0, 0, 0, 0])[:4]
    bounds_str = f'[{int(l)},{int(t)}][{int(r)},{int(b)}]'  # adb_utils' bounds parser format
    return AndroidElement(
        element_id=raw.get('id', index),
        tag='node',
        text=raw.get('text') or '',
        resource_id=raw.get('package') or raw.get('resource_id') or '',
        content_desc=raw.get('content_desc') or '',
        class_name=raw.get('class') or raw.get('class_name') or '',
        bounds=bounds_str,
        clickable=bool(raw.get('clickable', False)),
        enabled=bool(raw.get('enabled', True)),
        xpath=None,
        focusable=bool(raw.get('focused', False)),
    )


def _bounds_rect(bounds: str) -> Optional[Tuple[int, int, int, int]]:
    if not bounds:
        return None
    match = _BOUNDS_RE.match(bounds)
    if not match:
        return None
    x1, y1, x2, y2 = map(int, match.groups())
    return x1, y1, x2, y2


def _bounds_center(bounds: str) -> Tuple[Optional[int], Optional[int]]:
    rect = _bounds_rect(bounds)
    if rect is None:
        return None, None
    x1, y1, x2, y2 = rect
    return (x1 + x2) // 2, (y1 + y2) // 2


def _inside_any(bounds: str, regions: Sequence[Tuple[int, int, int, int]]) -> bool:
    """Would a tap on `bounds` land inside one of `regions`?"""
    x, y = _bounds_center(bounds)
    if x is None:
        return False
    return any(x1 <= x <= x2 and y1 <= y <= y2 for x1, y1, x2, y2 in regions)


def _parse_selector(element_identifier: str) -> Tuple[List[str], List[str]]:
    """Split a selector into the terms to look for and the ones that disqualify a match.

    `a|b` has always meant "try a, then b". A term prefixed with `!` now means the opposite:
    nothing inside an element carrying it may be clicked. That is what a real feed needs —
    `' seconds|!Sponsored'` reads "the first thing with a duration that is not an ad" — and it
    keeps the selector one string, so it still fits an edge's existing element_id parameter.

    A selector with no `|` is passed through untouched, leading space and all: today's trees
    rely on that, and ' seconds' is not 'seconds'.
    """
    if '|' not in element_identifier:
        return [element_identifier], []
    wanted, unwanted = [], []
    for part in element_identifier.split('|'):
        part = part.strip()
        if part.startswith('!'):
            excluded = part[1:].strip()
            if excluded:
                unwanted.append(excluded)
        elif part:
            wanted.append(part)
    return wanted, unwanted
