#!/usr/bin/env python3
"""Fill pours + selective copper for pdmrazora. Avoid dense meshes / shared B.Cu lanes."""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import pcbnew
from pcbnew import (
    VECTOR2I, FromMM, ToMM, PCB_TRACK, PCB_VIA, ZONE, F_Cu, B_Cu, ZONE_FILLER,
)

ROOT = Path(__file__).resolve().parents[1]
PCB_PATH = ROOT / "pdmrazora.kicad_pcb"
STATUS = ROOT / "scripts" / "copper_status.txt"


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


def clear_tracks(board):
    tracks = list(board.GetTracks())
    for t in tracks:
        board.Remove(t)


def set_rect_corners(z, x1, y1, x2, y2):
    assert z.GetNumCorners() == 4
    z.SetCornerPosition(0, mm(x1, y1))
    z.SetCornerPosition(1, mm(x2, y1))
    z.SetCornerPosition(2, mm(x2, y2))
    z.SetCornerPosition(3, mm(x1, y2))


def add_rect_zone(board, netname, layer, x1, y1, x2, y2, clearance=0.25, min_thickness=0.3):
    z = ZONE(board)
    z.SetNet(ensure_net(board, netname))
    z.SetLayer(layer)
    z.SetIsRuleArea(False)
    z.SetLocalClearance(FromMM(clearance))
    z.SetMinThickness(FromMM(min_thickness))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    for x, y in [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]:
        z.AppendCorner(mm(x, y), -1)
    board.Add(z)
    return z


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
        v.SetFrontWidth(FromMM(size))
    except Exception:
        try:
            v.SetWidth(F_Cu, FromMM(size))
        except Exception:
            pass
    v.SetNet(ensure_net(board, netname))
    board.Add(v)
    return v


def fp_map(board):
    return {fp.GetReference(): fp for fp in board.GetFootprints()}


def get_pad(fps, ref, num):
    for pad in fps[ref].Pads():
        if pad.GetNumber() == str(num):
            return pad
    raise KeyError(f"{ref}.{num}")


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
    assert "20240108" in path.read_text()[:250]
    assert 'generator_version "8.0"' in path.read_text()[:250]


def rebuild_zones(board):
    assert board.GetAreaCount() >= 16
    set_rect_corners(board.GetArea(1), 85, 55, 140, 100)  # VBAT HP
    set_rect_corners(board.GetArea(2), 1, 1, 149, 129)     # GND B
    set_rect_corners(board.GetArea(3), 1, 85, 70, 118)     # GND F entry
    set_rect_corners(board.GetArea(4), 86.5, 58.5, 92.5, 63.5)
    set_rect_corners(board.GetArea(5), 109.5, 58.5, 115.5, 63.5)
    set_rect_corners(board.GetArea(6), 86.5, 80.5, 92.5, 85.5)
    set_rect_corners(board.GetArea(7), 109.5, 80.5, 115.5, 85.5)
    for i, box in enumerate([
        (71.5, 13.5, 74.5, 19.0), (89.5, 13.5, 92.5, 19.0),
        (107.5, 13.5, 110.5, 19.0), (125.5, 13.5, 128.5, 19.0),
        (71.5, 39.5, 74.5, 45.0), (89.5, 39.5, 92.5, 45.0),
        (107.5, 39.5, 110.5, 45.0), (125.5, 39.5, 128.5, 45.0),
    ]):
        set_rect_corners(board.GetArea(8 + i), *box)
    # Extra VBAT
    add_rect_zone(board, "VBAT", F_Cu, 10, 88, 70, 118, 0.3, 0.4)
    add_rect_zone(board, "VBAT", F_Cu, 55, 115, 100, 128, 0.3, 0.4)
    add_rect_zone(board, "VBAT", F_Cu, 55, 7, 140, 12, 0.25, 0.3)
    add_rect_zone(board, "VBAT", F_Cu, 55, 33, 140, 37, 0.25, 0.3)
    add_rect_zone(board, "GND", F_Cu, 85, 55, 140, 100, 0.25, 0.3)


