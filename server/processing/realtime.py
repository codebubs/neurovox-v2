import time
import asyncio
import ctypes
import numpy as np
from difflib import SequenceMatcher
from loguru import logger

from buffer_manager import buffer_manager
from processing.llm import llm_processor

from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager

event_queue = None

def get_event_queue():
    global event_queue
    if event_queue is None:
        event_queue = asyncio.Queue()
    return event_queue

async def get_media_manager():
    try:
        return await GlobalSystemMediaTransportControlsSessionManager.request_async()
    except Exception as e:
        logger.error(f"Error accessing media manager: {e}")
        return None

class ClarificationDetector:
    def __init__(self):
        self.last_ocr_text = ""
        self.last_audio_rms = 0.0
        self.last_frame_bytes = None

    def calculate_audio_rms(self, chunks):
        if not chunks:
            return 0.0
        
        all_bytes = b"".join(c.audio_bytes for c in chunks)
        if not all_bytes:
            return 0.0
            
        try:
            audio_data = np.frombuffer(all_bytes, dtype=np.int16)
            if len(audio_data) == 0:
                return 0.0
            
            audio_data_f = audio_data.astype(np.float32)
            rms = np.sqrt(np.mean(np.square(audio_data_f)))
            return float(rms)
        except Exception as e:
            logger.error(f"Error calculating RMS: {e}")
            return 0.0

    async def check_for_trigger(self) -> bool:
        if not buffer_manager.realtime_enabled:
            return False
            
        now = time.time()
        if now - buffer_manager.last_clarification_time < buffer_manager.realtime_cooldown_sec:
            return False
            
        frames = buffer_manager.get_recent_frames(num_frames=1)
        if not frames:
            return False
            
        frame = frames[0]
        from processing.ocr import ocr_processor
        recent_ocr = await ocr_processor.extract_text_from_bytes(frame.image_bytes)
        
        from buffer_manager import OcrResult
        buffer_manager.add_ocr(OcrResult(timestamp=time.time(), text=recent_ocr))
        
        frame_diff = 0.0
        import io
        from PIL import Image
        if self.last_frame_bytes and frame.image_bytes:
            try:
                img1 = Image.open(io.BytesIO(self.last_frame_bytes)).convert('L').resize((64, 64))
                img2 = Image.open(io.BytesIO(frame.image_bytes)).convert('L').resize((64, 64))
                diff_arr = np.abs(np.array(img1, dtype=np.int16) - np.array(img2, dtype=np.int16))
                frame_diff = float(np.mean(diff_arr))
            except Exception as e:
                logger.error(f"Image diff error: {e}")
                
        self.last_frame_bytes = frame.image_bytes
        
        has_text = bool(recent_ocr and len(recent_ocr.strip()) >= 5)
        
        similarity_to_last_clarified = SequenceMatcher(None, recent_ocr, buffer_manager.last_clarified_text).ratio() if has_text else 0.0
        if has_text and similarity_to_last_clarified > 0.8:
            return False
            
        similarity_to_last_seen = SequenceMatcher(None, recent_ocr, self.last_ocr_text).ratio() if has_text else 1.0
        
        audio_chunks = buffer_manager.get_recent_audio(seconds=2.0)
        rms = self.calculate_audio_rms(audio_chunks)
        
        self.last_ocr_text = recent_ocr
        self.last_audio_rms = rms
        
        # trigger iff there is not much audio, and:
        # a. ocr text changed and enough text is visible
        # b. frame visually changed significantly
        
        text_trigger = has_text and similarity_to_last_seen < 0.8
        visual_trigger = frame_diff > 15.0
        
        if (text_trigger or visual_trigger) and rms < 1500:
            logger.info(f"Clarification trigger! OCR Sim: {similarity_to_last_seen:.2f}, Framediff: {frame_diff:.2f}, RMS: {rms:.2f}")
            return True
            
        return False

class ClarificationGenerator:
    @staticmethod
    async def generate_and_emit():
        mode = buffer_manager.realtime_verbosity
        logger.info(f"Generating clarification with verbosity {mode}...")
        
        res_text = await asyncio.to_thread(llm_processor.generate_narration, mode)
        
        buffer_manager.last_clarification_time = time.time()
        buffer_manager.last_clarified_text = buffer_manager.get_recent_ocr()
        
        system_paused_media = False
        manager = await get_media_manager()
        
        if buffer_manager.realtime_auto_pause and manager:
            try:
                session = manager.get_current_session()
                if session:
                    info = session.get_playback_info()
                    if info and info.playback_status.value == 4: # PLAYING
                        await session.try_pause_async()
                        system_paused_media = True
                        logger.info("Auto-paused media.")
            except Exception as e:
                logger.error(f"Error pausing media: {e}")
            
        await get_event_queue().put({"type": "speak", "text": res_text, "timestamp": time.time()})
        
        asyncio.create_task(ClarificationGenerator.handle_post_clarification(res_text, system_paused_media, manager))

    @staticmethod
    async def handle_post_clarification(text: str, system_paused_media: bool, manager):
        duration = max(2.0, len(text) / 14.0)
        start_time = time.time()
        user_unpaused = False
        
        while time.time() - start_time < duration:
            await asyncio.sleep(0.5)
            if manager:
                try:
                    session = manager.get_current_session()
                    if session:
                        info = session.get_playback_info()
                        if info and info.playback_status.value == 4: # PLAYING
                            user_unpaused = True
                            break
                except Exception:
                    pass
                    
        if user_unpaused:
            logger.info("User manually unpaused. Cancelling speech.")
            await get_event_queue().put({"type": "cancel_speech", "text": None, "timestamp": time.time()})
        else:
            if buffer_manager.realtime_auto_unpause and system_paused_media and manager:
                try:
                    session = manager.get_current_session()
                    if session:
                        info = session.get_playback_info()
                        if info and info.playback_status.value == 5: # PAUSED
                            logger.info("Explanation assumed done. Auto-unpausing.")
                            await session.try_play_async()
                except Exception:
                    pass

async def realtime_loop():
    logger.info("Starting realtime monitoring loop...")
    detector = ClarificationDetector()
    
    while True:
        try:
            if buffer_manager.realtime_enabled:
                if await detector.check_for_trigger():
                    await ClarificationGenerator.generate_and_emit()
            
        except Exception as e:
            logger.error(f"Error in realtime loop: {e}")
            
        await asyncio.sleep(2.0)
