import sys
import os
import io
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from PIL import Image

from processing.detector import FastLocalWatcher
from processing.models import WatcherSignal


def _make_jpeg(r=128, g=128, b=128, size=64) -> bytes:
    img = Image.new("RGB", (size, size), (r, g, b))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class FakeAudioChunk:
    def __init__(self, rms_value: float = 0.0):
        samples = np.full(1024, rms_value, dtype=np.int16)
        self.audio_bytes = samples.tobytes()


class TestFastLocalWatcher:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_no_frame(self):
        watcher = FastLocalWatcher()
        sig = self._run(watcher.compute_signal(None, "", [], ""))
        assert sig.frame_diff == 0.0
        assert sig.combined_score <= 0.20

    def test_first_frame_no_diff(self):
        watcher = FastLocalWatcher()
        frame = _make_jpeg(128, 128, 128)
        sig = self._run(watcher.compute_signal(frame, "", [], ""))
        assert sig.frame_diff == 0.0

    def test_identical_frames_zero_diff(self):
        watcher = FastLocalWatcher()
        frame = _make_jpeg(128, 128, 128)
        self._run(watcher.compute_signal(frame, "", [], ""))
        sig = self._run(watcher.compute_signal(frame, "", [], ""))
        assert sig.frame_diff < 1.0

    def test_different_frames_positive_diff(self):
        watcher = FastLocalWatcher()
        frame1 = _make_jpeg(0, 0, 0)
        frame2 = _make_jpeg(255, 255, 255)
        self._run(watcher.compute_signal(frame1, "", [], ""))
        sig = self._run(watcher.compute_signal(frame2, "", [], ""))
        assert sig.frame_diff > 100.0

    def test_ocr_change_detected(self):
        watcher = FastLocalWatcher()
        frame = _make_jpeg()
        self._run(watcher.compute_signal(frame, "hello world", [], ""))
        sig = self._run(watcher.compute_signal(frame, "completely different text", [], ""))
        assert sig.ocr_changed is True
        assert sig.ocr_similarity < 0.5

    def test_ocr_no_change(self):
        watcher = FastLocalWatcher()
        frame = _make_jpeg()
        self._run(watcher.compute_signal(frame, "same text", [], ""))
        sig = self._run(watcher.compute_signal(frame, "same text", [], ""))
        assert sig.ocr_changed is False
        assert sig.ocr_similarity == 1.0

    def test_text_density(self):
        watcher = FastLocalWatcher()
        frame = _make_jpeg()
        sig = self._run(watcher.compute_signal(frame, "x" * 100, [], ""))
        assert sig.text_density == 100

    def test_silence_detection(self):
        watcher = FastLocalWatcher()
        frame = _make_jpeg()
        sig = self._run(watcher.compute_signal(frame, "", [], ""))
        assert sig.is_silent

    def test_loud_audio_not_silent(self):
        watcher = FastLocalWatcher()
        frame = _make_jpeg()
        loud_chunks = [FakeAudioChunk(3000.0)]
        sig = self._run(watcher.compute_signal(frame, "", loud_chunks, ""))
        assert not sig.is_silent

    def test_sensitivity_update(self):
        watcher = FastLocalWatcher()
        default_frame_thr = watcher.frame_diff_threshold

        watcher.update_sensitivity(1.0)
        assert watcher.frame_diff_threshold < default_frame_thr

        watcher.update_sensitivity(0.0)
        assert watcher.frame_diff_threshold > default_frame_thr

    def test_active_window_title_passed(self):
        watcher = FastLocalWatcher()
        frame = _make_jpeg()
        sig = self._run(watcher.compute_signal(frame, "", [], "My App Window"))
        assert sig.active_window_title == "My App Window"
