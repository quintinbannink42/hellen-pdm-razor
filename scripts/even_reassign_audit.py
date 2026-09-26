#!/usr/bin/env python3
"""Upper bound on a SuperSeal pin reassignment for ADIO4 / ADIO6 / ADIO8.

Read-only. Does not move footprints, pour copper, bridge F1, pour
SENSOR_GND, export gerbers, or replay cut_crossings_sexp.py.

Every SuperSeal pin that is not already a preserved high-current net is
treated as the candidate net at once (pads are not obstacles). That is
the widest corridor pin reassignment can open. Preserved copper stays
an obstacle: PWR_OUT1–4, ADIO1/2/3/5/7, VBAT at priority >= 2, and VBAT
that reaches the fuse band. Priority-1 GND pours are not obstacles.
Signal tracks and GND tracks are ignored, because a new pour may push
them aside. Pads are not ignored.

Series neck is the minimum F+B of one continuous path. F and B add on
the same XY. A result under 3.47 mm is a hold: this file does not
derate the 8 A line and does not assume 2 oz.
"""
from __future__ import annotations

import heapq
import math
from pathlib import Path

import numpy as np
import pcbnew
from PIL import Image, ImageDraw
from scipy import ndimage

PCB = Path(__file__).resolve().parents[1] / "pdmrazora.kicad_pcb"
CLR = 0.20
NEED = 3.47
STEP = 0.30
X0, Y0, X1, Y1 = 8.0, 28.0, 140.0, 162.0
# Pins whose nets must stay. Everything else on J1 may be reassigned.
LOCKED = {
    "1", "2", "7", "8", "9", "13", "14", "15", "19", "20", "21", "22", "23", "24", "26",
}
PRESERVE = {
    "PWR_OUT1", "PWR_OUT2", "PWR_OUT3", "PWR_OUT4",
    "ADIO1", "ADIO2", "ADIO3", "ADIO5", "ADIO7", "VBAT",
}

board = pcbnew.LoadBoard(str(PCB))
F_Cu = pcbnew.F_Cu
B_Cu = pcbnew.B_Cu
W = int(round((X1 - X0) / STEP)) + 1
H = int(round((Y1 - Y0) / STEP)) + 1


def mm(v):
    return pcbnew.ToMM(v)


def xy_to_px(x, y):
    return int(round((x - X0) / STEP)), int(round((y - Y0) / STEP))


def px_to_xy(c, r):
    return X0 + c * STEP, Y0 + r * STEP


