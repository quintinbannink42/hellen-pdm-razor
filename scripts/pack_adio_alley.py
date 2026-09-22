#!/usr/bin/env python3
"""Open an IS alley by spreading ADIO columns 0.35 mm per gap.

Column 0 stays. Columns 1..3 move east 0.35 / 0.70 / 1.05 mm, and copper that
already sits inside that column (both ends, or a vertical fanout jogged at the
top of the package) moves with it. The IN_AUX1 spine at x=72 and the IN_AUX2/4
spines at x=80 / 80.8 / 81.6 are shifted on their own so the new pads do not
land on them.

Does not move J1, M1000, J2, or J3. Does not bridge F1. Does not add a
SENSOR_GND pour. Does not replay the long-haul routers.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pcbnew
from pcbnew import PCB_TRACK, ToMM

sys.path.insert(0, str(Path(__file__).resolve().parent))
import close_carrier_rats as cr  # noqa: E402

# Local copper only. The x=72 and x=80 spines are outside these bands.
LOCAL = (
    (55.80, 64.20, 0.35),
    (64.20, 72.35, 0.70),
    (72.35, 79.75, 1.05),
)
Y_LO = 67.05
Y_HI = 91.80
# Alternating jog heights just above the C30/R30 pads and below the driver pads.
JOG_Y = (66.52, 66.98)

COLUMNS = {
    0.00: ["U11", "U15", "R201", "R205", "R101", "R105", "C101", "C105"],
    0.35: ["U12", "U16", "R202", "R206", "R102", "R106", "C102", "C106"],
    0.70: ["U13", "U17", "R203", "R207", "R103", "R107", "C103", "C107"],
    1.05: ["U14", "U18", "R204", "R208", "R104", "R108", "C104", "C108"],
}

# East-spine endpoints that must clear U14's new pad edge (x = 80.555).
SPINE_NETS = {"IN_AUX2", "IN_AUX4"}
SPINE_DX = (
    (80.00, 1.00),
    (80.80, 1.00),
    (81.60, 1.00),
)


def mm_of(p) -> tuple[float, float]:
    return ToMM(p.x), ToMM(p.y)


def local_dx(x: float, y: float) -> float:
    if y < Y_LO or y > Y_HI:
        return 0.0
    for a, b, dx in LOCAL:
        if a <= x < b:
            return dx
    return 0.0


def set_ends(track, x1, y1, x2, y2) -> None:
    track.SetStart(cr.mm(x1, y1))
    track.SetEnd(cr.mm(x2, y2))


def add_seg(board, x1, y1, x2, y2, width, net, layer) -> None:
    if abs(x1 - x2) < 0.001 and abs(y1 - y2) < 0.001:
        return
    tr = PCB_TRACK(board)
    tr.SetStart(cr.mm(x1, y1))
    tr.SetEnd(cr.mm(x2, y2))
    tr.SetWidth(cr.mm(width))
    tr.SetLayer(layer)
    tr.SetNet(net)
    board.Add(tr)


def spine_dx(net: str, x: float, y: float) -> float:
    if net not in SPINE_NETS or y < 63.50:
        return 0.0
    for origin, dx in SPINE_DX:
        if abs(x - origin) < 0.06:
            return dx
    return 0.0


def shift_east_spines(board) -> int:
    n = 0
    for t in list(board.GetTracks()):
        if cr.is_via(t):
            continue
        net = t.GetNetname() or ""
        x1, y1 = mm_of(t.GetStart())
        x2, y2 = mm_of(t.GetEnd())
        d1 = spine_dx(net, x1, y1)
        d2 = spine_dx(net, x2, y2)
        if abs(d1) < 1e-9 and abs(d2) < 1e-9:
            continue
        set_ends(t, x1 + d1, y1, x2 + d2, y2)
        n += 1
    return n


def extend_in_aux1(board) -> None:
    """The x=72 bus stays put except the end that meets the jogged spine."""
    for t in list(board.GetTracks()):
        if cr.is_via(t) or (t.GetNetname() or "") != "IN_AUX1":
            continue
        x1, y1 = mm_of(t.GetStart())
        x2, y2 = mm_of(t.GetEnd())
        if abs(y1 - 72.0) < 0.06 and abs(x1 - 72.0) < 0.06 and abs(x2 - 72.0) > 0.5:
            set_ends(t, 72.70, y1, x2, y2)
            print("  extend IN_AUX1 bus to x=72.70")
        elif abs(y2 - 72.0) < 0.06 and abs(x2 - 72.0) < 0.06 and abs(x1 - 72.0) > 0.5:
            set_ends(t, x1, y1, 72.70, y2)
            print("  extend IN_AUX1 bus to x=72.70")


def move_local_copper(board) -> tuple[int, int]:
    moved = 0
    splits = []
    for t in list(board.GetTracks()):
        if cr.is_via(t):
            x, y = mm_of(t.GetPosition())
            dx = local_dx(x, y)
            if abs(dx) > 1e-9:
                t.SetPosition(cr.mm(x + dx, y))
                moved += 1
            continue
        x1, y1 = mm_of(t.GetStart())
        x2, y2 = mm_of(t.GetEnd())
        d1 = local_dx(x1, y1)
        d2 = local_dx(x2, y2)
        if abs(d1) < 1e-9 and abs(d2) < 1e-9:
            continue
        vertical = abs(x1 - x2) < 0.20
        one_sided = (abs(d1) < 1e-9) ^ (abs(d2) < 1e-9)
        if vertical and one_sided:
            splits.append(t)
            continue
        # Ends in different columns stay horizontal: each end follows its own
        # column, so the segment lengthens instead of rotating onto a neighbor.
        set_ends(t, x1 + d1, y1, x2 + d2, y2)
        moved += 1
    splits.sort(key=lambda t: mm_of(t.GetStart())[0])
    for i, t in enumerate(splits):
        x1, y1 = mm_of(t.GetStart())
        x2, y2 = mm_of(t.GetEnd())
        if local_dx(x1, y1) > 0:
            x, y_in, y_out, dx = x1, y1, y2, local_dx(x1, y1)
        else:
            x, y_in, y_out, dx = x2, y2, y1, local_dx(x2, y2)
        jog_y = JOG_Y[i % 2]
        # Keep the jog on the outside of the package, between the two ends.
        if not (min(y_in, y_out) + 0.05 < jog_y < max(y_in, y_out) - 0.05):
            jog_y = (min(y_in, y_out) + Y_LO) / 2
        width = ToMM(t.GetWidth())
        net = t.GetNet()
        layer = t.GetLayer()
        set_ends(t, x, y_out, x, jog_y)
        add_seg(board, x, jog_y, x + dx, jog_y, width, net, layer)
        add_seg(board, x + dx, jog_y, x + dx, y_in, width, net, layer)
        moved += 1
    return moved, len(splits)


def move_footprints(board) -> list[tuple[str, float, float, float, float]]:
    moves = []
    for dx, refs in COLUMNS.items():
        delta = cr.mm(dx, 0.0)
        for ref in refs:
            fp = board.FindFootprintByReference(ref)
            x0, y0 = mm_of(fp.GetPosition())
            if abs(dx) > 1e-9:
                fp.Move(delta)
            x1, y1 = mm_of(fp.GetPosition())
            moves.append((ref, x0, y0, x1, y1))
    return moves


def apply(board) -> list[tuple[str, float, float, float, float]]:
    n, nsplit = move_local_copper(board)
    print(f"local copper {n}, fanout splits {nsplit}")
    print(f"east spines shifted: {shift_east_spines(board)}")
    extend_in_aux1(board)
    return move_footprints(board)


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else cr.PCB
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src
    if src.resolve() != dst.resolve():
        shutil.copy(src, dst)
    board = pcbnew.LoadBoard(str(dst))
    moves = apply(board)
    for ref, x0, y0, x1, y1 in moves:
        if abs(x1 - x0) > 1e-6:
            print(f"  {ref:6} ({x0:.3f},{y0:.3f}) -> ({x1:.3f},{y1:.3f})")
    if cr.fuse_bridged(board):
        raise SystemExit("fuse bridged during pack")
    if cr.sensor_pours(board):
        raise SystemExit("SENSOR_GND pour appeared")
    cr.fill_zones(board)
    board.Save(str(dst))
    cr.downgrade_to_k8(dst)
    print(f"wrote {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
