#!/usr/bin/env python3
"""Second pass: close the carrier ratsnests the coarse stitcher left open.

Does not move polish anchors, does not bridge F1, does not add a SENSOR_GND
pour, and does not replay the 150×130 long-haul scripts. New copper is an
8-connected local search at 0.05 mm, committed only when the exact clearance
check passes. Samples that sit on the net's own pad are not clearance failures
(the track is landing on copper that is already there).
"""
from __future__ import annotations

import heapq
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from close_carrier_rats import (  # noqa: E402
    ART,
    BOARD_H,
    BOARD_W,
    CLR,
    DRC_JSON,
    EDGE,
    LEFTOVER,
    PCB,
    PNG,
    STATUS,
    VIA_DRILL,
    VIA_SIZE,
    Geom,
    add_track,
    add_via,
    dist_pt_rect,
    dist_pt_seg,
    downgrade_to_k8,
    drop_new_offenders,
    fill_zones,
    fuse_bridged,
    is_via,
    layer_of,
    plot_png,
    run_drc,
    sensor_pours,
    summarize,
    vbat_forbidden,
)

GRID = 0.05
WIDTH = 0.20


def own_pad_cover(geom: Geom, x, y, net, width) -> bool:
    lim = width / 2 + 0.02
    for p in geom.pads:
        if p["net"] == net and dist_pt_rect(x, y, p["box"]) <= lim:
            return True
    return False


def seg_ok_land(geom: Geom, x1, y1, x2, y2, width, lay, net) -> bool:
    """seg_ok, but a sample sitting on this net's pad is already copper."""
    if math.hypot(x2 - x1, y2 - y1) < 0.015:
        return True
    if geom.seg_ok(x1, y1, x2, y2, width, lay, net):
        return True
    need = width / 2 + CLR - 0.005
    length = math.hypot(x2 - x1, y2 - y1)
    steps = max(1, int(length / 0.05))
    for i in range(steps + 1):
        u = i / steps
        x = x1 + (x2 - x1) * u
        y = y1 + (y2 - y1) * u
        if own_pad_cover(geom, x, y, net, width):
            continue
        # Re-check this sample against foreign copper. If it fails and it is
        # not on our pad, the segment is illegal.
        if x < EDGE or y < EDGE or x > BOARD_W - EDGE or y > BOARD_H - EDGE:
            return False
        for p in geom.pads:
            if p["net"] == net or lay not in p["layers"]:
                continue
            if dist_pt_rect(x, y, p["box"]) < need:
                return False
        for sx1, sy1, sx2, sy2, sl, sn, sw in geom.segs:
            if sn == net or sl != lay:
                continue
            if dist_pt_seg(x, y, sx1, sy1, sx2, sy2) < need + sw / 2:
                return False
        for vx, vy, vn, vsz, _vd in geom.vias:
            if vn == net:
                continue
            if math.hypot(x - vx, y - vy) < need + vsz / 2:
                return False
    return True


def islands_of(geom: Geom, net: str):
    pads = [p for p in geom.pads if p["net"] == net]
    segs = [s for s in geom.segs if s[5] == net]
    vias = [v for v in geom.vias if v[2] == net]
    items = [("pad", p) for p in pads] + [("seg", s) for s in segs] + [("via", v) for v in vias]
    n = len(items)
    if n == 0:
        return items, []
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    buckets = defaultdict(list)

    def bucket_add(i, x, y):
        buckets[(int(x), int(y))].append(i)

    def pts_of(i):
        kind, obj = items[i]
        if kind == "pad":
            return [(obj["x"], obj["y"])], None
        if kind == "via":
            return [(obj[0], obj[1])], None
        x1, y1, x2, y2 = obj[0], obj[1], obj[2], obj[3]
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(length))
        return [(x1 + (x2 - x1) * k / steps, y1 + (y2 - y1) * k / steps) for k in range(steps + 1)], obj[4]

    meta = []
    for i, (kind, obj) in enumerate(items):
        pts, lay = pts_of(i)
        meta.append((kind, obj, pts, lay))
        for x, y in pts:
            bucket_add(i, x, y)

    def near(i):
        seen = set()
        for x, y in meta[i][2]:
            ix, iy = int(x), int(y)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in buckets.get((ix + dx, iy + dy), ()):
                        if j != i:
                            seen.add(j)
        return seen

    def touches(i, j) -> bool:
        ka, oa, pa, la = meta[i]
        kb, ob, pb, lb = meta[j]
        if ka == "seg" and kb == "seg":
            if la != lb:
                return False
            for x, y in pa:
                if dist_pt_seg(x, y, ob[0], ob[1], ob[2], ob[3]) <= 0.04:
                    return True
            return False
        if ka == "seg" or kb == "seg":
            si, oi = (i, j) if ka == "seg" else (j, i)
            _ks, os, ps, ls = meta[si]
            okind, oobj, opts, ol = meta[oi]
            if okind == "pad":
                if ls not in oobj["layers"]:
                    return False
                l, t, r, b = oobj["box"]
                for x, y in ps:
                    if dist_pt_rect(x, y, (l, t, r, b)) <= 0.06:
                        return True
                return False
            if okind == "via":
                for x, y in opts:
                    if dist_pt_seg(x, y, os[0], os[1], os[2], os[3]) <= 0.12 and (ol is None or ol == ls or True):
                        return True
                return False
            if ol is not None and ol != ls:
                return False
            for x, y in opts:
                if dist_pt_seg(x, y, os[0], os[1], os[2], os[3]) <= 0.06:
                    return True
            return False
        # pad/via vs pad/via
        for x, y in pa:
            for x2, y2 in pb:
                if math.hypot(x - x2, y - y2) <= 0.35:
                    # pads of different layers don't touch unless both include a layer
                    if ka == "pad" and kb == "pad":
                        if set(oa["layers"]) & set(ob["layers"]):
                            return True
                        return False
                    return True
        return False

    for i in range(n):
        for j in near(i):
            if j < i:
                continue
            if touches(i, j):
                union(i, j)
    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    return items, list(groups.values())