def route_power(board, fps):
    n = 0
    j2 = pad_xy(get_pad(fps, "J2", "1"))
    f1a = pad_xy(get_pad(fps, "F1", "1"))
    f1b = pad_xy(get_pad(fps, "F1", "2"))
    c1 = pad_xy(get_pad(fps, "C1", "1"))
    c2 = pad_xy(get_pad(fps, "C2", "1"))
    d1 = pad_xy(get_pad(fps, "D1", "1"))
    add_track(board, j2[0], j2[1], f1a[0], j2[1], 1.5, "VBAT"); n += 1
    add_track(board, f1a[0], j2[1], f1a[0], f1a[1], 1.5, "VBAT"); n += 1
    add_track(board, f1b[0], f1b[1], c1[0], f1b[1], 1.2, "VBAT"); n += 1
    add_track(board, c1[0], f1b[1], c1[0], c1[1], 1.2, "VBAT"); n += 1
    add_track(board, f1b[0], f1b[1], f1b[0], c2[1], 0.8, "VBAT"); n += 1
    add_track(board, f1b[0], c2[1], c2[0], c2[1], 0.8, "VBAT"); n += 1
    add_track(board, f1b[0], f1b[1], d1[0], f1b[1], 0.8, "VBAT"); n += 1
    add_track(board, d1[0], f1b[1], d1[0], d1[1], 0.8, "VBAT"); n += 1
    # link into HP VBAT pour
    add_track(board, f1b[0], f1b[1], f1b[0], 120.0, 1.2, "VBAT"); n += 1
    add_track(board, f1b[0], 120.0, 90.0, 120.0, 1.2, "VBAT"); n += 1
    add_track(board, 90.0, 120.0, 90.0, 100.0, 1.2, "VBAT"); n += 1
    # GND entry
    j2g = pad_xy(get_pad(fps, "J2", "2"))
    d1g = pad_xy(get_pad(fps, "D1", "2"))
    c1g = pad_xy(get_pad(fps, "C1", "2"))
    add_track(board, j2g[0], j2g[1], d1g[0], j2g[1], 1.2, "GND"); n += 1
    add_track(board, d1g[0], j2g[1], d1g[0], d1g[1], 1.2, "GND"); n += 1
    add_via(board, j2g[0] + 2.5, j2g[1], "GND"); n += 1
    add_track(board, c1g[0], c1g[1], c1g[0], 100.0, 0.5, "GND"); n += 1
    add_via(board, c1g[0], 100.0, "GND"); n += 1
    # HP dual VBAT pads
    for uref in ["U1", "U2", "U3", "U4"]:
        pts = []
        for pad in fps[uref].Pads():
            if pad.GetNumber() == "4" and pad.GetNetname() == "VBAT":
                pts.append(pad_xy(pad))
        if len(pts) >= 2:
            add_track(board, pts[0][0], pts[0][1], pts[1][0], pts[1][1], 1.0, "VBAT"); n += 1
    # ADIO VBAT stubs into supply strips
    for uref in ["U11", "U12", "U13", "U14"]:
        px, py = pad_xy(get_pad(fps, uref, "15"))
        add_track(board, px, py, px, 9.5, 0.6, "VBAT"); n += 1
    for uref in ["U15", "U16", "U17", "U18"]:
        px, py = pad_xy(get_pad(fps, uref, "15"))
        add_track(board, px, py, px, 35.0, 0.6, "VBAT"); n += 1
    # M1000 VBAT N27 → top strip via B.Cu north of keepout
    mx, my = pad_xy(get_pad(fps, "M1000", "N27"))
    add_track(board, mx, my, mx, 9.0, 0.5, "VBAT"); n += 1
    add_via(board, mx, 9.0, "VBAT"); n += 1
    add_track(board, mx, 9.0, 60.0, 9.0, 0.5, "VBAT", B_Cu); n += 1
    add_via(board, 60.0, 9.0, "VBAT"); n += 1
    add_track(board, 60.0, 9.0, 60.0, 9.5, 0.5, "VBAT"); n += 1
    return n


def route_hp_out(board, fps):
    """Unique mid-x corridors so PWR_OUT nets don't share copper."""
    n = 0
    # mid_x chosen between HP and J1, unique per channel
    mapping = [
        ("PWR_OUT1", "U1", ["14", "20"], 80.0),
        ("PWR_OUT2", "U2", ["1", "8"], 104.0),
        ("PWR_OUT3", "U3", ["7", "13"], 88.0),
        ("PWR_OUT4", "U4", ["19", "26"], 112.0),
    ]
    for idx, (net, uref, jpins, mid_x) in enumerate(mapping):
        outs = [pad_xy(get_pad(fps, uref, p)) for p in ("5", "6", "7")]
        cy = outs[0][1]
        xs = [p[0] for p in outs]
        add_track(board, min(xs), cy, max(xs), cy, 1.2, net); n += 1
        cx = sum(xs) / 3
        add_track(board, cx, cy, mid_x, cy, 1.0, net); n += 1
        # exclusive horizontal lane above connector per channel
        target_y = 118.0 + idx * 1.5
        add_track(board, mid_x, cy, mid_x, target_y, 1.0, net); n += 1
        for jp in jpins:
            jx, jy = pad_xy(get_pad(fps, "J1", jp))
            add_track(board, mid_x, target_y, jx, target_y, 1.0, net); n += 1
            add_track(board, jx, target_y, jx, jy, 1.0, net); n += 1
    return n


