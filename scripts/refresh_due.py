"""Skip fallback runs only after a verified collection for today's Beijing date."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.validate_data import validate


BEIJING = ZoneInfo("Asia/Shanghai")


def refresh_due(snapshot, now=None, force=False):
    if force:
        return True
    now = now or datetime.now(BEIJING)
    today = now.astimezone(BEIJING).date()
    try:
        validate(snapshot)
        collected = datetime.fromisoformat(snapshot["updated_at"])
        checked = datetime.fromisoformat(snapshot["quality"]["link_validation"]["checked_at"])
        if collected.tzinfo is None or checked.tzinfo is None:
            return True
        links = snapshot["quality"]["link_validation"]
        count = len(snapshot["items"])
        return not (
            snapshot["date"] == today.isoformat()
            and collected.astimezone(BEIJING).date() == today
            and checked.astimezone(BEIJING).date() == today
            and collected <= now and checked <= now
            and links.get("verified") == links.get("total") == count
            and all(row.get("link_status") == "verified" for row in snapshot["items"])
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snapshot = None
    print("due=" + str(refresh_due(snapshot, force=args.force)).lower())


if __name__ == "__main__":
    main()
