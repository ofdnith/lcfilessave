"""Is the device plugged in? Heavy work (OCR) only runs while charging."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

_cache: tuple[float, bool, dict] | None = None


def battery() -> dict:
    """{'charging': bool, 'percentage': int|None, 'temperature': float|None}"""
    global _cache
    if _cache and time.monotonic() - _cache[0] < 60:
        return _cache[2]
    info = _read()
    _cache = (time.monotonic(), info["charging"], info)
    return info


def is_charging() -> bool:
    return battery()["charging"]


def _read() -> dict:
    # Termux (needs the Termux:API app + `pkg install termux-api`)
    if shutil.which("termux-battery-status"):
        try:
            res = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=10)
            data = json.loads(res.stdout)
            return {"charging": data.get("plugged", "UNPLUGGED") != "UNPLUGGED",
                    "percentage": data.get("percentage"), "temperature": data.get("temperature")}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    # macOS
    if shutil.which("pmset"):
        try:
            out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5).stdout
            return {"charging": "AC Power" in out, "percentage": None, "temperature": None}
        except (OSError, subprocess.TimeoutExpired):
            pass
    # Linux laptops
    supplies = Path("/sys/class/power_supply")
    if supplies.is_dir():
        for online in supplies.glob("*/online"):
            try:
                if online.read_text().strip() == "1":
                    return {"charging": True, "percentage": None, "temperature": None}
            except OSError:
                continue
        if any(supplies.glob("BAT*")):
            return {"charging": False, "percentage": None, "temperature": None}
    # Desktop or unknown: treat as plugged in.
    return {"charging": True, "percentage": None, "temperature": None}
