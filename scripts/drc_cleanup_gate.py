#!/usr/bin/env python3
"""Gated DRC cleanup orchestrator for pdmrazora leftovers after a8d03e9.

Typical flow used to produce the cleanup commit:
  1. scripts/surgical_drc_fix.py  — delete shorting/crossing copper by DRC UUID;
     add SENSOR_5V R201–R208 taps + GND stitches; K8 downgrade.
  2. scripts/restore_connectivity.py — rebuild PWR_OUT / ADIO / CAN / EN-IS families
     with exclusive lanes (use carefully; re-check DRC after each family).
  3. Short-only UUID delete passes until only known J2 VBAT↔GND remains.
  4. ZONE_FILLER + downgrade to KiCad 8 (20240108 / 8.0).

Do NOT touch hellen-one (HELLCORE). Prefer deleting conflict segments over dense remesh.
  5. scripts/route_en_is_lanes.py — EN/IS exclusive-lane gated restore (after 5f0f389).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    print(__doc__)
    print("Running surgical_drc_fix.py ...")
    rc = subprocess.call([sys.executable, str(ROOT / "scripts" / "surgical_drc_fix.py")])
    return rc


if __name__ == "__main__":
    sys.exit(main())