def route_adio_out(board, fps):
    """Local F.Cu near chip; long run on B.Cu unique corridor; F stub to J1."""
    n = 0
    # corridor_x chosen away from J1 pad x of OTHER nets (esp. SENSOR_GND 79.5)
    mapping = [
        ("ADIO1", "U11", "21", 62.0, "R201"),
        ("ADIO2", "U12", "15", 63.8, "R202"),
        ("ADIO3", "U13", "22", 65.6, "R203"),
        ("ADIO4", "U14", "16", 67.4, "R204"),
        ("ADIO5", "U15", "23", 132.0, "R205"),
        ("ADIO6", "U16", "17", 133.5, "R206"),
        ("ADIO7", "U17", "24", 135.0, "R207"),
        ("ADIO8", "U18", "18", 136.5, "R208"),
    ]
    for idx, (net, uref, jpin, cx, rp) in enumerate(mapping):
        ys = []
        ox = None
        for pn in ("8", "9", "10", "12", "13", "14"):
            px, py = pad_xy(get_pad(fps, uref, pn))
            ox = px
            ys.append(py)
        add_track(board, ox, min(ys), ox, max(ys), 0.5, net); n += 1
        rx, ry = pad_xy(get_pad(fps, rp, "2"))
        # PU via short vertical only if ry is outside bar
        add_track(board, rx, ry, ox, ry, 0.35, net); n += 1
        add_track(board, ox, ry, ox, max(min(ys), min(max(ys), ry)), 0.35, net); n += 1
        # jog to corridor at unique escape_y per chip (avoid shared row y)
        esc_y = min(ys) - 1.5 - idx * 0.9
        add_track(board, ox, min(ys), ox, esc_y, 0.4, net); n += 1
        add_track(board, ox, esc_y, cx, esc_y, 0.4, net); n += 1
        add_via(board, cx, esc_y, net); n += 1
        jx, jy = pad_xy(get_pad(fps, "J1", jpin))
        # B.Cu south to exclusive approach_y then via and F to pin
        ap_y = 107.0 + idx * 1.1
        add_track(board, cx, esc_y, cx, ap_y, 0.35, net, B_Cu); n += 1
        add_via(board, cx, ap_y, net); n += 1
        add_track(board, cx, ap_y, jx, ap_y, 0.4, net); n += 1
        add_track(board, jx, ap_y, jx, jy, 0.4, net); n += 1
    return n


def route_local_sense(board, fps):
    """Short local IS↔RC only; GND via offset away from IS node."""
    n = 0
    for net, u, r, c in [
        ("IN_AUX1", "U1", "R10", "C10"), ("IN_AUX2", "U2", "R20", "C20"),
        ("IN_AUX3", "U3", "R30", "C30"), ("IN_AUX4", "U4", "R40", "C40"),
    ]:
        ux, uy = pad_xy(get_pad(fps, u, "3"))
        rx, ry = pad_xy(get_pad(fps, r, "2"))
        cx, cy = pad_xy(get_pad(fps, c, "1"))
        # approach pad2 from above/below, not across pad1
        mid_y = ry - 1.2
        add_track(board, ux, uy, ux, mid_y, 0.25, net); n += 1
        add_track(board, ux, mid_y, rx, mid_y, 0.25, net); n += 1
        add_track(board, rx, mid_y, rx, ry, 0.25, net); n += 1
        add_track(board, rx, ry, cx, cy, 0.25, net); n += 1
        # GND via south of R pad 1, clear of IS
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
    return n


