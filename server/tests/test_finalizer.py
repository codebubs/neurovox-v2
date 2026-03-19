import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from processing.models import (
    FinalizedSegment,
    ConsumedTimeline,
)
from processing.finalizer import EventFinalizer


class _Frame:
    def __init__(self, ts, data=b"\x00" * 100):
        self.timestamp = ts
        self.image_bytes = data


class _Ocr:
    def __init__(self, ts, text):
        self.timestamp = ts
        self.text = text


class _Audio:
    def __init__(self, ts, data=b"\x00" * 100):
        self.timestamp = ts
        self.audio_bytes = data
        self.sample_rate = 16000
        self.channels = 1


class _BufferManager:
    def __init__(self, frames=None, ocr=None, audio=None):
        self._frames = frames or []
        self._ocr = ocr or []
        self._audio = audio or []

    def get_frames_in_range(self, start, end):
        return [f for f in self._frames if start <= f.timestamp <= end]

    def get_ocr_in_range(self, start, end):
        return [o for o in self._ocr if start <= o.timestamp <= end]

    def get_audio_in_range(self, start, end):
        return [a for a in self._audio if start <= a.timestamp <= end]


class TestShouldNarrate:
    def test_first_narration_allowed(self):
        finalizer = EventFinalizer()
        timeline = ConsumedTimeline()
        bm = _BufferManager(
            frames=[_Frame(1.0)],
            ocr=[_Ocr(1.0, "hello")],
        )
        segment, should = finalizer.should_narrate(timeline, bm)
        assert should is True
        assert segment is not None

    def test_duplicate_rejected(self):
        finalizer = EventFinalizer()
        timeline = ConsumedTimeline()
        bm = _BufferManager(
            frames=[_Frame(1.0, b"\xaa" * 100)],
            ocr=[_Ocr(1.0, "same text")],
        )
        seg1, _ = finalizer.should_narrate(timeline, bm)
        timeline.advance(1.0, seg1.fingerprint)

        seg2, should2 = finalizer.should_narrate(timeline, bm)
        assert should2 is False
        assert seg2 is None

    def test_different_content_allowed(self):
        finalizer = EventFinalizer()
        timeline = ConsumedTimeline()
        bm1 = _BufferManager(
            frames=[_Frame(1.0, b"\xaa" * 100)],
            ocr=[_Ocr(1.0, "first text")],
        )
        seg1, _ = finalizer.should_narrate(timeline, bm1)
        timeline.advance(1.0, seg1.fingerprint)

        bm2 = _BufferManager(
            frames=[_Frame(2.0, b"\xbb" * 100)],
            ocr=[_Ocr(2.0, "different text")],
        )
        seg2, should2 = finalizer.should_narrate(timeline, bm2)
        assert should2 is True
        assert seg2 is not None


class TestFreezeSnapshot:
    def test_snapshot_captures_frames(self):
        finalizer = EventFinalizer()
        segment = FinalizedSegment(start_ts=0.0, end_ts=5.0)
        bm = _BufferManager(
            frames=[_Frame(i) for i in range(6)],
            ocr=[_Ocr(1.0, "text")],
            audio=[_Audio(1.0)],
        )
        snap = finalizer.freeze_snapshot(segment, bm)
        assert len(snap.frames) == 6
        assert len(snap.ocr_texts) == 1
        assert snap.start_ts == 0.0
        assert snap.end_ts == 5.0

    def test_snapshot_few_frames(self):
        finalizer = EventFinalizer()
        segment = FinalizedSegment(start_ts=0.0, end_ts=2.0)
        bm = _BufferManager(
            frames=[_Frame(0.0), _Frame(1.0), _Frame(2.0)],
        )
        snap = finalizer.freeze_snapshot(segment, bm)
        assert len(snap.frames) == 3

    def test_snapshot_no_audio(self):
        finalizer = EventFinalizer()
        segment = FinalizedSegment(start_ts=0.0, end_ts=1.0)
        bm = _BufferManager(frames=[_Frame(0.5)])
        snap = finalizer.freeze_snapshot(segment, bm)
        assert snap.audio_bytes == b""
        assert snap.audio_sample_rate == 0
