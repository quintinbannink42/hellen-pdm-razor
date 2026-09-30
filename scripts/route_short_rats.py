#!/usr/bin/env python3
"""Stitch short unconnected pairs that clear existing copper.

Already applied. Re-running reads /tmp/drc/after_en.json and will duplicate
those tracks. Does not bridge F1, does not pour SENSOR_GND, and does not
route VBAT across the fuse body. Foreign pours are obstacles.
"""
from __future__ import annotations

import json
import math
import re
from collections import deque
from pathlib import Path

import pcbnew

from close_remaining_rats import (
    CLR,
    Obs,
    add_track,
    add_via,
    normalize,
)

PCB = Path("/workspace/pdmrazora.kicad_pcb")
DRC = Path("/tmp/drc/after_en.json")


def route(board, obs, net, ax, ay, bx, by, width=0.20, max_len=12.0):
    """4-connected search on F and B. Returns True if copper was added."""
    if math.hypot(bx - ax, by - ay) > max_len:
        return False
    if net == "VBAT":
        # Both ends must sit on the same side of the fuse body.
        def side(y):
            if y < 17.0:
                return "pre"
            if y > 23.2:
                return "post"
            return "gap"

        if side(ay) != side(by) or side(ay) == "gap":
            return False
    step = 0.35
    # Straight shot first.
    for lay in ("F", "B"):
        if obs.seg_ok(net, lay, ax, ay, bx, by, width):
            add_track(board, ax, ay, bx, by, width, net, lay)
            obs.note_track(net, lay, ax, ay, bx, by, width)
            return True

    def key(x, y, lay):
        return (int(round(x / step)), int(round(y / step)), lay)

    start_cells = []
    for lay in ("F", "B"):
        start_cells.append((ax, ay, lay))
    q = deque()
    prev = {}
    for x, y, lay in start_cells:
        st = key(x, y, lay)
        # Allow the start even if the pad copper is "in the way" (same net).
        q.append((x, y, lay))
        prev[(round(x, 3), round(y, 3), lay)] = None
    found = None
    seen = set(prev)
    expansions = 0
    while q and expansions < 6000:
        x, y, lay = q.popleft()
        expansions += 1
        if math.hypot(x - bx, y - by) <= step * 0.75 and obs.seg_ok(net, lay, x, y, bx, by, width):
            found = (x, y, lay)
            break
        for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step)):
            nx, ny = x + dx, y + dy
            if abs(nx - ax) + abs(ny - ay) > max_len + 1:
                continue
            st = (round(nx, 3), round(ny, 3), lay)
            if st in seen:
                continue
            if not obs.seg_ok(net, lay, x, y, nx, ny, width):
                continue
            seen.add(st)
            prev[st] = (round(x, 3), round(y, 3), lay)
            q.append((nx, ny, lay))
        olay = "B" if lay == "F" else "F"
        st = (round(x, 3), round(y, 3), olay)
        if st not in seen and obs.via_ok(net, x, y):
            seen.add(st)
            prev[st] = ("via", round(x, 3), round(y, 3), lay)
            q.append((x, y, olay))
    if found is None:
        return False
    # Walk back.
    cur = (round(found[0], 3), round(found[1], 3), found[2])
    chain = [found]
    guard = 0
    while guard < 4000:
        guard += 1
        parent = prev.get(cur)
        if parent is None:
            break
        if parent[0] == "via":
            chain.append(("via", parent[1], parent[2]))
            cur = (parent[1], parent[2], parent[3])
            chain.append((parent[1], parent[2], parent[3]))
        else:
            chain.append(parent)
            cur = parent
    chain.reverse()
    chain.append((bx, by, found[2]))
    # Emit.
    i = 0
    added = 0
    while i < len(chain):
        item = chain[i]
        if isinstance(item, tuple) and item and item[0] == "via":
            if not obs.via_ok(net, item[1], item[2]):
                return added > 0
            add_via(board, item[1], item[2], net)
            obs.note_via(net, item[1], item[2])
            added += 1
            i += 1
            continue
        lay = item[2]
        j = i + 1
        run_end = i
        while j < len(chain):
            nxt = chain[j]
            if isinstance(nxt, tuple) and nxt and nxt[0] == "via":
                break
            if nxt[2] != lay:
                break
            run_end = j
            j += 1
        x1, y1 = item[0], item[1]
        x2, y2 = chain[run_end][0], chain[run_end][1]
        if math.hypot(x2 - x1, y2 - y1) >= 0.05:
            if obs.seg_ok(net, lay, x1, y1, x2, y2, width):
                add_track(board, x1, y1, x2, y2, width, net, lay)
                obs.note_track(net, lay, x1, y1, x2, y2, width)
                added += 1
            else:
                # Fall back to the grid steps.
                for k in range(i, run_end):
                    p, n = chain[k], chain[k + 1]
                    if isinstance(n, tuple) and n and n[0] == "via":
                        break
                    if obs.seg_ok(net, lay, p[0], p[1], n[0], n[1], width):
                        add_track(board, p[0], p[1], n[0], n[1], width, net, lay)
                        obs.note_track(net, lay, p[0], p[1], n[0], n[1], width)
                        added += 1
        i = j if j > i else i + 1
    return added > 0


def net_of(desc):
    if "[" not in desc:
        return None
    return desc.split("[", 1)[1].split("]", 1)[0]


def main():
    board = pcbnew.LoadBoard(str(PCB))
    obs = Obs(board)
    drc = json.loads(DRC.read_text())
    tried = 0
    kept = []
    for u in drc["unconnected_items"]:
        a, b = u["items"]
        ax, ay = a["pos"]["x"], a["pos"]["y"]
        bx, by = b["pos"]["x"], b["pos"]["y"]
        dist = math.hypot(ax - bx, ay - by)
        if dist < 0.15 or dist > 8.0:
            continue
        da, db = a["description"], b["description"]
        if "M1000" in da and "M1000" in db and "GND" in da:
            continue
        if da.startswith("Zone") or db.startswith("Zone"):
            continue
        net = net_of(da) or net_of(db)
        if not net or net.startswith("PWR_OUT"):
            continue
        tried += 1
        if route(board, obs, net, ax, ay, bx, by):
            kept.append((net, round(dist, 2), da[:40], db[:40]))
    print(f"tried {tried} kept {len(kept)}")
    for row in kept:
        print(" ", row)
    # One IN_AUX4 attempt, a bit longer, from the driver pad to the stub.
    if route(board, obs, "IN_AUX4", 101.65, 40.47, 97.60, 32.00, width=0.20, max_len=18.0):
        print("IN_AUX4 U4 stub routed")
    else:
        print("IN_AUX4 U4 stub blocked")
    print("filling")
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(PCB), board)
    normalize(PCB)
    print("saved")


if __name__ == "__main__":
    main()
