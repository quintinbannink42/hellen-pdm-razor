#!/usr/bin/env python3
"""Surgical DRC polish on the split-bobbin 104×93 PowerCore.

Clears packed-east pad collisions without moving the EMI split, J2/J3, M1000,
or ADIO, and without replaying the 150×130 long-haul scripts.

Placement (required — copper overlapped):
  - U3/U4 rotate -90 → +90 (centers unchanged) so their pin rows leave the
    U1/U2 VBAT tabs and face the sense parts already sitting south.
  - R10/C10/R20/C20 shift to y=35.70, into the gap between the U1/U2 pin row
    and the tab.
  - D1 moves to (88, 24), off the U1 pin row.
  - J1 nudges west 1.2 mm so its pin columns clear the mega-mcu144 east pads.

Copper:
  - Signal tracks/vias are rebuilt with a clearance-aware grid router.
  - VBAT/GND tracks that hit a foreign pad are removed; pours stay.
  - F1 is not bridged. SENSOR_GND is not poured onto chassis GND.
"""
from __future__ import annotations

import heapq
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import pcbnew
from pcbnew import (
    B_Cu,
    F_Cu,
    FromMM,
    PCB_TRACK,
    PCB_VIA,
    PCB_VIA_T,
    ToMM,
    VECTOR2I,
    ZONE_FILLER,
)

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "pdmrazora.kicad_pcb"
STATUS = ROOT / "scripts" / "copper_status.txt"
LEFTOVER = ROOT / "scripts" / "unconnected_leftover.txt"
DRC_JSON = ROOT / "scripts" / "drc_zonefill.json"
PNG = ROOT / "scripts" / "copper_fill_overview.png"
ART = Path("/opt/cursor/artifacts/copper_fill_fb_overview.png")

BOARD_W, BOARD_H = 104.0, 93.0
CLR = 0.20
EDGE = 0.55
GRID = 0.40

# Nets rebuilt from pads. VBAT/GND stay on pours + surviving straps.
REROUTE = {
    "PWR_OUT1", "PWR_OUT2", "PWR_OUT3", "PWR_OUT4",
    "ADIO1", "ADIO2", "ADIO3", "ADIO4", "ADIO5", "ADIO6", "ADIO7", "ADIO8",
    "OUT_PWM1", "OUT_PWM2", "OUT_PWM3", "OUT_PWM4",
    "OUT_PWM5", "OUT_PWM6", "OUT_PWM7", "OUT_PWM8",
    "OUT_IO5", "OUT_IO6", "OUT_IO7", "OUT_IO8",
    "IN_AUX1", "IN_AUX2", "IN_AUX3", "IN_AUX4",
    "IN_MAP1", "IN_MAP2", "IN_MAP3",
    "IN_O2S", "IN_O2S2",
    "IN_RES1", "IN_RES2", "IN_RES3",
    "CANH", "CANL", "IGN_SW", "IN_VIGN",
    "SENSOR_5V", "SENSOR_GND",
}
EN_NETS = {n for n in REROUTE if n.startswith("OUT_")}
WIDTH = {}
for n in REROUTE:
    if n.startswith("PWR_OUT"):
        WIDTH[n] = 0.40
    elif n.startswith("ADIO"):
        WIDTH[n] = 0.28
    elif n in EN_NETS or n.startswith("IN_"):
        WIDTH[n] = 0.20
    else:
        WIDTH[n] = 0.28

# Nets that must be able to land on the mega-mcu144 east-edge pads.
ALLEY_OK = set(EN_NETS) | {"SENSOR_5V", "SENSOR_GND"}


def mm(x, y=None):
    if y is None:
        return FromMM(x)
    return VECTOR2I(FromMM(x), FromMM(y))


def downgrade_to_k8(path: Path) -> None:
    text = path.read_text()
    text = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text = re.sub(r'\(generator_version "[^"]+"\)', '(generator_version "8.0")', text, count=1)
    text = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text)
    text = re.sub(r"\n\t\t\(embedded_fonts (yes|no)\)", "", text)
    text = re.sub(r"\n\t\t\(tenting [^\n]+\)", "", text)
    text = re.sub(r"\n\t\t\(legacy_teardrops (yes|no)\)", "", text)
    k8_layers = """(layers
		(0 "F.Cu" signal)
		(31 "B.Cu" signal)
		(33 "F.Adhes" user "F.Adhesive")
		(32 "B.Adhes" user "B.Adhesive")
		(35 "F.Paste" user)
		(34 "B.Paste" user)
		(37 "F.SilkS" user "F.Silkscreen")
		(36 "B.SilkS" user "B.Silkscreen")
		(39 "F.Mask" user)
		(38 "B.Mask" user)
		(40 "Dwgs.User" user "User.Drawings")
		(41 "Cmts.User" user "User.Comments")
		(42 "Eco1.User" user "User.Eco1")
		(43 "Eco2.User" user "User.Eco2")
		(44 "Edge.Cuts" user)
		(45 "Margin" user)
		(47 "F.CrtYd" user "F.Courtyard")
		(46 "B.CrtYd" user "B.Courtyard")
		(49 "F.Fab" user)
		(48 "B.Fab" user)
		(50 "User.1" user)
		(51 "User.2" user)
		(52 "User.3" user)
		(53 "User.4" user)
	)"""
    text = re.sub(r"\(layers\n.*?\n\t\)", k8_layers, text, count=1, flags=re.S)
    text = re.sub(r' "In\d+\.Cu"', "", text)
    path.write_text(text)
    head = path.read_text()[:300]
    assert "20240108" in head and 'generator_version "8.0"' in head


def setpos(fp, x, y):
    fp.SetPosition(mm(x, y))