def island_bbox(items, idxs):
    xs, ys = [], []
    for i in idxs:
        kind, obj = items[i]
        if kind == "pad":
            l, t, r, b = obj["box"]
            xs += [l, r]
            ys += [t, b]
        elif kind == "via":
            xs.append(obj[0])
            ys.append(obj[1])
        else:
            xs += [obj[0], obj[2]]
            ys += [obj[1], obj[3]]
    return min(xs), min(ys), max(xs), max(ys)


def island_is_m1000_only(items, idxs) -> bool:
    for i in idxs:
        kind, obj = items[i]
        if kind == "pad":
            if obj["ref"] != "M1000":
                return False
        else:
            return False
    return True


def route_local(geom: Geom, net: str, src, dst, width: float, expand: float, forbidden=None):
    """8-connected search from src copper to dst copper. Returns a path of
    (x, y, lay) or None. lay is 'F' or 'B'; a via is a repeated point with
    the layer change."""
    # Window around the source point closest to the destination, so a long
    # trunk doesn't blow the grid up. 0.05 mm stays put; that is the pitch
    # the pin-field and sense-channel gaps need.
    def _pts(group):
        out = []
        for kind, obj in group:
            if kind == "pad":
                out.append((obj["x"], obj["y"]))
            elif kind == "via":
                out.append((obj[0], obj[1]))
            else:
                out.append((obj[0], obj[1]))
                out.append((obj[2], obj[3]))
        return out
    sp = _pts(src)
    dp = _pts(dst)
    if not sp or not dp:
        return None
    dcx = sum(p[0] for p in dp) / len(dp)
    dcy = sum(p[1] for p in dp) / len(dp)
    ax, ay = min(sp, key=lambda p: (p[0] - dcx) ** 2 + (p[1] - dcy) ** 2)
    x0 = max(EDGE, ax - expand)
    y0 = max(EDGE, ay - expand)
    x1 = min(BOARD_W - EDGE, ax + expand)
    y1 = min(BOARD_H - EDGE, ay + expand)
    grid = GRID
    nx = int(round((x1 - x0) / grid)) + 1
    ny = int(round((y1 - y0) / grid)) + 1
    halo = width / 2 + CLR - 0.005
    vhalo = VIA_SIZE / 2 + CLR - 0.005
    blk = [bytearray(nx * ny), bytearray(nx * ny)]
    vblk = bytearray(nx * ny)

    def mark_disk(cx, cy, rad, li, via_only=False):
        ix0 = max(0, int((cx - rad - x0) / grid) - 1)
        ix1 = min(nx - 1, int((cx + rad - x0) / grid) + 1)
        iy0 = max(0, int((cy - rad - y0) / grid) - 1)
        iy1 = min(ny - 1, int((cy + rad - y0) / grid) + 1)
        r2 = rad * rad
        for iy in range(iy0, iy1 + 1):
            dy = (y0 + iy * grid) - cy
            row = iy * nx
            for ix in range(ix0, ix1 + 1):
                dx = (x0 + ix * grid) - cx
                if dx * dx + dy * dy <= r2:
                    if via_only:
                        vblk[row + ix] = 1
                    elif li is None:
                        blk[0][row + ix] = 1
                        blk[1][row + ix] = 1
                    else:
                        blk[li][row + ix] = 1

    for p in geom.pads:
        if p["net"] == net:
            continue
        l, t, r, b = p["box"]
        if r < x0 - 1 or l > x1 + 1 or b < y0 - 1 or t > y1 + 1:
            continue
        rad = halo
        reach = max(rad, 0.62)
        ix0 = max(0, int((l - reach - x0) / grid) - 1)
        ix1 = min(nx - 1, int((r + reach - x0) / grid) + 1)
        iy0 = max(0, int((t - reach - y0) / grid) - 1)
        iy1 = min(ny - 1, int((b + reach - y0) / grid) + 1)
        for iy in range(iy0, iy1 + 1):
            yy = y0 + iy * grid
            row = iy * nx
            for ix in range(ix0, ix1 + 1):
                if dist_pt_rect(x0 + ix * grid, yy, p["box"]) <= rad:
                    for L in p["layers"]:
                        blk[0 if L == "F" else 1][row + ix] = 1
                if dist_pt_rect(x0 + ix * grid, yy, p["box"]) <= 0.58:
                    vblk[row + ix] = 1
    for sx1, sy1, sx2, sy2, sl, sn, sw in geom.segs:
        if sn == net:
            continue
        if max(sx1, sx2) < x0 - 1 or min(sx1, sx2) > x1 + 1 or max(sy1, sy2) < y0 - 1 or min(sy1, sy2) > y1 + 1:
            continue
        rad = halo + sw / 2
        li = 0 if sl == "F" else 1
        length = math.hypot(sx2 - sx1, sy2 - sy1)
        steps = max(1, int(length / (grid * 0.9)))
        for i in range(steps + 1):
            u = i / steps
            mark_disk(sx1 + (sx2 - sx1) * u, sy1 + (sy2 - sy1) * u, rad, li)
            mark_disk(sx1 + (sx2 - sx1) * u, sy1 + (sy2 - sy1) * u, vhalo + sw / 2 + 0.08, None, via_only=True)
    for vx, vy, vn, vsz, vd in geom.vias:
        if vn == net:
            continue
        if vx < x0 - 1 or vx > x1 + 1 or vy < y0 - 1 or vy > y1 + 1:
            continue
        mark_disk(vx, vy, halo + vsz / 2, None)
        mark_disk(vx, vy, vhalo + vsz / 2 + 0.08, None, via_only=True)
    for hx, hy, hd in geom.holes:
        if hx < x0 - 2 or hx > x1 + 2 or hy < y0 - 2 or hy > y1 + 2:
            continue
        rad = (VIA_DRILL + hd) / 2 + 0.25
        ix0 = max(0, int((hx - rad - x0) / grid) - 1)
        ix1 = min(nx - 1, int((hx + rad - x0) / grid) + 1)
        iy0 = max(0, int((hy - rad - y0) / grid) - 1)
        iy1 = min(ny - 1, int((hy + rad - y0) / grid) + 1)
        r2 = rad * rad
        for iy in range(iy0, iy1 + 1):
            dy = (y0 + iy * grid) - hy
            row = iy * nx
            for ix in range(ix0, ix1 + 1):
                dx = (x0 + ix * grid) - hx
                if dx * dx + dy * dy <= r2:
                    vblk[row + ix] = 1
    if forbidden:
        for iy in range(ny):
            yy = y0 + iy * GRID
            row = iy * nx
            for ix in range(nx):
                if forbidden(x0 + ix * GRID, yy):
                    blk[0][row + ix] = 1
                    blk[1][row + ix] = 1
                    vblk[row + ix] = 1

    def cell(x, y):
        return int(round((x - x0) / grid)), int(round((y - y0) / grid))

    def inside(ix, iy):
        return 0 <= ix < nx and 0 <= iy < ny

    goal = [bytearray(nx * ny), bytearray(nx * ny)]

    def paint_copper(group, as_goal):
        cells = []
        for kind, obj in group:
            if kind == "pad":
                l, t, r, b = obj["box"]
                ix0 = max(0, int((l - x0) / grid) - 1)
                ix1 = min(nx - 1, int((r - x0) / grid) + 1)
                iy0 = max(0, int((t - y0) / grid) - 1)
                iy1 = min(ny - 1, int((b - y0) / grid) + 1)
                lays = [0 if L == "F" else 1 for L in obj["layers"]]
                for iy in range(iy0, iy1 + 1):
                    yy = y0 + iy * grid
                    for ix in range(ix0, ix1 + 1):
                        if dist_pt_rect(x0 + ix * grid, yy, obj["box"]) <= max(0.03, grid * 0.6):
                            for li in lays:
                                blk[li][iy * nx + ix] = 0
                                if as_goal:
                                    goal[li][iy * nx + ix] = 1
                                cells.append((ix, iy, li))
            elif kind == "via":
                ix, iy = cell(obj[0], obj[1])
                if inside(ix, iy):
                    for li in (0, 1):
                        blk[li][iy * nx + ix] = 0
                        if as_goal:
                            goal[li][iy * nx + ix] = 1
                        cells.append((ix, iy, li))
            else:
                li = 0 if obj[4] == "F" else 1
                length = math.hypot(obj[2] - obj[0], obj[3] - obj[1])
                steps = max(1, int(length / (grid * 0.8)))
                for i in range(steps + 1):
                    u = i / steps
                    ix, iy = cell(obj[0] + (obj[2] - obj[0]) * u, obj[1] + (obj[3] - obj[1]) * u)
                    if inside(ix, iy):
                        blk[li][iy * nx + ix] = 0
                        if as_goal:
                            goal[li][iy * nx + ix] = 1
                        cells.append((ix, iy, li))
        return cells

    starts = paint_copper(src, False)
    paint_copper(dst, True)
    if not starts or (not any(goal[0]) and not any(goal[1])):
        return None, 0
    # Drop starts that are already goals.
    ax = sum(x0 + ix * GRID for ix, iy, li in starts) / len(starts)
    ay = sum(y0 + iy * GRID for ix, iy, li in starts) / len(starts)
    # Heuristic target: a goal cell near the dest centroid.
    dest_pts = []
    for kind, obj in dst:
        if kind == "pad":
            dest_pts.append((obj["x"], obj["y"]))
        elif kind == "via":
            dest_pts.append((obj[0], obj[1]))
        else:
            dest_pts.append(((obj[0] + obj[2]) / 2, (obj[1] + obj[3]) / 2))
    tx = sum(p[0] for p in dest_pts) / len(dest_pts)
    ty = sum(p[1] for p in dest_pts) / len(dest_pts)

    def heur(ix, iy):
        return math.hypot(x0 + ix * grid - tx, y0 + iy * grid - ty) / grid

    inf = 10 ** 12
    best = {}
    parent = {}
    pq = []
    for ix, iy, li in starts:
        best[(ix, iy, li)] = 0
        heapq.heappush(pq, (heur(ix, iy), 0.0, ix, iy, li))
    found = None
    expanded = 0
    dirs = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
            (1, 1, 1.42), (1, -1, 1.42), (-1, 1, 1.42), (-1, -1, 1.42))
    while pq and expanded < 160000:
        _h, g, ix, iy, li = heapq.heappop(pq)
        if g != best.get((ix, iy, li)):
            continue
        expanded += 1
        if goal[li][iy * nx + ix] and g > 0:
            found = (ix, iy, li)
            break
        for dx, dy, cost in dirs:
            jx, jy = ix + dx, iy + dy
            if not inside(jx, jy):
                continue
            blocked = blk[li][jy * nx + jx]
            is_goal = goal[li][jy * nx + jx]
            if blocked and not is_goal:
                continue
            ng = g + cost
            key = (jx, jy, li)
            if ng < best.get(key, inf):
                best[key] = ng
                parent[key] = (ix, iy, li)
                heapq.heappush(pq, (ng + heur(jx, jy), ng, jx, jy, li))
                if is_goal and ng > 0:
                    # Land immediately; don't walk through the goal.
                    found = (jx, jy, li)
                    pq.clear()
                    break
        if found:
            break
        i = iy * nx + ix
        if vblk[i] == 0 and blk[0][i] == 0 and blk[1][i] == 0:
            oli = 1 - li
            ng = g + 6.0
            key = (ix, iy, oli)
            if ng < best.get(key, inf):
                best[key] = ng
                parent[key] = (ix, iy, li)
                heapq.heappush(pq, (ng + heur(ix, iy), ng, ix, iy, oli))
    if not found:
        return None, expanded
    path = [found]
    while path[-1] in parent:
        path.append(parent[path[-1]])
        if len(path) > 8000:
            return None, expanded
    path.reverse()
    world = [(x0 + ix * grid, y0 + iy * grid, "F" if li == 0 else "B") for ix, iy, li in path]
    return world, expanded


