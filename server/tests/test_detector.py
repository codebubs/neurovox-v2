import sys
import os
import asyncio
import io
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from processing.detector import FastLocalWatcher
from processing.models import WatcherSignal


def _make_jpeg(color=128, size=64):
    img = Image.new("L", (size, size), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestFastLocalWatcher:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_first_signal_zero_diff(self):
        watcher = FastLocalWatcher()
        frame = _make_jpeg(128)
        sig = self._run(watcher.compute_signal(frame, "", []))
        assert sig.frame_diff == 0.0

    def test_different_frames_nonzero_diff(self):
        watcher = FastLocalWatcher()
        f1 = _make_jpeg(0)
        f2 = _make_jpeg(255)
        self._run(watcher.compute_signal(f1, "", []))
        sig = self._run(watcher.compute_signal(f2, "", []))
        assert sig.frame_diff > 0.0

    def test_identical_frames_zero_diff(self):
        watcher = FastLocalWatcher()
        f = _make_jpeg(100)
        self._run(watcher.compute_signal(f, "", []))
        sig = self._run(watcher.compute_signal(f, "", []))
        assert sig.frame_diff == 0.0

    def test_ocr_change_detection(self):
        watcher = FastLocalWatcher()
        f = _make_jpeg()
        self._run(watcher.compute_signal(f, "hello world", []))
        sig = self._run(watcher.compute_signal(f, "completely different text", []))
        assert sig.ocr_changed is True

    def test_ocr_no_change(self):
        watcher = FastLocalWatcher()
        f = _make_jpeg()
        self._run(watcher.compute_signal(f, "hello world", []))
        sig = self._run(watcher.compute_signal(f, "hello world", []))
        assert sig.ocr_changed is False

    def test_text_density(self):
        watcher = FastLocalWatcher()
        f = _make_jpeg()
        sig = self._run(watcher.compute_signal(f, "short", []))
        assert sig.text_density == 5

    def test_empty_audio_rms(self):
        watcher = FastLocalWatcher()
        f = _make_jpeg()
        sig = self._run(watcher.compute_signal(f, "", []))
        assert sig.audio_rms == 0.0

    def test_active_window_title(self):
        watcher = FastLocalWatcher()
        frame = _make_jpeg()
        sig = self._run(watcher.compute_signal(frame, "", [], "My App Window"))
        assert sig.active_window_title == "My App Window"

    def test_sensitivity_update(self):
        watcher = FastLocalWatcher()
        watcher.update_sensitivity(0.5)
        assert watcher.frame_diff_threshold == 13.0