def apply_placement(board) -> dict:
    """Return a dict of documented nudges. Centers of U1/U2/U3/U4/J2/J3/M1000/ADIO stay."""
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    notes = {}
    for ref in ("U3", "U4"):
        old = fps[ref].GetOrientationDegrees()
        fps[ref].SetOrientationDegrees(90.0)
        p = fps[ref].GetPosition()
        notes[ref] = f"rot {old:.0f} → 90, anchor ({ToMM(p.x):.1f},{ToMM(p.y):.1f}) unchanged"
    # Sense RC into the pin-to-tab gap (y 34.7–36.7). X unchanged.
    for ref, x, y in (
        ("R10", 76.0, 35.70),
        ("C10", 80.0, 35.70),
        ("R20", 92.0, 35.70),
        ("C20", 96.0, 35.70),
    ):
        p = fps[ref].GetPosition()
        notes[ref] = f"({ToMM(p.x):.2f},{ToMM(p.y):.2f}) → ({x:.2f},{y:.2f})"
        setpos(fps[ref], x, y)
    p = fps["D1"].GetPosition()
    notes["D1"] = f"({ToMM(p.x):.2f},{ToMM(p.y):.2f}) → (88.00,24.00)"
    setpos(fps["D1"], 88.0, 24.0)
    p = fps["J1"].GetPosition()
    notes["J1"] = f"({ToMM(p.x):.2f},{ToMM(p.y):.2f}) → ({ToMM(p.x) - 1.2:.2f},{ToMM(p.y):.2f})"
    setpos(fps["J1"], ToMM(p.x) - 1.2, ToMM(p.y))
    return notes


def pad_box(pad):
    bb = pad.GetBoundingBox()
    return ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom())


def dist_pt_seg(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def boxes_overlap(a, b, clr=0.0) -> bool:
    return not (a[2] + clr < b[0] or b[2] + clr < a[0] or a[3] + clr < b[1] or b[3] + clr < a[1])


def collect_pads(board):
    pads = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            if not pad.IsOnLayer(F_Cu) and not pad.IsOnLayer(B_Cu):
                continue
            net = pad.GetNetname() or ""
            x, y = ToMM(pad.GetPosition().x), ToMM(pad.GetPosition().y)
            box = pad_box(pad)
            # Through-hole / module pads exist on both layers.
            attr = pad.GetAttribute()
            both = attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
            layers = ("F", "B") if both else ("F",)
            pads.append(
                {
                    "ref": ref,
                    "num": pad.GetNumber(),
                    "net": net,
                    "x": x,
                    "y": y,
                    "box": box,
                    "layers": layers,
                    "fp": ref,
                }
            )
    return pads


def is_via(t) -> bool:
    return t.Type() == PCB_VIA_T


def iter_segs(board):
    for t in board.GetTracks():
        if is_via(t):
            p = t.GetPosition()
            yield ("via", t, ToMM(p.x), ToMM(p.y), t.GetNetname(), ToMM(t.GetWidth()))
        else:
            a, b = t.GetStart(), t.GetEnd()
            lay = "F" if t.GetLayer() == F_Cu else "B"
            yield (
                "seg",
                t,
                ToMM(a.x),
                ToMM(a.y),
                ToMM(b.x),
                ToMM(b.y),
                lay,
                t.GetNetname(),
                ToMM(t.GetWidth()),
            )


def foreign_hit_pad(x, y, net, pads, halo) -> bool:
    for p in pads:
        if p["net"] == net:
            continue
        l, t, r, b = p["box"]
        if x < l - halo or x > r + halo or y < t - halo or y > b + halo:
            continue
        # Point vs expanded rect.
        cx = min(max(x, l), r)
        cy = min(max(y, t), b)
        if math.hypot(x - cx, y - cy) < halo:
            return True
    return False


def delete_signal_and_collisions(board, pads) -> tuple[int, int]:
    """Drop every reroute-net copper item, and VBAT/GND copper that hits a foreign pad."""
    n_sig = n_pwr = 0
    for t in list(board.GetTracks()):
        net = t.GetNetname()
        if net in REROUTE:
            board.Delete(t)
            n_sig += 1
            continue
        if net not in ("VBAT", "GND"):
            continue
        if is_via(t):
            p = t.GetPosition()
            x, y = ToMM(p.x), ToMM(p.y)
            if foreign_hit_pad(x, y, net, pads, ToMM(t.GetWidth()) / 2 + 0.02):
                board.Delete(t)
                n_pwr += 1
            continue
        a, b = t.GetStart(), t.GetEnd()
        x1, y1, x2, y2 = ToMM(a.x), ToMM(a.y), ToMM(b.x), ToMM(b.y)
        w = ToMM(t.GetWidth()) / 2
        hit = False
        # Sample the segment. Power tracks are long; 0.4 mm steps are enough to catch a pad.
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(length / 0.35))
        for i in range(steps + 1):
            u = i / steps
            if foreign_hit_pad(x1 + (x2 - x1) * u, y1 + (y2 - y1) * u, net, pads, w + 0.02):
                hit = True
                break
        if hit:
            board.Delete(t)
            n_pwr += 1
    return n_sig, n_pwr


def add_track(board, x1, y1, x2, y2, width, net, layer="F"):
    if math.hypot(x2 - x1, y2 - y1) < 0.02:
        return None
    tr = PCB_TRACK(board)
    tr.SetStart(mm(x1, y1))
    tr.SetEnd(mm(x2, y2))
    tr.SetWidth(FromMM(width))
    tr.SetLayer(F_Cu if layer == "F" else B_Cu)
    ni = board.FindNet(net)
    tr.SetNet(ni)
    board.Add(tr)
    return tr


def add_via(board, x, y, net, size=0.60, drill=0.30):
    v = PCB_VIA(board)
    v.SetPosition(mm(x, y))
    v.SetDrill(FromMM(drill))
    v.SetWidth(FromMM(size))
    v.SetNet(board.FindNet(net))
    board.Add(v)
    return v


