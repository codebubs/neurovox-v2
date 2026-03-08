import time
import io
from PIL import Image
from loguru import logger
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
import asyncio

class OcrProcessor:
    def __init__(self):
        self.engine = OcrEngine.try_create_from_user_profile_languages()
        if not self.engine:
            logger.warning("Could not initialize OCR")

    async def extract_text_from_bytes(self, image_bytes: bytes) -> str:
        if not self.engine:
            return ""

        try:
            stream = InMemoryRandomAccessStream()
            writer = DataWriter(stream)
            writer.write_bytes(image_bytes)
            writer.store_async()
            writer.flush_async()
            writer.detach_stream()

            decoder = await BitmapDecoder.create_async(stream)
            software_bitmap = await decoder.get_software_bitmap_async()

            ocr_result = await self.engine.recognize_async(software_bitmap)

            return ocr_result.text if ocr_result and ocr_result.text else ""
        except Exception as e:
            logger.error(f"OCR Error: {e}")
            return ""

ocr_processor = OcrProcessor()
