import time
import threading
from collections import deque
from typing import List, Optional
from pydantic import BaseModel


class FrameData(BaseModel):
    timestamp: float
    image_bytes: bytes
    width: int
    height: int


class AudioChunk(BaseModel):
    timestamp: float
    audio_bytes: bytes
    sample_rate: int
    channels: int


class OcrResult(BaseModel):
    timestamp: float
    text: str


class NarrationRecord(BaseModel):
    timestamp: float
    text: str
    trigger_type: str


class BufferManager:
    def __init__(self, frame_retention_sec=15.0, audio_retention_sec=15.0, ocr_retention_sec=15.0):
        self.frame_retention_sec = frame_retention_sec
        self.audio_retention_sec = audio_retention_sec
        self.ocr_retention_sec = ocr_retention_sec
        
        self.frames: deque[FrameData] = deque()
        self.audio_chunks: deque[AudioChunk] = deque()
        self.ocr_results: deque[OcrResult] = deque()
        self.narrations: deque[NarrationRecord] = deque(maxlen=20)

        self.finalized_segments: deque = deque(maxlen=50)

        self.lock = threading.Lock()

    def add_frame(self, frame: FrameData):
        with self.lock:
            self.frames.append(frame)
            self._prune_frames()

    def get_recent_frames(self, num_frames=3) -> List[FrameData]:
        with self.lock:
            if not self.frames:
                return []
            if len(self.frames) <= num_frames:
                return list(self.frames)
            if num_frames == 1:
                return [self.frames[-1]]
            
            indices = [int(i * (len(self.frames) - 1) / (num_frames - 1)) for i in range(num_frames)]
            return [self.frames[i] for i in indices]

    def get_frames_in_range(self, start: float, end: float) -> List[FrameData]:
        with self.lock:
            return [f for f in self.frames if start <= f.timestamp <= end]

    def add_audio_chunk(self, chunk: AudioChunk):
        with self.lock:
            self.audio_chunks.append(chunk)
            self._prune_audio()

    def get_recent_audio(self, seconds=5.0) -> List[AudioChunk]:
        with self.lock:
            cutoff = time.time() - seconds
            return [chunk for chunk in self.audio_chunks if chunk.timestamp >= cutoff]

    def get_audio_in_range(self, start: float, end: float) -> List[AudioChunk]:
        with self.lock:
            return [c for c in self.audio_chunks if start <= c.timestamp <= end]

    def add_ocr(self, ocr: OcrResult):
        with self.lock:
            self.ocr_results.append(ocr)
            self._prune_ocr()

    def get_recent_ocr(self) -> str:
        with self.lock:
            if not self.ocr_results:
                return ""
            return self.ocr_results[-1].text

    def add_narration(self, narration: NarrationRecord):
        with self.lock:
            self.narrations.append(narration)

    def get_recent_narrations(self) -> List[NarrationRecord]:
        with self.lock:
            return list(self.narrations)

    def get_last_narration(self) -> Optional[NarrationRecord]:
        with self.lock:
            if self.narrations:
                return self.narrations[-1]
            return None

    def add_segment(self, segment):
        with self.lock:
            self.finalized_segments.append(segment)

    def get_recent_segments(self, count: int = 10) -> list:
        with self.lock:
            return list(self.finalized_segments)[-count:]


    def _prune_frames(self):
        cutoff = time.time() - self.frame_retention_sec
        while self.frames and self.frames[0].timestamp < cutoff:
            self.frames.popleft()

    def _prune_audio(self):
        cutoff = time.time() - self.audio_retention_sec
        while self.audio_chunks and self.audio_chunks[0].timestamp < cutoff:
            self.audio_chunks.popleft()

    def _prune_ocr(self):
        cutoff = time.time() - self.ocr_retention_sec
        while self.ocr_results and self.ocr_results[0].timestamp < cutoff:
            self.ocr_results.popleft()


buffer_manager = BufferManager()
