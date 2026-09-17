"""
features/mobile-app/backend_host/controllers/phone_ui_verification.py — `waitForElementToAppear`
for a paired phone, read from its AccessibilityService node tree instead of an ADB UI dump.

Why it registers as **'adb'**: that is the `verification_type` every android_mobile navigation
tree records for a UI-element check (see the youtube-android-mobile tree). A paired phone has no
adb, but it has the same information — the accessibility tree the remote controller already
dumps for `dump_elements` — so backing the same verification type with it makes those trees run
unchanged on a phone, which is the whole point of pairing one.

Why the class name contains "Adb": VerificationExecutor binds controllers to slots by
substring-matching the class name (`elif 'adb' in class_name: self.adb_controller = ctrl`), which
is how every controller in this codebase is classified. Rename it and `verification_type: 'adb'`
silently stops dispatching here.

Search semantics deliberately mirror ADBVerificationController: case-insensitive "contains" over
every text-ish attribute, pipe-separated fallback terms, poll once when timeout is 0 and then
once a second, and the same result dict so reports and the frontend render it identically.

It also carries `waitForElementToChange` / `waitForElementToStopChanging` (implemented in
backend_host/src/controllers/verification/element_watch.py, shared with the ADB controller so a
tree behaves the same on either). They answer "is this playing?" from the player's own position
label rather than from motion in the captured frames — directly, in about a second, instead of
sampling pixels for up to a minute. That matters most right after a launch, when a phone's
captured player area is still black because nothing has drawn yet and a motion check reads that
as a failure.
"""
import time
from typing import Any, Dict, List, Optional, Tuple

from backend_host.src.controllers.base_controller import VerificationControllerInterface
from backend_host.src.controllers.verification import element_watch
from shared.src.lib.utils import ui_dump_capture

_LOG = '[@controller:PhoneUiVerification]'
# The same attributes element_watch matches on, so waitForElementToAppear and the watch pair
# agree about what a search term can select.
_SEARCHED_ATTRIBUTES = element_watch.SEARCHED_ATTRIBUTES
_POLL_INTERVAL_S = 1.0
# Same ceiling ADBVerificationController applies, for the same reason: a tree can carry a
# nonsense timeout and a verification should not hang a run on it.
_MAX_TIMEOUT_S = 60.0


