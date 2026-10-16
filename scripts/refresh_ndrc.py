"""Refresh NDRC recommendations independently of the exchange collection batch."""
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
from scripts.validate_ndrc_data import validate

BEIJING = ZoneInfo("Asia/Shanghai")


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def implementation_digest(root):
    paths = [Path(root) / name for name in ('collectors/ndrc_recommendations.py',
             'collectors/ndrc_matching.py', 'scripts/validate_ndrc_data.py', 'scripts/refresh_ndrc.py')]
    if not all(path.exists() for path in paths):
        return None
    return hashlib.sha256(''.join(digest(path) for path in paths).encode()).hexdigest()


def refresh_due(snapshot, status, public_sha, now=None, force=False, snapshot_sha=None,
                review_config_sha=None, implementation_sha=None):
    now = (now or datetime.now(BEIJING)).astimezone(BEIJING)
    if force:
        return True
    try:
        validate(snapshot)
        collected = datetime.fromisoformat(snapshot["updated_at"])
        return not (snapshot["date"] == now.date().isoformat()
                    and collected.tzinfo is not None and collected <= now
                    and collected.astimezone(BEIJING).date() == now.date()
                    and status["attempt_ok"] is True and status["status"] == "complete"
                    and status["public_snapshot_sha256"] == public_sha
                    and (snapshot_sha is None or status["snapshot_sha256"] == snapshot_sha)
                    and (review_config_sha is None or status.get("review_config_sha256") == review_config_sha)
                    and (implementation_sha is None or status.get("implementation_sha256") == implementation_sha))
    except (KeyError, TypeError, ValueError, AttributeError):
        return True


def run_refresh(root=ROOT, run_id=None, force=False, now=None, runner=subprocess.run):
    root = Path(root)
    now = (now or datetime.now(BEIJING)).astimezone(BEIJING)
    output, public_path = root / "data/ndrc_recommendations.json", root / "data/public_reits.json"
    status_path = root / "data/ndrc_refresh_status.json"
    previous, old_status = read(output), read(status_path) or {}
    public_sha = digest(public_path)
    config = root / 'config/ndrc_exchange_links.json'
    config_sha = digest(config) if config.exists() else None
    implementation_sha = implementation_digest(root)
    if not refresh_due(previous, old_status, public_sha, now, force,
                       digest(output) if output.exists() else None, config_sha, implementation_sha):
        return {"status": "already_complete", "date": now.date().isoformat()}
    batch_id = run_id or now.strftime("%Y%m%dT%H%M%S")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", batch_id):
        raise ValueError("Invalid batch ID")
    work = root / "workpapers/ndrc/refresh" / batch_id
    work.mkdir(parents=True, exist_ok=False)
    raw = root / "data/raw/ndrc/refresh" / batch_id
    candidate = work / "ndrc_candidate.json"
    if output.exists():
        shutil.copy2(output, candidate)
    command = [sys.executable, "-m", "collectors.ndrc_recommendations", "--output", str(candidate),
               "--public-input", str(public_path), "--raw-dir", str(raw),
               "--work-dir", str(work / "collection")]
    attempted = now.isoformat(timespec="seconds")
    try:
        with (work / "collection.log").open("w", encoding="utf-8") as log:
            runner(command, cwd=root, check=True, stdout=log, stderr=subprocess.STDOUT)
        result = read(candidate)
        audit = validate(result, read(public_path))
        if digest(public_path) != public_sha:
            raise ValueError("Public snapshot changed during matching; retry against one version")
        # The collector validated its candidate. Replace the live file only after
        # cross-checking its relations against the exact publication input.
        temporary = output.with_suffix(".json.tmp")
        shutil.copy2(candidate, temporary)
        temporary.replace(output)
        completed = datetime.now(BEIJING).isoformat(timespec="seconds")
        status = {"status": "complete", "attempt_ok": True, "date": now.date().isoformat(),
                  "batch_id": batch_id, "last_attempt_at": attempted, "completed_at": completed,
                  "last_successful_at": completed, "public_snapshot_sha256": public_sha,
                  "review_config_sha256": config_sha, "implementation_sha256": implementation_sha,
                  "snapshot_sha256": digest(output), "validation": audit,
                  "latest_recommended_date": result.get("coverage", {}).get("latest_recommended_date")}
        write(work / "release.json", {**status, "command": command, "raw_dir": str(raw.relative_to(root)),
                                     "work_dir": str(work.relative_to(root))})
        write(status_path, status)
        return status
    except Exception as exc:
        status = {"status": "failed", "attempt_ok": False, "date": now.date().isoformat(),
                  "batch_id": batch_id, "last_attempt_at": attempted,
                  "last_successful_at": old_status.get("last_successful_at"),
                  "public_snapshot_sha256": public_sha,
                  "review_config_sha256": config_sha, "implementation_sha256": implementation_sha,
                  "snapshot_sha256": digest(output) if output.exists() else None,
                  "error": str(exc), "policy": "Retain last complete recommendation snapshot"}
        write(work / "failure.json", status)
        write(status_path, status)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    if args.check_only:
        output = ROOT / "data/ndrc_recommendations.json"
        public = ROOT / "data/public_reits.json"
        config = ROOT / 'config/ndrc_exchange_links.json'
        due = refresh_due(read(output), read(ROOT / "data/ndrc_refresh_status.json"),
                          digest(public), force=args.force,
                          snapshot_sha=digest(output) if output.exists() else None,
                          review_config_sha=digest(config) if config.exists() else None,
                          implementation_sha=implementation_digest(ROOT))
        print("due=" + str(due).lower())
        return 0
    try:
        print(json.dumps(run_refresh(run_id=args.run_id, force=args.force), ensure_ascii=False))
        return 0
    except Exception as exc:
        print("Recommendation refresh failed; retained last complete snapshot: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
