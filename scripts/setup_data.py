#!/usr/bin/env python3
"""Wire the provided contest inference sets into data/raw/ and (optionally) fetch a
cat demo clip. Idempotent.

    python scripts/setup_data.py                          # symlink the contest sets
    python scripts/setup_data.py --cat-url "<youtube/cc cat video url>"   # + demo clip
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
RAW = DATA / "raw"
DEFAULT_CONTEST = Path.home() / "Downloads" / "inference_sets_contest"


def link(src: Path, dst: Path) -> None:
    if not src.exists():
        print(f"  skip (not found): {src}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        print(f"  exists: {dst}")
        return
    os.symlink(src, dst)
    print(f"  linked: {dst} -> {src}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contest", default=str(DEFAULT_CONTEST), help="path to inference_sets_contest")
    ap.add_argument("--cat-url", default=None, help="optional public cat video to fetch via yt-dlp")
    args = ap.parse_args()

    contest = Path(args.contest)
    print(f"Linking contest sets from: {contest}")
    link(contest / "how_far", RAW / "how_far")
    link(contest / "mental_map", RAW / "mental_map")
    link(contest / "go2_camera_details.txt", RAW / "go2_camera_details.txt")

    if args.cat_url:
        out = DATA / "cat_demo.mp4"
        print(f"Fetching cat demo clip -> {out}")
        try:
            subprocess.run(
                ["yt-dlp", "-f", "mp4", args.cat_url, "-o", str(out)], check=True
            )
        except FileNotFoundError:
            print("  yt-dlp not installed: pip install yt-dlp", file=sys.stderr)
        except subprocess.CalledProcessError as e:
            print(f"  download failed: {e}", file=sys.stderr)

    print("done. inference sets under data/raw/ ; run a demo with:")
    print("  python scripts/demo.py --source data/raw/how_far --save outputs/how_far_demo")


if __name__ == "__main__":
    main()
