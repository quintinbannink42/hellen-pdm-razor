#!/usr/bin/env python3
"""Reconnect moved drivers U14/U16/U18 and even-channel sense pads.

Does not move pours, does not bridge F1, does not pour SENSOR_GND,
does not export gerbers, and does not replay cut_crossings_sexp.py.

VBAT branches are priority 2 on B.Cu, the same class as the existing
driver column (3.6 mm), not a new 25 A neck. Signal and sense are
0.20 mm exclusive lanes. The ADIO4 OUT landing stitch is priority 3
and stays east of the unnetted pad so the 1.76 mm alley is untouched.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import pcbnew

PCB = Path("/workspace/pdmrazora.kicad_pcb")
F_Cu = pcbnew.F_Cu
B_Cu = pcbnew.B_Cu
CLR = 0.20
VIA_D = 0.60
VIA_R = 0.30
BOARD = (-32.0, -40.0, 142.0, 162.0)  # Edge.Cuts


def mm(v):
    return pcbnew.ToMM(v)


def lay_of(item):
    if item.GetClass() == "PCB_VIA":
        return "via"
    L = int(item.GetLayer())
    if L == int(F_Cu):
        return "F"
    if L == int(B_Cu):
        return "B"
    return None


def ensure_net(board, name):
    ni = board.FindNet(name)
    if ni is not None and ni.GetNetCode() > 0:
        return ni
    raise SystemExit(f"missing net {name}")


def add_track(board, x1, y1, x2, y2, width, net, layer):
    if math.hypot(x2 - x1, y2 - y1) < 1e-6:
        return None
    tr = pcbnew.PCB_TRACK(board)
    tr.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
    tr.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x2), pcbnew.FromMM(y2)))
    tr.SetWidth(pcbnew.FromMM(width))
    tr.SetLayer(F_Cu if layer == "F" else B_Cu)
    tr.SetNet(ensure_net(board, net))
    board.Add(tr)
    return tr


def add_via(board, x, y, net, size=VIA_D):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    v.SetDrill(pcbnew.FromMM(0.30))
    v.SetWidth(pcbnew.FromMM(size))
    v.SetNet(ensure_net(board, net))
    board.Add(v)
    return v


def add_zone(board, net, layer, box, name, priority):
    x0, y0, x1, y1 = box
    z = pcbnew.ZONE(board)
    z.SetNet(ensure_net(board, net))
    z.SetLayer(F_Cu if layer == "F" else B_Cu)
    z.SetIsRuleArea(False)
    z.SetAssignedPriority(priority)
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
    return z


def dist_point_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def seg_seg_intersect(a, b, c, d):
    def cross(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    d1, d2 = cross(c, d, a), cross(c, d, b)
    d3, d4 = cross(a, b, c), cross(a, b, d)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def seg_seg_dist(a, b):
    if seg_seg_intersect(a[0], a[1], b[0], b[1]):
        return 0.0
    return min(
        dist_point_seg(a[0][0], a[0][1], b[0][0], b[0][1], b[1][0], b[1][1]),
        dist_point_seg(a[1][0], a[1][1], b[0][0], b[0][1], b[1][0], b[1][1]),
        dist_point_seg(b[0][0], b[0][1], a[0][0], a[0][1], a[1][0], a[1][1]),
        dist_point_seg(b[1][0], b[1][1], a[0][0], a[0][1], a[1][0], a[1][1]),
    )


def dist_point_rect(px, py, x0, y0, x1, y1):
    dx = max(x0 - px, 0.0, px - x1)
    dy = max(y0 - py, 0.0, py - y1)
    return math.hypot(dx, dy)


def seg_rect_dist(ax, ay, bx, by, x0, y0, x1, y1):
    # Inside or crossing the filled rect.
    if x0 <= ax <= x1 and y0 <= ay <= y1:
        return 0.0
    if x0 <= bx <= x1 and y0 <= by <= y1:
        return 0.0
    edges = (
        ((x0, y0), (x1, y0)),
        ((x1, y0), (x1, y1)),
        ((x1, y1), (x0, y1)),
        ((x0, y1), (x0, y0)),
    )
    best = min(dist_point_rect(ax, ay, x0, y0, x1, y1), dist_point_rect(bx, by, x0, y0, x1, y1))
    for e0, e1 in edges:
        best = min(best, seg_seg_dist(((ax, ay), (bx, by)), (e0, e1)))
    return best


def rect_rect_gap(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    sx = max(bx0 - ax1, ax0 - bx1)
    sy = max(by0 - ay1, ay0 - by1)
    if sx < 0 and sy < 0:
        return max(sx, sy)  # overlap, negative
    if sx < 0:
        return sy
    if sy < 0:
        return sx
    return math.hypot(sx, sy)


class World:
    def __init__(self, board):
        self.rects = []  # (layer, net, x0, y0, x1, y1, tag)
        self.segs = []  # (layer, net, x0, y0, x1, y1, half, tag)
        self.vias = []  # (net, x, y, r, tag)
        self._collect(board)

    def _collect(self, board):
        for i in range(board.GetAreaCount()):
            z = board.GetArea(i)
            if z.GetIsRuleArea():
                continue
            net = z.GetNetname() or ""
            pri = z.GetAssignedPriority()
            if (net == "GND" and pri < 2) or (net == "VBAT" and pri < 2):
                continue
            ol = z.Outline()
            if ol.OutlineCount() == 0:
                continue
            ch = ol.Outline(0)
            xs = [mm(ch.CPoint(k).x) for k in range(ch.PointCount())]
            ys = [mm(ch.CPoint(k).y) for k in range(ch.PointCount())]
            lay = "F" if int(z.GetLayer()) == int(F_Cu) else "B" if int(z.GetLayer()) == int(B_Cu) else None
            if lay is None:
                continue
            name = z.GetZoneName() if hasattr(z, "GetZoneName") else ""
            self.rects.append((lay, net, min(xs), min(ys), max(xs), max(ys), f"zone {net} {name}"))
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                net = pad.GetNetname() or ""
                bb = pad.GetBoundingBox()
                x0, y0 = mm(bb.GetLeft()), mm(bb.GetTop())
                x1, y1 = mm(bb.GetRight()), mm(bb.GetBottom())
                attr = pad.GetAttribute()
                tag = f"pad {fp.GetReference()}.{pad.GetNumber()} {net}"
                on_f = pad.IsOnLayer(F_Cu) or attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
                on_b = pad.IsOnLayer(B_Cu) or attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
                if on_f:
                    self.rects.append(("F", net, x0, y0, x1, y1, tag))
                if on_b:
                    self.rects.append(("B", net, x0, y0, x1, y1, tag))
        for t in board.GetTracks():
            net = t.GetNetname() or ""
            if t.GetClass() == "PCB_VIA":
                x, y = mm(t.GetPosition().x), mm(t.GetPosition().y)
                r = mm(t.GetWidth()) / 2
                self.vias.append((net, x, y, r, f"via {net}"))
            else:
                lay = lay_of(t)
                if lay is None:
                    continue
                ax, ay = mm(t.GetStart().x), mm(t.GetStart().y)
                bx, by = mm(t.GetEnd().x), mm(t.GetEnd().y)
                half = mm(t.GetWidth()) / 2
                self.segs.append((lay, net, ax, ay, bx, by, half, f"trk {net}"))

    def add_seg(self, lay, net, ax, ay, bx, by, half, tag):
        self.segs.append((lay, net, ax, ay, bx, by, half, tag))

    def add_via(self, net, x, y, tag, radius=VIA_R):
        self.vias.append((net, x, y, radius, tag))

    def add_rect(self, lay, net, box, tag):
        x0, y0, x1, y1 = box
        self.rects.append((lay, net, x0, y0, x1, y1, tag))


def same(net, other):
    return bool(net) and net == other


def check_edge_seg(ax, ay, bx, by, half, tag, bad):
    x0, y0, x1, y1 = BOARD
    inset = 0.50 + half
    for x, y in ((ax, ay), (bx, by)):
        if not (x0 + inset - 1e-6 <= x <= x1 - inset + 1e-6 and y0 + inset - 1e-6 <= y <= y1 - inset + 1e-6):
            bad.append(f"{tag} edge ({x:.2f},{y:.2f})")


def check_edge_via(x, y, radius, tag, bad):
    x0, y0, x1, y1 = BOARD
    inset = 0.50 + radius
    if not (x0 + inset <= x <= x1 - inset and y0 + inset <= y <= y1 - inset):
        bad.append(f"{tag} via edge ({x:.2f},{y:.2f})")


def audit_seg(world, lay, net, ax, ay, bx, by, width, tag, bad):
    half = width / 2
    check_edge_seg(ax, ay, bx, by, half, tag, bad)
    for rlay, rnet, x0, y0, x1, y1, rtag in world.rects:
        if rlay != lay or same(net, rnet):
            continue
        d = seg_rect_dist(ax, ay, bx, by, x0, y0, x1, y1)
        if d < half + CLR - 1e-3:
            bad.append(f"{tag} vs {rtag} dist {d:.3f} need {half+CLR:.2f}")
    for slay, snet, x0, y0, x1, y1, sh, stag in world.segs:
        if slay != lay or same(net, snet):
            continue
        d = seg_seg_dist(((ax, ay), (bx, by)), ((x0, y0), (x1, y1)))
        need = half + sh + CLR
        if d < need - 1e-3:
            bad.append(f"{tag} vs {stag} dist {d:.3f} need {need:.2f}")
    for vnet, vx, vy, vr, vtag in world.vias:
        if same(net, vnet):
            continue
        d = dist_point_seg(vx, vy, ax, ay, bx, by)
        need = half + vr + CLR
        if d < need - 1e-3:
            bad.append(f"{tag} vs {vtag} dist {d:.3f} need {need:.2f}")


def audit_via(world, net, x, y, radius, tag, bad):
    check_edge_via(x, y, radius, tag, bad)
    for lay in ("F", "B"):
        for rlay, rnet, x0, y0, x1, y1, rtag in world.rects:
            if rlay != lay or same(net, rnet):
                continue
            d = dist_point_rect(x, y, x0, y0, x1, y1)
            if d < radius + CLR - 1e-3:
                bad.append(f"{tag} vs {rtag} dist {d:.3f}")
        for slay, snet, x0, y0, x1, y1, sh, stag in world.segs:
            if slay != lay or same(net, snet):
                continue
            d = dist_point_seg(x, y, x0, y0, x1, y1)
            need = radius + sh + CLR
            if d < need - 1e-3:
                bad.append(f"{tag} vs {stag} dist {d:.3f} need {need:.2f}")
    for vnet, vx, vy, vr, vtag in world.vias:
        if same(net, vnet):
            continue
        d = math.hypot(x - vx, y - vy)
        # hole-to-hole is looser than copper; copper governs
        if d < radius + vr + CLR - 1e-3:
            bad.append(f"{tag} vs {vtag} dist {d:.3f}")


def audit_zone(world, lay, net, box, tag, bad):
    for rlay, rnet, x0, y0, x1, y1, rtag in world.rects:
        if rlay != lay or same(net, rnet):
            continue
        g = rect_rect_gap(box, (x0, y0, x1, y1))
        if g < CLR - 1e-3:
            bad.append(f"{tag} vs {rtag} gap {g:.3f}")
    x0, y0, x1, y1 = box
    # vias of other nets inside or too close
    for vnet, vx, vy, vr, vtag in world.vias:
        if same(net, vnet):
            continue
        d = dist_point_rect(vx, vy, x0, y0, x1, y1)
        if d < vr + CLR - 1e-3:
            bad.append(f"{tag} vs {vtag} dist {d:.3f}")


def poly(world, net, lay, width, pts, tag, bad, commit):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if math.hypot(x2 - x1, y2 - y1) < 1e-6:
            continue
        piece = f"{tag} {lay} ({x1:.2f},{y1:.2f})-({x2:.2f},{y2:.2f})"
        before = len(bad)
        audit_seg(world, lay, net, x1, y1, x2, y2, width, piece, bad)
        if commit and len(bad) == before:
            world.add_seg(lay, net, x1, y1, x2, y2, width / 2, piece)


def via(world, net, x, y, tag, bad, commit, radius=VIA_R):
    before = len(bad)
    audit_via(world, net, x, y, radius, tag, bad)
    if commit and len(bad) == before:
        world.add_via(net, x, y, tag, radius)


SPUR_TRIM = ("A1_spur_Fw", "A3_spur_Fw", "A5_spur_Fw", "A7_spur_Fw")
# East tip was 104.25, 0.25 mm from PWR_OUT2 at x=104.50. Pulling it to
# 102.20 opens a 2.30 mm F slot. Spur height stays 3.80 mm, so the odd
# series necks (east / low ribbons) do not move. The west tip stays put:
# the odd OUT pads already seal that side.
SPUR_EAST = 102.20


def trim_odd_spur_tips(board):
    """Open an F slot between the odd spur tips and the PWR_OUT2 pour."""
    n = 0
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        name = z.GetZoneName() if hasattr(z, "GetZoneName") else ""
        if name not in SPUR_TRIM or int(z.GetLayer()) != int(F_Cu):
            continue
        ch = z.Outline().Outline(0)
        for k in range(ch.PointCount()):
            p = ch.CPoint(k)
            if mm(p.x) > 103.0:
                ch.SetPoint(k, pcbnew.VECTOR2I(pcbnew.FromMM(SPUR_EAST), p.y))
        n += 1
    if n != 4:
        raise SystemExit(f"expected to trim 4 odd spur tips, got {n}")
    print(f"trimmed F spur east tips {n} to x={SPUR_EAST}")


def build_routes():
    """Return (zones, vias, polylines).

    zones: (net, lay, box, name, pri)
    vias: (net, x, y, tag)
    polylines: (net, lay, width, [points], tag)
    """
    zones = [
        # Priority-2 B.Cu branches off the existing 3.6 mm driver column.
        # U14 goes around the ADIO8 B ribbon by extending the U18 column
        # past it, then east. The alley at x=136-140 is not crossed.
        # Bar stops at the U18 column. U16 is fed by a link below the bar so
        # an ADIO8 sense track can pass east of U18 and west of U16.
        # Bar stops on the U18 column, clear of ADIO2 at y=135.10.
        # U16 column is narrowed to x=120.20 so a sense track fits between
        # it and the ADIO6 west ribbon (x=121.20).
        ("VBAT", "B", (83.00, 128.40, 109.00, 134.70), "VBAT_se_bar", 2),
        ("VBAT", "B", (106.85, 134.20, 108.70, 153.15), "VBAT_u18", 2),
        ("VBAT", "B", (108.20, 142.40, 120.40, 143.40), "VBAT_u16_link", 2),
        ("VBAT", "B", (118.90, 143.10, 120.20, 148.05), "VBAT_u16", 2),
        ("VBAT", "B", (106.70, 152.45, 121.20, 153.40), "VBAT_u14_link", 2),
        ("VBAT", "B", (118.90, 152.45, 120.70, 157.40), "VBAT_u14", 2),
        ("ADIO4", "F", (123.80, 155.15, 125.55, 156.85), "A4_stitch", 3),
    ]
    # (net, x, y, tag, via diameter)
    vias = [
        ("VBAT", 107.40, 149.20, "via VBAT U18a", 0.60),
        ("VBAT", 107.40, 150.70, "via VBAT U18b", 0.60),
        ("VBAT", 119.55, 144.55, "via VBAT U16a", 0.60),
        ("VBAT", 119.55, 145.70, "via VBAT U16b", 0.60),
        ("VBAT", 119.55, 155.90, "via VBAT U14a", 0.60),
        ("VBAT", 119.55, 156.75, "via VBAT U14b", 0.60),
        ("GND", 103.55, 147.95, "via GND U18", 0.60),
        ("GND", 115.30, 143.95, "via GND U16", 0.60),
        ("GND", 115.30, 153.95, "via GND U14", 0.60),
    ]
    W = 0.20
    WN = 0.15  # parallel F margin, so a 0.50 via on the next lane still clears
    polys = []

    def P(net, lay, pts, tag, width=W):
        polys.append((net, lay, width, pts, tag))

    P("GND", "F", [(105.15, 148.05), (103.55, 147.95)], "gnd U18")
    P("GND", "F", [(117.15, 144.05), (115.30, 143.95)], "gnd U16")
    P("GND", "F", [(117.15, 154.05), (115.30, 153.95)], "gnd U14")

    # East-to-west verticals match north-to-south streets and west-to-east lanes.
    # Drop x / bus y follow how far north the net turns beside M1000.
    # Lanes pitch 0.55. Bus y pitch 0.60. Signal vias are 0.50 mm.
    spec = [
        # net, pad2, pad3 or None, vert x, escape y, street, lane, bus, drop, stub
        # Lanes pitch 0.55 and the east via sits on the copper-edge inset
        # (0.50 + 0.25 = 0.75 → x = 141.25).
        ("IN_O2S", (117.16, 156.00), None, 115.80, 156.00, 158.55, 138.50, -39.10, 19.05, None),
        ("OUT_PWM8", (117.15, 154.70), (117.15, 155.35), 115.10, 154.70, 159.05, 139.05, -37.90, 18.40, "pwm"),
        # South pad takes the eastern vertical so its exit does not cross the
        # northern vertical. That net also takes the northern street, and the
        # southern street takes the eastern lane.
        ("OUT_IO6", (117.15, 144.70), (117.15, 145.35), 113.70, 144.70, 160.05, 140.15, -39.10, 17.15, (15.55, 34.40, 14.80)),
        ("IN_RES1", (117.16, 146.00), None, 114.40, 146.00, 159.55, 139.60, -36.70, 19.65, None),
        ("OUT_IO8", (105.15, 148.70), (105.15, 149.35), 102.05, 148.70, 161.05, 141.25, -38.50, 17.75, (15.55, 44.80, 14.80)),
        ("IN_RES3", (105.16, 150.00), None, 102.70, 150.00, 160.55, 140.70, -36.10, 20.25, None),
    ]
    # Fix bus/drop: the tuple above mixed them. Set explicitly.
    # drop west->east and bus north->south: IO6, IO8, PWM8, O2S, RES1, RES3
    bus = {
        "OUT_IO6": (-39.10, 17.15),
        "OUT_IO8": (-38.50, 17.75),
        "OUT_PWM8": (-37.90, 18.40),
        "IN_O2S": (-37.30, 19.05),
        "IN_RES1": (-36.70, 19.65),
        "IN_RES3": (-36.10, 20.25),
    }
    is_y = {"IN_O2S": (68.30, -4.40), "IN_RES1": (68.90, -5.60), "IN_RES3": (69.50, -6.80)}

    for net, pad, pad3, vx, ey, street, lane, _b, _d, stub in spec:
        by, drop = bus[net]
        if pad3:
            P(net, "F", [pad, pad3], f"tie {net}")
        P(net, "F", [pad, (vx, ey), (vx, street), (lane, street)], f"{net} to lane")
        P(net, "F", [(lane, street), (lane, by)], f"{net} north", width=WN)
        vias.append((net, lane, by, f"via {net} bus", 0.50))
        if net in is_y:
            sy, sx = is_y[net]
            P(net, "B", [(lane, by), (drop, by), (drop, sy), (sx, sy), (sx, 66.40)], f"{net} to stub")
        elif net == "OUT_PWM8":
            P(net, "B", [(lane, by), (drop, by), (drop, 62.75), (14.80, 62.75)], f"{net} to pad")
            vias.append((net, 14.80, 62.75, "via PWM8 pad", 0.50))
            P(net, "F", [(14.80, 62.75), (14.60, 62.75), (14.60, 49.60), (14.00, 49.60)], f"{net} pad", width=0.18)
        else:
            vx2, vy2, xstub = stub
            P(net, "B", [(lane, by), (drop, by), (drop, vy2), (vx2, vy2)], f"{net} to stub")
            vias.append((net, vx2, vy2, f"via {net} stub", 0.50))
            P(net, "F", [(vx2, vy2), (xstub, vy2)], f"{net} stub")

    # Sense, 0.15 mm. The F slot (centers 102.65 / 103.25 / 103.85) is the
    # trimmed gap between spur tips x=102.20 and PWR_OUT2 x=104.50.
    # Only two tracks fit the pinch under IN_O2S2 (y=62.80) and above U2.
    # ADIO6 crosses that pinch on B. Alleys: ADIO4 vias back to F west of
    # the 1.76 mm alley; ADIO6 ends in the B alley; ADIO8 enters south of
    # the ADIO6 ribbon.
    # 0.12 mm so two tracks fit the 0.38 mm pinch between the IN_O2S2 via
    # and U2. Sense current does not use the 8 A neck.
    WS = 0.12
    P("ADIO4", "F", [
        (78.83, 56.20), (78.83, 57.40), (93.60, 57.40), (93.60, 63.38),
        (87.05, 63.38), (87.05, 79.20), (102.65, 79.20), (102.65, 116.40),
    ], "sense R204", width=WS)
    vias.append(("ADIO4", 102.65, 116.40, "via R204", 0.50))
    P("ADIO4", "B", [(102.65, 116.40), (133.30, 116.40)], "sense R204 B", width=WS)
    vias.append(("ADIO4", 133.30, 116.40, "via R204 alley", 0.50))
    P("ADIO4", "F", [(133.30, 116.40), (134.70, 116.40)], "sense R204 alley", width=WS)

    P("ADIO6", "F", [(86.83, 56.20), (86.83, 56.60)], "sense R206 drop", width=WS)
    vias.append(("ADIO6", 86.83, 56.60, "via R206 down", 0.50))
    P("ADIO6", "B", [
        (86.83, 56.60), (88.20, 56.60), (88.20, 60.80), (89.40, 60.80),
        (89.40, 77.20), (97.80, 77.20),         (97.80, 78.60), (99.80, 78.60),
    ], "sense R206 B", width=WS)
    vias.append(("ADIO6", 99.80, 78.60, "via R206 up", 0.50))
    P("ADIO6", "F", [
        (99.80, 78.60), (103.25, 78.60), (103.25, 117.20),
    ], "sense R206 slot", width=WS)
    vias.append(("ADIO6", 103.25, 117.20, "via R206 alley", 0.50))
    P("ADIO6", "B", [(103.25, 117.20), (136.70, 117.20)], "sense R206 alley", width=WS)

    P("ADIO8", "F", [
        (94.83, 56.20), (94.83, 58.00), (94.20, 58.00), (94.20, 63.70),
        (87.45, 63.70),         (87.45, 76.60), (95.50, 76.60), (95.50, 78.00),
        (104.05, 78.00), (104.05, 118.40),
    ], "sense R208", width=WS)
    vias.append(("ADIO8", 104.05, 118.40, "via R208", 0.50))
    # East of the narrowed U16 column (ends x=120.20), below ADIO6's ribbon,
    # then west into A8_land_B.
    P("ADIO8", "B", [
        (104.05, 118.40), (120.70, 118.40), (120.70, 148.60), (112.00, 148.60),
    ], "sense R208 B", width=WS)
    return zones, vias, polys



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
    if "(stackup" in text:
        return text
    if needle not in text:
        raise SystemExit("setup block not found for stackup insert")
    return text.replace(needle, stack, 1)


def normalize(path: Path):
    text = path.read_text()
    text = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text = re.sub(r'\(generator_version "[^"]+"\)', '(generator_version "8.0")', text, count=1)
    text = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text)
    text = insert_stackup(text)
    path.write_text(text)


def filled_area(board, net):
    area = 0.0
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetNetname() != net or z.GetIsRuleArea():
            continue
        polys = z.GetFilledPolysList(z.GetLayer())
        try:
            area += polys.Area()
        except Exception:
            # nm^2 via shoelace on outlines
            for oi in range(polys.OutlineCount()):
                ol = polys.Outline(oi)
                pts = [(ol.CPoint(k).x, ol.CPoint(k).y) for k in range(ol.PointCount())]
                s = 0.0
                for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
                    s += x1 * y2 - x2 * y1
                area += abs(s) * 0.5
    # pcbnew Area() is in nm^2. Convert to mm^2.
    return area / 1e12


def cut_width(board, net, layer, axis, at, lo, hi, step=0.02):
    """Longest filled run across one cut. axis 'x' cuts vertically at x=at."""
    spans = []
    inside = False
    start = None
    t = lo
    while t <= hi + 1e-9:
        hit = False
        for i in range(board.GetAreaCount()):
            z = board.GetArea(i)
            if z.GetNetname() != net or int(z.GetLayer()) != int(layer) or z.GetIsRuleArea():
                continue
            polys = z.GetFilledPolysList(layer)
            if axis == "x":
                pt = pcbnew.VECTOR2I(pcbnew.FromMM(at), pcbnew.FromMM(t))
            else:
                pt = pcbnew.VECTOR2I(pcbnew.FromMM(t), pcbnew.FromMM(at))
            if polys.Contains(pt):
                hit = True
                break
        if hit and not inside:
            inside = True
            start = t
        elif not hit and inside:
            spans.append(t - start)
            inside = False
        t += step
    if inside:
        spans.append(t - start)
    return max(spans) if spans else 0.0


def neck_table(board):
    """Short filled runs at the documented series sections."""
    rows = []
    # (name, net, samples: list of (layer, axis, at, lo, hi) summed)
    specs = [
        ("ADIO1", "ADIO1", [("F", "x", 70.0, 49.94, 51.80), ("B", "x", 70.0, 49.94, 51.80)]),
        ("ADIO2", "ADIO2", [("F", "y", 140.0, 86.5, 92.5), ("B", "y", 140.0, 86.5, 92.5)]),
        ("ADIO3", "ADIO3", [("F", "y", 80.0, 41.4, 43.6), ("B", "y", 80.0, 41.4, 43.6)]),
        ("ADIO4 alley", "ADIO4", [("F", "y", 100.0, 133.9, 136.2)]),
        ("ADIO4 throat", "ADIO4", [("F", "x", 50.0, 47.3, 48.7), ("B", "x", 50.0, 47.3, 48.7)]),
        ("ADIO5", "ADIO5", [("B", "y", 80.0, 111.0, 114.2)]),
        ("ADIO6 alley", "ADIO6", [("B", "y", 100.0, 135.9, 138.1)]),
        ("ADIO6 throat", "ADIO6", [("F", "x", 45.0, 44.3, 45.6), ("B", "x", 45.0, 44.3, 45.6)]),
        ("ADIO7", "ADIO7", [("B", "y", 80.0, 44.2, 48.2)]),
        ("ADIO8 alley", "ADIO8", [("B", "y", 100.0, 137.8, 140.1)]),
        ("ADIO8 throat", "ADIO8", [("F", "x", 42.0, 41.4, 42.6), ("B", "x", 42.0, 41.4, 42.6)]),
        ("PWR_OUT1", "PWR_OUT1", [("F", "x", 55.0, 102.0, 120.0)]),
        ("PWR_OUT2", "PWR_OUT2", [("F", "x", 80.0, 120.0, 138.0)]),
        ("PWR_OUT3", "PWR_OUT3", [("F", "y", 10.0, 16.0, 40.0)]),
        ("PWR_OUT4", "PWR_OUT4", [("F", "y", 10.0, 38.0, 56.0), ("B", "y", 10.0, 38.0, 56.0)]),
    ]
    for name, net, samples in specs:
        total = 0.0
        bits = []
        for layer_name, axis, at, lo, hi in samples:
            layer = F_Cu if layer_name == "F" else B_Cu
            w = cut_width(board, net, layer, axis, at, lo, hi)
            bits.append(f"{layer_name} {w:.2f}")
            total += w
        rows.append((name, total, ", ".join(bits)))
    return rows


def main():
    check_only = "--check" in sys.argv
    board = pcbnew.LoadBoard(str(PCB))
    trim_odd_spur_tips(board)
    world = World(board)
    zones, vias, polys = build_routes()
    bad = []
    # Zones first so later tracks can terminate in them (same net).
    for net, lay, box, name, pri in zones:
        audit_zone(world, lay, net, box, f"zone {name}", bad)
        if not any(b.startswith(f"zone {name} ") for b in bad[-8:]):
            world.add_rect(lay, net, box, f"zone {net} {name}")
    # Commit geometry into the world only when the piece itself is clean,
    # so one bad segment does not poison the rest of the report.
    for net, x, y, tag, size in vias:
        via(world, net, x, y, tag, bad, commit=True, radius=size / 2)
    for net, lay, width, pts, tag in polys:
        poly(world, net, lay, width, pts, tag, bad, commit=True)
    print(f"clearance flags {len(bad)}")
    for row in bad[:120]:
        print(" ", row)
    if bad:
        raise SystemExit(f"refusing to edit: {len(bad)} clearance flags")
    if check_only:
        print("check ok")
        return

    for net, lay, box, name, pri in zones:
        add_zone(board, net, lay, box, name, pri)
    for net, x, y, _tag, size in vias:
        add_via(board, x, y, net, size)
    for net, lay, width, pts, _tag in polys:
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            add_track(board, x1, y1, x2, y2, width, net, lay)
    print("filling...")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(PCB), board)
    normalize(PCB)
    print("saved", PCB)
    filled = pcbnew.LoadBoard(str(PCB))
    print("neck table (filled mm)")
    for name, total, bits in neck_table(filled):
        print(f"  {name:16} {total:6.2f}  {bits}")


if __name__ == "__main__":
    main()
