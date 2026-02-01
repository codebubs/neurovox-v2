import pyaudiowpatch as pyaudio
import time
import threading
from loguru import logger
from buffer_manager import buffer_manager, AudioChunk
import traceback

class AudioCaptureThread(threading.Thread):
    def __init__(self, chunk_size=4096):
        super().__init__(daemon=True)
        self.chunk_size = chunk_size
        self.running = False
        self.p = pyaudio.PyAudio()
        self.stream = None

    def run(self):
        self.running = True
        try:
            wasapi_info = self.p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = self.p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            
            if not default_speakers["isLoopbackDevice"]:
                for loopback in self.p.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]:
                        default_loopback = loopback
                        break
                else:
                    default_loopback = self.p.get_default_wasapi_loopback()
            else:
                default_loopback = default_speakers

            logger.info(f"Using audio loopback device: {default_loopback['name']}")
            
            sample_rate = int(default_loopback["defaultSampleRate"])
            channels = default_loopback["maxInputChannels"]

            def callback(in_data, frame_count, time_info, status):
                if in_data and self.running:
                    chunk = AudioChunk(
                        timestamp=time.time(),
                        audio_bytes=in_data,
                        sample_rate=sample_rate,
                        channels=channels
                    )
                    buffer_manager.add_audio_chunk(chunk)
                return (in_data, pyaudio.paContinue)

            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=sample_rate,
                frames_per_buffer=self.chunk_size,
                input=True,
                input_device_index=default_loopback["index"],
                stream_callback=callback
            )
            
            self.stream.start_stream()
            
            while self.stream.is_active() and self.running:
                time.sleep(0.5)
                
        except Exception as e:
            logger.error(f"Error in audio capture: {e}")
            traceback.print_exc()

    def stop(self):
        self.running = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.p.terminate()
