import time
import threading
import io
import mss
from PIL import Image
from loguru import logger
from buffer_manager import buffer_manager, FrameData
import traceback

class ScreenCaptureThread(threading.Thread):
    def __init__(self, fps=2.0, capture_active_only=False):
        super().__init__(daemon=True)
        self.fps = fps
        self.running = False
        # we can expand this later to capture only foreground window via win32gui
        self.capture_active_only = capture_active_only

    def run(self):
        self.running = True
        logger.info(f"Screen capture thread started at {self.fps} FPS")
        with mss.mss() as sct:
            while self.running:
                start_time = time.time()
                try:
                    monitor = sct.monitors[1]
                    sct_img = sct.grab(monitor)
                    
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    
                    max_dim = 1280
                    if max(img.width, img.height) > max_dim:
                        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

                    buffer = io.BytesIO()
                    img.save(buffer, format="JPEG", quality=75)
                    jpeg_bytes = buffer.getvalue()

                    frame = FrameData(
                        timestamp=time.time(),
                        image_bytes=jpeg_bytes,
                        width=img.width,
                        height=img.height
                    )
                    buffer_manager.add_frame(frame)
                    
                except Exception as e:
                    logger.error(f"Error in screen capture: {e}")
                    traceback.print_exc()

                elapsed = time.time() - start_time
                sleep_time = max(0, (1.0 / self.fps) - elapsed)
                time.sleep(sleep_time)

    def stop(self):
        self.running = False