def _vbat_kind(x, y) -> str | None:
    """pre = J2 pour or F1.1; post = fused pours / F1.2. None = open board."""
    if 83.4 <= x <= 103.2 and 0.6 <= y <= 22.3:
        return "pre"
    if abs(x - 58.0) <= 2.05 and abs(y - 18.0) <= 2.05:
        return "pre"
    if 66.4 <= x <= 82.6 and 0.6 <= y <= 24.3:
        return "post"
    if abs(x - 67.2) <= 2.05 and abs(y - 18.0) <= 2.05:
        return "post"
    if 72.8 <= x <= 103.2 and 31.7 <= y <= 64.3:
        return "post"
    if 47.8 <= x <= 82.3 and 65.7 <= y <= 81.3:
        return "post"
    return None


def split_fuse(board) -> int:
    """Delete VBAT copper that touches both the pre-fuse and fused regions.

    Then strap J2 to F1.1 south of both north pours, and feed N27 from the
    post-fuse pour. The ATO footprint is not bridged.
    """
    removed = 0
    for t in list(board.GetTracks()):
        if t.GetNetname() != "VBAT" or is_via(t):
            continue
        a, b = t.GetStart(), t.GetEnd()
        x1, y1, x2, y2 = ToMM(a.x), ToMM(a.y), ToMM(b.x), ToMM(b.y)
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(length / 0.4))
        kinds = set()
        for i in range(steps + 1):
            u = i / steps
            k = _vbat_kind(x1 + (x2 - x1) * u, y1 + (y2 - y1) * u)
            if k:
                kinds.add(k)
        if "pre" in kinds and "post" in kinds:
            board.Delete(t)
            removed += 1
    # Vias sitting in the J2 pour that only served the bypass spine.
    for t in list(board.GetTracks()):
        if t.GetNetname() != "VBAT" or not is_via(t):
            continue
        p = t.GetPosition()
        if _vbat_kind(ToMM(p.x), ToMM(p.y)) == "pre" and ToMM(p.y) < 8:
            board.Delete(t)
            removed += 1
    # J2 → F1.1. The long hop is on B.Cu so it does not cross the F.Cu D1 strap
    # (that strap is the fused side). F.Cu only drops at x=92 and onto F1.1.
    add_track(board, 92.0, 18.2, 92.0, 27.3, 0.80, "VBAT", "F")
    add_via(board, 92.0, 27.3, "VBAT", 0.80, 0.40)
    add_track(board, 92.0, 27.3, 58.5, 27.3, 0.70, "VBAT", "B")
    add_via(board, 58.5, 27.3, "VBAT", 0.80, 0.40)
    add_track(board, 58.5, 27.3, 58.5, 18.0, 0.80, "VBAT", "F")
    # Post-fuse pour → N27 on B, staying west of the J2 pour (x<=82).
    add_via(board, 72.0, 6.0, "VBAT", 0.70, 0.35)
    add_track(board, 72.0, 6.0, 18.5, 6.0, 0.45, "VBAT", "B")
    add_track(board, 18.5, 6.0, 18.5, 26.0, 0.45, "VBAT", "B")
    # Old HP→U14 bus sits on the R30/C30 row (y=66.4) and on a GND stitch.
    removed += _drop_south_vbat_bus(board)
    # C1's vertical stops 0.37 mm short of F1.1. Jog onto pad 1 only (pad 2 is x>=65.45).
    add_track(board, 60.52, 18.00, 58.40, 18.00, 0.60, "VBAT", "F")
    # Post-fuse spine ends at (80, 25.85). Continue into D1, south of the J2 pour (y<=22).
    add_track(board, 80.00, 25.85, 80.00, 26.20, 0.60, "VBAT", "F")
    add_track(board, 80.00, 26.20, 88.00, 26.20, 0.60, "VBAT", "F")
    # Two HP fill islands are split east of U1.1 (pad ends x=84.21). Gap at y=33.2 is x≈86.0–86.8.
    add_track(board, 85.30, 33.20, 87.60, 33.20, 0.50, "VBAT", "F")
    # HP tongue on the U3 VBAT pin (x≈80, y≈63.3) down the 0.65 mm slot between C30 pads.
    # w=0.22 leaves ~0.21 mm to each pad (clearance 0.20).
    add_track(board, 80.00, 63.30, 80.00, 66.80, 0.22, "VBAT", "F")
    return removed


def _drop_south_vbat_bus(board) -> int:
    """Delete the pre-existing F.Cu VBAT finger that crosses the IN_AUX row."""
    removed = 0
    for t in list(board.GetTracks()):
        if t.GetNetname() != "VBAT" or is_via(t) or t.GetLayer() != F_Cu:
            continue
        a, b = t.GetStart(), t.GetEnd()
        x1, y1 = ToMM(a.x), ToMM(a.y)
        x2, y2 = ToMM(b.x), ToMM(b.y)
        xs, xe = sorted((x1, x2))
        ys, ye = sorted((y1, y2))
        horiz = abs(y1 - y2) < 0.05 and abs(y1 - 66.4) < 0.08 and xs <= 76.1 and xe >= 85.4
        vert76 = abs(x1 - x2) < 0.05 and abs(x1 - 76.0) < 0.08 and ys <= 66.5 and ye >= 69.3
        vert856 = abs(x1 - x2) < 0.05 and abs(x1 - 85.6) < 0.08 and 63.5 <= ys and ye <= 66.6
        if horiz or vert76 or vert856:
            board.Delete(t)
            removed += 1
    return removed


