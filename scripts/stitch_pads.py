#!/usr/bin/env python3
"""Stitch GND pads that are one jog away from copper already on the net.

R10.1 sits in a 0.60 mm B.Cu slot between IN_O2S and IN_RES2, so the pour
never reaches it. C10.2 is already on that pour. C105.2 and C106.2 sit
under IN_O2S2 the same way C107 did; the B.Cu GND run at y=52.40 is the
ratsnest target. A jog is kept only when the unconnected count drops and
the locked checks still hold.

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


def wipe(board, items):
    for it in items:
        if it is not None:
            board.Delete(it)


def take(board, net, layer, seg):
    wall = find_seg(board, net, layer, *seg)
    if wall is None:
        print(f"missing {net} {seg}", flush=True)
        return None, None
    width = L.ToMM(wall.GetWidth())
    board.Delete(wall)
    return wall, width


def main():
    board = pcbnew.LoadBoard(str(L.PCB))
    mask0 = mask_count(board)
    L.ZONE_FILLER(board).Fill(board.Zones())
    before = checks(board)
    islands0 = vbat_islands(board)
    print("before", before, "islands", islands0, flush=True)
    base_un = before["unconnected"]

    def accept(label):
        L.ZONE_FILLER(board).Fill(board.Zones())
        now = checks(board)
        islands = vbat_islands(board)
        ok = (
            now["unconnected"] < base_un
            and now["keep"] == 0
            and now["fuse"] is False
            and now["sensor"] == 0
            and now["mask"] == mask0
            and islands <= islands0
        )
        print(label, now, "islands", islands, "ok", ok, flush=True)
        return ok, now["unconnected"]

    # --- R10: open the slot, via on the pad, B.Cu tie to the C10 via ---
    removed = []
    for seg in (
        (60.8, 76.0, 56.8, 76.0),
        (56.8, 76.0, 56.8, 74.4),
        (64.8, 76.8, 55.2, 76.8),
    ):
        wall, width = take(board, "IN_O2S" if seg[1] < 76.5 else "IN_RES2", "B", seg)
        if wall is None:
            raise SystemExit(f"R10 wall missing {seg}")
        removed.append((seg, width, "IN_O2S" if seg[1] < 76.5 else "IN_RES2"))

    router = OC.Router(OC.World(board))
    added = []
    polys = [
        ("IN_O2S", [(56.8, 74.4), (56.8, 75.90), (58.35, 75.90), (58.35, 76.0), (60.8, 76.0)], 0.20),
        ("IN_RES2", [(55.2, 76.8), (56.45, 76.8), (56.45, 77.10), (58.45, 77.10), (58.45, 76.8), (64.8, 76.8)], 0.20),
    ]
    failed = False
    for net, pts, width in polys:
        poly = add_poly(board, router, pts, net, "B", width)
        if not poly:
            print(f"R10 {net} jog refused", flush=True)
            failed = True
            break
        added.extend(poly)
    via = hop = None
    if not failed:
        via = add_via_item(board, router, 57.375, 76.48, "GND")
        if via is None:
            print("R10 via refused", flush=True)
            failed = True
        else:
            added.append(via)
            hop = add_poly(
                board, router,
                [(57.375, 76.48), (57.375, 76.40), (63.175, 76.40)],
                "GND", "B", 0.15,
            )
            if not hop:
                print("R10 tie refused", flush=True)
                failed = True
            else:
                added.extend(hop)
    if failed:
        wipe(board, added)
        for seg, width, net in removed:
            L.add_track(board, *seg, width, net, "B")
        print("R10 rolled back", flush=True)
    else:
        ok, base_un = accept("R10")
        if not ok:
            wipe(board, added)
            for seg, width, net in removed:
                L.add_track(board, *seg, width, net, "B")
            L.ZONE_FILLER(board).Fill(board.Zones())
            base_un = checks(board)["unconnected"]
            print("R10 rejected, restored", base_un, flush=True)

    # --- C105 / C106: widen the IN_O2S2 slot the way C107 was widened ---
    removed = []
    specs = [
        ("OUT_PWM2", (48.4, 54.8, 87.6, 54.8)),
        ("OUT_PWM2", (87.6, 54.8, 87.6, 55.15)),
        ("OUT_PWM2", (87.6, 55.15, 90.8, 55.15)),
        ("IN_O2S2", (81.6, 54.0, 88.3, 54.0)),
        ("IN_O2S2", (88.3, 54.0, 88.3, 54.68)),
        ("IN_O2S2", (88.3, 54.68, 90.2, 54.68)),
    ]
    for net, seg in specs:
        wall, width = take(board, net, "B", seg)
        if wall is None:
            raise SystemExit(f"cap wall missing {net} {seg}")
        removed.append((seg, width, net))
    router = OC.Router(OC.World(board))
    added = []
    failed = False
    cap_polys = [
        ("OUT_PWM2", [(48.4, 54.8), (81.40, 54.8), (81.40, 55.15), (90.8, 55.15)], 0.20),
        ("IN_O2S2", [(81.6, 54.0), (82.15, 54.0), (82.15, 54.68), (90.2, 54.68)], 0.20),
    ]
    for net, pts, width in cap_polys:
        poly = add_poly(board, router, pts, net, "B", width)
        if not poly:
            print(f"cap {net} jog refused", flush=True)
            failed = True
            break
        added.extend(poly)
    if not failed:
        for x in (82.775, 86.775):
            via = add_via_item(board, router, x, 54.05, "GND")
            if via is None:
                print(f"cap via {x} refused", flush=True)
                failed = True
                break
            added.append(via)
            hop = add_poly(board, router, [(x, 54.05), (x, 52.40)], "GND", "B", 0.15)
            if not hop:
                print(f"cap tie {x} refused", flush=True)
                failed = True
                break
            added.extend(hop)
    if failed:
        wipe(board, added)
        for seg, width, net in removed:
            L.add_track(board, *seg, width, net, "B")
        print("caps rolled back", flush=True)
    else:
        ok, base_un = accept("C105/C106")
        if not ok:
            wipe(board, added)
            for seg, width, net in removed:
                L.add_track(board, *seg, width, net, "B")
            L.ZONE_FILLER(board).Fill(board.Zones())
            base_un = checks(board)["unconnected"]
            print("caps rejected, restored", base_un, flush=True)

    final = checks(board)
    print("final", final, "islands", vbat_islands(board), flush=True)
    if final["unconnected"] >= before["unconnected"]:
        raise SystemExit("nothing kept")
    if final["mask"] != mask0 or final["keep"] or final["fuse"] or final["sensor"]:
        raise SystemExit("locked check failed")

    tmp = Path("/tmp/pdmrazora_stitch.kicad_pcb")
    board.Save(str(tmp))
    text = tmp.read_text()
    if "(version 20240108)" not in text[:240]:
        L.downgrade_to_k8(tmp)
        text = tmp.read_text()
    if "(version 20240108)" not in text[:240] or '(generator_version "8.0")' not in text[:240]:
        raise SystemExit(text[:180])
    L.PCB.write_text(text)
    print("saved", final["unconnected"], flush=True)


if __name__ == "__main__":
    main()
