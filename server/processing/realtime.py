import asyncio
import time
from loguru import logger

from buffer_manager import buffer_manager, OcrResult
from processing.models import (
    RealtimeState,
    ConsumedTimeline,
    CandidateEvent,
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

        self._active_candidate: CandidateEvent | None = None

        self.cooldown_sec: float = 15.0
        self._cooldown_until: float = 0.0
        self.tick_interval: float = 0.25
        self.ocr_every_n_ticks: int = 2
        self._tick_count: int = 0
        self._last_ocr_text: str = ""
        self.debug_mode: bool = False
        self.verbosity: str = "concise"

        self.capture_active_window: bool = False

        self._pending_segment = None
        self._pending_snapshot = None

        self._debug_log: list[dict] = []
        self._max_debug_entries: int = 200

    def _transition(self, new_state: RealtimeState, reason: str = ""):
        old = self.state
        self.state = new_state
        msg = f"State: {old.value} to {new_state.value}"
        if reason:
            msg += f" ({reason})"
        logger.info(msg)
        self._record_debug("state_transition", {
            "from": old.value, "to": new_state.value, "reason": reason
        })

    def enable(self):
        if self.state == RealtimeState.OFF:
            self._transition(RealtimeState.MONITORING, "realtime enabled")
            self.timeline = ConsumedTimeline()

    def disable(self):
        self._active_candidate = None
        self._transition(RealtimeState.OFF, "realtime disabled")

    async def run(self):
        logger.info("Realtime loop started")
        while True:
            try:
                if self.state == RealtimeState.OFF:
                    await asyncio.sleep(0.5)
                    continue

                if self.state == RealtimeState.COOLDOWN:
                    if time.time() >= self._cooldown_until:
                        self._transition(RealtimeState.MONITORING, "cooldown expired")
                    else:
                        await asyncio.sleep(self.tick_interval)
                        continue

                if self.state == RealtimeState.MONITORING:
                    await self._tick_monitoring()

                elif self.state in (
                    RealtimeState.CANDIDATE_OPEN,
                    RealtimeState.CANDIDATE_ACCUMULATING,
                ):
                    await self._tick_accumulating()

                elif self.state == RealtimeState.READY_TO_PAUSE:
                    await self._tick_ready_to_pause()

            except asyncio.CancelledError:
                logger.info("Realtime loop cancelled")
                break
            except Exception as e:
                logger.error(f"RealtimeEngine error: {e}")
                self._record_debug("error", {"error": str(e)})

            await asyncio.sleep(self.tick_interval)

    async def _tick_monitoring(self):
        signal = await self._collect_signal()
        if signal is None:
            return

        self._record_debug("watcher_tick", {
            "frame_diff": round(signal.frame_diff, 2),
            "ocr_changed": signal.ocr_changed,
            "text_density": signal.text_density,
            "rms": round(signal.audio_rms, 1),
            "score": round(signal.combined_score, 3),
        })

        if signal.combined_score >= 0.20:
            self._active_candidate = self.finalizer.open_candidate(signal)
            self._transition(RealtimeState.CANDIDATE_OPEN, f"score={signal.combined_score:.2f}")

    async def _tick_accumulating(self):
        if self._active_candidate is None:
            self._transition(RealtimeState.MONITORING, "no active candidate")
            return

        signal = await self._collect_signal()
        if signal is not None:
            self.finalizer.accumulate(self._active_candidate, signal)

        if self.state == RealtimeState.CANDIDATE_OPEN:
            self._transition(RealtimeState.CANDIDATE_ACCUMULATING, "accumulating")

        if self.finalizer.should_keep_accumulating(self._active_candidate):
            return

        segment, pause = self.finalizer.try_finalize(
            self._active_candidate, self.timeline
        )

        if segment is None or not pause:
            reason = "rejected" if segment is None else "not pause-worthy"
            self._record_debug("candidate_rejected", {
                "event_id": self._active_candidate.event_id,
                "reason": reason,
            })
            self._active_candidate = None
            self._transition(RealtimeState.MONITORING, reason)
            return

        snapshot = self.finalizer.freeze_snapshot(
            self._active_candidate, segment, buffer_manager
        )
        buffer_manager.add_segment(segment)
        self._pending_segment = segment
        self._pending_snapshot = snapshot
        self._transition(RealtimeState.READY_TO_PAUSE, f"segment={segment.segment_id}")

    async def _tick_ready_to_pause(self):
        segment = self._pending_segment
        snapshot = self._pending_snapshot
        self._pending_segment = None
        self._pending_snapshot = None

        system_paused = await self.helper.pause_media()
        segment.pause_status = "paused" if system_paused else "skipped"
        self._transition(
            RealtimeState.PAUSED_FOR_CLARIFICATION,
            "media paused" if system_paused else "pause skipped"
        )

        segment.summary_status = "generating"
        self._record_debug("narration_start", {
            "segment_id": segment.segment_id,
            "event_type": segment.event_type.value,
        })

        t0 = time.time()
        narration_text = await asyncio.to_thread(
            llm_processor.generate_clarification, snapshot, self.verbosity
        )
        latency = time.time() - t0

        segment.summary_status = "done"
        self._record_debug("narration_done", {
            "segment_id": segment.segment_id,
            "latency": round(latency, 2),
            "length": len(narration_text),
        })

        self._transition(RealtimeState.SPEAKING, "speaking clarification")
        event_queue = get_event_queue()
        await event_queue.put({
            "type": "speak",
            "text": narration_text,
            "timestamp": time.time(),
            "segment_id": segment.segment_id,
            "event_type": segment.event_type.value,
        })

        await self.helper.handle_post_clarification(
            narration_text, system_paused, event_queue
        )
        self.helper.advance_timeline(self.timeline, segment)
        self._cooldown_until = time.time() + self.cooldown_sec
        self._active_candidate = None
        self._transition(RealtimeState.COOLDOWN, f"cooldown {self.cooldown_sec}s")

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
            self.cooldown_sec = cooldown_sec
        if verbosity is not None:
            self.verbosity = verbosity
        if sensitivity is not None:
            self.watcher.update_sensitivity(sensitivity)
            self.finalizer.update_settings(sensitivity=sensitivity)
        if accumulation_window_sec is not None:
            self.finalizer.update_settings(accumulation_window_sec=accumulation_window_sec)
        if prefer_text_triggers is not None:
            self.finalizer.update_settings(prefer_text_triggers=prefer_text_triggers)
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
            "timeline_fingerprints": len(self.timeline.last_fingerprints),
            "cooldown_remaining": max(0, self._cooldown_until - time.time()),
            "active_candidate": (
                self._active_candidate.event_id
                if self._active_candidate else None
            ),

            "recent_events": self._debug_log[-20:] if self.debug_mode else [],
        }

realtime_engine = RealtimeEngine()


async def realtime_loop():
    await realtime_engine.run()