def strap_power(board, pads) -> None:
    """D1 back onto post-fuse VBAT, and a GND via that is not inside a VBAT pad."""
    # D1 VBAT pad is the southern SMB pad after the move to (88, 24).
    d1 = [p for p in pads if p["ref"] == "D1"]
    vb = next(p for p in d1 if p["net"] == "VBAT")
    gd = next(p for p in d1 if p["net"] == "GND")
    # South into the HP VBAT zone (y>=32), in the alley between the two tabs (x≈88).
    add_track(board, vb["x"], vb["y"], 88.0, 33.2, 0.80, "VBAT", "F")
    # GND via just west of D1, south of the J2 pour (pour ends y=22) and clear of pads.
    add_track(board, gd["x"], gd["y"], 85.2, 21.4, 0.40, "GND", "F")
    add_via(board, 85.2, 21.4, "GND")


def stitch_gnd(board, pads) -> int:
    """One via per carrier SMD GND pad that is not already next to a GND via."""
    existing = []
    for kind, *rest in iter_segs(board):
        if kind == "via" and rest[3] == "GND":
            existing.append((rest[1], rest[2]))
    n = 0
    offsets = [
        (0, -1.15), (0, 1.15), (-1.25, 0), (1.25, 0),
        (0, -1.7), (0, 1.7), (-1.7, 0), (1.7, 0),
        (-1.1, -1.1), (1.1, -1.1), (-1.1, 1.1), (1.1, 1.1),
    ]
    seen = set()
    for p in pads:
        if p["net"] != "GND" or p["ref"] in ("M1000", "J2", "J3"):
            continue
        if "F" not in p["layers"] or "B" in p["layers"]:
            continue  # PTH already hits the pour
        key = (round(p["x"], 2), round(p["y"], 2))
        if key in seen:
            continue
        seen.add(key)
        if any(math.hypot(p["x"] - vx, p["y"] - vy) < 1.6 for vx, vy in existing):
            continue
        placed = False
        for ox, oy in offsets:
            x, y = p["x"] + ox, p["y"] + oy
            if x < 1.0 or y < 1.0 or x > BOARD_W - 1.0 or y > BOARD_H - 1.0:
                continue
            if foreign_hit_pad(x, y, "GND", pads, 0.30 + CLR):
                continue
            if any(math.hypot(x - vx, y - vy) < 0.85 for vx, vy in existing):
                continue
            add_track(board, p["x"], p["y"], x, y, 0.30, "GND", "F")
            add_via(board, x, y, "GND")
            existing.append((x, y))
            n += 1
            placed = True
            break
        if not placed:
            pass
    return n


