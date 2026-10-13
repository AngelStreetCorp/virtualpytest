"""
Power Controller Implementations

This module contains controller implementations for power management:
- TapoPowerController: Tapo power control via SSH + uhubctl
- WOLPowerController: Wake-on-LAN to switch on, SSH shutdown to switch off
"""

from .tapo_power import TapoPowerController
from .wol_power import WOLPowerController

__all__ = [
    'TapoPowerController',
    'WOLPowerController'
]
