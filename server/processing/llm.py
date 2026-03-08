
import io
import wave
import base64
import requests
from loguru import logger
from buffer_manager import buffer_manager, AudioChunk

MANUAL_PROMPT = """You are a visual assistant for a blind NVDA screen reader user.
Your task is to describe the current moment in a video based on the provided frames, OCR text, and recorded audio.
Rules:
1. If there is visible text, summarize it and read the most important points.
2. If verbal audio is present, DO NOT repeat it. Instead, explain the visual content that is not covered by the speech.
3. Do not hallucinate.
4. Respond with natural language without markdown or asterisks.
5. Focus on what has CHANGED or what is currently the MAIN SUBJECT.
"""

REALTIME_PROMPT = """You are a visual assistant for a blind NVDA screen reader user.
Media playback has been paused because something important has happened. You must give a short explanation of what caused this pause.

Rules:
1. Describe ONLY what is newly relevant in this event.
2. Do NOT repeat content that was already explained in previous clarifications.
3. If there is visible text, summarize it and read the most important points.
4. If verbal audio is present, DO NOT repeat it. Instead, explain the visual content that is not covered by the speech.
5. Do not hallucinate.
6. Respond with natural language without markdown or asterisks.
7. Answer: "What visual thing just happened that the user should know about?"
"""


class LLMProcessor:
    def __init__(self):
        self.api_key = None
        self.model = ""
        self.url_template = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}"

    def update_api_key(self, api_key: str = None, model: str = None):
        if api_key:
            self.api_key = api_key
        if model:
            self.model = model

    def _create_wav_from_chunks(self, chunks: list[AudioChunk]) -> bytes:
        if not chunks:
            return b""
        audio_bytes = b"".join(c.audio_bytes for c in chunks)
        return self._create_wav_from_bytes(audio_bytes, chunks[0].sample_rate, chunks[0].channels)

    def _create_wav_from_bytes(self, audio_bytes: bytes, sample_rate: int, channels: int) -> bytes:
        if not audio_bytes or not sample_rate:
            return b""
        
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_bytes)
        return buffer.getvalue()

    def generate_narration(self, mode="concise") -> str:
        if not self.api_key:
            return "Configuration error. Please enter a Gemini API Key in the NVDA Neurovox settings."
        if not self.model:
            return "Configuration error. Please enter a Gemini Model in the NVDA Neurovox settings."

        frames = buffer_manager.get_recent_frames(num_frames=3)
        ocr_text = buffer_manager.get_recent_ocr()
        audio_chunks = buffer_manager.get_recent_audio(seconds=5.0)
        
        if not frames:
            return "Unable to capture screen at this time."

        parts = []
        parts.append({"text": MANUAL_PROMPT})

        if ocr_text:
            parts.append({"text": f"Recent on-screen text detected via OCR: {ocr_text}"})
            
        wav_bytes = self._create_wav_from_chunks(audio_chunks)
        if wav_bytes:
            parts.append({
                "inline_data": {
                    "mime_type": "audio/wav",
                    "data": base64.b64encode(wav_bytes).decode('utf-8')
                }
            })
            parts.append({"text": "The attached audio represents the last 5 seconds of recorded sound."})
        else:
            parts.append({"text": "No recent recorded audio."})

        parts.append({"text": "Recent frames (in chronological order):"})
        for f in frames:
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(f.image_bytes).decode('utf-8')
                }
            })
            
        if mode == "detailed":
            custom_prompt = "Provide a fully detailed description of the screen, layout, entities, and any relevant text or actions. Elaborate as much as needed."
        else:  # default to "concise"
            custom_prompt = "Provide a very short, concise description (1-2 sentences max) of the primary visual subject or action happening right now."

        parts.append({"text": custom_prompt})

        return self._call_api(parts, mode)

    def generate_clarification(self, snapshot, verbosity: str = "concise") -> str:
        if not self.api_key:
            return "Configuration error. Please enter a Gemini API Key in the NVDA Neurovox settings."
        if not self.model:
            return "Configuration error. Please enter a Gemini Model in the NVDA Neurovox settings."

        if not snapshot.frames:
            return "No visual data captured for this event."

        parts = []
        parts.append({"text": REALTIME_PROMPT})

        parts.append({
            "text": f"Event type: {snapshot.event_type.value}. "
                    f"Active window: {snapshot.active_window_title or 'unknown'}."
        })

        if snapshot.ocr_texts:
            combined_ocr = "\n---\n".join(snapshot.ocr_texts)
            parts.append({
                "text": f"On-screen text detected during this event:\n{combined_ocr}"
            })

        wav_bytes = self._create_wav_from_bytes(
            snapshot.audio_bytes,
            snapshot.audio_sample_rate,
            snapshot.audio_channels,
        )
        if wav_bytes:
            parts.append({
                "inline_data": {
                    "mime_type": "audio/wav",
                    "data": base64.b64encode(wav_bytes).decode('utf-8')
                }
            })
            parts.append({"text": "The attached audio is from the event time window."})
        else:
            parts.append({"text": "No audio was captured during this event."})

        parts.append({"text": f"Visual frames from this event ({len(snapshot.frames)} frames):"})
        for frame_bytes in snapshot.frames:
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(frame_bytes).decode('utf-8')
                }
            })

        if verbosity == "detailed":
            parts.append({
                "text": "Provide a detailed clarification of what this visual event shows. "
                        "Include all relevant text and visual elements."
            })
        else:
            parts.append({
                "text": "Provide a very short clarification (1-3 sentences) of what caused "
                        "this interruption and what the user should know."
            })

        return self._call_api(parts, f"realtime-{verbosity}")

    def _call_api(self, parts: list, mode_label: str) -> str:
        try:
            url = self.url_template.format(self.model, self.api_key)
            payload = {
                "contents": [{"parts": parts}]
            }
            logger.info(f"Calling Gemini API ({self.model}) - mode: {mode_label}")
            resp = requests.post(url, json=payload, timeout=15.0)
            
            if resp.status_code != 200:
                logger.error(f"API Error: {resp.status_code} - {resp.text}")
                return "API provider returned an error."
                
            data = resp.json()
            try:
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                text = text.replace("**", "").replace("_", "")
                return text
            except (KeyError, IndexError):
                logger.error(f"Unexpected response format: {data}")
                return "Unable to parse response."
                
        except Exception as e:
            logger.error(f"API Error: {e}")
            return "An error occurred while calling the model."


llm_processor = LLMProcessor()