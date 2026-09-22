#!/usr/bin/env python3
"""Land remaining ADIO nets with the ADIO6 neck pattern.

For each candidate:
- open local wall jogs if needed
- run B.Cu spine / bus onto a via on existing F.Cu driver copper
- punch a B.Cu-only pour keepout over the spine
- stitch any cut-off GND island

Keep a landing only when unconnected drops and locked checks hold.
Does not move footprints, bridge F1, pour SENSOR_GND, touch PWR_OUT
mask openings, or replay cut_crossings_sexp.py.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout_109x98 as L
import open_corridors as OC


def mask_count(board) -> int:
    return sum(1 for d in board.GetDrawings() if d.GetLayer() == pcbnew.F_Mask)


def unconnected(board) -> int:
    board.BuildConnectivity()
    return board.GetConnectivity().GetUnconnectedCount(False)


def checks(board) -> dict:
    return {
        "unconnected": unconnected(board),
        "keep": L.pour_inside_keepout(board),
        "fuse": L.fuse_bridged(board),
        "sensor": L.sensor_pours(board),
        "mask": mask_count(board),
    }


def locked_ok(info, mask0) -> bool:
    return (
        info["keep"] == 0
        and info["fuse"] is False
        and info["sensor"] == 0
        and info["mask"] == mask0
    )


def vbat_islands(board) -> int:
    n = 0
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetIsRuleArea() or z.GetNetname() != "VBAT" or not z.IsFilled():
            continue
        try:
            polys = z.GetFilledPolysList(z.GetFirstLayer())
        except TypeError:
            polys = z.GetFilledPolysList()
        n += polys.OutlineCount()
    return n


def refill(board):
    L.ZONE_FILLER(board).Fill(board.Zones())


def find_seg(board, net, layer, x1, y1, x2, y2, tol=0.08):
    want_f = layer == "F"
    for t in board.GetTracks():
        if L.is_via(t) or t.GetNetname() != net:
            continue
        if (t.GetLayer() == pcbnew.F_Cu) != want_f:
            continue
        a, b = t.GetStart(), t.GetEnd()
        seg = (L.ToMM(a.x), L.ToMM(a.y), L.ToMM(b.x), L.ToMM(b.y))
        if OC.near_seg(seg, x1, y1, x2, y2, tol):
            return t
    return None


def add_seg(board, router, x1, y1, x2, y2, net, layer, width):
    if not router.seg_ok(x1, y1, x2, y2, layer, net, width):
        return None
    tr = L.add_track(board, x1, y1, x2, y2, width, net, layer)
    if tr is None:
        return None
    router.w.commit_seg(x1, y1, x2, y2, layer, net, width)
    return tr


def add_poly(board, router, pts, net, layer, width):
    items = []
    for a, b in zip(pts, pts[1:]):
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 0.02:
            continue
        tr = add_seg(board, router, a[0], a[1], b[0], b[1], net, layer, width)
        if tr is None:
            for it in items:
                board.Delete(it)
            return None
        items.append(tr)
    return items


def add_via_item(board, router, x, y, net):
    if not router.via_ok(x, y, net):
        return None
    if not OC.put_via(board, x, y, net):
        return None
    router.w.commit_via(x, y, net)
    for t in board.GetTracks():
        if not L.is_via(t) or t.GetNetname() != net:
            continue
        p = t.GetPosition()
        if abs(L.ToMM(p.x) - x) < 0.02 and abs(L.ToMM(p.y) - y) < 0.02:
            return t
    return None


def add_b_keepout(board, corners):
    z = pcbnew.ZONE(board)
    z.SetIsRuleArea(True)
    ls = pcbnew.LSET()
    ls.AddLayer(pcbnew.B_Cu)
    z.SetLayerSet(ls)
    z.SetDoNotAllowCopperPour(True)
    z.SetDoNotAllowTracks(False)
    z.SetDoNotAllowVias(False)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    for x, y in corners:
        z.AppendCorner(L.mm(x, y), -1)
    board.Add(z)
    return z


def overlaps_net(router, x, y, layer, net, rad):
    ix, iy = int(math.floor(x / OC.CELL)), int(math.floor(y / OC.CELL))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for it in router.w.buck[layer].get((ix + dx, iy + dy), ()):
                if OC._name(it) != net:
                    continue
                if OC.gap(it, x, y) < rad:
                    return True
    return False


def bbox_of_pts(pts, pad=0.6):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [
        (min(xs) - pad, min(ys) - pad),
        (max(xs) + pad, min(ys) - pad),
        (max(xs) + pad, max(ys) + pad),
        (min(xs) - pad, max(ys) + pad),
    ]


def pour_has(board, x, y, net, layer):
    pt = pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))
    lay = pcbnew.B_Cu if layer == "B" else pcbnew.F_Cu
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetIsRuleArea() or z.GetNetname() != net or not z.IsFilled():
            continue
        if z.GetFirstLayer() != lay:
            continue
        try:
            polys = z.GetFilledPolysList(lay)
        except TypeError:
            polys = z.GetFilledPolysList()
        try:
            if polys.Contains(pt):
                return True
        except TypeError:
            return False
    return False


def gnd_stitch_near(board, router, x, y, added, rad=3.0):
    """Place a GND via that sits in both F and B pour if possible, else B pour + F tie."""
    cands = []
    for dx in (0.0, -0.8, 0.8, -1.6, 1.6, -2.4, 2.4):
        for dy in (0.0, -0.8, 0.8, -1.6, 1.6, -2.4, 2.4):
            vx, vy = round(x + dx, 2), round(y + dy, 2)
            if math.hypot(dx, dy) > rad:
                continue
            cands.append((vx, vy))
    for vx, vy in cands:
        in_b = pour_has(board, vx, vy, "GND", "B")
        in_f = pour_has(board, vx, vy, "GND", "F")
        if not in_b:
            continue
        v = add_via_item(board, router, vx, vy, "GND")
        if v is None:
            continue
        if in_f:
            added.append(v)
            print(f"  GND stitch F+B ({vx},{vy})", flush=True)
            return True
        # B-only: need F copper somehow; skip if no F pour
        board.Delete(v)
    print(f"  no GND stitch near ({x},{y})", flush=True)
    return False


def delete_adio_tail(board, net, ymin):
    """Remove B.Cu ADIO segments whose both ends are at/above ymin (south stub)."""
    doomed = []
    for t in board.GetTracks():
        if L.is_via(t) or t.GetNetname() != net or t.GetLayer() != pcbnew.B_Cu:
            continue
        a, b = t.GetStart(), t.GetEnd()
        y1, y2 = L.ToMM(a.y), L.ToMM(b.y)
        if min(y1, y2) >= ymin - 0.05:
            doomed.append(t)
    for t in doomed:
        board.Delete(t)
    return len(doomed)


def main():
    board = pcbnew.LoadBoard(str(L.PCB))
    mask0 = mask_count(board)
    before = unconnected(board)
    islands0 = None
    print(f"start unconnected={before} mask={mask0}", flush=True)

    refill(board)
    info = checks(board)
    islands0 = vbat_islands(board)
    print(f"baseline {info} vbat_islands={islands0}", flush=True)
    if not locked_ok(info, mask0):
        raise SystemExit("baseline locked checks failed")

    router = OC.Router(OC.World(board))
    kept = []

    def trial(name, build, keepout_pts=None, stitch_xy=None):
        """build(added, restore) may append restore callbacks for deleted copper."""
        nonlocal router, info, islands0
        added = []
        restore = []
        build(added, restore)
        if not added:
            for fn in restore:
                fn()
            print(f"skip {name}: nothing legal", flush=True)
            router = OC.Router(OC.World(board))
            return False
        if keepout_pts is not None:
            keepout = add_b_keepout(board, keepout_pts)
            added.append(keepout)
        if stitch_xy is not None:
            gnd_stitch_near(board, router, stitch_xy[0], stitch_xy[1], added)
        refill(board)
        now = checks(board)
        islands_now = vbat_islands(board)
        ok = (
            locked_ok(now, mask0)
            and now["unconnected"] < info["unconnected"]
            and islands_now <= islands0
        )
        if ok:
            info = now
            islands0 = islands_now
            kept.append(name)
            print(
                f"KEEP {name} -> un={now['unconnected']} islands={islands_now}",
                flush=True,
            )
            router = OC.Router(OC.World(board))
            return True
        for it in added:
            board.Delete(it)
        for fn in restore:
            fn()
        refill(board)
        router = OC.Router(OC.World(board))
        print(
            f"drop {name} un={now['unconnected']} islands={islands_now} "
            f"keep={now['keep']} fuse={now['fuse']} sensor={now['sensor']}",
            flush=True,
        )
        return False

    def snapshot_delete(board, track, restore):
        """Delete a track and push a restore callback with its geometry."""
        net = track.GetNetname()
        layer = "F" if track.GetLayer() == pcbnew.F_Cu else "B"
        a, b = track.GetStart(), track.GetEnd()
        x1, y1 = L.ToMM(a.x), L.ToMM(a.y)
        x2, y2 = L.ToMM(b.x), L.ToMM(b.y)
        w = L.ToMM(track.GetWidth())
        board.Delete(track)

        def restore_fn(net=net, layer=layer, x1=x1, y1=y1, x2=x2, y2=y2, w=w):
            L.add_track(board, x1, y1, x2, y2, w, net, layer)

        restore.append(restore_fn)
        return (net, layer, x1, y1, x2, y2, w)

    # --- ADIO8: BFS path around J3 east skirt ---
    def build_adio8(added, restore):
        pts, exp = OC.bfs(
            router,
            "ADIO8",
            (72.0, 82.0),
            "B",
            lambda x, y: abs(x - 95.8) < 0.15 and abs(y - 62.0) < 0.15,
            (16, 108, 50, 97),
            limit=400000,
        )
        print(f"  ADIO8 bfs exp={exp} n={len(pts) if pts else None}", flush=True)
        if not pts:
            return
        short = OC.shortcut(router, "ADIO8", "B", pts)
        print(f"  ADIO8 short {short}", flush=True)
        poly = add_poly(board, router, short, "ADIO8", "B", 0.15)
        if poly is None:
            print("  ADIO8 poly refused", flush=True)
            return
        added.extend(poly)
        vx, vy = 95.8, 62.0
        if not overlaps_net(router, vx, vy, "F", "ADIO8", 0.30):
            vx, vy = 95.75, 62.05
        if not overlaps_net(router, vx, vy, "F", "ADIO8", 0.30):
            print("  ADIO8 via not on F", flush=True)
            return
        v = add_via_item(board, router, vx, vy, "ADIO8")
        if v is None:
            print("  ADIO8 via refused", flush=True)
            return
        added.append(v)
        if math.hypot(vx - 95.75, vy - 62.05) > 0.05:
            tie = add_poly(board, router, [(vx, vy), (95.75, 62.05)], "ADIO8", "F", 0.15)
            if tie:
                added.extend(tie)

    trial(
        "ADIO8",
        build_adio8,
        keepout_pts=[(94.5, 61.0), (108.5, 61.0), (108.5, 81.0), (94.5, 81.0)],
        stitch_xy=(100.0, 78.0),
    )

    # --- ADIO5: BFS pin to existing via site on driver ---
    def build_adio5(added, restore):
        goal = (64.2, 60.8)
        pts, exp = OC.bfs(
            router,
            "ADIO5",
            (42.3, 46.5),
            "B",
            lambda x, y: abs(x - goal[0]) < 0.2 and abs(y - goal[1]) < 0.2,
            (16, 108, 36, 92),
            limit=350000,
        )
        print(f"  ADIO5 bfs exp={exp} n={len(pts) if pts else None}", flush=True)
        if not pts:
            return
        short = OC.shortcut(router, "ADIO5", "B", pts)
        print(f"  ADIO5 short ({len(short)}) {short}", flush=True)
        poly = add_poly(board, router, short, "ADIO5", "B", 0.15)
        if poly is None:
            print("  ADIO5 poly refused", flush=True)
            return
        added.extend(poly)
        if not overlaps_net(router, goal[0], goal[1], "B", "ADIO5", 0.20):
            if router.via_ok(goal[0], goal[1], "ADIO5"):
                v = add_via_item(board, router, goal[0], goal[1], "ADIO5")
                if v:
                    added.append(v)

    trial(
        "ADIO5",
        build_adio5,
        keepout_pts=[(63.0, 60.0), (66.0, 60.0), (66.0, 78.0), (63.0, 78.0)],
        stitch_xy=(65.0, 76.0),
    )

    # --- ADIO2: bus then try neck with wall jogs ---
    def build_adio2(added, restore):
        bus = [(24.9, 73.0), (26.0, 73.0), (26.0, 80.6), (70.8, 80.6)]
        poly = add_poly(board, router, bus, "ADIO2", "B", 0.15)
        if poly is None:
            print("  ADIO2 bus refused", flush=True)
            return
        added.extend(poly)
        local = OC.Router(OC.World(board))
        for goal in ((71.8, 52.0), (72.0, 52.0), (72.3, 52.0), (72.3, 51.5)):
            pts, exp = OC.bfs(
                local,
                "ADIO2",
                (70.8, 80.6),
                "B",
                lambda x, y, g=goal: abs(x - g[0]) < 0.15 and abs(y - g[1]) < 0.15,
                (55, 95, 48, 85),
                limit=250000,
            )
            print(f"  ADIO2 bfs->{goal} exp={exp} n={len(pts) if pts else None}", flush=True)
            if pts:
                short = OC.shortcut(local, "ADIO2", "B", pts)
                spine = add_poly(board, local, short, "ADIO2", "B", 0.15)
                if spine is None:
                    continue
                added.extend(spine)
                if not overlaps_net(local, goal[0], goal[1], "F", "ADIO2", 0.28):
                    print("  ADIO2 via not on F", flush=True)
                    continue
                v = add_via_item(board, local, goal[0], goal[1], "ADIO2")
                if v is None:
                    print("  ADIO2 via refused", flush=True)
                    continue
                added.append(v)
                return
        print("  ADIO2 trying wall jogs", flush=True)
        s5 = find_seg(board, "SENSOR_5V", "B", 69.17, 56.2, 73.6, 56.3, tol=0.15)
        if s5 is not None:
            snapshot_delete(board, s5, restore)
            jog = [
                (69.17, 56.2),
                (70.4, 56.2),
                (70.4, 56.75),
                (72.2, 56.75),
                (72.2, 56.3),
                (73.6, 56.3),
            ]
            fresh = OC.Router(OC.World(board))
            jp = add_poly(board, fresh, jog, "SENSOR_5V", "B", 0.15)
            if jp is None:
                print("  SENSOR_5V jog refused", flush=True)
            else:
                added.extend(jp)
                print("  SENSOR_5V jogged", flush=True)
        io6 = find_seg(board, "OUT_IO6", "B", 74.0, 58.8, 65.6, 58.8, tol=0.15)
        if io6 is not None:
            snapshot_delete(board, io6, restore)
            jog = [
                (74.0, 58.8),
                (72.5, 58.8),
                (72.5, 59.4),
                (70.0, 59.4),
                (70.0, 58.8),
                (65.6, 58.8),
            ]
            fresh = OC.Router(OC.World(board))
            jp = add_poly(board, fresh, jog, "OUT_IO6", "B", 0.20)
            if jp is None:
                print("  OUT_IO6 jog refused", flush=True)
            else:
                added.extend(jp)
                print("  OUT_IO6 jogged", flush=True)
        fresh = OC.Router(OC.World(board))
        spine_pts = [(70.8, 80.6), (70.8, 56.5), (71.8, 56.5), (71.8, 52.0)]
        spine = add_poly(board, fresh, spine_pts, "ADIO2", "B", 0.15)
        if spine is None:
            print("  ADIO2 jogged spine refused", flush=True)
            return
        added.extend(spine)
        if not overlaps_net(fresh, 71.8, 52.0, "F", "ADIO2", 0.28):
            print("  ADIO2 via not on F after jog", flush=True)
            return
        v = add_via_item(board, fresh, 71.8, 52.0, "ADIO2")
        if v is None:
            print("  ADIO2 via refused after jog", flush=True)
            return
        added.append(v)

    trial(
        "ADIO2",
        build_adio2,
        keepout_pts=[(69.5, 52.0), (72.5, 52.0), (72.5, 81.0), (69.5, 81.0)],
        stitch_xy=(68.0, 78.0),
    )

    # --- ADIO4: trim south stub, reroute via free passage ---
    def build_adio4(added, restore):
        doomed = []
        for t in board.GetTracks():
            if L.is_via(t) or t.GetNetname() != "ADIO4" or t.GetLayer() != pcbnew.B_Cu:
                continue
            a, b = t.GetStart(), t.GetEnd()
            y1, y2 = L.ToMM(a.y), L.ToMM(b.y)
            if min(y1, y2) >= 65.95:
                doomed.append(t)
        print(f"  ADIO4 deleting {len(doomed)} south segs", flush=True)
        for t in doomed:
            snapshot_delete(board, t, restore)
        fresh = OC.Router(OC.World(board))
        starts = []
        for it in fresh.w.items["B"]:
            if it[0] == "s" and it[6] == "ADIO4":
                for x, y in ((it[1], it[2]), (it[3], it[4])):
                    if 20 <= x <= 35 and 55 <= y <= 66:
                        starts.append((round(x, 1), round(y, 1)))
        starts = list(dict.fromkeys(starts))
        print(f"  ADIO4 starts {starts[:8]}", flush=True)
        if not starts:
            starts = [(30.4, 61.0), (23.7, 61.0)]
        best = None
        goal = (95.75, 62.05)
        for start in starts[:6]:
            pts, exp = OC.bfs(
                fresh,
                "ADIO4",
                start,
                "B",
                lambda x, y, g=goal: abs(x - g[0]) < 0.25 and abs(y - g[1]) < 0.25,
                (16, 108, 48, 92),
                limit=400000,
            )
            print(f"  ADIO4 bfs {start} exp={exp} n={len(pts) if pts else None}", flush=True)
            if pts:
                best = pts
                break
        if best is None:
            for g in ((95.8, 57.2), (95.6, 58.4), (95.8, 60.8)):
                for start in starts[:4]:
                    pts, exp = OC.bfs(
                        fresh,
                        "ADIO4",
                        start,
                        "B",
                        lambda x, y, g=g: abs(x - g[0]) < 0.25 and abs(y - g[1]) < 0.25,
                        (16, 108, 48, 92),
                        limit=350000,
                    )
                    print(
                        f"  ADIO4 bfs {start}->{g} exp={exp} n={len(pts) if pts else None}",
                        flush=True,
                    )
                    if pts:
                        best = pts
                        goal = g
                        break
                if best:
                    break
        if best is None:
            print("  ADIO4 no path", flush=True)
            return
        short = OC.shortcut(fresh, "ADIO4", "B", best)
        print(f"  ADIO4 short ({len(short)}) {short[:6]}...{short[-3:]}", flush=True)
        poly = add_poly(board, fresh, short, "ADIO4", "B", 0.15)
        if poly is None:
            print("  ADIO4 poly refused", flush=True)
            return
        added.extend(poly)
        gx, gy = short[-1]
        if not overlaps_net(fresh, gx, gy, "F", "ADIO4", 0.30):
            print("  ADIO4 end not on F", flush=True)
            return
        if fresh.via_ok(gx, gy, "ADIO4"):
            v = add_via_item(board, fresh, gx, gy, "ADIO4")
            if v:
                added.append(v)

    trial(
        "ADIO4",
        build_adio4,
        keepout_pts=[(94.0, 56.0), (108.0, 56.0), (108.0, 82.0), (94.0, 82.0)],
        stitch_xy=(100.0, 75.0),
    )

    # --- ADIO1 / ADIO3 / ADIO7: BFS attempts ---
    for net, pin, goals, ko, stitch in (
        (
            "ADIO1",
            (42.3, 52.5),
            [(64.2, 49.2), (64.0, 47.6), (64.25, 50.45), (64.25, 46.55)],
            [(62.5, 46.0), (66.0, 46.0), (66.0, 78.0), (62.5, 78.0)],
            (64.0, 76.0),
        ),
        (
            "ADIO3",
            (42.3, 49.5),
            [(87.2, 49.2), (87.2, 47.8), (87.15, 50.45), (87.15, 46.55)],
            [(85.5, 46.0), (89.0, 46.0), (89.0, 78.0), (85.5, 78.0)],
            (86.0, 76.0),
        ),
        (
            "ADIO7",
            (42.3, 43.5),
            [(87.2, 60.8), (87.2, 58.2), (90.4, 56.4), (87.15, 62.05)],
            [(85.5, 56.0), (91.0, 56.0), (91.0, 82.0), (85.5, 82.0)],
            (88.0, 78.0),
        ),
    ):

        def build_odd(added, restore, net=net, pin=pin, goals=goals):
            fresh = OC.Router(OC.World(board))
            best = None
            for g in goals:
                pts, exp = OC.bfs(
                    fresh,
                    net,
                    pin,
                    "B",
                    lambda x, y, g=g: abs(x - g[0]) < 0.25 and abs(y - g[1]) < 0.25,
                    (16, 108, 36, 92),
                    limit=400000,
                )
                print(f"  {net} bfs->{g} exp={exp} n={len(pts) if pts else None}", flush=True)
                if pts:
                    best = pts
                    break
            if best is None:
                return
            short = OC.shortcut(fresh, net, "B", best)
            print(f"  {net} short ({len(short)})", flush=True)
            poly = add_poly(board, fresh, short, net, "B", 0.15)
            if poly is None:
                print(f"  {net} poly refused", flush=True)
                return
            added.extend(poly)
            gx, gy = short[-1]
            if overlaps_net(fresh, gx, gy, "F", net, 0.30) and fresh.via_ok(gx, gy, net):
                existing = False
                for t in board.GetTracks():
                    if not L.is_via(t) or t.GetNetname() != net:
                        continue
                    p = t.GetPosition()
                    if abs(L.ToMM(p.x) - gx) < 0.15 and abs(L.ToMM(p.y) - gy) < 0.15:
                        existing = True
                        break
                if not existing:
                    v = add_via_item(board, fresh, gx, gy, net)
                    if v:
                        added.append(v)

        trial(net, build_odd, keepout_pts=ko, stitch_xy=stitch)

    refill(board)
    final = checks(board)
    print(f"FINAL {final} vbat_islands={vbat_islands(board)} kept={kept}", flush=True)
    if not locked_ok(final, mask0):
        raise SystemExit("final locked checks failed")

    n_tracks = sum(1 for t in board.GetTracks() if not L.is_via(t))
    n_vias = sum(1 for t in board.GetTracks() if L.is_via(t))
    print(f"tracks={n_tracks} vias={n_vias}", flush=True)

    # Per-net leftover summary
    board.BuildConnectivity()
    from collections import Counter

    # Use DRC report later; for now save.
    tmp = Path("/tmp/pdmrazora_adio_rest.kicad_pcb")
    board.Save(str(tmp))
    text = tmp.read_text()
    if "(version 20240108)" not in text[:240]:
        L.downgrade_to_k8(tmp)
        text = tmp.read_text()
    if "(version 20240108)" not in text[:240] or '(generator_version "8.0")' not in text[:240]:
        raise SystemExit(f"refusing to save non-KiCad-8 header: {text[:180]!r}")
    L.PCB.write_text(text)
    print(text[:180], flush=True)


if __name__ == "__main__":
    main()
