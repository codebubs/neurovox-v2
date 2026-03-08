import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from processing.models import (
    RealtimeState,
    EventType,
    WatcherSignal,
    CandidateEvent,
    FinalizedSegment,
    FrozenSnapshot,
    ConsumedTimeline,
)


class TestRealtimeState:
    def test_all_states_exist(self):
        states = [s.value for s in RealtimeState]
        assert "off" in states
        assert "monitoring" in states
        assert "candidate_open" in states
        assert "candidate_accumulating" in states
        assert "ready_to_pause" in states
        assert "paused_for_clarification" in states
        assert "speaking" in states
        assert "cooldown" in states
        assert len(states) == 8


class TestEventType:
    def test_all_types_exist(self):
        types = [t.value for t in EventType]
        assert "new_slide" in types
        assert "code_change" in types
        assert "dense_text" in types
        assert "chart_diagram" in types
        assert "ui_dialog" in types
        assert "silent_visual" in types
        assert "generic_visual" in types
        assert "unknown" in types


class TestWatcherSignal:
    def test_default_values(self):
        sig = WatcherSignal(timestamp=1.0)
        assert sig.frame_diff == 0.0
        assert sig.ocr_changed is False
        assert sig.combined_score == 0.0

    def test_combined_score_visual_only(self):
        sig = WatcherSignal(timestamp=1.0, frame_diff=30.0)
        assert sig.combined_score > 0.0

    def test_combined_score_text_change(self):
        sig = WatcherSignal(
            timestamp=1.0,
            ocr_changed=True,
            ocr_similarity=0.2,
            text_density=50,
        )
        assert sig.combined_score > 0.0

    def test_combined_score_silence_bonus(self):
        sig_no_silence = WatcherSignal(
            timestamp=1.0, frame_diff=20.0, is_silent=False
        )
        sig_silence = WatcherSignal(
            timestamp=1.0, frame_diff=20.0, is_silent=True
        )
        assert sig_silence.combined_score > sig_no_silence.combined_score

    def test_score_capped_at_one(self):
        sig = WatcherSignal(
            timestamp=1.0,
            frame_diff=100.0,
            ocr_changed=True,
            ocr_similarity=0.0,
            text_density=200,
            is_silent=True,
            layout_change=1.0,
        )
        assert sig.combined_score <= 1.0


class TestCandidateEvent:
    def test_add_signal_updates_peak(self):
        candidate = CandidateEvent()
        sig1 = WatcherSignal(timestamp=1.0, frame_diff=10.0, text_density=20, ocr_text="hello")
        sig2 = WatcherSignal(timestamp=2.0, frame_diff=30.0, text_density=50, ocr_text="world")
        candidate.add_signal(sig1)
        candidate.add_signal(sig2)

        assert candidate.peak_frame_diff == 30.0
        assert candidate.peak_text_density == 50
        assert candidate.anchor_ts == 2.0
        assert len(candidate.signals) == 2

    def test_duration(self):
        candidate = CandidateEvent(opened_at=time.time() - 1.0)
        assert candidate.duration >= 1.0

    def test_event_id_unique(self):
        c1 = CandidateEvent()
        c2 = CandidateEvent()
        assert c1.event_id != c2.event_id


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
        assert seg.consumed is False


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

    def test_is_after_timeline(self):
        timeline = ConsumedTimeline()
        timeline.advance(10.0, "fp")
        
        assert timeline.is_after_timeline(11.0)
        assert not timeline.is_after_timeline(10.0)
        assert not timeline.is_after_timeline(9.0)
