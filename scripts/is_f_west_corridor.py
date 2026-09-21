#!/usr/bin/env python3
"""Cut IS south-ring crossings: F.Cu westbound south of J1 + B.Cu west corridor.

B.Cu stub from R to y=113.2 (north of ADIO/PWR south U-turns), via to F.
F westbound at y=121.2–125.2 (south of VBAT F riser ending y=120, west of
SENSOR_5V F @x>=138) to a unique west-X in the empty B corridor (x=17.3–24.2,
west of MAP1 @25.50, skipping GND vias @16.5/20.0).
Via to B; north to y=52.40; east to S-pad X; north onto PTH S pad.

Does not reopen EN/IS; shorts stay J2-only. Optionally migrates AUX1/AUX4/MAP1.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from route_is_longhaul_thin_en import (  # noqa: E402
    PCB_PATH, STATUS, SNAP, F_Cu, B_Cu, ZONE_FILLER,
    REMAINING_IS, fp_map, get_pad, pad_xy, add_track, add_via, has_via_near,
    save_board, snap_save, snap_restore, run_drc, metrics, en_is_unc,
    count_tracks, ToMM,
)

NEW_IS = {t[0] for t in REMAINING_IS}
OLD_IS = [
    ("IN_AUX1", "R10", "S13", 64.50),
    ("IN_AUX4", "R40", "S10", 86.50),
    ("IN_MAP1", "R101", "S21", 25.20),
]
TRANSFER_Y = 113.20
S_APPROACH_Y = 52.40
# South of VBAT F end-cap (~120.6) and north of CANH B @126.5 / SENSOR @128.
F_HWY_POOL = [
    121.20, 121.70, 122.20, 122.70, 123.20,
    123.70, 124.20, 124.70, 125.20, 125.70,
    121.45, 122.95,
]
# Empty B corridor west of MAP1@25.50; skip GND vias 16.50 and 20.00.
WEST_X_POOL = [
    17.30, 17.75, 18.20, 18.65, 19.10,
    21.00, 21.45, 21.90, 22.35, 22.80,
    23.25, 23.70, 24.15,
]
# East of EN bot@64 / HP hwy@120; skip PWR_OUT4@130 and ADIO5–8@140–144.5.
FEED_POOL = [
    125.00, 125.55, 126.10, 126.65,
    131.20, 131.75, 132.30, 132.85, 133.40,
    134.00, 134.60, 135.20, 135.80, 136.40,
    137.00, 137.55, 139.00, 139.45,
]


def delete_longhaul(board, net):
    """Drop long-haul tracks/vias; keep local U–R–C (short, y<=53)."""
    n = 0
    for t in list(board.GetTracks()):
        if t.GetNetname() != net:
            continue
        if type(t).__name__ == "PCB_VIA":
            y = ToMM(t.GetPosition().y)
            x = ToMM(t.GetPosition().x)
            # keep via-in-pad at R / under ADIO (y<=53.5, x typically 60–130)
            if y > 53.5 or x < 40.0:
                board.Delete(t)
                n += 1
            continue
        s, e = t.GetStart(), t.GetEnd()
        y1, y2 = ToMM(s.y), ToMM(e.y)
        x1, x2 = ToMM(s.x), ToMM(e.x)
        try:
            L = ToMM(t.GetLength())
        except Exception:
            L = 99
        if L <= 8.0 and 14.0 <= min(y1, y2) and max(y1, y2) <= 53.0 and min(x1, x2) >= 55.0:
            continue
        board.Delete(t)
        n += 1
    return n


def add_corridor(board, fps, net, rref, mpad, jog_y, feeder_x, hwy_y, west_x):
    rx, ry = pad_xy(get_pad(fps, rref, "2"))
    mx, my = pad_xy(get_pad(fps, "M1000", mpad))
    n = 0
    if not has_via_near(board, rx, ry, net):
        add_via(board, rx, ry, net)
        n += 1
    jog_x = min(rx + 0.90, 148.8)
    jog_y = min(max(jog_y, ry + 1.05), TRANSFER_Y - 0.6)
    # B stub to transfer (north of ADIO south-ring)
    add_track(board, rx, ry, jog_x, ry, 0.25, net, B_Cu); n += 1
    add_track(board, jog_x, ry, jog_x, jog_y, 0.25, net, B_Cu); n += 1
    add_track(board, jog_x, jog_y, feeder_x, jog_y, 0.25, net, B_Cu); n += 1
    add_track(board, feeder_x, jog_y, feeder_x, TRANSFER_Y, 0.25, net, B_Cu); n += 1
    add_via(board, feeder_x, TRANSFER_Y, net); n += 1
    # F south + westbound (empty south margin)
    add_track(board, feeder_x, TRANSFER_Y, feeder_x, hwy_y, 0.25, net, F_Cu); n += 1
    add_track(board, feeder_x, hwy_y, west_x, hwy_y, 0.25, net, F_Cu); n += 1
    add_via(board, west_x, hwy_y, net); n += 1
    # B west corridor to S-row, then east to pad X
    add_track(board, west_x, hwy_y, west_x, S_APPROACH_Y, 0.25, net, B_Cu); n += 1
    add_track(board, west_x, S_APPROACH_Y, mx, S_APPROACH_Y, 0.25, net, B_Cu); n += 1
    add_track(board, mx, S_APPROACH_Y, mx, my, 0.25, net, B_Cu); n += 1
    return n


def relevant_shorts(drc, nets):
    n = 0
    for v in drc["violations"]:
        if v["type"] != "shorting_items":
            continue
        blob = json.dumps(v)
        if "J2" in blob and "VBAT" in blob and "GND" in blob:
            continue
        if "J1" in blob and not any(x in blob for x in nets):
            continue
        if any(x in blob for x in nets):
            n += 1
    return n


# Baked unique (feed, hwy, west) — one DRC per net unless it fails.
BAKED = {
    "IN_AUX2": (135.80, 121.20, 17.30),
    "IN_AUX3": (126.10, 121.70, 17.75),
    "IN_MAP2": (125.00, 122.20, 18.20),
    "IN_MAP3": (131.20, 122.70, 18.65),
    "IN_O2S":  (125.55, 123.20, 19.10),
    "IN_O2S2": (134.00, 123.70, 21.00),
    "IN_RES1": (134.60, 124.20, 21.45),
    "IN_RES2": (132.30, 124.70, 21.90),
    "IN_RES3": (133.40, 125.20, 22.35),
    "IN_AUX1": (136.40, 125.70, 22.80),
    "IN_AUX4": (137.00, 121.45, 23.25),
    "IN_MAP1": (137.55, 122.95, 23.70),
}


def candidates_for(net, rref, used_feed, used_hwy, used_west):
    cands = []
    if net in BAKED:
        fx, hy, wx = BAKED[net]
        if fx not in used_feed and hy not in used_hwy and wx not in used_west:
            cands.append((fx, hy, wx))
    feeds = [x for x in FEED_POOL if x not in used_feed]
    hwys = [y for y in F_HWY_POOL if y not in used_hwy]
    wests = [x for x in WEST_X_POOL if x not in used_west]
    for fx in feeds[:5]:
        for hy in hwys[:3]:
            for wx in wests[:3]:
                trip = (fx, hy, wx)
                if trip not in cands:
                    cands.append(trip)
    return cands[:12]


def try_nets(label, pairs, used_feed, used_hwy, used_west, base_shorts):
    landed = []
    failed = []
    for net, rref, mpad, jy in pairs:
        cands = candidates_for(net, rref, used_feed, used_hwy, used_west)
        if not cands:
            print(f"  NO CANDIDATES {net}")
            failed.append(net)
            continue
        ok = False
        last = None
        for fx, hy, wx in cands:
            snap_save()
            board = __import__("pcbnew").LoadBoard(str(PCB_PATH))
            fps = fp_map(board)
            nd = delete_longhaul(board, net)
            nadd = add_corridor(board, fps, net, rref, mpad, jy, fx, hy, wx)
            save_board(board)
            drc = run_drc()
            s, c, u = metrics(drc)
            e, opn = en_is_unc(drc)
            ns = relevant_shorts(drc, {net})
            last = (s, ns, c, e, fx, hy, wx, nd, nadd)
            if ns == 0 and s <= base_shorts and net not in opn:
                used_feed.add(fx)
                used_hwy.add(hy)
                used_west.add(wx)
                landed.append((net, fx, hy, wx, s, c, e))
                print(f"  LAND {label} {net}: feed={fx:.2f} hwy={hy:.2f} west={wx:.2f} "
                      f"shorts={s} new={ns} cross={c} en_is={e} del={nd} add={nadd}")
                ok = True
                break
            print(f"  retry {net} feed={fx:.2f} hwy={hy:.2f} west={wx:.2f} "
                  f"shorts={s} new={ns} cross={c} open={opn}")
            snap_restore()
        if not ok:
            failed.append(net)
            print(f"  FAIL {label} {net}: last={last}")
            snap_restore()
    return landed, failed


def main():
    print("=== IS F westbound + B west corridor (crossing cut) ===")
    drc0 = run_drc()
    s0, c0, u0 = metrics(drc0)
    e0, open0 = en_is_unc(drc0)
    print(f"BEFORE shorts={s0} cross={c0} unc={u0} en_is={e0} open={open0}")
    base_shorts = 1
    snap_save()

    used_feed, used_hwy, used_west = set(), set(), set()
    # Keep existing AUX4 feeder x=138.25 out of the pool (we may migrate it later)
    landed_n, fail_n = try_nets("new", REMAINING_IS, used_feed, used_hwy, used_west, base_shorts)
    print(f"new landed {len(landed_n)}/9 failed={fail_n}")

    landed_o, fail_o = try_nets("old", OLD_IS, used_feed, used_hwy, used_west, base_shorts)
    print(f"old landed {len(landed_o)}/3 failed={fail_o}")

    board = __import__("pcbnew").LoadBoard(str(PCB_PATH))
    ZONE_FILLER(board).Fill(board.Zones())
    at, av = count_tracks(board)
    save_board(board)
    drc1 = run_drc()
    s1, c1, u1 = metrics(drc1)
    e1, open1 = en_is_unc(drc1)
    print(f"AFTER shorts={s1} cross={c1} unc={u1} en_is={e1} open={open1} tracks={at} vias={av}")

    prev = {}
    if STATUS.exists():
        for line in STATUS.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                prev[k] = v
    with STATUS.open("w") as f:
        f.write(f"before_shorts={prev.get('before_shorts', 1)}\n")
        f.write(f"before_crossings={prev.get('before_crossings', 87)}\n")
        f.write(f"before_unc={prev.get('before_unc', 122)}\n")
        f.write(f"before_en_is_unc={prev.get('before_en_is_unc', 9)}\n")
        f.write(f"before_tracks={prev.get('before_tracks', 286)}\n")
        f.write(f"before_vias={prev.get('before_vias', 104)}\n")
        f.write(f"after_shorts={s1}\n")
        f.write(f"after_crossings={c1}\n")
        f.write(f"after_unc={u1}\n")
        f.write(f"after_en_is_unc={e1}\n")
        f.write(f"after_tracks={at}\n")
        f.write(f"after_vias={av}\n")
        f.write("is_landed=IN_AUX2,IN_AUX3,IN_MAP2,IN_MAP3,IN_O2S,IN_O2S2,IN_RES1,IN_RES2,IN_RES3\n")
        f.write(f"corridor_new={','.join(n for n, *_ in landed_n)}\n")
        f.write(f"corridor_old={','.join(n for n, *_ in landed_o)}\n")
        f.write(f"corridor_fail={','.join(fail_n + fail_o)}\n")
        f.write("strategy=is_F_westbound_B_west_corridor_plus_en_B_thin_k8\n")
        f.write("note=9 IS long-haul: B stub to y=113.2, F westbound y=121+, B west corridor x=17-24 to S; old IS migrated if gated; EN B thinned; HELLCORE untouched\n")
    print("Wrote", STATUS)
    ok = s1 <= base_shorts and e1 == 0
    if c1 >= 87:
        print(f"crossings still not under baseline: 87 -> {c1}")
    else:
        print(f"crossings reduced: 87 -> {c1}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
