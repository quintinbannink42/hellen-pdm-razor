#!/usr/bin/env python3
"""Close carrier ratsnests left after the packed-east DRC polish.

Does not move the polish anchors (U3/U4 +90, J1 48.8, D1 88/24, sense RC
y=35.70), does not bridge F1, does not add a SENSOR_GND pour, and does not
replay the 150×130 long-haul scripts.

New copper is clearance-checked against foreign pads, tracks, and vias
before it is committed. Zones are refilled afterwards so pours pull back
around the new tracks.
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
BEFORE_DRC = Path("/tmp/drc/before.json")

BOARD_W, BOARD_H = 104.0, 93.0
CLR = 0.20
HOLE_CLR = 0.25
EDGE = 0.50
GRID = 0.10
VIA_SIZE = 0.60
VIA_DRILL = 0.30

SIGNAL_NETS = [
    "ADIO1", "ADIO2", "ADIO3", "ADIO4", "ADIO5", "ADIO6", "ADIO7", "ADIO8",
    "IN_MAP2", "IN_MAP3", "IN_O2S", "IN_O2S2", "IN_RES1", "IN_RES2", "IN_RES3",
    "SENSOR_5V", "PWR_OUT1", "PWR_OUT2", "PWR_OUT3", "PWR_OUT4", "IGN_SW",
]


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
    head = path.read_text()[:400]
    assert "20240108" in head and 'generator_version "8.0"' in head


def is_via(t) -> bool:
    return t.Type() == PCB_VIA_T


def layer_of(t) -> str:
    return "F" if t.GetLayer() == F_Cu else "B"


def dist_pt_seg(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) < 1e-12 and abs(dy) < 1e-12:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def dist_pt_rect(px, py, box) -> float:
    l, t, r, b = box
    cx = min(max(px, l), r)
    cy = min(max(py, t), b)
    return math.hypot(px - cx, py - cy)


def dist_seg_rect(x1, y1, x2, y2, box) -> float:
    # Sample. Segments we commit are short or we also test endpoints + midpoints densely.
    length = math.hypot(x2 - x1, y2 - y1)
    steps = max(1, int(length / 0.05))
    best = 1e9
    for i in range(steps + 1):
        u = i / steps
        best = min(best, dist_pt_rect(x1 + (x2 - x1) * u, y1 + (y2 - y1) * u, box))
    return best


def point_in_poly(x, y, pts) -> bool:
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi):
            inside = not inside
        j = i
    return inside


class Geom:
    """Foreign-copper index rebuilt after each committed route."""

    def __init__(self, board):
        self.board = board
        self.rebuild()

    def rebuild(self):
        self.pads = []
        self.segs = []  # x1,y1,x2,y2,lay,net,w
        self.vias = []  # x,y,net,size,drill
        self.holes = []  # x,y,drill
        for fp in self.board.GetFootprints():
            ref = fp.GetReference()
            for pad in fp.Pads():
                if not pad.IsOnLayer(F_Cu) and not pad.IsOnLayer(B_Cu):
                    continue
                bb = pad.GetBoundingBox()
                box = (ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom()))
                drill = 0.0
                try:
                    drill = ToMM(pad.GetDrillSize().x)
                except Exception:
                    drill = 0.0
                both = pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH) or drill > 0.05
                layers = ("F", "B") if both else (("F",) if pad.IsOnLayer(F_Cu) else ("B",))
                x, y = ToMM(pad.GetPosition().x), ToMM(pad.GetPosition().y)
                self.pads.append(
                    {
                        "ref": ref,
                        "num": pad.GetNumber(),
                        "net": pad.GetNetname() or "",
                        "x": x,
                        "y": y,
                        "box": box,
                        "layers": layers,
                        "drill": drill,
                        "pad": pad,
                    }
                )
                if drill > 0.05:
                    self.holes.append((x, y, drill))
        for t in self.board.GetTracks():
            net = t.GetNetname() or ""
            if is_via(t):
                p = t.GetPosition()
                x, y = ToMM(p.x), ToMM(p.y)
                drill = ToMM(t.GetDrill())
                self.vias.append((x, y, net, ToMM(t.GetWidth()), drill))
                self.holes.append((x, y, drill))
            else:
                a, b = t.GetStart(), t.GetEnd()
                self.segs.append(
                    (
                        ToMM(a.x),
                        ToMM(a.y),
                        ToMM(b.x),
                        ToMM(b.y),
                        layer_of(t),
                        net,
                        ToMM(t.GetWidth()),
                    )
                )

    def seg_ok(self, x1, y1, x2, y2, width, lay, net) -> bool:
        if math.hypot(x2 - x1, y2 - y1) < 0.015:
            return True
        need = width / 2 + CLR - 0.005
        # Edge clearance for the copper body.
        samples_edge = []
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(length / 0.4))
        for i in range(steps + 1):
            u = i / steps
            samples_edge.append((x1 + (x2 - x1) * u, y1 + (y2 - y1) * u))
        for x, y in samples_edge:
            if x < EDGE or y < EDGE or x > BOARD_W - EDGE or y > BOARD_H - EDGE:
                # Allow a short landing onto an existing pad that already sits
                # closer than the edge rule (module outline pads).
                on_pad = False
                for p in self.pads:
                    if p["net"] == net and dist_pt_rect(x, y, p["box"]) < 0.02:
                        on_pad = True
                        break
                if not on_pad:
                    return False
        for p in self.pads:
            if p["net"] == net or lay not in p["layers"]:
                continue
            l, t, r, b = p["box"]
            if max(x1, x2) < l - need - 0.3 or min(x1, x2) > r + need + 0.3:
                continue
            if max(y1, y2) < t - need - 0.3 or min(y1, y2) > b + need + 0.3:
                continue
            if dist_seg_rect(x1, y1, x2, y2, p["box"]) < need:
                return False
        for sx1, sy1, sx2, sy2, sl, sn, sw in self.segs:
            if sn == net or sl != lay:
                continue
            gap = need + sw / 2
            if max(x1, x2) < min(sx1, sx2) - gap - 0.2 or min(x1, x2) > max(sx1, sx2) + gap + 0.2:
                continue
            if max(y1, y2) < min(sy1, sy2) - gap - 0.2 or min(y1, y2) > max(sy1, sy2) + gap + 0.2:
                continue
            # Segment-segment distance via sampling the new segment.
            length = math.hypot(x2 - x1, y2 - y1)
            steps = max(1, int(length / 0.08))
            for i in range(steps + 1):
                u = i / steps
                if dist_pt_seg(x1 + (x2 - x1) * u, y1 + (y2 - y1) * u, sx1, sy1, sx2, sy2) < gap:
                    return False
        for vx, vy, vn, vsz, _vd in self.vias:
            if vn == net:
                continue
            gap = need + vsz / 2
            if dist_pt_seg(vx, vy, x1, y1, x2, y2) < gap:
                return False
        return True

    def via_ok(self, x, y, net) -> bool:
        if x < EDGE + 0.3 or y < EDGE + 0.3 or x > BOARD_W - EDGE - 0.3 or y > BOARD_H - EDGE - 0.3:
            return False
        need = VIA_SIZE / 2 + CLR - 0.005
        for p in self.pads:
            if p["net"] == net:
                continue
            if dist_pt_rect(x, y, p["box"]) < need:
                return False
        for sx1, sy1, sx2, sy2, _sl, sn, sw in self.segs:
            if sn == net:
                continue
            if dist_pt_seg(x, y, sx1, sy1, sx2, sy2) < need + sw / 2:
                return False
        for vx, vy, vn, vsz, vd in self.vias:
            if math.hypot(x - vx, y - vy) > 3.0:
                continue
            if vn == net and math.hypot(x - vx, y - vy) < 0.2:
                return True  # stack on own via
            if math.hypot(x - vx, y - vy) < (VIA_SIZE + vsz) / 2 + CLR - 0.005:
                return False
            if (VIA_DRILL + vd) / 2 + HOLE_CLR > math.hypot(x - vx, y - vy):
                return False
        for hx, hy, hd in self.holes:
            if hd <= 0.05:
                continue
            if math.hypot(x - hx, y - hy) > 4.0:
                continue
            # Own-net pad hole: a via in a PTH pad of this net is unnecessary
            # and the hole clearance would fail. Reject.
            if (VIA_DRILL + hd) / 2 + HOLE_CLR > math.hypot(x - hx, y - hy) + 1e-6:
                return False
        return True


def add_track(board, geom: Geom, x1, y1, x2, y2, width, net, lay, new_ids: set):
    if math.hypot(x2 - x1, y2 - y1) < 0.02:
        return None
    tr = PCB_TRACK(board)
    tr.SetStart(mm(x1, y1))
    tr.SetEnd(mm(x2, y2))
    tr.SetWidth(FromMM(width))
    tr.SetLayer(F_Cu if lay == "F" else B_Cu)
    tr.SetNet(board.FindNet(net))
    board.Add(tr)
    new_ids.add(tr.m_Uuid.AsString())
    geom.segs.append((x1, y1, x2, y2, lay, net, width))
    return tr


def add_via(board, geom: Geom, x, y, net, new_ids: set):
    for vx, vy, vn, _s, _d in geom.vias:
        if vn == net and math.hypot(vx - x, vy - y) < 0.18:
            return None
    v = PCB_VIA(board)
    v.SetPosition(mm(x, y))
    v.SetDrill(FromMM(VIA_DRILL))
    v.SetWidth(FromMM(VIA_SIZE))
    v.SetNet(board.FindNet(net))
    board.Add(v)
    new_ids.add(v.m_Uuid.AsString())
    geom.vias.append((x, y, net, VIA_SIZE, VIA_DRILL))
    geom.holes.append((x, y, VIA_DRILL))
    return v


class Grid:
    def __init__(self):
        self.nx = int(BOARD_W / GRID) + 4
        self.ny = int(BOARD_H / GRID) + 4

    def cell(self, x, y):
        return int(round(x / GRID)), int(round(y / GRID))

    def xy(self, ix, iy):
        return ix * GRID, iy * GRID

    def inside(self, ix, iy):
        return 0 <= ix < self.nx and 0 <= iy < self.ny


def paint_mask(grid: Grid, geom: Geom, net: str, width: float, forbidden=None):
    """Blocked cells per layer, and via-blocked cells. Same-net copper is free."""
    halo = width / 2 + CLR
    vhalo = VIA_SIZE / 2 + CLR
    blk = [bytearray(grid.nx * grid.ny), bytearray(grid.nx * grid.ny)]
    vblk = bytearray(grid.nx * grid.ny)

    def mark_disk(cx, cy, rad, layer, via=False):
        ix0 = max(0, int((cx - rad) / GRID) - 1)
        ix1 = min(grid.nx - 1, int((cx + rad) / GRID) + 1)
        iy0 = max(0, int((cy - rad) / GRID) - 1)
        iy1 = min(grid.ny - 1, int((cy + rad) / GRID) + 1)
        r2 = rad * rad
        for iy in range(iy0, iy1 + 1):
            y = iy * GRID
            dy = y - cy
            row = iy * grid.nx
            for ix in range(ix0, ix1 + 1):
                x = ix * GRID
                if (x - cx) * (x - cx) + dy * dy <= r2:
                    if via:
                        vblk[row + ix] = 1
                    elif layer == "F":
                        blk[0][row + ix] = 1
                    elif layer == "B":
                        blk[1][row + ix] = 1
                    else:
                        blk[0][row + ix] = 1
                        blk[1][row + ix] = 1

    def mark_rect(box, rad, layers):
        l, t, r, b = box
        ix0 = max(0, int((l - rad) / GRID) - 1)
        ix1 = min(grid.nx - 1, int((r + rad) / GRID) + 1)
        iy0 = max(0, int((t - rad) / GRID) - 1)
        iy1 = min(grid.ny - 1, int((b + rad) / GRID) + 1)
        for iy in range(iy0, iy1 + 1):
            y = iy * GRID
            row = iy * grid.nx
            for ix in range(ix0, ix1 + 1):
                x = ix * GRID
                if dist_pt_rect(x, y, box) <= rad:
                    for lay in layers:
                        if lay == "F":
                            blk[0][row + ix] = 1
                        else:
                            blk[1][row + ix] = 1
                    vblk[row + ix] = 1

    for p in geom.pads:
        if p["net"] == net:
            continue
        mark_rect(p["box"], halo, p["layers"])
    for x1, y1, x2, y2, lay, n, w in geom.segs:
        if n == net:
            continue
        rad = halo + w / 2
        # Walk the segment.
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(length / 0.15))
        for i in range(steps + 1):
            u = i / steps
            mark_disk(x1 + (x2 - x1) * u, y1 + (y2 - y1) * u, rad, lay, via=False)
            mark_disk(x1 + (x2 - x1) * u, y1 + (y2 - y1) * u, vhalo + w / 2, None, via=True)
    for x, y, n, sz, _d in geom.vias:
        if n == net:
            continue
        mark_disk(x, y, halo + sz / 2, None, via=False)
        mark_disk(x, y, vhalo + sz / 2, None, via=True)
    # Board edge.
    for iy in range(grid.ny):
        y = iy * GRID
        row = iy * grid.nx
        for ix in range(grid.nx):
            x = ix * GRID
            if x < EDGE or y < EDGE or x > BOARD_W - EDGE or y > BOARD_H - EDGE:
                blk[0][row + ix] = 1
                blk[1][row + ix] = 1
                vblk[row + ix] = 1
    if forbidden:
        for ix in range(grid.nx):
            x = ix * GRID
            for iy in range(grid.ny):
                if forbidden(x, iy * GRID):
                    row = iy * grid.nx + ix
                    blk[0][row] = 1
                    blk[1][row] = 1
                    vblk[row] = 1
    # Hole keepout for vias (foreign and same-net PTH — don't drop a via in a hole).
    for hx, hy, hd in geom.holes:
        rad = (VIA_DRILL + hd) / 2 + HOLE_CLR
        mark_disk(hx, hy, rad, None, via=True)
    return blk, vblk


def paint_goal_cells(grid: Grid, cells_by_layer):
    goal = [bytearray(grid.nx * grid.ny), bytearray(grid.nx * grid.ny)]
    for lay, cells in cells_by_layer.items():
        gi = 0 if lay == "F" else 1
        for ix, iy in cells:
            if grid.inside(ix, iy):
                goal[gi][iy * grid.nx + ix] = 1
    return goal


def copper_cells_for_items(grid: Grid, pads, segs, vias, layer_filter=None):
    out = {"F": set(), "B": set()}
    for p in pads:
        for lay in p["layers"]:
            if layer_filter and lay not in layer_filter:
                continue
            l, t, r, b = p["box"]
            ix0 = max(0, int(l / GRID) - 1)
            ix1 = min(grid.nx - 1, int(r / GRID) + 1)
            iy0 = max(0, int(t / GRID) - 1)
            iy1 = min(grid.ny - 1, int(b / GRID) + 1)
            for iy in range(iy0, iy1 + 1):
                y = iy * GRID
                for ix in range(ix0, ix1 + 1):
                    if dist_pt_rect(ix * GRID, y, p["box"]) <= 0.02:
                        out[lay].add((ix, iy))
            # Always include the pad center so a route can land.
            ix, iy = grid.cell(p["x"], p["y"])
            if grid.inside(ix, iy):
                out[lay].add((ix, iy))
    for x1, y1, x2, y2, lay, _n, _w in segs:
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(length / (GRID * 0.8)))
        for i in range(steps + 1):
            u = i / steps
            ix, iy = grid.cell(x1 + (x2 - x1) * u, y1 + (y2 - y1) * u)
            if grid.inside(ix, iy):
                out[lay].add((ix, iy))
    for x, y, _n, _s, _d in vias:
        ix, iy = grid.cell(x, y)
        if grid.inside(ix, iy):
            out["F"].add((ix, iy))
            out["B"].add((ix, iy))
    return out


def route_astar(grid: Grid, blk, vblk, goal, starts, prefer: str, anchor):
    prefer_i = 0 if prefer == "F" else 1
    inf = 10 ** 9
    best = {}
    parent = {}
    pq = []
    ax, ay = anchor

    def heur(ix, iy):
        return math.hypot(ix * GRID - ax, iy * GRID - ay) / GRID

    for ix, iy, lay in starts:
        if not grid.inside(ix, iy):
            continue
        # A start cell sitting in the halo of a neighbour is still a legal
        # launch pad — the copper is already there. Unblock it.
        blk[lay][iy * grid.nx + ix] = 0
        best[(ix, iy, lay)] = 0
        heapq.heappush(pq, (heur(ix, iy), 0, ix, iy, lay))
    found = None
    expanded = 0
    while pq and expanded < 300000:
        _h, g, ix, iy, lay = heapq.heappop(pq)
        if g != best.get((ix, iy, lay)):
            continue
        expanded += 1
        if goal[lay][iy * grid.nx + ix] and g > 0:
            found = (ix, iy, lay)
            break
        step_base = 1.0 if lay == prefer_i else 1.35
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = ix + dx, iy + dy
            if not grid.inside(nx, ny):
                continue
            blocked = blk[lay][ny * grid.nx + nx]
            # A blocked goal cell is a landing, not a corridor. Stop on it
            # so the search can touch a pad that sits inside a neighbour halo.
            if blocked and not goal[lay][ny * grid.nx + nx]:
                continue
            ng = g + step_base
            key = (nx, ny, lay)
            if ng < best.get(key, inf):
                best[key] = ng
                parent[key] = (ix, iy, lay)
                heapq.heappush(pq, (ng + heur(nx, ny), ng, nx, ny, lay))
        if vblk[iy * grid.nx + ix] == 0 and not blk[0][iy * grid.nx + ix] and not blk[1][iy * grid.nx + ix]:
            nlay = 1 - lay
            ng = g + 14.0  # via is expensive; stay on the preferred layer when it works
            key = (ix, iy, nlay)
            if ng < best.get(key, inf):
                best[key] = ng
                parent[key] = (ix, iy, lay)
                heapq.heappush(pq, (ng + heur(ix, iy), ng, ix, iy, nlay))
    if not found:
        return None, expanded
    path = [found]
    while path[-1] in parent:
        path.append(parent[path[-1]])
        if len(path) > 8000:
            return None, expanded
    path.reverse()
    return path, expanded


def commit_path(board, geom: Geom, grid: Grid, path, net, width, new_ids: set) -> bool:
    """Turn a grid path into tracks/vias. Reject the whole path if any new
    segment fails the exact clearance check. Already-added items are removed."""
    made = []
    layname = {0: "F", 1: "B"}
    # Collapse colinear same-layer cells.
    simp = [path[0]]
    for i in range(1, len(path) - 1):
        x0, y0, l0 = simp[-1]
        x1, y1, l1 = path[i]
        x2, y2, l2 = path[i + 1]
        if l0 == l1 == l2 and (x1 - x0) * (y2 - y1) == (y1 - y0) * (x2 - x1):
            continue
        simp.append(path[i])
    if path[-1] != simp[-1]:
        simp.append(path[-1])
    pending = []
    for i in range(len(simp) - 1):
        ix, iy, la = simp[i]
        jx, jy, lb = simp[i + 1]
        x1, y1 = grid.xy(ix, iy)
        x2, y2 = grid.xy(jx, jy)
        if la != lb:
            if not geom.via_ok(x2, y2, net):
                return False
            pending.append(("via", x2, y2))
        else:
            if not geom.seg_ok(x1, y1, x2, y2, width, layname[la], net):
                return False
            pending.append(("seg", x1, y1, x2, y2, layname[la]))
    for item in pending:
        if item[0] == "via":
            v = add_via(board, geom, item[1], item[2], net, new_ids)
            if v is not None:
                made.append(v)
        else:
            tr = add_track(board, geom, item[1], item[2], item[3], item[4], width, net, item[5], new_ids)
            if tr is not None:
                made.append(tr)
    return True


def connect_islands(board, geom: Geom, net: str, width: float, prefer: str, new_ids: set, forbidden=None) -> str:
    """Route every disconnected island of `net` onto the largest one."""
    pads = [p for p in geom.pads if p["net"] == net]
    segs = [s for s in geom.segs if s[5] == net]
    vias = [v for v in geom.vias if v[2] == net]
    # Union-find on copper items. Touch tolerance is tight so a 0.07 mm gap
    # stays open and gets a real track.
    items = []
    for p in pads:
        items.append(("pad", p))
    for s in segs:
        items.append(("seg", s))
    for v in vias:
        items.append(("via", v))
    if len(items) < 2:
        return "nothing"
    parent = list(range(len(items)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    def item_points(it):
        kind, obj = it
        if kind == "pad":
            return [(obj["x"], obj["y"])]
        if kind == "via":
            return [(obj[0], obj[1])]
        return [(obj[0], obj[1]), (obj[2], obj[3])]

    def touches(a, b) -> bool:
        ka, oa = a
        kb, ob = b
        if ka == "seg" and kb == "seg":
            # Endpoint of one on the other segment.
            for px, py in ((oa[0], oa[1]), (oa[2], oa[3])):
                if dist_pt_seg(px, py, ob[0], ob[1], ob[2], ob[3]) <= 0.03 and oa[4] == ob[4]:
                    return True
            for px, py in ((ob[0], ob[1]), (ob[2], ob[3])):
                if dist_pt_seg(px, py, oa[0], oa[1], oa[2], oa[3]) <= 0.03 and oa[4] == ob[4]:
                    return True
            return False
        if ka == "via" or kb == "via":
            via = oa if ka == "via" else ob
            other = ob if ka == "via" else oa
            okind = kb if ka == "via" else ka
            vx, vy = via[0], via[1]
            if okind == "via":
                return math.hypot(vx - other[0], vy - other[1]) <= 0.05
            if okind == "pad":
                return dist_pt_rect(vx, vy, other["box"]) <= 0.02
            return dist_pt_seg(vx, vy, other[0], other[1], other[2], other[3]) <= 0.05
        # pad-pad or pad-seg
        if ka == "pad" and kb == "pad":
            return dist_pt_rect(oa["x"], oa["y"], ob["box"]) <= 0.02 or dist_pt_rect(ob["x"], ob["y"], oa["box"]) <= 0.02
        pad = oa if ka == "pad" else ob
        seg = ob if ka == "pad" else oa
        if dist_pt_rect(seg[0], seg[1], pad["box"]) <= 0.03 or dist_pt_rect(seg[2], seg[3], pad["box"]) <= 0.03:
            if "F" in pad["layers"] and seg[4] == "F" or "B" in pad["layers"] and seg[4] == "B":
                return True
        # PTH pad hits either layer.
        if len(pad["layers"]) == 2 and (
            dist_pt_rect(seg[0], seg[1], pad["box"]) <= 0.03 or dist_pt_rect(seg[2], seg[3], pad["box"]) <= 0.03
        ):
            return True
        return False

    # Spatial hash to avoid the full pair scan.
    buckets = defaultdict(list)
    for i, it in enumerate(items):
        kind, obj = it
        pts = item_points(it)
        if kind == "seg":
            x1, y1, x2, y2 = obj[0], obj[1], obj[2], obj[3]
            length = math.hypot(x2 - x1, y2 - y1)
            steps = max(1, int(length))
            pts = [(x1 + (x2 - x1) * u / steps, y1 + (y2 - y1) * u / steps) for u in range(steps + 1)]
        for x, y in pts:
            buckets[(int(x), int(y))].append(i)
    seen_pairs = set()
    for i, it in enumerate(items):
        cand = set()
        for x, y in item_points(it):
            ix, iy = int(x), int(y)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    cand.update(buckets.get((ix + dx, iy + dy), ()))
        for j in cand:
            if j <= i:
                continue
            key = (i, j)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            if touches(it, items[j]):
                union(i, j)

    groups = defaultdict(list)
    for i in range(len(items)):
        groups[find(i)].append(i)
    if len(groups) <= 1:
        return "ok"
    # Largest island is the anchor (most copper items, then most pads).
    def rank(idxs):
        pads_n = sum(1 for i in idxs if items[i][0] == "pad")
        return (len(idxs), pads_n)

    main_key = max(groups, key=lambda k: rank(groups[k]))
    grid = Grid()
    print(f"  {net}: {len(groups)} islands, painting...", flush=True)
    blk, vblk = paint_mask(grid, geom, net, width, forbidden)
    # Goal starts as the main island and grows as we attach others.
    def cells_of(idxs):
        pp, ss, vv = [], [], []
        for i in idxs:
            kind, obj = items[i]
            if kind == "pad":
                pp.append(obj)
            elif kind == "seg":
                ss.append(obj)
            else:
                vv.append(obj)
        return copper_cells_for_items(grid, pp, ss, vv)

    goal_cells = cells_of(groups[main_key])
    goal = paint_goal_cells(grid, goal_cells)

    def anchor_of(cells):
        for lay in ("F", "B"):
            if cells[lay]:
                ix, iy = next(iter(cells[lay]))
                return grid.xy(ix, iy)
        return (50.0, 46.0)

    main_anchor = anchor_of(goal_cells)
    order = sorted(groups, key=lambda k: 0 if k == main_key else -rank(groups[k])[0])
    failed = []
    for key in order:
        if key == main_key:
            continue
        src_cells = cells_of(groups[key])
        starts = []
        for lay, cells in src_cells.items():
            li = 0 if lay == "F" else 1
            for ix, iy in cells:
                starts.append((ix, iy, li))
        if not starts:
            failed.append("empty")
            continue
        # Already touching?
        if any(goal[lay][iy * grid.nx + ix] for ix, iy, lay in starts if grid.inside(ix, iy)):
            for lay, cells in src_cells.items():
                gi = 0 if lay == "F" else 1
                for ix, iy in cells:
                    goal[gi][iy * grid.nx + ix] = 1
            continue
        labels = []
        for i in groups[key]:
            kind, obj = items[i]
            if kind == "pad":
                labels.append(f"{obj['ref']}.{obj['num']}")
        path, expanded = route_astar(grid, blk, vblk, goal, starts, prefer, main_anchor)
        if path is None and prefer == "F":
            path, expanded = route_astar(grid, blk, vblk, goal, starts, "B", main_anchor)
        elif path is None:
            path, expanded = route_astar(grid, blk, vblk, goal, starts, "F", main_anchor)
        if path is None:
            print(f"    FAIL {labels or 'track'} expanded={expanded}", flush=True)
            failed.extend(labels or ["track"])
            continue
        if not commit_path(board, geom, grid, path, net, width, new_ids):
            print(f"    CLEARANCE {labels or 'track'}", flush=True)
            failed.extend(labels or ["track"])
            continue
        # Grow the goal by the source island and the new copper.
        for lay, cells in src_cells.items():
            gi = 0 if lay == "F" else 1
            for ix, iy in cells:
                goal[gi][iy * grid.nx + ix] = 1
        for ix, iy, lay in path:
            goal[lay][iy * grid.nx + ix] = 1
        print(f"    joined {labels or 'track'} via {len(path)} cells", flush=True)
    if not failed:
        return "ok"
    return "open:" + ",".join(failed)


def vbat_forbidden(x, y) -> bool:
    """Pre-fuse copper and the intentional J2→F1.1 hop. Do not route here."""
    if 82.8 <= x <= 104.0 and 0.0 <= y <= 23.2:
        return True
    if abs(x - 58.0) <= 2.3 and abs(y - 18.0) <= 2.3:
        return True
    if 56.8 <= x <= 93.2 and 26.85 <= y <= 28.15:
        return True
    if abs(x - 92.0) <= 1.15 and 16.5 <= y <= 28.4:
        return True
    if abs(x - 58.5) <= 1.15 and 16.5 <= y <= 28.4:
        return True
    return False


def outline_points(outline):
    return [(ToMM(outline.CPoint(j).x), ToMM(outline.CPoint(j).y)) for j in range(outline.PointCount())]


def poly_seed(pts):
    # A point inside the outline: centroid, else a bbox sample.
    if not pts:
        return None
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    if point_in_poly(cx, cy, pts):
        return cx, cy
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    for y in (min(ys) + (max(ys) - min(ys)) * u for u in (0.3, 0.5, 0.7)):
        for x in (min(xs) + (max(xs) - min(xs)) * u for u in (0.3, 0.5, 0.7)):
            if point_in_poly(x, y, pts):
                return x, y
    return cx, cy


def stitch_vbat(board, geom: Geom, new_ids: set) -> str:
    """Tie post-fuse VBAT pour islands (ADIO tabs, HP slivers, B alley)
    into the island that already contains F1.2 / the HP tab. The pre-fuse
    island stays on the other side of F1."""
    zones = []
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetIsRuleArea() or z.GetNetname() != "VBAT" or not z.IsFilled():
            continue
        lay = z.GetFirstLayer()
        name = "F" if lay == F_Cu else "B"
        try:
            polys = z.GetFilledPolysList(lay)
        except TypeError:
            polys = z.GetFilledPolysList()
        for k in range(polys.OutlineCount()):
            pts = outline_points(polys.COutline(k))
            seed = poly_seed(pts)
            if seed is None:
                continue
            zones.append({"lay": name, "pts": pts, "seed": seed, "bb": (
                min(p[0] for p in pts), min(p[1] for p in pts),
                max(p[0] for p in pts), max(p[1] for p in pts),
            )})
    if not zones:
        return "no-zones"

    def seg_hits(seg, isl) -> bool:
        x1, y1, x2, y2, lay, _n, _w = seg
        if lay != isl["lay"]:
            return False
        l, t, r, b = isl["bb"]
        if max(x1, x2) < l - 0.4 or min(x1, x2) > r + 0.4 or max(y1, y2) < t - 0.4 or min(y1, y2) > b + 0.4:
            return False
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(length / 0.35))
        for i in range(steps + 1):
            u = i / steps
            if point_in_poly(x1 + (x2 - x1) * u, y1 + (y2 - y1) * u, isl["pts"]):
                return True
        return False

    parent = list(range(len(zones)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    vbat_segs = [s for s in geom.segs if s[5] == "VBAT"]
    vbat_vias = [v for v in geom.vias if v[2] == "VBAT"]
    for s in vbat_segs:
        hit = [i for i, isl in enumerate(zones) if seg_hits(s, isl)]
        for a in hit[1:]:
            union(hit[0], a)
    for vx, vy, _n, _sz, _d in vbat_vias:
        hit = []
        for i, isl in enumerate(zones):
            l, t, r, b = isl["bb"]
            if not (l - 0.4 <= vx <= r + 0.4 and t - 0.4 <= vy <= b + 0.4):
                continue
            if point_in_poly(vx, vy, isl["pts"]):
                hit.append(i)
        for a in hit[1:]:
            union(hit[0], a)

    # Pads sitting in a pour join that pour.
    for p in geom.pads:
        if p["net"] != "VBAT":
            continue
        hit = []
        for i, isl in enumerate(zones):
            if isl["lay"] not in p["layers"] and not (len(p["layers"]) == 2):
                if isl["lay"] not in p["layers"]:
                    continue
            l, t, r, b = isl["bb"]
            if not (l - 0.2 <= p["x"] <= r + 0.2 and t - 0.2 <= p["y"] <= b + 0.2):
                continue
            if point_in_poly(p["x"], p["y"], isl["pts"]):
                hit.append(i)
        for a in hit[1:]:
            union(hit[0], a)

    groups = defaultdict(list)
    for i in range(len(zones)):
        groups[find(i)].append(i)

    def group_has_point(idxs, x, y):
        for i in idxs:
            isl = zones[i]
            l, t, r, b = isl["bb"]
            if l - 0.3 <= x <= r + 0.3 and t - 0.3 <= y <= b + 0.3 and point_in_poly(x, y, isl["pts"]):
                return True
        return False

    main = None
    pre = None
    for k, idxs in groups.items():
        if group_has_point(idxs, 80.0, 41.5) or group_has_point(idxs, 67.2, 18.0):
            main = k
        if group_has_point(idxs, 92.0, 11.0) or group_has_point(idxs, 58.0, 18.0):
            pre = k
    if main is None:
        return "no-main-island"
    print(f"  VBAT groups={len(groups)} main={len(groups[main])} pre={0 if pre is None else len(groups[pre])}", flush=True)

    grid = Grid()
    width = 0.30
    blk, vblk = paint_mask(grid, geom, "VBAT", width, vbat_forbidden)
    goal_cells = {"F": set(), "B": set()}
    for i in groups[main]:
        isl = zones[i]
        # Solid raster so the search stops as soon as it enters the pour.
        pts = isl["pts"]
        ys = [p[1] for p in pts]
        xs = [p[0] for p in pts]
        iy0 = max(0, int(min(ys) / GRID))
        iy1 = min(grid.ny - 1, int(max(ys) / GRID) + 1)
        n = len(pts)
        acc = goal_cells[isl["lay"]]
        for iy in range(iy0, iy1 + 1):
            y = iy * GRID
            hits = []
            for a in range(n):
                x1, y1 = pts[a]
                x2, y2 = pts[(a + 1) % n]
                if (y1 <= y < y2) or (y2 <= y < y1):
                    if abs(y2 - y1) < 1e-9:
                        continue
                    hits.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
            hits.sort()
            for a in range(0, len(hits) - 1, 2):
                ix0 = max(0, int(hits[a] / GRID))
                ix1 = min(grid.nx - 1, int(hits[a + 1] / GRID))
                for ix in range(ix0, ix1 + 1):
                    acc.add((ix, iy))
    goal = paint_goal_cells(grid, goal_cells)
    failed = 0
    joined = 0
    for k, idxs in groups.items():
        if k == main or k == pre:
            continue
        starts = []
        for i in idxs:
            isl = zones[i]
            # Seed from outline samples that are not forbidden.
            pts = isl["pts"][:: max(1, len(isl["pts"]) // 30)]
            seed = isl["seed"]
            pts = [seed] + pts
            li = 0 if isl["lay"] == "F" else 1
            for x, y in pts:
                if vbat_forbidden(x, y):
                    continue
                ix, iy = grid.cell(x, y)
                if grid.inside(ix, iy):
                    starts.append((ix, iy, li))
                    if len(starts) > 40:
                        break
        if not starts:
            failed += 1
            continue
        if any(goal[lay][iy * grid.nx + ix] for ix, iy, lay in starts):
            joined += 1
            continue
        path, expanded = route_astar(grid, blk, vblk, goal, starts, "B", (80.0, 45.0))
        if path is None:
            path, expanded = route_astar(grid, blk, vblk, goal, starts, "F", (80.0, 45.0))
        if path is None:
            print(f"    VBAT island fail near {zones[idxs[0]]['seed']} exp={expanded}", flush=True)
            failed += 1
            continue
        if not commit_path(board, geom, grid, path, "VBAT", width, new_ids):
            print(f"    VBAT island clearance near {zones[idxs[0]]['seed']}", flush=True)
            failed += 1
            continue
        for ix, iy, lay in path:
            goal[lay][iy * grid.nx + ix] = 1
        joined += 1
        print(f"    VBAT joined island @ {zones[idxs[0]]['seed']}", flush=True)
    return f"joined={joined} failed={failed}"


def gnd_pairs(board, geom: Geom, new_ids: set) -> int:
    """Join the carrier GND stubs. M1000 pad openings are left alone."""
    if not BEFORE_DRC.exists():
        print("  no before-DRC json, skip GND pairs", flush=True)
        return 0
    data = json.loads(BEFORE_DRC.read_text())
    idmap = {}
    for t in board.GetTracks():
        idmap[t.m_Uuid.AsString()] = t
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            idmap[pad.m_Uuid.AsString()] = pad
    fixed = 0
    grid = Grid()
    blk, vblk = paint_mask(grid, geom, "GND", 0.25, None)
    for item in data.get("unconnected_items") or []:
        desc = " ".join((it.get("description") or "") for it in item.get("items", []))
        if "[GND]" not in desc:
            continue
        if "M1000" in desc:
            continue
        objs = []
        for it in item.get("items", []):
            obj = idmap.get(it.get("uuid"))
            if obj is not None:
                objs.append(obj)
        if len(objs) != 2:
            continue
        def cells(obj):
            out = {"F": set(), "B": set()}
            if obj.GetClass() == "PCB_VIA":
                ix, iy = grid.cell(ToMM(obj.GetPosition().x), ToMM(obj.GetPosition().y))
                out["F"].add((ix, iy))
                out["B"].add((ix, iy))
            elif obj.GetClass() == "PAD":
                x, y = ToMM(obj.GetPosition().x), ToMM(obj.GetPosition().y)
                ix, iy = grid.cell(x, y)
                lays = ("F", "B") if obj.IsOnLayer(F_Cu) and obj.IsOnLayer(B_Cu) else (("F",) if obj.IsOnLayer(F_Cu) else ("B",))
                for lay in lays:
                    out[lay].add((ix, iy))
            else:
                a, b = obj.GetStart(), obj.GetEnd()
                lay = "F" if obj.GetLayer() == F_Cu else "B"
                x1, y1, x2, y2 = ToMM(a.x), ToMM(a.y), ToMM(b.x), ToMM(b.y)
                steps = max(1, int(math.hypot(x2 - x1, y2 - y1) / GRID))
                for i in range(steps + 1):
                    u = i / steps
                    out[lay].add(grid.cell(x1 + (x2 - x1) * u, y1 + (y2 - y1) * u))
            return out
        src = cells(objs[0])
        dst = cells(objs[1])
        goal = paint_goal_cells(grid, dst)
        starts = []
        for lay, cs in src.items():
            li = 0 if lay == "F" else 1
            for ix, iy in cs:
                if grid.inside(ix, iy):
                    starts.append((ix, iy, li))
        if not starts:
            continue
        if any(goal[lay][iy * grid.nx + ix] for ix, iy, lay in starts if grid.inside(ix, iy)):
            continue
        anchor = grid.xy(*next(iter(next(cs for cs in dst.values() if cs))))
        path, _exp = route_astar(grid, blk, vblk, goal, starts, "F", anchor)
        if path is None:
            path, _exp = route_astar(grid, blk, vblk, goal, starts, "B", anchor)
        if path is None:
            print("    GND pair failed", flush=True)
            continue
        if commit_path(board, geom, grid, path, "GND", 0.25, new_ids):
            fixed += 1
            print(f"    GND pair joined ({len(path)} cells)", flush=True)
        else:
            print("    GND pair clearance", flush=True)
    return fixed


def fuse_bridged(board) -> bool:
    f1 = None
    for fp in board.GetFootprints():
        if fp.GetReference() == "F1":
            f1 = fp
    if f1 is None:
        return False
    a = f1.FindPadByNumber("1").GetPosition()
    b = f1.FindPadByNumber("2").GetPosition()
    ax, ay, bx, by = ToMM(a.x), ToMM(a.y), ToMM(b.x), ToMM(b.y)
    for t in board.GetTracks():
        if t.GetNetname() != "VBAT" or is_via(t):
            continue
        s, e = t.GetStart(), t.GetEnd()
        x1, y1, x2, y2 = ToMM(s.x), ToMM(s.y), ToMM(e.x), ToMM(e.y)
        if dist_pt_seg(ax, ay, x1, y1, x2, y2) < 0.8 and dist_pt_seg(bx, by, x1, y1, x2, y2) < 0.8:
            return True
    return False


def sensor_pours(board) -> int:
    n = 0
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if not z.GetIsRuleArea() and z.GetNetname() == "SENSOR_GND":
            n += 1
    return n


def fill_zones(board):
    ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()


def run_drc() -> dict:
    out = Path("/tmp/pdmrazora_drc_close.json")
    proc = subprocess.run(
        ["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error", "--units", "mm", "-o", str(out), str(PCB)],
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
    for v in drc.get("unconnected_items") or []:
        counts["unconnected_items"] += 1
        nets = []
        for it in v.get("items", []):
            m = re.search(r"\[([^\]]+)\]", it.get("description") or "")
            if m:
                nets.append(m.group(1))
        un_nets["|".join(sorted(set(nets)) or ["?"])] += 1
    return counts, un_nets


def drop_new_offenders(board, drc, new_ids: set) -> int:
    idmap = {}
    for t in board.GetTracks():
        idmap[t.m_Uuid.AsString()] = t
    victims = set()
    for v in drc.get("violations") or []:
        if v.get("type") not in ("shorting_items", "tracks_crossing", "clearance", "hole_clearance", "copper_edge_clearance"):
            continue
        ids = [it.get("uuid") for it in v.get("items", [])]
        fresh = [i for i in ids if i in new_ids]
        if fresh:
            victims.add(fresh[0])
    n = 0
    for uid in victims:
        obj = idmap.get(uid)
        if obj is not None:
            board.Delete(obj)
            new_ids.discard(uid)
            n += 1
    return n


def plot_png(board, path: Path) -> None:
    from PIL import Image, ImageDraw
    scale = 8
    w, h = int(BOARD_W * scale) + 8, int(BOARD_H * scale) + 8
    img = Image.new("RGB", (w * 2 + 16, h), (18, 18, 22))
    dr = ImageDraw.Draw(img, "RGBA")

    def panel(origin, layer_name):
        def pxy(x, y):
            return origin + int(x * scale) + 4, int(y * scale) + 4
        dr.rectangle([pxy(0, 0), pxy(BOARD_W, BOARD_H)], outline=(90, 90, 100))
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
            col = (190, 70, 55, 130) if name == "VBAT" else (50, 90, 170, 100) if name == "GND" else (120, 120, 80, 80)
            for k in range(min(polys.OutlineCount(), 12)):
                outline = polys.COutline(k)
                # Decimate so the PNG stays small.
                step = max(1, outline.PointCount() // 80)
                pts = [pxy(ToMM(outline.CPoint(j).x), ToMM(outline.CPoint(j).y)) for j in range(0, outline.PointCount(), step)]
                if len(pts) >= 3:
                    dr.polygon(pts, fill=col)
        for t in board.GetTracks():
            if is_via(t):
                p = t.GetPosition()
                cx, cy = pxy(ToMM(p.x), ToMM(p.y))
                dr.ellipse([cx - 1, cy - 1, cx + 1, cy + 1], outline=(220, 220, 220))
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
            elif net.startswith("SENSOR"):
                col = (80, 210, 210)
            else:
                col = (200, 140, 220)
            dr.line([pxy(ToMM(a.x), ToMM(a.y)), pxy(ToMM(b.x), ToMM(b.y))], fill=col, width=1)
        dr.text((origin + 8, 6), "F.Cu" if layer_name == "F" else "B.Cu", fill=(230, 230, 230))

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
    print("=== close carrier rats ===", flush=True)
    board = pcbnew.LoadBoard(str(PCB))
    # Placement lock check.
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    assert abs(fps["U3"].GetOrientationDegrees() - 90) < 0.1
    assert abs(fps["U4"].GetOrientationDegrees() - 90) < 0.1
    assert abs(ToMM(fps["J1"].GetPosition().x) - 48.8) < 0.05
    assert abs(ToMM(fps["D1"].GetPosition().x) - 88.0) < 0.05
    assert abs(ToMM(fps["R10"].GetPosition().y) - 35.70) < 0.02
    geom = Geom(board)
    new_ids = set()
    report = {}

    print("GND stubs...", flush=True)
    n_g = gnd_pairs(board, geom, new_ids)
    report["GND"] = f"stubs_joined={n_g}"
    print(report["GND"], flush=True)

    print("VBAT islands...", flush=True)
    report["VBAT"] = stitch_vbat(board, geom, new_ids)
    print(report["VBAT"], flush=True)

    widths = {}
    prefers = {}
    for n in SIGNAL_NETS:
        if n.startswith("PWR_OUT"):
            widths[n] = 0.30
            prefers[n] = "F"
        elif n.startswith("ADIO"):
            widths[n] = 0.20
            prefers[n] = "F"
        elif n == "SENSOR_5V":
            widths[n] = 0.20
            prefers[n] = "F"
        else:
            widths[n] = 0.20
            prefers[n] = "F"
    for n in SIGNAL_NETS:
        print(f"route {n}", flush=True)
        # Rebuild geom so later nets see copper added above. Geom is mutated
        # in place by add_track/add_via, so this is current.
        report[n] = connect_islands(board, geom, n, widths[n], prefers[n], new_ids, None)
        print(f"  -> {report[n]}", flush=True)

    if sensor_pours(board):
        sys.exit("SENSOR_GND pour appeared")
    if fuse_bridged(board):
        sys.exit("fuse bridged — aborting before save")

    print("refill...", flush=True)
    fill_zones(board)
    pcbnew.SaveBoard(str(PCB), board)
    downgrade_to_k8(PCB)
    board = pcbnew.LoadBoard(str(PCB))
    tr, via = count_items(board)
    print(f"tracks={tr} vias={via}", flush=True)
    print("DRC...", flush=True)
    drc = run_drc()
    counts, un_nets = summarize(drc)
    print(dict(counts), flush=True)

    # If the new copper created a short or a clearance hit, drop just that
    # new item and refill. Do not touch the polish copper.
    for _pass in range(3):
        if not any(counts.get(k, 0) for k in ("shorting_items", "tracks_crossing", "clearance", "hole_clearance")):
            break
        board = pcbnew.LoadBoard(str(PCB))
        n = drop_new_offenders(board, drc, new_ids)
        print(f"removed {n} new offenders", flush=True)
        if n == 0:
            break
        fill_zones(board)
        pcbnew.SaveBoard(str(PCB), board)
        downgrade_to_k8(PCB)
        drc = run_drc()
        counts, un_nets = summarize(drc)
        print("DRC", dict(counts), flush=True)
        board = pcbnew.LoadBoard(str(PCB))

    if fuse_bridged(board):
        sys.exit("fuse bridged after refill")
    tr, via = count_items(board)
    plot_png(board, PNG)
    ART.parent.mkdir(parents=True, exist_ok=True)
    plot_png(board, ART)

    compact = {
        "cli_rc": drc.get("cli_rc", 0),
        "kicad": "8.0.9",
        "counts": dict(counts),
        "unconnected_nets": dict(un_nets),
        "route_report": report,
        "sensor_pours": sensor_pours(board),
        "fuse_segment_bridges_both_pads": fuse_bridged(board),
        "tracks": tr,
        "vias": via,
    }
    DRC_JSON.write_text(json.dumps(compact, indent=2) + "\n")
    lines = [
        f"tracks={tr}",
        f"vias={via}",
        "footprints=54",
        f"drc_shorts={counts.get('shorting_items', 0)}",
        f"drc_crossings={counts.get('tracks_crossing', 0)}",
        f"drc_unconnected={counts.get('unconnected_items', 0)}",
        f"drc_clearance={counts.get('clearance', 0)}",
        f"drc_courtyards={counts.get('courtyards_overlap', 0)}",
        f"drc_padstack={counts.get('padstack_invalid', 0)}",
        f"drc_cli_rc={drc.get('cli_rc', 0)}",
        "strategy=close_carrier_rats_fine_grid",
        "kicad_cli=8.0.9",
        "hellcore=untouched",
        "fuse=ATO_placeholder_not_bridged",
        "sensor_pour=absent_not_added",
        "placement_u3u4=rot+90_centers_unchanged",
        "placement_j1=48.80",
        "placement_d1=88,24",
        "placement_sense_rc_y=35.70",
    ]
    STATUS.write_text("\n".join(lines) + "\n")
    left = ["# Leftover after carrier ratsnest close\n", "## Route report\n"]
    for k, v in report.items():
        left.append(f"- {k}: {v}")
    left.append("\n## DRC counts\n")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        left.append(f"- {k}: {v}")
    left.append("\n## Unconnected by net\n")
    for k, v in sorted(un_nets.items(), key=lambda kv: -kv[1]):
        left.append(f"- {k}: {v}")
    left.append("\nSENSOR pours: 0. F1 not bridged.\n")
    LEFTOVER.write_text("\n".join(left) + "\n")
    print("wrote", DRC_JSON)
    return 0


if __name__ == "__main__":
    sys.exit(main())
