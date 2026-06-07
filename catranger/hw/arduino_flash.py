"""Flash the CatRanger Arduino sketch over USB via arduino-cli.

The web console's Connections tab calls this when the operator clicks "Flash
firmware". Requires arduino-cli on PATH and a USB-connected Arduino Mega.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SKETCH_DIR = _REPO_ROOT / "arduino" / "cat_ranger"
DEFAULT_FQBN = "arduino:avr:mega"
_CORE = "arduino:avr"
_LIBS = (
    "Adafruit Motor Shield library",
    "LiquidCrystal I2C",
)


def find_cli() -> str | None:
    return shutil.which("arduino-cli")


def readiness(
    *,
    sketch_dir: Path = DEFAULT_SKETCH_DIR,
    fqbn: str = DEFAULT_FQBN,
) -> dict[str, Any]:
    """Probe whether flashing is possible on this machine."""
    cli = find_cli()
    out: dict[str, Any] = {
        "ok": cli is not None and sketch_dir.is_dir(),
        "arduino_cli": cli,
        "sketch_dir": str(sketch_dir),
        "fqbn": fqbn,
    }
    if cli is None:
        out["problem"] = "arduino-cli not found on PATH"
        out["fix"] = (
            "install arduino-cli (brew install arduino-cli), "
            "then run: arduino-cli core install arduino:avr"
        )
        return out
    if not sketch_dir.is_dir():
        out["problem"] = f"sketch directory missing: {sketch_dir}"
        out["fix"] = "clone the repo with arduino/cat_ranger/cat_ranger.ino present"
        return out
    return out


def _run(cmd: list[str], *, timeout: float = 300) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:

        def _stream_text(chunk: str | bytes | None) -> str:
            if chunk is None:
                return ""
            if isinstance(chunk, bytes):
                return chunk.decode("utf-8", errors="replace")
            return chunk

        tail = _stream_text(exc.stdout) + _stream_text(exc.stderr)
        return 124, tail[-4000:] or "arduino-cli timed out"
    except OSError as exc:
        return 127, str(exc)
    combined = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, combined[-8000:]


def _ensure_toolchain(cli: str) -> tuple[bool, str]:
    steps: list[list[str]] = [
        [cli, "core", "install", _CORE],
        *[[cli, "lib", "install", lib] for lib in _LIBS],
    ]
    log: list[str] = []
    for cmd in steps:
        rc, out = _run(cmd, timeout=600)
        log.append(f"$ {' '.join(cmd)}\n{out}")
        if rc != 0:
            return False, "\n".join(log)
    return True, "\n".join(log)


def flash_sketch(
    port: str | None,
    *,
    sketch_dir: Path = DEFAULT_SKETCH_DIR,
    fqbn: str = DEFAULT_FQBN,
    install_deps: bool = True,
) -> dict[str, Any]:
    """Compile and upload cat_ranger.ino. Returns {ok, log, port?}."""
    ready = readiness(sketch_dir=sketch_dir, fqbn=fqbn)
    if not ready.get("ok"):
        return {"ok": False, **ready}

    cli = ready["arduino_cli"]
    assert isinstance(cli, str)

    logs: list[str] = []
    if install_deps:
        ok, setup_log = _ensure_toolchain(cli)
        logs.append(setup_log)
        if not ok:
            return {
                "ok": False,
                "code": "flash_setup_failed",
                "problem": "arduino-cli core/library install failed",
                "log": "\n".join(logs),
            }

    compile_cmd = [cli, "compile", "--fqbn", fqbn, str(sketch_dir)]
    rc, out = _run(compile_cmd, timeout=300)
    logs.append(f"$ {' '.join(compile_cmd)}\n{out}")
    if rc != 0:
        return {
            "ok": False,
            "code": "flash_compile_failed",
            "problem": "sketch compile failed",
            "log": "\n".join(logs),
        }

    upload_cmd = [cli, "upload", "--fqbn", fqbn, str(sketch_dir)]
    if port:
        upload_cmd[2:2] = ["-p", port]
    rc, out = _run(upload_cmd, timeout=120)
    logs.append(f"$ {' '.join(upload_cmd)}\n{out}")
    if rc != 0:
        return {
            "ok": False,
            "code": "flash_upload_failed",
            "problem": "upload failed — is the Mega plugged in via USB?",
            "fix": "pick the USB serial port from Scan devices, or pass -p /dev/ttyACM0",
            "log": "\n".join(logs),
            "port": port,
        }

    return {
        "ok": True,
        "port": port,
        "fqbn": fqbn,
        "sketch_dir": str(sketch_dir),
        "log": "\n".join(logs),
    }