class PhoneAgentAdbVerificationController(VerificationControllerInterface):
    """UI-element verification for a phone_agent device, over the accessibility node tree."""

    def __init__(self, device_id: str = None, device_model: str = None, bridge=None, **_ignored):
        super().__init__('Phone UI Verification', 'phone_agent')
        self.device_id = device_id
        self.device_model = device_model
        self.bridge = bridge

    # ---- element lookup -------------------------------------------------------------------

    def _dump_elements(self, reason: str = 'dump') -> Tuple[bool, List[Dict[str, Any]], str]:
        """The phone's current accessibility tree, in the shape the search below expects."""
        if not self.bridge:
            return False, [], 'no bridge configured for this controller'
        from ...lib import protocol

        ack = self.bridge.rpc(self.device_id, protocol.CMD_DUMP_UI, {},
                              protocol.CMD_TIMEOUT_SLOW_S)
        if not ack.get('ok'):
            return False, [], ack.get('error') or 'dump_ui failed'
        elements = (ack.get('result') or {}).get('elements') or []
        # Every dump goes into the run's trace, polls included. ui_dump_capture collapses a
        # tree identical to the one before it, so a verification that waits twenty seconds for
        # a screen that never changes costs twenty lines rather than twenty trees.
        rows = [
            {'text': e.get('text'), 'content_desc': e.get('content_desc'),
             'class_name': e.get('class') or e.get('class_name'), 'clickable': e.get('clickable')}
            for e in elements
            if str(e.get('text') or '').strip() or str(e.get('content_desc') or '').strip()
        ]
        ui_dump_capture.record(self.device_id, reason, rows, len(elements))
        return True, elements, ''

    @staticmethod
    def _record_outcome(outcome: str) -> None:
        """Annotate the dump this verification acted on, rather than repeating the tree."""
        ui_dump_capture.note(outcome)

    @staticmethod
    def _matches(element: Dict[str, Any], term: str) -> Optional[str]:
        """The attribute that matched, or None. Case-insensitive substring, like the ADB one."""
        needle = term.strip().lower()
        if not needle:
            return None
        for attr in _SEARCHED_ATTRIBUTES:
            # The phone reports `class`/`content_desc`; accept the ADB spellings too so a tree
            # written against either vocabulary behaves the same.
            value = element.get(attr) or element.get(attr.replace('class_name', 'class')) or ''
            if needle in str(value).lower():
                return attr
        return None

    def _search(self, term: str, reason: str = '') -> Tuple[bool, List[Dict[str, Any]], str]:
        ok, elements, error = self._dump_elements(reason or f'search({term!r})')
        if not ok:
            return False, [], error
        matches = []
        for index, element in enumerate(elements):
            attr = self._matches(element, term)
            if attr:
                matches.append({
                    'element_id': element.get('id', index),
                    'match_reason': f"{attr} contains '{term}'",
                    'text': element.get('text', ''),
                    'content_desc': element.get('content_desc', ''),
                    'resource_id': element.get('resource_id', ''),
                    'bounds': element.get('bounds'),
                })
        return bool(matches), matches, ''

    # ---- the ADB verification surface -----------------------------------------------------

    def waitForElementToAppear(self, search_term: str, timeout: float = 0.0):
        return self._wait(search_term, timeout, want_present=True)

    def waitForElementToDisappear(self, search_term: str, timeout: float = 0.0):
        return self._wait(search_term, timeout, want_present=False)

    def _wait(self, search_term: str, timeout: float, want_present: bool):
        verb = 'appear' if want_present else 'disappear'
        terms = [t.strip() for t in search_term.split('|') if t.strip()] or [search_term]
        started = time.time()
        last_error = None
        matches: List[Dict[str, Any]] = []
        hit_term = None

        while True:
            found = False
            for term in terms:
                ok, found_matches, error = self._search(term, f'{verb} {term!r}')
                if error:
                    last_error = error
                    continue
                if ok:
                    found, matches, hit_term = True, found_matches, term
                    break

            if found == want_present:
                elapsed = time.time() - started
                message = (f"Element found after {elapsed:.1f}s using term '{hit_term}'"
                           if want_present else
                           f"Element gone after {elapsed:.1f}s")
                print(f"{_LOG} SUCCESS: {message}")
                self._record_outcome(f"{verb} {search_term!r} -> PASS ({elapsed:.1f}s)")
                return True, message, self._result(search_term, terms, elapsed, matches, hit_term)

            elapsed = time.time() - started
            if timeout <= 0 or elapsed >= timeout:
                break
            time.sleep(_POLL_INTERVAL_S)

        elapsed = time.time() - started
        message = f"Element '{search_term}' did not {verb} after {elapsed:.1f}s"
        print(f"{_LOG} FAILED: {message}" + (f" (last error: {last_error})" if last_error else ''))
        self._record_outcome(f"{verb} {search_term!r} -> FAIL ({elapsed:.1f}s)")
        result = self._result(search_term, terms, elapsed, matches, hit_term)
        result['timeout_reached'] = True
        result['last_error'] = last_error
        return False, message, result

    @staticmethod
    def _result(search_term, terms, elapsed, matches, hit_term) -> Dict[str, Any]:
        return {
            'search_term': search_term,
            'successful_term': hit_term,
            'attempted_terms': terms,
            'wait_time': elapsed,
            'total_matches': len(matches),
            'matches': matches,
            'search_details': {
                'case_sensitive': False,
                'search_method': 'contains_any_attribute',
                'searched_attributes': list(_SEARCHED_ATTRIBUTES),
                'source': 'accessibility_tree',
                'fallback_strategy': len(terms) > 1,
            },
        }

    # ---- watching one element's label -----------------------------------------------------

    def _element_label(self, term: str) -> Tuple[bool, str, Dict[str, Any], str]:
        """What `element_watch` needs: the label of the first element matching `term`."""
        ok, elements, error = self._dump_elements(f'watch {term!r}')
        if not ok:
            return False, '', {}, error
        return element_watch.first_labelled_match(elements, term)

    def waitForElementToChange(self, search_term: str, timeout: float = 0.0):
        """Pass as soon as the element's label differs from the first reading."""
        ok, message, details = element_watch.wait_for_change(
            self._element_label, search_term, timeout, _LOG)
        self._record_outcome(f"watch {search_term!r} change -> {'PASS' if ok else 'FAIL'}")
        return ok, message, details

    def waitForElementToStopChanging(self, search_term: str,
                                     duration: float = element_watch.DEFAULT_STABLE_S,
                                     timeout: float = 0.0):
        """Pass once the element's label has held the same value for `duration` seconds."""
        ok, message, details = element_watch.wait_for_stable(
            self._element_label, search_term, duration, timeout, _LOG)
        self._record_outcome(f"watch {search_term!r} settle -> {'PASS' if ok else 'FAIL'}")
        return ok, message, details

    # ---- executor entry points ------------------------------------------------------------

    def get_available_verifications(self) -> List[Dict[str, Any]]:
        from shared.src.lib.schemas.param_types import create_param, ParamType

        def _params():
            return {
                'search_term': create_param(
                    ParamType.STRING, required=True, default='',
                    description='Element search term (text, content description, resource id)',
                    placeholder='Enter element identifier',
                ),
                'timeout': create_param(
                    ParamType.NUMBER, required=False, default=0.0,
                    description='Maximum time to wait (seconds)',
                ),
            }

        return [
            {
                'command': 'waitForElementToAppear',
                'label': 'Wait for Element to Appear',
                'description': "Wait for a UI element using the phone's accessibility tree",
                'params': _params(),
                'verification_type': 'adb',
            },
            {
                'command': 'waitForElementToDisappear',
                'label': 'Wait for Element to Disappear',
                'description': "Wait for a UI element to go using the phone's accessibility tree",
                'params': _params(),
                'verification_type': 'adb',
            },
        ] + element_watch.declare_verifications(
            create_param, ParamType, "phone's accessibility tree")


    def execute_verification(self, verification_config: Dict[str, Any]) -> Dict[str, Any]:
        params = verification_config.get('params', {}) or {}
        command = verification_config.get('command', 'waitForElementToAppear')
        search_term = params.get('search_term', '')

        if not search_term:
            return self._response(False, 'No search term specified for phone UI verification',
                                  search_term, {})

        # Trees record this in milliseconds, exactly as the ADB controller reads it.
        timeout = min(float(params.get('timeout', 0) or 0) / 1000.0, _MAX_TIMEOUT_S)
        print(f"{_LOG} {command} '{search_term}' (timeout {timeout}s) on {self.device_id}")

        if command == 'waitForElementToAppear':
            success, message, details = self.waitForElementToAppear(search_term, timeout)
        elif command == 'waitForElementToDisappear':
            success, message, details = self.waitForElementToDisappear(search_term, timeout)
        elif command == 'waitForElementToChange':
            success, message, details = self.waitForElementToChange(search_term, timeout)
        elif command == 'waitForElementToStopChanging':
            # `duration` is seconds, matching DetectMotion, while `timeout` stays milliseconds
            # like every other verification a tree records. Unit-mixing is unfortunate but both
            # halves match their own precedent, and changing either would break saved trees.
            duration = float(params.get('duration', element_watch.DEFAULT_STABLE_S)
                             or element_watch.DEFAULT_STABLE_S)
            success, message, details = self.waitForElementToStopChanging(
                search_term, duration, timeout)
        else:
            return self._response(False, f'Unknown phone UI verification command: {command}',
                                  search_term, {'error': f'Unsupported command: {command}'})

        return self._response(success, message, search_term, details)

    @staticmethod
    def _response(success: bool, message: str, search_term: str, details: Dict[str, Any]) -> Dict[str, Any]:
        """The same shape ADBVerificationController returns, so reports and the frontend do not
        need to know which of the two answered."""
        return {
            'success': success,
            'message': message,
            'matching_result': 1.0 if success else 0.0,
            'user_threshold': 0.8,
            'image_filter': 'none',
            'searchedText': search_term,
            'extractedText': (f"Found {details.get('total_matches', 0)} matches" if success
                              else 'No matches found'),
            'search_term': search_term,
            'wait_time': details.get('wait_time', 0.0),
            'total_matches': details.get('total_matches', 0),
            'matches': details.get('matches', []),
            'details': details,
        }