def collect():
    pads, zones, tracks = [], [], []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            if not (pad.IsOnLayer(F_Cu) or pad.IsOnLayer(B_Cu)):
                continue
            pos = pad.GetPosition()
            attr = pad.GetAttribute()
            pads.append(
                {
                    "ref": ref,
                    "num": pad.GetNumber(),
                    "x": mm(pos.x),
                    "y": mm(pos.y),
                    "w": mm(pad.GetSize().x),
                    "h": mm(pad.GetSize().y),
                    "net": pad.GetNetname(),
                    "pth": attr == pcbnew.PAD_ATTRIB_PTH,
                    "npth": attr == pcbnew.PAD_ATTRIB_NPTH,
                    "f": pad.IsOnLayer(F_Cu) or attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH),
                    "b": pad.IsOnLayer(B_Cu) or attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH),
                    "circle": pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE
                    or attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH),
                    "bb": (
                        mm(pad.GetBoundingBox().GetLeft()),
                        mm(pad.GetBoundingBox().GetTop()),
                        mm(pad.GetBoundingBox().GetRight()),
                        mm(pad.GetBoundingBox().GetBottom()),
                    ),
                }
            )
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        layers = []
        try:
            for L in z.GetLayerSet().Seq():
                if L == F_Cu:
                    layers.append("F")
                elif L == B_Cu:
                    layers.append("B")
        except Exception:
            if z.GetLayer() == F_Cu:
                layers.append("F")
            elif z.GetLayer() == B_Cu:
                layers.append("B")
        pts = []
        ol = z.Outline()
        if ol.OutlineCount() > 0:
            ch = ol.Outline(0)
            for k in range(ch.PointCount()):
                p = ch.CPoint(k)
                pts.append((mm(p.x), mm(p.y)))
        zones.append(
            {
                "name": z.GetZoneName() if hasattr(z, "GetZoneName") else "",
                "net": z.GetNetname(),
                "pri": z.GetAssignedPriority(),
                "rule": z.GetIsRuleArea(),
                "layers": layers,
                "pts": pts,
            }
        )
    for t in board.GetTracks():
        net = t.GetNetname()
        if net == "GND" or net not in PRESERVE:
            # Signal and GND tracks may be pushed by a pour. Preserve-net
            # tracks stay. The candidate net's own tracks are not obstacles.
            continue
        if t.GetClass() == "PCB_VIA":
            tracks.append(
                {
                    "kind": "via",
                    "x": mm(t.GetPosition().x),
                    "y": mm(t.GetPosition().y),
                    "w": mm(t.GetWidth()),
                    "net": net,
                    "layers": ("F", "B"),
                }
            )
        else:
            lay = "F" if t.GetLayer() == F_Cu else "B" if t.GetLayer() == B_Cu else None
            if not lay:
                continue
            tracks.append(
                {
                    "kind": "seg",
                    "x0": mm(t.GetStart().x),
                    "y0": mm(t.GetStart().y),
                    "x1": mm(t.GetEnd().x),
                    "y1": mm(t.GetEnd().y),
                    "w": mm(t.GetWidth()),
                    "net": net,
                    "layers": (lay,),
                }
            )
    return pads, zones, tracks


def hard_zone(z):
    if z["rule"]:
        return True
    if z["net"] in PRESERVE and z["net"] != "VBAT":
        return True
    if z["net"] == "VBAT":
        if z["pri"] >= 2:
            return True
        ys = [p[1] for p in z["pts"]] or [0]
        return min(ys) < 26
    return False


def draw_disc(draw, x, y, r):
    if r <= 0:
        return
    c, rr = xy_to_px(x, y)
    rad = r / STEP
    draw.ellipse((c - rad, rr - rad, c + rad, rr + rad), fill=1)


def draw_seg(draw, x0, y0, x1, y1, width):
    r = max(width / 2 / STEP, 0.5)
    c0, r0 = xy_to_px(x0, y0)
    c1, r1 = xy_to_px(x1, y1)
    draw.line((c0, r0, c1, r1), fill=1, width=int(math.ceil(r * 2)))
    draw.ellipse((c0 - r, r0 - r, c0 + r, r0 + r), fill=1)
    draw.ellipse((c1 - r, r1 - r, c1 + r, r1 + r), fill=1)


