"""
FX voice modem as a VirtualPyTest remote controller (TASK-71).

    from .remote.fx import FXRemoteController

Device model `fx_dongle`. See controller.py for the command surface and
dtmf.py for why "the modem accepted it" is not "a digit was sent".
"""

from .at_channel import ATChannel, ATError
from .controller import FXRemoteController, KEY_MAP
from .dtmf import CANDIDATES, Candidate, DtmfStrategy, tone_pair_for
from .voice_modem import VoiceModem

__all__ = [
    "ATChannel",
    "ATError",
    "CANDIDATES",
    "Candidate",
    "DtmfStrategy",
    "FXRemoteController",
    "KEY_MAP",
    "VoiceModem",
    "tone_pair_for",
]