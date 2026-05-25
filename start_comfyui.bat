@echo off
title ComfyUI Server (MTG Deck Builder)
"C:\Users\rvn92\Documents\ComfyUI\.venv\Scripts\python.exe" ^
    "E:\Games\comfy\ComfyUI\resources\ComfyUI\main.py" ^
    --port 8188 ^
    --listen 127.0.0.1 ^
    --base-directory "C:\Users\rvn92\Documents\ComfyUI" ^
    --disable-dynamic-vram
