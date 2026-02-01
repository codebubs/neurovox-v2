import os
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from loguru import logger
import asyncio
import time

from capture.video import ScreenCaptureThread
from capture.audio import AudioCaptureThread
from processing.ocr import ocr_processor
from processing.llm import llm_processor
from buffer_manager import buffer_manager, NarrationRecord

app = FastAPI(title="Neurovox Companion Service")

screen_thread = None
audio_thread = None

class NarrationRequest(BaseModel):
    mode: str = "concise" # "concise", "detailed", "ocr_only"
    api_key: str = None
    model: str = None

class SettingsRequest(BaseModel):
    api_key: str
    model: str = None

@app.on_event("startup")
async def startup_event():
    global screen_thread, audio_thread
    logger.info("Starting Companion Service threads...")
    
    screen_thread = ScreenCaptureThread(fps=1.0)
    screen_thread.start()
    
    audio_thread = AudioCaptureThread()
    audio_thread.start()

@app.on_event("shutdown")
async def shutdown_event():
    global screen_thread, audio_thread
    logger.info("Stopping capture threads...")
    if screen_thread:
        screen_thread.stop()
    if audio_thread:
        audio_thread.stop()

@app.post("/settings")
def update_settings(req: SettingsRequest):
    if req.api_key or req.model:
        llm_processor.update_api_key(api_key=req.api_key, model=req.model)
    return {"status": "success"}

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
        "audio_chunks": len(buffer_manager.audio_chunks)
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
