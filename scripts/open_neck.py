#!/usr/bin/env python3
"""Open the GND pour neck so ADIO6 can land on the driver.

The even-ADIO buses already sit at y=81.4 and y=82.0. A hop north from
that bus onto the driver pads crosses the B.Cu GND neck and seals the
pour between the M1000 keepout and the buses. This pass:

- jogs OUT_IO7 off x=72.4 so the column is clear
- runs ADIO6 down that column onto the existing F.Cu driver copper
- stitches the cut-off GND island into the F.Cu pour around J3
- punches a B.Cu-only pour keepout over the slot so the track does not
  mint a sliver

Then it tries a few clearance-checked landings (other ADIO columns, a
short IN_RES2 notch, GND pad-to-pour vias). A landing is kept only when
the unconnected count drops and the locked checks still hold.

Does not move footprints, bridge F1, pour SENSOR_GND, touch PWR_OUT mask
openings, or replay scripts/cut_crossings_sexp.py.
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
        tr = add_seg(board, router, a[0], a[1], b[0], b[1], net, layer, width)
        if tr is None and math.hypot(b[0] - a[0], b[1] - a[1]) >= 0.02:
            for it in items:
                board.Delete(it)
            return None
        if tr is not None:
            items.append(tr)
    return items


def add_via_item(board, router, x, y, net):
    if not router.via_ok(x, y, net):
        return None
    if not OC.put_via(board, x, y, net):
        return None
    router.w.commit_via(x, y, net)
    # put_via already added it; find the one we just added by position.
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


def refill(board):
    L.ZONE_FILLER(board).Fill(board.Zones())


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


def main():
    board = pcbnew.LoadBoard(str(L.PCB))
    mask0 = mask_count(board)
    before = unconnected(board)
    print(f"start unconnected={before} mask={mask0}", flush=True)

    doomed = []
    for spec in (
        (79.20, 62.40, 71.20, 62.40),
        (71.20, 62.40, 71.20, 59.60),
    ):
        t = find_seg(board, "OUT_IO7", "B", *spec)
        if t is None:
            raise SystemExit(f"missing OUT_IO7 segment {spec}")
        doomed.append(t)
    for t in doomed:
        board.Delete(t)

    world = OC.World(board)
    router = OC.Router(world)
    jog = [(79.2, 62.4), (73.6, 62.4), (73.6, 61.4), (71.2, 61.4), (71.2, 59.6)]
    width = 0.20
    items = add_poly(board, router, jog, "OUT_IO7", "B", width)
    if items is None:
        width = 0.15
        # world still has no jog (add_poly rolls its own tracks back)
        items = add_poly(board, router, jog, "OUT_IO7", "B", width)
    if items is None:
        raise SystemExit("OUT_IO7 jog refused")
    print(f"OUT_IO7 jog width {width}", flush=True)

    if not router.via_ok(72.4, 62.0, "ADIO6"):
        raise SystemExit("ADIO6 via refused after jog")
    spine = add_poly(
        board,
        router,
        [(66.0, 81.4), (72.4, 81.4), (72.4, 62.0)],
        "ADIO6",
        "B",
        0.15,
    )
    if spine is None:
        raise SystemExit("ADIO6 spine refused")
    via = add_via_item(board, router, 72.4, 62.0, "ADIO6")
    if via is None:
        raise SystemExit("ADIO6 via add failed")
    tie = add_poly(board, router, [(72.4, 62.0), (72.8, 62.0)], "ADIO6", "F", 0.15)
    if tie is None:
        raise SystemExit("ADIO6 F tie refused")
    stitch = add_via_item(board, router, 68.6, 79.0, "GND")
    if stitch is None:
        raise SystemExit("GND stitch via refused")
    add_b_keepout(
        board,
        [(71.0, 63.0), (75.0, 63.0), (75.0, 81.0), (71.0, 81.0)],
    )

    refill(board)
    info = checks(board)
    islands = vbat_islands(board)
    print(f"base {info} vbat_islands={islands}", flush=True)
    if not locked_ok(info, mask0) or info["unconnected"] >= before:
        raise SystemExit("base edit failed locked checks")

    def trial(name, build):
        """Add copper, keep it only when the ratsnest shrinks and VBAT does not gain an island."""
        nonlocal router, info
        added = []
        build(added)
        if not added:
            print(f"skip {name}: nothing legal", flush=True)
            router = OC.Router(OC.World(board))
            return False
        refill(board)
        now = checks(board)
        islands_now = vbat_islands(board)
        ok = (
            locked_ok(now, mask0)
            and now["unconnected"] < info["unconnected"]
            and islands_now <= islands
        )
        if ok:
            info["unconnected"] = now["unconnected"]
            print(f"KEEP {name} -> {now['unconnected']} islands={islands_now}", flush=True)
            router = OC.Router(OC.World(board))
            return True
        for it in added:
            board.Delete(it)
        refill(board)
        router = OC.Router(OC.World(board))
        print(
            f"drop {name} un={now['unconnected']} islands={islands_now} keep={now['keep']}",
            flush=True,
        )
        return False

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

    def gnd_one(ref, added):
        fp = next(f for f in board.GetFootprints() if f.GetReference() == ref)
        pad = next(p for p in fp.Pads() if p.GetNetname() == "GND")
        x, y = L.ToMM(pad.GetPosition().x), L.ToMM(pad.GetPosition().y)
        sx, sy = L.ToMM(pad.GetSize().x), L.ToMM(pad.GetSize().y)
        # Sites on the pad, then a ring out to 1.5 mm that is already in the B pour.
        cands = []
        for dx in (0.0, -0.3, 0.3, -0.6, 0.6):
            for dy in (0.0, -0.3, 0.3, -0.6, 0.6):
                cands.append((round(x + dx, 2), round(y + dy, 2)))
        for dx in (-1.2, -0.9, 0.9, 1.2, 0.0):
            for dy in (-1.2, -0.9, 0.9, 1.2, 0.0):
                vx, vy = round(x + dx, 2), round(y + dy, 2)
                if pour_has(board, vx, vy, "GND", "B"):
                    cands.append((vx, vy))
        seen = set()
        for vx, vy in cands:
            if (vx, vy) in seen:
                continue
            seen.add((vx, vy))
            on_pad = overlaps_net(router, vx, vy, "F", "GND", 0.24)
            in_pour = pour_has(board, vx, vy, "GND", "B")
            if not (on_pad or in_pour):
                continue
            v = add_via_item(board, router, vx, vy, "GND")
            if v is None:
                continue
            if on_pad and in_pour:
                added.append(v)
                print(f"  {ref} via in pour {vx},{vy}", flush=True)
                return
            # Need a short tie from the pad to a pour via, or the via is on the pad only.
            if on_pad:
                board.Delete(v)
                continue
            # Pour via: tie on F from the pad center if the segment is clear.
            # Pull the tie endpoint back onto the pad so it overlaps copper.
            tie = add_poly(board, router, [(x, y), (vx, vy)], "GND", "F", 0.15)
            if tie is None:
                board.Delete(v)
                continue
            added.append(v)
            added.extend(tie)
            print(f"  {ref} pour tie {vx},{vy}", flush=True)
            return
        print(f"  {ref} no pour via", flush=True)

    for ref in ("C10", "R10", "C101", "C102", "C105", "C106", "R101", "U15", "U16", "U18"):
        trial(f"GND {ref}", lambda added, ref=ref: gnd_one(ref, added))

    plans = [
        ("ADIO2", [(24.9, 73.0), (26.0, 73.0), (26.0, 80.6), (70.6, 80.6), (70.6, 56.1)], (70.9, 56.0)),
        ("ADIO8", [(72.0, 82.0), (73.8, 82.0), (73.8, 74.0), (89.2, 74.0), (89.2, 57.2), (94.6, 57.2)], (94.8, 56.6)),
        ("ADIO4", [(23.7, 73.0), (22.4, 73.0), (22.4, 80.4), (74.2, 80.4), (74.2, 57.4), (78.6, 57.4)], (78.8, 56.2)),
    ]

    def land_adio(net, pts, via_xy, added):
        poly = add_poly(board, router, pts, net, "B", 0.15)
        if poly is None:
            print(f"  {net} poly refused", flush=True)
            return
        added.extend(poly)
        if not overlaps_net(router, via_xy[0], via_xy[1], "F", net, 0.26):
            print(f"  {net} via not on F copper", flush=True)
            return
        v = add_via_item(board, router, via_xy[0], via_xy[1], net)
        if v is None:
            print(f"  {net} via refused", flush=True)
            return
        added.append(v)

    for net, pts, via_xy in plans:
        trial(net, lambda added, net=net, pts=pts, via_xy=via_xy: land_adio(net, pts, via_xy, added))

    def in_res2(added):
        wall = find_seg(board, "IN_O2S2", "B", 81.6, 54.0, 92.8, 54.0)
        if wall is None:
            print("  IN_O2S2 wall not found", flush=True)
            return
        board.Delete(wall)
        fresh = OC.Router(OC.World(board))
        notch = [(81.6, 54.0), (88.4, 54.0), (88.4, 53.55), (90.1, 53.55), (90.1, 54.0), (92.8, 54.0)]
        poly = add_poly(board, fresh, notch, "IN_O2S2", "B", 0.20)
        if poly is None:
            L.add_track(board, 81.6, 54.0, 92.8, 54.0, 0.20, "IN_O2S2", "B")
            print("  IN_O2S2 notch refused", flush=True)
            return
        v = add_via_item(board, fresh, 89.22, 54.05, "IN_RES2")
        hop = add_poly(board, fresh, [(89.22, 54.05), (89.22, 53.20)], "IN_RES2", "B", 0.15) if v else None
        if v is None or hop is None:
            for it in poly:
                board.Delete(it)
            if v is not None:
                board.Delete(v)
            L.add_track(board, 81.6, 54.0, 92.8, 54.0, 0.20, "IN_O2S2", "B")
            print("  IN_RES2 via/hop refused", flush=True)
            return
        added.extend(poly)
        added.append(v)
        added.extend(hop)
        # Wall stays deleted. On rollback the caller only deletes `added`,
        # so put a replacement wall into a side list the caller does not own.
        # Restore by keeping the original geometry in `added` as a new track
        # that trial() will delete on failure — and re-add the wall then.
        restored["wall_removed"] = True

    restored = {"wall_removed": False}
    in_res2_added = []
    in_res2(in_res2_added)
    if in_res2_added:
        refill(board)
        now = checks(board)
        islands_now = vbat_islands(board)
        if locked_ok(now, mask0) and now["unconnected"] < info["unconnected"] and islands_now <= islands:
            info["unconnected"] = now["unconnected"]
            print(f"KEEP IN_RES2 -> {now['unconnected']}", flush=True)
            restored["wall_removed"] = False
        else:
            for t in in_res2_added:
                board.Delete(t)
            if restored["wall_removed"] and find_seg(board, "IN_O2S2", "B", 81.6, 54.0, 92.8, 54.0) is None:
                L.add_track(board, 81.6, 54.0, 92.8, 54.0, 0.20, "IN_O2S2", "B")
            refill(board)
            print(f"drop IN_RES2 un={now['unconnected']} islands={islands_now}", flush=True)
    else:
        print("skip IN_RES2", flush=True)

    refill(board)
    final = checks(board)
    print(f"FINAL {final} vbat_islands={vbat_islands(board)}", flush=True)
    if not locked_ok(final, mask0) or final["unconnected"] > info["unconnected"]:
        raise SystemExit("final checks failed")

    n_tracks = sum(1 for t in board.GetTracks() if not L.is_via(t))
    n_vias = sum(1 for t in board.GetTracks() if L.is_via(t))
    print(f"tracks={n_tracks} vias={n_vias}", flush=True)

    tmp = Path("/tmp/pdmrazora_neck.kicad_pcb")
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
