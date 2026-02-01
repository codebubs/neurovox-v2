import os
import io
import wave
import base64
import requests
from loguru import logger
from buffer_manager import buffer_manager, AudioChunk

PROMPT = """You are a visual and auditory assistant for a blind NVDA screen reader user.
Your task is to describe the current moment in a video or on the screen based on the provided frames, OCR text, and system audio.
Rules:
1. If there is visible text or OCR, summarize it or read the most salient points, especially if it's a slide or UI.
2. If audio speech is present, DO NOT repeat it. Instead, explain the visual context relating to the speech.
3. If audio is noisy or unintelligible, say so and rely purely on visuals.
4. Do not invent details or hallucinate.
5. Respond with natural spoken language, no markdown, no asterisks.
6. Focus on what has CHANGED or what is currently the MAIN SUBJECT.
"""

class LLMProcessor:
    def __init__(self):
        self.api_key = os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not set.")
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
        
        sample_rate = chunks[0].sample_rate
        channels = chunks[0].channels
        
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2) # paInt16 is 2 bytes
            wf.setframerate(sample_rate)
            for chunk in chunks:
                wf.writeframes(chunk.audio_bytes)
                
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
        parts.append({"text": PROMPT})

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
            parts.append({"text": "The attached audio represents the last 5 seconds of system sound."})
        else:
            parts.append({"text": "No recent system audio."})

        parts.append({"text": "Recent frames (in chronological order):"})
        for f in frames:
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(f.image_bytes).decode('utf-8')
                }
            })
            
        if mode == "detailed":
            custom_prompt = "Provide a fully detailed description of the screen, layout, entities, and any relevant text or actions. Expand as much as needed."
        else: # default to "concise"
            custom_prompt = "Provide a very short, concise description (1-2 sentences max) of the primary visual subject or action happening right now."

        parts.append({"text": custom_prompt})

        try:
            url = self.url_template.format(self.model, self.api_key)
            payload = {
                "contents": [{"parts": parts}]
            }
            logger.info(f"Calling Gemini API REST Endpoint ({self.model}) with mode: {mode}")
            resp = requests.post(url, json=payload, timeout=15.0)
            
            if resp.status_code != 200:
                logger.error(f"LLM API Error: {resp.status_code} - {resp.text}")
                return "API provider returned an error."
                
            data = resp.json()
            try:
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                text = text.replace("**", "").replace("_", "")
                return text
            except (KeyError, IndexError):
                logger.error(f"Unexpected response format: {data}")
                return "Unable to parse AI response."
                
        except Exception as e:
            logger.error(f"LLM REST API Error: {e}")
            return "An error occurred while calling the AI model."

llm_processor = LLMProcessor()