def build_masks(pads, zones, tracks, ignore_nets, ignore_pads, carve=None):
    img = {L: Image.new("1", (W, H), 0) for L in ("F", "B")}
    draw = {L: ImageDraw.Draw(img[L]) for L in ("F", "B")}
    for p in pads:
        if (p["ref"], p["num"]) in ignore_pads and not p["npth"]:
            continue
        if p["ref"] != "J1" and p["net"] in ignore_nets and p["net"] and not p["npth"]:
            continue
        if p["circle"]:
            rad = p["w"] / 2
            if p["f"]:
                draw_disc(draw["F"], p["x"], p["y"], rad)
            if p["b"]:
                draw_disc(draw["B"], p["x"], p["y"], rad)
        else:
            x0, y0, x1, y1 = p["bb"]
            box = [xy_to_px(x0, y0), xy_to_px(x1, y0), xy_to_px(x1, y1), xy_to_px(x0, y1)]
            if p["f"]:
                draw["F"].polygon(box, fill=1)
            if p["b"]:
                draw["B"].polygon(box, fill=1)
    for z in zones:
        if z["net"] in ignore_nets and not z["rule"]:
            continue
        if not hard_zone(z) or len(z["pts"]) < 3:
            continue
        pp = [xy_to_px(x, y) for x, y in z["pts"]]
        for L in z["layers"] or ["F", "B"]:
            if L in draw:
                draw[L].polygon(pp, fill=1)
    for t in tracks:
        if t["net"] in ignore_nets:
            continue
        for L in t["layers"]:
            if t["kind"] == "via":
                draw_disc(draw[L], t["x"], t["y"], t["w"] / 2)
            else:
                draw_seg(draw[L], t["x0"], t["y0"], t["x1"], t["y1"], t["w"])
    out = {}
    ys = Y0 + np.arange(H) * STEP
    xs = X0 + np.arange(W) * STEP
    outside = (ys[:, None] < -39.5) | (ys[:, None] > 161.5) | (xs[None, :] < -31.5) | (xs[None, :] > 141.5)
    for L in ("F", "B"):
        out[L] = np.array(img[L], dtype=bool) | outside
    if carve:
        x0, y0, x1, y1 = carve
        c0, r0 = xy_to_px(x0, y0)
        c1, r1 = xy_to_px(x1, y1)
        rlo, rhi = sorted((r0, r1))
        clo, chi = sorted((c0, c1))
        out["F"][rlo : rhi + 1, clo : chi + 1] = True
        out["B"][rlo : rhi + 1, clo : chi + 1] = True
    return out


def halfwidths(arr):
    dist = ndimage.distance_transform_edt(~arr) * STEP
    return np.maximum(0.0, dist - CLR)


def cells_on_pad(pads_iter):
    cells = []
    mask = np.zeros((H, W), dtype=bool)
    for p in pads_iter:
        c, r = xy_to_px(p["x"], p["y"])
        rad = max(p["w"], p["h"]) / 2 / STEP
        r0, r1 = max(0, int(r - rad - 1)), min(H, int(r + rad + 2))
        c0, c1 = max(0, int(c - rad - 1)), min(W, int(c + rad + 2))
        for rr in range(r0, r1):
            for cc in range(c0, c1):
                if (rr - r) ** 2 + (cc - c) ** 2 <= (rad + 0.2) ** 2:
                    mask[rr, cc] = True
                    cells.append((rr, cc))
    return cells, mask


def dijkstra(score, free, src_cells, goal):
    ny, nx = score.shape
    best = np.full(score.shape, -1.0)
    parent = np.full(score.size, -1, np.int32)
    heap = []
    for r, c in src_cells:
        if 0 <= r < ny and 0 <= c < nx:
            best[r, c] = 1e6
            heapq.heappush(heap, (-1e6, r * nx + c))
    found = None
    found_idx = None
    while heap:
        neg, idx = heapq.heappop(heap)
        sc = -neg
        r, c = divmod(idx, nx)
        if sc < best[r, c] - 1e-9:
            continue
        if found is None and goal[r, c] and sc < 1e5:
            found = sc
            found_idx = idx
            break
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            rr, cc = r + dr, c + dc
            if rr < 0 or cc < 0 or rr >= ny or cc >= nx:
                continue
            cell = 1e6 if free[rr, cc] else float(score[rr, cc])
            if cell <= 0:
                continue
            cand = cell if sc >= 1e6 else min(sc, cell)
            if cand > best[rr, cc]:
                best[rr, cc] = cand
                parent[rr * nx + cc] = idx
                heapq.heappush(heap, (-cand, rr * nx + cc))
    return found, parent, found_idx


def region_goal(score, gx, gy, rad):
    goal = np.zeros_like(score, dtype=bool)
    gc, gr = xy_to_px(gx, gy)
    n = int(rad / STEP) + 2
    for r in range(gr - n, gr + n + 1):
        for c in range(gc - n, gc + n + 1):
            if 0 <= r < H and 0 <= c < W:
                x, y = px_to_xy(c, r)
                if (x - gx) ** 2 + (y - gy) ** 2 <= rad ** 2 and score[r, c] > 0:
                    goal[r, c] = True
    return goal


