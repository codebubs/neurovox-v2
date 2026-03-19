import asyncio
import time
from loguru import logger

from buffer_manager import buffer_manager, OcrResult
from processing.models import (
    RealtimeState,
    ConsumedTimeline,
)
from processing.detector import FastLocalWatcher
from processing.finalizer import EventFinalizer
from processing.pause_helper import PauseHelper
from processing.llm import llm_processor

_event_queue: asyncio.Queue | None = None


def get_event_queue() -> asyncio.Queue:
    global _event_queue
    if _event_queue is None:
        _event_queue = asyncio.Queue()
    return _event_queue


class RealtimeEngine:
    def __init__(self):
        self.state: RealtimeState = RealtimeState.OFF
        self.timeline = ConsumedTimeline()

        self.watcher = FastLocalWatcher()
        self.finalizer = EventFinalizer()
        self.helper = PauseHelper()

        self.narration_interval: float = 10.0
        self._timer_start: float = 0.0

        self.tick_interval: float = 0.25
        self.ocr_every_n_ticks: int = 2
        self._tick_count: int = 0
        self._last_ocr_text: str = ""
        self.debug_mode: bool = False
        self.verbosity: str = "concise"
        self.capture_active_window: bool = False

        self._llm_task: asyncio.Task | None = None
        self._llm_result: str | None = None
        self._llm_segment = None
        self._last_narration_text: str = ""

        self._debug_log: list[dict] = []
        self._max_debug_entries: int = 200

    def _transition(self, new_state: RealtimeState, reason: str = ""):
        old = self.state
        self.state = new_state
        msg = f"State: {old.value} -> {new_state.value}"
        if reason:
            msg += f" ({reason})"
        logger.info(msg)
        self._record_debug("state_transition", {
            "from": old.value, "to": new_state.value, "reason": reason
        })

    def enable(self):
        if self.state == RealtimeState.OFF:
            self.timeline = ConsumedTimeline()
            self._timer_start = time.time()
            self.timeline.timeline_ts = self._timer_start
            self._transition(RealtimeState.MONITORING, "realtime enabled")

    def disable(self):
        if self._llm_task and not self._llm_task.done():
            self._llm_task.cancel()
        self._llm_task = None
        self._llm_result = None
        self._llm_segment = None
        self._transition(RealtimeState.OFF, "realtime disabled")

    async def run(self):
        logger.info("Realtime loop started")
        while True:
            try:
                if self.state == RealtimeState.OFF:
                    await asyncio.sleep(0.5)
                    continue

                if self.state == RealtimeState.MONITORING:
                    await self._tick_monitoring()

                elif self.state == RealtimeState.NARRATING:
                    await self._tick_narrating()

            except asyncio.CancelledError:
                logger.info("Realtime loop cancelled")
                break
            except Exception as e:
                logger.error(f"RealtimeEngine error: {e}")
                self._record_debug("error", {"error": str(e)})

            await asyncio.sleep(self.tick_interval)

    async def _tick_monitoring(self):
        signal = await self._collect_signal()

        elapsed = time.time() - self._timer_start

        if self._llm_task is not None and self._llm_task.done():
            try:
                self._llm_result = self._llm_task.result()
            except Exception as e:
                logger.error(f"Background LLM call failed: {e}")
                self._llm_result = None
            self._llm_task = None

            if self._llm_result and self._llm_segment:
                self._transition(RealtimeState.NARRATING, "LLM response ready")
                return
            else:
                self._llm_segment = None
                self._reset_timer()

        if self._llm_task is None and elapsed >= self.narration_interval:
            segment, should = self.finalizer.should_narrate(
                self.timeline, buffer_manager
            )
            if should and segment is not None:
                snapshot = self.finalizer.freeze_snapshot(segment, buffer_manager)
                self._llm_segment = segment
                prev = self._last_narration_text
                self._llm_task = asyncio.create_task(
                    asyncio.to_thread(
                        llm_processor.generate_clarification,
                        snapshot, self.verbosity, prev
                    )
                )
                self._record_debug("llm_dispatched", {
                    "segment_id": segment.segment_id,
                    "span": round(segment.end_ts - segment.start_ts, 1),
                })
            else:
                self._reset_timer()
                self._record_debug("narration_skipped", {"reason": "duplicate"})

    async def _tick_narrating(self):
        segment = self._llm_segment
        narration_text = self._llm_result
        self._llm_segment = None
        self._llm_result = None

        system_paused = await self.helper.pause_media()
        segment.pause_status = "paused" if system_paused else "skipped"
        segment.summary_status = "done"

        self._record_debug("narration_speaking", {
            "segment_id": segment.segment_id,
            "length": len(narration_text),
            "paused": system_paused,
        })

        event_queue = get_event_queue()
        await event_queue.put({
            "type": "speak",
            "text": narration_text,
            "timestamp": time.time(),
            "segment_id": segment.segment_id,
        })

        await self.helper.handle_post_clarification(
            narration_text, system_paused, event_queue
        )
        self._last_narration_text = narration_text
        self.helper.advance_timeline(self.timeline, segment)
        buffer_manager.add_segment(segment)
        self._reset_timer()
        self._transition(RealtimeState.MONITORING, "narration complete")

    def _reset_timer(self):
        self._timer_start = time.time()

    async def _collect_signal(self):
        self._tick_count += 1

        frames = buffer_manager.get_recent_frames(num_frames=1)
        if not frames:
            return None

        frame = frames[0]

        ocr_text = self._last_ocr_text
        if self._tick_count % self.ocr_every_n_ticks == 0:
            from processing.ocr import ocr_processor
            try:
                ocr_text = await ocr_processor.extract_text_from_bytes(frame.image_bytes)
                self._last_ocr_text = ocr_text
                buffer_manager.add_ocr(OcrResult(timestamp=time.time(), text=ocr_text))
            except Exception as e:
                logger.debug(f"OCR error in watcher: {e}")

        audio_chunks = buffer_manager.get_recent_audio(seconds=2.0)

        signal = await self.watcher.compute_signal(
            frame_bytes=frame.image_bytes,
            ocr_text=ocr_text,
            audio_chunks=audio_chunks,
            active_window_title="",
        )
        return signal

    def update_settings(
        self,
        enabled: bool | None = None,
        auto_pause: bool | None = None,
        auto_unpause: bool | None = None,
        cooldown_sec: float | None = None,
        verbosity: str | None = None,
        sensitivity: float | None = None,
        accumulation_window_sec: float | None = None,
        prefer_text_triggers: bool | None = None,
        debug_mode: bool | None = None,
        capture_active_window: bool | None = None,
    ):
        if enabled is not None:
            if enabled:
                self.enable()
            else:
                self.disable()

        if auto_pause is not None:
            self.helper.update_settings(auto_pause=auto_pause)
        if auto_unpause is not None:
            self.helper.update_settings(auto_unpause=auto_unpause)
        if cooldown_sec is not None:
            self.narration_interval = cooldown_sec
        if verbosity is not None:
            self.verbosity = verbosity
        if sensitivity is not None:
            self.watcher.update_sensitivity(sensitivity)
        if debug_mode is not None:
            self.debug_mode = debug_mode
        if capture_active_window is not None:
            self.capture_active_window = capture_active_window

    def _record_debug(self, event_name: str, data: dict):
        if not self.debug_mode:
            return
        entry = {"ts": time.time(), "event": event_name, **data}
        self._debug_log.append(entry)
        if len(self._debug_log) > self._max_debug_entries:
            self._debug_log = self._debug_log[-self._max_debug_entries:]

    def get_debug_info(self) -> dict:
        return {
            "state": self.state.value,
            "timeline_ts": self.timeline.timeline_ts,
            "timer_elapsed": round(time.time() - self._timer_start, 1),
            "narration_interval": self.narration_interval,
            "llm_pending": self._llm_task is not None and not self._llm_task.done(),
            "recent_events": self._debug_log[-20:] if self.debug_mode else [],
        }

realtime_engine = RealtimeEngine()


async def realtime_loop():
    await realtime_engine.run()
