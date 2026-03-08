import io
import time
import numpy as np
from PIL import Image
from difflib import SequenceMatcher
from loguru import logger

from processing.models import WatcherSignal


class FastLocalWatcher:
    def __init__(
        self,
        frame_diff_threshold: float = 8.0,
        silence_rms_threshold: float = 1500.0,
        ocr_change_threshold: float = 0.80,
        min_text_density: int = 5,
    ):
        self.frame_diff_threshold = frame_diff_threshold
        self.silence_rms_threshold = silence_rms_threshold
        self.ocr_change_threshold = ocr_change_threshold
        self.min_text_density = min_text_density

        self._last_frame_thumb: np.ndarray | None = None
        self._last_ocr_text: str = ""
        self._last_layout_hash: str = ""

    async def compute_signal(
        self,
        frame_bytes: bytes | None,
        ocr_text: str,
        audio_chunks: list,
        active_window_title: str = "",
    ) -> WatcherSignal:
        now = time.time()

        frame_diff = 0.0
        thumb = None
        if frame_bytes:
            try:
                thumb = self._to_thumbnail(frame_bytes)
                if self._last_frame_thumb is not None:
                    frame_diff = float(
                        np.mean(np.abs(thumb.astype(np.int16) - self._last_frame_thumb.astype(np.int16)))
                    )
            except Exception as e:
                logger.debug(f"Watcher frame diff error: {e}")
            self._last_frame_thumb = thumb

        ocr_similarity = 1.0
        ocr_changed = False
        if ocr_text and self._last_ocr_text:
            ocr_similarity = SequenceMatcher(None, ocr_text, self._last_ocr_text).ratio()
            ocr_changed = ocr_similarity < self.ocr_change_threshold
        elif ocr_text and not self._last_ocr_text:
            ocr_changed = True
            ocr_similarity = 0.0

        text_density = len(ocr_text.strip()) if ocr_text else 0

        if ocr_text is not None:
            self._last_ocr_text = ocr_text

        rms = self._compute_rms(audio_chunks)
        is_silent = rms < self.silence_rms_threshold

        layout_change = self._estimate_layout_change(ocr_text)

        signal = WatcherSignal(
            timestamp=now,
            frame_diff=frame_diff,
            ocr_changed=ocr_changed,
            ocr_text=ocr_text or "",
            ocr_similarity=ocr_similarity,
            text_density=text_density,
            audio_rms=rms,
            is_silent=is_silent,
            layout_change=layout_change,
            active_window_title=active_window_title,
            frame_bytes=frame_bytes,
        )
        return signal

    def update_sensitivity(self, sensitivity: float):
        sensitivity = max(0.0, min(1.0, sensitivity))
        self.frame_diff_threshold = 15.0 - (sensitivity * 12.0)
        self.silence_rms_threshold = 1000.0 + (sensitivity * 2000.0)
        self.ocr_change_threshold = 0.90 - (sensitivity * 0.25)
        logger.debug(
            f"Watcher sensitivity={sensitivity:.2f}"
            f"frame_diff_thr={self.frame_diff_threshold:.1f}, "
            f"silence_rms_thr={self.silence_rms_threshold:.0f}, "
            f"ocr_change_thr={self.ocr_change_threshold:.2f}"
        )

    @staticmethod
    def _to_thumbnail(jpeg_bytes: bytes, size: int = 64) -> np.ndarray:
        img = Image.open(io.BytesIO(jpeg_bytes)).convert("L").resize((size, size))
        return np.array(img, dtype=np.uint8)

    @staticmethod
    def _compute_rms(audio_chunks: list) -> float:
        if not audio_chunks:
            return 0.0
        all_bytes = b"".join(c.audio_bytes for c in audio_chunks)
        if not all_bytes:
            return 0.0
        try:
            audio_data = np.frombuffer(all_bytes, dtype=np.int16).astype(np.float32)
            if len(audio_data) == 0:
                return 0.0
            return float(np.sqrt(np.mean(np.square(audio_data))))
        except Exception:
            return 0.0

    def _estimate_layout_change(self, ocr_text: str) -> float:
        if not ocr_text:
            return 0.0
        lines = ocr_text.strip().splitlines()
        layout_hash = "|".join(str(len(l)) for l in lines[:20])
        if not self._last_layout_hash:
            self._last_layout_hash = layout_hash
            return 0.0
        similarity = SequenceMatcher(None, layout_hash, self._last_layout_hash).ratio()
        self._last_layout_hash = layout_hash
        return 1.0 - similarity