def audit(pads, zones, tracks, net, src, extra, gx, gy, carve=None):
    ignore_pads = {("J1", src)} | {("J1", n) for n in extra}
    arr = build_masks(pads, zones, tracks, {net}, ignore_pads, carve=carve)
    hF = halfwidths(arr["F"])
    hB = halfwidths(arr["B"])
    score = hF + hB
    srcp = next(p for p in pads if p["ref"] == "J1" and p["num"] == src)
    _, free = cells_on_pad([p for p in pads if (p["ref"], p["num"]) in ignore_pads])
    src_cells, _ = cells_on_pad([srcp])
    goal = region_goal(score, gx, gy, 2.0)
    found, parent, found_idx = dijkstra(score, free, src_cells, goal)
    fb = 0.0 if found is None else 2.0 * found
    pinch = None
    if found_idx is not None:
        idx = found_idx
        nx = score.shape[1]
        guard = 0
        while idx >= 0 and guard < score.size + 2:
            r, c = divmod(int(idx), nx)
            if not free[r, c]:
                local = 2.0 * float(score[r, c])
                x, y = px_to_xy(c, r)
                if pinch is None or local < pinch[0]:
                    pinch = (local, x, y, 2 * float(hF[r, c]), 2 * float(hB[r, c]))
            idx = int(parent[idx])
            guard += 1
    return fb, pinch, int(goal.sum())


def main():
    pads, zones, tracks = collect()
    free_pins = tuple(
        p["num"] for p in pads if p["ref"] == "J1" and p["num"] and p["num"] not in LOCKED
    )
    print(f"grid {W}x{H} step {STEP:.2f} mm  need {NEED:.2f}")
    print("reassignable J1 pins (all same-net for the upper bound):", " ".join(free_pins))
    print("locked J1 pins stay on their nets:", " ".join(sorted(LOCKED, key=int)))
    targets = [
        ("ADIO4", "25", (96.0, 154.0), "south field beside U14"),
        ("ADIO6", "25", (68.0, 64.0), "west of U16 OUT"),
        ("ADIO6", "25", (80.0, 66.0), "east of U16"),
        ("ADIO8", "25", (98.0, 64.0), "east of U18 OUT"),
        ("ADIO8", "25", (96.0, 66.0), "north-east of U18"),
        ("ADIO2", "15", (87.6, 146.5), "U12 OUT neighborhood (sanity, pins 2+9+15 only)"),
    ]
    carve_u14 = (87.2, 150.5, 93.5, 161.0)
    for net, src, (gx, gy), label in targets:
        extra = free_pins if net != "ADIO2" else ("2", "9", "15")
        if net == "ADIO2":
            src = "15"
        fb, pinch, ngoals = audit(pads, zones, tracks, net, src, extra, gx, gy)
        flag = "PASS" if fb + 1e-6 >= NEED else "HOLD"
        if pinch:
            pinch_s = (
                f"pinch ({pinch[1]:.1f},{pinch[2]:.1f}) "
                f"FB {pinch[0]:.2f} F {pinch[3]:.2f} B {pinch[4]:.2f}"
            )
        else:
            pinch_s = "no positive-width path"
        print(f"{flag:4} {fb:6.2f}  {net:5} -> ({gx:.0f},{gy:.0f}) {label}  goals {ngoals}  {pinch_s}")
    fb, pinch, ngoals = audit(
        pads, zones, tracks, "ADIO2", "15", ("2", "9", "15"), 87.6, 146.5, carve=carve_u14
    )
    pinch_s = "no positive-width path" if pinch is None else (
        f"pinch ({pinch[1]:.1f},{pinch[2]:.1f}) FB {pinch[0]:.2f} F {pinch[3]:.2f} B {pinch[4]:.2f}"
    )
    print(
        f"HOLD {fb:6.2f}  ADIO2 -> (88,146) with U14-east tube blanked "
        f"{carve_u14}  goals {ngoals}  {pinch_s}"
    )


if __name__ == "__main__":
    main()
