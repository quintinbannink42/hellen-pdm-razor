#!/usr/bin/env python3
"""Open the SuperSeal corridors that PR #15 left walled off.

Moves the SENSOR_GND B.Cu spine off x=38.40 onto a west bypass so the
ADIO pins can leave, then routes the carrier nets that still have a
clearance-legal path. Does not pour SENSOR_GND, does not bridge F1,
does not replay cut_crossings, does not touch PWR_OUT mask openings.
"""
from __future__ import annotations

import heapq
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout_109x98 as L

GRID = 0.10
CLR = 0.20
TW = 0.15
NEED = CLR + TW / 2
VIA_R = 0.25
VIA_NEED = VIA_R + CLR
VIA_DRILL = 0.30
CELL = 2.0
# Edge clearance is 0.5 mm to the copper edge.
EDGE = 0.50 + TW / 2


def dps(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def near_seg(s, x1, y1, x2, y2, tol=0.08):
    return (
        (abs(s[0] - x1) < tol and abs(s[1] - y1) < tol and abs(s[2] - x2) < tol and abs(s[3] - y2) < tol)
        or (abs(s[0] - x2) < tol and abs(s[1] - y2) < tol and abs(s[2] - x1) < tol and abs(s[3] - y1) < tol)
    )


# SENSOR_GND copper that forms the spine and the south drop off it.
# The F.Cu bus at y=63.6 (E39 ↔ W1) and the J1.6 ↔ J1.12 tie stay.
SPINE = [
    (38.40, 43.20, 38.40, 55.60),
    (38.40, 55.60, 39.20, 55.60),
    (38.00, 43.20, 38.40, 43.20),
    (43.20, 61.20, 43.20, 63.60),
    (43.20, 63.60, 44.00, 63.50),
    (36.80, 43.20, 38.00, 43.20),
    (36.80, 42.00, 36.80, 43.20),
    (39.20, 55.60, 39.20, 60.80),
    (39.20, 60.80, 40.40, 60.80),
    (40.40, 60.80, 40.40, 61.20),
    (40.40, 61.20, 43.20, 61.20),
]
SPINE_VIAS = [(38.00, 43.20), (39.20, 55.60), (43.20, 61.20)]


def delete_spine(board) -> int:
    n = 0
    doomed = []
    for t in list(board.GetTracks()):
        if t.GetNetname() != "SENSOR_GND":
            continue
        if L.is_via(t):
            p = t.GetPosition()
            x, y = L.ToMM(p.x), L.ToMM(p.y)
            if any(abs(x - vx) < 0.08 and abs(y - vy) < 0.08 for vx, vy in SPINE_VIAS):
                doomed.append(t)
            continue
        a, b = t.GetStart(), t.GetEnd()
        seg = (L.ToMM(a.x), L.ToMM(a.y), L.ToMM(b.x), L.ToMM(b.y))
        if any(near_seg(seg, *sp) for sp in SPINE):
            doomed.append(t)
    for t in doomed:
        board.Delete(t)
        n += 1
    return n


class World:
    def __init__(self, board):
        self.board = board
        self.items = {"F": [], "B": []}
        self.buck = {"F": {}, "B": {}}
        self.drills = []  # x, y, drill
        self._load()

    def _load(self):
        for fp in self.board.GetFootprints():
            for pad in fp.Pads():
                net = pad.GetNetname() or ""
                attr = pad.GetAttribute()
                pth = attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
                on_f = pth or pad.IsOnLayer(pcbnew.F_Cu)
                on_b = pth or pad.IsOnLayer(pcbnew.B_Cu)
                if not on_f and not on_b:
                    continue
                x, y = L.ToMM(pad.GetPosition().x), L.ToMM(pad.GetPosition().y)
                sx, sy = L.ToMM(pad.GetSize().x), L.ToMM(pad.GetSize().y)
                drill = pad.GetDrillSize()
                dr = max(L.ToMM(drill.x), L.ToMM(drill.y))
                if pth and dr > 0:
                    self.drills.append((x, y, dr))
                rot = pad.GetOrientation().AsDegrees()
                if pad.GetShape() == pcbnew.PAD_SHAPE_CIRCLE or pth:
                    it = ("c", x, y, max(sx, sy) / 2, net)
                else:
                    ang = math.radians(rot % 180.0)
                    c, s = abs(math.cos(ang)), abs(math.sin(ang))
                    hw = (sx * c + sy * s) / 2
                    hh = (sx * s + sy * c) / 2
                    it = ("a", x - hw, y - hh, x + hw, y + hh, net)
                if on_f:
                    self._add("F", it)
                if on_b:
                    self._add("B", it)
        for t in self.board.GetTracks():
            net = t.GetNetname()
            if L.is_via(t):
                p = t.GetPosition()
                x, y = L.ToMM(p.x), L.ToMM(p.y)
                r = L.ToMM(t.GetWidth()) / 2
                dr = L.ToMM(t.GetDrill())
                self.drills.append((x, y, dr))
                it = ("c", x, y, r, net)
                self._add("F", it)
                self._add("B", it)
            else:
                a, b = t.GetStart(), t.GetEnd()
                lay = "F" if t.GetLayer() == pcbnew.F_Cu else "B"
                self._add(
                    lay,
                    (
                        "s",
                        L.ToMM(a.x),
                        L.ToMM(a.y),
                        L.ToMM(b.x),
                        L.ToMM(b.y),
                        L.ToMM(t.GetWidth()) / 2,
                        net,
                    ),
                )

    def _add(self, layer, it):
        self.items[layer].append(it)
        if it[0] == "c":
            xs, ys, rad = [it[1]], [it[2]], it[3]
        elif it[0] == "a":
            xs, ys, rad = [it[1], it[3]], [it[2], it[4]], 0.0
        else:
            xs, ys, rad = [it[1], it[3]], [it[2], it[4]], it[5]
        x0, x1 = min(xs) - rad, max(xs) + rad
        y0, y1 = min(ys) - rad, max(ys) + rad
        for ix in range(int(math.floor(x0 / CELL)) - 1, int(math.floor(x1 / CELL)) + 2):
            for iy in range(int(math.floor(y0 / CELL)) - 1, int(math.floor(y1 / CELL)) + 2):
                self.buck[layer].setdefault((ix, iy), []).append(it)

    def commit_seg(self, x1, y1, x2, y2, layer, net, width=TW):
        self._add(layer, ("s", x1, y1, x2, y2, width / 2, net))

    def commit_via(self, x, y, net, size=VIA_R * 2, drill=VIA_DRILL):
        self.drills.append((x, y, drill))
        it = ("c", x, y, size / 2, net)
        self._add("F", it)
        self._add("B", it)


def gap(it, x, y):
    if it[0] == "c":
        return math.hypot(x - it[1], y - it[2]) - it[3]
    if it[0] == "a":
        l, t, r, b = it[1:5]
        dx = 0.0 if l <= x <= r else (l - x if x < l else x - r)
        dy = 0.0 if t <= y <= b else (t - y if y < t else y - b)
        return math.hypot(dx, dy)
    return dps(x, y, it[1], it[2], it[3], it[4]) - it[5]


def _name(it):
    if it[0] == "s":
        return it[6]
    if it[0] == "a":
        return it[5]
    return it[4]


class Router:
    def __init__(self, world: World):
        self.w = world
        self.X0, self.Y0 = 0.0, 0.0
        self.X1, self.Y1 = 109.0, 98.0
        self.NX = int(round(self.X1 / GRID)) + 1
        self.NY = int(round(self.Y1 / GRID)) + 1

    def blocked(self, x, y, layer, net, need=NEED):
        if x < EDGE or y < EDGE or x > self.X1 - EDGE or y > self.Y1 - EDGE:
            return True
        ix, iy = int(math.floor(x / CELL)), int(math.floor(y / CELL))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for it in self.w.buck[layer].get((ix + dx, iy + dy), ()):
                    if _name(it) == net:
                        continue
                    if gap(it, x, y) < need:
                        return True
        return False

    def via_ok(self, x, y, net):
        if self.blocked(x, y, "F", net, VIA_NEED) or self.blocked(x, y, "B", net, VIA_NEED):
            return False
        for vx, vy, dr in self.w.drills:
            dist = math.hypot(vx - x, vy - y)
            if dist < 0.02:
                continue
            need = dr / 2 + VIA_DRILL / 2 + 0.25
            if dist < need - 1e-6:
                return False
        return True

    def _ij(self, x, y):
        return int(round(x / GRID)), int(round(y / GRID))

    def _xy(self, i, j):
        return i * GRID, j * GRID

    def route(self, net, starts, goals, via_cost=14, limit=1600000, forbid_y=None):
        """4-connected BFS. A via is allowed only to step onto the other
        layer's goal copper, so the long run stays on one layer.
        """
        from collections import deque

        goal = set()
        via_land = set()
        for x, y, lay in goals:
            i, j = self._ij(x, y)
            if 0 <= i < self.NX and 0 <= j < self.NY:
                goal.add((i, j, lay))
                # A via can land up to ~0.2 mm off the copper and still overlap it.
                for di in (-2, -1, 0, 1, 2):
                    for dj in (-2, -1, 0, 1, 2):
                        via_land.add((i + di, j + dj, lay))
        if not goal:
            return None, 0
        prev = {}
        q = deque()
        for x, y, lay in starts:
            i, j = self._ij(x, y)
            if not (0 <= i < self.NX and 0 <= j < self.NY):
                continue
            st = (i, j, lay)
            if st in prev:
                continue
            if self.blocked(i * GRID, j * GRID, "FB"[lay], net):
                continue
            prev[st] = None
            q.append(st)
        found = None
        exp = 0
        while q:
            cur = q.popleft()
            exp += 1
            if exp > limit:
                break
            i, j, lay = cur
            x, y = i * GRID, j * GRID
            if forbid_y and forbid_y[0] <= y <= forbid_y[1]:
                continue
            if cur in goal:
                found = cur
                break
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if not (0 <= ni < self.NX and 0 <= nj < self.NY):
                    continue
                nxt = (ni, nj, lay)
                if nxt in prev:
                    continue
                xx, yy = ni * GRID, nj * GRID
                if forbid_y and forbid_y[0] <= yy <= forbid_y[1]:
                    continue
                if self.blocked(xx, yy, "FB"[lay], net):
                    continue
                prev[nxt] = cur
                q.append(nxt)
            olay = 1 - lay
            landed = (i, j, olay)
            if landed in via_land and landed not in prev and self.via_ok(x, y, net):
                prev[landed] = cur
                found = landed
                break
        if not found:
            return None, exp
        path = []
        cur = found
        while cur is not None:
            path.append(cur)
            cur = prev[cur]
        path.reverse()
        pts = []
        for i, j, lay in path:
            x, y = i * GRID, j * GRID
            if len(pts) >= 2 and pts[-1][2] == lay and pts[-2][2] == lay:
                if abs((pts[-1][0] - pts[-2][0]) * (y - pts[-1][1]) - (pts[-1][1] - pts[-2][1]) * (x - pts[-1][0])) < 1e-9:
                    pts[-1][0], pts[-1][1] = x, y
                    continue
            pts.append([x, y, lay])
        return pts, exp

    def seg_ok(self, x1, y1, x2, y2, layer, net, width=TW):
        need = CLR + width / 2
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(length / 0.05))
        for k in range(steps + 1):
            u = k / steps
            if self.blocked(x1 + (x2 - x1) * u, y1 + (y2 - y1) * u, layer, net, need):
                return False
        return True

    def commit_path(self, pts, net, width=TW):
        if not pts or len(pts) < 2:
            return False
        for a, b in zip(pts, pts[1:]):
            if a[2] != b[2]:
                if not self.via_ok(a[0], a[1], net):
                    return False
                continue
            lay = "F" if a[2] == 0 else "B"
            if not self.seg_ok(a[0], a[1], b[0], b[1], lay, net, width):
                return False
        for a, b in zip(pts, pts[1:]):
            if a[2] != b[2]:
                self.w.commit_via(a[0], a[1], net)
                L.add_via(self.w.board, a[0], a[1], net, VIA_R * 2, VIA_DRILL)
            else:
                lay = "F" if a[2] == 0 else "B"
                self.w.commit_seg(a[0], a[1], b[0], b[1], lay, net, width)
                L.add_track(self.w.board, a[0], a[1], b[0], b[1], width, net, lay)
        return True


