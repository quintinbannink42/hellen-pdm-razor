#!/usr/bin/env python3
"""Widest 1 oz corridor out of the even SuperSeal ADIO pins.

Read-only. Does not move footprints, pour copper, bridge F1, pour
SENSOR_GND, export gerbers, or replay cut_crossings_sexp.py.

Odd ADIO pins sit on the east edge of J1, so a pour can leave the pad and
be 3.47 mm wide immediately. Even pins (J1.15/16/17/18) are an interior
column. Both copper layers see the same PTH pads (`remove_unused_layers no`
on a 2-layer stack: F.Cu + B.Cu). F and B on the same XY add, which is the
same rule as scripts/adio_ampacity.txt. A path may leave in any direction,
including around the connector body. The number reported is the minimum
neck of the widest such path, not the sum of parallel 0.60 mm slots.
"""
from __future__ import annotations

import heapq
import math
import re
from pathlib import Path

import numpy as np

PCB = Path(__file__).resolve().parents[1] / "pdmrazora.kicad_pcb"
NEED = 3.47
RULE_CLR = 0.20
# Coarse enough to finish quickly; the pinch is an orthogonal 3.0 mm door,
# so the grid error is well under the gap between 1.20 mm and 3.47 mm.
STEP = 0.025


def _footprint_block(text: str) -> str:
    key = '(footprint "pdmrazora:TE_6473418-1_SuperSeal26_Vertical"'
    i = text.find(key)
    if i < 0:
        raise SystemExit("SuperSeal footprint not in the board")
    j = text.find("\n\t(footprint ", i + len(key))
    if j < 0:
        j = len(text)
    return text[i:j]


def _world(fx, fy, rot_deg, lx, ly):
    """KiCad PCB rotation: Y down, positive angle clockwise."""
    r = math.radians(rot_deg)
    c, s = math.cos(r), math.sin(r)
    return fx + lx * c + ly * s, fy - lx * s + ly * c


def load_j1(path: Path):
    block = _footprint_block(path.read_text())
    at = re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", block)
    fx, fy = float(at.group(1)), float(at.group(2))
    rot = float(at.group(3) or 0)
    pads = []
    for m in re.finditer(r"\(pad (\"[^\"]*\") (thru_hole|np_thru_hole) circle", block):
        start = m.start()
        # Pad sexp ends at the next pad or the close of the footprint pads.
        nxt = block.find("\n\t\t(pad ", start + 4)
        chunk = block[start : nxt if nxt > 0 else start + 800]
        xy = re.search(r"\(at ([-\d.]+) ([-\d.]+)\)", chunk)
        size = re.search(r"\(size ([-\d.]+) ([-\d.]+)\)", chunk)
        drill = re.search(r"\(drill ([-\d.]+)\)", chunk)
        net_m = re.search(r'\(net \d+ "([^"]*)"\)', chunk)
        num = m.group(1).strip('"')
        lx, ly = float(xy.group(1)), float(xy.group(2))
        wx, wy = _world(fx, fy, rot, lx, ly)
        pads.append(
            {
                "num": num,
                "kind": m.group(2),
                "x": wx,
                "y": wy,
                "dia": float(size.group(1)),
                "drill": float(drill.group(1)),
                "net": net_m.group(1) if net_m else "",
            }
        )
    return pads


def _field(pads, source, *, pad_dia, clr, hole_only_nets=(), ignore=()):
    """Half-width available at each cell on one layer.

    `pad_dia` is the copper diameter used for foreign signal pads.
    Mounting holes keep their drilled diameter. Pads in `ignore` (the
    source net) are not obstacles. Nets in `hole_only_nets` obstruct as
    drills rather than as `pad_dia`.
    """
    xs0 = min(p["x"] for p in pads) - 4.0
    ys0 = min(p["y"] for p in pads) - 4.0
    xs1 = max(p["x"] for p in pads) + 4.0
    ys1 = max(p["y"] for p in pads) + 4.0
    xs = np.arange(xs0, xs1 + STEP, STEP)
    ys = np.arange(ys0, ys1 + STEP, STEP)
    X, Y = np.meshgrid(xs, ys)
    inf = np.full(X.shape, 1e6, dtype=np.float64)
    hF = inf.copy()
    hB = inf.copy()
    src_r = source["dia"] / 2
    ignored = {id(source)} | {id(p) for p in ignore}
    for p in pads:
        if id(p) in ignored:
            continue
        hole_r = p["drill"] / 2
        if p["kind"] == "np_thru_hole" or p["net"] in hole_only_nets:
            rF = rB = hole_r
        else:
            rF = rB = pad_dia / 2
        d = np.hypot(X - p["x"], Y - p["y"])
        hF = np.minimum(hF, d - rF - clr)
        hB = np.minimum(hB, d - rB - clr)
    return xs, ys, X, Y, hF, hB, src_r


