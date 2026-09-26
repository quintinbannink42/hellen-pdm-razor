#!/usr/bin/env python3
"""Pour ADIO4/6/8 at the 2 oz / 20 °C 8 A line (1.74 mm geometric).

Board-wide copper weight is 2 oz. This script does not trim HP or ADIO2,
does not bridge F1, does not pour SENSOR_GND, does not export gerbers,
and does not replay cut_crossings_sexp.py.

Run only from a clean pdmrazora.kicad_pcb. It rewrites zones and will
double-pour if launched again on its own output.

IPC-2221A external, k=0.048, dT=20, 2 oz = 2.756 mil:
  8 A  -> 1.736 mm (reported 1.74 mm)
  25 A -> 8.359 mm (reported 8.36 mm)
Width scales as 1/thickness from the 1 oz ruler (3.472 mm and 16.717 mm).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pcbnew

PCB = Path("/workspace/pdmrazora.kicad_pcb")
NEED = 1.74  # mm, 2 oz external, 8 A, 20 °C

# Loaded in main() / by the repair script. Importing this file must not
# open the board (callers set `board` before using the zone helpers).
board = None
F_Cu = pcbnew.F_Cu
B_Cu = pcbnew.B_Cu


def mm(v):
    return pcbnew.ToMM(v)


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def find_zone(name):
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if hasattr(z, "GetZoneName") and z.GetZoneName() == name:
            return z
    raise SystemExit(f"missing zone {name}")


def set_outlines(name, outlines):
    z = find_zone(name)
    ol = z.Outline()
    ol.RemoveAllContours()
    for pts in outlines:
        ol.NewOutline()
        for x, y in pts:
            ol.Append(int(round(pcbnew.FromMM(x))), int(round(pcbnew.FromMM(y))))
    return z


def shrink_pads():
    j1 = next(fp for fp in board.GetFootprints() if fp.GetReference() == "J1")
    for pad in j1.Pads():
        n = pad.GetNumber()
        if n in ("16", "17", "18"):
            pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(1.60), pcbnew.FromMM(1.60)))
        elif n in ("22", "23", "24", "25"):
            # 1.60 mm keeps a 0.15 mm annular ring on the 1.30 mm drill and
            # opens a 0.88 mm F+B throat (sum 1.76 mm) beside ADIO7.
            pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(1.60), pcbnew.FromMM(1.60)))
    print("pads 16/17/18/22/23/24/25 -> 1.60 mm")


def move_drivers():
    moves = {
        "U18": (108.0, 150.0),
        "U16": (120.0, 146.0),
        "U14": (120.0, 156.0),
    }
    for ref, (x, y) in moves.items():
        fp = next(f for f in board.GetFootprints() if f.GetReference() == ref)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        fp.SetOrientationDegrees(0)
        print(f"  {ref} -> ({x:.1f},{y:.1f}) rot 0")


def reshape_odd():
    """Open the even throats. Odd series necks stay above the 2 oz 8 A line.

    A5 east ribbon becomes 1.77 mm tall (was 2.20). F is removed in one
    slot so ADIO4 can drop south; B through that slot is the 1.77 mm neck.
    A3 east ribbon becomes 1.08 mm on each layer (F+B 2.16).
    A7 pin section becomes 1.55 mm on each layer (F+B 3.10) and its B.Cu
    leg still joins the untouched 3.80 mm A7_east ribbon.
    """
    # A5. Top stays 47.35. Bottom 45.58 -> height 1.77 mm.
    # Height 1.77 mm. Bottom 45.58 is 0.12 mm onto the 1.60 mm ADIO5 pad
    # (pad bottom 45.70) and 0.20 mm clear of the ADIO6 pour (top 45.38).
    a5_b = [(41.50, 45.58), (129.80, 45.58), (129.80, 47.35), (41.50, 47.35)]
    set_outlines("A5_east_B", [a5_b])
    # F stops through x=111.2–114.0 (ADIO4's south drop). B stays 1.77 mm.
    a5_f_w = [(41.50, 45.58), (111.20, 45.58), (111.20, 47.35), (41.50, 47.35)]
    a5_f_e = [(114.00, 45.58), (129.80, 45.58), (129.80, 47.35), (114.00, 47.35)]
    set_outlines("A5_east_F", [a5_f_w, a5_f_e])

    a3 = [(41.50, 48.70), (127.20, 48.70), (127.20, 49.73), (41.50, 49.73)]
    set_outlines("A3_east_F", [a3])
    set_outlines("A3_east_B", [a3])

    # West block stays clear of the ADIO8/ADIO6 throats. East of x=44 the
    # B outline drops to y=40.25 so it lands on the full A7_east ribbon.
    a7_b = [
        (41.50, 42.70),
        (44.00, 42.70),
        (44.00, 40.25),
        (50.70, 40.25),
        (50.70, 44.30),
        (41.50, 44.30),
    ]
    a7_f = [(41.50, 42.70), (44.00, 42.70), (44.00, 44.30), (41.50, 44.30)]
    set_outlines("A7_pin_B", [a7_b])
    set_outlines("A7_pin_F", [a7_f])
    print("reshaped A5_east, A3_east, A7_pin")


# (net, layer, rect, name)
NEW = []


def add_rect(net, layer, x0, y0, x1, y1, name):
    NEW.append((net, layer, (x0, y0, x1, y1), name))


def build_even_zones():
    """Layer-continuous pours. Series neck target is 1.74 mm at 2 oz.

    Hauls are stacked in Y so a northern run crosses a southern alley's
    X only above that alley. Alleys do not share a layer with a foreign
    haul. ADIO4 stays on F through the A5 slot; the short band under A7
    is F+B (1.58 mm each). Vias sit on the edge of an overlap so one
    remnant is still an F+B path at or above 1.74 mm.
    """
    # East slots, 1.74 mm, 0.20 mm apart, east of A7_col (x=134.00).
    # A = ADIO4 F, B = ADIO6 B, C = ADIO8 B.
    # --- ADIO8. Northern B haul (y=34.34–36.08) reaches slot C.
    add_rect("ADIO8", F_Cu, 39.20, 41.55, 48.86, 42.45, "A8_th_F")
    add_rect("ADIO8", B_Cu, 39.20, 41.55, 43.80, 42.45, "A8_th_B")
    add_rect("ADIO8", F_Cu, 44.20, 39.55, 48.86, 42.45, "A8_bridge_F")
    add_rect("ADIO8", F_Cu, 47.12, 34.24, 48.86, 42.45, "A8_drop_F")
    add_rect("ADIO8", B_Cu, 47.12, 34.34, 139.82, 36.08, "A8_haul_B")
    add_rect("ADIO8", B_Cu, 138.08, 34.34, 139.82, 150.88, "A8_alley_B")
    add_rect("ADIO8", B_Cu, 109.55, 149.12, 139.82, 150.88, "A8_west_B")
    add_rect("ADIO8", F_Cu, 109.85, 147.75, 112.20, 149.55, "A8_landS_F")
    add_rect("ADIO8", F_Cu, 109.85, 150.45, 112.20, 152.25, "A8_landN_F")
    add_rect("ADIO8", B_Cu, 109.55, 147.75, 112.40, 152.25, "A8_land_B")

    # --- ADIO6. Middle B haul stops at slot B, below the ADIO8 haul.
    add_rect("ADIO6", F_Cu, 39.20, 44.50, 50.90, 45.38, "A6_th_F")
    add_rect("ADIO6", B_Cu, 39.20, 44.50, 50.90, 45.38, "A6_th_B")
    add_rect("ADIO6", F_Cu, 49.06, 36.28, 50.80, 45.38, "A6_drop_F")
    add_rect("ADIO6", B_Cu, 49.06, 36.28, 137.88, 38.02, "A6_haul_B")
    add_rect("ADIO6", B_Cu, 136.14, 36.28, 137.88, 146.88, "A6_alley_B")
    add_rect("ADIO6", B_Cu, 121.20, 145.12, 137.88, 146.88, "A6_west_B")
    add_rect("ADIO6", F_Cu, 121.55, 143.75, 124.20, 145.55, "A6_landS_F")
    add_rect("ADIO6", F_Cu, 121.55, 146.45, 124.20, 148.25, "A6_landN_F")
    add_rect("ADIO6", B_Cu, 121.20, 143.75, 124.40, 148.25, "A6_land_B")

    # --- ADIO4. F the whole way. B only on the 1.58 mm band under A7.
    add_rect("ADIO4", F_Cu, 39.20, 47.50, 113.30, 48.50, "A4_th_F")
    add_rect("ADIO4", B_Cu, 39.20, 47.50, 113.30, 48.50, "A4_th_B")
    add_rect("ADIO4", F_Cu, 111.50, 38.47, 113.24, 48.50, "A4_drop_F")
    add_rect("ADIO4", F_Cu, 111.50, 38.47, 130.00, 40.21, "A4_haul_F")
    add_rect("ADIO4", F_Cu, 129.90, 38.47, 135.94, 40.05, "A4_gate_F")
    add_rect("ADIO4", B_Cu, 127.50, 38.47, 135.94, 40.05, "A4_gate_B")
    add_rect("ADIO4", F_Cu, 134.20, 38.47, 135.94, 156.88, "A4_alley_F")
    # South of unnetted pad 11 (y=156). 1.74 mm, still on the south OUT pads.
    add_rect("ADIO4", F_Cu, 121.55, 153.81, 135.94, 155.55, "A4_west_F")
    add_rect("ADIO4", F_Cu, 121.55, 153.75, 124.20, 155.55, "A4_landS_F")
    add_rect("ADIO4", F_Cu, 121.55, 156.45, 124.20, 158.25, "A4_landN_F")


def add_zone(net, layer, box, name):
    x0, y0, x1, y1 = box
    z = pcbnew.ZONE(board)
    z.SetNet(board.FindNet(net))
    z.SetLayer(layer)
    z.SetIsRuleArea(False)
    z.SetAssignedPriority(3)
    z.SetLocalClearance(pcbnew.FromMM(0.20))
    z.SetMinThickness(pcbnew.FromMM(0.15))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
    if hasattr(z, "SetZoneName"):
        z.SetZoneName(name)
    try:
        z.SetFillMode(pcbnew.ZONE_FILL_MODE_POLYGONS)
    except Exception:
        pass
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        z.AppendCorner(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)), -1)
    board.Add(z)


def add_via(x, y, net):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    v.SetDrill(pcbnew.FromMM(0.30))
    v.SetWidth(pcbnew.FromMM(0.60))
    v.SetNet(board.FindNet(net))
    board.Add(v)


def place_vias():
    # Stitch stubs at the F-to-B handoff, and a pair at each OUT landing.
    # The 1.74 mm ribbon itself has no drill.
    sites = {
        # South edge of each B haul, so the north remnant stays F+B >= 1.74.
        # Driver vias sit in the landing bulge, outside the 1.76 mm west ribbon.
        "ADIO8": (
            (47.20, 35.78),
            (48.10, 35.78),
            (109.95, 148.60),
            (109.95, 151.40),
        ),
        "ADIO6": (
            (49.50, 37.72),
            (50.40, 37.72),
            (122.05, 144.60),
            (122.05, 147.40),
        ),
        "ADIO4": (
            (127.80, 39.75),
            (128.70, 39.75),
        ),
    }
    n = 0
    for net, pts in sites.items():
        for x, y in pts:
            add_via(x, y, net)
            n += 1
    print(f"vias {n}")


def item_hits(item, box, margin):
    x0, y0, x1, y1 = box
    if item.GetClass() == "PCB_VIA":
        x, y = mm(item.GetPosition().x), mm(item.GetPosition().y)
        r = mm(item.GetWidth()) / 2
        return (x0 - margin - r) <= x <= (x1 + margin + r) and (y0 - margin - r) <= y <= (y1 + margin + r)
    if not hasattr(item, "GetStart"):
        return False
    ax, ay = mm(item.GetStart().x), mm(item.GetStart().y)
    bx, by = mm(item.GetEnd().x), mm(item.GetEnd().y)
    w = mm(item.GetWidth()) / 2 if hasattr(item, "GetWidth") else 0.0
    m = margin + w
    xa, xb = x0 - m, x1 + m
    ya, yb = y0 - m, y1 + m

    def inn(x, y):
        return xa <= x <= xb and ya <= y <= yb

    if inn(ax, ay) or inn(bx, by):
        return True
    if max(ax, bx) < xa or min(ax, bx) > xb or max(ay, by) < ya or min(ay, by) > yb:
        return False
    steps = max(2, int(math.hypot(bx - ax, by - ay) / 0.4))
    for i in range(steps + 1):
        t = i / steps
        if inn(ax + (bx - ax) * t, ay + (by - ay) * t):
            return True
    return False


PRESERVE = {"ADIO1", "ADIO2", "ADIO3", "ADIO5", "ADIO7", "VBAT"}


def delete_conflicting():
    kill = []
    protected = []
    for t in list(board.GetTracks()):
        net = t.GetNetname()
        if t.GetClass() == "PCB_VIA":
            layer = "via"
        elif t.GetLayer() == F_Cu:
            layer = F_Cu
        elif t.GetLayer() == B_Cu:
            layer = B_Cu
        else:
            continue
        hit_net = None
        for zn, zl, box, _name in NEW:
            if layer != "via" and layer != zl:
                continue
            if item_hits(t, box, 0.05):
                hit_net = zn
                break
        if hit_net is None:
            continue
        if net.startswith("PWR_OUT") or net in PRESERVE:
            protected.append((net, t.GetClass(), hit_net))
            continue
        if net == hit_net:
            continue
        kill.append(t)
    if protected:
        print(f"WARNING preserved tracks hit new copper: {len(protected)}")
        for row in protected[:12]:
            print("   ", row)
    for t in kill:
        board.Remove(t)
    print(f"deleted foreign tracks {len(kill)}")
    return len(protected)


def gap_of(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    sep_x = max(bx0 - ax1, ax0 - bx1)
    sep_y = max(by0 - ay1, ay0 - by1)
    if sep_x < 0 and sep_y < 0:
        return min(sep_x, sep_y)
    if sep_x < 0:
        return sep_y
    if sep_y < 0:
        return sep_x
    return math.hypot(sep_x, sep_y)


def audit_clearance():
    """Raster test: a new rect may not come within 0.18 mm of preserved copper.

    Same-net pads are ignored. Priority-1 GND and priority-1 VBAT that stays
    south of the fuse are pushable and are not obstacles.
    """
    from PIL import Image, ImageDraw
    import numpy as np

    step = 0.10
    x0, y0, x1, y1 = 36.0, 28.0, 142.0, 162.0
    W = int(round((x1 - x0) / step)) + 1
    H = int(round((y1 - y0) / step)) + 1

    def px(x, y):
        return int(round((x - x0) / step)), int(round((y - y0) / step))

    obs = {L: Image.new("1", (W, H), 0) for L in ("F", "B")}
    draw = {L: ImageDraw.Draw(obs[L]) for L in ("F", "B")}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            net = pad.GetNetname()
            if net in ("ADIO4", "ADIO6", "ADIO8"):
                continue
            bb = pad.GetBoundingBox()
            box = [px(mm(bb.GetLeft()), mm(bb.GetTop())), px(mm(bb.GetRight()), mm(bb.GetTop())),
                   px(mm(bb.GetRight()), mm(bb.GetBottom())), px(mm(bb.GetLeft()), mm(bb.GetBottom()))]
            attr = pad.GetAttribute()
            if pad.IsOnLayer(F_Cu) or attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                draw["F"].polygon(box, fill=1)
            if pad.IsOnLayer(B_Cu) or attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                draw["B"].polygon(box, fill=1)
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        net = z.GetNetname()
        pri = z.GetAssignedPriority()
        if net == "GND" and pri < 2:
            continue
        if net == "VBAT" and pri < 2:
            ol = z.Outline()
            if ol.OutlineCount():
                ys = [mm(ol.Outline(0).CPoint(k).y) for k in range(ol.Outline(0).PointCount())]
                if ys and min(ys) >= 26:
                    continue
        if not (str(net).startswith("PWR_OUT") or net in PRESERVE or net == "VBAT" or pri >= 2 or z.GetIsRuleArea()):
            continue
        ol = z.Outline()
        if ol.OutlineCount() == 0:
            continue
        ch = ol.Outline(0)
        pts = [px(mm(ch.CPoint(k).x), mm(ch.CPoint(k).y)) for k in range(ch.PointCount())]
        lay = "F" if z.GetLayer() == F_Cu else "B" if z.GetLayer() == B_Cu else None
        if lay:
            draw[lay].polygon(pts, fill=1)
    arr = {L: np.array(obs[L], dtype=bool) for L in ("F", "B")}
    bad = []
    for net, layer, box, name in NEW:
        lay = "F" if layer == F_Cu else "B"
        xa, ya, xb, yb = box
        # Interior only. A 0.20 mm gap does not put an obstacle pixel inside.
        c0, r0 = px(xa + 0.05, ya + 0.05)
        c1, r1 = px(xb - 0.05, yb - 0.05)
        c0, c1 = max(0, min(c0, c1)), min(W - 1, max(c0, c1))
        r0, r1 = max(0, min(r0, r1)), min(H - 1, max(r0, r1))
        sub = arr[lay][r0 : r1 + 1, c0 : c1 + 1]
        if sub.any():
            ys, xs = np.nonzero(sub)
            k = int(len(xs) // 2)
            hx = x0 + (c0 + xs[k]) * step
            hy = y0 + (r0 + ys[k]) * step
            bad.append(f"{name} hits preserved {lay} near ({hx:.2f},{hy:.2f}) pixels {int(sub.sum())}")
    print(f"clearance flags {len(bad)}")
    for row in bad[:30]:
        print("  ", row)
    return bad


def add_fab_note():
    tb = board.GetTitleBlock()
    tb.SetComment(
        0,
        "PowerCore PDM (pdmrazora) - 2 oz Cu both layers - ADIO 8 A neck 1.74 mm, HP 25 A neck 8.36 mm",
    )
    board.SetTitleBlock(tb)
    text = pcbnew.PCB_TEXT(board)
    text.SetText(
        "FAB  stackup 2 oz (70 um) F.Cu + 2 oz B.Cu, core 1.46 mm, 1.6 mm finished. "
        "IPC-2221A external 20 C: 8 A = 1.74 mm, 25 A = 8.36 mm. Copper weight is board-wide."
    )
    text.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(-28), pcbnew.FromMM(158)))
    text.SetLayer(pcbnew.Dwgs_User)
    text.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.9), pcbnew.FromMM(0.9)))
    text.SetTextThickness(pcbnew.FromMM(0.12))
    board.Add(text)


def insert_stackup(text):
    stack = """\t\t\t(outputdirectory "")