def copper_goals(world, net, avoid, min_dist=1.6):
    ax, ay = avoid
    gs = []
    for lay, key in (("F", 0), ("B", 1)):
        for it in world.items[lay]:
            if _name(it) != net:
                continue
            if it[0] == "c":
                if math.hypot(it[1] - ax, it[2] - ay) < min_dist:
                    continue
                gs.append((it[1], it[2], key))
            elif it[0] == "s":
                length = math.hypot(it[3] - it[1], it[4] - it[2])
                steps = max(1, int(length / 0.4))
                for k in range(steps + 1):
                    u = k / steps
                    x = it[1] + (it[3] - it[1]) * u
                    y = it[2] + (it[4] - it[2]) * u
                    if math.hypot(x - ax, y - ay) < min_dist:
                        continue
                    gs.append((x, y, key))
            elif it[0] == "a":
                cx, cy = (it[1] + it[3]) / 2, (it[2] + it[4]) / 2
                if math.hypot(cx - ax, cy - ay) < min_dist:
                    continue
                gs.append((cx, cy, key))
    return gs


def pad_starts(world, net, x, y, layers, rad):
    """Cells on the pad (same-net copper is not an obstacle) on the given layers."""
    out = []
    for lay in layers:
        # Center plus a ring, so a pad whose center sits on foreign copper
        # (it shouldn't) still has a start.
        cands = [(x, y)]
        for k in range(16):
            ang = k * math.pi / 8
            cands.append((x + rad * 0.6 * math.cos(ang), y + rad * 0.6 * math.sin(ang)))
        layer = "F" if lay == 0 else "B"
        # blocked() isn't available yet; the router checks at expansion.
        for px, py in cands:
            out.append((px, py, lay))
    return out