def _project(group, x, y):
    best = None
    bd = 1e9
    for kind, obj in group:
        if kind == "pad":
            l, t, r, b = obj["box"]
            cx = min(max(x, l), r)
            cy = min(max(y, t), b)
            d = math.hypot(x - cx, y - cy)
            if d < bd:
                bd = d
                best = (cx, cy, obj["layers"][0] if obj["layers"] else "F")
        elif kind == "via":
            d = math.hypot(x - obj[0], y - obj[1])
            if d < bd:
                bd = d
                best = (obj[0], obj[1], None)
        else:
            x1, y1, x2, y2 = obj[0], obj[1], obj[2], obj[3]
            dx, dy = x2 - x1, y2 - y1
            if abs(dx) < 1e-12 and abs(dy) < 1e-12:
                d = math.hypot(x - x1, y - y1)
                px, py = x1, y1
            else:
                u = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
                px, py = x1 + u * dx, y1 + u * dy
                d = math.hypot(x - px, y - py)
            if d < bd:
                bd = d
                best = (px, py, obj[4])
    return best, bd


def commit_world(board, geom, path, net, width, new_ids, src=None, dst=None) -> bool:
    if not path or len(path) < 2:
        return False
    if src is not None:
        snap, dist = _project(src, path[0][0], path[0][1])
        if snap and dist < 0.8:
            path = [(snap[0], snap[1], path[0][2])] + list(path[1:])
    if dst is not None:
        snap, dist = _project(dst, path[-1][0], path[-1][1])
        if snap and dist < 0.8:
            path = list(path[:-1]) + [(snap[0], snap[1], path[-1][2])]
    # Collapse colinear same-layer runs.
    simp = [path[0]]
    for i in range(1, len(path) - 1):
        x0, y0, l0 = simp[-1]
        x1, y1, l1 = path[i]
        x2, y2, l2 = path[i + 1]
        if l0 == l1 == l2 and abs((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)) < 1e-6:
            continue
        simp.append(path[i])
    if path[-1] != simp[-1]:
        simp.append(path[-1])
    pending = []
    for i in range(len(simp) - 1):
        x1, y1, l1 = simp[i]
        x2, y2, l2 = simp[i + 1]
        if l1 != l2:
            if not geom.via_ok(x2, y2, net):
                return False
            pending.append(("via", x2, y2))
        else:
            if not seg_ok_land(geom, x1, y1, x2, y2, width, l1, net):
                return False
            pending.append(("seg", x1, y1, x2, y2, l1))
    for item in pending:
        if item[0] == "via":
            add_via(board, geom, item[1], item[2], net, new_ids)
        else:
            add_track(board, geom, item[1], item[2], item[3], item[4], width, net, item[5], new_ids)
    return True


