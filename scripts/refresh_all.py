"""Collect both REIT libraries as one validated, traceable daily release."""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.refresh_due import refresh_due as institutional_due
from scripts.validate_data import validate as validate_institutional
from scripts.validate_public_data import validate as validate_public
BEIJING = ZoneInfo("Asia/Shanghai")
FILES = {"institutional": "institutional.json", "public": "public_reits.json"}


def read(path, fallback=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def record_failed_attempt(output_dir, batch_id, started_at, error, now=None):
    """Keep the last complete pair and separately expose the latest failed attempt."""
    now = (now or datetime.now(BEIJING)).astimezone(BEIJING)
    status_path = Path(output_dir) / 'refresh_status.json'
    previous = read(status_path, {}) or {}
    status = {**previous, 'status': 'failed', 'attempt_ok': False,
              'last_attempt_batch_id': batch_id, 'last_attempt_at': started_at,
              'failed_at': now.isoformat(timespec='seconds'), 'error': str(error),
              'last_successful_at': previous.get('last_successful_at') or previous.get('completed_at'),
              'policy': 'Retain the last complete public and institutional snapshots'}
    write(status_path, status)
    return status


def public_due(snapshot, now):
    try:
        validate_public(snapshot)
        times = [datetime.fromisoformat(snapshot["source_status"][key]["collected_at"]) for key in ("SSE", "SZSE")]
        return not (snapshot["date"] == now.date().isoformat() and all(
            item.tzinfo is not None and item <= now and item.astimezone(BEIJING).date() == now.date() for item in times))
    except (KeyError, TypeError, ValueError, AttributeError):
        return True


def refresh_due(institutional, public, status, now=None, force=False):
    now = (now or datetime.now(BEIJING)).astimezone(BEIJING)
    if force or institutional_due(institutional, now) or public_due(public, now):
        return True
    try:
        batch_id = status["batch_id"]
        return not (batch_id and status["status"] == "complete" and status["date"] == now.date().isoformat()
                    and institutional["refresh_batch"]["id"] == public["refresh_batch"]["id"] == batch_id)
    except (KeyError, TypeError):
        return True


def publish_candidates(candidates, output_dir, batch_id, started_at, now=None):
    """Validate the complete pair before touching either final data file."""
    now = (now or datetime.now(BEIJING)).astimezone(BEIJING)
    snapshots = {key: read(candidates[key]) for key in FILES}
    validation = {"institutional": validate_institutional(snapshots["institutional"]),
                  "public": validate_public(snapshots["public"])}
    if institutional_due(snapshots["institutional"], now) or public_due(snapshots["public"], now):
        raise ValueError("Both libraries require complete source and identity checks for today's Beijing date")
    batch = {"id": batch_id, "date": now.date().isoformat(), "started_at": started_at,
             "completed_at": now.isoformat(timespec="seconds")}
    source_hashes = {key: hashlib.sha256(Path(path).read_bytes()).hexdigest() for key, path in candidates.items()}
    output_dir = Path(output_dir)
    for snapshot in snapshots.values():
        snapshot["refresh_batch"] = batch
    status = {"status": "complete", "attempt_ok": True, "date": batch["date"], "batch_id": batch_id,
              "started_at": started_at, "completed_at": batch["completed_at"], "validation": validation,
              "last_successful_at": batch["completed_at"], "last_attempt_at": started_at,
              "disclosure_checked_at": {key: value.get("enrichment", {}).get("checked_at") for key, value in snapshots.items()}}
    for key, snapshot in snapshots.items():
        write(output_dir / FILES[key], snapshot)
    write(output_dir / "refresh_status.json", status)
    return {"batch": batch, "validation": validation, "source_snapshot_sha256": source_hashes,
            "output_sha256": {key: hashlib.sha256((output_dir / name).read_bytes()).hexdigest() for key, name in FILES.items()},
            "transformation": "Add shared refresh_batch metadata after both snapshots pass validation; preserve research disclosure dates"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    now = datetime.now(BEIJING)
    due = refresh_due(read(ROOT / "data/institutional.json"), read(ROOT / "data/public_reits.json"),
                      read(ROOT / "data/refresh_status.json"), now, args.force)
    if args.check_only:
        print("due=" + str(due).lower())
        return 0
    if not due:
        print(json.dumps({"status": "already_complete", "date": now.date().isoformat()}))
        return 0
    batch_id = args.run_id or now.strftime("%Y%m%dT%H%M%S")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", batch_id):
        raise ValueError("Invalid batch ID")
    work = ROOT / "workpapers/daily_refresh" / batch_id
    raw = ROOT / "data/raw/daily_refresh" / batch_id
    work.mkdir(parents=True, exist_ok=False)
    raw.mkdir(parents=True, exist_ok=False)
    candidates = {key: work / "collected" / name for key, name in FILES.items()}
    for key, path in candidates.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "data" / FILES[key], path)
    started_at = now.isoformat(timespec="seconds")
    commands = {
        "institutional": [sys.executable, "-m", "collectors.institutional", "--output", str(candidates["institutional"]),
                          "--archive-dir", str(work / "institutional_snapshots"), "--verify-links", "--raw-dir", str(raw / "institutional")],
        "public": [sys.executable, "-m", "collectors.public_reits", "--output", str(candidates["public"]),
                   "--work-dir", str(work / "public"), "--raw-dir", str(raw / "public")],
    }
    def collect(key):
        with (work / (key + ".log")).open("w", encoding="utf-8") as log:
            subprocess.run(commands[key], cwd=ROOT, check=True, stdout=log, stderr=subprocess.STDOUT)
        return key
    try:
        # Both populations share the same exchange hosts. Avoid multiplying
        # request rates across two independent subprocesses.
        for key in FILES:
            print(json.dumps({"collected": collect(key)}), flush=True)
        manifest = publish_candidates(candidates, ROOT / "data", batch_id, started_at)
        manifest.update({"raw_dir": str(raw.relative_to(ROOT)), "workpaper": str(work.relative_to(ROOT)),
                         "commands": {key: [str(Path(arg).relative_to(ROOT)) if str(arg).startswith(str(ROOT) + "/") else arg for arg in command] for key, command in commands.items()},
                         "raw_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(raw.rglob("*")) if p.is_file()}})
        write(work / "validation.json", manifest)
        write(ROOT / "data/source_manifest/daily_refresh" / (batch_id + ".json"), manifest)
        print(json.dumps({"status": "complete", "batch_id": batch_id, "validation": manifest["validation"]}, ensure_ascii=False))
        return 0
    except Exception as exc:
        record_failed_attempt(ROOT / 'data', batch_id, started_at, exc)
        write(work / "failure.json", {"batch_id": batch_id, "failed_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
                                      "error": str(exc), "policy": "Do not commit or deploy a partial collection"})
        print("Combined refresh failed; do not publish partial data: " + str(exc), file=sys.stderr)
        for key in FILES:
            log_path = work / (key + ".log")
            if log_path.exists():
                print(f"Collector diagnostics ({key}):\n" + log_path.read_text(encoding="utf-8")[-12000:], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