def put_track(board, x1, y1, x2, y2, net, layer):
    """Add a track and refuse to keep it if KiCad stored a different net."""
    if math.hypot(x2 - x1, y2 - y1) < 0.02:
        return True
    tr = L.add_track(board, x1, y1, x2, y2, TW, net, layer)
    if tr is None:
        return True
    code = board.FindNet(net).GetNetCode()
    tr.SetNetCode(code)
    if tr.GetNetname() != net:
        print(f"NET MISMATCH {net} stored as {tr.GetNetname()}", flush=True)
        board.Delete(tr)
        return False
    return True


def put_via(board, x, y, net):
    v = L.add_via(board, x, y, net, VIA_R * 2, VIA_DRILL)
    code = board.FindNet(net).GetNetCode()
    v.SetNetCode(code)
    if v.GetNetname() != net:
        print(f"VIA NET MISMATCH {net} stored as {v.GetNetname()}", flush=True)
        board.Delete(v)
        return False
    return True


def commit_pts(router, net, lay, pts):
    """lay is 'F' or 'B'. Points are (x, y)."""
    clean = []
    for p in pts:
        x, y = round(p[0], 2), round(p[1], 2)
        if clean and abs(clean[-1][0] - x) < 0.02 and abs(clean[-1][1] - y) < 0.02:
            continue
        clean.append((x, y))
    for a, b in zip(clean, clean[1:]):
        if not router.seg_ok(a[0], a[1], b[0], b[1], lay, net):
            print(f"  {net} seg refused {a}->{b}", flush=True)
            return False
    for a, b in zip(clean, clean[1:]):
        if not put_track(router.w.board, a[0], a[1], b[0], b[1], net, lay):
            return False
        router.w.commit_seg(a[0], a[1], b[0], b[1], lay, net)
    return True


