import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from processing.models import (
    RealtimeState,
    EventType,
    WatcherSignal,
    FinalizedSegment,
    FrozenSnapshot,
    ConsumedTimeline,
)


class TestRealtimeState:
    def test_all_states_exist(self):
        states = [s.value for s in RealtimeState]
        assert "off" in states
        assert "monitoring" in states
        assert "narrating" in states
        assert len(states) == 3


class TestEventType:
    def test_all_types_exist(self):
        types = [t.value for t in EventType]
        assert "new_slide" in types
        assert "code_change" in types
        assert "dense_text" in types
        assert "generic_visual" in types
        assert "unknown" in types


class TestWatcherSignal:
    def test_default_values(self):
        sig = WatcherSignal(timestamp=1.0)
        assert sig.frame_diff == 0.0
        assert sig.ocr_changed is False

    def test_fields_stored(self):
        sig = WatcherSignal(timestamp=1.0, frame_diff=30.0, is_silent=True)
        assert sig.frame_diff == 30.0
        assert sig.is_silent is True


class TestFinalizedSegment:
    def test_compute_fingerprint(self):
        fp1 = FinalizedSegment.compute_fingerprint("Hello World")
        fp2 = FinalizedSegment.compute_fingerprint("Hello World")
        fp3 = FinalizedSegment.compute_fingerprint("Goodbye World")

        assert fp1 == fp2
        assert fp1 != fp3
        assert len(fp1) == 24

    def test_fingerprint_with_frame(self):
        fp1 = FinalizedSegment.compute_fingerprint("test", b"\x00" * 100)
        fp2 = FinalizedSegment.compute_fingerprint("test", b"\xff" * 100)
        assert fp1 != fp2

    def test_defaults(self):
        seg = FinalizedSegment()
        assert seg.summary_status == "pending"
        assert seg.pause_status == "pending"


class TestFrozenSnapshot:
    def test_defaults(self):
        snap = FrozenSnapshot()
        assert snap.frames == []
        assert snap.ocr_texts == []
        assert snap.audio_bytes == b""
        assert snap.event_type == EventType.UNKNOWN


class TestConsumedTimeline:
    def test_advance(self):
        timeline = ConsumedTimeline()
        assert timeline.timeline_ts == 0.0

        timeline.advance(10.0, "fp_1")
        assert timeline.timeline_ts == 10.0
        assert "fp_1" in timeline.last_fingerprints

    def test_is_duplicate(self):
        timeline = ConsumedTimeline()
        timeline.advance(1.0, "fp_1")
        timeline.advance(2.0, "fp_2")

        assert timeline.is_duplicate("fp_1")
        assert timeline.is_duplicate("fp_2")
        assert not timeline.is_duplicate("fp_3")

    def test_fingerprint_pruning(self):
        timeline = ConsumedTimeline()
        for i in range(30):
            timeline.advance(float(i), f"fp_{i}")

        assert len(timeline.last_fingerprints) == 20
        assert not timeline.is_duplicate("fp_0")
        assert timeline.is_duplicate("fp_29")
