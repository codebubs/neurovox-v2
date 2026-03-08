import time
import threading
import io
import mss
from PIL import Image
from loguru import logger
from buffer_manager import buffer_manager, FrameData
import traceback


def get_foreground_window_rect():
    try:
        user32 = ctypes.windll.user32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))

        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w < 100 or h < 100: # make sure window size is reasonable
            return None

        return {
            "left": rect.left,
            "top": rect.top,
            "width": w,
            "height": h,
        }
    except Exception as e:
        logger.debug(f"Could not get foreground window rect: {e}")
        return None


def get_foreground_window_title() -> str:
    try:
        user32 = ctypes.windll.user32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""

        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""

        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


import ctypes
import ctypes.wintypes


class ScreenCaptureThread(threading.Thread):
    def __init__(self, fps=4.0, capture_active_only=False):
        super().__init__(daemon=True)
        self.fps = fps
        self.running = False
        self.capture_active_only = capture_active_only
        self._active_window_title: str = ""
        self._lock = threading.Lock()

    @property
    def active_window_title(self) -> str:
        with self._lock:
            return self._active_window_title

    def set_fps(self, fps: float):
        self.fps = max(0.5, min(fps, 10.0))
        logger.debug(f"Screen capture FPS set to {self.fps}")

    def set_capture_active_only(self, value: bool):
        self.capture_active_only = value
        logger.debug(f"Capture active window only: {value}")

    def run(self):
        self.running = True
        logger.info(f"Screen capture thread started at {self.fps} FPS")
        with mss.mss() as sct:
            while self.running:
                start_time = time.time()
                try:
                    title = get_foreground_window_title()
                    with self._lock:
                        self._active_window_title = title

                    if self.capture_active_only:
                        region = get_foreground_window_rect()
                        if region:
                            monitor = region
                        else:
                            monitor = sct.monitors[1]  # fall back to full screen
                    else:
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
