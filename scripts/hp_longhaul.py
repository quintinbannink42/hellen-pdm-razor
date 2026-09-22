#!/usr/bin/env python3
"""Join PWR_OUT1–4 driver islands to the SuperSeal pins.

Wide current path stays on F.Cu with an F.Mask opening (assemblers can add
solder). Where the mega-mcu144 south pad wall is a 0.6 mm gap, the track
necks to 0.20 mm and may hop to B.Cu to pass the signal fanout already on
F.Cu. Does not bridge F1, does not pour SENSOR_GND, does not replay
cut_crossings_sexp.py.
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
import layout_109x98 as L

GRID = 0.10
CLR = 0.20
# 0.008 mm inside the 0.20 rule so a gap-center cell stays routable.
HALO = 0.10 + CLR - 0.008
EDGE = 0.55


def jog_crossing(board) -> int:
    """Move the IN_O2S2 back-side run off the IN_RES2 diagonal."""
    hits = []
    for t in board.GetTracks():
        if L.is_via(t) or t.GetLayer() != pcbnew.B_Cu:
            continue
        if t.GetNetname() != "IN_O2S2":
            continue
        a, b = t.GetStart(), t.GetEnd()
        x1, y1, x2, y2 = L.ToMM(a.x), L.ToMM(a.y), L.ToMM(b.x), L.ToMM(b.y)
        if abs(y1 - 54.0) < 0.05 and abs(y2 - 54.0) < 0.05 and abs(x2 - x1) > 8:
            hits.append((t, min(x1, x2), max(x1, x2), y1))
    n = 0
    for t, x1, x2, y in hits:
        # Gap the horizontal under the IN_RES2 diagonal (x≈88–89.2, y≤54.3).
        pts = [
            (x1, y),
            (87.2, y),
            (87.2, 54.95),
            (90.8, 54.95),
            (90.8, y),
            (x2, y),
        ]
        ok = True
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            if not L.segment_clear(board, ax, ay, bx, by, 0.20, "IN_O2S2", "B"):
                print(f"  jog blocked ({ax},{ay})-({bx},{by})", flush=True)
                ok = False
                break
        if not ok:
            continue
        t.SetStart(L.mm(pts[0][0], pts[0][1]))
        t.SetEnd(L.mm(pts[1][0], pts[1][1]))
        for (ax, ay), (bx, by) in zip(pts[1:], pts[2:]):
            L.add_track(board, ax, ay, bx, by, 0.20, "IN_O2S2", "B")
        n += 1
    return n


class Router:
    def __init__(self, board):
        self.board = board
        self.nx = int(L.BOARD_W / GRID) + 2
        self.ny = int(L.BOARD_H / GRID) + 2
        self.segs = []
        self.vias = []
        for item in L.iter_segs(board):
            if item[0] == "via":
                _, _t, x, y, net, sz = item
                self.vias.append((x, y, net, sz))
            else:
                _, _t, x1, y1, x2, y2, lay, net, w = item
                self.segs.append((x1, y1, x2, y2, lay, net, w))
        self.pads = []
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                attr = pad.GetAttribute()
                names = L.layer_names(pad)
                if attr in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                    layers = ("F", "B")
                elif "F.Cu" in names and "B.Cu" in names:
                    layers = ("F", "B")
                elif "F.Cu" in names:
                    layers = ("F",)
                elif "B.Cu" in names:
                    layers = ("B",)
                else:
                    continue
                self.pads.append(
                    {
                        "net": pad.GetNetname() or "",
                        "box": L.pad_box(pad),
                        "layers": layers,
                    }
                )

    def paint(self, net):
        blk = [bytearray(self.nx * self.ny), bytearray(self.nx * self.ny)]
        vblk = bytearray(self.nx * self.ny)

        def fill(l, t, r, b, layer, via=False):
            ix0 = max(0, int(math.floor(l / GRID)))
            ix1 = min(self.nx - 1, int(math.ceil(r / GRID)))
            iy0 = max(0, int(math.floor(t / GRID)))
            iy1 = min(self.ny - 1, int(math.ceil(b / GRID)))
            for iy in range(iy0, iy1 + 1):
                row = iy * self.nx
                cy = iy * GRID
                if cy < t - GRID or cy > b + GRID:
                    continue
                for ix in range(ix0, ix1 + 1):
                    cx = ix * GRID
                    if l <= cx <= r and t <= cy <= b:
                        if via:
                            vblk[row + ix] = 1
                        elif layer is None:
                            blk[0][row + ix] = 1
                            blk[1][row + ix] = 1
                        else:
                            blk[layer][row + ix] = 1

        for p in self.pads:
            if p["net"] == net:
                continue
            l, t, r, b = p["box"]
            if "F" in p["layers"]:
                fill(l - HALO, t - HALO, r + HALO, b + HALO, 0)
                fill(l - 0.52, t - 0.52, r + 0.52, b + 0.52, None, via=True)
            if "B" in p["layers"]:
                fill(l - HALO, t - HALO, r + HALO, b + HALO, 1)
                fill(l - 0.52, t - 0.52, r + 0.52, b + 0.52, None, via=True)
        for x1, y1, x2, y2, lay, n, w in self.segs:
            if n == net:
                continue
            h = HALO + w / 2 - 0.10  # HALO already includes our half-width
            # foreign half-width extra
            h = (0.10 + CLR + w / 2) - 0.008
            fill(min(x1, x2) - h, min(y1, y2) - h, max(x1, x2) + h, max(y1, y2) + h, 0 if lay == "F" else 1)
            hv = 0.30 + CLR + w / 2
            fill(
                min(x1, x2) - hv,
                min(y1, y2) - hv,
                max(x1, x2) + hv,
                max(y1, y2) + hv,
                None,
                via=True,
            )
        for x, y, n, sz in self.vias:
            if n == net:
                continue
            h = 0.10 + CLR + sz / 2 - 0.008
            fill(x - h, y - h, x + h, y + h, None)
            hv = 0.30 + CLR + sz / 2
            fill(x - hv, y - hv, x + hv, y + hv, None, via=True)
        for ix in range(self.nx):
            for iy in range(self.ny):
                x, y = ix * GRID, iy * GRID
                if x < EDGE or y < EDGE or x > L.BOARD_W - EDGE or y > L.BOARD_H - EDGE:
                    blk[0][iy * self.nx + ix] = 1
                    blk[1][iy * self.nx + ix] = 1
                    vblk[iy * self.nx + ix] = 1
        self.blk = blk
        self.vblk = vblk

    def free(self, ix, iy, lay) -> bool:
        if not (0 <= ix < self.nx and 0 <= iy < self.ny):
            return False
        return self.blk[lay][iy * self.nx + ix] == 0

    def nearest(self, x, y, layers, rad_max=18):
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

    def route(self, x1, y1, x2, y2, start_layers, goal_layers):
        starts = self.nearest(x1, y1, start_layers)
        if not starts:
            return None
        inf = 10**9
        best = {}
        pq = []
        parent = {}
        for ix, iy, lay in starts:
            c0 = 0 if lay == 0 else 6
            best[(ix, iy, lay)] = c0
            heapq.heappush(pq, (c0 + abs(ix * GRID - x2) + abs(iy * GRID - y2), c0, ix, iy, lay))
        expanded = 0
        found = None
        while pq and expanded < 2500000:
            _h, g, ix, iy, lay = heapq.heappop(pq)
            if g != best.get((ix, iy, lay)):
                continue
            expanded += 1
            if lay in goal_layers and math.hypot(ix * GRID - x2, iy * GRID - y2) <= 0.55 and g > 0:
                found = (ix, iy, lay)
                break
            step_base = 1.0 if lay == 0 else 3.4
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = ix + dx, iy + dy
                if not self.free(nx, ny, lay):
                    continue
                ng = g + step_base
                key = (nx, ny, lay)
                if ng < best.get(key, inf):
                    best[key] = ng
                    parent[key] = (ix, iy, lay)
                    cx, cy = nx * GRID, ny * GRID
                    heapq.heappush(pq, (ng + abs(cx - x2) + abs(cy - y2), ng, nx, ny, lay))
            if self.vblk[iy * self.nx + ix] == 0 and self.free(ix, iy, 0) and self.free(ix, iy, 1):
                nlay = 1 - lay
                ng = g + 8.0
                key = (ix, iy, nlay)
                if ng < best.get(key, inf):
                    best[key] = ng
                    parent[key] = (ix, iy, lay)
                    heapq.heappush(pq, (ng + abs(ix * GRID - x2) + abs(iy * GRID - y2), ng, ix, iy, nlay))
        print(f"    expanded {expanded} found {found is not None}", flush=True)
        if not found:
            return None
        path = [found]
        while path[-1] in parent:
            path.append(parent[path[-1]])
            if len(path) > 20000:
                return None
        path.reverse()
        return path

    def commit(self, path, x1, y1, x2, y2, net):
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
        layname = {0: "F", 1: "B"}
        for i in range(len(simp) - 1):
            xa, ya, la = simp[i]
            xb, yb, lb = simp[i + 1]
            if la != lb:
                L.add_via(self.board, xb, yb, net, 0.55, 0.30)
                self.vias.append((xb, yb, net, 0.55))
                continue
            L.add_track(self.board, xa, ya, xb, yb, 0.20, net, layname[la])
            self.segs.append((xa, ya, xb, yb, layname[la], net, 0.20))
        fl = sum(math.hypot(simp[i + 1][0] - simp[i][0], simp[i + 1][1] - simp[i][1]) for i in range(len(simp) - 1) if simp[i][2] == simp[i + 1][2] == 0)
        bl = sum(math.hypot(simp[i + 1][0] - simp[i][0], simp[i + 1][1] - simp[i][1]) for i in range(len(simp) - 1) if simp[i][2] == simp[i + 1][2] == 1)
        return fl, bl


def add_trunk(board, net, pts, width, layer="F"):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if not L.segment_clear(board, x1, y1, x2, y2, width, net, layer):
            print(f"  trunk refused {net} w={width} ({x1},{y1})-({x2},{y2})", flush=True)
            return False
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        L.add_track(board, x1, y1, x2, y2, width, net, layer)
    print(f"  trunk {net} w={width} {pts[0]} -> {pts[-1]}", flush=True)
    return True


def mask_new(board, before_count) -> int:
    """Open F.Mask over F.Cu PWR_OUT tracks that do not already have an opening."""
    existing = set()
    for d in board.GetDrawings():
        if d.GetLayer() != pcbnew.F_Mask or not hasattr(d, "GetStart"):
            continue
        a, b = d.GetStart(), d.GetEnd()
        key = (
            round(L.ToMM(a.x), 2),
            round(L.ToMM(a.y), 2),
            round(L.ToMM(b.x), 2),
            round(L.ToMM(b.y), 2),
        )
        existing.add(key)
    n = 0
    for t in list(board.GetTracks()):
        if L.is_via(t) or t.GetLayer() != pcbnew.F_Cu:
            continue
        if not t.GetNetname().startswith("PWR_OUT"):
            continue
        a, b = t.GetStart(), t.GetEnd()
        key = (
            round(L.ToMM(a.x), 2),
            round(L.ToMM(a.y), 2),
            round(L.ToMM(b.x), 2),
            round(L.ToMM(b.y), 2),
        )
        if key in existing:
            continue
        width = max(0.15, L.ToMM(t.GetWidth()) - 0.10)
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(a)
        s.SetEnd(b)
        s.SetWidth(pcbnew.FromMM(width))
        s.SetLayer(pcbnew.F_Mask)
        board.Add(s)
        n += 1
    return n


def stitch_vbat(board) -> list[str]:
    """Tie C1 into the pre-fuse island and D1 into the post-fuse island. Never both F1 pads."""
    notes = []
    # C1.1 (60.52, 7.5) → pre-fuse pour, which begins at x=68.5. Stop at x=70.
    if L.segment_clear(board, 60.52, 7.50, 70.0, 7.50, 0.80, "VBAT", "F"):
        L.add_track(board, 60.52, 7.50, 70.0, 7.50, 0.80, "VBAT", "F")
        notes.append("C1.1 F.Cu strap to pre-fuse x=70")
    else:
        notes.append("C1.1 strap blocked")
    # D1.1 (106, 24.15) south into the post-fuse pour (y>=27.5). Clear of F1.2.
    pts = [(106.0, 24.15), (106.0, 28.4), (103.5, 28.4)]
    if all(L.segment_clear(board, a[0], a[1], b[0], b[1], 0.60, "VBAT", "F") for a, b in zip(pts, pts[1:])):
        for a, b in zip(pts, pts[1:]):
            L.add_track(board, a[0], a[1], b[0], b[1], 0.60, "VBAT", "F")
        notes.append("D1.1 F.Cu strap into post-fuse y=28.4")
    else:
        notes.append("D1.1 strap blocked")
    return notes


def main() -> int:
    board = L.pcbnew.LoadBoard(str(L.PCB)) if False else pcbnew.LoadBoard(str(L.PCB))
    print("jog", jog_crossing(board), flush=True)

    # Series F.Cu trunks that clearance already proved, overlapping the PROFET OUT pads.
    trunks = []
    if add_trunk(board, "PWR_OUT1", [(55.6, 72.40), (34.2, 72.40)], 1.20):
        trunks.append(("PWR_OUT1", 34.2, 72.40))
    if add_trunk(board, "PWR_OUT4", [(103.6, 35.39), (107.2, 35.39), (107.2, 73.6)], 0.35):
        trunks.append(("PWR_OUT4", 107.2, 73.6))

    goals = {
        "PWR_OUT1": (42.30, 55.50),
        "PWR_OUT2": (34.30, 55.50),
        "PWR_OUT3": (34.30, 37.50),
        "PWR_OUT4": (42.30, 37.50),
    }
    starts = {
        "PWR_OUT1": (58.35, 72.40),
        "PWR_OUT2": (101.65, 65.59),
        "PWR_OUT3": (58.35, 43.01),
        "PWR_OUT4": (101.65, 35.39),
    }
    for net, x, y in trunks:
        starts[net] = (x, y)

    router = Router(board)
    report = {}
    for net in ("PWR_OUT1", "PWR_OUT2", "PWR_OUT3", "PWR_OUT4"):
        print(f"route {net} from {starts[net]} to {goals[net]}", flush=True)
        router.paint(net)
        sx, sy = starts[net]
        gx, gy = goals[net]
        path = router.route(sx, sy, gx, gy, (0,), (0, 1))
        if path is None:
            path = router.route(sx, sy, gx, gy, (0, 1), (0, 1))
        if path is None:
            report[net] = "open"
            continue
        fl, bl = router.commit(path, sx, sy, gx, gy, net)
        report[net] = f"F {fl:.1f} mm / B {bl:.1f} mm"
        print(f"  {report[net]}", flush=True)

    # Rebuild router view is stale for widen; widen uses the live board.
    n_wide = L.widen_pwr(board)
    print(f"widened {n_wide}", flush=True)
    n_mask = mask_new(board, 0)
    print(f"new mask openings {n_mask}", flush=True)
    notes = stitch_vbat(board)
    print("stitch", notes, flush=True)

    print("fill", flush=True)
    L.ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    print(f"keepout {L.pour_inside_keepout(board)} fuse {L.fuse_bridged(board)} sensor {L.sensor_pours(board)}", flush=True)
    board.Save(str(L.PCB))
    L.downgrade_to_k8(L.PCB)
    board = pcbnew.LoadBoard(str(L.PCB))
    L.plot_png(board, L.PNG)
    L.plot_png(board, L.ART)
    L.plot_mask(board, L.MASK_PNG)
    L.plot_mask(board, L.ART_MASK)
    print("DRC", flush=True)
    _rc, text, err = L.run_drc()
    (L.ROOT / "scripts" / "drc_109.txt").write_text(text)
    summary = L.summarize_report(text)
    print(json.dumps(summary["counts"], indent=2))
    (L.ROOT / "scripts" / "hp_longhaul_status.txt").write_text(
        "trunks " + json.dumps(trunks) + "\n"
        "route " + json.dumps(report) + "\n"
        "stitch " + json.dumps(notes) + "\n"
        "mask_new " + str(n_mask) + "\n"
        "drc " + json.dumps(summary["counts"]) + "\n"
        f"keepout {L.pour_inside_keepout(board)} fuse {L.fuse_bridged(board)} sensor {L.sensor_pours(board)}\n"
    )
    if err:
        print(err[-300:], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