def route_en_to_m1000(board, fps):
    """Exclusive B.Cu lane = M1000 pad Y; exclusive via column per net."""
    n = 0
    pairs = [
        ("OUT_PWM1", "U1", ["2"], "E27", 82.0),
        ("OUT_PWM2", "U2", ["2"], "E17", 83.0),
        ("OUT_PWM3", "U3", ["2"], "E16", 84.0),
        ("OUT_PWM4", "U4", ["2"], "E15", 85.0),
        ("OUT_PWM5", "U11", ["2", "3"], "E14", 86.0),
        ("OUT_PWM6", "U12", ["2", "3"], "E26", 87.0),
        ("OUT_PWM7", "U13", ["2", "3"], "E25", 96.0),
        ("OUT_PWM8", "U14", ["2", "3"], "E28", 97.0),
        ("OUT_IO5", "U15", ["2", "3"], "E7", 98.0),
        ("OUT_IO6", "U16", ["2", "3"], "E9", 99.0),
        ("OUT_IO7", "U17", ["2", "3"], "E23", 100.0),
        ("OUT_IO8", "U18", ["2", "3"], "E22", 101.0),
    ]
    for net, uref, pins, mpad, via_x in pairs:
        coords = [pad_xy(get_pad(fps, uref, p)) for p in pins]
        if len(coords) > 1:
            add_track(board, coords[0][0], coords[0][1], coords[1][0], coords[1][1], 0.25, net); n += 1
        sx, sy = coords[0]
        mx, my = pad_xy(get_pad(fps, "M1000", mpad))
        # F: stub toward via_x on unique column (right of module, left of drivers)
        add_track(board, sx, sy, via_x, sy, 0.25, net); n += 1
        add_via(board, via_x, sy, net); n += 1
        add_track(board, via_x, sy, via_x, my, 0.25, net, B_Cu); n += 1
        approach = 52.0
        add_track(board, via_x, my, approach, my, 0.25, net, B_Cu); n += 1
        add_via(board, approach, my, net); n += 1
        add_track(board, approach, my, mx, my, 0.25, net); n += 1
    return n


def route_isense_to_m1000(board, fps):
    """Exclusive via column; approach M1000 from south on F.Cu."""
    n = 0
    pairs = [
        ("IN_AUX1", "R10", "S13", 53.2), ("IN_AUX2", "R20", "S12", 53.9),
        ("IN_AUX3", "R30", "S11", 54.6), ("IN_AUX4", "R40", "S10", 55.3),
        ("IN_MAP1", "R101", "S21", 56.0), ("IN_MAP2", "R102", "S20", 56.7),
        ("IN_MAP3", "R103", "S19", 57.4), ("IN_O2S", "R104", "S16", 58.1),
        ("IN_O2S2", "R105", "S15", 58.8), ("IN_RES1", "R106", "S17", 59.5),
        ("IN_RES2", "R107", "S14", 60.2), ("IN_RES3", "R108", "S18", 60.9),
    ]
    for idx, (net, rref, mpad, via_x) in enumerate(pairs):
        sx, sy = pad_xy(get_pad(fps, rref, "2"))
        mx, my = pad_xy(get_pad(fps, "M1000", mpad))
        hwy = 53.2 + idx * 0.7  # exclusive B.Cu horizontal lane
        add_track(board, sx, sy, via_x, sy, 0.25, net); n += 1
        add_via(board, via_x, sy, net); n += 1
        add_track(board, via_x, sy, via_x, hwy, 0.25, net, B_Cu); n += 1
        add_track(board, via_x, hwy, mx, hwy, 0.25, net, B_Cu); n += 1
        add_via(board, mx, hwy, net); n += 1
        add_track(board, mx, hwy, mx, my, 0.25, net); n += 1
    return n

