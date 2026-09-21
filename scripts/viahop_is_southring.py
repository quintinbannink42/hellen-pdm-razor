#!/usr/bin/env python3
"""Punch F.Cu via-hops in new-IS B south-ring where it crosses other B tracks.

Only hops at y>=110 (south of J1, F is empty) or x<=40 (west module approach).
Gated: shorts must stay at J2-only; EN/IS must stay closed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from route_is_longhaul_thin_en import (  # noqa: E402
    PCB_PATH, STATUS, SNAP, F_Cu, B_Cu, ZONE_FILLER,
    fp_map, add_track, add_via, save_board, snap_save, snap_restore,
    run_drc, metrics, en_is_unc, count_tracks, ToMM,
)

NEW_IS = {
    "IN_AUX2", "IN_AUX3", "IN_MAP2", "IN_MAP3", "IN_O2S",
    "IN_O2S2", "IN_RES1", "IN_RES2", "IN_RES3",
}
HOP = 1.20  # mm each side of foreign track / cluster
TARGET_OTHER = None  # filled in main: PWR/ADIO/SENSOR


def merge_clusters(vals, gap=2.6):
    vals = sorted(vals)
    if not vals:
        return []
    out = [[vals[0], vals[0]]]
    for v in vals[1:]:
        if v - out[-1][1] <= gap:
            out[-1][1] = v
        else:
            out.append([v, v])
    return out


def segs(board, layer=None, nets=None, exclude=None):
    out = []
    for t in board.GetTracks():
        if type(t).__name__ == "PCB_VIA":
            continue
        if layer is not None and t.GetLayer() != layer:
            continue
        net = t.GetNetname() or ""
        if nets is not None and net not in nets:
            continue
        if exclude is not None and net in exclude:
            continue
        s, e = t.GetStart(), t.GetEnd()
        out.append((t, net, ToMM(s.x), ToMM(s.y), ToMM(e.x), ToMM(e.y), ToMM(t.GetWidth())))
    return out


def is_h(x1, y1, x2, y2):
    return abs(y1 - y2) < 0.05 and abs(x1 - x2) > 0.05


def is_v(x1, y1, x2, y2):
    return abs(x1 - x2) < 0.05 and abs(y1 - y2) > 0.05


def hop_horizontal(board, tr, net, x1, y, x2, foreign_xs):
    """Replace one B horizontal with B stubs + F hops at each foreign cluster."""
    xa, xb = (x1, x2) if x1 < x2 else (x2, x1)
    clusters = merge_clusters([x for x in foreign_xs if xa + HOP + 0.4 < x < xb - HOP - 0.4])
    if not clusters:
        return 0
    board.Delete(tr)
    n = 0
    cursor = xa
    for lo_x, hi_x in clusters:
        left, right = lo_x - HOP, hi_x + HOP
        if left <= 136.5 <= right:
            # skip SENSOR_5V F riser band
            continue
        if left - cursor > 0.05:
            add_track(board, cursor, y, left, y, 0.25, net, B_Cu); n += 1
        add_via(board, left, y, net); n += 1
        add_track(board, left, y, right, y, 0.25, net, F_Cu); n += 1
        add_via(board, right, y, net); n += 1
        cursor = right
    if xb - cursor > 0.05:
        add_track(board, cursor, y, xb, y, 0.25, net, B_Cu); n += 1
    return n


def hop_vertical(board, tr, net, x, y1, y2, foreign_ys):
    ya, yb = (y1, y2) if y1 < y2 else (y2, y1)
    clusters = merge_clusters([y for y in foreign_ys if ya + HOP + 0.4 < y < yb - HOP - 0.4])
    if not clusters:
        return 0
    board.Delete(tr)
    n = 0
    cursor = ya
    for lo_y, hi_y in clusters:
        lo, hi = lo_y - HOP, hi_y + HOP
        if lo - cursor > 0.05:
            add_track(board, x, cursor, x, lo, 0.25, net, B_Cu); n += 1
        add_via(board, x, lo, net); n += 1
        add_track(board, x, lo, x, hi, 0.25, net, F_Cu); n += 1
        add_via(board, x, hi, net); n += 1
        cursor = hi
    if yb - cursor > 0.05:
        add_track(board, x, cursor, x, yb, 0.25, net, B_Cu); n += 1
    return n


def main():
    print("=== via-hop new-IS B south-ring crossings ===")
    drc0 = run_drc()
    s0, c0, u0 = metrics(drc0)
    e0, open0 = en_is_unc(drc0)
    print(f"BEFORE shorts={s0} cross={c0} unc={u0} en_is={e0}")
    snap_save()

    import pcbnew
    board = pcbnew.LoadBoard(str(PCB_PATH))
    others = segs(board, layer=B_Cu, exclude=NEW_IS)
    ours = segs(board, layer=B_Cu, nets=NEW_IS)
    def other_ok(onet):
        return onet.startswith("PWR_OUT") or onet.startswith("ADIO") or onet == "SENSOR_5V"

    hops = 0
    for tr, net, x1, y1, x2, y2, _w in ours:
        if is_h(x1, y1, x2, y2) and min(y1, y2) >= 110.0:
            fxs = []
            y = (y1 + y2) / 2
            xa, xb = min(x1, x2), max(x1, x2)
            for _ot, onet, ox1, oy1, ox2, oy2, ow in others:
                if not other_ok(onet) or not is_v(ox1, oy1, ox2, oy2):
                    continue
                ox = (ox1 + ox2) / 2
                oya, oyb = min(oy1, oy2), max(oy1, oy2)
                if xa < ox < xb and oya - 0.2 <= y <= oyb + 0.2:
                    fxs.append(ox)
            hops += hop_horizontal(board, tr, net, x1, y, x2, fxs)
        elif is_v(x1, y1, x2, y2):
            fys = []
            x = (x1 + x2) / 2
            ya, yb = min(y1, y2), max(y1, y2)
            for _ot, onet, ox1, oy1, ox2, oy2, ow in others:
                if not other_ok(onet) or not is_h(ox1, oy1, ox2, oy2):
                    continue
                oy = (oy1 + oy2) / 2
                if oy < 110.0:
                    continue
                oxa, oxb = min(ox1, ox2), max(ox1, ox2)
                if ya < oy < yb and oxa - 0.2 <= x <= oxb + 0.2:
                    fys.append(oy)
            hops += hop_vertical(board, tr, net, x, y1, y2, fys)

    print(f"Inserted hop segments/vias={hops}")
    save_board(board)
    drc = run_drc()
    s, c, u = metrics(drc)
    e, opn = en_is_unc(drc)
    print(f"  GATE hop: shorts={s} cross={c} unc={u} en_is={e} open={opn}")
    if s > s0 or e > 0:
        print("FAIL hop — restore")
        snap_restore()
        ok = False
    else:
        ok = True
        snap_save()

    board = pcbnew.LoadBoard(str(PCB_PATH))
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
        f.write(f"via_hop={'ok' if ok else 'reverted'}\n")
        f.write("strategy=is_B_southring_viahop_plus_en_B_thin_k8\n")
        f.write("note=9 IS long-haul B south-ring with F via-hops at y>=110; EN B thinned; HELLCORE untouched\n")
    print("Wrote", STATUS)
    return 0 if s1 <= s0 and e1 == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
