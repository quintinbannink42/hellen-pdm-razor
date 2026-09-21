#!/usr/bin/env python3
"""Phase 3: flip remaining IS long-haul B→F (avoid ADIO/PWR B crossings)
and shift PWM3/4 approach X west of bot-EN cols.

Runs on the already-gated board (9 IS + EN v2). Does not reopen EN/IS.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from route_is_longhaul_thin_en import (  # noqa: E402
    PCB_PATH, STATUS, SNAP, F_Cu, B_Cu, ZONE_FILLER,
    REMAINING_IS, EN_NETS, IS_NETS,
    fp_map, get_pad, pad_xy, add_track, add_via, has_via_near,
    save_board, snap_save, snap_restore, run_drc, metrics, en_is_unc,
    count_tracks, clear_nets, route_en_v2, ToMM,
)

# Last successful B long-haul (feeder, hwy, jog_y) — reuse on F
F_ROUTES = {
    "IN_AUX2": (135.50, 118.80, 64.40),
    "IN_AUX3": (93.60, 119.30, 86.40),
    "IN_MAP2": (99.00, 119.80, 24.70),
    "IN_MAP3": (111.00, 121.50, 25.70),
    "IN_O2S": (125.00, 114.90, 27.20),
    "IN_O2S2": (114.00, 123.50, 50.60),
    "IN_RES1": (116.50, 113.20, 51.20),
    "IN_RES2": (128.00, 125.50, 51.80),
    "IN_RES3": (133.50, 112.00, 52.40),
}
HP_IS = {"IN_AUX2", "IN_AUX3"}


def delete_b_longhaul(board, nets):
    n = 0
    for t in list(board.GetTracks()):
        net = t.GetNetname()
        if net not in nets:
            continue
        if type(t).__name__ == "PCB_VIA":
            if net in HP_IS:
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
        # keep short local U–R under-package B (y 16–23 / 42–49, L~7)
        if L <= 8.0 and 15.0 <= min(y1, y2) and max(y1, y2) <= 53.0:
            continue
        board.Delete(t)
        n += 1
    return n


def add_f_longhaul(board, fps, net, rref, mpad, feeder_x, hwy_y, jog_y):
    rx, ry = pad_xy(get_pad(fps, rref, "2"))
    mx, my = pad_xy(get_pad(fps, "M1000", mpad))
    n = 0
    jog_x = min(rx + 0.90, 148.8)
    add_track(board, rx, ry, jog_x, ry, 0.25, net, F_Cu); n += 1
    add_track(board, jog_x, ry, jog_x, jog_y, 0.25, net, F_Cu); n += 1
    add_track(board, jog_x, jog_y, feeder_x, jog_y, 0.25, net, F_Cu); n += 1
    add_track(board, feeder_x, jog_y, feeder_x, hwy_y, 0.25, net, F_Cu); n += 1
    add_track(board, feeder_x, hwy_y, mx, hwy_y, 0.25, net, F_Cu); n += 1
    add_track(board, mx, hwy_y, mx, my, 0.25, net, F_Cu); n += 1
    return n


def main():
    print("=== phase3: IS long-haul B→F + HP ax shift ===")
    drc0 = run_drc()
    s0, c0, u0 = metrics(drc0)
    e0, open0 = en_is_unc(drc0)
    print(f"BEFORE shorts={s0} cross={c0} unc={u0} en_is={e0} open={open0}")
    base_shorts = s0
    snap_save()

    # --- flip IS ---
    board = __import__("pcbnew").LoadBoard(str(PCB_PATH))
    fps = fp_map(board)
    ndel = delete_b_longhaul(board, set(F_ROUTES))
    print(f"Deleted {ndel} B long-haul items")
    nadd = 0
    for net, rref, mpad, _jy in REMAINING_IS:
        fx, hy, jy = F_ROUTES[net]
        nadd += add_f_longhaul(board, fps, net, rref, mpad, fx, hy, jy)
    print(f"Added {nadd} F long-haul segments")
    save_board(board)
    drc = run_drc()
    s, c, u = metrics(drc)
    e, opn = en_is_unc(drc)
    print(f"  GATE is_F: shorts={s} cross={c} unc={u} en_is={e} open={opn}")
    if s > base_shorts or e > 0:
        print("FAIL is_F — restore")
        snap_restore()
        is_f_ok = False
    else:
        is_f_ok = True
        snap_save()
        base_shorts = s

    # --- HP ax shift: PWM3/4 to 60.40/60.95 (west of bot EN cols) ---
    import route_is_longhaul_thin_en as R
    R.HP_APPROACH_X = [50.70, 51.25, 60.40, 60.95]
    snap_save()
    board = __import__("pcbnew").LoadBoard(str(PCB_PATH))
    fps = fp_map(board)
    deleted = clear_nets(board, {"OUT_PWM1", "OUT_PWM2", "OUT_PWM3", "OUT_PWM4"})
    nseg = R.route_en_v2(board, fps, ["hp"])
    save_board(board)
    drc = run_drc()
    s, c, u = metrics(drc)
    e, opn = en_is_unc(drc)
    print(f"  GATE hp_ax: del={deleted} segs={nseg} shorts={s} cross={c} unc={u} en_is={e} open={opn}")
    if s > base_shorts or (set(opn) & {"OUT_PWM1", "OUT_PWM2", "OUT_PWM3", "OUT_PWM4"}):
        print("FAIL hp_ax — restore")
        snap_restore()
        hp_ok = False
    else:
        hp_ok = True
        snap_save()

    board = __import__("pcbnew").LoadBoard(str(PCB_PATH))
    print("Filling zones...")
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
        f.write(f"before_shorts={prev.get('before_shorts', s0)}\n")
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
        f.write(f"is_F_flip={'ok' if is_f_ok else 'reverted'}\n")
        f.write(f"hp_ax_shift={'ok' if hp_ok else 'reverted'}\n")
        f.write("strategy=is_F_southring_plus_en_B_thin_k8\n")
        f.write("note=9 IS long-haul on F.Cu south-ring (B local kept); EN B thinned; HELLCORE untouched; J2 short may remain\n")
    print("Wrote", STATUS, f"is_F={is_f_ok} hp={hp_ok}")
    return 0 if s1 <= 1 and e1 == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
