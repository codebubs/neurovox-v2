@echo off
echo Building Neurovox Companion Server EXE...
cd server
call venv\Scripts\activate.bat
pyinstaller --name neurovox --onefile --hidden-import uvicorn.logging --hidden-import uvicorn.loops --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols --hidden-import uvicorn.protocols.http --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan --hidden-import uvicorn.lifespan.on --hidden-import uvicorn.lifespan.off main.py
copy /Y dist\neurovox.exe ..\neurovox.exe
rmdir /s /q build
rmdir /s /q dist
del /q neurovox.spec
cd ..
echo Build complete at neurovox.exe
