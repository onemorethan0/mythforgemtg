"""Check exactly which DLL dependency is missing for onnxruntime_providers_cuda.dll"""
import ctypes
import os
import sys

dll_path = r'C:\Users\rvn92\Documents\ComfyUI\.venv\Lib\site-packages\onnxruntime\capi\onnxruntime_providers_cuda.dll'

# Add the directory to DLL search path (Windows 3.8+)
dll_dir = os.path.dirname(dll_path)
os.add_dll_directory(dll_dir)

# Also add nvidia package directories
venv_site = r'C:\Users\rvn92\Documents\ComfyUI\.venv\Lib\site-packages'
nvidia_dirs = [
    os.path.join(venv_site, 'nvidia', d, 'bin')
    for d in ['cublas', 'cuda_runtime', 'cudnn', 'cufft', 'curand', 'cusolver', 'cusparse', 'nvjitlink', 'cuda_nvrtc']
]
for d in nvidia_dirs:
    if os.path.exists(d):
        os.add_dll_directory(d)
        print(f"Added DLL path: {d}")

print(f"\nAttempting to load: {dll_path}")

try:
    ctypes.WinDLL(dll_path)
    print("SUCCESS: DLL loaded!")
except OSError as e:
    print(f"FAILED: {e}")
    print(f"\nError code: {e.winerror if hasattr(e, 'winerror') else 'unknown'}")

    # Try with LOAD_WITH_ALTERED_SEARCH_PATH flag
    print("\nTrying with LOAD_WITH_ALTERED_SEARCH_PATH...")
    try:
        ctypes.CDLL(dll_path, winmode=8)  # LOAD_WITH_ALTERED_SEARCH_PATH
        print("SUCCESS with altered search path!")
    except OSError as e2:
        print(f"Still failed: {e2}")
