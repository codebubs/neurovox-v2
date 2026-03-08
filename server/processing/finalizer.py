import time
from loguru import logger

from processing.models import (
    CandidateEvent,
    EventType,
    FinalizedSegment,
    FrozenSnapshot,
    ConsumedTimeline,
    WatcherSignal,
)


class EventFinalizer:
    def __init__(
        self,
        accumulation_window_sec: float = 0.8,
        settle_threshold: float = 5.0,
        min_confidence: float = 0.25,
        prefer_text_triggers: bool = False,
    ):
        self.accumulation_window_sec = accumulation_window_sec
        self.settle_threshold = settle_threshold
        self.min_confidence = min_confidence
        self.prefer_text_triggers = prefer_text_triggers

    def open_candidate(self, trigger_signal: WatcherSignal) -> CandidateEvent:
        candidate = CandidateEvent(
            opened_at=trigger_signal.timestamp,
            anchor_ts=trigger_signal.timestamp,
        )
        candidate.add_signal(trigger_signal)
        logger.debug(
            f"Candidate {candidate.event_id} opened "
            f"(frame_diff={trigger_signal.frame_diff:.1f}, "
            f"ocr_changed={trigger_signal.ocr_changed}, "
            f"text_density={trigger_signal.text_density})"
        )
        return candidate

    def accumulate(self, candidate: CandidateEvent, signal: WatcherSignal):
        candidate.add_signal(signal)

    def should_keep_accumulating(self, candidate: CandidateEvent) -> bool:
        if candidate.duration >= self.accumulation_window_sec:
            return False

        if len(candidate.signals) >= 2:
            last = candidate.signals[-1]
            if last.frame_diff < self.settle_threshold:
                return False

        return True

    def try_finalize(
        self, candidate: CandidateEvent, timeline: ConsumedTimeline
    ) -> tuple[FinalizedSegment | None, bool]:
        candidate.is_accumulating = False

        event_type = self._classify(candidate)
        candidate.event_type_hypothesis = event_type

        confidence = self._score_confidence(candidate)
        candidate.confidence_score = confidence

        fingerprint = FinalizedSegment.compute_fingerprint(
            candidate.peak_ocr_text,
            candidate.signals[-1].frame_bytes if candidate.signals else None,
        )

        if timeline.is_duplicate(fingerprint):
            logger.debug(
                f"Candidate {candidate.event_id} rejected: duplicate fingerprint"
            )
            return None, False

        if confidence < self.min_confidence:
            logger.debug(
                f"Candidate {candidate.event_id} rejected: low confidence "
                f"{confidence:.2f} < {self.min_confidence:.2f}"
            )
            return None, False

        is_pause_worthy = self._is_pause_worthy(candidate, event_type, confidence)
        candidate.is_pause_worthy = is_pause_worthy

        start_ts = candidate.opened_at
        end_ts = candidate.signals[-1].timestamp if candidate.signals else time.time()

        segment = FinalizedSegment(
            start_ts=start_ts,
            anchor_ts=candidate.anchor_ts,
            end_ts=end_ts,
            event_type=event_type,
            confidence=confidence,
            fingerprint=fingerprint,
        )

        logger.info(
            f"Candidate {candidate.event_id} finalized to segment {segment.segment_id} "
            f"(type={event_type.value}, conf={confidence:.2f}, "
            f"pause_worthy={is_pause_worthy})"
        )
        return segment, is_pause_worthy

    def freeze_snapshot(
        self,
        candidate: CandidateEvent,
        segment: FinalizedSegment,
        buffer_manager,
    ) -> FrozenSnapshot:
        frames_data = buffer_manager.get_frames_in_range(
            segment.start_ts, segment.end_ts
        )
        frame_bytes_list = [f.image_bytes for f in frames_data]

        if len(frame_bytes_list) > 3:
            n = len(frame_bytes_list)
            indices = [0, n // 2, n - 1]
            frame_bytes_list = [frame_bytes_list[i] for i in indices]
        ocr_texts = list(
            dict.fromkeys(
                s.ocr_text for s in candidate.signals if s.ocr_text
            )
        )

        audio_chunks = buffer_manager.get_audio_in_range(
            segment.start_ts, segment.end_ts
        )
        audio_bytes = b"".join(c.audio_bytes for c in audio_chunks)
        sample_rate = audio_chunks[0].sample_rate if audio_chunks else 0
        channels = audio_chunks[0].channels if audio_chunks else 0

        snapshot = FrozenSnapshot(
            segment_id=segment.segment_id,
            event_type=segment.event_type,
            frames=frame_bytes_list,
            ocr_texts=ocr_texts,
            audio_bytes=audio_bytes,
            audio_sample_rate=sample_rate,
            audio_channels=channels,
            start_ts=segment.start_ts,
            anchor_ts=segment.anchor_ts,
            end_ts=segment.end_ts,
            active_window_title=(
                candidate.signals[-1].active_window_title
                if candidate.signals else ""
            ),
            event_metadata={
                "peak_frame_diff": candidate.peak_frame_diff,
                "peak_text_density": candidate.peak_text_density,
                "mean_audio_rms": candidate.mean_audio_rms,
                "num_signals": len(candidate.signals),
            },
        )
        logger.debug(
            f"Snapshot frozen for segment {segment.segment_id}: "
            f"{len(snapshot.frames)} frames, "
            f"{len(snapshot.ocr_texts)} OCR texts, "
            f"{len(snapshot.audio_bytes)} audio bytes"
        )
        return snapshot

    def _classify(self, candidate: CandidateEvent) -> EventType:
        text = candidate.peak_ocr_text.lower()
        density = candidate.peak_text_density
        mean_rms = candidate.mean_audio_rms

        if density > 30 and any(
            kw in text for kw in ["slide", "page", "chapter", "•"]
        ):
            return EventType.NEW_SLIDE

        code_chars = sum(1 for c in text if c in "{}[]();=<>")
        if code_chars > 5 or (density > 20 and "def " in text or "class " in text
                               or "function" in text or "import " in text):
            return EventType.CODE_CHANGE

        if density > 100:
            return EventType.DENSE_TEXT

        if density > 10 and density < 80 and candidate.peak_frame_diff > 20:
            return EventType.UI_DIALOG

        if candidate.peak_frame_diff > 15 and mean_rms < 500:
            return EventType.SILENT_VISUAL

        if candidate.peak_frame_diff > 20 and density < 15:
            return EventType.CHART_DIAGRAM

        if candidate.peak_frame_diff > 10 or density > 5:
            return EventType.GENERIC_VISUAL

        return EventType.UNKNOWN

    def _score_confidence(self, candidate: CandidateEvent) -> float:
        score = 0.0

        if candidate.peak_frame_diff > 8:
            score += min(candidate.peak_frame_diff / 40.0, 0.35)

        if candidate.peak_text_density > 5:
            score += min(candidate.peak_text_density / 200.0, 0.30)

        max_ocr_change = 0.0
        for s in candidate.signals:
            if s.ocr_changed:
                max_ocr_change = max(max_ocr_change, 1.0 - s.ocr_similarity)
        score += max_ocr_change * 0.25

        silent_ticks = sum(1 for s in candidate.signals if s.is_silent)
        if len(candidate.signals) > 0:
            silence_ratio = silent_ticks / len(candidate.signals)
            score += silence_ratio * 0.10

        if self.prefer_text_triggers and candidate.peak_text_density > 20:
            score += 0.10

        return min(score, 1.0)

    def _is_pause_worthy(
        self,
        candidate: CandidateEvent,
        event_type: EventType,
        confidence: float,
    ) -> bool:
        high_value = {
            EventType.NEW_SLIDE,
            EventType.DENSE_TEXT,
            EventType.CODE_CHANGE,
            EventType.CHART_DIAGRAM,
            EventType.UI_DIALOG,
            EventType.SILENT_VISUAL,
        }
        if event_type in high_value and confidence >= 0.30:
            return True

        if event_type == EventType.GENERIC_VISUAL and confidence >= 0.50:
            return True

        if candidate.mean_audio_rms > 2000 and candidate.peak_frame_diff < 20:
            return False

        return False

    def update_settings(
        self,
        accumulation_window_sec: float | None = None,
        prefer_text_triggers: bool | None = None,
        sensitivity: float | None = None,
    ):
        if accumulation_window_sec is not None:
            self.accumulation_window_sec = accumulation_window_sec
        if prefer_text_triggers is not None:
            self.prefer_text_triggers = prefer_text_triggers
        if sensitivity is not None:
            self.min_confidence = 0.40 - (sensitivity * 0.25)
