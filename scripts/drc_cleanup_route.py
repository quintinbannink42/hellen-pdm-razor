#!/usr/bin/env python3
"""Surgical DRC cleanup for pdmrazora: remove conflicted selective copper,
re-route with exclusive lanes, SENSOR_5V PU taps, GND stitches. Keep K8."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pcbnew
from pcbnew import (
    VECTOR2I, FromMM, ToMM, PCB_TRACK, PCB_VIA, F_Cu, B_Cu, ZONE_FILLER,
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


def fp_map(board):
    return {fp.GetReference(): fp for fp in board.GetFootprints()}


def get_pad(fps, ref, num):
    pad = fps[ref].FindPadByNumber(str(num))
    if pad is None:
        raise KeyError(f"{ref}.{num}")
    return pad


def clear_tracks(board):
    tracks = list(board.GetTracks())
    for t in tracks:
        board.Delete(t)


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


def manhattan(board, pts, width, net, layer=F_Cu):
    """Add chain of points as Manhattan segments (axis-aligned already expected)."""
    n = 0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if abs(x1 - x2) > 1e-4 and abs(y1 - y2) > 1e-4:
            # force L via intermediate
            add_track(board, x1, y1, x2, y1, width, net, layer); n += 1
            add_track(board, x2, y1, x2, y2, width, net, layer); n += 1
        else:
            add_track(board, x1, y1, x2, y2, width, net, layer); n += 1
    return n


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
    assert "20240108" in head
    assert 'generator_version "8.0"' in head


# ---------------------------------------------------------------------------
# Routing — exclusive lanes, avoid pin-row shorts
# ---------------------------------------------------------------------------

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
    # bottom VBAT link into HP island (stay south of J1 PWR lanes)
    add_track(board, f1b[0], f1b[1], f1b[0], 126.0, 1.2, "VBAT"); n += 1
    add_track(board, f1b[0], 126.0, 95.0, 126.0, 1.2, "VBAT"); n += 1
    add_track(board, 95.0, 126.0, 95.0, 100.0, 1.2, "VBAT"); n += 1
    # GND entry
    j2g = pad_xy(get_pad(fps, "J2", "2"))
    d1g = pad_xy(get_pad(fps, "D1", "2"))
    c1g = pad_xy(get_pad(fps, "C1", "2"))
    add_track(board, j2g[0], j2g[1], d1g[0], j2g[1], 1.2, "GND"); n += 1
    add_track(board, d1g[0], j2g[1], d1g[0], d1g[1], 1.2, "GND"); n += 1
    add_via(board, j2g[0] + 2.5, j2g[1], "GND"); n += 1
    add_track(board, c1g[0], c1g[1], c1g[0], 102.0, 0.5, "GND"); n += 1
    add_via(board, c1g[0], 102.0, "GND"); n += 1
    # HP dual VBAT pads — short bar only on VBAT pads (not into OUT)
    for uref in ["U1", "U2", "U3", "U4"]:
        pts = []
        for p in list(fps[uref].Pads()):
            if p.GetNumber() == "4" and p.GetNetname() == "VBAT":
                pts.append(pad_xy(p))
        if len(pts) >= 2:
            add_track(board, pts[0][0], pts[0][1], pts[1][0], pts[1][1], 0.8, "VBAT"); n += 1
        elif len(pts) == 1:
            x, y = pts[0]
            add_track(board, x, y, x, y - 1.5, 0.8, "VBAT"); n += 1
    # ADIO VBAT stubs into supply strips (short vertical only)
    for uref in ["U11", "U12", "U13", "U14"]:
        px, py = pad_xy(get_pad(fps, uref, "15"))
        add_track(board, px, py, px, 10.0, 0.5, "VBAT"); n += 1
    for uref in ["U15", "U16", "U17", "U18"]:
        px, py = pad_xy(get_pad(fps, uref, "15"))
        add_track(board, px, py, px, 35.5, 0.5, "VBAT"); n += 1
    # M1000 VBAT N27
    mx, my = pad_xy(get_pad(fps, "M1000", "N27"))
    add_track(board, mx, my, mx, 9.0, 0.5, "VBAT"); n += 1
    add_via(board, mx, 9.0, "VBAT"); n += 1
    add_track(board, mx, 9.0, 60.0, 9.0, 0.5, "VBAT", B_Cu); n += 1
    add_via(board, 60.0, 9.0, "VBAT"); n += 1
    add_track(board, 60.0, 9.0, 60.0, 10.0, 0.5, "VBAT"); n += 1
    return n



def route_hp_out(board, fps):
    """OUT pads narrow bar; escape NORTH; B.Cu corridors; short F stubs at unique J1 vias."""
    n = 0
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
            # B to a via just south of the pad (unique), short F stub only — no shared F columns
            via_y = jy + 1.4
            add_track(board, mid_x, target_y, jx, target_y, 0.8, net, B_Cu); n += 1
            add_track(board, jx, target_y, jx, via_y, 0.8, net, B_Cu); n += 1
            add_via(board, jx, via_y, net); n += 1
            add_track(board, jx, via_y, jx, jy, 0.6, net); n += 1
    return n


def route_adio_out(board, fps):
    """Local F; via south of EN zone (y>=50); B corridors clear of EN/PWR; F stub at J1."""
    n = 0
    # Left bank far-left of J1; right bank far-right — clear of PWR mid_x 64/86/108/130
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
        if not (y0 <= ry <= y1):
            add_track(board, ox, ry, ox, max(y0, min(y1, ry)), 0.3, net); n += 1
        # F descend/ascend to via_y >= 50 (south of EN B horizontals at y=18..36)
        via_y = 50.5 + (idx % 4) * 0.6
        add_track(board, ox, y1 if idx >= 4 else y0, ox, via_y, 0.3, net); n += 1
        add_track(board, ox, via_y, cx, via_y, 0.3, net); n += 1
        add_via(board, cx, via_y, net); n += 1
        jx, jy = pad_xy(get_pad(fps, "J1", jpin))
        ap_y = 113.0 + idx * 0.65
        add_track(board, cx, via_y, cx, ap_y, 0.3, net, B_Cu); n += 1
        add_track(board, cx, ap_y, jx, ap_y, 0.3, net, B_Cu); n += 1
        stub_y = jy + 1.3
        add_track(board, jx, ap_y, jx, stub_y, 0.3, net, B_Cu); n += 1
        add_via(board, jx, stub_y, net); n += 1
        add_track(board, jx, stub_y, jx, jy, 0.3, net); n += 1
    return n


def route_local_sense(board, fps):
    """IS pin → sense R/C without crossing EN."""
    n = 0
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
    return n


def route_en(board, fps):
    """EN via away from IS; B columns in x=63.5–72.5 (east of ADIO corridors 55–59.5)."""
    n = 0
    pairs = [
        # B columns west of ADIO corridors (55–59.5) and PWR mid_x (64+)
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
        # via on column at pad Y; F stub east into M1000 E pad (mx≈50)
        add_via(board, col, my, net); n += 1
        add_track(board, col, my, mx, my, 0.25, net); n += 1
    return n


def route_is(board, fps):
    """Sense R → exclusive B lanes south of module to M1000 S pads."""
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
        vx, vy = sx + 1.0, sy + 1.8
        add_track(board, sx, sy, sx, vy, 0.25, net); n += 1
        add_track(board, sx, vy, vx, vy, 0.25, net); n += 1
        add_via(board, vx, vy, net); n += 1
        hwy = 55.0 + idx * 0.8
        col = 44.0 + (idx % 12) * 0.8
        add_track(board, vx, vy, col, vy, 0.25, net, B_Cu); n += 1
        add_track(board, col, vy, col, hwy, 0.25, net, B_Cu); n += 1
        add_track(board, col, hwy, mx, hwy, 0.25, net, B_Cu); n += 1
        add_via(board, mx, hwy, net); n += 1
        add_track(board, mx, hwy, mx, my, 0.25, net); n += 1
    return n


def route_ign_can(board, fps):
    n = 0
    jign = pad_xy(get_pad(fps, "J1", "4"))
    r1a = pad_xy(get_pad(fps, "R1", "1"))
    r1b = pad_xy(get_pad(fps, "R1", "2"))
    r2a = pad_xy(get_pad(fps, "R2", "1"))
    mx, my = pad_xy(get_pad(fps, "M1000", "N26"))
    add_track(board, jign[0], jign[1], jign[0], r1a[1], 0.4, "IGN_SW"); n += 1
    add_track(board, jign[0], r1a[1], r1a[0], r1a[1], 0.4, "IGN_SW"); n += 1
    add_track(board, r1b[0], r1b[1], r2a[0], r1b[1], 0.3, "IN_VIGN"); n += 1
    add_track(board, r2a[0], r1b[1], r2a[0], r2a[1], 0.3, "IN_VIGN"); n += 1
    # IN_VIGN on B along top edge y=3.5 — clear of SENSOR_5V bus at y=5.5
    add_track(board, r1b[0], r1b[1], 58.0, r1b[1], 0.3, "IN_VIGN"); n += 1
    add_via(board, 58.0, r1b[1], "IN_VIGN"); n += 1
    add_track(board, 58.0, r1b[1], 58.0, 3.5, 0.3, "IN_VIGN", B_Cu); n += 1
    add_track(board, 58.0, 3.5, mx, 3.5, 0.3, "IN_VIGN", B_Cu); n += 1
    add_via(board, mx, 3.5, "IN_VIGN"); n += 1
    add_track(board, mx, 3.5, mx, my, 0.3, "IN_VIGN"); n += 1
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


def route_sensor(board, fps):
    """SENSOR_5V top bus + left-edge riser (no mid-board spine); PU taps; SENSOR_GND."""
    n = 0
    bus_y = 5.5  # top B bus for PU
    e38 = pad_xy(get_pad(fps, "M1000", "E38"))
    # E38 → north to bus (short), not south through channel
    add_track(board, e38[0], e38[1], e38[0], 40.0, 0.35, "SENSOR_5V"); n += 1
    add_track(board, e38[0], 40.0, 4.0, 40.0, 0.35, "SENSOR_5V"); n += 1
    add_via(board, 4.0, 40.0, "SENSOR_5V"); n += 1
    add_track(board, 4.0, 40.0, 4.0, bus_y, 0.35, "SENSOR_5V", B_Cu); n += 1
    add_track(board, 4.0, bus_y, 145.0, bus_y, 0.4, "SENSOR_5V", B_Cu); n += 1
    # left-edge riser to bottom for J1
    add_track(board, 4.0, 40.0, 4.0, 128.5, 0.35, "SENSOR_5V", B_Cu); n += 1
    add_track(board, 4.0, 128.5, 140.0, 128.5, 0.35, "SENSOR_5V", B_Cu); n += 1
    for i, jp in enumerate(("5", "11")):
        jx, jy = pad_xy(get_pad(fps, "J1", jp))
        ex = 136.0 - i * 1.5
        add_via(board, ex, 128.5, "SENSOR_5V"); n += 1
        add_track(board, ex, 128.5, ex, jy, 0.35, "SENSOR_5V"); n += 1
        add_track(board, ex, jy, jx, jy, 0.35, "SENSOR_5V"); n += 1
    a5 = pad_xy(get_pad(fps, "J1", "5"))
    a11 = pad_xy(get_pad(fps, "J1", "11"))
    add_track(board, a5[0], a5[1], a11[0], a5[1], 0.35, "SENSOR_5V"); n += 1
    add_track(board, a11[0], a5[1], a11[0], a11[1], 0.35, "SENSOR_5V"); n += 1
    # N30 / W2 into left-edge / top bus
    n30 = pad_xy(get_pad(fps, "M1000", "N30"))
    add_track(board, n30[0], n30[1], n30[0], bus_y + 2.0, 0.3, "SENSOR_5V"); n += 1
    add_via(board, n30[0], bus_y + 2.0, "SENSOR_5V"); n += 1
    add_track(board, n30[0], bus_y + 2.0, n30[0], bus_y, 0.3, "SENSOR_5V", B_Cu); n += 1
    add_track(board, n30[0], bus_y, 4.0, bus_y, 0.3, "SENSOR_5V", B_Cu); n += 1
    w2 = pad_xy(get_pad(fps, "M1000", "W2"))
    add_track(board, w2[0], w2[1], 4.0, w2[1], 0.3, "SENSOR_5V"); n += 1
    add_via(board, 4.0, w2[1], "SENSOR_5V"); n += 1
    add_track(board, 4.0, w2[1], 4.0, bus_y, 0.3, "SENSOR_5V", B_Cu); n += 1

    # PU taps R201–R208
    for r in range(201, 209):
        rx, ry = pad_xy(get_pad(fps, f"R{r}", "1"))
        side = rx - 2.4  # west of PU, clear of ADIO OUT bar to the east
        add_track(board, rx, ry, side, ry, 0.3, "SENSOR_5V"); n += 1
        add_via(board, side, ry, "SENSOR_5V"); n += 1
        add_track(board, side, ry, side, bus_y, 0.3, "SENSOR_5V", B_Cu); n += 1

    # SENSOR_GND — left edge, staggered from SENSOR_5V
    a = pad_xy(get_pad(fps, "J1", "6"))
    b = pad_xy(get_pad(fps, "J1", "12"))
    add_track(board, a[0], a[1], b[0], a[1], 0.35, "SENSOR_GND"); n += 1
    add_track(board, b[0], a[1], b[0], b[1], 0.35, "SENSOR_GND"); n += 1
    sg = 129.8
    add_track(board, a[0], a[1], a[0], sg, 0.35, "SENSOR_GND"); n += 1
    add_via(board, a[0], sg, "SENSOR_GND"); n += 1
    e39 = pad_xy(get_pad(fps, "M1000", "E39"))
    add_track(board, e39[0], e39[1], e39[0], 42.0, 0.35, "SENSOR_GND"); n += 1
    add_track(board, e39[0], 42.0, 2.0, 42.0, 0.35, "SENSOR_GND"); n += 1
    add_via(board, 2.0, 42.0, "SENSOR_GND"); n += 1
    add_track(board, 2.0, 42.0, 2.0, sg, 0.35, "SENSOR_GND", B_Cu); n += 1
    add_track(board, 2.0, sg, a[0], sg, 0.35, "SENSOR_GND", B_Cu); n += 1
    w1 = pad_xy(get_pad(fps, "M1000", "W1"))
    add_track(board, w1[0], w1[1], 2.0, w1[1], 0.3, "SENSOR_GND"); n += 1
    add_via(board, 2.0, w1[1], "SENSOR_GND"); n += 1
    add_track(board, 2.0, w1[1], 2.0, sg, 0.3, "SENSOR_GND", B_Cu); n += 1
    return n


def stitch_gnd(board, fps):
    """Via WEST of discrete GND pads into B.Cu (away from ADIO OUT bars)."""
    n = 0
    targets = []

    def collect_gnd(ref):
        if ref not in fps:
            return
        for pad in list(fps[ref].Pads()):
            if pad.GetNetname() == "GND":
                targets.append(pad_xy(pad))

    for r in [10, 20, 30, 40, 101, 102, 103, 104, 105, 106, 107, 108, 2]:
        collect_gnd(f"R{r}")
    for c in [10, 20, 30, 40, 101, 102, 103, 104, 105, 106, 107, 108, 1, 2]:
        collect_gnd(f"C{c}")
    seen = set()
    for x, y in targets:
        key = (round(x, 2), round(y, 2))
        if key in seen:
            continue
        seen.add(key)
        # due west of pad — clear of ADIO vertical bars to the east of R/C
        vx, vy = x - 1.3, y
        add_track(board, x, y, vx, vy, 0.3, "GND"); n += 1
        add_via(board, vx, vy, "GND"); n += 1
    for x, y in [
        (20, 100), (40, 100), (55, 95), (70, 110),
        (95, 75), (105, 75), (95, 95), (120, 95),
        (80, 55), (100, 55), (120, 55), (30, 90),
    ]:
        add_via(board, x, y, "GND"); n += 1
    return n




def main():
    print("=== DRC cleanup selective re-route ===")
    board = pcbnew.LoadBoard(str(PCB_PATH))
    board.BuildConnectivity()
    before_unc = board.GetConnectivity().GetUnconnectedCount(True)
    before_tracks = len([t for t in board.GetTracks() if type(t).__name__ != "PCB_VIA"])
    before_vias = len([t for t in board.GetTracks() if type(t).__name__ == "PCB_VIA"])
    print(f"BEFORE tracks={before_tracks} vias={before_vias} unconnected={before_unc}")

    fps = fp_map(board)
    # Do not touch HELLCORE / M1000 footprint — only copper
    clear_tracks(board)

    total = 0
    for name, fn in [
        ("power", route_power),
        ("HP outs", route_hp_out),
        ("ADIO outs", route_adio_out),
        ("local sense", route_local_sense),
        ("EN", route_en),
        ("IS", route_is),
        ("IGN/CAN", route_ign_can),
        ("SENSOR+PU", route_sensor),
        ("GND stitch", stitch_gnd),
    ]:
        print(f"Routing {name}...")
        total += fn(board, fps)
    print(f"Added ~{total} copper items")

    print("Filling zones...")
    ZONE_FILLER(board).Fill(board.Zones())
    filled = 0
    for i in range(board.GetAreaCount()):
        z = board.GetArea(i)
        if z.GetIsRuleArea():
            continue
        polys = z.GetFilledPolysList(z.GetLayer())
        oc = polys.OutlineCount() if polys else 0
        if oc:
            filled += 1
        print(f"  {z.GetNetname():12s} {pcbnew.LayerName(z.GetLayer())} filled={oc}")

    board.BuildConnectivity()
    after_unc = board.GetConnectivity().GetUnconnectedCount(True)
    ntracks = len([t for t in board.GetTracks() if type(t).__name__ != "PCB_VIA"])
    nvias = len([t for t in board.GetTracks() if type(t).__name__ == "PCB_VIA"])
    print(f"AFTER tracks={ntracks} vias={nvias} unconnected={after_unc} zones_filled={filled}")

    pcbnew.SaveBoard(str(PCB_PATH), board)
    downgrade_to_k8(PCB_PATH)

    with STATUS.open("w") as f:
        f.write(f"before_tracks={before_tracks}\n")
        f.write(f"before_vias={before_vias}\n")
        f.write(f"before_unc={before_unc}\n")
        f.write(f"after_tracks={ntracks}\n")
        f.write(f"after_vias={nvias}\n")
        f.write(f"after_unc={after_unc}\n")
        f.write(f"zones_with_fill={filled}\n")
        f.write("strategy=drc_cleanup_exclusive_lanes_sensor5v_gnd_stitch_k8\n")
    print("Wrote", STATUS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
