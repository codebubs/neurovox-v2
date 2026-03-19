# Neurovox

Neurovox is an advanced accessibility addon designed for blind and low-vision users. It allows users to navigate and understand visual media (like silent videos, slide decks, tutorials, and uncaptioned content) using the NVDA screen reader. 

## Installation Instructions

### Starting the Companion
Download and run `neurovox.exe` from the [releases](https://github.com/codebubs/neurovox-v2/releases/latest) page.

Or, run the server manually:
1. Navigate to `server/`.
2. `python -m venv venv`
3. `.\venv\Scripts\activate` 
4. `pip install -r requirements.txt`
5. `python main.py`

To compile the release version of the server, change the production flag in main to `True` and run `build_exe.bat`.

### Installing the NVDA Add-on
1. Download `neurovox.nvda-addon` from the [releases](https://github.com/codebubs/neurovox-v2/releases/latest) page.
2. Double-click `neurovox.nvda-addon`.
3. Restart NVDA when prompted.
4. Configure your Gemini API Key and desired Gemini Model via NVDA Menu > Preferences > Neurovox API Settings. The addon supports models that provide `generateContent` such as `gemini-3.1-flash-lite-preview` and `gemini-2.5-flash-lite`.

The addon can be built using `python build_addon.py`.

## Gestures / Hotkeys
You can configure these hotkeys in NVDA's Input Gestures dialog under the "Neurovox" category. The defaults are:
- `NVDA + E`: **Narrate Concise**. Quickly analyze and describe the current video frame and recent audio.
- `NVDA + Shift + E`: **Narrate Detailed**. Deeply analyze and describe the current video frame and recent audio.
- `NVDA + Control + E`: **Read On-screen Text (OCR)**. Instantly read dense text on screen (like slides or diagrams) using native OCR.
- `NVDA + Shift + R`: **Toggle Realtime Narration**. Automatically narrate significant visual events that are insufficiently explained by verbal audio as they happen.