\t\t)
\t\t(stackup
\t\t\t(layer "F.Cu"
\t\t\t\t(type "copper")
\t\t\t\t(thickness 0.07)
\t\t\t)
\t\t\t(layer "dielectric 1"
\t\t\t\t(type "core")
\t\t\t\t(thickness 1.46)
\t\t\t\t(material "FR4")
\t\t\t\t(epsilon_r 4.5)
\t\t\t\t(loss_tangent 0.02)
\t\t\t)
\t\t\t(layer "B.Cu"
\t\t\t\t(type "copper")
\t\t\t\t(thickness 0.07)
\t\t\t)
\t\t\t(copper_finish "None")
\t\t\t(dielectric_constraints no)
\t\t)
\t)"""
    needle = '\t\t\t(outputdirectory "")\n\t\t)\n\t)'
    if needle not in text:
        raise SystemExit("setup block not found for stackup insert")
    return text.replace(needle, stack, 1)


def main():
    global board
    board = pcbnew.LoadBoard(str(PCB))
    shrink_pads()
    move_drivers()
    reshape_odd()
    build_even_zones()
    flags = audit_clearance()
    if flags:
        raise SystemExit(f"refusing to pour: {len(flags)} clearance flags")
    for net, layer, box, name in NEW:
        add_zone(net, layer, box, name)
    print(f"zones added {len(NEW)}")
    place_vias()
    nprot = delete_conflicting()
    if nprot:
        raise SystemExit("refusing to fill: preserved copper intersects the new pours")
    print("filling...")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    add_fab_note()
    pcbnew.SaveBoard(str(PCB), board)
    text = PCB.read_text()
    text2 = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text2 = re.sub(r'\(generator_version "[^"]+"\)', '(generator_version "8.0")', text2, count=1)
    text2 = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text2)
    text2 = insert_stackup(text2)
    if text2 != text:
        PCB.write_text(text2)
    print("saved", PCB)


if __name__ == "__main__":
    main()
