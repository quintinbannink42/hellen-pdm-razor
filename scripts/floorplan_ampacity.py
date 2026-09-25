#!/usr/bin/env python3
"""Ampacity floorplan for pdmrazora.

Grows the outline and moves M1000, the west HP drivers, and a handful of
passives so PWR_OUT1–4 can be poured at the IPC-2221A 1 oz / 20 °C width
(16.72 mm, or F+B legs that sum to that). Does not bridge F1, does not pour
SENSOR_GND, does not export gerbers, and does not replay cut_crossings_sexp.py.

80 A peak stays a pour + F.Mask solder-blob, not an 83 mm trace.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pcbnew
from pcbnew import (
    B_Cu,
    F_Cu,
    F_Mask,
    FromMM,
    PCB_SHAPE,
    PCB_VIA,
    ToMM,
    VECTOR2I,
    ZONE,
    ZONE_CONNECTION_FULL,
    ZONE_FILLER,
)

PCB = Path("/workspace/pdmrazora.kicad_pcb")

# New outline. Old was (0, 0)–(109, 98).
X0, Y0, X1, Y1 = -32.0, -40.0, 142.0, 162.0

# (net, layer, x0, y0, x1, y1, name)
# Widths below are the series cross-section of that leg (the short side),
# except PO4_wleg which is paralleled F+B (8.70 + 8.70, one drill on a cut).
ZONES = [
    # PWR_OUT1 — F.Cu. Hole bypass 8.55 + 8.60, then 16.72 band and drop.
    ("PWR_OUT1", F_Cu, 38.25, 53.95, 54.97, 60.60, "PO1_pins"),
    # Stop at 119.20 so these legs do not enter the PWR_OUT2 band (y=120).
    ("PWR_OUT1", F_Cu, 38.25, 56.00, 46.80, 119.20, "PO1_left"),
    ("PWR_OUT1", F_Cu, 51.00, 56.00, 59.60, 119.20, "PO1_right"),
    ("PWR_OUT1", F_Cu, 53.93, 70.10, 70.65, 119.20, "PO1_drop"),
    ("PWR_OUT1", F_Cu, 38.25, 102.00, 71.00, 118.72, "PO1_band"),
    # PWR_OUT2 — F.Cu west column, south band, east column, driver drop.
    ("PWR_OUT2", F_Cu, 21.08, 53.95, 37.80, 140.00, "PO2_col"),
    ("PWR_OUT2", F_Cu, 99.20, 51.90, 116.00, 68.70, "PO2_drop"),
    ("PWR_OUT2", F_Cu, 104.50, 51.90, 121.22, 140.00, "PO2_east"),
    ("PWR_OUT2", F_Cu, 21.08, 120.00, 122.00, 136.72, "PO2_band"),
    # PWR_OUT3 — upper gallery, west pin column, B.Cu drop through PO4's band.
    ("PWR_OUT3", F_Cu, 16.30, -36.00, 37.70, 38.70, "PO3_pcol"),
    # Taller than 16.72 so one via drill on a vertical cut still leaves ≥16.72.
    ("PWR_OUT3", F_Cu, 16.30, -37.50, 68.00, -19.28, "PO3_gal"),
    # Wider than 16.72 so two via drills on one cross-cut still leave ≥16.72.
    ("PWR_OUT3", B_Cu, 49.20, -35.50, 69.00, 16.50, "PO3_bdrop"),
    ("PWR_OUT3", F_Cu, 49.20, 0.15, 69.00, 16.50, "PO3_fvia"),
    ("PWR_OUT3", F_Cu, 51.03, 16.00, 67.75, 43.70, "PO3_col"),
    ("PWR_OUT3", F_Cu, 67.40, 40.05, 73.00, 43.65, "PO3_stub"),
    # PWR_OUT4 — F+B west leg (8.55 each), F.Cu top band, east drop, driver.
    # 8.70 mm each side. One 0.30 mm drill on a cross-cut leaves (8.70-0.30)*2 = 16.80.
    ("PWR_OUT4", F_Cu, 38.00, -18.20, 46.70, 39.20, "PO4_wleg"),
    ("PWR_OUT4", B_Cu, 38.00, -18.20, 46.70, 39.20, "PO4_wleg_B"),
    ("PWR_OUT4", F_Cu, 38.00, -18.20, 138.22, -0.40, "PO4_top"),
    # B.Cu cap stops 0.40 mm west of the PWR_OUT3 B drop (x=49.20).
    ("PWR_OUT4", B_Cu, 38.00, -18.20, 48.80, -0.40, "PO4_top_B"),
    ("PWR_OUT4", F_Cu, 121.50, -18.20, 138.22, 38.27, "PO4_down"),
    ("PWR_OUT4", F_Cu, 102.10, 21.55, 138.22, 38.27, "PO4_link"),
    ("PWR_OUT4", F_Cu, 99.20, 34.70, 104.20, 38.50, "PO4_pad"),
]

# F.Cu rectangles that get solder-mask openings (solder-blob peak path).
MASK_RECTS = [z[2:6] for z in ZONES if z[1] == F_Cu]

MOVES = {
    "R10": (48.8, 88.0),
    "C10": (48.8, 92.5),
    "R20": (96.5, 100.0),
    "C20": (96.5, 104.5),
    "R40": (78.0, 100.0),
    "C40": (84.0, 100.0),
    "R30": (72.0, 30.0),
    "C30": (76.0, 30.0),
    "R1": (-20.0, -28.0),
    "R2": (-12.0, -28.0),
    "C1": (100.0, -28.0),
    "C2": (112.0, -28.0),
    "D1": (112.0, 8.0),
}


def mm(x, y=None):
    if y is None:
        return FromMM(x)
    return VECTOR2I(FromMM(x), FromMM(y))


def xy(p):
    return ToMM(p.x), ToMM(p.y)


def wipe(board, items):
    for it in items:
        board.Delete(it)


def zones(board):
    return [board.GetArea(i) for i in range(board.GetAreaCount())]


def inside(x, y, box, pad=0.0):
    return box[0] - pad <= x <= box[2] + pad and box[1] - pad <= y <= box[3] + pad


def relocate_copper(board, box, dx, dy):
    """Move items with both ends in box. Delete items with only one end in box."""
    d = mm(dx, dy)
    moved = deleted = 0
    kill = []
    for t in list(board.GetTracks()):
        if t.GetClass() == "PCB_VIA":
            x, y = xy(t.GetPosition())
            if inside(x, y, box):
                t.Move(d)
                moved += 1
            continue
        ends = []
        getters = []
        if hasattr(t, "GetStart") and hasattr(t, "GetEnd"):
            getters = [t.GetStart, t.GetEnd]
        flags = []
        pts = []
        for g in getters:
            p = g()
            pts.append(p)
            flags.append(inside(ToMM(p.x), ToMM(p.y), box))
        if not flags:
            continue
        if all(flags):
            t.Move(d)
            moved += 1
        elif any(flags):
            kill.append(t)
            deleted += 1
    wipe(board, kill)
    return moved, deleted


def seg_hits_rect(x1, y1, x2, y2, rect, margin):
    x0, y0, x1r, y1r = rect[0] - margin, rect[1] - margin, rect[2] + margin, rect[3] + margin

    def inn(x, y):
        return x0 <= x <= x1r and y0 <= y <= y1r

    if inn(x1, y1) or inn(x2, y2):
        return True
    if max(x1, x2) < x0 or min(x1, x2) > x1r or max(y1, y2) < y0 or min(y1, y2) > y1r:
        return False
    steps = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.35))
    for i in range(steps + 1):
        t = i / steps
        if inn(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t):
            return True
    return False


def item_hits(item, rect, margin):
    if item.GetClass() == "PCB_VIA":
        x, y = xy(item.GetPosition())
        r = ToMM(item.GetWidth()) / 2
        return seg_hits_rect(x, y, x, y, rect, margin + r)
    if not hasattr(item, "GetStart"):
        return False
    a, b = item.GetStart(), item.GetEnd()
    w = ToMM(item.GetWidth()) / 2 if hasattr(item, "GetWidth") else 0.0
    return seg_hits_rect(ToMM(a.x), ToMM(a.y), ToMM(b.x), ToMM(b.y), rect, margin + w)


def add_zone(board, net, layer, rect, name):
    x0, y0, x1, y1 = rect
    z = ZONE(board)
    z.SetNet(board.FindNet(net))
    z.SetLayer(layer)
    z.SetIsRuleArea(False)
    z.SetAssignedPriority(3)
    z.SetLocalClearance(FromMM(0.20))
    z.SetMinThickness(FromMM(0.15))
    z.SetPadConnection(ZONE_CONNECTION_FULL)
    if hasattr(z, "SetZoneName"):
        z.SetZoneName(name)
    try:
        z.SetFillMode(pcbnew.ZONE_FILL_MODE_POLYGONS)
    except Exception:
        pass
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        z.AppendCorner(mm(x, y), -1)
    board.Add(z)
    return z


def set_outline(zone, rect, holes=()):
    """Replace a zone outline. holes are (x0, y0, x1, y1) cutouts.

    SHAPE_POLY_SET.Append after NewHole writes the outer contour, leaving an
    empty hole. Cutouts go through AddHole on a closed chain.
    """
    x0, y0, x1, y1 = rect
    zone.UnFill()
    ol = zone.Outline()
    ol.RemoveAllContours()
    ol.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        ol.Append(int(FromMM(x)), int(FromMM(y)))
    for hx0, hy0, hx1, hy1 in holes:
        chain = pcbnew.SHAPE_LINE_CHAIN()
        # Opposite winding from the outer (CW) rectangle.
        for x, y in ((hx0, hy0), (hx0, hy1), (hx1, hy1), (hx1, hy0)):
            chain.Append(int(FromMM(x)), int(FromMM(y)))
        chain.SetClosed(True)
        ol.AddHole(chain)
    zone.SetNeedRefill(True)


def add_via(board, x, y, net):
    v = PCB_VIA(board)
    v.SetPosition(mm(x, y))
    v.SetDrill(FromMM(0.30))
    v.SetWidth(FromMM(0.60))
    v.SetNet(board.FindNet(net))
    board.Add(v)
    return v


def via_grid(board, net, xs, ys):
    n = 0
    for x in xs:
        for y in ys:
            add_via(board, x, y, net)
            n += 1
    return n


def via_diag(board, net, x0, y0, n, dx, dy):
    """One via per X and per Y, so an axis-aligned cut hits a single drill."""
    for i in range(n):
        add_via(board, round(x0 + i * dx, 3), round(y0 + i * dy, 3), net)
    return n


def grow_outline(board):
    board.GetDesignSettings().SetAuxOrigin(mm(X0, Y1))
    found = {"top": False, "bottom": False, "left": False, "right": False}
    edges = {
        "top": ((X0, Y0), (X1, Y0)),
        "bottom": ((X1, Y1), (X0, Y1)),
        "left": ((X0, Y1), (X0, Y0)),
        "right": ((X1, Y0), (X1, Y1)),
    }
    for d in board.GetDrawings():
        if d.GetLayer() != pcbnew.Edge_Cuts or not hasattr(d, "GetStart"):
            continue
        x1, y1 = xy(d.GetStart())
        x2, y2 = xy(d.GetEnd())
        key = None
        if abs(y1) < 0.3 and abs(y2) < 0.3:
            key = "top"
        elif abs(y1 - 98) < 0.3 and abs(y2 - 98) < 0.3:
            key = "bottom"
        elif abs(x1) < 0.3 and abs(x2) < 0.3:
            key = "left"
        elif abs(x1 - 109) < 0.3 and abs(x2 - 109) < 0.3:
            key = "right"
        if key is None or found[key]:
            continue
        (sx, sy), (ex, ey) = edges[key]
        d.SetStart(mm(sx, sy))
        d.SetEnd(mm(ex, ey))
        found[key] = True
    missing = [k for k, ok in found.items() if not ok]
    if missing:
        raise SystemExit(f"edge cuts not updated: {missing} {found}")
    tb = board.GetTitleBlock()
    # pcbnew comment index 0 is the file's (comment 1).
    tb.SetComment(
        0,
        "PowerCore PDM (pdmrazora) - Razor-class 174x202 - ampacity floorplan, exposed HP outs",
    )
    board.SetTitleBlock(tb)


def reshape_existing_zones(board):
    feeder = None
    gnd = None
    for z in zones(board):
        if z.GetIsRuleArea():
            continue
        name = z.GetZoneName() if hasattr(z, "GetZoneName") else ""
        bb = z.Outline().BBox()
        box = (
            round(ToMM(bb.GetLeft()), 2),
            round(ToMM(bb.GetTop()), 2),
            round(ToMM(bb.GetRight()), 2),
            round(ToMM(bb.GetBottom()), 2),
        )
        if name == "VBAT_post_fuse_feeder" or (
            z.GetNetname() == "VBAT" and z.GetAssignedPriority() == 2 and box[1] > 20 and box[3] < 32
        ):
            feeder = z
        if z.GetNetname() == "GND" and z.GetLayer() == B_Cu and (box[2] - box[0]) > 80:
            gnd = z
    if feeder is None or gnd is None:
        raise SystemExit(f"missing zone feeder={feeder is not None} gnd={gnd is not None}")
    # Keep ≥16.72 mm and stay 0.40 mm west of the PWR_OUT4 link (x=102.10).
    set_outline(feeder, (84.80, 23.40, 101.70, 29.20))
    # Keepout cutout is 0.1 mm outside the inflated rule area so the outline
    # does not share an edge with it. PWR_OUT4 B cutout is 0.45 mm outside
    # that pour so the filled gap beats the zone clearance without relying
    # on the filler's ~0.015 mm undershoot.
    set_outline(
        gnd,
        (X0 + 0.8, Y0 + 0.8, X1 - 0.8, Y1 - 0.8),
        holes=(
            (-29.2, 24.7, 15.5, 67.2),
            (37.55, -18.65, 49.25, 39.65),
        ),
    )
    gnd.SetLocalClearance(FromMM(0.25))
    ol = gnd.Outline()
    print(
        "reshaped feeder and GND B outline",
        "holes",
        ol.HoleCount(0),
        "hole0 pts",
        ol.CHole(0, 0).PointCount() if ol.HoleCount(0) else 0,
    )


def delete_mask(board):
    kill = []
    for d in board.GetDrawings():
        if d.GetLayer() == F_Mask and d.GetClass() == "PCB_SHAPE":
            kill.append(d)
    wipe(board, kill)
    return len(kill)


def add_mask(board):
    """Hatch F.Mask openings over the new F.Cu HP pours. Target ~358."""

    def segs(step):
        out = []
        for x0, y0, x1, y1 in MASK_RECTS:
            inset = 0.65
            xa, xb = x0 + inset, x1 - inset
            if xb - xa < 1.2:
                continue
            y = y0 + inset
            while y <= y1 - inset + 1e-6:
                out.append((xa, y, xb, y))
                y += step
        return out

    step = 4.0
    n = len(segs(step))
    if n:
        step = max(1.15, min(8.0, step * n / 358.0))
    chosen = segs(step)
    # Nudge once if we're outside 340–380.
    if len(chosen) > 380:
        step *= len(chosen) / 358.0
        chosen = segs(step)
    elif len(chosen) < 340:
        step *= len(chosen) / 358.0
        chosen = segs(step)
    for xa, y, xb, _ in chosen:
        s = PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(mm(xa, y))
        s.SetEnd(mm(xb, y))
        s.SetWidth(FromMM(0.45))
        s.SetLayer(F_Mask)
        board.Add(s)
    return len(chosen), step


def pour_rects():
    return [(z[1], z[2:6]) for z in ZONES]


def delete_conflicting_copper(board):
    kill = []
    for t in list(board.GetTracks()):
        net = t.GetNetname()
        if net.startswith("PWR_OUT") or net.startswith("ADIO"):
            kill.append(t)
            continue
        layer = None
        if t.GetClass() == "PCB_VIA":
            layer = "via"
        elif t.GetLayer() == F_Cu:
            layer = F_Cu
        elif t.GetLayer() == B_Cu:
            layer = B_Cu
        else:
            continue
        for zlayer, rect in pour_rects():
            if layer != "via" and layer != zlayer:
                continue
            if item_hits(t, rect, 0.15):
                kill.append(t)
                break
    # unique
    seen = set()
    uniq = []
    for t in kill:
        i = t.m_Uuid.AsString() if hasattr(t, "m_Uuid") else id(t)
        if i in seen:
            continue
        seen.add(i)
        uniq.append(t)
    wipe(board, uniq)
    return len(uniq)


def delete_foreign_on_moved_pads(board, refs):
    boxes = []
    for fp in board.GetFootprints():
        if fp.GetReference() not in refs:
            continue
        for pad in fp.Pads():
            net = pad.GetNetname()
            if not net:
                continue
            bb = pad.GetBoundingBox()
            boxes.append(
                (
                    net,
                    (
                        ToMM(bb.GetLeft()),
                        ToMM(bb.GetTop()),
                        ToMM(bb.GetRight()),
                        ToMM(bb.GetBottom()),
                    ),
                )
            )
    kill = []
    for t in list(board.GetTracks()):
        net = t.GetNetname()
        for pnet, rect in boxes:
            if net == pnet:
                continue
            if item_hits(t, rect, 0.22):
                kill.append(t)
                break
    wipe(board, kill)
    return len(kill)


def measure(board):
    """Minimum filled cross-section of each named zone, in the short direction."""
    rows = []
    for z in zones(board):
        name = z.GetZoneName() if hasattr(z, "GetZoneName") else ""
        if not name.startswith("PO"):
            continue
        if not z.IsFilled():
            rows.append((name, 0.0, "unfilled"))
            continue
        bb = z.Outline().BBox()
        x0, y0 = ToMM(bb.GetLeft()), ToMM(bb.GetTop())
        x1, y1 = ToMM(bb.GetRight()), ToMM(bb.GetBottom())
        layer = z.GetLayer()
        # Flow is along the long side, except the PWR_OUT3 via landing,
        # which is a vertical series path inside a wide rectangle.
        wide = (x1 - x0) >= (y1 - y0) and name != "PO3_fvia"
        spans = []
        if wide:
            # horizontal leg: series width is vertical span
            for i in range(1, 8):
                x = x0 + (x1 - x0) * i / 8
                ys = []
                y = y0 - 0.4
                while y <= y1 + 0.4:
                    if z.HitTestFilledArea(layer, mm(x, y)):
                        ys.append(y)
                    y += 0.20
                if ys:
                    spans.append(ys[-1] - ys[0] + 0.20)
        else:
            for i in range(1, 8):
                y = y0 + (y1 - y0) * i / 8
                xs = []
                x = x0 - 0.4
                while x <= x1 + 0.4:
                    if z.HitTestFilledArea(layer, mm(x, y)):
                        xs.append(x)
                    x += 0.20
                if xs:
                    spans.append(xs[-1] - xs[0] + 0.20)
        rows.append((name, min(spans) if spans else 0.0, f"{x1-x0:.2f}x{y1-y0:.2f}"))
    return rows


def keepout_hits(board):
    # Moved keepout: (-27.9, 26)–(14.2, 65.9)
    k = (-27.7, 26.2, 14.0, 65.7)
    n = 0
    for z in zones(board):
        if z.GetIsRuleArea() or not z.IsFilled():
            continue
        layer = z.GetLayer()
        # sample a grid
        x = k[0]
        while x < k[2]:
            y = k[1]
            while y < k[3]:
                try:
                    if z.HitTestFilledArea(layer, mm(x, y)):
                        n += 1
                        break
                except Exception:
                    pass
                y += 2.0
            else:
                x += 2.0
                continue
            break
    return n


def main():
    before_txt = PCB.read_text()
    in1_before = before_txt.count("In1.Cu")
    board = pcbnew.LoadBoard(str(PCB))

    # --- M1000 west, keepout and local copper with it ---
    old_keep = (2.1, 26.0, 44.2, 65.9)
    m1000 = next(f for f in board.GetFootprints() if f.GetReference() == "M1000")
    print("M1000 from", tuple(round(v, 2) for v in xy(m1000.GetPosition())))
    mv, dl = relocate_copper(board, (old_keep[0] - 1.2, old_keep[1] - 1.2, old_keep[2] + 1.2, old_keep[3] + 1.2), -30, 0)
    m1000.Move(mm(-30, 0))
    # Footprint.Move translates the embedded keepout polygon by the same
    # delta. The filler treats those points as board coordinates, so a second
    # shift lands the pour ban 30 mm west of the module and across the new
    # north apron. Rewrite it to the translated module box (inflated like
    # the board rule area).
    for z in m1000.Zones():
        if z.GetIsRuleArea():
            set_outline(z, (-29.1, 24.8, 15.4, 67.1))
    print(f"M1000 copper moved {mv} deleted-stretched {dl}")
    for z in zones(board):
        if not z.GetIsRuleArea():
            continue
        bb = z.Outline().BBox()
        if abs(ToMM(bb.GetLeft()) - 2.1) < 0.3 and abs(ToMM(bb.GetTop()) - 26) < 0.3:
            # Inflate 1.2 mm past the translated keepout so edge pads and the
            # tracks that sit on the module wall are inside the pour ban.
            # Translated box is (-27.9, 26.0)–(14.2, 65.9).
            set_outline(z, (-29.1, 24.8, 15.4, 67.1))
            print("keepout moved and inflated")

    for ref, dx in (("U1", 10), ("U3", 12)):
        fp = next(f for f in board.GetFootprints() if f.GetReference() == ref)
        boxes = []
        for pad in fp.Pads():
            bb = pad.GetBoundingBox()
            boxes.append(
                (ToMM(bb.GetLeft()) - 0.5, ToMM(bb.GetTop()) - 0.5, ToMM(bb.GetRight()) + 0.5, ToMM(bb.GetBottom()) + 0.5)
            )
        # One box around all pads.
        box = (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )
        mv, dl = relocate_copper(board, box, dx, 0)
        fp.Move(mm(dx, 0))
        print(f"{ref} +{dx} copper moved {mv} deleted {dl} now {tuple(round(v,2) for v in xy(fp.GetPosition()))}")

    for ref, (x, y) in MOVES.items():
        fp = next(f for f in board.GetFootprints() if f.GetReference() == ref)
        print(f"{ref} {tuple(round(v,2) for v in xy(fp.GetPosition()))} -> ({x}, {y})")
        fp.SetPosition(mm(x, y))

    grow_outline(board)
    reshape_existing_zones(board)

    n_cu = delete_conflicting_copper(board)
    print("deleted power/conflicting copper", n_cu)
    n_pad = delete_foreign_on_moved_pads(board, {"M1000", "U1", "U3", *MOVES})
    print("deleted foreign copper on moved pads", n_pad)

    for net, layer, x0, y0, x1, y1, name in ZONES:
        add_zone(board, net, layer, (x0, y0, x1, y1), name)

    # Via fences. A 0.30 mm drill removes 0.30 mm from every layer on that cut.
    # Diagonals keep each axis-aligned cut to one drill. The lower PWR_OUT3
    # fence is two columns inside a 19.80 mm vertical leg (cut loses 0.60).
    def seq(a, n, step):
        return [round(a + i * step, 3) for i in range(n)]

    nvia = 0
    # 26 * 0.67 mm ≈ 17.4 mm. Pitch sqrt(0.70^2+0.48^2) ≈ 0.85 mm.
    nvia += via_diag(board, "PWR_OUT3", 50.0, -34.8, 26, 0.70, 0.48)
    nvia += via_grid(board, "PWR_OUT3", [54.0, 55.3], seq(1.2, 15, 1.05))
    # 13 * 0.67 mm ≈ 8.7 mm, enough for the 8.70 mm B.Cu half.
    nvia += via_diag(board, "PWR_OUT4", 38.40, -15.0, 13, 0.85, 0.45)
    print("vias", nvia)

    removed_mask = delete_mask(board)
    nmask, step = add_mask(board)
    print(f"mask removed {removed_mask} added {nmask} step {step:.2f}")

    print("filling...")
    ZONE_FILLER(board).Fill(board.Zones())
    rows = measure(board)
    for name, w, kind in rows:
        print(f"  fill {name:12} min~{w:.2f}  ({kind})")

    print("keepout sample hits", keepout_hits(board))

    pcbnew.SaveBoard(str(PCB), board)
    text = PCB.read_text()
    text2 = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text2 = re.sub(r'\(generator_version "[^"]+"\)', '(generator_version "8.0")', text2, count=1)
    text2 = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text2)
    text2 = text2.replace(
        "Razor-class 109x98 - symmetric drivers, exposed HP outs",
        "Razor-class 174x202 - ampacity floorplan, exposed HP outs",
    )
    text2 = re.sub(r'\n\t\t\(comment 2 "[^"]*"\)', "", text2)
    if text2 != text:
        PCB.write_text(text2)
        print("normalized file version to 20240108 / 8.0")
    in1_after = PCB.read_text().count("In1.Cu")
    print(f"In1.Cu before {in1_before} after {in1_after}")
    print(f"outline ({X0},{Y0})-({X1},{Y1})  {X1-X0:.0f} x {Y1-Y0:.0f} mm")


if __name__ == "__main__":
    main()