def bfs(router, net, start, lay, pred, box, limit=200000):
    """Orthogonal BFS. pred(x, y) is true on a goal cell. lay is 'F' or 'B'."""
    from collections import deque

    x0, x1, y0, y1 = box
    si, sj = int(round(start[0] / GRID)), int(round(start[1] / GRID))
    if router.blocked(si * GRID, sj * GRID, lay, net):
        return None, 0
    prev = {(si, sj): None}
    q = deque([(si, sj)])
    exp = 0
    found = None
    while q:
        i, j = q.popleft()
        exp += 1
        if exp > limit:
            break
        x, y = i * GRID, j * GRID
        if pred(x, y) and (i, j) != (si, sj):
            found = (i, j)
            break
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if (ni, nj) in prev:
                continue
            xx, yy = ni * GRID, nj * GRID
            if not (x0 <= xx <= x1 and y0 <= yy <= y1):
                continue
            if router.blocked(xx, yy, lay, net):
                continue
            prev[(ni, nj)] = (i, j)
            q.append((ni, nj))
    if not found:
        return None, exp
    path = []
    cur = found
    while cur is not None:
        path.append((round(cur[0] * GRID, 2), round(cur[1] * GRID, 2)))
        cur = prev[cur]
    path.reverse()
    pts = []
    for x, y in path:
        if len(pts) >= 2:
            ax, ay = pts[-2]
            bx, by = pts[-1]
            if abs((bx - ax) * (y - by) - (by - ay) * (x - bx)) < 1e-9:
                pts[-1] = (x, y)
                continue
        pts.append((x, y))
    return pts, exp


def route_net(router, net, starts, goals, note, via_cost=14, limit=1600000, forbid_y=None):
    t0 = time.time()
    pts, exp = router.route(net, starts, goals, via_cost=via_cost, limit=limit, forbid_y=forbid_y)
    if not pts:
        print(f"  {note} FAIL exp {exp} {time.time()-t0:.1f}s", flush=True)
        return False
    if not router.commit_path(pts, net):
        print(f"  {note} path failed exact check exp {exp}", flush=True)
        return False
    vias = sum(1 for a, b in zip(pts, pts[1:]) if a[2] != b[2])
    print(
        f"  {note} OK bends {len(pts)-1} vias {vias} exp {exp} {time.time()-t0:.1f}s "
        f"-> ({pts[-1][0]:.2f},{pts[-1][1]:.2f})",
        flush=True,
    )
    return True


