# Neurovox

Neurovox is an advanced accessibility addon designed for blind and low-vision users. It allows users to navigate and understand visual media (like silent videos, slide decks, tutorials, and uncaptioned content) using the NVDA screen reader. 

## Installation Instructions

### Starting the Companion Server
1. Navigate to `server/`.
2. `python -m venv venv`
3. `.\venv\Scripts\activate` 
4. `pip install -r requirements.txt`
5. `python main.py`

### Installing the NVDA Add-on
1. Double-click `neurovox.nvda-addon`.
2. Restart NVDA when prompted.
3. Configure your Gemini API Key and desired Gemini Model via NVDA Menu > Preferences > Neurovox API Settings. The addon supports models that provide `generateContent` such as `gemini-1.5-flash` and `gemini-2.5-flash-lite`.

The addon can be built using `python build.py`.

## Gestures / Hotkeys
You can configure these hotkeys in NVDA's Input Gestures dialog under the "Neurovox" category. The defaults are:
- `NVDA + N`: **Narrate Concise**. Quickly analyze and describe the current video frame and recent audio.
- `NVDA + Shift + N`: **Narrate Detailed**. Deeply analyze and describe the current video frame and recent audio.
- `NVDA + Control + N`: **Read On-screen Text (OCR)**. Instantly read dense text on screen (like slides or diagrams) using offline Windows OCR.
