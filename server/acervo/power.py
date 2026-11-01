"""Is the device plugged in, and is it too hot to keep working?

Heavy work (OCR) only runs while charging. On the phone, which lives on the
charger, that is almost always — so background jobs also pause when the
battery gets hot (ThermalGate), to spare the battery and the SoC.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)

_cache: tuple[float, bool, dict] | None = None

# Resume only after cooling this many degrees below the limit, so the worker
# does not flip on and off around the threshold.
COOL_DOWN_MARGIN = 3.0


class ThermalGate:
    """Pauses background work while the battery is at or above `max_temp_c`.

    Battery temperature is what Termux:API reports and what matters for battery
    swelling. Unknown temperature (Mac, no Termux:API) never pauses anything.
    """

    def __init__(self, max_temp_c: float, read=None) -> None:
        self.max_temp_c = max_temp_c
        self._read = read or (lambda: battery().get("temperature"))
        self.paused = False
        self.temperature: float | None = None

    def too_hot(self) -> bool:
        try:
            temp = self._read()
        except Exception:  # a broken sensor must not stop the worker forever
            temp = None
        self.temperature = float(temp) if isinstance(temp, (int, float)) else None
        if self.temperature is None:
            self.paused = False
        elif self.paused:
            if self.temperature <= self.max_temp_c - COOL_DOWN_MARGIN:
                self.paused = False
                log.info("Temperatura em %.1f °C: tarefas retomadas", self.temperature)
        elif self.temperature >= self.max_temp_c:
            self.paused = True
            log.info("Temperatura em %.1f °C (limite %s °C): tarefas pausadas até esfriar",
                     self.temperature, self.max_temp_c)
        return self.paused

    def status(self) -> dict:
        return {"temperature": self.temperature, "max_temp_c": self.max_temp_c, "paused": self.paused}


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