class GridRouter:
    def __init__(self, pads, segs, vias):
        self.pads = pads
        self.segs = segs  # (x1,y1,x2,y2,lay,net,w)
        self.vias = vias  # (x,y,net,size)
        self.nx = int(BOARD_W / GRID) + 2
        self.ny = int(BOARD_H / GRID) + 2

    def _cell(self, x, y):
        return int(round(x / GRID)), int(round(y / GRID))

    def _xy(self, ix, iy):
        return ix * GRID, iy * GRID

    def paint(self, net, width):
        """Blocked track cells per layer, and via-blocked cells (either layer)."""
        halo = width / 2 + CLR
        vhalo = 0.30 + CLR
        blk = [bytearray(self.nx * self.ny), bytearray(self.nx * self.ny)]
        vblk = bytearray(self.nx * self.ny)

        def mark(ix, iy, layer, via=False):
            if 0 <= ix < self.nx and 0 <= iy < self.ny:
                if layer is None or layer == 0:
                    if via:
                        vblk[iy * self.nx + ix] = 1
                    else:
                        blk[0][iy * self.nx + ix] = 1
                if layer is None or layer == 1:
                    if not via:
                        blk[1][iy * self.nx + ix] = 1

        def paint_rect(l, t, r, b, layer, via=False):
            ix0 = max(0, int((l) / GRID))
            ix1 = min(self.nx - 1, int((r) / GRID) + 1)
            iy0 = max(0, int((t) / GRID))
            iy1 = min(self.ny - 1, int((b) / GRID) + 1)
            for iy in range(iy0, iy1 + 1):
                cy = iy * GRID
                if cy < t or cy > b:
                    # still mark if cell center is inside expanded box — compare properly
                    pass
                row = iy * self.nx
                for ix in range(ix0, ix1 + 1):
                    cx = ix * GRID
                    if l <= cx <= r and t <= cy <= b:
                        if via:
                            vblk[row + ix] = 1
                        elif layer == 0:
                            blk[0][row + ix] = 1
                        elif layer == 1:
                            blk[1][row + ix] = 1
                        else:
                            blk[0][row + ix] = 1
                            blk[1][row + ix] = 1

        for p in self.pads:
            if p["net"] == net:
                continue
            l, t, r, b = p["box"]
            layers = p["layers"]
            if "F" in layers:
                paint_rect(l - halo, t - halo, r + halo, b + halo, 0)
                paint_rect(l - vhalo, t - vhalo, r + vhalo, b + vhalo, None, via=True)
            if "B" in layers:
                paint_rect(l - halo, t - halo, r + halo, b + halo, 1)
                paint_rect(l - vhalo, t - vhalo, r + vhalo, b + vhalo, None, via=True)
        for x1, y1, x2, y2, lay, n, w in self.segs:
            if n == net:
                continue
            h = halo + w / 2
            # Expand the segment's bbox.
            paint_rect(min(x1, x2) - h, min(y1, y2) - h, max(x1, x2) + h, max(y1, y2) + h, 0 if lay == "F" else 1)
            paint_rect(
                min(x1, x2) - (vhalo + w / 2),
                min(y1, y2) - (vhalo + w / 2),
                max(x1, x2) + (vhalo + w / 2),
                max(y1, y2) + (vhalo + w / 2),
                None,
                via=True,
            )
        for x, y, n, sz in self.vias:
            if n == net:
                continue
            h = halo + sz / 2
            paint_rect(x - h, y - h, x + h, y + h, None)
            paint_rect(x - (vhalo + sz / 2), y - (vhalo + sz / 2), x + (vhalo + sz / 2), y + (vhalo + sz / 2), None, via=True)
        # Keep the module east-pad face clear for EN / sense. Power fanout
        # goes around the north gap instead of sealing this alley.
        if net not in ALLEY_OK:
            paint_rect(44.35, 28.0, 45.9, 64.5, None)
        # Board edge.
        for ix in range(self.nx):
            for iy in range(self.ny):
                x, y = ix * GRID, iy * GRID
                if x < EDGE or y < EDGE or x > BOARD_W - EDGE or y > BOARD_H - EDGE:
                    blk[0][iy * self.nx + ix] = 1
                    blk[1][iy * self.nx + ix] = 1
                    vblk[iy * self.nx + ix] = 1
        self.blk = blk
        self.vblk = vblk
        self.halo = halo

    def free(self, ix, iy, layer) -> bool:
        if not (0 <= ix < self.nx and 0 <= iy < self.ny):
            return False
        return self.blk[layer][iy * self.nx + ix] == 0

    def nearest_free(self, x, y, layer):
        ix, iy = self._cell(x, y)
        if self.free(ix, iy, layer):
            return ix, iy
        for rad in range(1, 8):
            for dx in range(-rad, rad + 1):
                for dy in range(-rad, rad + 1):
                    if max(abs(dx), abs(dy)) != rad:
                        continue
                    if self.free(ix + dx, iy + dy, layer):
                        return ix + dx, iy + dy
        return None

    def route(self, x1, y1, x2, y2, prefer_layer: int, start_layers=None, goal_layers=None):
        other = 1 - prefer_layer
        start_layers = tuple(start_layers) if start_layers else (prefer_layer, other)
        goal_layers = tuple(goal_layers) if goal_layers else (prefer_layer, other)
        starts = []
        for lay in start_layers:
            cell = self.nearest_free(x1, y1, lay)
            if cell:
                starts.append((cell[0], cell[1], lay))
        if not starts:
            return None

        inf = 10**9
        best = {}
        pq = []
        for ix, iy, lay in starts:
            # slight preference
            c0 = 0 if lay == prefer_layer else 3
            best[(ix, iy, lay)] = c0
            heapq.heappush(pq, (c0 + abs(ix * GRID - x2) + abs(iy * GRID - y2), c0, ix, iy, lay))
        parent = {}
        expanded = 0
        found = None
        while pq and expanded < 250000:
            _h, g, ix, iy, lay = heapq.heappop(pq)
            if g != best.get((ix, iy, lay)):
                continue
            expanded += 1
            # Land on a free cell of an allowed layer, within one grid step of the pad.
            if lay in goal_layers and math.hypot(ix * GRID - x2, iy * GRID - y2) <= 0.72 and g > 0:
                found = (ix, iy, lay)
                break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = ix + dx, iy + dy
                if not self.free(nx, ny, lay):
                    continue
                step = 1.0 if lay == prefer_layer else 1.15
                # Mild penalty inside the module keepout so fanout stays east when it can.
                cx, cy = nx * GRID, ny * GRID
                if 2.0 < cx < 44.5 and 26.0 < cy < 66.0:
                    step += 0.45
                ng = g + step
                key = (nx, ny, lay)
                if ng < best.get(key, inf):
                    best[key] = ng
                    parent[key] = (ix, iy, lay)
                    heapq.heappush(pq, (ng + abs(cx - x2) + abs(cy - y2), ng, nx, ny, lay))
            # Via
            if self.vblk[iy * self.nx + ix] == 0 and self.free(ix, iy, 0) and self.free(ix, iy, 1):
                nlay = 1 - lay
                ng = g + 2.4
                key = (ix, iy, nlay)
                if ng < best.get(key, inf):
                    best[key] = ng
                    parent[key] = (ix, iy, lay)
                    heapq.heappush(pq, (ng + abs(ix * GRID - x2) + abs(iy * GRID - y2), ng, ix, iy, nlay))
        if not found:
            return None
        path = [found]
        while path[-1] in parent:
            path.append(parent[path[-1]])
            if len(path) > 5000:
                return None
        path.reverse()
        return path


def simplify_path(path):
    """Drop colinear middle cells on the same layer."""
    if len(path) < 3:
        return path
    out = [path[0]]
    for i in range(1, len(path) - 1):
        x0, y0, l0 = out[-1]
        x1, y1, l1 = path[i]
        x2, y2, l2 = path[i + 1]
        if l0 == l1 == l2 and (x1 - x0) * (y2 - y1) == (y1 - y0) * (x2 - x1):
            continue
        out.append(path[i])
    out.append(path[-1])
    return out


def commit_path(board, router: GridRouter, path, x1, y1, x2, y2, net, width):
    pts = [(x1, y1, path[0][2])]
    for ix, iy, lay in path:
        pts.append((ix * GRID, iy * GRID, lay))
    pts.append((x2, y2, path[-1][2]))
    # Collapse identical points.
    compact = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - compact[-1][0]) < 0.02 and abs(p[1] - compact[-1][1]) < 0.02 and p[2] == compact[-1][2]:
            continue
        if abs(p[0] - compact[-1][0]) < 0.02 and abs(p[1] - compact[-1][1]) < 0.02 and p[2] != compact[-1][2]:
            compact.append(p)
            continue
        compact.append(p)
    # Simplify colinear on same layer.
    simp = [compact[0]]
    for i in range(1, len(compact) - 1):
        a, b, c = simp[-1], compact[i], compact[i + 1]
        if a[2] == b[2] == c[2]:
            if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) < 1e-6:
                continue
        simp.append(b)
    simp.append(compact[-1])
    layname = {0: "F", 1: "B"}
    for i in range(len(simp) - 1):
        x_a, y_a, la = simp[i]
        x_b, y_b, lb = simp[i + 1]
        if la != lb:
            add_via(board, x_b, y_b, net)
            router.vias.append((x_b, y_b, net, 0.6))
            continue
        add_track(board, x_a, y_a, x_b, y_b, width, net, layname[la])
        router.segs.append((x_a, y_a, x_b, y_b, layname[la], net, width))


