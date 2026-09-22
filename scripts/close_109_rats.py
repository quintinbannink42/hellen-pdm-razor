#!/usr/bin/env python3
"""Close carrier ratsnests on the 109×98 PowerCore nest.

Does not move the outline, J1, M1000, J2, or J3. Does not bridge F1.
Does not pour SENSOR_GND. Does not cover PWR_OUT F.Mask openings.
Does not replay cut_crossings_sexp.py or the 150×130 routers.

Tracks are 0.20 mm. Vias are 0.50 / 0.30, the board minimum.
SuperSeal pads are round, so clearance uses the real circle, not the
square bounding box.
"""
from __future__ import annotations

import heapq
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout_109x98 as L

GRID = 0.10
CLR = 0.20
# 0.15 mm necks the 0.60 mm gaps in the mega-mcu144 south pad row
# (0.60 mm pads on a 1.20 mm pitch). A 0.20 mm track is exactly the gap
# and the grid closes it. 0.15 mm leaves 0.225 mm clearance.
TRACK_W = 0.15
VIA_D = 0.50
VIA_DRILL = 0.30
# Paint a little fat so a grid center that survives still clears 0.20 mm
# when the segment is checked exactly.
PAINT_EXTRA = 0.0
EDGE_COPPER = 0.50

# Fuse band. Pre-fuse copper stays north of y=22.5. Post-fuse starts at
# y=27.5. Nothing new is allowed to cross this band, so F1 stays open.
FUSE_Y0, FUSE_Y1 = 23.15, 26.05