def route_system(board, fps):
    n = 0
    # IGN
    jign = pad_xy(get_pad(fps, "J1", "4"))
    r1a = pad_xy(get_pad(fps, "R1", "1"))
    r1b = pad_xy(get_pad(fps, "R1", "2"))
    r2a = pad_xy(get_pad(fps, "R2", "1"))
    r2b = pad_xy(get_pad(fps, "R2", "2"))
    add_track(board, jign[0], jign[1], jign[0], r1a[1], 0.4, "IGN_SW"); n += 1
    add_track(board, jign[0], r1a[1], r1a[0], r1a[1], 0.4, "IGN_SW"); n += 1
    add_track(board, r1b[0], r1b[1], r2a[0], r1b[1], 0.3, "IN_VIGN"); n += 1
    add_track(board, r2a[0], r1b[1], r2a[0], r2a[1], 0.3, "IN_VIGN"); n += 1
    add_track(board, r2b[0], r2b[1], r2b[0], r2b[1] + 2.0, 0.3, "GND"); n += 1
    add_via(board, r2b[0], r2b[1] + 2.0, "GND"); n += 1
    # IN_VIGN to N26 via B.Cu north edge
    mx, my = pad_xy(get_pad(fps, "M1000", "N26"))
    add_track(board, r1b[0], r1b[1], r1b[0] - 2.5, r1b[1], 0.3, "IN_VIGN"); n += 1
    add_via(board, r1b[0] - 2.5, r1b[1], "IN_VIGN"); n += 1
    add_track(board, r1b[0] - 2.5, r1b[1], r1b[0] - 2.5, 10.0, 0.3, "IN_VIGN", B_Cu); n += 1
    add_track(board, r1b[0] - 2.5, 10.0, mx, 10.0, 0.3, "IN_VIGN", B_Cu); n += 1
    add_via(board, mx, 10.0, "IN_VIGN"); n += 1
    add_track(board, mx, 10.0, mx, my, 0.3, "IN_VIGN"); n += 1

    # CAN — left edge B.Cu, exclusive x=4.5 / 5.5
    for net, mpad, jpin, lane_x in [("CANH", "W12", "3", 4.0), ("CANL", "W13", "10", 7.0)]:
        mx, my = pad_xy(get_pad(fps, "M1000", mpad))
        jx, jy = pad_xy(get_pad(fps, "J1", jpin))
        add_track(board, mx, my, lane_x, my, 0.3, net); n += 1
        add_via(board, lane_x, my, net); n += 1
        add_track(board, lane_x, my, lane_x, 122.0, 0.3, net, B_Cu); n += 1
        add_track(board, lane_x, 122.0, jx, 122.0, 0.3, net, B_Cu); n += 1
        add_via(board, jx, 122.0, net); n += 1
        add_track(board, jx, 122.0, jx, jy, 0.3, net); n += 1

    # SENSOR_5V: B.Cu bus along top (y=5), clear of ADIO B corridors
    bus_y = 5.0
    e38 = pad_xy(get_pad(fps, "M1000", "E38"))
    add_track(board, e38[0], e38[1], 52.5, e38[1], 0.4, "SENSOR_5V"); n += 1
    add_via(board, 52.5, e38[1], "SENSOR_5V"); n += 1
    add_track(board, 52.5, e38[1], 52.5, bus_y, 0.4, "SENSOR_5V", B_Cu); n += 1
    add_track(board, 52.5, bus_y, 132.0, bus_y, 0.5, "SENSOR_5V", B_Cu); n += 1
    for r in range(201, 209):
        rx, ry = pad_xy(get_pad(fps, f"R{r}", "1"))
        side = rx - 1.8  # west of PU, away from ADIO OUT east pads
        add_track(board, rx, ry, side, ry, 0.3, "SENSOR_5V"); n += 1
        add_via(board, side, ry, "SENSOR_5V"); n += 1
        add_track(board, side, ry, side, bus_y, 0.3, "SENSOR_5V", B_Cu); n += 1
        # tee into bus
        add_track(board, side, bus_y, side + 0.01, bus_y, 0.3, "SENSOR_5V", B_Cu); n += 1
    for jp in ("5", "11"):
        jx, jy = pad_xy(get_pad(fps, "J1", jp))
        ex = 81.0 + (0.8 if jp == "5" else 0.0)
        add_track(board, jx, jy, ex, jy, 0.4, "SENSOR_5V"); n += 1
        add_via(board, ex, jy, "SENSOR_5V"); n += 1
        add_track(board, ex, jy, ex, bus_y, 0.4, "SENSOR_5V", B_Cu); n += 1
    n30 = pad_xy(get_pad(fps, "M1000", "N30"))
    w2 = pad_xy(get_pad(fps, "M1000", "W2"))
    add_track(board, n30[0], n30[1], n30[0], 10.0, 0.35, "SENSOR_5V"); n += 1
    add_via(board, n30[0], 10.0, "SENSOR_5V"); n += 1
    add_track(board, n30[0], 10.0, n30[0], bus_y, 0.35, "SENSOR_5V", B_Cu); n += 1
    add_track(board, n30[0], bus_y, 52.5, bus_y, 0.35, "SENSOR_5V", B_Cu); n += 1
    add_track(board, w2[0], w2[1], 5.0, w2[1], 0.35, "SENSOR_5V"); n += 1
    add_via(board, 5.0, w2[1], "SENSOR_5V"); n += 1
    add_track(board, 5.0, w2[1], 5.0, bus_y, 0.35, "SENSOR_5V", B_Cu); n += 1
    add_track(board, 5.0, bus_y, 52.5, bus_y, 0.35, "SENSOR_5V", B_Cu); n += 1

    # SENSOR_GND dedicated
    a = pad_xy(get_pad(fps, "J1", "6"))
    b = pad_xy(get_pad(fps, "J1", "12"))
    add_track(board, a[0], a[1], b[0], a[1], 0.4, "SENSOR_GND"); n += 1
    add_track(board, b[0], a[1], b[0], b[1], 0.4, "SENSOR_GND"); n += 1
    e39 = pad_xy(get_pad(fps, "M1000", "E39"))
    add_track(board, e39[0], e39[1], 52.5, e39[1], 0.4, "SENSOR_GND"); n += 1
    add_via(board, 52.5, e39[1], "SENSOR_GND"); n += 1
    # B highway at y=60 (below SENSOR_5V bus)
    sg_y = 70.0
    add_track(board, 52.5, e39[1], 52.5, sg_y, 0.4, "SENSOR_GND", B_Cu); n += 1
    add_track(board, 52.5, sg_y, a[0] + 2.0, sg_y, 0.4, "SENSOR_GND", B_Cu); n += 1
    add_via(board, a[0] + 2.0, sg_y, "SENSOR_GND"); n += 1
    add_track(board, a[0] + 2.0, sg_y, a[0] + 2.0, a[1], 0.4, "SENSOR_GND"); n += 1
    add_track(board, a[0] + 2.0, a[1], a[0], a[1], 0.4, "SENSOR_GND"); n += 1
    w1 = pad_xy(get_pad(fps, "M1000", "W1"))
    add_track(board, w1[0], w1[1], 2.5, w1[1], 0.35, "SENSOR_GND"); n += 1
    add_via(board, 2.5, w1[1], "SENSOR_GND"); n += 1
    add_track(board, 2.5, w1[1], 2.5, sg_y, 0.35, "SENSOR_GND", B_Cu); n += 1
    add_track(board, 2.5, sg_y, 52.5, sg_y, 0.35, "SENSOR_GND", B_Cu); n += 1
    return n