def items_of(items, idxs):
    return [items[i] for i in idxs]


def _drop_uuids(board, geom, new_ids, fresh):
    for t in list(board.GetTracks()):
        uid = t.m_Uuid.AsString()
        if uid in fresh:
            board.Remove(t)
            new_ids.discard(uid)
    geom.rebuild()


def connect_net(board, geom, net, width, new_ids, expand, forbidden=None, skip_m1000=False, already=None) -> str:
    items, groups = islands_of(geom, net)
    if len(groups) < 2:
        return "single"
    groups.sort(key=len, reverse=True)
    if skip_m1000:
        groups = [g for g in groups if not island_is_m1000_only(items, g)]
        if len(groups) < 2:
            return "m1000-only"
        groups.sort(key=len, reverse=True)
    main = groups[0]
    before = len(groups)
    joined = 0
    failed = 0
    for g in groups[1:]:
        if skip_m1000 and island_is_m1000_only(items, g):
            continue
        src = items_of(items, g)
        dst = items_of(items, main)
        labels = []
        for kind, obj in src:
            if kind == "pad":
                labels.append(f"{obj['ref']}.{obj['num']}")
        key = (net, tuple(labels) or ("stub", round(src[0][1][0], 2), round(src[0][1][1], 2)))
        if already is not None and key in already:
            continue
        result = route_local(geom, net, src, dst, width, expand, forbidden)
        if result is None or result[0] is None:
            exp = 0 if result is None else result[1]
            print(f"    FAIL {net} {labels or 'stub'} exp={exp}", flush=True)
            failed += 1
            if already is not None:
                already.add(key)
            continue
        path, exp = result
        fresh = set()
        if commit_world(board, geom, path, net, width, fresh, src, dst):
            _items2, groups2 = islands_of(geom, net)
            if skip_m1000:
                groups2 = [g for g in groups2 if not island_is_m1000_only(_items2, g)]
            if len(groups2) < before:
                new_ids |= fresh
                print(f"    joined {net} {labels or 'stub'} cells={len(path)} islands {before}->{len(groups2)}", flush=True)
                return "joined:1"
            _drop_uuids(board, geom, fresh, fresh)
            print(f"    NOJOIN {net} {labels or 'stub'} cells={len(path)}", flush=True)
        else:
            print(f"    CLEAR {net} {labels or 'stub'} cells={len(path)}", flush=True)
        failed += 1
        if already is not None:
            already.add(key)
    return f"joined={joined} failed={failed}"