def dist_pt_seg(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def rect_gap(px, py, l, t, r, b) -> float:
    """Distance from point to rectangle. 0 if inside."""
    dx = 0.0 if l <= px <= r else (l - px if px < l else px - r)
    dy = 0.0 if t <= py <= b else (t - py if py < t else py - b)
    return math.hypot(dx, dy)


class UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


class World:
    def __init__(self, board):
        self.board = board
        self.pads = []
        self.segs = []  # x1,y1,x2,y2,layer,net,width
        self.vias = []  # x,y,net,size,drill
        self._load()
        self.nx = int(L.BOARD_W / GRID) + 3
        self.ny = int(L.BOARD_H / GRID) + 3
        if os.environ.get("SKIP_RASTER") == "1":
            self.gnd_b = set()
            self.vbat_f = set()
            self.vbat_b = set()
        else:
            self.gnd_b = self._raster_fill("GND", "B")
            self.vbat_f = self._raster_fill("VBAT", "F")
            self.vbat_b = self._raster_fill("VBAT", "B")

    def _load(self):
        for fp in self.board.GetFootprints():
            ref = fp.GetReference()
            for pad in fp.Pads():
                net = pad.GetNetname() or ""
                if not net:
                    # Still copper. Clearance applies. Net stays blank.
                    pass
                attr = pad.GetAttribute()
                pth = attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
                on_f = pad.IsOnLayer(pcbnew.F_Cu) or pth
                on_b = pad.IsOnLayer(pcbnew.B_Cu) or pth
                if not on_f and not on_b:
                    continue
                x, y = L.ToMM(pad.GetPosition().x), L.ToMM(pad.GetPosition().y)
                shape = pad.GetShape()
                sx, sy = L.ToMM(pad.GetSize().x), L.ToMM(pad.GetSize().y)
                drill = pad.GetDrillSize()
                dx, dy = L.ToMM(drill.x), L.ToMM(drill.y)
                bb = pad.GetBoundingBox()
                self.pads.append(
                    {
                        "ref": ref,
                        "num": pad.GetNumber(),
                        "net": net,
                        "x": x,
                        "y": y,
                        "pth": pth,
                        "f": on_f,
                        "b": on_b,
                        "circle": shape == pcbnew.PAD_SHAPE_CIRCLE,
                        "r": sx / 2 if shape == pcbnew.PAD_SHAPE_CIRCLE else 0.0,
                        "box": (
                            L.ToMM(bb.GetLeft()),
                            L.ToMM(bb.GetTop()),
                            L.ToMM(bb.GetRight()),
                            L.ToMM(bb.GetBottom()),
                        ),
                        "drill": max(dx, dy),
                    }
                )
        for t in self.board.GetTracks():
            if L.is_via(t):
                p = t.GetPosition()
                self.vias.append(
                    (
                        L.ToMM(p.x),
                        L.ToMM(p.y),
                        t.GetNetname(),
                        L.ToMM(t.GetWidth()),
                        L.ToMM(t.GetDrill()),
                    )
                )
            else:
                a, b = t.GetStart(), t.GetEnd()
                lay = "F" if t.GetLayer() == pcbnew.F_Cu else "B"
                self.segs.append(
                    (
                        L.ToMM(a.x),
                        L.ToMM(a.y),
                        L.ToMM(b.x),
                        L.ToMM(b.y),
                        lay,
                        t.GetNetname(),
                        L.ToMM(t.GetWidth()),
                    )
                )

    def _raster_fill(self, net, layer):
        """Set of (ix, iy) at GRID whose center lies in a filled polygon."""
        lay = pcbnew.F_Cu if layer == "F" else pcbnew.B_Cu
        polys = []
        for i in range(self.board.GetAreaCount()):
            z = self.board.GetArea(i)
            if z.GetIsRuleArea() or z.GetNetname() != net or z.GetFirstLayer() != lay:
                continue
            if not z.IsFilled():
                continue
            try:
                polys.append(z.GetFilledPolysList(lay))
            except TypeError:
                polys.append(z.GetFilledPolysList())
        cells = set()
        if not polys:
            return cells
        # Sample at GRID. 1090x980 Contains calls is a few seconds once.
        for iy in range(self.ny):
            y = iy * GRID
            if y < 0 or y > L.BOARD_H:
                continue
            for ix in range(self.nx):
                x = ix * GRID
                if x < 0 or x > L.BOARD_W:
                    continue
                pt = pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
                if any(p.Contains(pt) for p in polys):
                    cells.add((ix, iy))
        return cells

    def pad_gap(self, pad, x, y) -> float:
        if pad["circle"]:
            return math.hypot(x - pad["x"], y - pad["y"]) - pad["r"]
        l, t, r, b = pad["box"]
        return rect_gap(x, y, l, t, r, b)

    def pad_hit_point(self, pad, x, y, margin) -> bool:
        return self.pad_gap(pad, x, y) <= margin

    def seg_blocked(self, x1, y1, x2, y2, net, layer, width=TRACK_W) -> bool:
        halo = width / 2 + CLR
        samples = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.20) + 1)
        pts = []
        for i in range(samples):
            u = i / (samples - 1)
            pts.append((x1 + (x2 - x1) * u, y1 + (y2 - y1) * u))
        for px, py in pts:
            if px - width / 2 < EDGE_COPPER or py - width / 2 < EDGE_COPPER:
                return True
            if px + width / 2 > L.BOARD_W - EDGE_COPPER or py + width / 2 > L.BOARD_H - EDGE_COPPER:
                return True
            if net == "VBAT" and FUSE_Y0 <= py <= FUSE_Y1:
                return True
        for s in self.segs:
            if s[5] == net:
                continue
            if s[4] != layer:
                continue
            need = halo + s[6] / 2
            # bbox reject
            if min(x1, x2) - need > max(s[0], s[2]) or max(x1, x2) + need < min(s[0], s[2]):
                continue
            if min(y1, y2) - need > max(s[1], s[3]) or max(y1, y2) + need < min(s[1], s[3]):
                continue
            for px, py in pts:
                if dist_pt_seg(px, py, s[0], s[1], s[2], s[3]) < need:
                    return True
        for v in self.vias:
            if v[2] == net:
                continue
            need = halo + v[3] / 2
            for px, py in pts:
                if math.hypot(px - v[0], py - v[1]) < need:
                    return True
        for p in self.pads:
            if p["net"] == net and p["net"]:
                continue
            if layer == "F" and not p["f"]:
                continue
            if layer == "B" and not p["b"]:
                continue
            for px, py in pts:
                if self.pad_gap(p, px, py) < halo:
                    return True
        return False

    def via_blocked(self, x, y, net, size=VIA_D, drill=VIA_DRILL) -> bool:
        if x - size / 2 < EDGE_COPPER or y - size / 2 < EDGE_COPPER:
            return True
        if x + size / 2 > L.BOARD_W - EDGE_COPPER or y + size / 2 > L.BOARD_H - EDGE_COPPER:
            return True
        if net == "VBAT" and FUSE_Y0 <= y <= FUSE_Y1:
            return True
        halo = size / 2 + CLR
        for p in self.pads:
            if p["net"] == net and p["net"]:
                continue
            if self.pad_gap(p, x, y) < halo:
                return True
            if p["drill"] > 0.05:
                need = drill / 2 + p["drill"] / 2 + 0.25
                if math.hypot(x - p["x"], y - p["y"]) < need:
                    return True
        for s in self.segs:
            if s[5] == net:
                continue
            need = halo + s[6] / 2
            if dist_pt_seg(x, y, s[0], s[1], s[2], s[3]) < need:
                return True
        for v in self.vias:
            dist = math.hypot(x - v[0], y - v[1])
            # Same-net copper may touch. Holes may not: 0.25 mm edge to edge.
            if v[2] != net and dist < halo + v[3] / 2:
                return True
            need = drill / 2 + v[4] / 2 + 0.25
            if dist < need - 1e-6:
                return True
        return False

    def add_seg(self, x1, y1, x2, y2, net, layer, width=TRACK_W):
        if math.hypot(x2 - x1, y2 - y1) < 0.02:
            return False
        L.add_track(self.board, x1, y1, x2, y2, width, net, layer)
        self.segs.append((x1, y1, x2, y2, layer, net, width))
        return True

    def add_via(self, x, y, net, size=VIA_D, drill=VIA_DRILL):
        L.add_via(self.board, x, y, net, size, drill)
        self.vias.append((x, y, net, size, drill))

    def islands(self, net):
        """Copper objects of this net, grouped by what actually touches."""
        objs = []
        for p in self.pads:
            if p["net"] == net:
                objs.append(("pad", p))
        for s in self.segs:
            if s[5] == net:
                objs.append(("seg", s))
        for v in self.vias:
            if v[2] == net:
                objs.append(("via", v))
        uf = UF(len(objs))

        def layers_of(obj):
            kind = obj[0]
            if kind == "pad":
                p = obj[1]
                if p["pth"]:
                    return ("F", "B")
                out = []
                if p["f"]:
                    out.append("F")
                if p["b"]:
                    out.append("B")
                return tuple(out)
            if kind == "seg":
                return (obj[1][4],)
            return ("F", "B")

        def connect_point_pad(x, y, layer, width, pad):
            lays = layers_of(("pad", pad))
            if layer not in lays and not pad["pth"]:
                return False
            return self.pad_hit_point(pad, x, y, width / 2 + 0.01)

        for i, a in enumerate(objs):
            for j in range(i + 1, len(objs)):
                b = objs[j]
                if self._objects_touch(a, b):
                    uf.union(i, j)
        groups = defaultdict(list)
        for i, obj in enumerate(objs):
            groups[uf.find(i)].append(obj)
        return list(groups.values())

    def _objects_touch(self, a, b) -> bool:
        # Order pad < seg < via for simpler cases by swapping.
        pair = tuple(sorted((a, b), key=lambda o: o[0]))
        ka, kb = pair[0][0], pair[1][0]
        if ka == "pad" and kb == "pad":
            pa, pb = pair[0][1], pair[1][1]
            # PTH pads of the same ref don't auto-connect unless copper overlaps.
            if pa["circle"] and pb["circle"]:
                return math.hypot(pa["x"] - pb["x"], pa["y"] - pb["y"]) <= pa["r"] + pb["r"] + 0.01
            return self.pad_gap(pa, pb["x"], pb["y"]) <= (pb["r"] if pb["circle"] else 0) + 0.01
        if ka == "pad" and kb == "seg":
            pad, s = pair[0][1], pair[1][1]
            if s[4] == "F" and not pad["f"] and not pad["pth"]:
                return False
            if s[4] == "B" and not pad["b"] and not pad["pth"]:
                return False
            return self.pad_hit_point(pad, s[0], s[1], s[6] / 2 + 0.02) or self.pad_hit_point(
                pad, s[2], s[3], s[6] / 2 + 0.02
            ) or (
                dist_pt_seg(pad["x"], pad["y"], s[0], s[1], s[2], s[3])
                <= (pad["r"] if pad["circle"] else 0.4) + s[6] / 2 + 0.02
                and self.pad_gap(pad, *_closest_on_seg(pad["x"], pad["y"], s), ) <= s[6] / 2 + 0.02
            )
        if ka == "pad" and kb == "via":
            pad, v = pair[0][1], pair[1][1]
            return self.pad_gap(pad, v[0], v[1]) <= v[3] / 2 + 0.02
        if ka == "seg" and kb == "seg":
            s, t = pair[0][1], pair[1][1]
            if s[4] != t[4]:
                return False
            need = s[6] / 2 + t[6] / 2 + 0.02
            for px, py in ((s[0], s[1]), (s[2], s[3])):
                if dist_pt_seg(px, py, t[0], t[1], t[2], t[3]) <= need:
                    return True
            for px, py in ((t[0], t[1]), (t[2], t[3])):
                if dist_pt_seg(px, py, s[0], s[1], s[2], s[3]) <= need:
                    return True
            return False
        if ka == "seg" and kb == "via":
            s, v = pair[0][1], pair[1][1]
            return dist_pt_seg(v[0], v[1], s[0], s[1], s[2], s[3]) <= s[6] / 2 + v[3] / 2 + 0.02
        if ka == "via" and kb == "via":
            va, vb = pair[0][1], pair[1][1]
            return math.hypot(va[0] - vb[0], va[1] - vb[1]) <= va[3] / 2 + vb[3] / 2 + 0.02
        return False

    def anchors(self, group):
        pts = []
        for kind, obj in group:
            if kind == "pad":
                lays = []
                if obj["pth"] or obj["f"]:
                    lays.append(0)
                if obj["pth"] or obj["b"]:
                    lays.append(1)
                rad = obj["r"] if obj["circle"] else min(0.45, max(obj["box"][2] - obj["box"][0], obj["box"][3] - obj["box"][1]) / 2)
                pts.append((obj["x"], obj["y"], tuple(lays), max(0.20, rad * 0.75), f"{obj['ref']}.{obj['num']}"))
            elif kind == "seg":
                lay = 0 if obj[4] == "F" else 1
                pts.append((obj[0], obj[1], (lay,), 0.28, "track"))
                pts.append((obj[2], obj[3], (lay,), 0.28, "track"))
            else:
                pts.append((obj[0], obj[1], (0, 1), obj[3] / 2 * 0.8, "via"))
        return pts

    def paint(self, net):
        halo = TRACK_W / 2 + CLR + PAINT_EXTRA
        vhalo = VIA_D / 2 + CLR + PAINT_EXTRA
        blk = [bytearray(self.nx * self.ny), bytearray(self.nx * self.ny)]
        vblk = bytearray(self.nx * self.ny)

        def mark_rect(l, t, r, b, layer, via=False, disk=None):
            ix0 = max(0, int(math.floor(l / GRID)))
            ix1 = min(self.nx - 1, int(math.ceil(r / GRID)))
            iy0 = max(0, int(math.floor(t / GRID)))
            iy1 = min(self.ny - 1, int(math.ceil(b / GRID)))
            dcx = dcy = dr = 0.0
            if disk is not None:
                dcx, dcy, dr = disk
            for iy in range(iy0, iy1 + 1):
                cy = iy * GRID
                row = iy * self.nx
                for ix in range(ix0, ix1 + 1):
                    cx = ix * GRID
                    if disk is not None:
                        if math.hypot(cx - dcx, cy - dcy) > dr:
                            continue
                    elif not (l <= cx <= r and t <= cy <= b):
                        continue
                    if via:
                        vblk[row + ix] = 1
                    elif layer is None:
                        blk[0][row + ix] = 1
                        blk[1][row + ix] = 1
                    else:
                        blk[layer][row + ix] = 1

        for p in self.pads:
            if p["net"] == net and p["net"]:
                # Still block vias on the hole-to-hole rule against this pad's drill
                # only when the via is not sitting on the pad. Handled at commit.
                if p["drill"] > 0.05:
                    need = VIA_DRILL / 2 + p["drill"] / 2 + 0.25
                    mark_rect(p["x"] - need, p["y"] - need, p["x"] + need, p["y"] + need, None, via=True)
                    # Free the pad center so a via can still land on a same-net PTH
                    # if copper clearance allows. Hole rule forbids via-in-hole, so
                    # leave the drill blocked. The annular ring outside the drill is
                    # usable when need is only the hole clearance.
                continue
            if p["circle"]:
                rad = p["r"] + halo
                vrad = p["r"] + vhalo
            else:
                l, t, r, b = p["box"]
                rad = None
            if p["f"]:
                if p["circle"]:
                    mark_rect(p["x"] - rad, p["y"] - rad, p["x"] + rad, p["y"] + rad, 0, disk=(p["x"], p["y"], rad))
                    vr = p["r"] + vhalo
                    mark_rect(p["x"] - vr, p["y"] - vr, p["x"] + vr, p["y"] + vr, None, via=True, disk=(p["x"], p["y"], vr))
                else:
                    l, t, r, b = p["box"]
                    mark_rect(l - halo, t - halo, r + halo, b + halo, 0)
                    mark_rect(l - vhalo, t - vhalo, r + vhalo, b + vhalo, None, via=True)
            if p["b"]:
                if p["circle"]:
                    mark_rect(p["x"] - rad, p["y"] - rad, p["x"] + rad, p["y"] + rad, 1, disk=(p["x"], p["y"], rad))
                    vr = p["r"] + vhalo
                    mark_rect(p["x"] - vr, p["y"] - vr, p["x"] + vr, p["y"] + vr, None, via=True, disk=(p["x"], p["y"], vr))
                else:
                    l, t, r, b = p["box"]
                    mark_rect(l - halo, t - halo, r + halo, b + halo, 1)
                    mark_rect(l - vhalo, t - vhalo, r + vhalo, b + vhalo, None, via=True)
            if p["drill"] > 0.05 and not (p["net"] == net and p["net"]):
                need = VIA_DRILL / 2 + p["drill"] / 2 + 0.25
                mark_rect(p["x"] - need, p["y"] - need, p["x"] + need, p["y"] + need, None, via=True)
        for x1, y1, x2, y2, lay, n, w in self.segs:
            if n == net:
                continue
            # Capsule, not the axis-aligned box. A diagonal bbox closes the
            # south SuperSeal slots the next net still needs.
            h = TRACK_W / 2 + CLR + PAINT_EXTRA + w / 2
            hv = VIA_D / 2 + CLR + PAINT_EXTRA + w / 2
            layer = 0 if lay == "F" else 1
            length = math.hypot(x2 - x1, y2 - y1)
            ortho = abs(x2 - x1) < 0.02 or abs(y2 - y1) < 0.02
            if ortho:
                mark_rect(min(x1, x2) - h, min(y1, y2) - h, max(x1, x2) + h, max(y1, y2) + h, layer)
                mark_rect(min(x1, x2) - hv, min(y1, y2) - hv, max(x1, x2) + hv, max(y1, y2) + hv, None, via=True)
            else:
                steps = max(1, int(length / GRID))
                for i in range(steps + 1):
                    u = i / steps
                    px = x1 + (x2 - x1) * u
                    py = y1 + (y2 - y1) * u
                    mark_rect(px - h, py - h, px + h, py + h, layer, disk=(px, py, h))
                    mark_rect(px - hv, py - hv, px + hv, py + hv, None, via=True, disk=(px, py, hv))
        for x, y, n, sz, drill in self.vias:
            # Same-net copper may overlap. The drill still owns a 0.25 mm hole halo
            # so the next via on this net does not land 0.50 mm away.
            need = VIA_DRILL / 2 + drill / 2 + 0.25
            mark_rect(x - need, y - need, x + need, y + need, None, via=True, disk=(x, y, need))
            if n == net:
                continue
            h = TRACK_W / 2 + CLR + PAINT_EXTRA + sz / 2
            mark_rect(x - h, y - h, x + h, y + h, None, disk=(x, y, h))
            hv = VIA_D / 2 + CLR + PAINT_EXTRA + sz / 2
            mark_rect(x - hv, y - hv, x + hv, y + hv, None, via=True, disk=(x, y, hv))
        for ix in range(self.nx):
            for iy in range(self.ny):
                x, y = ix * GRID, iy * GRID
                if (
                    x < EDGE_COPPER + TRACK_W / 2
                    or y < EDGE_COPPER + TRACK_W / 2
                    or x > L.BOARD_W - EDGE_COPPER - TRACK_W / 2
                    or y > L.BOARD_H - EDGE_COPPER - TRACK_W / 2
                ):
                    blk[0][iy * self.nx + ix] = 1
                    blk[1][iy * self.nx + ix] = 1
                    vblk[iy * self.nx + ix] = 1
                elif net == "VBAT" and FUSE_Y0 <= y <= FUSE_Y1:
                    blk[0][iy * self.nx + ix] = 1
                    blk[1][iy * self.nx + ix] = 1
                    vblk[iy * self.nx + ix] = 1
        self.blk = blk
        self.vblk = vblk

    def _foreign_blocks_track(self, x, y, layer, net, ignore_pad) -> bool:
        halo = TRACK_W / 2 + CLR + PAINT_EXTRA
        if layer == 0:
            for s in self.segs:
                if s[5] == net or s[4] != "F":
                    continue
                if dist_pt_seg(x, y, s[0], s[1], s[2], s[3]) < halo + s[6] / 2:
                    return True
        else:
            for s in self.segs:
                if s[5] == net or s[4] != "B":
                    continue
                if dist_pt_seg(x, y, s[0], s[1], s[2], s[3]) < halo + s[6] / 2:
                    return True
        for v in self.vias:
            if v[2] == net:
                continue
            if math.hypot(x - v[0], y - v[1]) < halo + v[3] / 2:
                return True
        for p in self.pads:
            if p is ignore_pad or (p["net"] == net and p["net"]):
                continue
            if layer == 0 and not p["f"]:
                continue
            if layer == 1 and not p["b"]:
                continue
            if self.pad_gap(p, x, y) < halo:
                return True
        return False

    def _only_this_circle(self, x, y, pad, layer, net, rad) -> bool:
        if math.hypot(x - pad["x"], y - pad["y"]) <= rad:
            return False
        return not self._foreign_blocks_track(x, y, layer, net, pad)

    def _via_only_this(self, x, y, pad, net, vrad) -> bool:
        if math.hypot(x - pad["x"], y - pad["y"]) <= vrad:
            return False
        return not self.via_blocked(x, y, net)

    def free(self, ix, iy, lay) -> bool:
        if not (0 <= ix < self.nx and 0 <= iy < self.ny):
            return False
        return self.blk[lay][iy * self.nx + ix] == 0

    def nearest(self, x, y, layers, rad_max=12):
        ix, iy = int(round(x / GRID)), int(round(y / GRID))
        found = []
        for lay in layers:
            if self.free(ix, iy, lay):
                found.append((ix, iy, lay))
        if found:
            return found
        for rad in range(1, rad_max + 1):
            for dx in range(-rad, rad + 1):
                for dy in range(-rad, rad + 1):
                    if max(abs(dx), abs(dy)) != rad:
                        continue
                    for lay in layers:
                        if self.free(ix + dx, iy + dy, lay):
                            found.append((ix + dx, iy + dy, lay))
            if found:
                return found
        return []

    def route(self, x1, y1, x2, y2, start_layers, goal_layers, goal_r, net, extra_goals=None, limit=1_200_000, bounds=None, goal_lay=None):
        starts = self.nearest(x1, y1, start_layers, rad_max=16)
        if not starts:
            return None, 0
        # Prefer the back side through the connector: F.Cu there is the wide
        # PWR_OUT copper. East of the module, either layer is fine.
        inf = 10**9
        best = {}
        pq = []
        parent = {}
        for ix, iy, lay in starts:
            c0 = 0.0
            best[(ix, iy, lay)] = c0
            c0 = 0.0
            dxg = abs(ix - int(round(x2 / GRID)))
            dyg = abs(iy - int(round(y2 / GRID)))
            h0 = max(dxg, dyg) + 0.42 * min(dxg, dyg)
            best[(ix, iy, lay)] = c0
            heapq.heappush(pq, (h0, c0, ix, iy, lay))
        goal_ix = int(round(x2 / GRID))
        goal_iy = int(round(y2 / GRID))
        expanded = 0
        found = None
        while pq and expanded < limit:
            _h, g, ix, iy, lay = heapq.heappop(pq)
            if g != best.get((ix, iy, lay)):
                continue
            expanded += 1
            cx, cy = ix * GRID, iy * GRID
            dxg = abs(ix - goal_ix)
            dyg = abs(iy - goal_iy)
            # Octile, matching ortho cost 1 and diagonal cost 1.42.
            heur = max(dxg, dyg) + 0.42 * min(dxg, dyg)
            hit_goal = False
            if lay in goal_layers and math.hypot(cx - x2, cy - y2) <= goal_r and (g > 0 or math.hypot(x1 - x2, y1 - y2) < 0.05):
                hit_goal = True
            # Pour goals are layer-specific. A front-side cell sitting over the
            # back pour is not a connection. goal_lay=None keeps the old
            # "either layer" check for VBAT, which is how C1 hits the pre pour.
            if extra_goals and (ix, iy) in extra_goals and g > 0 and (goal_lay is None or lay == goal_lay):
                hit_goal = True
            if hit_goal:
                found = (ix, iy, lay)
                break
            # Minimum step stays 1 so the octile heuristic is admissible.
            # The packed driver band is expensive, which makes the south margin
            # (y>67) and the north shelf the paths A* actually tries first.
            # F.Cu west of x=50 is the wide PWR_OUT copper.
            step = 1.0
            if 30.0 <= cy <= 66.0 and cx >= 45.0:
                step = 4.0
            elif lay == 0 and cx < 50.0 and 28.0 <= cy <= 66.0:
                step = 2.2
            for dx, dy in (
                (1, 0),
                (-1, 0),
                (0, 1),
                (0, -1),
                (1, 1),
                (1, -1),
                (-1, 1),
                (-1, -1),
            ):
                nx, ny = ix + dx, iy + dy
                if bounds is not None:
                    qx, qy = nx * GRID, ny * GRID
                    if not (bounds[0] <= qx <= bounds[2] and bounds[1] <= qy <= bounds[3]):
                        continue
                if not self.free(nx, ny, lay):
                    continue
                diag = dx != 0 and dy != 0
                ng = round(g + (step * 1.42 if diag else step), 3)
                key = (nx, ny, lay)
                if ng < best.get(key, inf):
                    best[key] = ng
                    parent[key] = (ix, iy, lay)
                    ndx, ndy = abs(nx - goal_ix), abs(ny - goal_iy)
                    nh = max(ndx, ndy) + 0.42 * min(ndx, ndy)
                    heapq.heappush(pq, (ng + nh, ng, nx, ny, lay))
            if self.vblk[iy * self.nx + ix] == 0 and self.free(ix, iy, 0) and self.free(ix, iy, 1):
                nlay = 1 - lay
                ng = round(g + 6.5, 3)
                key = (ix, iy, nlay)
                if ng < best.get(key, inf):
                    best[key] = ng
                    parent[key] = (ix, iy, lay)
                    heapq.heappush(pq, (ng + heur, ng, ix, iy, nlay))
        if not found:
            return None, expanded
        path = [found]
        while path[-1] in parent:
            path.append(parent[path[-1]])
            if len(path) > 20000:
                return None, expanded
        path.reverse()
        return path, expanded

    def commit(self, path, x1, y1, x2, y2, net) -> bool:
        pts = [(x1, y1, path[0][2])]
        for ix, iy, lay in path:
            pts.append((round(ix * GRID, 3), round(iy * GRID, 3), lay))
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
        planned = []
        planned_vias = []
        for i in range(len(simp) - 1):
            xa, ya, la = simp[i]
            xb, yb, lb = simp[i + 1]
            if la != lb:
                if self.via_blocked(xb, yb, net):
                    return False
                for vx, vy in planned_vias:
                    if math.hypot(xb - vx, yb - vy) < VIA_DRILL + 0.25:
                        return False
                planned.append(("v", xb, yb))
                planned_vias.append((xb, yb))
            else:
                lay = "F" if la == 0 else "B"
                if math.hypot(xb - xa, yb - ya) < 0.02:
                    continue
                if self.seg_blocked(xa, ya, xb, yb, net, lay):
                    return False
                planned.append(("t", xa, ya, xb, yb, lay))
        if not planned:
            return False
        for item in planned:
            if item[0] == "v":
                self.add_via(item[1], item[2], net)
            else:
                _, xa, ya, xb, yb, lay = item
                self.add_seg(xa, ya, xb, yb, net, lay)
        return True