def route_en_stubs(board, fps):
    """Adjacent via + exclusive B.Cu lane per net (lane = M1000 pad Y)."""
    n = 0
    pairs = [
        ("OUT_PWM1", "U1", ["2"], "E27"), ("OUT_PWM2", "U2", ["2"], "E17"),
        ("OUT_PWM3", "U3", ["2"], "E16"), ("OUT_PWM4", "U4", ["2"], "E15"),
        ("OUT_PWM5", "U11", ["2", "3"], "E14"), ("OUT_PWM6", "U12", ["2", "3"], "E26"),
        ("OUT_PWM7", "U13", ["2", "3"], "E25"), ("OUT_PWM8", "U14", ["2", "3"], "E28"),
        ("OUT_IO5", "U15", ["2", "3"], "E7"), ("OUT_IO6", "U16", ["2", "3"], "E9"),
        ("OUT_IO7", "U17", ["2", "3"], "E23"), ("OUT_IO8", "U18", ["2", "3"], "E22"),
    ]
    for idx, (net, uref, pins, mpad) in enumerate(pairs):
        coords = [pad_xy(get_pad(fps, uref, p)) for p in pins]
        if len(coords) > 1:
            add_track(board, coords[0][0], coords[0][1], coords[1][0], coords[1][1], 0.25, net); n += 1
        sx, sy = coords[0]
        mx, my = pad_xy(get_pad(fps, "M1000", mpad))
        vx, vy = sx - 1.3, sy
        add_track(board, sx, sy, vx, vy, 0.25, net); n += 1
        add_via(board, vx, vy, net); n += 1
        # B: to exclusive column then to my
        col = 48.5 - idx * 0.55  # left of module east edge, unique
        if col < 45:
            col = 45.0 + (idx % 6) * 0.55
        add_track(board, vx, vy, col, vy, 0.25, net, B_Cu); n += 1
        add_track(board, col, vy, col, my, 0.25, net, B_Cu); n += 1
        add_track(board, col, my, 50.2, my, 0.25, net, B_Cu); n += 1
        add_via(board, 50.2, my, net); n += 1
        add_track(board, 50.2, my, mx, my, 0.25, net); n += 1
    return n


def route_is_stubs(board, fps):
    """Adjacent via; B.Cu path along x=46-52 band only (module east keepout edge)."""
    n = 0
    pairs = [
        ("IN_AUX1", "R10", "S13"), ("IN_AUX2", "R20", "S12"),
        ("IN_AUX3", "R30", "S11"), ("IN_AUX4", "R40", "S10"),
        ("IN_MAP1", "R101", "S21"), ("IN_MAP2", "R102", "S20"),
        ("IN_MAP3", "R103", "S19"), ("IN_O2S", "R104", "S16"),
        ("IN_O2S2", "R105", "S15"), ("IN_RES1", "R106", "S17"),
        ("IN_RES2", "R107", "S14"), ("IN_RES3", "R108", "S18"),
    ]
    for idx, (net, rref, mpad) in enumerate(pairs):
        sx, sy = pad_xy(get_pad(fps, rref, "2"))
        mx, my = pad_xy(get_pad(fps, "M1000", mpad))
        vx, vy = sx, sy + 1.5
        add_track(board, sx, sy, vx, vy, 0.25, net); n += 1
        add_via(board, vx, vy, net); n += 1
        col = 46.0 + (idx % 12) * 0.45
        hwy = 65.0 + idx * 0.55
        add_track(board, vx, vy, col, vy, 0.25, net, B_Cu); n += 1
        add_track(board, col, vy, col, hwy, 0.25, net, B_Cu); n += 1
        add_track(board, col, hwy, mx, hwy, 0.25, net, B_Cu); n += 1
        add_via(board, mx, hwy, net); n += 1
        add_track(board, mx, hwy, mx, my, 0.25, net); n += 1
    return n



