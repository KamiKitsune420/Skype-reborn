"""Skype Reborn — server entry point with pre-flight dependency check."""
import sys
import os

# ── ANSI colours (work on Linux, macOS and Windows 10+) ──────────
_G = "\033[92m"   # green
_Y = "\033[93m"   # yellow
_R = "\033[91m"   # red
_B = "\033[94m"   # blue
_W = "\033[97m"   # white
_X = "\033[0m"    # reset

def _ok(msg):   print(f"  {_G}[OK]{_X}   {msg}")
def _warn(msg): print(f"  {_Y}[!!]{_X}   {msg}")
def _fail(msg): print(f"  {_R}[XX]{_X}   {msg}")

def preflight():
    """Run dependency / environment checks before starting uvicorn."""
    print(f"\n{_B}{'='*50}{_X}")
    print(f"{_W}  Skype Reborn -- startup check{_X}")
    print(f"{_B}{'='*50}{_X}\n")

    ok = True

    # ── Python version ────────────────────────────────────────────
    pv = sys.version_info
    if pv >= (3, 10):
        _ok(f"Python {pv.major}.{pv.minor}.{pv.micro}")
    else:
        _fail(f"Python {pv.major}.{pv.minor} — need 3.10+")
        ok = False

    # ── Required Python packages ──────────────────────────────────
    REQUIRED = [
        ("fastapi",           "fastapi"),
        ("uvicorn",           "uvicorn"),
        ("sqlalchemy",        "sqlalchemy"),
        ("aiosqlite",         "aiosqlite"),
        ("websockets",        "websockets"),
        ("httpx",             "httpx"),
        ("pydantic",          "pydantic"),
        ("pydantic_settings", "pydantic-settings"),
        ("structlog",         "structlog"),
        ("numpy",             "numpy"),
        ("aiofiles",          "aiofiles"),
        ("jose",              "python-jose"),
        ("cryptography",      "cryptography"),
        ("argon2",            "argon2-cffi"),
    ]
    for module, pkg in REQUIRED:
        try:
            __import__(module)
            _ok(f"{pkg}")
        except ImportError:
            _fail(f"{pkg} not installed  →  pip install {pkg}")
            ok = False

    # ── opuslib / libopus (needed for the echo-service bot) ───────
    try:
        import opuslib  # noqa: F401
        _ok("opuslib (Opus codec)")
    except Exception:
        if sys.platform == "win32":
            dll = os.path.join(os.path.dirname(__file__), "lib", "libopus.dll")
            if os.path.exists(dll):
                _warn("opuslib import failed but lib/libopus.dll is present "
                      "(the bot will patch the path at startup)")
            else:
                _warn("opuslib not importable — echo bot audio will be silent.\n"
                      "       Place libopus.dll in lib/ or run: pip install opuslib")
        else:
            _warn("opuslib not importable — echo bot audio will be silent.\n"
                  f"       Linux: apt install libopus-dev && pip install opuslib\n"
                  f"       macOS: brew install opus && pip install opuslib")

    # ── Platform-specific libopus ─────────────────────────────────
    if sys.platform != "win32":
        import ctypes.util
        lib = ctypes.util.find_library("opus")
        if lib:
            _ok(f"libopus system library: {lib}")
        else:
            _warn("libopus not found in system library paths\n"
                  "       Ubuntu/Debian: sudo apt install libopus-dev\n"
                  "       macOS:         brew install opus")
    else:
        dll = os.path.join(os.path.dirname(__file__), "lib", "libopus.dll")
        if os.path.exists(dll):
            _ok(f"lib/libopus.dll present")
        else:
            _warn("lib/libopus.dll not found — echo bot audio will be silent")

    # ── Asset directories ─────────────────────────────────────────
    for path in ("assets/sounds", "assets/images"):
        if os.path.isdir(path):
            _ok(f"Directory: {path}")
        else:
            _warn(f"Missing directory: {path}  (some features may not work)")

    # ── Upload directory (auto-created on startup) ─────────────────
    upload_dir = os.environ.get("UPLOAD_DIR", "server/uploads")
    if os.path.isdir(upload_dir):
        _ok(f"Upload dir: {upload_dir}")
    else:
        _warn(f"Upload dir missing: {upload_dir}  (will be created at startup)")

    # ── Database writability ──────────────────────────────────────
    try:
        db_path = "skype_reborn.db"
        test_file = db_path + ".write_test"
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        _ok(f"Database directory is writable")
    except OSError as e:
        _fail(f"Cannot write to current directory: {e}")
        ok = False

    # ── Port availability ─────────────────────────────────────────
    import socket
    for port, name in ((9433, "HTTP/WS API"), (9000, "UDP voice relay")):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM if port == 9433 else socket.AF_INET) as s:
            try:
                s.bind(("0.0.0.0", port))
                _ok(f"Port {port} ({name}) is free")
            except OSError:
                if port == 9433:
                    _fail(f"Port {port} ({name}) is already in use")
                    ok = False
                else:
                    _warn(f"Port {port} ({name}) may be in use — voice relay might fail")

    # ── .env file ─────────────────────────────────────────────────
    if os.path.exists(".env"):
        _ok(".env file found")
    else:
        _warn(".env not found — using default settings (SECRET_KEY will be random)")

    print()
    if ok:
        print(f"{_G}  All checks passed — starting server…{_X}\n")
    else:
        print(f"{_R}  One or more checks failed.  Fix the issues above before starting.{_X}\n")
        sys.exit(1)

    return ok


if __name__ == "__main__":
    preflight()

    import uvicorn
    from server.main import app

    uvicorn.run(app, host="0.0.0.0", port=9433)