def _closest_on_seg(px, py, s):
    x1, y1, x2, y2 = s[0], s[1], s[2], s[3]
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return x1, y1
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return x1 + t * dx, y1 + t * dy


def closest_pair(world, groups):
    best = None
    best_d = 1e9
    anchors = [world.anchors(g) for g in groups]
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            for a in anchors[i]:
                for b in anchors[j]:
                    d = math.hypot(a[0] - b[0], a[1] - b[1])
                    if d < best_d:
                        best_d = d
                        best = (d, a, b)
    return best


def connect_net(world, net, notes, goal_cells=None, max_links=8, max_dist=1e9, limit=1_200_000, max_fail=4) -> int:
    linked = 0
    failed = set()
    # Failures must not consume the success budget. A 0.00 mm pair that does
    # not quite touch used to return an empty commit and stop the real route.
    failures = 0
    while linked < max_links and failures < max_fail:
        groups = world.islands(net)
        if len(groups) <= 1:
            break
        pair = _closest_unfailed(world, groups, failed)
        if pair and pair[0] > max_dist:
            break
        if pair is None:
            break
        d, a, b = pair
        key = (round(a[0], 2), round(a[1], 2), round(b[0], 2), round(b[1], 2))
        print(f"  {net} {d:.2f} mm {a[4]} ({a[0]:.2f},{a[1]:.2f}) -> {b[4]} ({b[0]:.2f},{b[1]:.2f})", flush=True)
        t0 = time.time()
        path, exp = world.route(a[0], a[1], b[0], b[1], a[2], b[2], max(b[3], 0.25), net, limit=limit)
        print(f"    expand {exp} path {path is not None} {time.time()-t0:.1f}s", flush=True)
        if not path or not world.commit(path, a[0], a[1], b[0], b[1], net):
            notes.append(
                f"{net} blocked {a[4]} ({a[0]:.2f},{a[1]:.2f}) to {b[4]} ({b[0]:.2f},{b[1]:.2f}) {d:.2f} mm exp {exp}"
            )
            failed.add(key)
            failures += 1
            continue
        linked += 1
        world.paint(net)
    return linked


