import uuid
import hashlib
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


class RealtimeState(Enum):
    OFF = "off"
    MONITORING = "monitoring"
    NARRATING = "narrating"


class EventType(Enum):
    NEW_SLIDE = "new_slide"
    DENSE_TEXT = "dense_text"
    CODE_CHANGE = "code_change"
    CHART_DIAGRAM = "chart_diagram"
    UI_DIALOG = "ui_dialog"
    SILENT_VISUAL = "silent_visual"
    GENERIC_VISUAL = "generic_visual"
    UNKNOWN = "unknown"


@dataclass
class WatcherSignal:
    timestamp: float
    frame_diff: float = 0.0
    ocr_changed: bool = False
    ocr_text: str = ""
    ocr_similarity: float = 1.0
    text_density: int = 0
    audio_rms: float = 0.0
    is_silent: bool = False
    layout_change: float = 0.0
    active_window_title: str = ""
    frame_bytes: Optional[bytes] = field(default=None, repr=False)


@dataclass
class FinalizedSegment:
    segment_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    start_ts: float = 0.0
    end_ts: float = 0.0
    event_type: EventType = EventType.UNKNOWN

    summary_status: str = "pending"
    pause_status: str = "pending"

    fingerprint: str = ""

    @staticmethod
    def compute_fingerprint(ocr_text: str, frame_bytes: Optional[bytes] = None) -> str:
        h = hashlib.sha256()
        normalized = " ".join(ocr_text.lower().split())
        h.update(normalized.encode("utf-8"))
        if frame_bytes:
            h.update(frame_bytes[:4096])
        return h.hexdigest()[:24]


@dataclass
class FrozenSnapshot:
    segment_id: str = ""
    event_type: EventType = EventType.UNKNOWN

    frames: List[bytes] = field(default_factory=list, repr=False)
    ocr_texts: List[str] = field(default_factory=list)
    audio_bytes: bytes = field(default=b"", repr=False)
    audio_sample_rate: int = 0
    audio_channels: int = 0

    start_ts: float = 0.0
    end_ts: float = 0.0
    event_metadata: Dict[str, Any] = field(default_factory=dict)
    active_window_title: str = ""


@dataclass
class ConsumedTimeline:
    timeline_ts: float = 0.0
    last_fingerprints: List[str] = field(default_factory=list)
    _max_fingerprints: int = 20

    def advance(self, ts: float, fingerprint: str):
        self.timeline_ts = max(self.timeline_ts, ts)
        self.last_fingerprints.append(fingerprint)
        if len(self.last_fingerprints) > self._max_fingerprints:
            self.last_fingerprints = self.last_fingerprints[-self._max_fingerprints:]

    def is_duplicate(self, fingerprint: str) -> bool:
        return fingerprint in self.last_fingerprints