def move_sensor_gnd_via(board, geom, new_ids) -> str:
    """The 0.60 mm via at (38.4, 55.6) seals the only 0.20 mm exit from the
    south SuperSeal pins. Slide it south onto the existing F spine."""
    target = None
    for t in board.GetTracks():
        if not is_via(t) or t.GetNetname() != "SENSOR_GND":
            continue
        x, y = pcbnew.ToMM(t.GetPosition().x), pcbnew.ToMM(t.GetPosition().y)
        if abs(x - 38.4) < 0.05 and abs(y - 55.6) < 0.05:
            target = t
            break
    if target is None:
        return "via-not-found"
    # y=57.2 is a PWR_OUT1 back-side track. 56.4 still clears it and
    # still lets a 0.20 mm track out of J1 pin 21.
    nx, ny = 38.4, 56.4
    if not geom.via_ok(nx, ny, "SENSOR_GND"):
        return "new-via-blocked"
    if not geom.seg_ok(38.4, 55.6, nx, ny, 0.28, "B", "SENSOR_GND"):
        return "b-extend-blocked"
    target.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(nx), pcbnew.FromMM(ny)))
    geom.rebuild()
    add_track(board, geom, 38.4, 55.6, nx, ny, 0.28, "SENSOR_GND", "B", new_ids)
    return f"moved to ({nx},{ny})"


