#!/usr/bin/env python3
"""Widen the IN_RES2 channel at C107 so a via can reach the B.Cu stub.

IN_O2S2 (y=54.00) and OUT_PWM2 (y=54.80) leave a 0.60 mm copper gap.
A 0.50 mm via needs 0.90 mm. This jogs both tracks south of C107.1,
drops the via on the pad, and ties it to the existing B.Cu stub at
y=53.20. Kept only when the unconnected count drops and the locked
checks still hold.

Does not move footprints, bridge F1, pour SENSOR_GND, or touch PWR_OUT.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout_109x98 as L
import open_corridors as OC
from open_neck import add_poly, add_via_item, checks, find_seg, mask_count, vbat_islands


def replace_seg(board, net, layer, old, pts, width):
    wall = find_seg(board, net, layer, *old)
    if wall is None:
        print(f"missing {net} {old}", flush=True)
        return None
    got = L.ToMM(wall.GetWidth())
    board.Delete(wall)
    router = OC.Router(OC.World(board))
    poly = add_poly(board, router, pts, net, layer, width if width else got)
    if poly is None:
        L.add_track(board, *old, got, net, layer)
        print(f"{net} notch refused", flush=True)
        return None
    return poly


def main():
    board = pcbnew.LoadBoard(str(L.PCB))
    mask0 = mask_count(board)
    L.ZONE_FILLER(board).Fill(board.Zones())
    before = checks(board)
    islands = vbat_islands(board)
    print("before", before, "islands", islands, flush=True)

    added = []
    # OUT_PWM2 moves south just enough to clear OUT_IO8 at y=55.60.
    pwm = replace_seg(
        board,
        "OUT_PWM2",
        "B",
        (92.0, 54.8, 48.4, 54.8),
        [(48.4, 54.8), (87.6, 54.8), (87.6, 55.15), (90.8, 55.15), (90.8, 54.8), (92.0, 54.8)],
        0.20,
    )
    if not pwm:
        raise SystemExit("OUT_PWM2 jog failed")
    added.extend(pwm)

    o2 = replace_seg(
        board,
        "IN_O2S2",
        "B",
        (81.6, 54.0, 92.8, 54.0),
        [(81.6, 54.0), (88.3, 54.0), (88.3, 54.68), (90.2, 54.68), (90.2, 54.0), (92.8, 54.0)],
        0.20,
    )
    if not o2:
        raise SystemExit("IN_O2S2 jog failed")
    added.extend(o2)

    router = OC.Router(OC.World(board))
    via = add_via_item(board, router, 89.22, 54.05, "IN_RES2")
    hop = None
    if via is not None:
        hop = add_poly(board, router, [(89.22, 54.05), (89.22, 53.20)], "IN_RES2", "B", 0.15)
    if via is None or hop is None:
        print("via/hop refused", "via" if via else "no via", flush=True)
        raise SystemExit(1)
    added.append(via)
    added.extend(hop)

    L.ZONE_FILLER(board).Fill(board.Zones())
    now = checks(board)
    islands_now = vbat_islands(board)
    print("after", now, "islands", islands_now, flush=True)
    ok = (
        now["keep"] == 0
        and now["fuse"] is False
        and now["sensor"] == 0
        and now["mask"] == mask0
        and now["unconnected"] < before["unconnected"]
        and islands_now <= islands
    )
    if not ok:
        raise SystemExit("rejected")

    tmp = Path("/tmp/pdmrazora_res2.kicad_pcb")
    board.Save(str(tmp))
    text = tmp.read_text()
    if "(version 20240108)" not in text[:240]:
        L.downgrade_to_k8(tmp)
        text = tmp.read_text()
    if "(version 20240108)" not in text[:240] or '(generator_version "8.0")' not in text[:240]:
        raise SystemExit(text[:180])
    L.PCB.write_text(text)
    print("saved", now["unconnected"], flush=True)


if __name__ == "__main__":
    main()
