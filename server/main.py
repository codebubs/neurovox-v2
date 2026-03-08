
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from loguru import logger
import asyncio
import time
from typing import Optional

from capture.video import ScreenCaptureThread
from capture.audio import AudioCaptureThread
from processing.ocr import ocr_processor
from processing.llm import llm_processor
from buffer_manager import buffer_manager, NarrationRecord
from processing.realtime import realtime_loop, get_event_queue, realtime_engine

screen_thread = None
audio_thread = None
realtime_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global screen_thread, audio_thread, realtime_task
    logger.info("Starting Companion Service threads...")
    
    screen_thread = ScreenCaptureThread(fps=4.0)
    screen_thread.start()
    
    audio_thread = AudioCaptureThread()
    audio_thread.start()
    
    realtime_task = asyncio.create_task(realtime_loop())
    
    yield
    
    logger.info("Stopping capture threads...")
    if screen_thread:
        screen_thread.stop()
    if audio_thread:
        audio_thread.stop()
    if realtime_task:
        realtime_task.cancel()

app = FastAPI(title="Neurovox Companion Service", lifespan=lifespan)



class NarrationRequest(BaseModel):
    mode: str = "concise"  # "concise", "detailed", "ocr_only"
    api_key: str = None
    model: str = None

class SettingsRequest(BaseModel):
    api_key: str
    model: str = None

class RealtimeStateRequest(BaseModel):
    enabled: bool
    auto_pause: bool = False
    auto_unpause: bool = True
    cooldown_sec: float = 15.0
    verbosity: str = "concise"

    sensitivity: Optional[float] = None           # 0-1
    accumulation_window_sec: Optional[float] = None
    prefer_text_triggers: Optional[bool] = None

    debug_mode: Optional[bool] = None
    capture_active_window: Optional[bool] = None


@app.post("/settings")
def update_settings(req: SettingsRequest):
    if req.api_key or req.model:
        llm_processor.update_api_key(api_key=req.api_key, model=req.model)
    return {"status": "success"}


@app.post("/realtime/state")
def update_realtime_state(req: RealtimeStateRequest):
    realtime_engine.update_settings(
        enabled=req.enabled,
        auto_pause=req.auto_pause,
        auto_unpause=req.auto_unpause,
        cooldown_sec=req.cooldown_sec,
        verbosity=req.verbosity,
        sensitivity=req.sensitivity,
        accumulation_window_sec=req.accumulation_window_sec,
        prefer_text_triggers=req.prefer_text_triggers,

        debug_mode=req.debug_mode,
        capture_active_window=req.capture_active_window,
    )

    
    if screen_thread and req.capture_active_window is not None:
        screen_thread.set_capture_active_only(req.capture_active_window)
    
    return {"status": "success", "state": realtime_engine.state.value}


@app.get("/realtime/events")
async def get_realtime_events():
    try:
        event = await asyncio.wait_for(get_event_queue().get(), timeout=10.0)
        return event
    except asyncio.TimeoutError:
        return {"text": None}


@app.get("/realtime/debug")
def get_realtime_debug():
    return realtime_engine.get_debug_info()


@app.post("/narrate")
async def narrate(req: NarrationRequest):
    if req.api_key or req.model:
        llm_processor.update_api_key(api_key=req.api_key, model=req.model)

    if req.mode == "ocr_only":
        frames = buffer_manager.get_recent_frames(num_frames=1)
        if not frames:
            return {"text": "No active display context found."}
        
        frame = frames[0]
        text = await ocr_processor.extract_text_from_bytes(frame.image_bytes)
        
        from buffer_manager import OcrResult
        buffer_manager.add_ocr(OcrResult(timestamp=time.time(), text=text))
        
        if not text:
            return {"text": "No meaningful text found on screen."}
            
        summary = text
        if len(text) > 400:
            summary = "Dense text detected: " + text[:400] + "... (Text truncated)"
            
        return {"text": summary}
        
    res_text = await asyncio.to_thread(llm_processor.generate_narration, req.mode)
    
    buffer_manager.add_narration(NarrationRecord(
        timestamp=time.time(),
        text=res_text,
        trigger_type=req.mode
    ))
    
    return {"text": res_text}


@app.get("/health")
def health_check():
    return {
        "status": "ok", 
        "frames": len(buffer_manager.frames), 
        "audio_chunks": len(buffer_manager.audio_chunks),
        "realtime_state": realtime_engine.state.value,
        "segments_count": len(buffer_manager.finalized_segments),
    }

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