def nudge_r1(board) -> str:
    """F1/R1 courtyard is the only overlap a <=0.5 mm nudge can clear.
    Shift R1 +X just enough that the courtyard boxes separate, and refuse
    the move if any pad copper then overlaps."""
    f1 = r1 = None
    for fp in board.GetFootprints():
        if fp.GetReference() == "F1":
            f1 = fp
        elif fp.GetReference() == "R1":
            r1 = fp
    if f1 is None or r1 is None:
        return "missing"
    def cbox(fp):
        bb = fp.GetCourtyard(pcbnew.F_CrtYd)
        if bb is None or bb.OutlineCount() == 0:
            b = fp.GetBoundingBox(False, False)
            return (pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop()),
                    pcbnew.ToMM(b.GetRight()), pcbnew.ToMM(b.GetBottom()))
        xs, ys = [], []
        ol = bb.COutline(0)
        for i in range(ol.PointCount()):
            xs.append(pcbnew.ToMM(ol.CPoint(i).x))
            ys.append(pcbnew.ToMM(ol.CPoint(i).y))
        return min(xs), min(ys), max(xs), max(ys)
    a = cbox(f1)
    b = cbox(r1)
    # Overlap width in X.
    ox = min(a[2], b[2]) - max(a[0], b[0])
    oy = min(a[3], b[3]) - max(a[1], b[1])
    if ox <= 0 or oy <= 0:
        return "already-clear"
    # R1 is east of F1? Move it further east by the overlap plus a hair.
    dx = ox + 0.05
    if dx > 0.50:
        return f"needs {dx:.2f} mm, over the 0.5 cap"
    old = r1.GetPosition()
    r1.SetPosition(pcbnew.VECTOR2I(old.x + pcbnew.FromMM(dx), old.y))
    # Pad copper overlap check against every other pad.
    def pad_boxes(fp):
        out = []
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            out.append((pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()),
                        pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom())))
        return out
    mine = pad_boxes(r1)
    for fp in board.GetFootprints():
        if fp.GetReference() == "R1":
            continue
        for box in pad_boxes(fp):
            for m in mine:
                if min(m[2], box[2]) - max(m[0], box[0]) > 0.01 and min(m[3], box[3]) - max(m[1], box[1]) > 0.01:
                    r1.SetPosition(old)
                    return "pad-overlap, reverted"
    nb = cbox(r1)
    nox = min(a[2], nb[2]) - max(a[0], nb[0])
    noy = min(a[3], nb[3]) - max(a[1], nb[1])
    if nox > 0 and noy > 0:
        r1.SetPosition(old)
        return "still-overlaps, reverted"
    return f"R1 +{dx:.2f} mm X"


