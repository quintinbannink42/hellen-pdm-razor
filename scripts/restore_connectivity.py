#!/usr/bin/env python3
"""After surgical deletes: kill remaining shorts, restore key nets, bridge SENSOR_5V, keep K8."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pcbnew
from pcbnew import (
    VECTOR2I, FromMM, ToMM, PCB_TRACK, PCB_VIA, F_Cu, B_Cu, ZONE_FILLER,
)

ROOT = Path(__file__).resolve().parents[1]
PCB_PATH = ROOT / "pdmrazora.kicad_pcb"
STATUS = ROOT / "scripts" / "copper_status.txt"
DRC_JSON = Path("/tmp/drc/restore.json")


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


def run_drc():
    subprocess.check_call([
        "kicad-cli", "pcb", "drc", "--format", "json", "--severity-error",
        "--output", str(DRC_JSON), str(PCB_PATH),
    ], stdout=subprocess.DEVNULL)
    return json.loads(DRC_JSON.read_text())


def delete_by_uuid(board, uuids):
    idmap = {t.m_Uuid.AsString(): t for t in board.GetTracks()}
    n = 0
    for u in uuids:
        if u in idmap:
            board.Delete(idmap[u])
            n += 1
    return n


def kill_remaining_shorts(board, drc):
    """Delete track/via side of every remaining short except known J2 pad-pad."""
    idmap = {t.m_Uuid.AsString(): t for t in board.GetTracks()}
    deleted = 0
    for v in drc["violations"]:
        if v["type"] != "shorting_items":
            continue
        desc = v.get("description", "")
        # skip known J2 header pitch short
        if "J2" in json.dumps(v) and "VBAT" in desc and "GND" in desc:
            continue
        track_ids = [it["uuid"] for it in v["items"] if it["uuid"] in idmap]
        # prefer deleting longer B.Cu / the sense highway
        def score(uid):
            obj = idmap[uid]
            s = 50 if type(obj).__name__ == "PCB_VIA" else 0
            try:
                s += ToMM(obj.GetLength())
            except Exception:
                pass
            return s
        if not track_ids:
            continue
        victim = max(track_ids, key=score)
        board.Delete(idmap[victim])
        deleted += 1
        # refresh idmap after delete
        idmap = {t.m_Uuid.AsString(): t for t in board.GetTracks()}
    return deleted


def remove_bad_gnd_stitches(board, fps):
    """Remove GND F stubs that land on sense C pads (C40 etc)."""
    # Delete GND tracks that end near C** pad1 if that pad is NOT GND
    bad = []
    sense_pads = []
    for ref in list(fps):
        if not (ref.startswith("C") or ref.startswith("R")):
            continue
        for pad in list(fps[ref].Pads()):
            if pad.GetNetname() and pad.GetNetname() != "GND":
                sense_pads.append((pad_xy(pad), pad.GetNetname()))
    for t in list(board.GetTracks()):
        if type(t).__name__ == "PCB_VIA":
            continue
        if t.GetNetname() != "GND":
            continue
        if t.GetLayer() != F_Cu:
            continue
        sx, sy = ToMM(t.GetStart().x), ToMM(t.GetStart().y)
        ex, ey = ToMM(t.GetEnd().x), ToMM(t.GetEnd().y)
        for (px, py), net in sense_pads:
            for x, y in ((sx, sy), (ex, ey)):
                if abs(x - px) < 0.35 and abs(y - py) < 0.35:
                    bad.append(t)
                    break
    for t in bad:
        try:
            board.Delete(t)
        except Exception:
            pass
    return len(bad)


def bridge_sensor5v(board, fps):
    """Connect PU top-bus island to existing bottom/module SENSOR_5V copper."""
    n = 0
    # Top bus was added at y=5 from E38 via; existing spine uses x=52 and y=128
    # Bridge: from top bus at (52, 5) down left edge to y=128, then to existing
    # Check if (52,5) region exists — add explicit bridge from side via of R201 up to left riser
    # Left riser at x=5 already may exist from original route_sensor_only
    # Connect top bus (y=5) to x=5 vertical if present, else create
    add_track(board, 50.0, 5.0, 5.0, 5.0, 0.35, "SENSOR_5V", B_Cu); n += 1
    add_track(board, 5.0, 5.0, 5.0, 128.0, 0.35, "SENSOR_5V", B_Cu); n += 1
    add_track(board, 5.0, 128.0, 52.0, 128.0, 0.35, "SENSOR_5V", B_Cu); n += 1
    # also tie E38 via path: existing via near (52, e38.y)
    e38 = pad_xy(get_pad(fps, "M1000", "E38"))
    add_track(board, e38[0], 10.0, 52.0, 10.0, 0.35, "SENSOR_5V", B_Cu); n += 1
    add_track(board, 52.0, 10.0, 52.0, 5.0, 0.35, "SENSOR_5V", B_Cu); n += 1
    return n


def restore_adio(board, fps):
    """Rebuild ADIO OUT: local bar + B corridor clear of PWR F lanes + J1 stub."""
    n = 0
    mapping = [
        ("ADIO1", "U11", "21", 55.0, "R201"),
        ("ADIO2", "U12", "15", 56.5, "R202"),
        ("ADIO3", "U13", "22", 58.0, "R203"),
        ("ADIO4", "U14", "16", 59.5, "R204"),
        ("ADIO5", "U15", "23", 140.0, "R205"),
        ("ADIO6", "U16", "17", 141.5, "R206"),
        ("ADIO7", "U17", "24", 143.0, "R207"),
        ("ADIO8", "U18", "18", 144.5, "R208"),
    ]
    # Clear existing ADIO tracks/vias first for clean restore
    for t in list(board.GetTracks()):
        if t.GetNetname() and t.GetNetname().startswith("ADIO"):
            board.Delete(t)
    for idx, (net, uref, jpin, cx, rp) in enumerate(mapping):
        ys = []
        ox = None
        for pn in ("8", "9", "10", "12", "13", "14"):
            px, py = pad_xy(get_pad(fps, uref, pn))
            ox = px
            ys.append(py)
        y0, y1 = min(ys), max(ys)
        add_track(board, ox, y0, ox, y1, 0.4, net); n += 1
        rx, ry = pad_xy(get_pad(fps, rp, "2"))
        add_track(board, rx, ry, ox, ry, 0.3, net); n += 1
        via_y = 50.5 + (idx % 4) * 0.55
        add_track(board, ox, y1 if idx >= 4 else y0, ox, via_y, 0.3, net); n += 1
        add_track(board, ox, via_y, cx, via_y, 0.3, net); n += 1
        add_via(board, cx, via_y, net); n += 1
        jx, jy = pad_xy(get_pad(fps, "J1", jpin))
        ap_y = 114.0 + idx * 0.6
        add_track(board, cx, via_y, cx, ap_y, 0.3, net, B_Cu); n += 1
        add_track(board, cx, ap_y, jx, ap_y, 0.3, net, B_Cu); n += 1
        stub_y = jy + 1.25
        add_track(board, jx, ap_y, jx, stub_y, 0.3, net, B_Cu); n += 1
        add_via(board, jx, stub_y, net); n += 1
        add_track(board, jx, stub_y, jx, jy, 0.3, net); n += 1
    return n


def restore_pwr(board, fps):
    """Rebuild PWR_OUT with B.Cu long runs + short F stubs at J1."""
    n = 0
    for t in list(board.GetTracks()):
        if t.GetNetname() and t.GetNetname().startswith("PWR_OUT"):
            board.Delete(t)
    mapping = [
        ("PWR_OUT1", "U1", ["14", "20"], 61.5, 120.5),
        ("PWR_OUT2", "U2", ["1", "8"], 108.0, 122.5),
        ("PWR_OUT3", "U3", ["7", "13"], 86.0, 124.5),
        ("PWR_OUT4", "U4", ["19", "26"], 130.0, 126.5),
    ]
    for net, uref, jpins, mid_x, target_y in mapping:
        outs = [pad_xy(get_pad(fps, uref, p)) for p in ("5", "6", "7")]
        cy = outs[0][1]
        xs = [p[0] for p in outs]
        add_track(board, min(xs), cy, max(xs), cy, 0.5, net); n += 1
        cx = sum(xs) / 3.0
        esc_y = cy - 2.8
        add_track(board, cx, cy, cx, esc_y, 0.7, net); n += 1
        add_track(board, cx, esc_y, mid_x, esc_y, 0.7, net); n += 1
        add_via(board, mid_x, esc_y, net); n += 1
        add_track(board, mid_x, esc_y, mid_x, target_y, 0.8, net, B_Cu); n += 1
        for jp in jpins:
            jx, jy = pad_xy(get_pad(fps, "J1", jp))
            via_y = jy + 1.4
            add_track(board, mid_x, target_y, jx, target_y, 0.8, net, B_Cu); n += 1
            add_track(board, jx, target_y, jx, via_y, 0.8, net, B_Cu); n += 1
            add_via(board, jx, via_y, net); n += 1
            add_track(board, jx, via_y, jx, jy, 0.55, net); n += 1
    return n


def restore_can(board, fps):
    n = 0
    for t in list(board.GetTracks()):
        if t.GetNetname() in ("CANH", "CANL"):
            board.Delete(t)
    for net, mpad, jpin, lane_x, bus_y in [
        ("CANH", "W12", "3", 3.5, 126.5),
        ("CANL", "W13", "10", 6.5, 127.8),
    ]:
        mx, my = pad_xy(get_pad(fps, "M1000", mpad))
        jx, jy = pad_xy(get_pad(fps, "J1", jpin))
        add_track(board, mx, my, lane_x, my, 0.3, net); n += 1
        add_via(board, lane_x, my, net); n += 1
        add_track(board, lane_x, my, lane_x, bus_y, 0.3, net, B_Cu); n += 1
        add_track(board, lane_x, bus_y, jx, bus_y, 0.3, net, B_Cu); n += 1
        add_via(board, jx, bus_y, net); n += 1
        add_track(board, jx, bus_y, jx, jy, 0.3, net); n += 1
    return n


def restore_en_is(board, fps):
    """Clear and rebuild EN/IS with exclusive lanes west of ADIO corridors."""
    n = 0
    en_nets = {
        "OUT_PWM1", "OUT_PWM2", "OUT_PWM3", "OUT_PWM4",
        "OUT_PWM5", "OUT_PWM6", "OUT_PWM7", "OUT_PWM8",
        "OUT_IO5", "OUT_IO6", "OUT_IO7", "OUT_IO8",
    }
    is_nets = {
        "IN_AUX1", "IN_AUX2", "IN_AUX3", "IN_AUX4",
        "IN_MAP1", "IN_MAP2", "IN_MAP3", "IN_O2S",
        "IN_O2S2", "IN_RES1", "IN_RES2", "IN_RES3",
    }
    for t in list(board.GetTracks()):
        if t.GetNetname() in en_nets or t.GetNetname() in is_nets:
            board.Delete(t)

    # local sense first
    for net, u, r, c in [
        ("IN_AUX1", "U1", "R10", "C10"), ("IN_AUX2", "U2", "R20", "C20"),
        ("IN_AUX3", "U3", "R30", "C30"), ("IN_AUX4", "U4", "R40", "C40"),
    ]:
        ux, uy = pad_xy(get_pad(fps, u, "3"))
        rx, ry = pad_xy(get_pad(fps, r, "2"))
        cx, cy = pad_xy(get_pad(fps, c, "1"))
        mid_y = uy - 1.8
        add_track(board, ux, uy, ux, mid_y, 0.25, net); n += 1
        add_track(board, ux, mid_y, rx, mid_y, 0.25, net); n += 1
        add_track(board, rx, mid_y, rx, ry, 0.25, net); n += 1
        add_track(board, rx, ry, cx, cy, 0.25, net); n += 1
    for net, u, r, c in [
        ("IN_MAP1", "U11", "R101", "C101"), ("IN_MAP2", "U12", "R102", "C102"),
        ("IN_MAP3", "U13", "R103", "C103"), ("IN_O2S", "U14", "R104", "C104"),
        ("IN_O2S2", "U15", "R105", "C105"), ("IN_RES1", "U16", "R106", "C106"),
        ("IN_RES2", "U17", "R107", "C107"), ("IN_RES3", "U18", "R108", "C108"),
    ]:
        ux, uy = pad_xy(get_pad(fps, u, "4"))
        rx, ry = pad_xy(get_pad(fps, r, "2"))
        cx, cy = pad_xy(get_pad(fps, c, "1"))
        add_track(board, ux, uy, ux, ry, 0.25, net); n += 1
        add_track(board, ux, ry, rx, ry, 0.25, net); n += 1
        add_track(board, rx, ry, cx, ry, 0.25, net); n += 1
        add_track(board, cx, ry, cx, cy, 0.25, net); n += 1

    # EN
    pairs = [
        ("OUT_PWM1", "U1", ["2"], "E27", +1.7, -2.0, 47.0),
        ("OUT_PWM2", "U2", ["2"], "E17", +1.7, -2.0, 47.7),
        ("OUT_PWM3", "U3", ["2"], "E16", +1.7, -2.0, 48.4),
        ("OUT_PWM4", "U4", ["2"], "E15", +1.7, -2.0, 49.1),
        ("OUT_PWM5", "U11", ["2", "3"], "E14", -1.8, 0.0, 49.8),
        ("OUT_PWM6", "U12", ["2", "3"], "E26", -1.8, 0.0, 50.5),
        ("OUT_PWM7", "U13", ["2", "3"], "E25", -1.8, 0.0, 51.2),
        ("OUT_PWM8", "U14", ["2", "3"], "E28", -1.8, 0.0, 51.9),
        ("OUT_IO5", "U15", ["2", "3"], "E7", -1.8, 0.0, 52.6),
        ("OUT_IO6", "U16", ["2", "3"], "E9", -1.8, 0.0, 53.3),
        ("OUT_IO7", "U17", ["2", "3"], "E23", -1.8, 0.0, 54.0),
        ("OUT_IO8", "U18", ["2", "3"], "E22", -1.8, 0.0, 54.7),
    ]
    for net, uref, pins, mpad, dx, dy, col in pairs:
        coords = [pad_xy(get_pad(fps, uref, p)) for p in pins]
        if len(coords) > 1:
            add_track(board, coords[0][0], coords[0][1], coords[1][0], coords[1][1], 0.25, net); n += 1
        sx, sy = coords[0]
        mx, my = pad_xy(get_pad(fps, "M1000", mpad))
        vx, vy = sx + dx, sy + dy
        add_track(board, sx, sy, sx, vy, 0.25, net); n += 1
        add_track(board, sx, vy, vx, vy, 0.25, net); n += 1
        add_via(board, vx, vy, net); n += 1
        add_track(board, vx, vy, col, vy, 0.25, net, B_Cu); n += 1
        add_track(board, col, vy, col, my, 0.25, net, B_Cu); n += 1
        add_via(board, col, my, net); n += 1
        add_track(board, col, my, mx, my, 0.25, net); n += 1

    # IS to M1000 S — columns at x=43–52, highways y>=56 (south of EN my<=36 and ADIO via_y)
    is_pairs = [
        ("IN_AUX1", "R10", "S13"), ("IN_AUX2", "R20", "S12"),
        ("IN_AUX3", "R30", "S11"), ("IN_AUX4", "R40", "S10"),
        ("IN_MAP1", "R101", "S21"), ("IN_MAP2", "R102", "S20"),
        ("IN_MAP3", "R103", "S19"), ("IN_O2S", "R104", "S16"),
        ("IN_O2S2", "R105", "S15"), ("IN_RES1", "R106", "S17"),
        ("IN_RES2", "R107", "S14"), ("IN_RES3", "R108", "S18"),
    ]
    for idx, (net, rref, mpad) in enumerate(is_pairs):
        sx, sy = pad_xy(get_pad(fps, rref, "2"))
        mx, my = pad_xy(get_pad(fps, "M1000", mpad))
        vx, vy = sx + 1.0, sy + 1.8
        add_track(board, sx, sy, sx, vy, 0.25, net); n += 1
        add_track(board, sx, vy, vx, vy, 0.25, net); n += 1
        add_via(board, vx, vy, net); n += 1
        hwy = 56.0 + idx * 0.8
        col = 42.5 + (idx % 12) * 0.8
        add_track(board, vx, vy, col, vy, 0.25, net, B_Cu); n += 1
        add_track(board, col, vy, col, hwy, 0.25, net, B_Cu); n += 1
        add_track(board, col, hwy, mx, hwy, 0.25, net, B_Cu); n += 1
        add_via(board, mx, hwy, net); n += 1
        add_track(board, mx, hwy, mx, my, 0.25, net); n += 1
    return n


def count_tracks(board):
    tr = [t for t in board.GetTracks() if type(t).__name__ != "PCB_VIA"]
    vias = [t for t in board.GetTracks() if type(t).__name__ == "PCB_VIA"]
    return len(tr), len(vias)


def main():
    print("=== restore connectivity ===")
    drc0 = run_drc()
    shorts0 = sum(1 for v in drc0["violations"] if v["type"] == "shorting_items")
    cross0 = sum(1 for v in drc0["violations"] if v["type"] == "tracks_crossing")
    unc0 = len(drc0["unconnected_items"])
    print(f"BEFORE shorts={shorts0} cross={cross0} unc={unc0}")

    board = pcbnew.LoadBoard(str(PCB_PATH))
    fps = fp_map(board)

    d1 = kill_remaining_shorts(board, drc0)
    print(f"Killed {d1} remaining short tracks")
    d2 = remove_bad_gnd_stitches(board, fps)
    print(f"Removed {d2} bad GND stitches")

    print("Restoring ADIO...")
    print(" ", restore_adio(board, fps))
    print("Restoring PWR_OUT...")
    print(" ", restore_pwr(board, fps))
    print("Restoring CAN...")
    print(" ", restore_can(board, fps))
    print("Restoring EN/IS...")
    print(" ", restore_en_is(board, fps))
    print("Bridging SENSOR_5V...")
    print(" ", bridge_sensor5v(board, fps))

    print("Filling zones...")
    ZONE_FILLER(board).Fill(board.Zones())
    board.BuildConnectivity()
    at, av = count_tracks(board)
    unc_c = board.GetConnectivity().GetUnconnectedCount(True)
    print(f"MID tracks={at} vias={av} unc_conn={unc_c}")

    pcbnew.SaveBoard(str(PCB_PATH), board)
    downgrade_to_k8(PCB_PATH)

    drc1 = run_drc()
    shorts1 = sum(1 for v in drc1["violations"] if v["type"] == "shorting_items")
    cross1 = sum(1 for v in drc1["violations"] if v["type"] == "tracks_crossing")
    unc1 = len(drc1["unconnected_items"])
    print(f"AFTER shorts={shorts1} cross={cross1} unc={unc1}")

    # one more short-only surgical pass if needed
    if shorts1 > 5:
        board = pcbnew.LoadBoard(str(PCB_PATH))
        idmap = {t.m_Uuid.AsString(): t for t in board.GetTracks()}
        victims = set()
        for v in drc1["violations"]:
            if v["type"] != "shorting_items":
                continue
            if "J2" in json.dumps(v):
                continue
            ids = [it["uuid"] for it in v["items"] if it["uuid"] in idmap]
            if not ids:
                continue
            def score(uid):
                obj = idmap[uid]
                try:
                    return ToMM(obj.GetLength()) + (30 if type(obj).__name__ == "PCB_VIA" else 0)
                except Exception:
                    return 10
            victims.add(max(ids, key=score))
        for uid in victims:
            board.Delete(idmap[uid])
        print(f"Extra short pass deleted {len(victims)}")
        ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(str(PCB_PATH), board)
        downgrade_to_k8(PCB_PATH)
        drc1 = run_drc()
        shorts1 = sum(1 for v in drc1["violations"] if v["type"] == "shorting_items")
        cross1 = sum(1 for v in drc1["violations"] if v["type"] == "tracks_crossing")
        unc1 = len(drc1["unconnected_items"])
        at, av = count_tracks(board)
        print(f"AFTER2 shorts={shorts1} cross={cross1} unc={unc1} tracks={at} vias={av}")

    with STATUS.open("w") as f:
        f.write(f"before_shorts={shorts0}\n")
        f.write(f"before_crossings={cross0}\n")
        f.write(f"before_unc={unc0}\n")
        f.write(f"after_tracks={at}\n")
        f.write(f"after_vias={av}\n")
        f.write(f"after_shorts={shorts1}\n")
        f.write(f"after_crossings={cross1}\n")
        f.write(f"after_unc={unc1}\n")
        f.write("strategy=surgical_delete_plus_selective_restore_k8\n")
    print("Wrote", STATUS)
    head = PCB_PATH.read_text()[:200]
    print("K8", "20240108" in head, '8.0' in head)
    return 0


if __name__ == "__main__":
    sys.exit(main())
