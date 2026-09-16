#!/usr/bin/env python3
"""Surgical DRC fix: delete conflicted tracks/vias from shorts/crossings,
add SENSOR_5V PU taps + GND stitches, refill, keep K8. No dense remesh."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pcbnew
from pcbnew import (
    VECTOR2I, FromMM, ToMM, PCB_TRACK, PCB_VIA, F_Cu, B_Cu, ZONE_FILLER,
)

ROOT = Path(__file__).resolve().parents[1]
PCB_PATH = ROOT / "pdmrazora.kicad_pcb"
STATUS = ROOT / "scripts" / "copper_status.txt"
DRC_JSON = Path("/tmp/drc/surgical.json")


def mm(x, y=None):
    if y is None:
        return FromMM(x)
    return VECTOR2I(FromMM(x), FromMM(y))


def ensure_net(board, name):
    ni = board.FindNet(name)
    if ni is not None and ni.GetNetCode() > 0:
        return ni
    ni = pcbnew.NETINFO_ITEM(board, name)
    board.Add(ni)
    return ni


def pad_xy(pad):
    p = pad.GetPosition()
    return ToMM(p.x), ToMM(p.y)


def fp_map(board):
    return {fp.GetReference(): fp for fp in board.GetFootprints()}


def get_pad(fps, ref, num):
    pad = fps[ref].FindPadByNumber(str(num))
    if pad is None:
        raise KeyError(f"{ref}.{num}")
    return pad


def add_track(board, x1, y1, x2, y2, width_mm, netname, layer=F_Cu):
    if abs(x1 - x2) < 1e-4 and abs(y1 - y2) < 1e-4:
        return None
    tr = PCB_TRACK(board)
    tr.SetStart(mm(x1, y1))
    tr.SetEnd(mm(x2, y2))
    tr.SetWidth(FromMM(width_mm))
    tr.SetLayer(layer)
    tr.SetNet(ensure_net(board, netname))
    board.Add(tr)
    return tr


def add_via(board, x, y, netname, drill=0.3, size=0.6):
    v = PCB_VIA(board)
    v.SetPosition(mm(x, y))
    v.SetDrill(FromMM(drill))
    try:
        v.SetWidth(F_Cu, FromMM(size))
        v.SetWidth(B_Cu, FromMM(size))
    except Exception:
        try:
            v.SetFrontWidth(FromMM(size))
        except Exception:
            pass
    v.SetNet(ensure_net(board, netname))
    board.Add(v)
    return v


def downgrade_to_k8(path: Path):
    text = path.read_text()
    text = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text = re.sub(r'\(generator_version "[^"]+"\)', '(generator_version "8.0")', text, count=1)
    text = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text)
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
    path.write_text(text)
    head = path.read_text()[:250]
    assert "20240108" in head and 'generator_version "8.0"' in head


def run_drc():
    DRC_JSON.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call([
        "kicad-cli", "pcb", "drc", "--format", "json", "--severity-error",
        "--output", str(DRC_JSON), str(PCB_PATH),
    ], stdout=subprocess.DEVNULL)
    return json.loads(DRC_JSON.read_text())


def track_map(board):
    return {t.m_Uuid.AsString(): t for t in board.GetTracks()}


def is_via(obj):
    return type(obj).__name__ == "PCB_VIA"


def track_score(obj):
    """Higher = more preferable to delete (long runs / vias in dense areas)."""
    if is_via(obj):
        return 50.0
    try:
        return ToMM(obj.GetLength()) + (10.0 if obj.GetLayer() == B_Cu else 0.0)
    except Exception:
        return 20.0


def delete_conflict_copper(board, drc, max_delete=180):
    """Delete one track/via per short/crossing, preferring high-conflict offenders."""
    idmap = track_map(board)
    # frequency across shorts+crossings
    freq = Counter()
    events = []
    for v in drc["violations"]:
        if v["type"] not in ("shorting_items", "tracks_crossing"):
            continue
        ids = []
        for it in v["items"]:
            uid = it["uuid"]
            if uid in idmap:
                ids.append(uid)
                freq[uid] += 1
        if ids:
            events.append((v["type"], ids))

    to_delete = set()
    for typ, ids in events:
        # pick the track/via with highest (freq, score)
        best = max(ids, key=lambda u: (freq[u], track_score(idmap[u])))
        to_delete.add(best)
        if len(to_delete) >= max_delete:
            break

    deleted = 0
    for uid in list(to_delete):
        obj = idmap.get(uid)
        if obj is None:
            continue
        board.Delete(obj)
        deleted += 1
    return deleted, len(events)


def add_sensor5v_taps(board, fps):
    """Connect R201–R208 pad1 to SENSOR_5V via top-edge B bus (avoid mid-board spine)."""
    n = 0
    bus_y = 5.0
    # ensure a top bus exists from x=52..145; tee from existing spine if present
    # Find existing SENSOR_5V via near module or create left riser
    e38 = pad_xy(get_pad(fps, "M1000", "E38"))
    # short path: E38 north on F to y=10, via, B to bus, bus east
    add_track(board, e38[0], e38[1], e38[0], 10.0, 0.35, "SENSOR_5V"); n += 1
    add_via(board, e38[0], 10.0, "SENSOR_5V"); n += 1
    add_track(board, e38[0], 10.0, e38[0], bus_y, 0.35, "SENSOR_5V", B_Cu); n += 1
    add_track(board, e38[0], bus_y, 145.0, bus_y, 0.4, "SENSOR_5V", B_Cu); n += 1

    for r in range(201, 209):
        rx, ry = pad_xy(get_pad(fps, f"R{r}", "1"))
        # via west of PU pad, clear of ADIO OUT (~ox east of R)
        side = rx - 2.5
        add_track(board, rx, ry, side, ry, 0.3, "SENSOR_5V"); n += 1
        add_via(board, side, ry, "SENSOR_5V"); n += 1
        add_track(board, side, ry, side, bus_y, 0.3, "SENSOR_5V", B_Cu); n += 1
    return n


def add_gnd_stitches(board, fps):
    """GND vias west of discrete GND pads + a few island stitches."""
    n = 0
    targets = []
    for ref in [f"R{r}" for r in (10, 20, 30, 40, 101, 102, 103, 104, 105, 106, 107, 108, 2)]:
        if ref not in fps:
            continue
        for pad in list(fps[ref].Pads()):
            if pad.GetNetname() == "GND":
                targets.append(pad_xy(pad))
    for ref in [f"C{c}" for c in (10, 20, 30, 40, 101, 102, 103, 104, 105, 106, 107, 108, 1, 2)]:
        if ref not in fps:
            continue
        for pad in list(fps[ref].Pads()):
            if pad.GetNetname() == "GND":
                targets.append(pad_xy(pad))
    seen = set()
    for x, y in targets:
        key = (round(x, 1), round(y, 1))
        if key in seen:
            continue
        seen.add(key)
        vx = x - 1.4
        add_track(board, x, y, vx, y, 0.3, "GND"); n += 1
        add_via(board, vx, y, "GND"); n += 1
    for x, y in [(20, 100), (40, 100), (55, 95), (95, 75), (120, 95), (100, 55), (30, 90)]:
        add_via(board, x, y, "GND"); n += 1
    return n


def count_tracks(board):
    tr = [t for t in board.GetTracks() if type(t).__name__ != "PCB_VIA"]
    vias = [t for t in board.GetTracks() if type(t).__name__ == "PCB_VIA"]
    return len(tr), len(vias)


def main():
    print("=== surgical DRC fix ===")
    # baseline DRC on current file
    print("Running baseline DRC...")
    drc0 = run_drc()
    shorts0 = sum(1 for v in drc0["violations"] if v["type"] == "shorting_items")
    cross0 = sum(1 for v in drc0["violations"] if v["type"] == "tracks_crossing")
    unc0 = len(drc0["unconnected_items"])
    print(f"BEFORE shorts={shorts0} crossings={cross0} unc={unc0}")

    board = pcbnew.LoadBoard(str(PCB_PATH))
    fps = fp_map(board)
    bt, bv = count_tracks(board)

    deleted, events = delete_conflict_copper(board, drc0)
    print(f"Deleted {deleted} conflict tracks/vias from {events} short/cross events")

    print("Adding SENSOR_5V PU taps...")
    n_s = add_sensor5v_taps(board, fps)
    print(f"  +{n_s} copper")
    print("Adding GND stitches...")
    n_g = add_gnd_stitches(board, fps)
    print(f"  +{n_g} copper")

    print("Filling zones...")
    ZONE_FILLER(board).Fill(board.Zones())

    board.BuildConnectivity()
    unc_mid = board.GetConnectivity().GetUnconnectedCount(True)
    at, av = count_tracks(board)
    print(f"MID tracks={at} vias={av} unc(connectivity)={unc_mid}")

    pcbnew.SaveBoard(str(PCB_PATH), board)
    downgrade_to_k8(PCB_PATH)

    print("Re-running DRC...")
    drc1 = run_drc()
    shorts1 = sum(1 for v in drc1["violations"] if v["type"] == "shorting_items")
    cross1 = sum(1 for v in drc1["violations"] if v["type"] == "tracks_crossing")
    unc1 = len(drc1["unconnected_items"])
    print(f"AFTER shorts={shorts1} crossings={cross1} unc={unc1}")

    # Second pass: delete remaining shorts only (not all crossings)
    if shorts1 > 0:
        board = pcbnew.LoadBoard(str(PCB_PATH))
        # rebuild freq from new drc — delete only shorting items' tracks
        idmap = track_map(board)
        freq = Counter()
        victims = []
        for v in drc1["violations"]:
            if v["type"] != "shorting_items":
                continue
            ids = [it["uuid"] for it in v["items"] if it["uuid"] in idmap]
            for u in ids:
                freq[u] += 1
            if ids:
                victims.append(ids)
        to_del = set()
        for ids in victims:
            best = max(ids, key=lambda u: (freq[u], track_score(idmap[u])))
            to_del.add(best)
        for uid in to_del:
            board.Delete(idmap[uid])
        print(f"Second pass deleted {len(to_del)} shorting tracks/vias")
        ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(str(PCB_PATH), board)
        downgrade_to_k8(PCB_PATH)
        drc2 = run_drc()
        shorts1 = sum(1 for v in drc2["violations"] if v["type"] == "shorting_items")
        cross1 = sum(1 for v in drc2["violations"] if v["type"] == "tracks_crossing")
        unc1 = len(drc2["unconnected_items"])
        board.BuildConnectivity()
        at, av = count_tracks(board)
        print(f"AFTER2 shorts={shorts1} crossings={cross1} unc={unc1} tracks={at} vias={av}")

    with STATUS.open("w") as f:
        f.write(f"before_tracks={bt}\n")
        f.write(f"before_vias={bv}\n")
        f.write(f"before_shorts={shorts0}\n")
        f.write(f"before_crossings={cross0}\n")
        f.write(f"before_unc={unc0}\n")
        f.write(f"after_tracks={at}\n")
        f.write(f"after_vias={av}\n")
        f.write(f"after_shorts={shorts1}\n")
        f.write(f"after_crossings={cross1}\n")
        f.write(f"after_unc={unc1}\n")
        f.write("strategy=surgical_delete_conflicts_sensor5v_gnd_k8\n")
    print("Wrote", STATUS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