def route_ign_only(board, fps):
    n = 0
    jign = pad_xy(get_pad(fps, "J1", "4"))
    r1a = pad_xy(get_pad(fps, "R1", "1"))
    r1b = pad_xy(get_pad(fps, "R1", "2"))
    r2a = pad_xy(get_pad(fps, "R2", "1"))
    mx, my = pad_xy(get_pad(fps, "M1000", "N26"))
    add_track(board, jign[0], jign[1], jign[0], r1a[1], 0.4, "IGN_SW"); n += 1
    add_track(board, jign[0], r1a[1], r1a[0], r1a[1], 0.4, "IGN_SW"); n += 1
    add_track(board, r1b[0], r1b[1], r2a[0], r1b[1], 0.3, "IN_VIGN"); n += 1
    add_track(board, r2a[0], r1b[1], r2a[0], pad_xy(get_pad(fps, "R2", "1"))[1], 0.3, "IN_VIGN"); n += 1
    add_track(board, r1b[0], r1b[1], 58.0, r1b[1], 0.3, "IN_VIGN"); n += 1
    add_via(board, 58.0, r1b[1], "IN_VIGN"); n += 1
    add_track(board, 58.0, r1b[1], 58.0, 6.5, 0.3, "IN_VIGN", B_Cu); n += 1
    add_track(board, 58.0, 6.5, mx, 6.5, 0.3, "IN_VIGN", B_Cu); n += 1
    add_via(board, mx, 6.5, "IN_VIGN"); n += 1
    add_track(board, mx, 6.5, mx, my, 0.3, "IN_VIGN"); n += 1
    return n


def route_can_only(board, fps):
    n = 0
    for net, mpad, jpin, lane_x in [("CANH", "W12", "3", 4.0), ("CANL", "W13", "10", 7.0)]:
        mx, my = pad_xy(get_pad(fps, "M1000", mpad))
        jx, jy = pad_xy(get_pad(fps, "J1", jpin))
        add_track(board, mx, my, lane_x, my, 0.3, net); n += 1
        add_via(board, lane_x, my, net); n += 1
        add_track(board, lane_x, my, lane_x, 124.0, 0.3, net, B_Cu); n += 1
        add_track(board, lane_x, 124.0, jx, 124.0, 0.3, net, B_Cu); n += 1
        add_via(board, jx, 124.0, net); n += 1
        add_track(board, jx, 124.0, jx, jy, 0.3, net); n += 1
    return n


