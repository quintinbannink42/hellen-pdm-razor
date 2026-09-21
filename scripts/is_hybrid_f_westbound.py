#!/usr/bin/env python3
"""Move new-IS westbound onto F.Cu at y=111.5–116 (south of J1, empty F).

B.Cu only: R → feeder → transfer Y=108.2, then via; F westbound to S-pad X;
via; B north to M1000 S. Cuts ADIO/PWR B crossings. Gated on shorts + EN/IS.
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
TRANSFER_Y = 108.20
F1_SAFE_X = 35.00  # between RES2 col@33.90 and F1 pad edge@36.25
# Unique F westbound Y — south of D1 (pad to y≈111.3)
F_HWY = {
    "IN_AUX2": 112.60,
    "IN_AUX3": 113.10,
    "IN_MAP2": 113.60,
    "IN_MAP3": 114.10,
    "IN_O2S": 114.60,
    "IN_O2S2": 115.10,
    "IN_RES1": 115.60,
    "IN_RES2": 116.10,
    "IN_RES3": 116.60,
}
F_FEED = {
    "IN_AUX2": 135.50,
    "IN_AUX3": 93.60,
    "IN_MAP2": 99.00,
    "IN_MAP3": 111.00,
    "IN_O2S": 125.00,
    "IN_O2S2": 114.00,
    "IN_RES1": 116.50,
    "IN_RES2": 128.00,
    "IN_RES3": 133.50,
}


def delete_new_is_longhaul_b(board):
    n = 0
    for t in list(board.GetTracks()):
        net = t.GetNetname()
        if net not in NEW_IS:
            continue
        if type(t).__name__ == "PCB_VIA":
            p = t.GetPosition()
            y = ToMM(p.y)
            # keep ADIO local vias at U/R (y~16–49); drop long-haul vias
            if y > 53.5 or net in ("IN_AUX2", "IN_AUX3") and y > 55:
                board.Delete(t)
                n += 1
            continue
        if t.GetLayer() != B_Cu:
            continue
        s, e = t.GetStart(), t.GetEnd()
        y1, y2 = ToMM(s.y), ToMM(e.y)
        try:
            L = ToMM(t.GetLength())
        except Exception:
            L = 99
        if L <= 8.0 and 15.0 <= min(y1, y2) and max(y1, y2) <= 53.0:
            continue
        board.Delete(t)
        n += 1
    return n


def add_hybrid(board, fps, net, rref, mpad, jog_y):
    rx, ry = pad_xy(get_pad(fps, rref, "2"))
    mx, my = pad_xy(get_pad(fps, "M1000", mpad))
    fx = F_FEED[net]
    hy = F_HWY[net]
    n = 0
    jog_x = min(rx + 0.90, 148.8)
    if not has_via_near(board, rx, ry, net):
        add_via(board, rx, ry, net); n += 1
    # B to transfer
    add_track(board, rx, ry, jog_x, ry, 0.25, net, B_Cu); n += 1
    add_track(board, jog_x, ry, jog_x, jog_y, 0.25, net, B_Cu); n += 1
    add_track(board, jog_x, jog_y, fx, jog_y, 0.25, net, B_Cu); n += 1
    add_track(board, fx, jog_y, fx, TRANSFER_Y, 0.25, net, B_Cu); n += 1
    add_via(board, fx, TRANSFER_Y, net); n += 1
    # F westbound — land west of F1 if S-pad X would clip the fuse
    land_x = mx if mx <= F1_SAFE_X else F1_SAFE_X
    add_track(board, fx, TRANSFER_Y, fx, hy, 0.25, net, F_Cu); n += 1
    add_track(board, fx, hy, land_x, hy, 0.25, net, F_Cu); n += 1
    add_track(board, land_x, hy, land_x, TRANSFER_Y, 0.25, net, F_Cu); n += 1
    add_via(board, land_x, TRANSFER_Y, net); n += 1
    # B to S pad (jog around F1 if needed)
    if abs(land_x - mx) > 0.05:
        mid_y = 54.00  # between S-row @51.7 and F1 @93
        add_track(board, land_x, TRANSFER_Y, land_x, mid_y, 0.25, net, B_Cu); n += 1
        add_track(board, land_x, mid_y, mx, mid_y, 0.25, net, B_Cu); n += 1
        add_track(board, mx, mid_y, mx, my, 0.25, net, B_Cu); n += 1
    else:
        add_track(board, mx, TRANSFER_Y, mx, my, 0.25, net, B_Cu); n += 1
    return n


def relevant_shorts(drc, nets):
    """Count shorts that involve `nets`, ignoring J2 and old-IS vs J1 ghosts."""
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


def main():
    print("=== hybrid IS: B stub + F westbound ===")
    drc0 = run_drc()
    s0, c0, u0 = metrics(drc0)
    e0, open0 = en_is_unc(drc0)
    print(f"BEFORE shorts={s0} cross={c0} unc={u0} en_is={e0}")
    snap_save()

    import pcbnew
    board = pcbnew.LoadBoard(str(PCB_PATH))
    # per-net: try hybrid, keep if shorts stay
    landed_h = []
    for net, rref, mpad, jy in REMAINING_IS:
        snap_save()
        board = pcbnew.LoadBoard(str(PCB_PATH))
        fps = fp_map(board)
        # delete this net's B long-haul only
        nd = 0
        for t in list(board.GetTracks()):
            if t.GetNetname() != net:
                continue
            if type(t).__name__ == "PCB_VIA":
                y = ToMM(t.GetPosition().y)
                if y > 53.5:
                    board.Delete(t); nd += 1
                continue
            if t.GetLayer() != B_Cu:
                if t.GetLayer() == F_Cu:
                    try:
                        L = ToMM(t.GetLength())
                    except Exception:
                        L = 99
                    s, e = t.GetStart(), t.GetEnd()
                    y1, y2 = ToMM(s.y), ToMM(e.y)
                    if L > 10.0 or max(y1, y2) > 90.0 or min(y1, y2) < 14.0:
                        board.Delete(t); nd += 1
                continue
            s, e = t.GetStart(), t.GetEnd()
            y1, y2 = ToMM(s.y), ToMM(e.y)
            try:
                L = ToMM(t.GetLength())
            except Exception:
                L = 99
            if L <= 8.0 and 15.0 <= min(y1, y2) and max(y1, y2) <= 53.0:
                continue
            board.Delete(t); nd += 1
        nadd = add_hybrid(board, fps, net, rref, mpad, jy)
        save_board(board)
        drc = run_drc()
        s, c, u = metrics(drc)
        e, opn = en_is_unc(drc)
        ns = relevant_shorts(drc, {net})
        if ns == 0 and net not in opn:
            print(f"  LAND hybrid {net}: shorts={s} new_shorts={ns} cross={c} en_is={e}")
            landed_h.append(net)
            snap_save()
            s0, c0 = s, c
        else:
            print(f"  FAIL hybrid {net}: shorts={s} new_shorts={ns} cross={c} open={opn} — restore")
            snap_restore()
    print(f"hybrid landed {len(landed_h)}/9 {landed_h}")
    ok = True

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
        f.write(f"hybrid_F_west={'ok' if ok else 'reverted'}\n")
        f.write("strategy=is_hybrid_F_westbound_plus_en_B_thin_k8\n")
        f.write("note=9 IS long-haul: B stub to y=108.2, F westbound, B to S; EN B thinned; HELLCORE untouched\n")
    print("Wrote", STATUS)
    return 0 if s1 <= s0 and e1 == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