def add_bypass(board, world_later_check=None):
    """West B.Cu bypass from J1.12 onto the existing F.Cu bus at y=63.6."""
    L.add_track(board, 36.60, 41.60, 12.00, 41.60, TW, "SENSOR_GND", "B")
    L.add_track(board, 12.00, 41.60, 12.00, 63.60, TW, "SENSOR_GND", "B")
    L.add_via(board, 12.00, 63.60, "SENSOR_GND", VIA_R * 2, VIA_DRILL)


def raster_pour(board, net, layer):
    lay = pcbnew.F_Cu if layer == "F" else pcbnew.B_Cu
    polys = []
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
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
    step = 0.20
    y = 0.0
    while y <= 98.0:
        x = 0.0
        while x <= 109.0:
            pt = pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
            if any(p.Contains(pt) for p in polys):
                cells.add((int(round(x / GRID)), int(round(y / GRID))))
            x += step
        y += step
    return cells


def gnd_carriers(world):
    """One anchor per carrier GND pad that is not an M1000 keepout pad."""
    seen = set()
    out = []
    for lay in ("F", "B"):
        for it in world.items[lay]:
            if it[0] not in ("c", "a") or _name(it) != "GND":
                continue
            if it[0] == "c":
                x, y = it[1], it[2]
            else:
                x, y = (it[1] + it[3]) / 2, (it[2] + it[4]) / 2
            key = (round(x, 2), round(y, 2))
            if key in seen:
                continue
            seen.add(key)
            # M1000 GND pads sit on the keepout boundary. Leave them.
            if 1.5 <= x <= 45.0 and 25.5 <= y <= 66.5:
                # Could still be a carrier inside that box? The carriers we
                # care about are east of x=50 or the north stubs. The keepout
                # pads are the only GND pads inside the module outline.
                if x <= 44.6:
                    continue
            out.append((x, y, 0 if lay == "F" else 1))
    return out


def pour_goals_near(cells, x, y, reach=14.0):
    gs = []
    ix, iy = x / GRID, y / GRID
    rad = reach / GRID
    for cx, cy in cells:
        if abs(cx - ix) <= rad and abs(cy - iy) <= rad:
            gs.append((cx * GRID, cy * GRID, 1))  # B pour
    return gs


def drop_s5v_spine(board) -> int:
    """Move the F.Cu SENSOR_5V spine off the ADIO corridor.

    The replacement is a B.Cu drop at x=10, from the existing F.Cu run at
    y=43.60 down onto the F.Cu bus at y=62.40. The J1.5 / J1.11 ties stay.
    """
    n = 0
    for t in list(board.GetTracks()):
        if L.is_via(t) or t.GetNetname() != "SENSOR_5V":
            continue
        a, b = t.GetStart(), t.GetEnd()
        x1, y1, x2, y2 = L.ToMM(a.x), L.ToMM(a.y), L.ToMM(b.x), L.ToMM(b.y)
        vertical = abs(x1 - 38.4) < 0.05 and abs(x2 - 38.4) < 0.05 and max(y1, y2) > 60 and min(y1, y2) < 48
        jog = abs(y1 - 46.4) < 0.05 and abs(y2 - 46.4) < 0.05 and max(x1, x2) > 38 and min(x1, x2) < 37.2
        if vertical or jog:
            board.Delete(t)
            n += 1
    return n


def f_segments(world, net, xmin=55.0):
    out = []
    for it in world.items["F"]:
        if it[0] == "s" and it[6] == net and max(it[1], it[3]) >= xmin:
            out.append(it)
    return out


def touches_seg(segs, x, y, extra=0.02):
    for it in segs:
        if dps(x, y, it[1], it[2], it[3], it[4]) <= it[5] + extra:
            return it
    return None


def project(it, x, y):
    dx, dy = it[3] - it[1], it[4] - it[2]
    length = dx * dx + dy * dy
    if length < 1e-9:
        return it[1], it[2]
    t = max(0.0, min(1.0, ((x - it[1]) * dx + (y - it[2]) * dy) / length))
    return it[1] + t * dx, it[2] + t * dy


def via_landings(router, net):
    """B.Cu via sites that can tie onto the driver-side F.Cu copper."""
    segs = f_segments(router.w, net)
    if not segs:
        return []
    cands = []
    y = 52.0
    while y <= 70.0:
        x = 55.0
        while x <= 100.0:
            if router.via_ok(x, y, net) and not router.blocked(x, y, "B", net):
                best = min(segs, key=lambda it: dps(x, y, it[1], it[2], it[3], it[4]))
                md = dps(x, y, best[1], best[2], best[3], best[4]) - best[5]
                if md < 5.0:
                    cands.append((md, round(x, 2), round(y, 2), best))
            x = round(x + 0.4, 4)
        y = round(y + 0.4, 4)
    cands.sort(key=lambda c: c[0])
    lands = []
    seen = set()
    for md, x, y, it in cands:
        key = (round(x, 0), round(y, 0))
        if key in seen:
            continue
        seen.add(key)
        px, py = project(it, x, y)
        px, py = round(px, 2), round(py, 2)
        if math.hypot(px - x, py - y) < 0.05 or router.seg_ok(x, y, px, py, "F", net):
            lands.append((x, y, px, py))
        if len(lands) >= 4:
            break
        if len(seen) > 25:
            break
    return lands


