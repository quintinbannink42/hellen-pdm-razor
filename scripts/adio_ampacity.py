#!/usr/bin/env python3
"""ADIO ampacity pours for pdmrazora.

Odd channels ADIO1, ADIO3, ADIO5, ADIO7 leave the east edge of J1 on F+B
(or a single 3.80 mm B.Cu leg where F.Cu is the HP pour) and run down the
east margin into the south of the HP field. Even channels ADIO2, ADIO4,
ADIO6, ADIO8 stay open. `scripts/even_adio_fanout.py` (also
`adio_ampacity.py --even-audit`) measures the widest corridor out of
those pins; the SuperSeal cage still closes them at 0.60 mm (F+B 1.20 mm).
This script does not pour the even nets, does not bridge F1, does not pour
SENSOR_GND, does not export gerbers, and does not replay
cut_crossings_sexp.py.

HP PWR_OUT zones are not rewritten. 80 A peak stays pour + F.Mask.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

# pcbnew is imported by main(). The even-pin audit does not need KiCad.
pcbnew = None
B_Cu = F_Cu = FromMM = PCB_VIA = ToMM = VECTOR2I = None
ZONE = ZONE_CONNECTION_FULL = ZONE_FILLER = None


def _load_pcbnew():
    global pcbnew, B_Cu, F_Cu, FromMM, PCB_VIA, ToMM, VECTOR2I
    global ZONE, ZONE_CONNECTION_FULL, ZONE_FILLER
    import pcbnew as _pcbnew
    from pcbnew import (
        B_Cu as _B_Cu,
        F_Cu as _F_Cu,
        FromMM as _FromMM,
        PCB_VIA as _PCB_VIA,
        ToMM as _ToMM,
        VECTOR2I as _VECTOR2I,
        ZONE as _ZONE,
        ZONE_CONNECTION_FULL as _ZONE_CONNECTION_FULL,
        ZONE_FILLER as _ZONE_FILLER,
    )

    pcbnew = _pcbnew
    B_Cu, F_Cu, FromMM, PCB_VIA, ToMM = _B_Cu, _F_Cu, _FromMM, _PCB_VIA, _ToMM
    VECTOR2I, ZONE = _VECTOR2I, _ZONE
    ZONE_CONNECTION_FULL, ZONE_FILLER = _ZONE_CONNECTION_FULL, _ZONE_FILLER

PCB = Path("/workspace/pdmrazora.kicad_pcb")
CLR = 0.20

# Driver column. OUT faces east (rotation 0). Center pad sits in the VBAT tap;
# OUT pads sit just east of it. Spur copper starts at x=86.85.
X_DRV = 84.8
# (ref, net or "", y). Empty net = parked even driver, VBAT only.
# North-to-south spurs match west-to-east columns, so a spur never crosses
# another channel's column (that column has already ended).
DRIVERS = [
    ("U11", "ADIO1", 82.0),
    ("U13", "ADIO3", 91.0),
    ("U15", "ADIO5", 100.0),
    ("U17", "ADIO7", 109.0),
    ("U12", "", 146.0),
    ("U14", "", 154.0),
]

# Spur on the south OUT pads (local +y), clear of the unnetted center pad.
SPUR_DY0, SPUR_DY1 = 0.55, 2.75  # 2.20 mm

# (net, layer, x0, y0, x1, y1, name, flow) flow h = width is dy, v = width is dx
ZONES = []


def add(net, layer, rect, name, flow):
    x0, y0, x1, y1 = rect
    ZONES.append((net, layer, x0, y0, x1, y1, name, flow))


def _spur(net, prefix, col, east_y, spur_y, east_h_is_pin=False):
    """Column + B spur under PO2_east + F only on either side of that pour.

    col is (x0, x1). east_y is (y0, y1) of the eastbound leg. spur_y is the
    3.80 mm driver spur. The eastbound rectangles themselves are added by the
    caller so the pin jog can be a different height.
    """
    cx0, cx1 = col
    ey0, ey1 = east_y
    sy0, sy1 = spur_y
    # Vertical slot. Starts at the eastbound (north of every column further west
    # has not begun, or this slot is west of those still running).
    add(net, F_Cu, (cx0, ey0, cx1, sy1), f"{prefix}_col_F", "v")
    add(net, B_Cu, (cx0, ey0, cx1, sy1), f"{prefix}_col_B", "v")
    # B.Cu under PWR_OUT2 east (x=104.50–121.22). 3.80 mm, no via on this leg.
    add(net, B_Cu, (86.85, sy0, cx1, sy1), f"{prefix}_spur_B", "h")
    # F.Cu up to the OUT pads, stopping 0.25 mm west of PO2_east.
    add(net, F_Cu, (86.85, sy0, 104.25, sy1), f"{prefix}_spur_Fw", "h")
    # F.Cu again once past PO2_east, joining the column.
    add(net, F_Cu, (121.45, sy0, cx1, sy1), f"{prefix}_spur_Fe", "h")
    # North OUT pads sit on the other side of the unnetted pad 11 (same X,
    # 0.20 mm gap in Y). The north bar stays above pad 11 and overlaps the
    # east bridge; the bridge starts at x=88.55, 0.25 mm clear of pad 11.
    yd = sy0 - 0.55  # spur starts at driver_y + 0.55
    add(net, F_Cu, (86.85, yd - 2.45, 90.30, yd - 0.55), f"{prefix}_outN", "h")
    add(net, F_Cu, (88.55, yd - 2.45, 90.30, sy1), f"{prefix}_outJ", "v")


def build_zones():
    ZONES.clear()
    # Slots, west to east: ADIO1, ADIO3, ADIO5, ADIO7.
    # Northern eastbound (ADIO7) flies over the top to the eastern slot.
    # Each spur is north of every column it would otherwise have to cross.
    c1 = (122.40, 124.60)  # 2.20
    c3 = (125.00, 127.20)
    c5 = (127.60, 129.80)
    c7 = (130.20, 134.00)  # 3.80

    # ADIO7. Pin F+B 2.20, long B.Cu leg 3.80 (under PO3 / U3 / U4 and to the slot).
    add("ADIO7", F_Cu, (41.50, 42.55, 50.70, 44.75), "A7_pin_F", "h")
    add("ADIO7", B_Cu, (41.50, 42.55, 50.70, 44.75), "A7_pin_B", "h")
    add("ADIO7", B_Cu, (44.30, 40.25, c7[1], 44.05), "A7_east_B", "h")
    _spur("ADIO7", "A7", c7, (40.25, 44.05), (109.55, 113.35))

    # ADIO5. F+B 2.20. Eastbound stops at its own slot.
    add("ADIO5", F_Cu, (41.50, 45.15, c5[1], 47.35), "A5_east_F", "h")
    add("ADIO5", B_Cu, (41.50, 45.15, c5[1], 47.35), "A5_east_B", "h")
    _spur("ADIO5", "A5", c5, (45.15, 47.35), (100.55, 104.35))

    # ADIO3. F+B 2.01, clear of the ADIO5 pad.
    add("ADIO3", F_Cu, (41.50, 47.72, c3[1], 49.73), "A3_east_F", "h")
    add("ADIO3", B_Cu, (41.50, 47.72, c3[1], 49.73), "A3_east_B", "h")
    _spur("ADIO3", "A3", c3, (47.72, 49.73), (91.55, 95.35))

    # ADIO1. Pin F+B 2.20, low corridor F+B 1.75 with no via.
    add("ADIO1", F_Cu, (41.50, 51.40, 47.20, 53.60), "A1_pin_F", "h")
    add("ADIO1", B_Cu, (41.50, 51.40, 47.20, 53.60), "A1_pin_B", "h")
    add("ADIO1", F_Cu, (44.80, 49.94, c1[1], 51.70), "A1_low_F", "h")
    add("ADIO1", B_Cu, (44.80, 49.94, c1[1], 51.70), "A1_low_B", "h")
    _spur("ADIO1", "A1", c1, (49.94, 51.70), (82.55, 86.35))

    # VBAT tap along the driver exposed pads. 3.60 mm, the pad column.
    # F stops through the PWR_OUT2 band (y=120–136.72); B.Cu carries that hop.
    # This is the driver branch, not the post-fuse feeder.
    add("VBAT", F_Cu, (83.00, 74.55, 86.60, 119.55), "VBAT_drv_Fn", "v")
    add("VBAT", F_Cu, (83.00, 137.05, 86.60, 158.00), "VBAT_drv_Fs", "v")
    add("VBAT", B_Cu, (83.00, 74.55, 86.60, 158.00), "VBAT_drv_B", "v")


def mm(x, y=None):
    if y is None:
        return FromMM(x)
    return VECTOR2I(FromMM(x), FromMM(y))


def xy(p):
    return ToMM(p.x), ToMM(p.y)


def wipe(board, items):
    for it in items:
        board.Delete(it)


def overlaps(a, b, gap):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 + gap < bx0 or bx1 + gap < ax0 or ay1 + gap < by0 or by1 + gap < ay0)


def gap_of(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    dx = max(0.0, max(ax0, bx0) - min(ax1, bx1))
    # negative dx means overlap in x; use separation
    sep_x = max(bx0 - ax1, ax0 - bx1)
    sep_y = max(by0 - ay1, ay0 - by1)
    if sep_x < 0 and sep_y < 0:
        return min(sep_x, sep_y)  # overlap, most negative axis
    if sep_x < 0:
        return sep_y
    if sep_y < 0:
        return sep_x
    return math.hypot(sep_x, sep_y)


def collect_obstacles(board):
    pads = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            bb = pad.GetBoundingBox()
            box = (
                ToMM(bb.GetLeft()),
                ToMM(bb.GetTop()),
                ToMM(bb.GetRight()),
                ToMM(bb.GetBottom()),
            )
            if not pad.IsOnLayer(F_Cu) and not pad.IsOnLayer(B_Cu):
                continue
            pth = pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
            pads.append((pad.GetNetname(), fp.GetReference(), pad.GetNumber(), pth, pad.GetLayer(), box))
    hp = []
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        bb = z.Outline().BBox()
        box = (
            ToMM(bb.GetLeft()),
            ToMM(bb.GetTop()),
            ToMM(bb.GetRight()),
            ToMM(bb.GetBottom()),
        )
        if z.GetIsRuleArea():
            # Layer -1 means every copper layer.
            layers = []
            try:
                seq = list(z.GetLayerSet().Seq())
            except Exception:
                seq = [z.GetLayer()]
            hp.append(("KEEP", True, seq, box))
            continue
        name = z.GetNetname()
        if name.startswith("PWR_OUT") or name == "":
            hp.append((name or "KEEP", False, [z.GetLayer()], box))
    return pads, hp


def audit(board):
    """Return a list of clearance failures. Empty means the outlines are legal."""
    pads, hp = collect_obstacles(board)
    bad = []
    for net, layer, x0, y0, x1, y1, name, _flow in ZONES:
        rect = (x0, y0, x1, y1)
        for pnet, ref, num, pth, ply, box in pads:
            if pnet == net and pnet:
                continue
            if not pth and ply != layer:
                continue
            g = gap_of(rect, box)
            if g < CLR - 1e-3:
                bad.append(f"{name} vs {ref}.{num} {pnet or 'NONET'} gap {g:.3f} box {tuple(round(v,2) for v in box)}")
        for hname, rule, layers, box in hp:
            if layer not in layers and not (rule and (not layers or -1 in layers or layer in layers)):
                # rule areas with a single copper layer still block that layer
                if not rule and layer not in layers:
                    continue
                if rule:
                    # both-layer keepout has layer id -1 and a layerset
                    if layers and layer not in layers and -1 not in layers:
                        # F+B keepout stores both ids
                        if not any(L in (-1, layer) for L in layers):
                            continue
                    elif layers and layer not in layers and -1 not in layers:
                        continue
            if rule and layers and -1 not in layers and layer not in layers:
                continue
            if not rule and layer not in layers:
                continue
            g = gap_of(rect, box)
            if g < CLR - 1e-3:
                bad.append(f"{name} vs {hname} gap {g:.3f} box {tuple(round(v,2) for v in box)}")
    # Different-net ADIO/VBAT outlines.
    for i, a in enumerate(ZONES):
        for b in ZONES[i + 1 :]:
            if a[0] == b[0] and a[1] == b[1]:
                continue
            if a[0] == b[0]:
                continue  # same net, other layer is fine
            if a[1] != b[1]:
                continue
            g = gap_of(a[2:6], b[2:6])
            if g < CLR - 1e-3:
                bad.append(f"{a[6]} vs {b[6]} gap {g:.3f}")
    return bad


def item_hits(item, rect, margin):
    if item.GetClass() == "PCB_VIA":
        x, y = xy(item.GetPosition())
        r = ToMM(item.GetWidth()) / 2
        return rect[0] - margin - r <= x <= rect[2] + margin + r and rect[1] - margin - r <= y <= rect[3] + margin + r
    if not hasattr(item, "GetStart"):
        return False
    x1, y1 = xy(item.GetStart())
    x2, y2 = xy(item.GetEnd())
    w = ToMM(item.GetWidth()) / 2 if hasattr(item, "GetWidth") else 0.0
    m = margin + w
    x0, y0, x1r, y1r = rect[0] - m, rect[1] - m, rect[2] + m, rect[3] + m

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


def delete_conflicting(board):
    rects = [(z[1], z[2:6]) for z in ZONES]
    kill = []
    protected = []
    for t in list(board.GetTracks()):
        net = t.GetNetname()
        layer = None
        if t.GetClass() == "PCB_VIA":
            layer = "via"
        elif t.GetLayer() == F_Cu:
            layer = F_Cu
        elif t.GetLayer() == B_Cu:
            layer = B_Cu
        else:
            continue
        hit = False
        for zlayer, rect in rects:
            if layer != "via" and layer != zlayer:
                continue
            if item_hits(t, rect, 0.05):
                hit = True
                break
        if not hit:
            continue
        if net.startswith("PWR_OUT"):
            protected.append((net, t.GetClass()))
            continue
        # Same-net copper can stay; the zone replaces the path but a stub is not a short.
        znet = None
        for net_z, zlayer, *rest in [(z[0], z[1], z[2:6]) for z in ZONES]:
            pass
        same = False
        for zn, zl, x0, y0, x1, y1, _n, _f in ZONES:
            if zn != net:
                continue
            if layer != "via" and layer != zl:
                continue
            if item_hits(t, (x0, y0, x1, y1), 0.05):
                same = True
                break
        if same:
            continue
        kill.append(t)
    if protected:
        raise SystemExit(f"refusing to cut PWR_OUT copper: {protected[:8]}")
    wipe(board, kill)
    return len(kill)


def add_zone(board, net, layer, rect, name, priority):
    x0, y0, x1, y1 = rect
    z = ZONE(board)
    z.SetNet(board.FindNet(net))
    z.SetLayer(layer)
    z.SetIsRuleArea(False)
    z.SetAssignedPriority(priority)
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


def add_via(board, x, y, net):
    v = PCB_VIA(board)
    v.SetPosition(mm(x, y))
    v.SetDrill(FromMM(0.30))
    v.SetWidth(FromMM(0.60))
    v.SetNet(board.FindNet(net))
    board.Add(v)
    return v


def add_vias(board):
    """One via per axis-aligned cut, on the spur (and the VBAT hop)."""
    n = 0
    # Spurs are 2.20 mm tall on the south pad row. Three vias on a diagonal.
    # Driver-side F+B only (x < 104). The PO2_east underpass stays via-free.
    spur_vias = {
        "ADIO1": (82.55, 86.35),
        "ADIO3": (91.55, 95.35),
        "ADIO5": (100.55, 104.35),
        "ADIO7": (109.55, 113.35),
    }
    for net, (y0, y1) in spur_vias.items():
        for i, x in enumerate((91.2, 92.3, 93.4)):
            y = y0 + 0.45 + i * 0.55
            if y > y1 - 0.35:
                y = y1 - 0.40
            add_via(board, x, y, net)
            n += 1
    # Tie the VBAT F legs through the B.Cu hop under PWR_OUT2.
    for x, y in ((83.7, 116.5), (84.6, 117.6), (85.5, 118.7), (83.8, 139.2), (84.7, 140.3), (85.6, 141.4)):
        add_via(board, x, y, "VBAT")
        n += 1
    return n


def move_parts(board):
    moves = {
        "J3": (-14.0, 108.0),
        # West apron, clear of the HP F.Mask hatch and of J3.
        "C40": (-20.0, 90.0),
        "C20": (74.0, 88.0),
        # Off the ADIO5 spur (y=100.55–104.35).
        "R20": (96.5, 106.5),
    }
    for ref, y in ((r, y) for r, _n, y in DRIVERS):
        moves[ref] = (X_DRV, y)
    for ref, (x, y) in moves.items():
        fp = next(f for f in board.GetFootprints() if f.GetReference() == ref)
        old = tuple(round(v, 2) for v in xy(fp.GetPosition()))
        fp.SetPosition(mm(x, y))
        if ref.startswith("U1"):
            fp.SetOrientationDegrees(0)
        print(f"move {ref} {old} -> ({x:.2f}, {y:.2f}) rot {fp.GetOrientationDegrees():.0f}")


def measure(board):
    rows = []
    for z in [board.GetArea(i) for i in range(board.GetAreaCount())]:
        name = z.GetZoneName() if hasattr(z, "GetZoneName") else ""
        if not (name.startswith("A") or name.startswith("VBAT_drv") or name.startswith("PO")):
            continue
        if not z.IsFilled():
            rows.append((name, 0.0))
            continue
        bb = z.Outline().BBox()
        x0, y0 = ToMM(bb.GetLeft()), ToMM(bb.GetTop())
        x1, y1 = ToMM(bb.GetRight()), ToMM(bb.GetBottom())
        layer = z.GetLayer()
        wide = (x1 - x0) >= (y1 - y0)
        spans = []
        if wide:
            for i in range(1, 8):
                x = x0 + (x1 - x0) * i / 8
                ys = []
                y = y0 - 0.3
                while y <= y1 + 0.3:
                    if z.HitTestFilledArea(layer, mm(x, y)):
                        ys.append(y)
                    y += 0.10
                if ys:
                    spans.append(ys[-1] - ys[0] + 0.10)
        else:
            for i in range(1, 8):
                y = y0 + (y1 - y0) * i / 8
                xs = []
                x = x0 - 0.3
                while x <= x1 + 0.3:
                    if z.HitTestFilledArea(layer, mm(x, y)):
                        xs.append(x)
                    x += 0.10
                if xs:
                    spans.append(xs[-1] - xs[0] + 0.10)
        rows.append((name, min(spans) if spans else 0.0))
    return rows


def hit_pads(board):
    """Which ADIO/VBAT pads does the fill actually touch?"""
    zones = [board.GetArea(i) for i in range(board.GetAreaCount())]
    lines = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref not in {"J1", "U11", "U13", "U15", "U17", "U12", "U14"}:
            continue
        for pad in fp.Pads():
            net = pad.GetNetname()
            if net not in {"ADIO1", "ADIO3", "ADIO5", "ADIO7", "VBAT"} and not (net == "" ):
                continue
            if net == "" and ref == "J1":
                continue
            bb = pad.GetBoundingBox()
            cx = (ToMM(bb.GetLeft()) + ToMM(bb.GetRight())) / 2
            cy = (ToMM(bb.GetTop()) + ToMM(bb.GetBottom())) / 2
            touched = []
            for z in zones:
                if not z.IsFilled() or z.GetIsRuleArea():
                    continue
                if z.GetLayer() != F_Cu and not (pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH and z.GetLayer() == B_Cu):
                    if z.GetLayer() != F_Cu:
                        continue
                if z.HitTestFilledArea(z.GetLayer(), mm(cx, cy)):
                    touched.append(z.GetZoneName() or z.GetNetname())
            if net.startswith("ADIO") or (net == "VBAT" and ref.startswith("U")):
                lines.append(f"  {ref}.{pad.GetNumber():<3} {net or 'NONET':8} ({cx:.2f},{cy:.2f}) fill {touched}")
    return lines


def main():
    _load_pcbnew()
    build_zones()
    before = PCB.read_text()
    in1_before = before.count("In1.Cu")
    board = pcbnew.LoadBoard(str(PCB))
    move_parts(board)
    bad = audit(board)
    if bad:
        print(f"AUDIT FAIL {len(bad)}")
        for line in bad[:40]:
            print(" ", line)
        raise SystemExit(1)
    print("audit ok", len(ZONES), "zones")
    n_del = delete_conflicting(board)
    print("deleted conflicting copper", n_del)
    for net, layer, x0, y0, x1, y1, name, _flow in ZONES:
        pri = 2 if net == "VBAT" else 3
        add_zone(board, net, layer, (x0, y0, x1, y1), name, pri)
    nvia = add_vias(board)
    print("vias", nvia)
    print("filling...")
    ZONE_FILLER(board).Fill(board.Zones())
    for name, w in measure(board):
        if name.startswith("A") or name.startswith("VBAT_drv") or name.startswith("PO"):
            if name.startswith("PO") or name.startswith("A") or name.startswith("VBAT"):
                print(f"  fill {name:12} {w:.2f}")
    print("pad hits:")
    for line in hit_pads(board):
        print(line)
    tb = board.GetTitleBlock()
    tb.SetComment(
        0,
        "PowerCore PDM (pdmrazora) - Razor-class 174x202 - ADIO 8 A pours, exposed HP outs",
    )
    board.SetTitleBlock(tb)
    pcbnew.SaveBoard(str(PCB), board)
    text = PCB.read_text()
    text2 = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text2 = re.sub(r'\(generator_version "[^"]+"\)', '(generator_version "8.0")', text2, count=1)
    text2 = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text2)
    if text2 != text:
        PCB.write_text(text2)
    in1_after = PCB.read_text().count("In1.Cu")
    print(f"In1.Cu {in1_before} -> {in1_after}")


if __name__ == "__main__":
    import sys

    if "--even-audit" in sys.argv:
        from even_adio_fanout import main as even_main

        even_main()
    else:
        main()
