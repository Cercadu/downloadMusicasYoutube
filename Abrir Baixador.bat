@echo off
cd /d "%~dp0"
python -c "import customtkinter, yt_dlp, imageio_ffmpeg, numpy" 2>nul || (
    echo Instalando dependencias, aguarde...
    python -m pip install -r requirements.txt
)
start "" pythonw app.py