def shortcut(router, net, lay, pts):
    """Drop bends whose straight chord is still clearance-legal."""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    i = 0
    while i < len(pts) - 1:
        j = len(pts) - 1
        while j > i + 1:
            if router.seg_ok(pts[i][0], pts[i][1], pts[j][0], pts[j][1], lay, net):
                break
            j -= 1
        out.append(pts[j])
        i = j
    return out


def driver_touch(world, net, xmin, ymax):
    """Existing driver copper only. The south bus (y >= ymax) is not a goal."""
    segs = []
    for it in world.items["B"]:
        if it[0] == "s" and it[6] == net and max(it[1], it[3]) >= xmin and min(it[2], it[4]) < ymax:
            segs.append(it)

    def pred(x, y, segs=segs):
        return x >= xmin and y < ymax and touches_seg(segs, x, y, 0.02) is not None

    return pred


def same_layer_touch(world, net, lay, xmin=55.0):
    segs = []
    for it in world.items[lay]:
        # Driver copper sits north of the south highway (y < 70). The highway
        # tracks themselves run past x=55 and must not count as the target.
        if it[0] == "s" and it[6] == net and max(it[1], it[3]) >= xmin and min(it[2], it[4]) < 70:
            segs.append(it)
    def pred(x, y, segs=segs):
        return x >= xmin and touches_seg(segs, x, y, 0.02) is not None
    return pred


