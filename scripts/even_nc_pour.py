#!/usr/bin/env python3
"""Even-ADIO NC bridge that actually clears a 3.47 mm series neck.

Pins J1.2 and J1.9 join ADIO2. Loom pin names stay N/C (no harness wire).
Pin J1.25 stays N/C: with the odd pours and the PWR_OUT4 west leg in
place, the continuous path from that pad to U18 is well under 3.47 mm,
so ADIO7's B.Cu leg is not moved to chase it.

The pour is a Euclidean tube around the widest F+B path, clipped to
cells that already clear the 0.20 mm gap. A Manhattan dilation leaves
diagonal stretches near 2.5 mm; the disk does not. Series neck is the
minimum F+B cross-section of that one path. Parallel slot sums are not
the rating and are not poured.

Does not bridge F1, does not pour SENSOR_GND, does not export gerbers,
does not replay cut_crossings_sexp.py.

Run only from a clean pdmrazora.kicad_pcb. It adds zones and will
double-pour if launched again on its own output.
"""
from __future__ import annotations

import heapq
import math
import re
from pathlib import Path

import numpy as np
import pcbnew
from PIL import Image, ImageDraw
from scipy import ndimage

PCB = Path("/workspace/pdmrazora.kicad_pcb")
CLR = 0.20
NEED = 3.47
STEP = 0.20
X0, Y0, X1, Y1 = 14.0, 32.0, 115.0, 162.0
# Euclidean tube radius. 2.80 mm around the medial path covers a 4.8 mm
# opening and stays a ribbon where the field is wide open.
TUBE_R_MM = 2.80

board = pcbnew.LoadBoard(str(PCB))
F_Cu = pcbnew.F_Cu
B_Cu = pcbnew.B_Cu


def mm(v):
    return pcbnew.ToMM(v)


def set_pad_nets():
    j1 = next(fp for fp in board.GetFootprints() if fp.GetReference() == "J1")
    for pad in j1.Pads():
        n = pad.GetNumber()
        if n in ("2", "9"):
            pad.SetNet(board.FindNet("ADIO2"))
    print("J1.2 and J1.9 -> ADIO2; J1.25 stays N/C")


# ---------- geometry ----------
W = int(round((X1 - X0) / STEP)) + 1
H = int(round((Y1 - Y0) / STEP)) + 1


def xy_to_px(x, y):
    return int(round((x - X0) / STEP)), int(round((y - Y0) / STEP))


def px_to_xy(c, r):
    return X0 + c * STEP, Y0 + r * STEP


def collect():
    pads = []
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
                    "f": pad.IsOnLayer(F_Cu) or attr == pcbnew.PAD_ATTRIB_PTH or attr == pcbnew.PAD_ATTRIB_NPTH,
                    "b": pad.IsOnLayer(B_Cu) or attr == pcbnew.PAD_ATTRIB_PTH or attr == pcbnew.PAD_ATTRIB_NPTH,
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
    zones = []
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
    tracks = []
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            tracks.append(
                {
                    "kind": "via",
                    "x": mm(t.GetPosition().x),
                    "y": mm(t.GetPosition().y),
                    "w": mm(t.GetWidth()),
                    "net": t.GetNetname(),
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
                    "net": t.GetNetname(),
                    "layers": (lay,),
                }
            )
    return pads, zones, tracks


def hard_zone(z):
    if z["rule"]:
        return True
    if z["pri"] >= 2:
        return True
    if z["net"] == "GND":
        return False
    if z["net"] == "VBAT":
        ys = [p[1] for p in z["pts"]] or [0]
        # North pour and anything that reaches the fuse band stay put.
        if min(ys) < 26:
            return True
        return False
    return True


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


def build_masks(pads, zones, tracks, ignore_nets, ignore_pads):
    img = {L: Image.new("1", (W, H), 0) for L in ("F", "B")}
    draw = {L: ImageDraw.Draw(img[L]) for L in ("F", "B")}
    for p in pads:
        if (p["ref"], p["num"]) in ignore_pads and not p["npth"]:
            continue
        if p["net"] in ignore_nets and p["net"] and not p["npth"]:
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
        if not hard_zone(z):
            continue
        if len(z["pts"]) < 3:
            continue
        pp = [xy_to_px(x, y) for x, y in z["pts"]]
        lays = z["layers"] or ["F", "B"]
        for L in lays:
            if L in draw:
                draw[L].polygon(pp, fill=1)
    for t in tracks:
        if t["net"] in ignore_nets and t["net"]:
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
        a = np.array(img[L], dtype=bool)
        a |= outside
        out[L] = a
    return out


def halfwidths(arr):
    dist = ndimage.distance_transform_edt(~arr) * STEP
    return np.maximum(0.0, dist - CLR)


