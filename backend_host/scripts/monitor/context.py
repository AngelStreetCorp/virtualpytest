"""What one frame looks like to an analyzer."""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class FrameContext:
    capture_folder: str
    device_index: Optional[int]       # N of DEVICE{N}; None until goal 7 resolves it
    sequence: int
    timestamp: float
    frame_path: str
    thumbnail: Any                    # 320x180 gray ndarray loaded once by core; None until an analyzer needs it
    device_state: dict                # per-device mutable state owned by the incident manager
    profile: Any                      # resolved Profile; None until goal 3
    # Fields the tv_app analyzer needs from the core's per-frame bookkeeping:
    filename: str = ''
    device_id: str = ''
    queue_size: int = 0
    json_file: str = ''
    needs_detection: bool = True      # False when the JSON already exists and is analyzed (audio-only update)
    audio: dict = field(default_factory=dict)  # audio status already merged by core (audio, mean_volume_db, ...)
