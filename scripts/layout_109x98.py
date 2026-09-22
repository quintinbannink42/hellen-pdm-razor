#!/usr/bin/env python3
"""Grow pdmrazora to 109×98 mm and rebuild the split-bobbin power field.

Quintin: +5 mm on each axis (104×93 → 109×98), HP×4 and ADIO×8 mirrored
about the power-field centerline x=80, M1000 keepout punched through the
pours, PWR_OUT1–4 carried on exposed F.Cu.

Does not replay scripts/cut_crossings_sexp.py or the 150×130 long-haul routers.
Does not pour SENSOR_GND. Does not bridge F1.
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
    F_Mask,
    FromMM,
    PCB_SHAPE,
    PCB_TRACK,
    PCB_VIA,
    PCB_VIA_T,
    ToMM,
    VECTOR2I,
    ZONE,
    ZONE_CONNECTION_FULL,
    ZONE_FILLER,
)

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "pdmrazora.kicad_pcb"
OFFICIAL = Path("/tmp/mcu/mega-mcu144.kicad_mod")
STATUS = ROOT / "scripts" / "copper_status.txt"
LEFTOVER = ROOT / "scripts" / "unconnected_leftover.txt"
MOVES = ROOT / "scripts" / "layout_109_moves.txt"
DRC_JSON = ROOT / "scripts" / "drc_zonefill.json"
PNG = ROOT / "scripts" / "copper_fill_overview.png"
MASK_PNG = ROOT / "scripts" / "hp_mask_openings.png"
ART = Path("/opt/cursor/artifacts/copper_fill_fb_overview.png")
ART_MASK = Path("/opt/cursor/artifacts/hp_exposed_fcu_mask.png")

BOARD_W, BOARD_H = 109.0, 98.0
CX = 80.0  # power-field centerline (vertical). Drivers mirror about this line.
CLR = 0.20
EDGE = 0.55
GRID = 0.40

# Module keepout in board coordinates. M1000 anchor (2, 66), official polygon
# local (0.1, -40) … (42.2, -0.1).
KEEP_X0, KEEP_Y0, KEEP_X1, KEEP_Y1 = 2.1, 26.0, 44.2, 65.9

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
        WIDTH[n] = 0.70
    elif n.startswith("ADIO"):
        WIDTH[n] = 0.30
    else:
        WIDTH[n] = 0.20


def mm(x, y=None):
    if y is None:
        return FromMM(x)
    return VECTOR2I(FromMM(x), FromMM(y))


def setpos(fp, x, y, rot=None):
    if rot is not None:
        fp.SetOrientationDegrees(rot)
    fp.SetPosition(mm(x, y))


def cy_box(fp):
    poly = fp.GetCourtyard(pcbnew.F_CrtYd)
    bb = poly.BBox()
    if bb.GetWidth() <= 0 or bb.GetHeight() <= 0:
        return None
    return (
        ToMM(bb.GetLeft()),
        ToMM(bb.GetTop()),
        ToMM(bb.GetRight()),
        ToMM(bb.GetBottom()),
    )


def boxes_overlap(a, b, clr=0.0) -> bool:
    return not (a[2] + clr < b[0] or b[2] + clr < a[0] or a[3] + clr < b[1] or b[3] + clr < a[1])


def snapshot(board):
    rows = []
    for fp in board.GetFootprints():
        p = fp.GetPosition()
        rows.append(
            (
                fp.GetReference(),
                round(ToMM(p.x), 3),
                round(ToMM(p.y), 3),
                round(fp.GetOrientationDegrees(), 1),
            )
        )
    return {r[0]: r for r in rows}


def apply_placement(board):
    """Symmetric driver field between J2 (north VBAT) and J3 (south GND)."""
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    # (ref, x, y, rot). Rot 0 / 180 mirrors TO-263 and TSDSO about x=80.
    place = {
        "M1000": (2.0, 66.0, 0),
        "J1": (48.8, 46.5, 90),
        "J2": (80.0, 12.0, 0),
        "J3": (80.0, 86.5, 0),
        "F1": (100.0, 15.0, -90),
        "C1": (62.0, 7.5, 0),
        "C2": (93.2, 6.2, 0),
        "D1": (106.0, 22.0, 90),
        "R1": (56.0, 18.5, 0),
        "R2": (56.0, 21.5, 90),
        # North row is PWR_OUT3/4 (connector pins are the north ends of the columns).
        "U3": (66.0, 39.2, 0),
        "U4": (94.0, 39.2, 180),
        # South row is PWR_OUT1/2 (connector pins are the south ends).
        "U1": (66.0, 69.4, 0),
        "U2": (94.0, 69.4, 180),
        # HP sense, outboard of the packages so the centerline stays clear.
        "R30": (58.2, 32.2, 0),
        "C30": (62.4, 32.2, 0),
        "R40": (101.8, 32.2, 0),
        "C40": (97.6, 32.2, 0),
        "R10": (58.2, 76.6, 0),
        "C10": (62.4, 76.6, 0),
        "R20": (101.8, 76.6, 0),
        "C20": (97.6, 76.6, 0),
    }
    adio_x = [67.1, 75.7, 84.3, 92.9]
    for i, ref in enumerate(["U11", "U12", "U13", "U14"]):
        place[ref] = (adio_x[i], 48.5, 180 if adio_x[i] < CX else 0)
    for i, ref in enumerate(["U15", "U16", "U17", "U18"]):
        place[ref] = (adio_x[i], 60.1, 180 if adio_x[i] < CX else 0)
    # Three passive rows between the ADIO rows, 8-wide, mirrored X.
    xs = [66.0, 70.0, 74.0, 78.0, 82.0, 86.0, 90.0, 94.0]
    for i, ref in enumerate([f"R10{n}" for n in range(1, 9)]):
        place[ref] = (xs[i], 52.4, 0)
    for i, ref in enumerate([f"C10{n}" for n in range(1, 9)]):
        place[ref] = (xs[i], 54.3, 0)
    for i, ref in enumerate([f"R20{n}" for n in range(1, 9)]):
        place[ref] = (xs[i], 56.2, 0)

    for ref, (x, y, rot) in place.items():
        setpos(fps[ref], x, y, rot)
    return place


def courtyard_hits(board):
    fps = list(board.GetFootprints())
    hits = []
    boxes = []
    for fp in fps:
        box = cy_box(fp)
        if box is None:
            continue
        boxes.append((fp.GetReference(), box))
    for i, (ra, a) in enumerate(boxes):
        for rb, b in boxes[i + 1 :]:
            if boxes_overlap(a, b, 0.0):
                hits.append((ra, rb, a, b))
    return hits


def remove_item(board, item):
    # KiCad 8's swig wrapper double-frees unless Python releases ownership first.
    item.thisown = 0
    board.Remove(item)


def _seg_ends(shape):
    a, b = shape.GetStart(), shape.GetEnd()
    return ToMM(a.x), ToMM(a.y), ToMM(b.x), ToMM(b.y)


def grow_outline(board):
    # Set this before any Remove(); deleting Edge.Cuts shapes breaks the swig wrapper.
    design = board.GetDesignSettings()
    design.SetAuxOrigin(mm(0, BOARD_H))
    edges = {
        "top": ((0, 0), (BOARD_W, 0)),
        "right": ((BOARD_W, 0), (BOARD_W, BOARD_H)),
        "bottom": ((BOARD_W, BOARD_H), (0, BOARD_H)),
        "left": ((0, BOARD_H), (0, 0)),
    }
    found = {k: False for k in edges}
    for d in board.GetDrawings():
        if d.GetLayer() != pcbnew.Edge_Cuts or not hasattr(d, "GetStart"):
            continue
        x1, y1, x2, y2 = _seg_ends(d)
        horiz = abs(y1 - y2) < 0.2
        vert = abs(x1 - x2) < 0.2
        key = None
        if horiz and min(y1, y2) < 1:
            key = "top"
        elif horiz and max(y1, y2) > 50:
            key = "bottom"
        elif vert and min(x1, x2) < 1:
            key = "left"
        elif vert and max(x1, x2) > 50:
            key = "right"
        if key is None or found[key]:
            continue
        (sx, sy), (ex, ey) = edges[key]
        d.SetStart(mm(sx, sy))
        d.SetEnd(mm(ex, ey))
        found[key] = True
    missing = [k for k, ok in found.items() if not ok]
    if missing:
        raise SystemExit(f"edge cuts not updated: {missing}")
    # Stretch the existing EMI marker; add the driver centerline once.
    has_center = False
    for d in board.GetDrawings():
        if d.GetLayer() != pcbnew.Dwgs_User or not hasattr(d, "GetStart"):
            continue
        x1, y1, x2, y2 = _seg_ends(d)
        if abs(x1 - 45.5) < 0.2 and abs(x2 - 45.5) < 0.2:
            d.SetStart(mm(45.5, 2.0))
            d.SetEnd(mm(45.5, 96.0))
        if abs(x1 - CX) < 0.2 and abs(x2 - CX) < 0.2:
            has_center = True
    if not has_center:
        s = PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(mm(CX, 2.0))
        s.SetEnd(mm(CX, 96.0))
        s.SetLayer(pcbnew.Dwgs_User)
        s.SetWidth(FromMM(0.12))
        board.Add(s)
    tb = board.GetTitleBlock()
    tb.SetComment(1, "PowerCore PDM (pdmrazora) - Razor-class 109x98 - symmetric drivers, exposed HP outs")
    # Refresh the user notes that still say 104×93.
    for d in board.GetDrawings():
        if d.GetClass() != "PCB_TEXT":
            continue
        text = d.GetText()
        if "POWER" in text:
            d.SetText("POWER  drivers mirrored @ x=80")
            d.SetPosition(mm(58, 3.2))
        elif text.startswith("J2 M6"):
            d.SetText("J2 M6 VBAT+ north    J3 M6 GND south    centerline x=80")
            d.SetPosition(mm(56, 1.6))
        elif text.startswith("J1 TE"):
            d.SetPosition(mm(46.5, 95.2))


def layer_names(pad, board=None):
    ls = pad.GetLayerSet()
    names = []
    for lid in range(pcbnew.PCB_LAYER_ID_COUNT):
        if ls.Contains(lid):
            names.append(pcbnew.LayerName(lid))
    return names


def fix_m1000(board):
    """Restore Hellen 0.7 inner-layer pads and make the keepout punch all copper.

    On a 2-layer carrier the In1/In2 pads save as 'no layer' and DRC reports
    padstack_invalid. Put the official single inner layer back so silk, pads,
    and the keepout polygon describe the same 42.2 × 40 mm module.
    """
    if not OFFICIAL.exists():
        raise SystemExit(f"missing official footprint {OFFICIAL}")
    off = pcbnew.FootprintLoad(str(OFFICIAL.parent), "mega-mcu144")
    off_inner = defaultdict(list)
    for pad in off.Pads():
        names = layer_names(pad)
        if names in (["In1.Cu"], ["In2.Cu"]):
            p = pad.GetPosition()
            key = (round(ToMM(p.x), 3), round(ToMM(p.y), 3))
            off_inner[key].append(names[0])
    fp = next(f for f in board.GetFootprints() if f.GetReference() == "M1000")
    anchor = fp.GetPosition()
    ax, ay = ToMM(anchor.x), ToMM(anchor.y)
    restored = 0
    by_pos = defaultdict(list)
    for pad in fp.Pads():
        if layer_names(pad):
            continue
        p = pad.GetPosition()
        key = (round(ToMM(p.x) - ax, 3), round(ToMM(p.y) - ay, 3))
        by_pos[key].append(pad)
    for key, pads in by_pos.items():
        names = off_inner.get(key, [])
        for pad, name in zip(pads, names):
            ls = pcbnew.LSET()
            ls.AddLayer(pcbnew.In1_Cu if name == "In1.Cu" else pcbnew.In2_Cu)
            pad.SetLayerSet(ls)
            restored += 1
    # Footprint keepout: all copper, same polygon as silk.
    for z in fp.Zones():
        if z.GetIsRuleArea():
            z.SetLayerSet(pcbnew.LSET.AllCuMask())
            z.SetDoNotAllowCopperPour(True)
            z.SetDoNotAllowTracks(False)
            z.SetDoNotAllowVias(False)
            z.SetDoNotAllowPads(False)
            z.SetDoNotAllowFootprints(False)
    return restored


def strip_board_copper(path: Path) -> dict:
    """Drop board-level tracks and zones. Footprint keepout zones stay (two-tab indent)."""
    text = path.read_text()
    names = {"segment", "via", "zone", "arc"}
    out = []
    i = 0
    n = len(text)
    removed = defaultdict(int)
    while i < n:
        hit = text.startswith("\n\t(", i)
        if hit:
            j = i + 3
            k = j
            while k < n and text[k].isalnum():
                k += 1
            name = text[j:k]
            if name in names:
                depth = 0
                p = i + 2  # the '('
                while p < n:
                    c = text[p]
                    if c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                        if depth == 0:
                            p += 1
                            break
                    p += 1
                removed[name] += 1
                i = p
                continue
        out.append(text[i])
        i += 1
    path.write_text("".join(out))
    return dict(removed)


def add_rect_zone(board, net, layer, corners, priority=1, clearance=0.30):
    z = ZONE(board)
    if net:
        z.SetNet(board.FindNet(net))
    z.SetLayer(layer)
    z.SetIsRuleArea(False)
    z.SetAssignedPriority(priority)
    z.SetLocalClearance(FromMM(clearance))
    z.SetMinThickness(FromMM(0.35))
    z.SetPadConnection(ZONE_CONNECTION_FULL)
    for x, y in corners:
        z.AppendCorner(mm(x, y), -1)
    board.Add(z)
    return z


def add_keepout(board):
    z = ZONE(board)
    z.SetIsRuleArea(True)
    ls = pcbnew.LSET()
    ls.AddLayer(F_Cu)
    ls.AddLayer(B_Cu)
    z.SetLayerSet(ls)
    z.SetDoNotAllowCopperPour(True)
    z.SetDoNotAllowTracks(False)
    z.SetDoNotAllowVias(False)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    for x, y in (
        (KEEP_X0, KEEP_Y0),
        (KEEP_X1, KEEP_Y0),
        (KEEP_X1, KEEP_Y1),
        (KEEP_X0, KEEP_Y1),
    ):
        z.AppendCorner(mm(x, y), -1)
    board.Add(z)
    return z


def build_zones(board):
    """VBAT split at F1. GND full board on B.Cu. No SENSOR_GND pour.

    F1 rot -90 at (100, 15): pad 1 (pre) at (100, 15), pad 2 (post) at (100, 24.2).
    """
    add_keepout(board)
    # Pre-fuse: J2 island plus a finger to F1.1 only. Stops west of x=102 and
    # north of y=19 so it cannot reach F1.2 at y=24.2.
    add_rect_zone(
        board,
        "VBAT",
        F_Cu,
        [(68.5, 1.0), (103.5, 1.0), (103.5, 19.2), (96.5, 19.2), (96.5, 22.5), (68.5, 22.5)],
    )
    add_rect_zone(
        board,
        "VBAT",
        B_Cu,
        [(68.5, 1.0), (103.5, 1.0), (103.5, 19.2), (96.5, 19.2), (96.5, 22.5), (68.5, 22.5)],
    )
    # Post-fuse driver field. Top edge y=27 is south of F1.2 (pad extends to ~26)
    # and the strap from pad 2 is a track, not a pour that also covers pad 1.
    add_rect_zone(board, "VBAT", F_Cu, [(54.5, 27.5), (107.5, 27.5), (107.5, 75.2), (54.5, 75.2)])
    add_rect_zone(board, "VBAT", B_Cu, [(86.0, 30.0), (107.0, 30.0), (107.0, 74.5), (86.0, 74.5)])
    add_rect_zone(board, "VBAT", B_Cu, [(55.0, 32.0), (78.0, 32.0), (78.0, 74.5), (55.0, 74.5)])
    # GND. Module keepout punches the pour. F.Cu island is only around J3.
    add_rect_zone(board, "GND", B_Cu, [(0.8, 0.8), (108.2, 0.8), (108.2, 97.2), (0.8, 97.2)], clearance=0.25)
    add_rect_zone(board, "GND", F_Cu, [(68.0, 76.2), (92.5, 76.2), (92.5, 97.0), (68.0, 97.0)])


def add_track(board, x1, y1, x2, y2, width, net, layer="F"):
    if math.hypot(x2 - x1, y2 - y1) < 0.02:
        return None
    tr = PCB_TRACK(board)
    tr.SetStart(mm(x1, y1))
    tr.SetEnd(mm(x2, y2))
    tr.SetWidth(FromMM(width))
    tr.SetLayer(F_Cu if layer == "F" else B_Cu)
    tr.SetNet(board.FindNet(net))
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


def strap_fuse(board):
    """J2 → F1.1 on both layers. F1.2 → post-fuse pour. No segment touches both pads."""
    # J2 copper is the 16 mm pad at (80, 12). Exit east.
    add_track(board, 88.0, 12.0, 100.0, 12.0, 2.0, "VBAT", "F")
    add_track(board, 100.0, 12.0, 100.0, 15.0, 2.0, "VBAT", "F")
    add_track(board, 88.0, 14.5, 100.0, 14.5, 1.4, "VBAT", "B")
    add_via(board, 88.0, 12.0, "VBAT", 0.9, 0.45)
    add_via(board, 96.0, 14.5, "VBAT", 0.9, 0.45)
    # Post-fuse pad 2 at (100, 24.2), pad radius ~1.75. Stop the strap at the pad.
    add_track(board, 100.0, 24.2, 100.0, 30.5, 2.0, "VBAT", "F")
    add_track(board, 100.0, 30.5, 90.0, 30.5, 2.0, "VBAT", "F")
    add_via(board, 90.0, 30.5, "VBAT", 0.9, 0.45)
    add_via(board, 100.0, 28.5, "VBAT", 0.9, 0.45)


def pad_box(pad):
    bb = pad.GetBoundingBox()
    return ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom())


def collect_pads(board):
    pads = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            names = layer_names(pad)
            on_f = "F.Cu" in names or any(n.startswith("In") for n in names) and pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
            on_b = "B.Cu" in names
            # PTH *.Cu includes F and B even if the name list is long.
            attr = pad.GetAttribute()
            if attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                layers = ("F", "B")
            elif "F.Cu" in names:
                layers = ("F",)
            elif "B.Cu" in names:
                layers = ("B",)
            else:
                continue
            if not names and attr not in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                continue
            x, y = ToMM(pad.GetPosition().x), ToMM(pad.GetPosition().y)
            pads.append(
                {
                    "ref": ref,
                    "num": pad.GetNumber(),
                    "net": pad.GetNetname() or "",
                    "x": x,
                    "y": y,
                    "box": pad_box(pad),
                    "layers": layers,
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


class GridRouter:
    def __init__(self, pads, segs, vias):
        self.pads = pads
        self.segs = segs
        self.vias = vias
        self.nx = int(BOARD_W / GRID) + 3
        self.ny = int(BOARD_H / GRID) + 3

    def _cell(self, x, y):
        return int(round(x / GRID)), int(round(y / GRID))

    def paint(self, net, width):
        halo = width / 2 + CLR
        vhalo = 0.30 + CLR
        blk = [bytearray(self.nx * self.ny), bytearray(self.nx * self.ny)]
        vblk = bytearray(self.nx * self.ny)

        def paint_rect(l, t, r, b, layer, via=False):
            ix0 = max(0, int(l / GRID))
            ix1 = min(self.nx - 1, int(r / GRID) + 1)
            iy0 = max(0, int(t / GRID))
            iy1 = min(self.ny - 1, int(b / GRID) + 1)
            for iy in range(iy0, iy1 + 1):
                cy = iy * GRID
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
            if "F" in p["layers"]:
                paint_rect(l - halo, t - halo, r + halo, b + halo, 0)
                paint_rect(l - vhalo, t - vhalo, r + vhalo, b + vhalo, None, via=True)
            if "B" in p["layers"]:
                paint_rect(l - halo, t - halo, r + halo, b + halo, 1)
                paint_rect(l - vhalo, t - vhalo, r + vhalo, b + vhalo, None, via=True)
        for x1, y1, x2, y2, lay, n, w in self.segs:
            if n == net:
                continue
            h = halo + w / 2
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
        for ix in range(self.nx):
            for iy in range(self.ny):
                x, y = ix * GRID, iy * GRID
                if x < EDGE or y < EDGE or x > BOARD_W - EDGE or y > BOARD_H - EDGE:
                    blk[0][iy * self.nx + ix] = 1
                    blk[1][iy * self.nx + ix] = 1
                    vblk[iy * self.nx + ix] = 1
        self.blk = blk
        self.vblk = vblk

    def free(self, ix, iy, layer) -> bool:
        if not (0 <= ix < self.nx and 0 <= iy < self.ny):
            return False
        return self.blk[layer][iy * self.nx + ix] == 0

    def nearest_free(self, x, y, layer, rad_max=10):
        ix, iy = self._cell(x, y)
        if self.free(ix, iy, layer):
            return ix, iy
        for rad in range(1, rad_max + 1):
            for dx in range(-rad, rad + 1):
                for dy in range(-rad, rad + 1):
                    if max(abs(dx), abs(dy)) != rad:
                        continue
                    if self.free(ix + dx, iy + dy, layer):
                        return ix + dx, iy + dy
        return None

    def route(self, x1, y1, x2, y2, prefer_layer, start_layers=None, goal_layers=None, goal_r=0.85):
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
            c0 = 0 if lay == prefer_layer else 4
            best[(ix, iy, lay)] = c0
            heapq.heappush(pq, (c0 + abs(ix * GRID - x2) + abs(iy * GRID - y2), c0, ix, iy, lay))
        parent = {}
        expanded = 0
        found = None
        while pq and expanded < 400000:
            _h, g, ix, iy, lay = heapq.heappop(pq)
            if g != best.get((ix, iy, lay)):
                continue
            expanded += 1
            if lay in goal_layers and math.hypot(ix * GRID - x2, iy * GRID - y2) <= goal_r and g > 0:
                found = (ix, iy, lay)
                break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = ix + dx, iy + dy
                if not self.free(nx, ny, lay):
                    continue
                step = 1.0 if lay == prefer_layer else 1.25
                cx, cy = nx * GRID, ny * GRID
                if KEEP_X0 < cx < KEEP_X1 and KEEP_Y0 < cy < KEEP_Y1:
                    step += 0.55
                ng = g + step
                key = (nx, ny, lay)
                if ng < best.get(key, inf):
                    best[key] = ng
                    parent[key] = (ix, iy, lay)
                    heapq.heappush(pq, (ng + abs(cx - x2) + abs(cy - y2), ng, nx, ny, lay))
            if self.vblk[iy * self.nx + ix] == 0 and self.free(ix, iy, 0) and self.free(ix, iy, 1):
                nlay = 1 - lay
                ng = g + 2.6
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
            if len(path) > 8000:
                return None
        path.reverse()
        return path


def commit_path(board, router, path, x1, y1, x2, y2, net, width):
    pts = [(x1, y1, path[0][2])]
    for ix, iy, lay in path:
        pts.append((ix * GRID, iy * GRID, lay))
    pts.append((x2, y2, path[-1][2]))
    compact = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - compact[-1][0]) < 0.02 and abs(p[1] - compact[-1][1]) < 0.02 and p[2] == compact[-1][2]:
            continue
        compact.append(p)
    simp = [compact[0]]
    for i in range(1, len(compact) - 1):
        a, b, c = simp[-1], compact[i], compact[i + 1]
        if a[2] == b[2] == c[2] and abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) < 1e-6:
            continue
        simp.append(b)
    simp.append(compact[-1])
    layname = {0: "F", 1: "B"}
    for i in range(len(simp) - 1):
        xa, ya, la = simp[i]
        xb, yb, lb = simp[i + 1]
        if la != lb:
            add_via(board, xb, yb, net)
            router.vias.append((xb, yb, net, 0.6))
            continue
        add_track(board, xa, ya, xb, yb, width, net, layname[la])
        router.segs.append((xa, ya, xb, yb, layname[la], net, width))


def route_signals(board, pads) -> dict:
    segs, vias = [], []
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
        if p["net"] in REROUTE:
            by_net[p["net"]].append(p)

    def _rank(n):
        if n.startswith("PWR"):
            return 0
        if n.startswith("ADIO"):
            return 1
        if n.startswith("OUT_"):
            return 2
        if n.startswith("IN_"):
            return 3
        return 4

    report = {}
    for net in sorted(by_net, key=lambda n: (_rank(n), n)):
        uniq, seen = [], set()
        for p in by_net[net]:
            k = (round(p["x"], 2), round(p["y"], 2), p["ref"], p["num"])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(p)
        uniq.sort(key=lambda p: (p["ref"] == "M1000", p["ref"] != "J1", p["ref"], str(p["num"])))
        if len(uniq) < 2:
            report[net] = "single-pad"
            print(f"  {net}: single-pad", flush=True)
            continue
        width = WIDTH[net]
        # PWR_OUT stays on F.Cu so the mask opening covers the current path.
        if net.startswith("PWR_OUT"):
            prefer, starts, goals = 0, (0,), (0,)
        elif net in EN_NETS:
            prefer, starts, goals = 1, (1, 0), (1, 0)
        else:
            prefer, starts, goals = 0, (0, 1), (0, 1)
        router.paint(net, width)

        def lays(p):
            return tuple(0 if L == "F" else 1 for L in p["layers"])

        clusters = [[p] for p in uniq]
        failed = []
        guard = 0
        while len(clusters) > 1 and guard < 40:
            guard += 1
            best = None
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    for a in clusters[i]:
                        for b in clusters[j]:
                            dist = abs(a["x"] - b["x"]) + abs(a["y"] - b["y"])
                            if best is None or dist < best[0]:
                                best = (dist, i, j, a, b)
            _d, i, j, a, b = best
            path = router.route(a["x"], a["y"], b["x"], b["y"], prefer, starts, goals)
            if path is None and not net.startswith("PWR_OUT"):
                path = router.route(a["x"], a["y"], b["x"], b["y"], 1 - prefer, (0, 1), (0, 1))
            if path is None and net.startswith("PWR_OUT"):
                # Last resort: allow a B.Cu hop, then still expose the F.Cu portions.
                path = router.route(a["x"], a["y"], b["x"], b["y"], 0, (0, 1), (0, 1))
            if path is None:
                drop = j if len(clusters[j]) <= len(clusters[i]) else i
                failed.extend(f"{p['ref']}.{p['num']}" for p in clusters[drop])
                clusters.pop(drop)
                continue
            commit_path(board, router, path, a["x"], a["y"], b["x"], b["y"], net, width)
            hi, lo = max(i, j), min(i, j)
            clusters[lo].extend(clusters[hi])
            clusters.pop(hi)
            router.paint(net, width)
        report[net] = "ok" if not failed else "open:" + ",".join(failed)
        print(f"  {net}: {report[net]}", flush=True)
    return report


def dist_pt_seg(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def segment_clear(board, x1, y1, x2, y2, width, net, layer) -> bool:
    """True if a track of this width stays 0.20 mm off foreign copper on the layer."""
    halo = width / 2 + CLR
    samples = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.35) + 1)
    for t in board.GetTracks():
        if is_via(t):
            if t.GetNetname() == net:
                continue
            p = t.GetPosition()
            if dist_pt_seg(ToMM(p.x), ToMM(p.y), x1, y1, x2, y2) < halo + ToMM(t.GetWidth()) / 2:
                return False
            continue
        if t.GetNetname() == net:
            continue
        if (layer == "F" and t.GetLayer() != F_Cu) or (layer == "B" and t.GetLayer() != B_Cu):
            continue
        a, b = t.GetStart(), t.GetEnd()
        # bbox reject
        if min(x1, x2) - halo > max(ToMM(a.x), ToMM(b.x)) + ToMM(t.GetWidth()):
            continue
        # sample-to-segment
        tw = ToMM(t.GetWidth()) / 2
        for i in range(samples):
            u = i / (samples - 1)
            px = x1 + (x2 - x1) * u
            py = y1 + (y2 - y1) * u
            if dist_pt_seg(px, py, ToMM(a.x), ToMM(a.y), ToMM(b.x), ToMM(b.y)) < halo + tw:
                return False
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if (pad.GetNetname() or "") == net:
                continue
            names = layer_names(pad)
            attr = pad.GetAttribute()
            if attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                hit_layer = True
            elif layer == "F":
                hit_layer = "F.Cu" in names
            else:
                hit_layer = "B.Cu" in names
            if not hit_layer:
                continue
            l, t, r, b = pad_box(pad)
            for i in range(samples):
                u = i / (samples - 1)
                px = x1 + (x2 - x1) * u
                py = y1 + (y2 - y1) * u
                cx = min(max(px, l), r)
                cy = min(max(py, t), b)
                if math.hypot(px - cx, py - cy) < halo:
                    return False
    # Board edge.
    for i in range(samples):
        u = i / (samples - 1)
        px = x1 + (x2 - x1) * u
        py = y1 + (y2 - y1) * u
        if px - width / 2 < 0.5 or py - width / 2 < 0.5 or px + width / 2 > BOARD_W - 0.5 or py + width / 2 > BOARD_H - 0.5:
            return False
    return True


def widen_pwr(board):
    """Grow each F.Cu PWR_OUT segment up to 2.4 mm where clearance allows."""
    widened = 0
    for t in list(board.GetTracks()):
        if is_via(t) or t.GetLayer() != F_Cu:
            continue
        net = t.GetNetname()
        if not net.startswith("PWR_OUT"):
            continue
        a, b = t.GetStart(), t.GetEnd()
        x1, y1, x2, y2 = ToMM(a.x), ToMM(a.y), ToMM(b.x), ToMM(b.y)
        chosen = ToMM(t.GetWidth())
        for w in (2.40, 1.80, 1.20, 0.90):
            if w <= chosen + 0.01:
                break
            if segment_clear(board, x1, y1, x2, y2, w, net, "F"):
                t.SetWidth(FromMM(w))
                chosen = w
                widened += 1
                break
    return widened


def expose_pwr_mask(board):
    """Solder-mask openings (F.Mask) over every F.Cu PWR_OUT1–4 track.

    The opening is 0.10 mm narrower than the copper so it does not reach the
    next net. KiCad plots F.Mask as a mask opening.
    """
    n = 0
    for t in list(board.GetTracks()):
        if is_via(t) or t.GetLayer() != F_Cu:
            continue
        net = t.GetNetname()
        if not net.startswith("PWR_OUT"):
            continue
        a, b = t.GetStart(), t.GetEnd()
        width = max(0.25, ToMM(t.GetWidth()) - 0.10)
        s = PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(a)
        s.SetEnd(b)
        s.SetWidth(FromMM(width))
        s.SetLayer(F_Mask)
        board.Add(s)
        n += 1
    return n


def pour_inside_keepout(board) -> int:
    hits = 0
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetIsRuleArea() or not z.IsFilled():
            continue
        try:
            polys = z.GetFilledPolysList(z.GetFirstLayer())
        except TypeError:
            polys = z.GetFilledPolysList()
        for k in range(polys.OutlineCount()):
            ol = polys.COutline(k)
            for j in range(ol.PointCount()):
                x, y = ToMM(ol.CPoint(j).x), ToMM(ol.CPoint(j).y)
                if KEEP_X0 + 0.15 < x < KEEP_X1 - 0.15 and KEEP_Y0 + 0.15 < y < KEEP_Y1 - 0.15:
                    hits += 1
                    break
    return hits


def fuse_bridged(board) -> bool:
    fp = next(f for f in board.GetFootprints() if f.GetReference() == "F1")
    a = fp.FindPadByNumber("1").GetPosition()
    b = fp.FindPadByNumber("2").GetPosition()
    ax, ay, bx, by = ToMM(a.x), ToMM(a.y), ToMM(b.x), ToMM(b.y)
    for item in iter_segs(board):
        if item[0] != "seg" or item[7] != "VBAT":
            continue
        _, _t, x1, y1, x2, y2, *_rest = item
        if dist_pt_seg(ax, ay, x1, y1, x2, y2) < 1.2 and dist_pt_seg(bx, by, x1, y1, x2, y2) < 1.2:
            return True
    return False


def sensor_pours(board) -> int:
    n = 0
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if not z.GetIsRuleArea() and z.GetNetname() == "SENSOR_GND":
            n += 1
    return n


def downgrade_to_k8(path: Path) -> None:
    text = path.read_text()
    text = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text = re.sub(r'\(generator_version "[^"]+"\)', '(generator_version "8.0")', text, count=1)
    text = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text)
    text = re.sub(r"\n\t\t\(embedded_fonts (yes|no)\)", "", text)
    text = re.sub(r"\n\t\t\(tenting [^\n]+\)", "", text)
    path.write_text(text)


def restore_inner_after_save(path: Path) -> int:
    """pcbnew drops In1/In2 on a 2-layer board. Write the official layers back."""
    if not OFFICIAL.exists():
        return 0
    off = pcbnew.FootprintLoad(str(OFFICIAL.parent), "mega-mcu144")
    # Local positions that must be inner-only, in the order they appear.
    wanted = []
    for pad in off.Pads():
        names = layer_names(pad)
        if names in (["In1.Cu"], ["In2.Cu"]):
            p = pad.GetPosition()
            wanted.append((round(ToMM(p.x), 3), round(ToMM(p.y), 3), names[0]))
    text = path.read_text()
    # Replace empty-layer SMD pads that sit on those local coordinates inside M1000.
    # The saved form of a stripped pad is `(layers )` or a missing copper layer.
    # KiCad 8 writes `(layers "F.Cu")` etc. Stripped inner pads come out as
    # `(layers)` empty which DRC calls "Pad has no layer". Match the at-position
    # relative to the footprint only by rewriting pads whose layer list is empty.
    n = len(re.findall(r"\(layers\)", text))
    # Pair sequentially with the official inner pads — same order as the footprint.
    idx = {"i": 0}

    def repl(m):
        i = idx["i"]
        if i >= len(wanted):
            return m.group(0)
        name = wanted[i][2]
        idx["i"] += 1
        return f'(layers "{name}")'

    text2, count = re.subn(r"\(layers\)", repl, text, count=len(wanted))
    if count:
        path.write_text(text2)
    return count


def plot_png(board, path: Path) -> None:
    from PIL import Image, ImageDraw

    scale = 8
    w, h = int(BOARD_W * scale) + 8, int(BOARD_H * scale) + 8

    img = Image.new("RGB", (w * 2 + 16, h), (16, 16, 20))
    dr = ImageDraw.Draw(img, "RGBA")

    def panel(origin_x, layer_name):
        def pxy(x, y):
            return origin_x + int(x * scale) + 4, int(y * scale) + 4

        dr.rectangle([pxy(0, 0), pxy(BOARD_W, BOARD_H)], outline=(120, 120, 130))
        dr.rectangle(
            [pxy(KEEP_X0, KEEP_Y0), pxy(KEEP_X1, KEEP_Y1)],
            outline=(220, 80, 80),
        )
        for i in range(board.GetAreaCount()):
            z = board.GetArea(i)
            if z.GetIsRuleArea() or not z.IsFilled():
                continue
            lay = z.GetFirstLayer()
            if (lay == F_Cu and layer_name != "F") or (lay == B_Cu and layer_name != "B"):
                continue
            try:
                polys = z.GetFilledPolysList(lay)
            except TypeError:
                polys = z.GetFilledPolysList()
            name = z.GetNetname()
            col = (190, 70, 55, 130) if name == "VBAT" else (50, 90, 170, 100)
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
            width = 3 if net.startswith("PWR_OUT") else 1
            if net.startswith("PWR_OUT"):
                col = (255, 196, 40)
            elif net == "VBAT":
                col = (230, 90, 70)
            elif net == "GND":
                col = (120, 170, 240)
            elif net.startswith("ADIO"):
                col = (240, 210, 80)
            else:
                col = (190, 140, 210)
            dr.line([pxy(ToMM(a.x), ToMM(a.y)), pxy(ToMM(b.x), ToMM(b.y))], fill=col, width=width)
        label = "F.Cu  (gold = exposed PWR_OUT)" if layer_name == "F" else "B.Cu"
        dr.text((origin_x + 8, 6), label, fill=(235, 235, 235))

    panel(0, "F")
    panel(w + 8, "B")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def plot_mask(board, path: Path) -> None:
    from PIL import Image, ImageDraw

    scale = 10
    w, h = int(BOARD_W * scale) + 8, int(BOARD_H * scale) + 8
    img = Image.new("RGB", (w, h), (12, 18, 12))
    dr = ImageDraw.Draw(img, "RGBA")

    def pxy(x, y):
        return int(x * scale) + 4, int(y * scale) + 4

    dr.rectangle([pxy(0, 0), pxy(BOARD_W, BOARD_H)], outline=(80, 120, 80))
    for t in board.GetTracks():
        if is_via(t) or t.GetLayer() != F_Cu or not t.GetNetname().startswith("PWR_OUT"):
            continue
        a, b = t.GetStart(), t.GetEnd()
        dr.line(
            [pxy(ToMM(a.x), ToMM(a.y)), pxy(ToMM(b.x), ToMM(b.y))],
            fill=(255, 210, 60),
            width=max(2, int(ToMM(t.GetWidth()) * scale * 0.7)),
        )
    for d in board.GetDrawings():
        if d.GetLayer() != F_Mask:
            continue
        if not hasattr(d, "GetStart"):
            continue
        a, b = d.GetStart(), d.GetEnd()
        dr.line(
            [pxy(ToMM(a.x), ToMM(a.y)), pxy(ToMM(b.x), ToMM(b.y))],
            fill=(255, 80, 40, 180),
            width=max(2, int(ToMM(d.GetWidth()) * scale * 0.45)),
        )
    dr.text((8, 6), "F.Cu PWR_OUT (gold) + F.Mask opening (red)", fill=(240, 240, 220))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def run_drc():
    out = Path("/tmp/pdmrazora_drc_109.json")
    proc = subprocess.run(
        ["kicad-cli", "pcb", "drc", "--severity-error", "--units", "mm", "--format", "report", "-o", str(out), str(PCB)],
        capture_output=True,
        text=True,
    )
    text = out.read_text() if out.exists() else proc.stdout
    return proc.returncode, text, proc.stderr


def summarize_report(text: str) -> dict:
    counts = defaultdict(int)
    un = defaultdict(int)
    section = None
    for line in text.splitlines():
        if line.startswith("[") and ":" in line:
            typ = line.split("]")[0][1:]
            # unconnected items are listed separately
            if "unconnected" in line.lower():
                section = "unconnected"
            else:
                section = typ
                counts[typ] += 1
        elif line.startswith("** Found"):
            continue
        elif "Pad" in line and section == "unconnected":
            m = re.search(r"\[([^\]]+)\]", line)
            if m:
                un[m.group(1)] += 1
    # The report format counts each violation header.
    types = re.findall(r"^\[([^\]]+)\]", text, re.M)
    counts = defaultdict(int)
    for t in types:
        counts[t] += 1
    # unconnected block
    un_items = re.findall(r"^\[unconnected_items\]:(.*)", text, re.M)
    return {"counts": dict(counts), "unconnected_headers": len(un_items), "un_nets_in_lines": dict(un)}


def main() -> int:
    print("=== 109x98 symmetric layout ===", flush=True)
    board = pcbnew.LoadBoard(str(PCB))
    before = snapshot(board)
    apply_placement(board)
    after = snapshot(board)
    hits = courtyard_hits(board)
    print(f"courtyard overlaps: {len(hits)}", flush=True)
    for ra, rb, a, b in hits[:30]:
        print(f"  {ra} {tuple(round(v,2) for v in a)} ~ {rb} {tuple(round(v,2) for v in b)}")
    if hits and "--force" not in sys.argv:
        print("aborting before save; fix placement", flush=True)
        return 2

    lines = ["ref before_x before_y before_rot after_x after_y after_rot"]
    for ref in sorted(before, key=lambda r: (r[0], int("".join(ch for ch in r if ch.isdigit()) or "0"))):
        bx, by, br = before[ref][1:]
        ax, ay, ar = after[ref][1:]
        if (bx, by, br) != (ax, ay, ar):
            lines.append(f"{ref} {bx:.3f} {by:.3f} {br:.1f} {ax:.3f} {ay:.3f} {ar:.1f}")
    MOVES.write_text("\n".join(lines) + "\n")
    print(f"moved {len(lines)-1} footprints", flush=True)

    n_inner = fix_m1000(board)
    print(f"restored M1000 inner pads {n_inner}", flush=True)
    grow_outline(board)
    board.Save(str(PCB))
    downgrade_to_k8(PCB)
    stripped = strip_board_copper(PCB)
    print(f"stripped {stripped}", flush=True)
    n_restore = restore_inner_after_save(PCB)
    print(f"sexp inner-layer restore {n_restore}", flush=True)
    board = pcbnew.LoadBoard(str(PCB))
    build_zones(board)
    strap_fuse(board)
    pads = collect_pads(board)
    print("routing…", flush=True)
    report = route_signals(board, pads)
    n_wide = widen_pwr(board)
    n_mask = expose_pwr_mask(board)
    print(f"widened {n_wide} PWR segments, mask openings {n_mask}", flush=True)
    print("filling…", flush=True)
    ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    print(f"keepout interior pour verts {pour_inside_keepout(board)}", flush=True)
    print(f"fuse bridged {fuse_bridged(board)} sensor pours {sensor_pours(board)}", flush=True)
    board.Save(str(PCB))
    downgrade_to_k8(PCB)
    n_restore = restore_inner_after_save(PCB)
    print(f"sexp inner-layer restore after route {n_restore}", flush=True)
    board = pcbnew.LoadBoard(str(PCB))
    plot_png(board, PNG)
    plot_png(board, ART)
    plot_mask(board, MASK_PNG)
    plot_mask(board, ART_MASK)
    print("DRC…", flush=True)
    rc, report_text, err = run_drc()
    (ROOT / "scripts" / "drc_109.txt").write_text(report_text)
    summary = summarize_report(report_text)
    print(json.dumps(summary["counts"], indent=2))
    STATUS.write_text(
        f"outline {BOARD_W}x{BOARD_H}\n"
        f"centerline x={CX}\n"
        f"fuse_bridged {fuse_bridged(board)}\n"
        f"sensor_pours {sensor_pours(board)}\n"
        f"keepout_hits {pour_inside_keepout(board)}\n"
        f"mask_openings {n_mask}\n"
        f"route {json.dumps(report)}\n"
        f"drc {json.dumps(summary['counts'])}\n"
    )
    print(err[-400:] if err else "", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