def dijkstra(score, free, src_cells, goal):
    ny, nx = score.shape
    best = np.full(score.shape, -1.0)
    parent = np.full(score.size, -1, np.int32)
    heap = []
    for r, c in src_cells:
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
        # Best-first: the first goal cell popped is the widest path.
        if goal is not None and found is None and goal[r, c] and sc < 1e5:
            found = sc
            found_idx = idx
        if found is not None and sc < NEED / 2:
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
    return best, found, parent, found_idx


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
                if (rr - r) ** 2 + (cc - c) ** 2 <= rad ** 2:
                    mask[rr, cc] = True
                    cells.append((rr, cc))
    return cells, mask


def corridor(pads, zones, tracks, net, bridge_nums, src_num, goal_refs):
    ignore = {net}
    ignore_pads = {("J1", n) for n in bridge_nums}
    ignore_pads.add(("J1", src_num))
    arr = build_masks(pads, zones, tracks, ignore, ignore_pads)
    hF = halfwidths(arr["F"])
    hB = halfwidths(arr["B"])
    score = hF + hB
    ours = [
        p
        for p in pads
        if (p["net"] == net) or ((p["ref"], p["num"]) in ignore_pads)
    ]
    src = next(p for p in pads if p["ref"] == "J1" and p["num"] == src_num)
    _, free = cells_on_pad(ours)
    src_cells, _ = cells_on_pad([src])
    goals = [p for p in pads if p["ref"] in goal_refs and p["net"] == net and p["f"]]
    _, goal = cells_on_pad(goals)
    best, found, parent, found_idx = dijkstra(score, free, src_cells, goal)
    fb = 0.0 if found is None else 2.0 * found
    print(f"  {net} widest path to driver F+B {fb:.2f}")
    path_mask = np.zeros_like(score, dtype=bool)
    if found_idx is not None:
        idx = found_idx
        guard = 0
        last = None
        off_pinch = None
        while idx >= 0 and guard < score.size + 2:
            r, c = divmod(int(idx), score.shape[1])
            path_mask[r, c] = True
            x, y = px_to_xy(c, r)
            local = 99.0 if free[r, c] else 2.0 * float(score[r, c])
            if local < 50 and (off_pinch is None or local < off_pinch[0]):
                off_pinch = (local, x, y, 2 * float(hF[r, c]), 2 * float(hB[r, c]))
            if last is None or math.hypot(x - last[0], y - last[1]) >= 4:
                tag = "PAD" if local > 50 else f"FB {local:.2f} F {2*float(hF[r,c]):.2f} B {2*float(hB[r,c]):.2f}"
                print(f"    ({x:7.2f},{y:7.2f}) {tag}")
                last = (x, y)
            idx = int(parent[idx])
            guard += 1
        if off_pinch:
            print(
                f"    pinch ({off_pinch[1]:.2f},{off_pinch[2]:.2f}) "
                f"FB {off_pinch[0]:.2f} F {off_pinch[3]:.2f} B {off_pinch[4]:.2f}"
            )
    if found is None or fb + 1e-6 < NEED:
        return None, fb, hF, hB
    # Disk around the widest path, clipped to legal copper. A Manhattan
    # diamond leaves diagonal stretches near 2.5 mm. A flood of every
    # cell that could carry 3.47 mm fills the open B.Cu field.
    rad = int(math.ceil(TUBE_R_MM / STEP))
    yy, xx = np.ogrid[-rad : rad + 1, -rad : rad + 1]
    disk = (yy * yy + xx * xx) <= (TUBE_R_MM / STEP) ** 2
    tube = ndimage.binary_dilation(path_mask, structure=disk)
    keep = tube & ((score >= 0.05) | free)
    fmask = keep & ((hF >= 0.12) | (free & goal))
    bmask = keep & (hB >= 0.12)
    # Same-net PTH / source pads belong on both layers.
    pth = [p for p in ours if p["pth"]]
    _, pth_m = cells_on_pad(pth)
    fmask |= keep & pth_m
    bmask |= keep & pth_m
    _, gmask = cells_on_pad(goals)
    fmask |= gmask
    print(f"  {net} corridor cells F {int(fmask.sum())} B {int(bmask.sum())}")
    return (fmask, bmask, ours, goals), fb, hF, hB


def rects_from_mask(mask):
    """Merge horizontal runs into rectangles. Coordinates are mm, cell edges."""
    finished = []
    active = {}
    Hh, Ww = mask.shape
    for r in range(Hh + 1):
        runs = []
        if r < Hh:
            c = 0
            while c < Ww:
                if mask[r, c]:
                    c1 = c + 1
                    while c1 < Ww and mask[r, c1]:
                        c1 += 1
                    runs.append((c, c1))
                    c = c1
                else:
                    c += 1
        run_set = set(runs)
        for key in list(active):
            if key not in run_set:
                finished.append(active.pop(key))
        for key in runs:
            if key in active:
                active[key][3] = r + 1
            else:
                active[key] = [key[0], r, key[1], r + 1]
    out = []
    for c0, r0, c1, r1 in finished:
        # cell c covers center ± STEP/2
        x0 = X0 + (c0 - 0.5) * STEP
        x1 = X0 + (c1 - 0.5) * STEP
        y0 = Y0 + (r0 - 0.5) * STEP
        y1 = Y0 + (r1 - 0.5) * STEP
        if (x1 - x0) < 0.35 and (y1 - y0) < 0.35:
            continue
        out.append((x0, y0, x1, y1))
    return out


