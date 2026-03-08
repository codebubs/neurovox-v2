import asyncio
import time
from loguru import logger

from processing.models import FinalizedSegment, ConsumedTimeline

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager,
)


async def get_media_manager():
    try:
        return await GlobalSystemMediaTransportControlsSessionManager.request_async()
    except Exception as e:
        logger.error(f"Error accessing media manager: {e}")
        return None


class PauseHelper:
    def __init__(self, auto_pause: bool = False, auto_unpause: bool = True):
        self.auto_pause = auto_pause
        self.auto_unpause = auto_unpause
        self._manager = None

    async def _ensure_manager(self):
        if self._manager is None:
            self._manager = await get_media_manager()
        return self._manager

    async def pause_media(self) -> bool:
        if not self.auto_pause:
            return False

        manager = await self._ensure_manager()
        if not manager:
            return False

        try:
            session = manager.get_current_session()
            if session:
                info = session.get_playback_info()
                if info and info.playback_status.value == 4:  # PLAYING
                    await session.try_pause_async()
                    logger.info("Media paused")
                    return True
        except Exception as e:
            logger.error(f"Error pausing media: {e}")
        return False

    async def handle_post_clarification(
        self,
        text: str,
        system_paused: bool,
        event_queue: asyncio.Queue,
    ):
        if not system_paused:
            return

        duration = max(2.0, len(text) / 14.0)
        start_time = time.time()
        user_unpaused = False

        manager = await self._ensure_manager()

        while time.time() - start_time < duration:
            await asyncio.sleep(0.5)
            if manager:
                try:
                    session = manager.get_current_session()
                    if session:
                        info = session.get_playback_info()
                        if info and info.playback_status.value == 4:  # PLAYING
                            user_unpaused = True
                            break
                except Exception:
                    pass

        if user_unpaused:
            logger.info("User manually unpaused. Canceling speech")
            await event_queue.put({
                "type": "cancel_speech",
                "text": None,
                "timestamp": time.time(),
            })
        elif self.auto_unpause and system_paused and manager:
            try:
                session = manager.get_current_session()
                if session:
                    info = session.get_playback_info()
                    if info and info.playback_status.value == 5:  # PAUSED
                        logger.info("Resuming media after clarification")
                        await session.try_play_async()
            except Exception:
                pass

    def advance_timeline(
        self, timeline: ConsumedTimeline, segment: FinalizedSegment
    ):
        timeline.advance(segment.end_ts, segment.fingerprint)
        segment.consumed = True
        logger.debug(
            f"Timeline to {segment.end_ts:.2f}, "
            f"fingerprint {segment.fingerprint[:8]}..."
        )

    def update_settings(
        self,
        auto_pause: bool | None = None,
        auto_unpause: bool | None = None,
    ):
        if auto_pause is not None:
            self.auto_pause = auto_pause
        if auto_unpause is not None:
            self.auto_unpause = auto_unpause