def main():
    board = pcbnew.LoadBoard(str(PCB))
    # Placement locks.
    locks = {}
    for fp in board.GetFootprints():
        locks[fp.GetReference()] = (
            round(pcbnew.ToMM(fp.GetPosition().x), 2),
            round(pcbnew.ToMM(fp.GetPosition().y), 2),
            round(fp.GetOrientationDegrees(), 1),
        )
    assert locks["U3"][2] == 90.0 and locks["U4"][2] == 90.0
    assert abs(locks["J1"][0] - 48.8) < 0.05
    assert abs(locks["D1"][0] - 88.0) < 0.05
    assert abs(locks["R10"][1] - 35.70) < 0.05
    geom = Geom(board)
    new_ids = set()
    print("move via:", move_sensor_gnd_via(board, geom, new_ids), flush=True)

    order = [
        ("GND", 0.20, 14.0, True),
        ("SENSOR_5V", 0.20, 12.0, False),
        ("IN_MAP2", 0.20, 14.0, False),
        ("IN_MAP3", 0.20, 14.0, False),
        ("IN_O2S", 0.20, 14.0, False),
        ("IN_O2S2", 0.20, 14.0, False),
        ("IN_RES1", 0.20, 14.0, False),
        ("IN_RES2", 0.20, 14.0, False),
        ("IN_RES3", 0.20, 14.0, False),
        ("ADIO5", 0.20, 16.0, False),
        ("ADIO6", 0.20, 16.0, False),
        ("ADIO1", 0.20, 18.0, False),
        ("ADIO2", 0.20, 18.0, False),
        ("ADIO3", 0.20, 18.0, False),
        ("ADIO4", 0.20, 18.0, False),
        ("ADIO7", 0.20, 18.0, False),
        ("ADIO8", 0.20, 24.0, False),
        ("PWR_OUT1", 0.20, 26.0, False),
        ("PWR_OUT2", 0.20, 26.0, False),
        ("PWR_OUT3", 0.20, 26.0, False),
        ("PWR_OUT4", 0.20, 26.0, False),
        ("IGN_SW", 0.20, 26.0, False),
        ("VBAT", 0.22, 18.0, False),
    ]
    already = set()
    for _pass in range(2):
        print(f"--- pass {_pass} ---", flush=True)
        progress = False
        for net, width, expand, skip_m in order:
            forbidden = vbat_forbidden if net == "VBAT" else None
            if net == "VBAT":
                msg = "start"
                for _k in range(6):
                    msg = connect_vbat(board, geom, new_ids)
                    if isinstance(msg, str) and msg.startswith("joined:"):
                        progress = True
                        continue
                    break
            else:
                msg = "start"
                for _k in range(8):
                    msg = connect_net(
                        board, geom, net, width, new_ids, expand, forbidden, skip_m, already
                    )
                    if msg.startswith("joined:"):
                        progress = True
                        continue
                    break
            print(f"  {net}: {msg}", flush=True)
        if not progress:
            break
    print("R1 nudge:", nudge_r1(board), flush=True)
    if fuse_bridged(board):
        print("FUSE BRIDGED — aborting save", flush=True)
        sys.exit(2)
    if sensor_pours(board):
        print("SENSOR POUR APPEARED — aborting save", flush=True)
        sys.exit(2)
    fill_zones(board)
    board.Save(str(PCB))
    downgrade_to_k8(PCB)
    # Re-load after downgrade so DRC sees the K8 file.
    board = pcbnew.LoadBoard(str(PCB))
    drc = run_drc()
    removed = 0
    for _ in range(3):
        n = drop_new_offenders(board, drc, new_ids)
        removed += n
        if n == 0:
            break
        if fuse_bridged(board):
            print("fuse bridged after cleanup", flush=True)
            sys.exit(2)
        fill_zones(board)
        board.Save(str(PCB))
        downgrade_to_k8(PCB)
        board = pcbnew.LoadBoard(str(PCB))
        drc = run_drc()
    counts, un_nets = summarize(drc)
    print("DRC", dict(counts), flush=True)
    print("nets", dict(un_nets), flush=True)
    print("removed offenders", removed, "sensor pours", sensor_pours(board), "fuse", fuse_bridged(board), flush=True)
    # Locks still hold.
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if ref in ("U3", "U4", "J1", "D1", "R10", "C10", "R20", "C20", "J2", "J3", "M1000", "F1"):
            now = (
                round(pcbnew.ToMM(fp.GetPosition().x), 2),
                round(pcbnew.ToMM(fp.GetPosition().y), 2),
                round(fp.GetOrientationDegrees(), 1),
            )
            if ref == "R1":
                continue
            if ref in locks and now != locks[ref]:
                print(f"LOCK MOVED {ref} {locks[ref]} -> {now}", flush=True)
    plot_png(board, PNG)
    try:
        ART.parent.mkdir(parents=True, exist_ok=True)
        plot_png(board, ART)
    except Exception as exc:
        print("art plot", exc, flush=True)
    tracks = sum(1 for t in board.GetTracks() if not is_via(t))
    vias = sum(1 for t in board.GetTracks() if is_via(t))
    lines = [
        f"tracks={tracks}",
        f"vias={vias}",
        f"footprints={len(list(board.GetFootprints()))}",
        f"drc_shorts={counts.get('shorting_items', 0)}",
        f"drc_crossings={counts.get('tracks_crossing', 0)}",
        f"drc_unconnected={counts.get('unconnected_items', 0)}",
        f"drc_clearance={counts.get('clearance', 0)}",
        f"drc_courtyards={counts.get('courtyards_overlap', 0)}",
        f"drc_padstack={counts.get('padstack_invalid', 0)}",
        "strategy=close_carrier_pass2_local_8conn",
        "kicad_cli=8.0.9",
        f"fuse_bridged={fuse_bridged(board)}",
        f"sensor_pours={sensor_pours(board)}",
        "placements_locked=U3/U4/J1/D1/senseRC/J2/J3/M1000/F1",
    ]
    STATUS.write_text("\n".join(lines) + "\n")
    payload = {
        "counts": dict(counts),
        "unconnected_nets": dict(un_nets),
        "tracks": tracks,
        "vias": vias,
        "fuse_bridged": fuse_bridged(board),
        "sensor_pours": sensor_pours(board),
    }
    DRC_JSON.write_text(json.dumps(payload, indent=2) + "\n")
    LEFTOVER.write_text(
        "# Leftover after carrier pass 2\n\n"
        + "\n".join(f"- {k}: {v}" for k, v in sorted(un_nets.items(), key=lambda kv: -kv[1]))
        + "\n\n"
        + "\n".join(f"- {k}: {v}" for k, v in sorted(counts.items()))
        + "\n"
    )
    print("wrote", DRC_JSON, flush=True)