def add_zone(net, layer, rect, name):
    x0, y0, x1, y1 = rect
    z = pcbnew.ZONE(board)
    z.SetNet(board.FindNet(net))
    z.SetLayer(layer)
    z.SetIsRuleArea(False)
    z.SetAssignedPriority(3)
    z.SetLocalClearance(pcbnew.FromMM(0.20))
    z.SetMinThickness(pcbnew.FromMM(0.15))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
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


def place_vias(net, fmask, bmask, hF, hB, goals):
    """Stitch F and B where both are wide, near the driver and along the haul.

    One drill on a cut subtracts 0.30 mm per layer. Only sit where each
    layer is already >= 2.4 mm so the sum stays above 3.47.
    """
    both = fmask & bmask & (hF >= 1.2) & (hB >= 1.2)
    n = 0
    # Prefer a cluster just upstream of the OUT pads, then a sparse line.
    gy = float(np.mean([g["y"] for g in goals]))
    gx = float(np.mean([g["x"] for g in goals]))
    ys, xs = np.nonzero(both)
    if len(xs) == 0:
        print(f"  {net} no via sites")
        return 0
    pts = list(zip(xs.tolist(), ys.tolist()))
    pts.sort(key=lambda rc: (px_to_xy(*rc)[0] - gx) ** 2 + (px_to_xy(*rc)[1] - gy) ** 2)
    chosen = []
    for c, r in pts:
        x, y = px_to_xy(c, r)
        if any(math.hypot(x - x2, y - y2) < 2.2 for x2, y2 in chosen):
            continue
        # Keep the cluster within 25 mm of the driver, plus a few on the haul.
        if math.hypot(x - gx, y - gy) > 40 and len(chosen) > 4:
            continue
        chosen.append((x, y))
        if len(chosen) >= 8:
            break
    for x, y in chosen:
        add_via(x, y, net)
        n += 1
    print(f"  {net} vias {n}")
    return n


def pour(net, pack):
    if pack is None:
        print(f"  {net} not poured (no {NEED:.2f} mm path)")
        return 0
    fmask, bmask, _ours, goals = pack
    layer = {"F": F_Cu, "B": B_Cu}
    n = 0
    for tag, mask in (("F", fmask), ("B", bmask)):
        rects = rects_from_mask(mask)
        print(f"  {net} {tag} rects {len(rects)}")
        for i, rect in enumerate(rects):
            add_zone(net, layer[tag], rect, f"{net[0]}{net[-1]}{tag}{i}")
            n += 1
    return n


def main():
    print(f"grid {W}x{H} tube radius {TUBE_R_MM:.2f} mm")
    set_pad_nets()
    pads, zones, tracks = collect()
    print("corridor ADIO2 (pins 2 and 9)")
    p2, fb2, hF2, hB2 = corridor(pads, zones, tracks, "ADIO2", ("2", "9", "15"), "15", {"U12"})
    print("corridor ADIO8 (pin 25, not poured unless it clears)")
    p8, fb8, hF8, hB8 = corridor(pads, zones, tracks, "ADIO8", ("25", "18"), "18", {"U18"})
    print("corridor ADIO4 (west chain already given to ADIO2)")
    corridor(pads, zones, tracks, "ADIO4", ("16",), "16", {"U14"})
    print("corridor ADIO6")
    corridor(pads, zones, tracks, "ADIO6", ("17",), "17", {"U16"})
    n = 0
    n += pour("ADIO2", p2)
    if p8 is not None:
        n += pour("ADIO8", p8)
        place_vias("ADIO8", p8[0], p8[1], hF8, hB8, p8[3])
    if p2:
        place_vias("ADIO2", p2[0], p2[1], hF2, hB2, p2[3])
    print(f"zones added {n}")
    print("filling...")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    tb = board.GetTitleBlock()
    tb.SetComment(
        0,
        "PowerCore PDM (pdmrazora) - Razor-class 174x202 - even ADIO NC bridges, exposed HP outs",
    )
    board.SetTitleBlock(tb)
    pcbnew.SaveBoard(str(PCB), board)
    text = PCB.read_text()
    text2 = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text2 = re.sub(r'\(generator_version "[^"]+"\)', '(generator_version "8.0")', text2, count=1)
    text2 = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text2)
    if text2 != text:
        PCB.write_text(text2)
    print("saved", PCB)


if __name__ == "__main__":
    main()