def main() -> int:
    board = pcbnew.LoadBoard(str(L.PCB))
    before_mask = sum(1 for d in board.GetDrawings() if d.GetLayer() == pcbnew.F_Mask)
    removed = delete_spine(board)
    dropped = drop_s5v_spine(board)
    print(f"removed spine {removed} s5v spine {dropped}", flush=True)
    add_bypass(board)
    # SENSOR_5V replacement: existing F run ends at (10, 43.6); bus is y=62.4.
    put_track(board, 10.0, 43.6, 10.0, 62.4, "SENSOR_5V", "B")
    put_via(board, 10.0, 43.6, "SENSOR_5V")
    put_via(board, 10.0, 62.4, "SENSOR_5V")
    print("building world", flush=True)
    world = World(board)
    router = Router(world)
    if not router.seg_ok(36.6, 41.6, 12.0, 41.6, "B", "SENSOR_GND") or not router.seg_ok(12.0, 41.6, 12.0, 63.6, "B", "SENSOR_GND"):
        print("BYPASS does not clear", flush=True)
        return 2
    if not router.via_ok(12.0, 63.6, "SENSOR_GND") or not router.via_ok(10.0, 43.6, "SENSOR_5V") or not router.seg_ok(10.0, 43.6, 10.0, 62.4, "B", "SENSOR_5V"):
        print("SENSOR_5V drop does not clear", flush=True)
        return 2
    print("bypass and sensor drop clear", flush=True)

    # West SuperSeal pins. Each uses its own middle-column gap, then a private
    # lane and a private S-row passage. Southern buses sit further east so the
    # north passages can drop past them without crossing.
    west = [
        ("ADIO2", [(39.80, 51.0), (38.30, 51.0), (38.30, 52.5), (36.80, 52.5), (34.30, 51.0), (31.0, 51.0), (31.0, 61.6), (24.9, 61.6), (24.9, 73.0)]),
        ("ADIO4", [(39.80, 48.0), (38.30, 48.0), (38.30, 49.5), (36.80, 49.5), (34.30, 48.0), (30.4, 48.0), (30.4, 61.0), (23.7, 61.0), (23.7, 73.0)]),
        ("ADIO6", [(39.80, 45.0), (38.30, 45.0), (38.30, 46.5), (36.80, 46.5), (34.30, 45.0), (29.8, 45.0), (29.8, 60.4), (20.1, 60.4), (20.1, 73.0)]),
        ("ADIO8", [(39.80, 42.0), (38.30, 42.0), (38.30, 43.5), (36.80, 43.5), (34.30, 42.0), (29.2, 42.0), (29.2, 59.8), (18.9, 59.8), (18.9, 73.0)]),
    ]
    ends = {}
    for name, pts in west:
        ok = commit_pts(router, name, "B", pts)
        print(f"{name} west {ok}", flush=True)
        if ok:
            ends[name] = ("B", pts[-1])
    # Drop to y=82 before going east. The band y=76–78 is a GND-pour neck;
    # crossing it on the way out of the passages splits the pour.
    for name, pts in (
        ("ADIO8", [(18.9, 73.0), (18.9, 82.0), (72.0, 82.0)]),
        ("ADIO6", [(20.1, 73.0), (20.1, 81.4), (66.0, 81.4)]),
    ):
        if commit_pts(router, name, "B", pts):
            ends[name] = ("B", pts[-1])
            print(f"{name} low bus {pts[-1]}", flush=True)
        else:
            print(f"{name} low bus FAIL", flush=True)

    # East pins reach the south highway if the search is not stopped in the
    # pocket at y≈58. Each gets a distinct landing so the runs do not stack.
    for name, start, gx, gy in (
        # East-pin highway searches reach y=76 but do not find the driver
        # copper, and the search path cuts a GND pour neck. Left for a
        # later corridor that stays on the low bus.
    ):
        if router.blocked(gx, gy, "B", name):
            print(f"{name} highway goal blocked", flush=True)
            continue
        pts, exp = bfs(
            router, name, start, "B",
            lambda x, y, gx=gx, gy=gy: abs(x - gx) < 0.05 and abs(y - gy) < 0.05,
            (16, 108, 36, 92), limit=180000,
        )
        if pts and commit_pts(router, name, "B", pts):
            ends[name] = ("B", pts[-1])
            print(f"{name} highway {pts[-1]} bends {len(pts)-1} exp {exp}", flush=True)
        else:
            print(f"{name} highway FAIL exp {exp}", flush=True)

    def finish_south(name, lay, start):
        lands = via_landings(router, name) if lay == "B" else []
        via_at = {(lx, ly): (fx, fy) for lx, ly, fx, fy in lands}
        touch = same_layer_touch(world, name, lay)

        def pred(x, y):
            if touch(x, y):
                return True
            return (round(x, 2), round(y, 2)) in via_at or (x, y) in via_at

        # Snap goal test to the 0.1 grid the BFS walks.
        def pred_grid(x, y):
            if touch(x, y):
                return True
            key = (round(x, 1), round(y, 1))
            for lx, ly in via_at:
                if abs(lx - key[0]) < 0.05 and abs(ly - key[1]) < 0.05:
                    return True
            return False

        print(f"  {name} landings {len(lands)} from {start}", flush=True)
        if start[0] >= 40:
            box, limit = (40, 108, 50, 90), 160000
        else:
            box, limit = (15, 108, 54, 92), 400000
        pts, exp = bfs(router, name, start, lay, pred_grid, box, limit=limit)
        if not pts:
            print(f"  {name} south FAIL exp {exp}", flush=True)
            return False
        if not commit_pts(router, name, lay, pts):
            print(f"  {name} south commit failed", flush=True)
            return False
        end = pts[-1]
        landed = None
        for lx, ly, fx, fy in lands:
            if abs(end[0] - lx) < 0.15 and abs(end[1] - ly) < 0.15:
                landed = (lx, ly, fx, fy)
                break
        if landed:
            lx, ly, fx, fy = landed
            if not router.via_ok(lx, ly, name):
                print(f"  {name} via refused at {landed[:2]}", flush=True)
                return False
            put_via(board, lx, ly, name)
            router.w.commit_via(lx, ly, name)
            if math.hypot(fx - lx, fy - ly) >= 0.05:
                if not commit_pts(router, name, "F", [(lx, ly), (fx, fy)]):
                    print(f"  {name} F tie failed", flush=True)
                    return False
            print(f"  {name} via ({lx:.2f},{ly:.2f}) -> F ({fx:.2f},{fy:.2f}) exp {exp}", flush=True)
        else:
            print(f"  {name} touched copper {end} bends {len(pts)-1} exp {exp}", flush=True)
        return True

    # Driver hops from the low bus cross the GND pour neck at y≈76–78
    # (or the east board edge) and isolate a GND island. Left off. The west
    # spines and the y≥80 buses are the exits that stay pour-neutral.

    # Short GND stitches onto existing pour copper, plus the one SENSOR_5V
    # pull-up whose pad center accepts a via (R202). Proven on the stock
    # board: GND 38→35, SENSOR_5V 4→3, VBAT stays 10. The R102 wander
    # through y≈46 closed two more GND pads and opened a VBAT island.
    stitches = [
        ("GND", "B", [(77.2, 52.4), (78.9, 51.0)]),
        ("GND", "F", [(90.8, 54.3), (92.6, 53.6), (92.6, 52.4)]),
        ("GND", "F", [(66.8, 54.3), (69.2, 52.4)]),
        ("GND", "F", [(74.8, 54.3), (73.9, 55.1), (72.4, 55.1), (72.5, 53.6), (72.9, 51.7)]),
        ("GND", "F", [(69.9, 50.4), (69.9, 52.2)]),
    ]
    for net, lay, pts in stitches:
        print(f"stitch {lay} {pts[0]} {commit_pts(router, net, lay, pts)}", flush=True)
    r202 = (
        router.via_ok(69.175, 56.2, "SENSOR_5V")
        and commit_pts(router, "SENSOR_5V", "B", [(69.175, 56.2), (73.6, 56.3)])
        and put_via(board, 69.175, 56.2, "SENSOR_5V")
    )
    if r202:
        router.w.commit_via(69.175, 56.2, "SENSOR_5V")
    print(f"r202 {r202}", flush=True)

    # Vias whose annular ring already sits in the B.Cu GND pour and whose
    # copper overlaps the F.Cu pad. R104's via lands on the B stitch above,
    # which reaches the pour; the pad center itself is not in the pour.
    # C10's via is on the pad's south edge. It joins a pour island (GND -1)
    # even though the pad itself stays on the ratsnest.
    pour_vias = [
        (77.175, 52.40, "R104"),
        (56.000, 20.675, "R2"),
        (78.775, 54.225, "C104"),
        (63.500, 6.55, "C1"),
        (63.175, 76.20, "C10"),
        (106.000, 19.85, "D1"),
        (100.975, 77.00, "R20"),
        (98.375, 77.00, "C20"),
    ]
    for x, y, ref in pour_vias:
        ok = router.via_ok(x, y, "GND") and put_via(board, x, y, "GND")
        if ok:
            router.w.commit_via(x, y, "GND")
        print(f"pour via {ref} {ok}", flush=True)

    # C2.2 sits on a clear F.Cu run to a via that the B pour already covers.
    c2 = commit_pts(router, "GND", "F", [(94.15, 6.2), (103.9, 6.2)]) and put_via(board, 103.9, 6.2, "GND")
    if c2:
        router.w.commit_via(103.9, 6.2, "GND")
    print(f"C2 {c2}", flush=True)
    # C108.2 accepts a via in the pad. The B.Cu run ends in the pour.
    c108 = [(94.775, 54.3), (98.2, 54.3), (98.2, 52.1), (97.9, 51.8), (91.9, 51.8)]
    c108_ok = router.via_ok(94.775, 54.3, "GND") and put_via(board, 94.775, 54.3, "GND") and commit_pts(router, "GND", "B", c108)
    if c108_ok:
        router.w.commit_via(94.775, 54.3, "GND")
    print(f"C108 {c108_ok}", flush=True)

    print("fill", flush=True)
    L.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    keep = L.pour_inside_keepout(board)
    fuse = L.fuse_bridged(board)
    sensor = L.sensor_pours(board)
    after_mask = sum(1 for d in board.GetDrawings() if d.GetLayer() == pcbnew.F_Mask)
    counts = {}
    for t in board.GetTracks():
        if L.is_via(t):
            continue
        if L.ToMM(t.GetWidth()) > 0.16:
            continue
        counts[t.GetNetname()] = counts.get(t.GetNetname(), 0) + 1
    print("new-ish 0.15 tracks", {k: counts[k] for k in sorted(counts) if k.startswith("ADIO") or k in ("SENSOR_5V", "SENSOR_GND")}, flush=True)
    print(f"keepout {keep} fuse {fuse} sensor {sensor} mask {before_mask}->{after_mask}", flush=True)
    out = Path("/tmp/pdm_candidate.kicad_pcb")
    board.Save(str(out))
    L.downgrade_to_k8(out)
    saved = L.PCB
    L.PCB = out
    try:
        _rc, text, err = L.run_drc()
    finally:
        L.PCB = saved
    summary = L.summarize_report(text)
    print(summary["counts"], flush=True)
    from collections import Counter
    per = Counter()
    for block in text.split("[unconnected_items]:")[1:]:
        m = re.search(r"\[([A-Z][A-Z0-9_]*)\]", block)
        if m:
            per[m.group(1)] += 1
    print("per-net", dict(per), "sum", sum(per.values()), flush=True)
    Path("/tmp/open_corridors_drc.txt").write_text(text)
    if err:
        print(err[-400:], flush=True)
    hard_keys = (
        "shorting_items", "tracks_crossing", "clearance", "hole_clearance",
        "hole_near_hole", "solder_mask_bridge", "courtyards_overlap", "padstack_invalid",
    )
    hard = sum(summary["counts"].get(k, 0) for k in hard_keys)
    if hard or keep or fuse or sensor or after_mask != before_mask:
        print("NOT installed", flush=True)
        return 1
    print("candidate is hard-clean", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
