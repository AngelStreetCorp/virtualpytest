"""
DTMF generation strategy (TASK-71 goal 2 — the blocker).

The CX93001-EIS firmware advertises tone generation:

    AT+VTS=?   ->   (200-3000),(200-3000),(0-255)

and then answers ERROR to every documented form of it. That is the whole open
question of this task: **no +VTS syntax is known to work**, and no one has
proven that a digit can reach the far end.

Rather than hardcode a guess that may be wrong, this module *probes once and
caches what the modem accepted*. The first send_digits() on a given port tries
each candidate in order; whichever the modem takes becomes that modem's
strategy, and later calls go straight to it.

Two things this deliberately does not do:

* **It does not claim success.** "The modem accepted the command" and "a digit
  reached the far end" are different claims, and only the first is observable
  from this side. `send_digits` reports which one it can support, and the
  bench script prints the same caveat. Verifying goal 2 needs a human, or an
  answering machine, at the other end of the line.

* **It does not treat in-call dialling as equivalent.** `ATDT1;` after CONNECT
  is a different mechanism (dialling DTMF as tone pairs through the dial path)
  from a tone-generator command. It is in the list because it is the most
  likely winner on this firmware, but it is marked `needs_call=True` so it is
  only tried once a call is actually up — sending it in hook would dial.

Candidate order is cheapest-and-most-likely first. If the firmware turns out to
be one of the obvious forms, the very first attempt wins and the cost of
negotiation is paid once per modem.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional

from .at_channel import ATError, DTMF_TIMEOUT


ROW_FREQS = (697, 770, 852, 941)
COL_FREQS = (1209, 1336, 1477, 1633)
DIGIT_KEYS = {
    "1": (0, 0), "2": (0, 1), "3": (0, 2), "A": (0, 3),
    "4": (1, 0), "5": (1, 1), "6": (1, 2), "B": (1, 3),
    "7": (2, 0), "8": (2, 1), "9": (2, 2), "C": (2, 3),
    "*": (3, 0), "0": (3, 1), "#": (3, 2), "D": (3, 3),
}

DEFAULT_TONE_MS = 50

class Candidate(NamedTuple):
    label: str
    command: str
    # A template that can carry an ARBITRARY digit, or None when the form can
    # only ever emit the digit it was probed with. This distinction matters: a
    # probe command and the command that actually sends must be the SAME form.
    # Rebuilding `AT+VTS=[697,1209,50]` as `AT+VTS=697,1209,50` after probing
    # the bracketed form asks for something the modem never agreed to.
    template: Optional[str] = None
    needs_call: bool = False
    family: str = "vts"

    def build(self, digit: str, ms: int = DEFAULT_TONE_MS) -> Optional[str]:
        """The command that sends `digit`, or None if this form cannot."""
        if self.template:
            pair = tone_pair_for(digit)
            if pair is None:
                return None
            return self.template.format(lo=pair[0], hi=pair[1], ms=ms, d=digit)
        if self.family == "dial":
            return f"ATDT{digit};"
        # A digit-index form was probed with '1' and cannot express anything else.
        return self.command if digit == "1" else None


# Ordered. See the module docstring for why this order.
CANDIDATES: List[Candidate] = [
    Candidate("digit index", "AT+VTS=1"),
    Candidate("digit braced", "AT+VTS={1}"),
    Candidate("tone pair bracketed", "AT+VTS=[697,1209,50]",
              template="AT+VTS=[{lo},{hi},{ms}]"),
    Candidate("tone pair bare", "AT+VTS=697,1209,50",
              template="AT+VTS={lo},{hi},{ms}"),
    Candidate("tone pair with flag", "AT+VTS=697,1209,50,0",
              template="AT+VTS={lo},{hi},{ms},0"),
    Candidate("tone freq and duration", "AT+VTS=697,1209,200",
              template="AT+VTS={lo},{hi},{ms}"),
    Candidate("Conexant VDTMF", "AT+VDTMF=1"),
    Candidate("Conexant VDTMF braced", "AT+VDTMF={1}"),
    Candidate("VTS query form", "AT+VTS=?"),
    # Not a tone-generator command: dials one digit after CONNECT.
    Candidate("in-call dialling", "ATDT1;", needs_call=True, family="dial"),
]

# Standard DTMF row/column frequencies, used to build tone-pair commands for an
# arbitrary digit rather than the single '1' above.


def tone_pair_for(digit: str) -> Optional[tuple]:
    """(low, high) Hz for one DTMF digit, or None if it is not a DTMF key."""
    key = DIGIT_KEYS.get(digit.strip().upper())
    if key is None:
        return None
    return ROW_FREQS[key[0]], COL_FREQS[key[1]]


class DtmfStrategy:
    """Per-modem DTMF state: which form this modem accepts, if any.

    One instance per VoiceModem, so four dongles do not borrow each other's
    answer — a second modem on a different OEM firmware may need a different
    form entirely.
    """

    def __init__(self, port: str, candidates: Optional[List[Candidate]] = None):
        self.port = port
        self.candidates = list(candidates or CANDIDATES)
        self.chosen: Optional[Candidate] = None
        self.probe_results: List[Dict] = []

    # -- introspection -----------------------------------------------------

    @property
    def resolved(self) -> bool:
        return self.chosen is not None

    def describe(self) -> str:
        if self.chosen is None:
            return "unresolved — no +VTS form accepted yet"
        return f"{self.chosen.family}:{self.chosen.label}"

    # -- probing -----------------------------------------------------------

    def probe(self, channel, in_call: bool = False) -> List[Dict]:
        """Try every candidate; remember the first the modem accepts.

        Never raises: this is a search, and a modem that accepts nothing is a
        legitimate result that the caller has to be able to report.
        """
        if self.chosen is not None:
            return self.probe_results

        self.probe_results = []
        for cand in self.candidates:
            if cand.needs_call and not in_call:
                self.probe_results.append(
                    {"label": cand.label, "command": cand.command,
                     "accepted": None, "reason": "skipped — needs a connected call"}
                )
                continue
            ok, reply = channel.try_command(cand.command, timeout=DTMF_TIMEOUT)
            reason = reply.split("->", 1)[-1].strip() if "->" in reply else reply
            self.probe_results.append(
                {"label": cand.label, "command": cand.command,
                 "accepted": ok, "reason": reason.replace("\n", " ")[:80]}
            )
            if ok:
                self.chosen = cand
                # Keep probing nothing further: the first acceptance wins and we
                # do not want to fire a real tone at a live line just to be sure.
                break
        return self.probe_results

    # -- sending -----------------------------------------------------------

    def send(self, channel, digits: str, in_call: bool = False) -> Dict:
        """Send DTMF. Returns a dict describing what was attempted.

        `verified` is always False: acceptance by the modem is not proof that a
        digit was heard. The caller decides what to do with that.
        """
        digits = (digits or "").strip()
        if not digits:
            return {"ok": False, "reason": "no digits given", "verified": False}

        if not self.resolved:
            self.probe(channel, in_call=in_call)
        if not self.resolved:
            return {
                "ok": False,
                "reason": "no DTMF form accepted by this modem",
                "attempted": self.probe_results,
                "verified": False,
            }

        cand = self.chosen
        if cand.family == "dial":
            ok, reply = True, ""
            for ch in digits:
                cmd = f"ATDT{ch};"
                ok, reply = channel.try_command(cmd, timeout=DTMF_TIMEOUT)
                if not ok:
                    break
        else:
            # Send the SAME form that was accepted, just with this digit's tone
            # pair. Reusing the template is what keeps the bracketed form
            # bracketed — asking for a different syntax after a successful probe
            # is how a working strategy gets thrown away.
            cmds = [cand.build(ch) for ch in digits]
            if any(c is None for c in cmds):
                bad = next(ch for ch, c in zip(digits, cmds) if c is None)
                return {"ok": False, "verified": False, "strategy": cand.label,
                        "reason": (f"the probed form ({cand.label}) can only emit the digit "
                                   f"it was probed with; {bad!r} needs a different syntax")}
            ok, reply = True, ""
            for cmd in cmds:
                ok, reply = channel.try_command(cmd, timeout=DTMF_TIMEOUT)
                if not ok:
                    break

        return {
            "ok": ok,
            "command": f"{cand.command} (per-digit form of this strategy)",
            "strategy": cand.label,
            "reason": reply,
            # Accepted by the modem. NOT proof a digit was emitted.
            "verified": False,
        }