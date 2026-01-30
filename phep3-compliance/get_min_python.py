#!/usr/bin/env python3
"""Extract minimum PHEP 3 supported Python version from schedule.json."""
import json
import sys
from datetime import datetime, timezone


def main():
    if len(sys.argv) < 2:
        print("3.12")
        return

    schedule_file = sys.argv[1]
    try:
        with open(schedule_file) as f:
            data = json.load(f)

        now = datetime.now(timezone.utc)
        supported = []
        for version, info in data.get("python", {}).items():
            drop_date = datetime.fromisoformat(
                info["drop_date"].replace("Z", "+00:00")
            )
            if drop_date > now:
                supported.append(version)

        if supported:
            # Sort and get minimum
            supported.sort(key=lambda v: [int(x) for x in v.split(".")])
            print(supported[0])
        else:
            print("3.12")  # Fallback
    except Exception:
        print("3.12")


if __name__ == "__main__":
    main()