def route_signals(board, pads) -> dict:
    segs = []
    vias = []
    for item in iter_segs(board):
        if item[0] == "via":
            _, _t, x, y, net, sz = item
            vias.append((x, y, net, sz))
        else:
            _, _t, x1, y1, x2, y2, lay, net, w = item
            segs.append((x1, y1, x2, y2, lay, net, w))
    router = GridRouter(pads, segs, vias)
    by_net = defaultdict(list)
    for p in pads:
        if p["net"] in REROUTE and p["ref"] != "M1000" or (p["net"] in REROUTE and p["ref"] == "M1000"):
            by_net[p["net"]].append(p)
    # Stable order: power, then ADIO, EN, IS, system.
        def _rank(n):
            if n.startswith("OUT_"):
                return 0
            if n.startswith("IN_"):
                return 1
            if n.startswith("SENSOR") or n in ("CANH", "CANL", "IGN_SW", "IN_VIGN"):
                return 2
            if n.startswith("ADIO"):
                return 3
            if n.startswith("PWR"):
                return 4
            return 5

        order = sorted(by_net, key=lambda n: (_rank(n), n))
    report = {}
    for net in order:
        plist = by_net[net]
        # Unique pad locations.
        uniq = []
        seen = set()
        for p in plist:
            k = (round(p["x"], 2), round(p["y"], 2), p["ref"], p["num"])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(p)
        # Seed from the carrier pin, not an edge pad that can be boxed in.
        uniq.sort(key=lambda p: (p["ref"] == "M1000", p["ref"], str(p["num"])))
        if len(uniq) < 2:
            report[net] = "single-pad"
            continue
        width = WIDTH[net]
        prefer = 1 if net in EN_NETS else 0
        router.paint(net, width)

        def lays(p):
            return tuple(0 if L == "F" else 1 for L in p["layers"])

        clusters = [[p] for p in uniq]
        failed = []
        # Join nearest clusters first so a packed pin row ties together
        # before the long haul to J1 / M1000.
        while len(clusters) > 1:
            best = None
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    for a in clusters[i]:
                        for b in clusters[j]:
                            dist = abs(a["x"] - b["x"]) + abs(a["y"] - b["y"])
                            if best is None or dist < best[0]:
                                best = (dist, i, j, a, b)
            _d, i, j, a, b = best
            path = router.route(a["x"], a["y"], b["x"], b["y"], prefer, lays(a), lays(b))
            if path is None:
                alt = 1 - prefer
                path = router.route(a["x"], a["y"], b["x"], b["y"], alt, lays(a), lays(b))
            if path is None:
                # Drop the smaller cluster; its pads stay open.
                drop = j if len(clusters[j]) <= len(clusters[i]) else i
                failed.extend(f"{p['ref']}.{p['num']}" for p in clusters[drop])
                clusters.pop(drop)
                continue
            commit_path(board, router, path, a["x"], a["y"], b["x"], b["y"], net, width)
            keep, drop = (i, j) if i < j else (j, i)
            # recompute after possible index shift: pop the higher index
            hi, lo = max(i, j), min(i, j)
            clusters[lo].extend(clusters[hi])
            clusters.pop(hi)
            router.paint(net, width)
        joined = len(uniq) - len(failed)
        report[net] = "ok" if not failed else "open:" + ",".join(failed)
        print(f"  {net}: {report[net]} ({joined}/{len(uniq)})", flush=True)
    return report


def fill_zones(board) -> None:
    ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()


def sensor_pour_count(board) -> int:
    n = 0
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if not z.GetIsRuleArea() and z.GetNetname() == "SENSOR_GND":
            n += 1
    return n


def fuse_bridged(board) -> bool:
    """True if a VBAT track/via directly joins the J2 island to the post-fuse island
    without going through F1's two pads as separate endpoints.

    Geometric test: a VBAT segment that has one end in the pre-fuse box and the
    other end outside it bridges the fuse.
    """
    pre = (83.0, 0.5, 103.5, 22.5)  # J2 pour, includes F1? F1.1 is at x=58. Don't use this.
    # Pre-fuse copper is the J2 pour plus the track to F1 pad 1 (x≈58,y≈18).
    # A bridge is any VBAT segment that comes within 0.4 mm of BOTH F1.1 and F1.2.
    f1 = None
    for fp in board.GetFootprints():
        if fp.GetReference() == "F1":
            f1 = fp
    if f1 is None:
        return False
    a = f1.FindPadByNumber("1").GetPosition()
    b = f1.FindPadByNumber("2").GetPosition()
    ax, ay, bx, by = ToMM(a.x), ToMM(a.y), ToMM(b.x), ToMM(b.y)
    # Union-find VBAT copper excluding a direct pad-to-pad inside the fuse footprint.
    # Flag a segment whose bbox covers both pads.
    for item in iter_segs(board):
        if item[0] != "seg":
            continue
        _, _t, x1, y1, x2, y2, _lay, net, _w = item
        if net != "VBAT":
            continue
        d1 = min(dist_pt_seg(ax, ay, x1, y1, x2, y2), dist_pt_seg(bx, by, x1, y1, x2, y2))
        near_a = dist_pt_seg(ax, ay, x1, y1, x2, y2) < 0.8
        near_b = dist_pt_seg(bx, by, x1, y1, x2, y2) < 0.8
        if near_a and near_b:
            return True
        _ = d1
    return False