def route_sensor_only(board, fps):
    n = 0
    e38 = pad_xy(get_pad(fps, "M1000", "E38"))
    add_track(board, e38[0], e38[1], 52.0, e38[1], 0.4, "SENSOR_5V"); n += 1
    add_via(board, 52.0, e38[1], "SENSOR_5V"); n += 1
    add_track(board, 52.0, e38[1], 52.0, 128.0, 0.4, "SENSOR_5V", B_Cu); n += 1
    add_track(board, 52.0, 128.0, 140.0, 128.0, 0.4, "SENSOR_5V", B_Cu); n += 1
    for i, jp in enumerate(("5", "11")):
        jx, jy = pad_xy(get_pad(fps, "J1", jp))
        ex = 138.0 - i * 1.5
        add_via(board, ex, 128.0, "SENSOR_5V"); n += 1
        add_track(board, ex, 128.0, ex, jy, 0.4, "SENSOR_5V"); n += 1
        add_track(board, ex, jy, jx, jy, 0.4, "SENSOR_5V"); n += 1
    a5 = pad_xy(get_pad(fps, "J1", "5"))
    a11 = pad_xy(get_pad(fps, "J1", "11"))
    add_track(board, a5[0], a5[1], a11[0], a5[1], 0.4, "SENSOR_5V"); n += 1
    add_track(board, a11[0], a5[1], a11[0], a11[1], 0.4, "SENSOR_5V"); n += 1
    n30 = pad_xy(get_pad(fps, "M1000", "N30"))
    add_track(board, n30[0], n30[1], n30[0], 8.0, 0.35, "SENSOR_5V"); n += 1
    add_via(board, n30[0], 8.0, "SENSOR_5V"); n += 1
    add_track(board, n30[0], 8.0, 52.0, 8.0, 0.35, "SENSOR_5V", B_Cu); n += 1
    add_track(board, 52.0, 8.0, 52.0, e38[1], 0.35, "SENSOR_5V", B_Cu); n += 1
    w2 = pad_xy(get_pad(fps, "M1000", "W2"))
    add_track(board, w2[0], w2[1], 5.0, w2[1], 0.35, "SENSOR_5V"); n += 1
    add_via(board, 5.0, w2[1], "SENSOR_5V"); n += 1
    add_track(board, 5.0, w2[1], 5.0, 128.0, 0.35, "SENSOR_5V", B_Cu); n += 1
    add_track(board, 5.0, 128.0, 52.0, 128.0, 0.35, "SENSOR_5V", B_Cu); n += 1
    a = pad_xy(get_pad(fps, "J1", "6"))
    b = pad_xy(get_pad(fps, "J1", "12"))
    add_track(board, a[0], a[1], b[0], a[1], 0.4, "SENSOR_GND"); n += 1
    add_track(board, b[0], a[1], b[0], b[1], 0.4, "SENSOR_GND"); n += 1
    sg = 129.0
    add_track(board, a[0], a[1], a[0], sg, 0.4, "SENSOR_GND"); n += 1
    add_via(board, a[0], sg, "SENSOR_GND"); n += 1
    e39 = pad_xy(get_pad(fps, "M1000", "E39"))
    add_track(board, e39[0], e39[1], 52.0, e39[1], 0.4, "SENSOR_GND"); n += 1
    add_via(board, 52.0, e39[1], "SENSOR_GND"); n += 1
    add_track(board, 52.0, e39[1], 52.0, sg, 0.4, "SENSOR_GND", B_Cu); n += 1
    add_track(board, 52.0, sg, a[0], sg, 0.4, "SENSOR_GND", B_Cu); n += 1
    w1 = pad_xy(get_pad(fps, "M1000", "W1"))
    add_track(board, w1[0], w1[1], 2.5, w1[1], 0.35, "SENSOR_GND"); n += 1
    add_via(board, 2.5, w1[1], "SENSOR_GND"); n += 1
    add_track(board, 2.5, w1[1], 2.5, sg, 0.35, "SENSOR_GND", B_Cu); n += 1
    add_track(board, 2.5, sg, 52.0, sg, 0.35, "SENSOR_GND", B_Cu); n += 1
    return n


def main():
    print("=== fill + selective route v2 ===")
    board = pcbnew.LoadBoard(str(PCB_PATH))
    board.BuildConnectivity()
    before_unc = board.GetConnectivity().GetUnconnectedCount(True)
    before_tracks = len(list(board.GetTracks()))
    print(f"BEFORE tracks={before_tracks} unconnected={before_unc}")

    fps = fp_map(board)
    clear_tracks(board)
    rebuild_zones(board)

    total = 0
    for name, fn in [
        ("power", route_power),
        ("HP outs", route_hp_out),
        ("ADIO outs", route_adio_out),
        ("local sense", route_local_sense),
        ("IGN only", route_ign_only),
        ("CAN", route_can_only),
        ("SENSOR", route_sensor_only),
        ("EN stubs", route_en_stubs),
        ("IS stubs", route_is_stubs),
    ]:
        print(f"Routing {name}...")
        total += fn(board, fps)
    print(f"Added ~{total} copper items")

    print("Filling zones...")
    ZONE_FILLER(board).Fill(board.Zones())
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetIsRuleArea():
            continue
        polys = z.GetFilledPolysList(z.GetLayer())
        oc = polys.OutlineCount() if polys else 0
        print(f"  {z.GetNetname():12s} {pcbnew.LayerName(z.GetLayer())} filled={oc}")

    board.BuildConnectivity()
    after_unc = board.GetConnectivity().GetUnconnectedCount(True)
    ntracks = len([t for t in board.GetTracks() if type(t).__name__ != "PCB_VIA"])
    nvias = len([t for t in board.GetTracks() if type(t).__name__ == "PCB_VIA"])
    print(f"AFTER tracks={ntracks} vias={nvias} unconnected={after_unc}")

    pcbnew.SaveBoard(str(PCB_PATH), board)
    downgrade_to_k8(PCB_PATH)

    with STATUS.open("w") as f:
        f.write(f"before_tracks={before_tracks}\n")
        f.write(f"before_unc={before_unc}\n")
        f.write(f"after_tracks={ntracks}\n")
        f.write(f"after_vias={nvias}\n")
        f.write(f"after_unc={after_unc}\n")
    print("Wrote", STATUS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
