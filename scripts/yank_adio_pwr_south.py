#!/usr/bin/env python3
"""Cut crossings: Y-shift ADIO U-turns north of IS; drop orphan PWR south stubs.

Only edits existing ADIO B endpoints that sit on the old U-turn Y (114–118).
Does not invent new risers. PWR_OUT B with y>110 is orphaned (never meets J1 vias).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from route_is_longhaul_thin_en import (  # noqa: E402
    PCB_PATH, STATUS, SNAP, B_Cu, ZONE_FILLER, ToMM, FromMM, VECTOR2I,
    save_board, snap_save, snap_restore, run_drc, metrics, en_is_unc,
    count_tracks,
)

# old U-turn Y -> new Y (left 1-4 and right 5-8 share Ys; X ranges disjoint)
ADIO_SHIFT = {
    "ADIO1": (114.00, 105.40),
    "ADIO2": (114.60, 105.90),
    "ADIO3": (115.20, 106.40),
    "ADIO4": (115.80, 106.90),
    "ADIO5": (116.40, 105.40),
    "ADIO6": (117.00, 105.90),
    "ADIO7": (117.60, 106.40),
    "ADIO8": (118.20, 106.90),
}
PWR = {"PWR_OUT1", "PWR_OUT2", "PWR_OUT3", "PWR_OUT4"}


def set_xy(t, which, x, y):
    pt = VECTOR2I(FromMM(x), FromMM(y))
    if which == "start":
        t.SetStart(pt)
    else:
        t.SetEnd(pt)


def main():
    print("=== ADIO U-turn Y-shift + PWR orphan drop ===")
    drc0 = run_drc()
    s0, c0, u0 = metrics(drc0)
    e0, open0 = en_is_unc(drc0)
    print(f"BEFORE shorts={s0} cross={c0} unc={u0} en_is={e0}")
    snap_save()

    import pcbnew
    board = pcbnew.LoadBoard(str(PCB_PATH))

    nshift = 0
    ndel = 0
    for t in list(board.GetTracks()):
        net = t.GetNetname()
        if net in PWR:
            if type(t).__name__ == "PCB_VIA":
                if ToMM(t.GetPosition().y) > 110.0:
                    board.Delete(t); ndel += 1
                continue
            if t.GetLayer() != B_Cu:
                continue
            s, e = t.GetStart(), t.GetEnd()
            if max(ToMM(s.y), ToMM(e.y)) > 110.0:
                board.Delete(t); ndel += 1
            continue
        if net not in ADIO_SHIFT or type(t).__name__ == "PCB_VIA":
            continue
        if t.GetLayer() != B_Cu:
            continue
        old_y, new_y = ADIO_SHIFT[net]
        s, e = t.GetStart(), t.GetEnd()
        x1, y1, x2, y2 = ToMM(s.x), ToMM(s.y), ToMM(e.x), ToMM(e.y)
        ch = False
        if abs(y1 - old_y) < 0.20:
            set_xy(t, "start", x1, new_y); ch = True
        if abs(y2 - old_y) < 0.20:
            set_xy(t, "end", x2, new_y); ch = True
        if ch:
            nshift += 1

    print(f"shifted {nshift} ADIO tracks; deleted {ndel} PWR south items")
    ZONE_FILLER(board).Fill(board.Zones())
    at, av = count_tracks(board)
    save_board(board)
    drc1 = run_drc()
    s1, c1, u1 = metrics(drc1)
    e1, open1 = en_is_unc(drc1)
    print(f"AFTER shorts={s1} cross={c1} unc={u1} en_is={e1} open={open1} tracks={at} vias={av}")
    if s1 > 1 or e1 != 0:
        print("RESTORE — shorts or EN/IS open")
        snap_restore()
        return 1
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
        f.write("strategy=is_southring_adio_Yshift_pwr_orphan_en_B_thin_k8\n")
        f.write("note=9 IS B south-ring; ADIO U-turns Y-shifted to 105.4–106.9; orphan PWR y>110 deleted; EN B thinned; HELLCORE untouched\n")
    print("Wrote", STATUS)
    print(f"crossings {c0} -> {c1} (baseline 87)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