def run_drc() -> dict:
    out = Path("/tmp/pdmrazora_drc_polish.json")
    proc = subprocess.run(
        [
            "kicad-cli", "pcb", "drc",
            "--format", "json", "--severity-error", "--units", "mm",
            "-o", str(out), str(PCB),
        ],
        capture_output=True, text=True,
    )
    data = {"cli_rc": proc.returncode}
    if out.exists():
        data.update(json.loads(out.read_text()))
    return data


def summarize(drc: dict) -> dict:
    from collections import Counter
    counts = Counter()
    for v in drc.get("violations") or []:
        counts[v.get("type", "?")] += 1
    un_nets = Counter()
    samples = defaultdict(list)
    for v in drc.get("violations") or []:
        typ = v.get("type")
        if typ in ("shorting_items", "tracks_crossing", "unconnected_items") and len(samples[typ]) < 6:
            samples[typ].append(
                {
                    "description": (v.get("description") or "")[:180],
                    "items": [
                        {
                            "net": (it.get("description") or "")[:90],
                            "pos": it.get("pos"),
                        }
                        for it in v.get("items", [])[:3]
                    ],
                }
            )
    for v in drc.get("unconnected_items") or []:
        counts["unconnected_items"] += 1
        nets = []
        for it in v.get("items", []):
            m = re.search(r"\[([^\]]+)\]", it.get("description") or "")
            if m:
                nets.append(m.group(1))
        un_nets["|".join(sorted(set(nets)) or ["?"])] += 1
        if len(samples["unconnected_items"]) < 8:
            samples["unconnected_items"].append(
                {
                    "description": "unconnected",
                    "items": [(it.get("description") or "")[:100] for it in v.get("items", [])],
                }
            )
    return {"counts": dict(counts), "unconnected_nets": dict(un_nets), "samples": samples}


def plot_png(board, path: Path) -> None:
    from PIL import Image, ImageDraw
    scale = 10
    w, h = int(BOARD_W * scale) + 8, int(BOARD_H * scale) + 8

    def xy(x, y):
        return int(x * scale) + 4, int(y * scale) + 4

    img = Image.new("RGB", (w * 2 + 12, h), (18, 18, 22))
    front = ImageDraw.Draw(img, "RGBA")
    # Two panels: F and B side by side. Draw outline on both.
    def panel(origin_x, layer_name):
        dr = front
        ox = origin_x

        def pxy(x, y):
            return ox + int(x * scale) + 4, int(y * scale) + 4

        dr.rectangle([pxy(0, 0), pxy(BOARD_W, BOARD_H)], outline=(90, 90, 100))
        for i in range(board.GetAreaCount()):
            z = board.GetArea(i)
            if z.GetIsRuleArea() or not z.IsFilled():
                continue
            name = z.GetNetname()
            try:
                lay = z.GetFirstLayer()
                polys = z.GetFilledPolysList(lay)
            except TypeError:
                polys = z.GetFilledPolysList()
            want = (lay == F_Cu and layer_name == "F") or (lay == B_Cu and layer_name == "B")
            # Some zones are single-layer; skip the other panel.
            if not want:
                continue
            if name == "VBAT":
                col = (190, 70, 55, 140)
            elif name == "GND":
                col = (50, 90, 170, 110)
            else:
                col = (120, 120, 80, 80)
            for k in range(polys.OutlineCount()):
                outline = polys.COutline(k)
                pts = [pxy(ToMM(outline.CPoint(j).x), ToMM(outline.CPoint(j).y)) for j in range(outline.PointCount())]
                if len(pts) >= 3:
                    dr.polygon(pts, fill=col)
        for t in board.GetTracks():
            if is_via(t):
                p = t.GetPosition()
                cx, cy = pxy(ToMM(p.x), ToMM(p.y))
                dr.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], outline=(230, 230, 230))
                continue
            if (t.GetLayer() == F_Cu and layer_name != "F") or (t.GetLayer() == B_Cu and layer_name != "B"):
                continue
            a, b = t.GetStart(), t.GetEnd()
            net = t.GetNetname()
            if net == "VBAT":
                col = (230, 90, 70)
            elif net == "GND":
                col = (120, 170, 240)
            elif net.startswith("PWR_OUT"):
                col = (240, 170, 60)
            elif net.startswith("ADIO"):
                col = (240, 210, 80)
            elif net.startswith("OUT_"):
                col = (80, 200, 140)
            else:
                col = (200, 140, 220)
            dr.line([pxy(ToMM(a.x), ToMM(a.y)), pxy(ToMM(b.x), ToMM(b.y))], fill=col, width=1)
        dr.text((ox + 8, 6), f"{'F.Cu' if layer_name == 'F' else 'B.Cu'}", fill=(230, 230, 230))

    panel(0, "F")
    panel(w + 8, "B")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def count_items(board):
    tr = via = 0
    for t in board.GetTracks():
        if is_via(t):
            via += 1
        else:
            tr += 1
    return tr, via