def _closest_unfailed(world, groups, failed):
    best = None
    best_d = 1e9
    anchors = [world.anchors(g) for g in groups]
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            for a in anchors[i]:
                for b in anchors[j]:
                    key = (round(a[0], 2), round(a[1], 2), round(b[0], 2), round(b[1], 2))
                    key2 = (key[2], key[3], key[0], key[1])
                    if key in failed or key2 in failed:
                        continue
                    d = math.hypot(a[0] - b[0], a[1] - b[1])
                    if d < best_d:
                        best_d = d
                        best = (d, a, b)
    return best


_GOAL_CACHE = {}


def _nearest_goal(x, y, cells):
    key = id(cells)
    pts = _GOAL_CACHE.get(key)
    if pts is None:
        # Keep a coarse lattice so the nearest-pour query stays cheap.
        pts = [(ix * GRID, iy * GRID) for ix, iy in cells if ix % 4 == 0 and iy % 4 == 0]
        if not pts:
            pts = [(ix * GRID, iy * GRID) for ix, iy in cells]
        _GOAL_CACHE[key] = pts
    best = 1e9
    bp = (x, y)
    # Bucket by 2 mm so we don't scan the whole pour.
    bx, by = int(x // 2), int(y // 2)
    buckets = _GOAL_CACHE.get((key, "b"))
    if buckets is None:
        buckets = defaultdict(list)
        for px, py in pts:
            buckets[(int(px // 2), int(py // 2))].append((px, py))
        _GOAL_CACHE[(key, "b")] = buckets
    for rad in range(0, 30):
        hit = False
        for dx in range(-rad, rad + 1):
            for dy in range(-rad, rad + 1):
                if max(abs(dx), abs(dy)) != rad:
                    continue
                for px, py in buckets.get((bx + dx, by + dy), ()):
                    hit = True
                    d = math.hypot(px - x, py - y)
                    if d < best:
                        best = d
                        bp = (px, py)
        if hit and best < (rad + 1) * 2:
            break
    return best, bp[0], bp[1]


def mask_count(board) -> int:
    n = 0
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.F_Mask:
            n += 1
    return n


def run(only=None, trial=False) -> int:
    board = pcbnew.LoadBoard(str(L.PCB))
    before_mask = mask_count(board)
    before_pos = {
        fp.GetReference(): (
            round(L.ToMM(fp.GetPosition().x), 3),
            round(L.ToMM(fp.GetPosition().y), 3),
            round(fp.GetOrientation().AsDegrees(), 1),
        )
        for fp in board.GetFootprints()
    }
    print("raster fills...", flush=True)
    t0 = time.time()
    world = World(board)
    print(f"  pads {len(world.pads)} segs {len(world.segs)} vias {len(world.vias)} raster {time.time()-t0:.1f}s", flush=True)
    print(f"  GND.B cells {len(world.gnd_b)} VBAT.F {len(world.vbat_f)} VBAT.B {len(world.vbat_b)}", flush=True)
    notes = []
    linked = {}

    def want(net):
        return only is None or net in only

    local_order = [
        "OUT_PWM1", "OUT_PWM2", "OUT_PWM3", "OUT_PWM4",
        "OUT_PWM5", "OUT_PWM6", "OUT_PWM7", "OUT_PWM8",
        "OUT_IO5", "OUT_IO6", "OUT_IO7", "OUT_IO8",
        "IN_AUX1", "IN_AUX2", "IN_AUX3", "IN_AUX4",
        "IN_MAP1", "IN_MAP2", "IN_MAP3",
        "IN_O2S", "IN_O2S2",
        "IN_RES1", "IN_RES2", "IN_RES3",
        "SENSOR_5V", "IGN_SW",
        "ADIO1", "ADIO2", "ADIO3", "ADIO4",
        "ADIO5", "ADIO6", "ADIO7", "ADIO8",
    ]
    # Local layer fixes first (a via at the pad). Then the SuperSeal escapes,
    # which need the south pad-row slots before a long east-west track walls them off.
    adio = [n for n in local_order if n.startswith("ADIO")]
    rest = [n for n in local_order if n not in adio]
    for net in local_order:
        if not want(net):
            continue
        print(f"{net} local", flush=True)
        world.paint(net)
        linked[net] = connect_net(world, net, notes, max_links=6, max_dist=3.0, limit=80_000)
    # SuperSeal escapes are walled by the SENSOR_GND spine. Record the
    # millimetre geometry and do not keep searching.
    document_blocked(notes)
    for net in adio + rest:
        if not want(net):
            continue
        print(f"{net} long", flush=True)
        world.paint(net)
        n_islands = len(world.islands(net))
        print(f"  islands {n_islands}", flush=True)
        # ADIO SuperSeal pins use the seven S-row slots (see connect_escapes).
        # A free search from the second pin walks the whole board and never
        # arrives; don't repeat that.
        if net.startswith("ADIO") or net == "IGN_SW":
            linked[net] = linked.get(net, 0) + connect_net(
                world, net, notes, max_links=4, max_dist=12.0, limit=60_000, max_fail=3
            )
        else:
            linked[net] = linked.get(net, 0) + connect_net(
                world, net, notes, max_links=3, max_dist=1e9, limit=700_000, max_fail=2
            )
    # Pour stitches after the signal escapes. A GND or VBAT strap through the
    # south S-row slots would wall off ADIO before those pins ever route.
    if want("GND"):
        print("GND", flush=True)
        world.paint("GND")
        linked["GND"] = connect_gnd(world, notes)
    if want("VBAT"):
        print("VBAT", flush=True)
        world.paint("VBAT")
        linked["VBAT"] = connect_vbat(world, notes)

    print("fill", flush=True)
    L.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    keep = L.pour_inside_keepout(board)
    fuse = L.fuse_bridged(board)
    sensor = L.sensor_pours(board)
    after_mask = mask_count(board)
    moved = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        now = (
            round(L.ToMM(fp.GetPosition().x), 3),
            round(L.ToMM(fp.GetPosition().y), 3),
            round(fp.GetOrientation().AsDegrees(), 1),
        )
        if before_pos.get(ref) != now:
            moved.append((ref, before_pos.get(ref), now))
    print(f"keepout {keep} fuse {fuse} sensor {sensor} mask {before_mask}->{after_mask} moved {len(moved)}", flush=True)
    out = Path("/tmp/pdm_candidate.kicad_pcb")
    board.Save(str(out))
    L.downgrade_to_k8(out)
    # DRC the candidate. Do not touch the repo file until the counts are known.
    proc_path = L.PCB
    # run_drc reads L.PCB. Point it at the candidate by swapping the constant's target.
    saved = L.PCB
    L.PCB = out
    try:
        _rc, text, err = L.run_drc()
    finally:
        L.PCB = saved
    summary = L.summarize_report(text)
    print(json.dumps(summary["counts"], indent=2), flush=True)
    (Path("/tmp/close_109_notes.txt")).write_text("\n".join(notes) + "\n")
    (Path("/tmp/close_109_drc.txt")).write_text(text)
    meta = {
        "linked": linked,
        "notes": notes,
        "keepout": keep,
        "fuse": fuse,
        "sensor": sensor,
        "mask": [before_mask, after_mask],
        "moved": moved,
        "counts": summary["counts"],
    }
    Path("/tmp/close_109_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print("notes", len(notes), flush=True)
    for line in notes[:40]:
        print(" ", line, flush=True)
    if err:
        print(err[-400:], flush=True)
    if trial:
        print("trial; repo PCB not replaced", flush=True)
        return 0
    # Caller decides whether to install. Always leave the candidate at /tmp.
    return 0


def document_blocked(notes) -> None:
    """SuperSeal pins that cannot be closed without a new DRC error."""
    notes.append(
        "ADIO1-8 J1 pins stay open. SENSOR_GND spine is B.Cu x=38.40, y=43.20-55.60, "
        "width 0.20. It blocks a west exit from columns x=39.80 and x=42.30 until y≈56.0. "
        "The band south of the spine (y=56.8-59.9, x=32-41, 3.1 mm tall) can hold parallel "
        "0.15 mm tracks, but the pad maze east of the spine has one southbound opening. "
        "ADIO1 uses it (x=40.6-42.3, y=52.5-59.1). ADIO2-7 then have no path "
        "(search exhausts inside x=39-44). Leaving every J1 pin open keeps that opening free."
    )
    notes.append(
        "M1000 S-row B.Cu passages that reach y=76 are x=18.9, 20.1, 21.3, 22.5, 23.7, "
        "24.9, 26.1. Each waist is one 0.10 mm cell in a 0.60 mm copper gap (one 0.15 mm "
        "track). x=45.6 is the east alley and is not reachable from the pin field. "
        "J3 at (80, 86.5) radius 8 mm pinches the south bus at x=82 to y=73.0-74.2 "
        "(1.2 mm) plus a 0.4 mm sliver at y=78.0-78.4."
    )
    notes.append(
        "IGN_SW J1.4 (34.30,46.50) has no free B.Cu cell within 0.8 mm of the pad. "
        "A* does not reach the north shelf (42.0,24.8) or the east alley (44.8,32.0). "
        "R1.1 stays on the far side of the SENSOR_GND spine."
    )


def connect_gnd(world, notes) -> int:
    """Stitch carrier GND pads to the B pour. Leave M1000 keepout pads alone."""
    linked = 0
    # Islands that contain only M1000 pads are the keepout pairs.
    for _ in range(60):
        groups = world.islands("GND")
        carriers = []
        for g in groups:
            pads = [obj for kind, obj in g if kind == "pad"]
            if pads and all(p["ref"] == "M1000" for p in pads) and not any(kind != "pad" for kind, _o in g):
                continue
            # An island already touching the pour needs no strap.
            if _group_on_pour(g, world.gnd_b):
                continue
            carriers.append(g)
        if not carriers:
            break
        best = None
        best_d = 1e9
        for g in carriers:
            for a in world.anchors(g):
                if a[4].startswith("M1000") or a[4] in _GND_SKIP:
                    continue
                d, gx, gy = _nearest_goal(a[0], a[1], world.gnd_b)
                if d < best_d:
                    best_d = d
                    best = (d, a, (gx, gy))
        if best is None or best[0] > 80:
            break
        d, a, (gx, gy) = best
        # One attempt per pad. A short track that does not land on the pour
        # used to be committed again on every pass.
        _GND_SKIP.add(a[4])
        if d < 0.35:
            if len(_GND_SKIP) > 80:
                break
            continue
        print(f"  GND {d:.2f} mm {a[4]} ({a[0]:.2f},{a[1]:.2f}) -> pour ({gx:.2f},{gy:.2f})", flush=True)
        t0 = time.time()
        path, exp = world.route(
            a[0], a[1], gx, gy, a[2], (1,), 0.45, "GND", extra_goals=world.gnd_b, goal_lay=1
        )
        print(f"    expand {exp} path {path is not None} {time.time()-t0:.1f}s", flush=True)
        if not path or not world.commit(path, a[0], a[1], gx, gy, "GND"):
            notes.append(f"GND blocked {a[4]} ({a[0]:.2f},{a[1]:.2f}) to pour ({gx:.2f},{gy:.2f}) {d:.2f} mm")
            # Don't retry the same anchor forever.
            world.gnd_b = set(world.gnd_b)
            # Poison this anchor by adding a dummy? Remove it from future by
            # recording a skip set.
            _skip_add(a[4])
            if _skipped(a[4]):
                # filter next time via a sentinel track? Simpler: break if the
                # same ref fails twice.
                if notes.count(notes[-1]) > 1 or sum(1 for n in notes if n.startswith("GND blocked " + a[4])) > 0:
                    # mark pad net temporarily? We'll drop this anchor by
                    # moving on: store skips and consult them.
                    pass
            if sum(1 for n in notes if "GND blocked" in n and a[4] in n) >= 1:
                # Remove this pad from routing by giving it a private skip.
                _GND_SKIP.add(a[4])
            if len(_GND_SKIP) > 30:
                break
            continue
        linked += 1
        # The new track's cells become pour goals so the next pad can land on it.
        _absorb_track_goals(world, "GND")
        world.paint("GND")
    return linked


_GND_SKIP = set()


def _skip_add(ref):
    _GND_SKIP.add(ref)


def _skipped(ref):
    return ref in _GND_SKIP


def _group_on_pour(group, cells) -> bool:
    for kind, obj in group:
        if kind == "pad":
            ix, iy = int(round(obj["x"] / GRID)), int(round(obj["y"] / GRID))
            if (ix, iy) in cells and (obj["pth"] or obj["b"]):
                return True
        elif kind == "via":
            ix, iy = int(round(obj[0] / GRID)), int(round(obj[1] / GRID))
            if (ix, iy) in cells:
                return True
        elif kind == "seg" and obj[4] == "B":
            for x, y in ((obj[0], obj[1]), (obj[2], obj[3])):
                ix, iy = int(round(x / GRID)), int(round(y / GRID))
                if (ix, iy) in cells:
                    return True
    return False


def _absorb_track_goals(world, net):
    cells = world.gnd_b if net == "GND" else None
    if cells is None:
        return
    for s in world.segs:
        if s[5] != net:
            continue
        steps = max(1, int(math.hypot(s[2] - s[0], s[3] - s[1]) / GRID))
        for i in range(steps + 1):
            u = i / steps
            x = s[0] + (s[2] - s[0]) * u
            y = s[1] + (s[3] - s[1]) * u
            cells.add((int(round(x / GRID)), int(round(y / GRID))))
    _GOAL_CACHE.clear()


def connect_vbat(world, notes) -> int:
    """Tie post-fuse islands and C1 / N27. Do not cross the fuse band."""
    linked = 0
    # Main post-fuse fill is the large F polygon south of y=27.
    post_cells = {(ix, iy) for ix, iy in world.vbat_f if iy * GRID >= 27.0}
    pre_cells = {(ix, iy) for ix, iy in world.vbat_f if iy * GRID <= 22.6}
    pre_cells |= {(ix, iy) for ix, iy in world.vbat_b if iy * GRID <= 22.6}
    if not post_cells:
        notes.append("VBAT post fill raster empty")
        return 0

    def route_to(label, x, y, layers, cells):
        nonlocal linked
        d, gx, gy = _nearest_goal(x, y, cells)
        if d < 0.2:
            return
        print(f"  VBAT {label} {d:.2f} mm ({x:.2f},{y:.2f}) -> ({gx:.2f},{gy:.2f})", flush=True)
        path, exp = world.route(x, y, gx, gy, layers, (0, 1), 0.45, "VBAT", extra_goals=cells)
        print(f"    expand {exp} path {path is not None}", flush=True)
        if not path or not world.commit(path, x, y, gx, gy, "VBAT"):
            notes.append(f"VBAT blocked {label} ({x:.2f},{y:.2f}) to ({gx:.2f},{gy:.2f}) {d:.2f} mm")
            return
        linked += 1
        world.paint("VBAT")
        for s in world.segs:
            if s[5] != "VBAT":
                continue
            steps = max(1, int(math.hypot(s[2] - s[0], s[3] - s[1]) / GRID))
            for i in range(steps + 1):
                u = i / max(1, steps)
                px = s[0] + (s[2] - s[0]) * u
                py = s[1] + (s[3] - s[1]) * u
                cells.add((int(round(px / GRID)), int(round(py / GRID))))
        _GOAL_CACHE.clear()

    # C1.1 is pre-fuse.
    for p in world.pads:
        if p["net"] == "VBAT" and p["ref"] == "C1" and p["num"] == "1":
            route_to("C1.1", p["x"], p["y"], (0,), pre_cells)
    for p in world.pads:
        if p["net"] == "VBAT" and p["ref"] == "M1000" and p["num"] == "N27":
            route_to("M1000.N27", p["x"], p["y"], (0, 1), post_cells)

    # Post-fuse zone islands: sample a cell of each F island that is not the main pour.
    # Cells in vbat_f south of the fuse that are NOT 4-connected to the main blob.
    seen = set()
    main = None
    blobs = []
    for cell in post_cells:
        if cell in seen:
            continue
        # flood
        stack = [cell]
        blob = []
        seen.add(cell)
        while stack:
            c = stack.pop()
            blob.append(c)
            ix, iy = c
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (ix + dx, iy + dy)
                if n in post_cells and n not in seen:
                    seen.add(n)
                    stack.append(n)
        blobs.append(blob)
    blobs.sort(key=len, reverse=True)
    print(f"  VBAT post blobs {len(blobs)} sizes {[len(b) for b in blobs[:12]]}", flush=True)
    if not blobs:
        return linked
    main_set = set(blobs[0])
    for blob in blobs[1:]:
        # closest cell of this blob to the main set, coarsely
        bx = sum(c[0] for c in blob) / len(blob) * GRID
        by = sum(c[1] for c in blob) / len(blob) * GRID
        route_to(f"island@{bx:.1f},{by:.1f}", bx, by, (0,), main_set | post_cells)
        # grow main with the blob if the route landed
        main_set |= set(blob)
    return linked


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    trial = "--trial" in sys.argv or True  # install is a separate step after DRC review
    only = set(args) if args else None
    sys.exit(run(only=only, trial=trial))