def connect_vbat(board, geom, new_ids) -> str:
    """Stitch post-fuse VBAT pour islands into the main island with a local
    0.22 mm search. Pre-fuse copper stays forbidden."""
    from close_carrier_rats import outline_points, poly_seed, point_in_poly

    zones = []
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetIsRuleArea() or z.GetNetname() != "VBAT" or not z.IsFilled():
            continue
        lay = z.GetFirstLayer()
        name = "F" if lay == pcbnew.F_Cu else "B"
        try:
            polys = z.GetFilledPolysList(lay)
        except TypeError:
            polys = z.GetFilledPolysList()
        for k in range(polys.OutlineCount()):
            pts = outline_points(polys.COutline(k))
            seed = poly_seed(pts)
            if seed is None or len(pts) < 3:
                continue
            zones.append({
                "lay": name,
                "pts": pts,
                "seed": seed,
                "bb": (min(p[0] for p in pts), min(p[1] for p in pts),
                       max(p[0] for p in pts), max(p[1] for p in pts)),
            })
    if not zones:
        return "no-zones"
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

    def hits_poly(x, y, isl, lay_ok):
        if not lay_ok:
            return False
        l, t, r, b = isl["bb"]
        if not (l - 0.3 <= x <= r + 0.3 and t - 0.3 <= y <= b + 0.3):
            return False
        return point_in_poly(x, y, isl["pts"])

    for s in geom.segs:
        if s[5] != "VBAT":
            continue
        x1, y1, x2, y2, lay = s[0], s[1], s[2], s[3], s[4]
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(length / 0.4))
        hit = set()
        for i in range(steps + 1):
            u = i / steps
            x, y = x1 + (x2 - x1) * u, y1 + (y2 - y1) * u
            for zi, isl in enumerate(zones):
                if hits_poly(x, y, isl, isl["lay"] == lay):
                    hit.add(zi)
        hit = list(hit)
        for a in hit[1:]:
            union(hit[0], a)
    for vx, vy, vn, _sz, _d in geom.vias:
        if vn != "VBAT":
            continue
        hit = [i for i, isl in enumerate(zones) if hits_poly(vx, vy, isl, True)]
        for a in hit[1:]:
            union(hit[0], a)
    groups = defaultdict(list)
    for i in range(len(zones)):
        groups[find(i)].append(i)

    def has(idxs, x, y):
        for i in idxs:
            if hits_poly(x, y, zones[i], True):
                return True
        return False

    main = pre = None
    for k, idxs in groups.items():
        if has(idxs, 80.0, 41.5) or has(idxs, 67.2, 18.0):
            main = k
        if has(idxs, 90.0, 8.0) or has(idxs, 58.0, 18.0):
            pre = k
    if main is None:
        return "no-main"
    print(f"    VBAT groups={len(groups)} main={len(groups[main])} pre={0 if pre is None else len(groups.get(pre, []))}", flush=True)
    # Represent each non-main, non-pre group by a short same-net stub at the
    # seed so the local router has a start, and the main pour as a goal.
    # We synthesize pad-like boxes from the seed.
    joined = 0
    failed = 0
    main_items = []
    for i in groups[main]:
        isl = zones[i]
        sx, sy = isl["seed"]
        main_items.append(("seg", (sx, sy, sx + 0.05, sy, isl["lay"], "VBAT", 0.2)))
    for k, idxs in groups.items():
        if k == main or k == pre:
            continue
        isl = zones[idxs[0]]
        # Skip slivers smaller than a via.
        l, t, r, b = isl["bb"]
        if (r - l) < 0.4 and (b - t) < 0.4:
            continue
        sx, sy = isl["seed"]
        src = [("seg", (sx, sy, sx + 0.05, sy, isl["lay"], "VBAT", 0.2))]
        result = route_local(geom, "VBAT", src, main_items, 0.22, 16.0, vbat_forbidden)
        if result is None or result[0] is None:
            exp = 0 if result is None else result[1]
            print(f"    FAIL VBAT seed ({sx:.2f},{sy:.2f}) exp={exp}", flush=True)
            failed += 1
            continue
        path, exp = result
        if commit_world(board, geom, path, "VBAT", 0.22, new_ids):
            print(f"    joined VBAT ({sx:.2f},{sy:.2f}) cells={len(path)}", flush=True)
            joined += 1
            return f"joined:{joined}"
        print(f"    CLEAR VBAT ({sx:.2f},{sy:.2f})", flush=True)
        failed += 1
    return f"joined={joined} failed={failed}"


if __name__ == "__main__":
    main()
