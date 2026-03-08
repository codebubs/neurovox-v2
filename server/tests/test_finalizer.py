import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from processing.models import (
    WatcherSignal,
    CandidateEvent,
    FinalizedSegment,
    ConsumedTimeline,
    EventType,
)
from processing.finalizer import EventFinalizer


def _make_signal(
    frame_diff=0.0,
    ocr_text="",
    ocr_changed=False,
    ocr_similarity=1.0,
    text_density=0,
    audio_rms=0.0,
    is_silent=True,
    frame_bytes=None,
    timestamp=None,
):
    return WatcherSignal(
        timestamp=timestamp or time.time(),
        frame_diff=frame_diff,
        ocr_changed=ocr_changed,
        ocr_text=ocr_text,
        ocr_similarity=ocr_similarity,
        text_density=text_density,
        audio_rms=audio_rms,
        is_silent=is_silent,
        frame_bytes=frame_bytes or b"\x00" * 100,
    )


class TestEventFinalizer:
    def test_open_candidate(self):
        finalizer = EventFinalizer()
        sig = _make_signal(frame_diff=20.0)
        candidate = finalizer.open_candidate(sig)
        assert candidate.event_id
        assert len(candidate.signals) == 1

    def test_accumulate(self):
        finalizer = EventFinalizer()
        sig1 = _make_signal(frame_diff=20.0)
        candidate = finalizer.open_candidate(sig1)

        sig2 = _make_signal(frame_diff=5.0, text_density=50, ocr_text="hello world")
        finalizer.accumulate(candidate, sig2)

        assert len(candidate.signals) == 2
        assert candidate.peak_frame_diff == 20.0
        assert candidate.peak_text_density == 50

    def test_should_keep_accumulating_within_window(self):
        finalizer = EventFinalizer(accumulation_window_sec=1.0)
        sig = _make_signal(frame_diff=20.0)
        candidate = finalizer.open_candidate(sig)
        assert finalizer.should_keep_accumulating(candidate) is True

    def test_should_stop_accumulating_after_window(self):
        finalizer = EventFinalizer(accumulation_window_sec=0.0)
        sig = _make_signal(frame_diff=20.0)
        candidate = finalizer.open_candidate(sig)
        candidate.opened_at = time.time() - 1.0
        assert finalizer.should_keep_accumulating(candidate) is False

    def test_early_settle(self):
        finalizer = EventFinalizer(accumulation_window_sec=5.0, settle_threshold=5.0)
        sig1 = _make_signal(frame_diff=20.0)
        candidate = finalizer.open_candidate(sig1)
        sig2 = _make_signal(frame_diff=2.0)
        finalizer.accumulate(candidate, sig2)
        assert finalizer.should_keep_accumulating(candidate) is False

    def test_finalize_accepted(self):
        finalizer = EventFinalizer(min_confidence=0.1)
        timeline = ConsumedTimeline()

        sig = _make_signal(frame_diff=25.0, ocr_text="New slide content", text_density=40, ocr_changed=True, ocr_similarity=0.2)
        candidate = finalizer.open_candidate(sig)

        segment, is_pause_worthy = finalizer.try_finalize(candidate, timeline)
        assert segment is not None
        assert segment.fingerprint != ""
        assert segment.start_ts > 0

    def test_finalize_rejected_low_confidence(self):
        finalizer = EventFinalizer(min_confidence=0.9)
        timeline = ConsumedTimeline()

        sig = _make_signal(frame_diff=2.0, text_density=1)
        candidate = finalizer.open_candidate(sig)

        segment, is_pause_worthy = finalizer.try_finalize(candidate, timeline)
        assert segment is None

    def test_finalize_rejected_duplicate(self):
        finalizer = EventFinalizer(min_confidence=0.1)
        timeline = ConsumedTimeline()

        sig = _make_signal(frame_diff=25.0, ocr_text="Hello World", text_density=40, ocr_changed=True, ocr_similarity=0.2)
        candidate1 = finalizer.open_candidate(sig)
        segment1, _ = finalizer.try_finalize(candidate1, timeline)
        assert segment1 is not None

        timeline.advance(segment1.end_ts, segment1.fingerprint)

        sig2 = _make_signal(frame_diff=25.0, ocr_text="Hello World", text_density=40, ocr_changed=True, ocr_similarity=0.2)
        candidate2 = finalizer.open_candidate(sig2)
        segment2, _ = finalizer.try_finalize(candidate2, timeline)
        assert segment2 is None

    def test_classify_new_slide(self):
        finalizer = EventFinalizer()
        candidate = CandidateEvent()
        candidate.peak_text_density = 50
        candidate.peak_ocr_text = "• Bullet point on slide"
        candidate.peak_frame_diff = 15.0
        candidate.mean_audio_rms = 100.0

        event_type = finalizer._classify(candidate)
        assert event_type == EventType.NEW_SLIDE

    def test_classify_code(self):
        finalizer = EventFinalizer()
        candidate = CandidateEvent()
        candidate.peak_text_density = 100
        candidate.peak_ocr_text = "def my_function():\n    import os\n    return True"
        candidate.peak_frame_diff = 10.0

        event_type = finalizer._classify(candidate)
        assert event_type == EventType.CODE_CHANGE

    def test_classify_silent_visual(self):
        finalizer = EventFinalizer()
        candidate = CandidateEvent()
        candidate.peak_text_density = 3
        candidate.peak_ocr_text = "abc"
        candidate.peak_frame_diff = 25.0
        candidate.mean_audio_rms = 100.0

        event_type = finalizer._classify(candidate)
        assert event_type == EventType.SILENT_VISUAL

    def test_pause_worthy_high_value(self):
        finalizer = EventFinalizer()
        candidate = CandidateEvent()
        candidate.peak_frame_diff = 20.0
        candidate.mean_audio_rms = 100.0

        assert finalizer._is_pause_worthy(candidate, EventType.NEW_SLIDE, 0.5) is True
        assert finalizer._is_pause_worthy(candidate, EventType.CODE_CHANGE, 0.5) is True

    def test_not_pause_worthy_audio_adequate(self):
        finalizer = EventFinalizer()
        candidate = CandidateEvent()
        candidate.peak_frame_diff = 10.0
        candidate.mean_audio_rms = 3000.0

        assert finalizer._is_pause_worthy(candidate, EventType.GENERIC_VISUAL, 0.3) is False

    def test_update_settings(self):
        finalizer = EventFinalizer()
        finalizer.update_settings(
            accumulation_window_sec=2.0,
            prefer_text_triggers=True,
            sensitivity=0.8,
        )
        assert finalizer.accumulation_window_sec == 2.0
        assert finalizer.prefer_text_triggers is True
        assert finalizer.min_confidence < 0.40
