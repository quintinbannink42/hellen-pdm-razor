#!/usr/bin/env python3
"""Close leftover rats on the 2 oz board without narrowing series necks.

Already applied to pdmrazora.kicad_pcb. Re-running main() duplicates the
ADIO5 sliver and the EN ties. Does not bridge F1, does not pour
SENSOR_GND, does not move footprints, does not edit ADIO2 or the HP
outlines, and does not replay cut_crossings_sexp.py.

ADIO5's B slot and ADIO8's F drop are widened only into empty copper,
enough for the filled reading to clear 1.74 mm.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pcbnew

PCB = Path("/workspace/pdmrazora.kicad_pcb")
F_Cu = pcbnew.F_Cu
B_Cu = pcbnew.B_Cu
CLR = 0.20
EDGE = (-32.0, -40.0, 142.0, 162.0)
# Open fuse body. VBAT must not cross this band.
FUSE_Y0, FUSE_Y1 = 17.0, 23.2
FUSE_X0, FUSE_X1 = 96.0, 104.0


def mm(v):
    return pcbnew.ToMM(v)


def lay_name(layer):
    if int(layer) == int(F_Cu):
        return "F"
    if int(layer) == int(B_Cu):
        return "B"
    return None


def ensure_net(board, name):
    ni = board.FindNet(name)
    if ni is None or ni.GetNetCode() <= 0:
        raise SystemExit(f"missing net {name}")
    return ni


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


def add_via(board, x, y, net, size=0.50, drill=0.30):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    v.SetDrill(pcbnew.FromMM(drill))
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


def seg_seg_dist(a, b):
    def cross(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    a0, a1 = a
    b0, b1 = b
    d1, d2 = cross(b0, b1, a0), cross(b0, b1, a1)
    d3, d4 = cross(a0, a1, b0), cross(a0, a1, b1)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return 0.0
    return min(
        dist_point_seg(a0[0], a0[1], b0[0], b0[1], b1[0], b1[1]),
        dist_point_seg(a1[0], a1[1], b0[0], b0[1], b1[0], b1[1]),
        dist_point_seg(b0[0], b0[1], a0[0], a0[1], a1[0], a1[1]),
        dist_point_seg(b1[0], b1[1], a0[0], a0[1], a1[0], a1[1]),
    )


def dist_point_rect(px, py, x0, y0, x1, y1):
    dx = max(x0 - px, 0.0, px - x1)
    dy = max(y0 - py, 0.0, py - y1)
    return math.hypot(dx, dy)


def seg_rect_dist(ax, ay, bx, by, x0, y0, x1, y1):
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


class Obs:
    """Foreign copper the new track must clear. Same-net copper is ignored."""

    def __init__(self, board):
        self.zones = []  # layer, net, bbox, polys, clr
        self.pads = []
        self.segs = []
        self.vias = []
        self.holes = []
        for i in range(board.GetAreaCount()):
            z = board.GetArea(i)
            if z.GetIsRuleArea():
                continue
            lay = lay_name(z.GetLayer())
            if lay is None:
                continue
            try:
                polys = z.GetFilledPolysList(z.GetLayer())
            except Exception:
                continue
            bb = z.GetBoundingBox()
            box = (mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))
            self.zones.append((lay, z.GetNetname() or "", box, polys, mm(z.GetLocalClearance()) or CLR))
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                net = pad.GetNetname() or ""
                bb = pad.GetBoundingBox()
                box = (mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))
                attr = pad.GetAttribute()
                pth = attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
                if pad.IsOnLayer(F_Cu) or pth:
                    self.pads.append(("F", net, box, f"{fp.GetReference()}.{pad.GetNumber()}"))
                if pad.IsOnLayer(B_Cu) or pth:
                    self.pads.append(("B", net, box, f"{fp.GetReference()}.{pad.GetNumber()}"))
                drill = pad.GetDrillSize()
                dr = max(mm(drill.x), mm(drill.y)) / 2
                if dr > 0.05:
                    p = pad.GetPosition()
                    self.holes.append((mm(p.x), mm(p.y), dr))
        for t in board.GetTracks():
            net = t.GetNetname() or ""
            if t.GetClass() == "PCB_VIA":
                x, y = mm(t.GetX()), mm(t.GetY())
                r = mm(t.GetWidth()) / 2
                self.vias.append((net, x, y, r))
                self.holes.append((x, y, mm(t.GetDrillValue()) / 2))
            else:
                lay = lay_name(t.GetLayer())
                if lay is None:
                    continue
                self.segs.append(
                    (
                        lay,
                        net,
                        mm(t.GetStart().x),
                        mm(t.GetStart().y),
                        mm(t.GetEnd().x),
                        mm(t.GetEnd().y),
                        mm(t.GetWidth()) / 2,
                    )
                )

    def edge_ok(self, x, y, half):
        x0, y0, x1, y1 = EDGE
        inset = 0.50 + half
        return x0 + inset <= x <= x1 - inset and y0 + inset <= y <= y1 - inset

    def fuse_blocks(self, net, x, y):
        return net == "VBAT" and FUSE_X0 <= x <= FUSE_X1 and FUSE_Y0 <= y <= FUSE_Y1

    def seg_ok(self, net, lay, x1, y1, x2, y2, width):
        half = width / 2
        if not self.edge_ok(x1, y1, half) or not self.edge_ok(x2, y2, half):
            return False
        if self.fuse_blocks(net, x1, y1) or self.fuse_blocks(net, x2, y2):
            return False
        # Sample the fuse rectangle so a long segment cannot slip through.
        steps = max(1, int(math.hypot(x2 - x1, y2 - y1) / 0.4))
        for i in range(steps + 1):
            t = i / steps
            if self.fuse_blocks(net, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t):
                return False
        need_pad = half + CLR
        for play, pnet, box, _tag in self.pads:
            if play != lay or pnet == net:
                continue
            if seg_rect_dist(x1, y1, x2, y2, *box) < need_pad - 1e-3:
                return False
        for slay, snet, ax, ay, bx, by, sh in self.segs:
            if slay != lay or snet == net:
                continue
            if seg_seg_dist(((x1, y1), (x2, y2)), ((ax, ay), (bx, by))) < half + sh + CLR - 1e-3:
                return False
        for vnet, vx, vy, vr in self.vias:
            if vnet == net:
                continue
            if dist_point_seg(vx, vy, x1, y1, x2, y2) < half + vr + CLR - 1e-3:
                return False
        seg = pcbnew.SEG(
            pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)),
            pcbnew.VECTOR2I(pcbnew.FromMM(x2), pcbnew.FromMM(y2)),
        )
        mx0, my0 = min(x1, x2) - 2, min(y1, y2) - 2
        mx1, my1 = max(x1, x2) + 2, max(y1, y2) + 2
        for zlay, znet, box, polys, zclr in self.zones:
            if zlay != lay or znet == net:
                continue
            if box[2] < mx0 or box[0] > mx1 or box[3] < my0 or box[1] > my1:
                continue
            gap = half + max(CLR, zclr)
            if polys.Collide(seg, pcbnew.FromMM(gap)):
                return False
        return True

    def via_ok(self, net, x, y, radius=0.25, drill_r=0.15):
        if not self.edge_ok(x, y, radius):
            return False
        if self.fuse_blocks(net, x, y):
            return False
        for hx, hy, hr in self.holes:
            if math.hypot(x - hx, y - hy) < drill_r + hr + 0.25 - 1e-3:
                return False
        for lay in ("F", "B"):
            for play, pnet, box, _tag in self.pads:
                if play != lay or pnet == net:
                    continue
                if dist_point_rect(x, y, *box) < radius + CLR - 1e-3:
                    return False
            for slay, snet, ax, ay, bx, by, sh in self.segs:
                if slay != lay or snet == net:
                    continue
                if dist_point_seg(x, y, ax, ay, bx, by) < radius + sh + CLR - 1e-3:
                    return False
            for zlay, znet, box, polys, zclr in self.zones:
                if zlay != lay or znet == net:
                    continue
                if dist_point_rect(x, y, *box) > radius + max(CLR, zclr) + 1.0:
                    continue
                pt = pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
                if polys.Collide(pt, pcbnew.FromMM(radius + max(CLR, zclr))):
                    return False
        for vnet, vx, vy, vr in self.vias:
            if vnet == net:
                continue
            if math.hypot(x - vx, y - vy) < radius + vr + CLR - 1e-3:
                return False
        return True

    def note_track(self, net, lay, x1, y1, x2, y2, width):
        self.segs.append((lay, net, x1, y1, x2, y2, width / 2))

    def note_via(self, net, x, y, radius=0.25, drill_r=0.15):
        self.vias.append((net, x, y, radius))
        self.holes.append((x, y, drill_r))


def cut_spans(board, net, layer, axis, at, lo, hi, step=0.01):
    spans = []
    inside = False
    start = None
    t = lo
    while t <= hi + 1e-9:
        if axis == "x":
            pt = pcbnew.VECTOR2I(pcbnew.FromMM(at), pcbnew.FromMM(t))
        else:
            pt = pcbnew.VECTOR2I(pcbnew.FromMM(t), pcbnew.FromMM(at))
        hit = False
        for i in range(board.GetAreaCount()):
            z = board.GetArea(i)
            if z.GetNetname() != net or int(z.GetLayer()) != int(layer) or z.GetIsRuleArea():
                continue
            try:
                if z.GetFilledPolysList(layer).Contains(pt):
                    hit = True
                    break
            except Exception:
                pass
        if hit and not inside:
            inside = True
            start = t
        elif not hit and inside:
            spans.append(t - start)
            inside = False
        t += step
    if inside:
        spans.append((t - step) - start)
    return max(spans) if spans else 0.0


def neck_report(board):
    """Filled widths at the series cuts. ADIO5/8 use the pinch, not a pad."""
    rows = {}

    def put(name, total):
        rows[name] = total

    put("ADIO1", cut_spans(board, "ADIO1", F_Cu, "x", 70.0, 48.0, 54.0) + cut_spans(board, "ADIO1", B_Cu, "x", 70.0, 48.0, 54.0))
    # ADIO2's 4.53 mm corridor is not an F+B sum at y=140 (that cut reads ~9.6).
    put("ADIO3", cut_spans(board, "ADIO3", F_Cu, "x", 80.0, 38.0, 50.0) + cut_spans(board, "ADIO3", B_Cu, "x", 80.0, 38.0, 50.0))
    put("ADIO4_alley", cut_spans(board, "ADIO4", F_Cu, "y", 100.0, 133.5, 136.5))
    put("ADIO4_drop", cut_spans(board, "ADIO4", F_Cu, "y", 42.0, 110.5, 114.5))
    put(
        "ADIO4_throat",
        cut_spans(board, "ADIO4", F_Cu, "x", 50.0, 47.2, 48.8) + cut_spans(board, "ADIO4", B_Cu, "x", 50.0, 47.2, 48.8),
    )
    # B only through the F slot. Minimum along the slot is the series neck.
    a5 = 99.0
    x = 111.05
    while x <= 113.35:
        a5 = min(a5, cut_spans(board, "ADIO5", B_Cu, "x", x, 44.8, 48.4))
        x = round(x + 0.1, 2)
    put("ADIO5_slot", a5)
    put("ADIO6_alley", cut_spans(board, "ADIO6", B_Cu, "y", 100.0, 135.5, 138.5))
    put(
        "ADIO6_throat",
        cut_spans(board, "ADIO6", F_Cu, "x", 45.0, 44.0, 46.0) + cut_spans(board, "ADIO6", B_Cu, "x", 45.0, 44.0, 46.0),
    )
    put("ADIO7", cut_spans(board, "ADIO7", B_Cu, "x", 100.0, 38.0, 50.0))
    put("ADIO8_alley", cut_spans(board, "ADIO8", B_Cu, "y", 100.0, 137.5, 140.5))
    a8 = 99.0
    y = 34.30
    while y <= 39.80:
        # Narrow drop only; the bridge above y~40 is several mm wide.
        w = cut_spans(board, "ADIO8", F_Cu, "y", y, 46.5, 49.5)
        if 0.5 < w < 3.0:
            a8 = min(a8, w)
        y = round(y + 0.1, 2)
    put("ADIO8_drop", a8)
    put(
        "ADIO8_throat",
        cut_spans(board, "ADIO8", F_Cu, "x", 42.0, 41.2, 42.8) + cut_spans(board, "ADIO8", B_Cu, "x", 42.0, 41.2, 42.8),
    )
    put("PWR_OUT1", cut_spans(board, "PWR_OUT1", F_Cu, "x", 55.0, 100.0, 122.0))
    put("PWR_OUT2", cut_spans(board, "PWR_OUT2", F_Cu, "x", 80.0, 118.0, 140.0))
    put("PWR_OUT3", cut_spans(board, "PWR_OUT3", F_Cu, "y", 10.0, 14.0, 42.0))
    put("PWR_OUT4", cut_spans(board, "PWR_OUT4", F_Cu, "y", 10.0, 36.0, 58.0) + cut_spans(board, "PWR_OUT4", B_Cu, "y", 10.0, 36.0, 58.0))
    return rows


def widen_adio8_drop(board):
    """Move the west edge of A8_drop_F from 47.12 to 47.08.

    PWR_OUT4 fill ends at x=46.68, so 47.08 still clears 0.20 mm.
    The east edge stays on ADIO6. This only makes up the 0.01 mm fill inset.
    """
    n = 0
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetZoneName() != "A8_drop_F":
            continue
        ch = z.Outline().Outline(0)
        for k in range(ch.PointCount()):
            p = ch.CPoint(k)
            if abs(mm(p.x) - 47.12) < 0.02:
                ch.SetPoint(k, pcbnew.VECTOR2I(pcbnew.FromMM(47.08), p.y))
                n += 1
    if n != 2:
        raise SystemExit(f"A8_drop_F west edge edits {n}, expected 2")
    print(f"A8_drop_F west edge 47.12 -> 47.08 ({n} corners)")


def add_adio5_slot(board):
    """B sliver under the F slot. The top is clipped by ADIO4 at y=47.30.

    ADIO7 fill on this x ends at y=44.05, so y=45.46 is clear.
    Existing ribbon bottom is 45.58; the sliver overlaps it.
    """
    add_zone(board, "ADIO5", "B", (111.00, 45.46, 113.45, 45.78), "A5_slot_ext", 3)
    print("added A5_slot_ext B (111.00,45.46)-(113.45,45.78)")


def add_en_ties(board, obs):
    """Pad 2–3 ties on the drivers #26 did not move, plus U12."""
    ties = [
        ("OUT_PWM5", 81.95, 80.70, 81.95, 81.35),
        ("OUT_PWM7", 81.95, 89.70, 81.95, 90.35),
        ("OUT_IO5", 81.95, 98.70, 81.95, 99.35),
        ("OUT_IO7", 81.95, 107.70, 81.95, 108.35),
        ("OUT_PWM6", 81.95, 144.70, 81.95, 145.35),
    ]
    kept = []
    for net, x1, y1, x2, y2 in ties:
        if obs.seg_ok(net, "F", x1, y1, x2, y2, 0.20):
            add_track(board, x1, y1, x2, y2, 0.20, net, "F")
            obs.note_track(net, "F", x1, y1, x2, y2, 0.20)
            kept.append(net)
        else:
            print(f"  skip EN tie {net}: clearance")
    print("EN ties", kept)
    return kept


def normalize(path: Path):
    text = path.read_text()
    text = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text = re.sub(r'\(generator_version "[^"]+"\)', '(generator_version "8.0")', text, count=1)
    text = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text)
    path.write_text(text)


def main():
    board = pcbnew.LoadBoard(str(PCB))
    for i in range(board.GetAreaCount()):
        if board.GetArea(i).GetZoneName() == "A5_slot_ext":
            raise SystemExit("A5_slot_ext is already on the board; do not re-run")
    print("BEFORE necks")
    before = neck_report(board)
    for k, v in before.items():
        print(f"  {k:16} {v:.2f}")

    widen_adio8_drop(board)
    add_adio5_slot(board)
    print("filling polish...")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    print("AFTER polish necks")
    mid = neck_report(board)
    for k, v in mid.items():
        print(f"  {k:16} {v:.2f}  (was {before[k]:.2f})")

    obs = Obs(board)
    add_en_ties(board, obs)

    print("filling...")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(PCB), board)
    normalize(PCB)
    filled = pcbnew.LoadBoard(str(PCB))
    print("FINAL necks")
    final = neck_report(filled)
    for k, v in final.items():
        print(f"  {k:16} {v:.2f}")


if __name__ == "__main__":
    main()