def widest(pads, source, *, pad_dia, clr, hole_only_nets=(), ignore=()):
    """Minimum F+B neck (mm) of the widest path from `source` to outside.

    Current enters on `source` (the loom pin). Pad metal there is not a
    neck. Pads in `ignore` are same-net copper (not obstacles) but the
    path still has to reach them from `source`, so the bridge counts.
    F and B add on the same XY. Returns (fb_mm, pinch_xy, single_layer_mm).
    """
    xs, ys, X, Y, hF, hB, src_r = _field(
        pads, source, pad_dia=pad_dia, clr=clr, hole_only_nets=hole_only_nets,
        ignore=(source, *ignore),
    )
    score = hF + hB  # FB width = 2 * min(score); each h is a half-width
    on_src = np.hypot(X - source["x"], Y - source["y"]) <= src_r + 1e-9
    ny, nx = score.shape
    env_x0 = min(p["x"] - p["dia"] / 2 for p in pads if p["kind"] != "np_thru_hole") - 0.4
    env_x1 = max(p["x"] + p["dia"] / 2 for p in pads if p["kind"] != "np_thru_hole") + 0.4
    env_y0 = min(p["y"] - p["dia"] / 2 for p in pads if p["kind"] != "np_thru_hole") - 0.4
    env_y1 = max(p["y"] + p["dia"] / 2 for p in pads if p["kind"] != "np_thru_hole") + 0.4
    outside = (X < env_x0) | (X > env_x1) | (Y < env_y0) | (Y > env_y1)

    best = np.full(score.shape, -1.0, dtype=np.float64)
    parent = np.full(score.size, -1, dtype=np.int32)
    heap = []
    sy, sx = np.nonzero(on_src)
    for y, x in zip(sy.tolist(), sx.tolist()):
        best[y, x] = 1e6
        heapq.heappush(heap, (-1e6, y * nx + x))

    found = None
    while heap:
        neg, idx = heapq.heappop(heap)
        sc = -neg
        y, x = divmod(idx, nx)
        if sc < best[y, x] - 1e-9:
            continue
        if outside[y, x] and not on_src[y, x]:
            found = (sc, idx)
            break
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            yy, xx = y + dy, x + dx
            if yy < 0 or xx < 0 or yy >= ny or xx >= nx:
                continue
            cell = 1e6 if on_src[yy, xx] else float(score[yy, xx])
            if cell <= 0:
                continue
            cand = cell if sc >= 1e6 else min(sc, cell)
            if cand > best[yy, xx]:
                best[yy, xx] = cand
                parent[yy * nx + xx] = idx
                heapq.heappush(heap, (-cand, yy * nx + xx))
    if found is None:
        return 0.0, None, 0.0

    sc, idx = found
    # The path score is the min local score. Record the cell nearest the
    # source pad that actually attains it (the exit often only ties it).
    pinch_sc = sc
    pinch_idx = idx
    best_d = 1e9
    guard = 0
    while idx >= 0 and guard < score.size + 2:
        y, x = divmod(idx, nx)
        if not on_src[y, x]:
            cell = float(score[y, x])
            dsrc = (float(X[y, x]) - source["x"]) ** 2 + (float(Y[y, x]) - source["y"]) ** 2
            if cell <= pinch_sc + 1e-6 and dsrc < best_d:
                pinch_sc = min(pinch_sc, cell)
                pinch_idx = idx
                best_d = dsrc
        idx = int(parent[idx])
        guard += 1
    py, px = divmod(pinch_idx, nx)
    # score is hF+hB; each h is a half-width, so FB width is 2*score.
    fb = 2.0 * sc
    return fb, (float(X[py, px]), float(Y[py, px]), 2.0 * pinch_sc), fb / 2.0


def ring_cut(pads, source, pad_dia, clr):
    """Upper bound: sum of the gaps in the ring of nearest foreign pads.

    This is the parallel-slot reading (every door around the pin at once).
    It is not the series neck. Returned as F+B mm, assuming both layers
    identical.
    """
    r = pad_dia / 2
    dists = []
    for p in pads:
        if p is source or p["kind"] == "np_thru_hole" or not p["num"]:
            continue
        d = math.hypot(p["x"] - source["x"], p["y"] - source["y"])
        dists.append(d)
    dists.sort()
    # The enclosing ring is the pads closer than the next pitch step (4 mm
    # skips the far column). Each gap is credited once.
    cap = 0.0
    for d in dists:
        if d > 3.4:
            break
        gap = d - pad_dia - 2 * clr
        if gap > 0:
            cap += gap
    return 2 * cap  # F+B, identical layers


