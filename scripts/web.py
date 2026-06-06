#!/usr/bin/env python3
"""Cross-platform dev launcher for the web console.

Runs `catranger serve` (FastAPI, :8080) and the Next.js console dev server
(`pnpm dev`, :3000) together in one terminal, and tears both down on Ctrl-C or
when either exits. Works on Windows/macOS/Linux — no `make`, shell `&`, or
`trap` required (the DX review flagged that `make web` is Unix-only).

    python scripts/web.py        # from the repo root
    make web                     # convenience wrapper (Unix)
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_WEB = _REPO / "apps" / "web"


def main() -> int:
    if not (_WEB / "node_modules").is_dir():
        print("[web] apps/web deps not installed — run: pnpm install --dir apps/web")
        return 1

    print("[web] starting FastAPI (:8080) + Next.js console (:3000) … Ctrl-C to stop")
    procs: list[subprocess.Popen] = [
        subprocess.Popen([sys.executable, "-m", "catranger.cli", "serve"], cwd=str(_REPO)),
        # shell=True so Windows resolves pnpm.cmd / pnpm.ps1 on PATH.
        subprocess.Popen("pnpm dev", cwd=str(_WEB), shell=True),
    ]
    try:
        while True:
            for p in procs:
                rc = p.poll()
                if rc is not None:
                    print(f"[web] a process exited (code {rc}) — shutting down the other")
                    return rc or 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[web] stopping …")
        return 0
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()


if __name__ == "__main__":
    raise SystemExit(main())
