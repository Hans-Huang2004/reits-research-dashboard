"""Validate the shared successful batch before publishing either REIT library."""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
BEIJING = ZoneInfo("Asia/Shanghai")
SNAPSHOTS = ("institutional.json", "public_reits.json")
BATCH_KEYS = ("id", "date", "started_at", "completed_at")


def _read_object(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read release metadata from {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or invalid {label}")
    return value


def _date(value, label):
    value = _text(value, label)
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid calendar date for {label}: {value}") from exc


def _timestamp(value, label):
    value = _text(value, label)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid timestamp for {label}: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"Timezone is required for {label}")
    return parsed


def validate_release(root=ROOT):
    """Return a release report or raise ValueError; never read the network or write.

    ``batch_id``, ``date`` and the batch timestamps always describe the last
    successful pair. A failed later attempt belongs only in the attempt fields.
    Older complete snapshots remain publishable, including their failure notice.
    Individual record validation remains the responsibility of each data validator.
    """
    data = Path(root) / "data"
    snapshots = {name: _read_object(data / name) for name in SNAPSHOTS}
    status = _read_object(data / "refresh_status.json")
    batches = {}
    for name, snapshot in snapshots.items():
        coverage = snapshot.get("coverage")
        if not isinstance(coverage, dict) or coverage.get("complete") is not True:
            raise ValueError(f"{name} is not a complete retained snapshot")
        batch = snapshot.get("refresh_batch")
        if not isinstance(batch, dict):
            raise ValueError(f"Missing refresh_batch in {name}")
        for key in BATCH_KEYS:
            _text(batch.get(key), f"{name}.refresh_batch.{key}")
        _date(snapshot.get("date"), f"{name}.date")
        batches[name] = batch

    batch = batches[SNAPSHOTS[0]]
    if any(other != batch for other in batches.values()):
        raise ValueError("Release snapshots do not share the same complete refresh_batch metadata")
    batch_date = _date(batch["date"], "refresh_batch.date")
    started = _timestamp(batch["started_at"], "refresh_batch.started_at")
    completed = _timestamp(batch["completed_at"], "refresh_batch.completed_at")
    if started > completed:
        raise ValueError("refresh_batch.started_at is after completed_at")
    if completed.astimezone(BEIJING).date() != batch_date:
        raise ValueError("refresh_batch.date differs from its Beijing completion date")
    for name, snapshot in snapshots.items():
        if snapshot["date"] != batch["date"]:
            raise ValueError(f"{name}.date differs from the successful refresh_batch.date")

    _date(status.get("date"), "refresh_status.date")
    for status_key, batch_key in (("batch_id", "id"), ("date", "date"),
                                  ("started_at", "started_at"), ("completed_at", "completed_at")):
        if _text(status.get(status_key), f"refresh_status.{status_key}") != batch[batch_key]:
            raise ValueError(f"refresh_status.{status_key} differs from the successful batch")
    if status.get("last_successful_at") != batch["completed_at"]:
        raise ValueError("refresh_status.last_successful_at must retain the successful batch completion time")

    state = status.get("status")
    attempt_started = _timestamp(status.get("last_attempt_at"), "refresh_status.last_attempt_at")
    if state == "complete":
        if status.get("attempt_ok") is not True:
            raise ValueError("Complete refresh_status requires attempt_ok=true")
        if status["last_attempt_at"] != batch["started_at"]:
            raise ValueError("Complete refresh_status.last_attempt_at differs from the successful batch start")
        if "last_attempt_batch_id" in status and status["last_attempt_batch_id"] != batch["id"]:
            raise ValueError("Complete refresh_status points to a different latest attempt batch")
    elif state == "failed":
        if status.get("attempt_ok") is not False:
            raise ValueError("Failed refresh_status requires attempt_ok=false")
        _text(status.get("last_attempt_batch_id"), "refresh_status.last_attempt_batch_id")
        failed = _timestamp(status.get("failed_at"), "refresh_status.failed_at")
        _text(status.get("error"), "refresh_status.error")
        if attempt_started < completed or failed < attempt_started:
            raise ValueError("Failed attempt timestamps must follow the retained successful batch")
    else:
        raise ValueError("refresh_status.status must be complete or failed")

    return {"ok": True, "batch_id": batch["id"], "date": batch["date"], "status": state,
            "refresh_batch": batch, "retained_after_failed_attempt": state == "failed",
            "last_attempt_at": status["last_attempt_at"],
            "last_attempt_batch_id": status.get("last_attempt_batch_id", batch["id"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        result = validate_release(args.root)
    except ValueError as exc:
        print(f"Release validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
