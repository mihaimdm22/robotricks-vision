"""Local run history: archive every overnight train/eval run + a queryable index.

`runs/history/` is the on-disk record of what happened overnight. Each run gets its
own timestamped directory; one append-only `index.jsonl` plus a rendered `INDEX.md`
make the whole night reviewable in the morning. Stdlib only (no torch / numpy) so
the index can be read and printed on any box, even without the ML extra installed.

Layout::

    runs/history/
      index.jsonl                      one JSON line per archived run (append-only)
      INDEX.md                         human-readable table, regenerated each append
      20260606-231500-autoresearch/
        meta.json                      kind, status, ts, duration_s, metric, summary
        params.json                    what was run (config, overrides, source, ...)
        metrics.json                   structured metrics (eval) / winner (train)
        run.log                        captured stdout+stderr
        best.pt                        copied trained weights (train runs)
        report.md                      copied eval report (eval runs)

Nothing here imports the perception stack, so `python -m catranger.history` works as
a zero-dependency "what happened last night?" command.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = _REPO_ROOT / "runs" / "history"
_INDEX_NAME = "index.jsonl"
_INDEX_MD_NAME = "INDEX.md"


def stamp(dt: datetime | None = None) -> str:
    """A sortable, filesystem-safe timestamp (``YYYYMMDD-HHMMSS``).

    `dt` is injectable so callers/tests can pin the value; defaults to local now.
    """
    return (dt or datetime.now()).strftime("%Y%m%d-%H%M%S")


def _base(base: Path | None) -> Path:
    return base if base is not None else HISTORY_DIR


def archive_run(
    kind: str,
    *,
    ts: str,
    status: str = "ok",
    params: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    metric: float | None = None,
    metric_key: str | None = None,
    summary: str = "",
    duration_s: float | None = None,
    log_text: str | None = None,
    artifacts: dict[str, str] | None = None,
    base: Path | None = None,
) -> Path:
    """Archive one run to ``runs/history/<ts>-<kind>/`` and append the index.

    Args:
      kind:       run type, e.g. ``"autoresearch"``, ``"train"``, ``"eval"``.
      ts:         timestamp prefix (see :func:`stamp`) — also the dir name prefix.
      status:     ``"ok"`` | ``"fail"`` | ``"skipped"``.
      params:     what was run (config path, overrides, source, device, ...).
      metrics:    structured result dict (eval metrics, or the train winner dict).
      metric:     the single headline number for the index column (optional).
      metric_key: label for ``metric`` (e.g. ``"mean_fps"`` or ``"mAP50-95"``).
      summary:    one-line human summary for INDEX.md.
      duration_s: wall-clock seconds the run took.
      log_text:   captured stdout+stderr to persist as ``run.log``.
      artifacts:  ``{dest_filename: source_path}`` files to copy into the run dir.
      base:       history root (defaults to ``runs/history/``; injectable for tests).

    Returns the created run directory.
    """
    root = _base(base)
    run_dir = root / f"{ts}-{kind}"
    run_dir.mkdir(parents=True, exist_ok=True)

    meta: dict[str, Any] = {
        "kind": kind,
        "ts": ts,
        "status": status,
        "duration_s": duration_s,
        "metric": metric,
        "metric_key": metric_key,
        "summary": summary,
    }
    _write_json(run_dir / "meta.json", meta)
    if params is not None:
        _write_json(run_dir / "params.json", params)
    if metrics is not None:
        _write_json(run_dir / "metrics.json", metrics)
    if log_text is not None:
        (run_dir / "run.log").write_text(log_text, encoding="utf-8")

    copied: list[str] = []
    digests: dict[str, str] = {}
    for dest_name, src in (artifacts or {}).items():
        src_path = Path(src)
        if src_path.exists():
            # WS-A6: atomic copy (temp + os.replace) so a crash mid-copy never leaves a
            # half-written best.pt/report.md, and record a sha256 to detect corruption.
            digests[dest_name] = _atomic_copy(src_path, run_dir / dest_name)
            copied.append(dest_name)
    if copied:
        meta["artifacts"] = copied
        meta["sha256"] = digests
        _write_json(run_dir / "meta.json", meta)

    entry = {
        "ts": ts,
        "kind": kind,
        "status": status,
        "metric": metric,
        "metric_key": metric_key,
        "duration_s": duration_s,
        "summary": summary,
        "dir": run_dir.name,
    }
    append_index(entry, base=root)
    return run_dir


def append_index(entry: dict[str, Any], *, base: Path | None = None) -> None:
    """Append one entry to ``index.jsonl`` and regenerate ``INDEX.md``."""
    root = _base(base)
    root.mkdir(parents=True, exist_ok=True)
    with open(root / _INDEX_NAME, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    render_index(base=root)


def read_index(*, base: Path | None = None) -> list[dict[str, Any]]:
    """Return every archived run entry, oldest first ([] if none yet)."""
    path = _base(base) / _INDEX_NAME
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def render_index(*, base: Path | None = None) -> str:
    """(Re)write ``INDEX.md`` from ``index.jsonl`` and return its text."""
    root = _base(base)
    entries = read_index(base=root)
    lines = ["# CatRanger run history", ""]
    if not entries:
        lines.append("_No runs archived yet._")
        lines.append("")
    else:
        lines.append(f"{len(entries)} run(s). Newest last.")
        lines.append("")
        lines.append("| When | Kind | Status | Metric | Took | Summary | Dir |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for e in entries:
            lines.append(
                "| {ts} | {kind} | {status} | {metric} | {took} | {summary} | `{dir}` |".format(
                    ts=e.get("ts", "—"),
                    kind=e.get("kind", "—"),
                    status=e.get("status", "—"),
                    metric=_fmt_metric(e.get("metric"), e.get("metric_key")),
                    took=_fmt_secs(e.get("duration_s")),
                    summary=(e.get("summary") or "").replace("|", "\\|"),
                    dir=e.get("dir", "—"),
                )
            )
        lines.append("")
    text = "\n".join(lines)
    root.mkdir(parents=True, exist_ok=True)
    (root / _INDEX_MD_NAME).write_text(text, encoding="utf-8")
    return text


def _fmt_metric(metric: object, metric_key: object) -> str:
    if metric is None:
        return "—"
    value = f"{metric:.4g}" if isinstance(metric, (int, float)) else str(metric)
    return f"{value} ({metric_key})" if metric_key else value


def _fmt_secs(seconds: object) -> str:
    if not isinstance(seconds, (int, float)):
        return "—"
    if seconds < 90:
        return f"{seconds:.0f}s"
    return f"{seconds / 60.0:.1f}m"


def _sha256(path: Path) -> str:
    """Streaming sha256 of a file (handles large best.pt without loading it whole)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_copy(src: Path, dst: Path) -> str:
    """Copy src -> dst atomically (temp in the SAME dir + os.replace) so readers never
    see a partial file after a crash. Returns the sha256 of the copied bytes (WS-A6)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dst.parent), prefix=f".{dst.name}.", suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        shutil.copyfile(src, tmp_path)
        digest = _sha256(tmp_path)
        os.replace(tmp_path, dst)  # atomic on the same filesystem (POSIX + Windows)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    return digest


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    """Write JSON atomically (temp + os.replace) so a crash never truncates meta.json."""
    text = json.dumps(obj, indent=2, default=str)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if Path(tmp).exists():
            Path(tmp).unlink()
        raise


def main(argv: list[str] | None = None) -> int:
    """`python -m catranger.history` — print the run-history index to stdout."""
    entries = read_index()
    if not entries:
        print(f"no runs archived yet (nothing under {HISTORY_DIR})")
        return 0
    print(render_index())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