def ceiling_fb():
    """Absolute 1 oz ceiling: copper flush with both 1.3 mm drills, 0 clearance.

    Best door is the 3.0 mm vertical pitch. Diagonal doors are tighter.
    """
    pitch = 3.0
    drill = 1.3
    per_layer = pitch - drill  # 1.70, zero annular, zero clearance
    return per_layer * 2  # 3.40


def main():
    pads = load_j1(PCB)
    by_net = {}
    for p in pads:
        if p["net"]:
            by_net.setdefault(p["net"], []).append(p)
    print(f"J1 pads {len(pads)}")
    for net in ("ADIO1", "ADIO2"):
        p = by_net[net][0]
        print(f"  {net} pin {p['num']} ({p['x']:.2f}, {p['y']:.2f}) dia {p['dia']:.2f} drill {p['drill']:.2f}")

    def report(title, **kw):
        print(f"\n{title}")
        rows = []
        for net in [f"ADIO{i}" for i in range(1, 9)]:
            src = by_net[net][0]
            fb, pinch, single = widest(pads, src, **kw)
            pinch_s = "none"
            if pinch:
                pinch_s = f"({pinch[0]:.2f}, {pinch[1]:.2f}) neck {pinch[2]:.2f}"
            flag = "PASS" if fb + 1e-6 >= NEED else "blocked"
            print(f"  {net:6} {flag:8} F+B {fb:.2f}  layer {single:.2f}  pinch {pinch_s}")
            rows.append((net, fb, single))
        return rows

    as_built = report("as-built pad 2.00 mm, clearance 0.20 mm", pad_dia=2.0, clr=RULE_CLR)
    report("pad 1.60 mm (0.15 mm annular on 1.3 drill), clearance 0.20", pad_dia=1.60, clr=RULE_CLR)
    report("pad = drill 1.30 mm, clearance 0.20", pad_dia=1.30, clr=RULE_CLR)
    report("pad = drill 1.30 mm, clearance 0 (short to the plating)", pad_dia=1.30, clr=0.0)

    def with_nc(net, nums):
        """Same-net bridge: NC holes stay, their pads join `net` (no clearance).

        The search still starts on the ADIO pin, so the copper between that
        pin and the NC pad is part of the neck.
        """
        src = by_net[net][0]
        extra = [p for p in pads if p["num"] in nums]
        fb, pinch, single = widest(
            pads, src, pad_dia=2.0, clr=RULE_CLR, ignore=extra
        )
        pinch_s = "none" if not pinch else f"({pinch[0]:.2f}, {pinch[1]:.2f}) {pinch[2]:.2f}"
        flag = "PASS" if fb + 1e-6 >= NEED else "blocked"
        print(f"  {net:6} + {','.join(nums):8} {flag:8} F+B {fb:.2f}  layer {single:.2f}  pinch {pinch_s}")
        return fb

    print("\nNC same-net bridges (holes stay, one net at a time)")
    with_nc("ADIO2", ["9", "2"])
    with_nc("ADIO4", ["9", "2"])
    with_nc("ADIO6", ["9", "2"])
    with_nc("ADIO8", ["25"])
    with_nc("ADIO6", ["25"])
    with_nc("ADIO4", ["25"])
    with_nc("ADIO8", ["9", "2"])

    print("\nparallel-slot upper bound (not a series neck), as-built F+B")
    for net in ("ADIO2", "ADIO4", "ADIO6", "ADIO8"):
        cap = ring_cut(pads, by_net[net][0], 2.0, RULE_CLR)
        print(f"  {net:6} ring {cap:.2f}")

    ceil_fb = ceiling_fb()
    print(f"\n1 oz ceiling F+B {ceil_fb:.2f} (3.0 mm pitch, 1.3 mm drills, 0 clearance)")
    print(f"need {NEED:.2f}")

    # Sanity: the east-edge odd pin clears 3.47; the interior even pin does not.
    odd = next(fb for net, fb, _s in as_built if net == "ADIO1")
    even = next(fb for net, fb, _s in as_built if net == "ADIO2")
    if odd < NEED:
        raise SystemExit(f"sanity fail: ADIO1 F+B {odd:.2f} < {NEED} (model too tight)")
    if even > 1.40:
        raise SystemExit(f"sanity fail: ADIO2 F+B {even:.2f} looks open")
    if ceil_fb >= NEED:
        raise SystemExit("sanity fail: ceiling meets 3.47, proof is wrong")
    print("sanity ok")


if __name__ == "__main__":
    main()
