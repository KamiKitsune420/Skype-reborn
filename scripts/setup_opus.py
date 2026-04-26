import os
import sys
import platform

def setup_opus():
    print("=== Skype™ Reborn: Opus Audio Setup ===")
    
    if platform.system() != "Windows":
        print("This script is currently optimized for Windows (win32).")
        print("On Linux/macOS, please install libopus via your package manager:")
        print("  Ubuntu/Debian: sudo apt-get install libopus0")
        print("  macOS: brew install opus")
        return

    print("\nTo enable high-quality compressed audio (Opus), you need 'opus.dll'.")
    print("1. Download libopus-0.dll (x64) from a trusted source, e.g.:")
    print("   https://github.com/Emzi0767/discord-binaries/blob/master/libopus/x64/libopus-0.dll")
    print("2. Rename it to 'opus.dll'.")
    print("3. Place it in the project root directory:")
    print(f"   {os.getcwd()}")
    
    # Check if it already exists
    if os.path.exists("opus.dll"):
        print("\n[SUCCESS] 'opus.dll' was found in the project root.")
        try:
            import opuslib
            print("[SUCCESS] opuslib was able to load the DLL successfully!")
        except Exception as e:
            print(f"[ERROR] Found opus.dll but failed to load it: {e}")
    else:
        print("\n[MISSING] 'opus.dll' not found. The app will fallback to raw PCM (high bandwidth).")

if __name__ == "__main__":
    setup_opus()
