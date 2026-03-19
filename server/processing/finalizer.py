import time
from loguru import logger

from processing.models import (
    EventType,
    FinalizedSegment,
    FrozenSnapshot,
    ConsumedTimeline,
)


class EventFinalizer:
    def __init__(self):
        pass

    def should_narrate(
        self, timeline: ConsumedTimeline, buffer_manager
    ) -> tuple[FinalizedSegment | None, bool]:
        now = time.time()
        since_ts = timeline.timeline_ts

        frames = buffer_manager.get_frames_in_range(since_ts, now)
        ocr_results = buffer_manager.get_ocr_in_range(since_ts, now)

        latest_ocr = ocr_results[-1].text if ocr_results else ""
        latest_frame_bytes = frames[-1].image_bytes if frames else None

        fingerprint = FinalizedSegment.compute_fingerprint(latest_ocr, latest_frame_bytes)

        if timeline.is_duplicate(fingerprint):
            logger.debug(f"Narration skipped: duplicate fingerprint")
            return None, False

        segment = FinalizedSegment(
            start_ts=since_ts,
            end_ts=now,
            event_type=EventType.GENERIC_VISUAL,
            fingerprint=fingerprint,
        )

        logger.info(
            f"Narration approved for segment {segment.segment_id}, "
            f"span={now - since_ts:.1f}s"
        )
        return segment, True

    def freeze_snapshot(
        self,
        segment: FinalizedSegment,
        buffer_manager,
    ) -> FrozenSnapshot:
        frames_data = buffer_manager.get_frames_in_range(
            segment.start_ts, segment.end_ts
        )
        frame_bytes_list = [f.image_bytes for f in frames_data]

        if len(frame_bytes_list) > 8:
            n = len(frame_bytes_list)
            indices = [int(i * (n - 1) / 7) for i in range(8)]
            frame_bytes_list = [frame_bytes_list[i] for i in indices]

        ocr_results = buffer_manager.get_ocr_in_range(
            segment.start_ts, segment.end_ts
        )
        ocr_texts = list(dict.fromkeys(o.text for o in ocr_results if o.text))

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
            end_ts=segment.end_ts,
            active_window_title="",
        )
        logger.debug(
            f"Snapshot frozen for segment {segment.segment_id}: "
            f"{len(snapshot.frames)} frames, "
            f"{len(snapshot.ocr_texts)} OCR texts, "
            f"{len(snapshot.audio_bytes)} audio bytes, "
            f"span={segment.end_ts - segment.start_ts:.1f}s"
        )
        return snapshot
