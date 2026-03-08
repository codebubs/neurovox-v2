import uuid
import hashlib
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


class RealtimeState(Enum):
    OFF = "off"
    MONITORING = "monitoring"
    CANDIDATE_OPEN = "candidate_open"
    CANDIDATE_ACCUMULATING = "candidate_accumulating"
    READY_TO_PAUSE = "ready_to_pause"
    PAUSED_FOR_CLARIFICATION = "paused_for_clarification"
    SPEAKING = "speaking"
    COOLDOWN = "cooldown"


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

    @property
    def combined_score(self) -> float:
        score = 0.0
        if self.frame_diff > 8.0:
            score += min(self.frame_diff / 30.0, 1.0) * 0.35
        if self.ocr_changed and self.text_density >= 5:
            score += (1.0 - self.ocr_similarity) * 0.35
        if self.is_silent:
            score += 0.15
        if self.layout_change > 0.1:
            score += min(self.layout_change, 1.0) * 0.15
        return min(score, 1.0)


@dataclass
class CandidateEvent:
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    opened_at: float = field(default_factory=time.time)
    anchor_ts: float = 0.0

    signals: List[WatcherSignal] = field(default_factory=list)
    peak_frame_diff: float = 0.0
    peak_ocr_text: str = ""
    peak_text_density: int = 0
    mean_audio_rms: float = 0.0

    event_type_hypothesis: EventType = EventType.UNKNOWN
    confidence_score: float = 0.0

    is_accumulating: bool = True
    is_pause_worthy: bool = False

    def add_signal(self, signal: WatcherSignal):
        self.signals.append(signal)
        if signal.frame_diff > self.peak_frame_diff:
            self.peak_frame_diff = signal.frame_diff
            self.anchor_ts = signal.timestamp
        if signal.text_density > self.peak_text_density:
            self.peak_text_density = signal.text_density
            self.peak_ocr_text = signal.ocr_text
        n = len(self.signals)
        self.mean_audio_rms = (self.mean_audio_rms * (n - 1) + signal.audio_rms) / n

    @property
    def duration(self) -> float:
        return time.time() - self.opened_at


@dataclass
class FinalizedSegment:
    segment_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    start_ts: float = 0.0
    anchor_ts: float = 0.0
    end_ts: float = 0.0
    event_type: EventType = EventType.UNKNOWN
    confidence: float = 0.0

    summary_status: str = "pending"
    pause_status: str = "pending"
    consumed: bool = False

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
    anchor_ts: float = 0.0
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

    def is_after_timeline(self, ts: float) -> bool:
        return ts > self.timeline_ts