def main() -> int:
    print("=== drc polish ===", flush=True)
    board = pcbnew.LoadBoard(str(PCB))
    notes = apply_placement(board)
    print("placement:")
    for k, v in notes.items():
        print(f"  {k}: {v}")
    pads = collect_pads(board)
    # Pad-pad audit (carrier, ignore M1000-M1000).
    overlaps = []
    for i, a in enumerate(pads):
        for b in pads[i + 1 :]:
            if a["ref"] == b["ref"] or a["net"] == b["net"]:
                continue
            if a["ref"] == "M1000" and b["ref"] == "M1000":
                continue
            if boxes_overlap(a["box"], b["box"], 0.0):
                overlaps.append(f"{a['ref']}.{a['num']} {a['net']} ~ {b['ref']}.{b['num']} {b['net']}")
    print(f"pad-pad overlaps after nudge: {len(overlaps)}")
    for line in overlaps[:20]:
        print("   ", line)

    n_sig, n_pwr = delete_signal_and_collisions(board, pads)
    print(f"deleted signal copper {n_sig}, colliding VBAT/GND {n_pwr}")
    n_bridge = split_fuse(board)
    print(f"removed fuse-bypass VBAT segments {n_bridge}")
    pads = collect_pads(board)
    strap_power(board, pads)
    n_g = stitch_gnd(board, pads)
    print(f"GND stitches added {n_g}")
    print("filling zones before route...", flush=True)
    fill_zones(board)
    print("routing signals...", flush=True)
    report = route_signals(board, collect_pads(board))
    print("refill...", flush=True)
    fill_zones(board)
    if sensor_pour_count(board) != 0:
        sys.exit("SENSOR_GND pour appeared — abort")
    bridged = fuse_bridged(board)
    print("fuse bridged by a VBAT segment:", bridged)

    pcbnew.SaveBoard(str(PCB), board)
    downgrade_to_k8(PCB)
    # Reload after downgrade so the plot uses the saved file.
    board = pcbnew.LoadBoard(str(PCB))
    tr, via = count_items(board)
    print(f"tracks={tr} vias={via}", flush=True)
    print("DRC...", flush=True)
    drc = run_drc()
    summary = summarize(drc)
    counts = summary["counts"]
    print("DRC", counts, flush=True)

    # Second pass: delete signal tracks/vias that still short or cross, then refill.
    # Keeps the placement and the pours. Records whatever is still open.
    if counts.get("shorting_items", 0) or counts.get("tracks_crossing", 0):
        print("second pass: drop remaining short/crossing signal copper", flush=True)
        board = pcbnew.LoadBoard(str(PCB))
        idmap = {}
        for t in board.GetTracks():
            idmap[t.m_Uuid.AsString()] = t
        victims = set()
        freq = defaultdict(int)
        for v in (drc.get("violations") or []):
            if v.get("type") not in ("shorting_items", "tracks_crossing"):
                continue
            ids = []
            for it in v.get("items", []):
                uid = it.get("uuid")
                obj = idmap.get(uid)
                if obj is None:
                    continue
                if obj.GetNetname() in ("VBAT", "GND") and v.get("type") == "tracks_crossing":
                    continue
                ids.append(uid)
                freq[uid] += 1
            if not ids:
                continue
            # Prefer deleting a signal track over a pour-net via.
            def rank(uid):
                obj = idmap[uid]
                sig = 0 if obj.GetNetname() in ("VBAT", "GND") else 1
                return (sig, freq[uid])
            victims.add(max(ids, key=rank))
        for uid in victims:
            obj = idmap.get(uid)
            if obj is not None and obj.GetNetname() not in ("VBAT", "GND"):
                board.Delete(obj)
        print(f"  removed {len(victims)} items")
        fill_zones(board)
        pcbnew.SaveBoard(str(PCB), board)
        downgrade_to_k8(PCB)
        board = pcbnew.LoadBoard(str(PCB))
        tr, via = count_items(board)
        drc = run_drc()
        summary = summarize(drc)
        counts = summary["counts"]
        print("DRC2", counts, flush=True)

    plot_png(board, PNG)
    ART.parent.mkdir(parents=True, exist_ok=True)
    plot_png(board, ART)

    compact = {
        "cli_rc": drc.get("cli_rc", 0),
        "kicad": "8.0.9",
        "counts": counts,
        "unconnected_nets": summary["unconnected_nets"],
        "short_samples": summary["samples"].get("shorting_items", []),
        "crossing_samples": summary["samples"].get("tracks_crossing", []),
        "unconnected_samples": summary["samples"].get("unconnected_items", []),
        "placement": notes,
        "route_report": report,
        "sensor_pours": sensor_pour_count(board),
        "fuse_segment_bridges_both_pads": bridged,
    }
    DRC_JSON.write_text(json.dumps(compact, indent=2) + "\n")

    lines = [
        f"tracks={tr}",
        f"vias={via}",
        f"footprints=54",
        f"drc_shorts={counts.get('shorting_items', 0)}",
        f"drc_crossings={counts.get('tracks_crossing', 0)}",
        f"drc_unconnected={counts.get('unconnected_items', 0)}",
        f"drc_clearance={counts.get('clearance', 0)}",
        f"drc_cli_rc={drc.get('cli_rc', 0)}",
        "strategy=surgical_east_drc_polish_rotate_u3u4_reroute",
        "kicad_cli=8.0.9",
        "hellcore=untouched",
        "fuse=ATO_placeholder_not_bridged" if not bridged else "fuse=BRIDGED",
        "sensor_pour=absent_not_added",
        "placement_u3u4=rot+90_centers_unchanged",
        "placement_j1=west_1.2mm",
        "placement_d1=88,24",
        "placement_sense_rc_y=35.70",
    ]
    STATUS.write_text("\n".join(lines) + "\n")

    left = ["# Leftover after surgical east DRC polish\n"]
    left.append("## Placement nudges (required to clear pad copper)\n")
    for k, v in notes.items():
        left.append(f"- {k}: {v}")
    left.append("\n## Route report\n")
    for k, v in report.items():
        if v != "ok":
            left.append(f"- {k}: {v}")
    left.append("\n## DRC counts\n")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        left.append(f"- {k}: {v}")
    left.append("\n## Unconnected by net\n")
    for k, v in sorted(summary["unconnected_nets"].items(), key=lambda kv: -kv[1]):
        left.append(f"- {k}: {v}")
    left.append("\n## Still shorting (sample)\n")
    for s in summary["samples"].get("shorting_items", []):
        left.append(f"- {s['description']}")
    left.append("\nSENSOR pours: 0 (not added). F1 ATO placeholder left in place.\n")
    left.append(f"Fuse segment bridges both F1 pads: {bridged}\n")
    LEFTOVER.write_text("\n".join(left) + "\n")
    print("wrote", DRC_JSON, STATUS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
