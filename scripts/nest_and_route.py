#!/usr/bin/env python3
"""Nest footprints + route copper for pdmrazora. Save via pcbnew then downgrade to KiCad 8."""
from __future__ import annotations

import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import pcbnew
from pcbnew import (
    VECTOR2I,
    FromMM,
    ToMM,
    PCB_TRACK,
    ZONE,
    F_Cu,
    B_Cu,
    Edge_Cuts,
    SHAPE_POLY_SET,
    ZONE_FILLER,
)

ROOT = Path(__file__).resolve().parents[1]
PCB_PATH = ROOT / "pdmrazora.kicad_pcb"
BACKUP = ROOT / "pdmrazora.kicad_pcb.bak_pre_nest"
FP_BASE = Path("/usr/share/kicad/footprints")

BOARD_W = 125.0
BOARD_H = 105.0

LAYOUT = {
    "M1000": (8.0, 48.0, 0.0),
    "J1": (62.0, BOARD_H - 20.5, 0.0),  # bottom edge, y=84.5
    "J2": (10.0, 70.0, 0.0),
    "F1": (28.0, 68.0, 0.0),
    "D1": (28.0, 78.0, 0.0),
    "C1": (40.0, 68.0, 0.0),
    "C2": (40.0, 75.0, 0.0),
    "R1": (48.0, 58.0, 90.0),
    "R2": (52.0, 58.0, 90.0),
    "U1": (95.0, 42.0, 270.0),
    "U2": (112.0, 42.0, 270.0),
    "U3": (95.0, 58.0, 270.0),
    "U4": (112.0, 58.0, 270.0),
    "R10": (82.0, 38.0, 0.0),
    "C10": (82.0, 42.0, 0.0),
    "R20": (122.0, 38.0, 0.0),
    "C20": (122.0, 42.0, 0.0),
    "R30": (82.0, 54.0, 0.0),
    "C30": (82.0, 58.0, 0.0),
    "R40": (122.0, 54.0, 0.0),
    "C40": (122.0, 58.0, 0.0),
    "U11": (58.0, 28.0, 0.0),
    "U12": (70.0, 28.0, 0.0),
    "U13": (82.0, 28.0, 0.0),
    "U14": (94.0, 28.0, 0.0),
    "U15": (58.0, 40.0, 0.0),
    "U16": (70.0, 40.0, 0.0),
    "U17": (82.0, 40.0, 0.0),
    "U18": (94.0, 40.0, 0.0),
}

ADIO_PASSIVES = {
    11: ("R101", "C101", "R201"),
    12: ("R102", "C102", "R202"),
    13: ("R103", "C103", "R203"),
    14: ("R104", "C104", "R204"),
    15: ("R105", "C105", "R205"),
    16: ("R106", "C106", "R206"),
    17: ("R107", "C107", "R207"),
    18: ("R108", "C108", "R208"),
}

FOOTPRINT_LIBS = {
    "C1": ("Capacitor_SMD.pretty", "C_1210_3225Metric", "100u_50V"),
    "C2": ("Capacitor_SMD.pretty", "C_0805_2012Metric", "100n"),
    "D1": ("Diode_SMD.pretty", "D_SMB", "SMBJ33CA"),
    "F1": ("Fuse.pretty", "Fuseholder_Blade_ATO_Littelfuse_Pudenz_2_Pin", "150A_MEGA_TBD"),
    "R1": ("Resistor_SMD.pretty", "R_0603_1608Metric", "100k"),
    "R2": ("Resistor_SMD.pretty", "R_0603_1608Metric", "10k"),
}
for n in (10, 20, 30, 40):
    FOOTPRINT_LIBS[f"R{n}"] = ("Resistor_SMD.pretty", "R_0603_1608Metric", "2k7")
    FOOTPRINT_LIBS[f"C{n}"] = ("Capacitor_SMD.pretty", "C_0603_1608Metric", "10n")
for n in range(101, 109):
    FOOTPRINT_LIBS[f"R{n}"] = ("Resistor_SMD.pretty", "R_0603_1608Metric", "4k7")
    FOOTPRINT_LIBS[f"C{n}"] = ("Capacitor_SMD.pretty", "C_0603_1608Metric", "10n")
    FOOTPRINT_LIBS[f"R{n + 100}"] = ("Resistor_SMD.pretty", "R_0603_1608Metric", "4k7")


def build_passive_nets():
    out = []
    for n, isense in [(10, "IN_AUX1"), (20, "IN_AUX2"), (30, "IN_AUX3"), (40, "IN_AUX4")]:
        out += [(f"R{n}", "1", "GND"), (f"R{n}", "2", isense), (f"C{n}", "1", isense), (f"C{n}", "2", "GND")]
    mapping = [
        (101, "IN_MAP1", "ADIO1"),
        (102, "IN_MAP2", "ADIO2"),
        (103, "IN_MAP3", "ADIO3"),
        (104, "IN_O2S", "ADIO4"),
        (105, "IN_O2S2", "ADIO5"),
        (106, "IN_RES1", "ADIO6"),
        (107, "IN_RES2", "ADIO7"),
        (108, "IN_RES3", "ADIO8"),
    ]
    for n, isense, adio in mapping:
        out += [
            (f"R{n}", "1", "GND"),
            (f"R{n}", "2", isense),
            (f"C{n}", "1", isense),
            (f"C{n}", "2", "GND"),
            (f"R{n + 100}", "1", "SENSOR_5V"),
            (f"R{n + 100}", "2", adio),
        ]
    out += [
        ("F1", "1", "VBAT"),
        ("F1", "2", "VBAT"),
        ("D1", "1", "VBAT"),
        ("D1", "2", "GND"),
        ("C1", "1", "VBAT"),
        ("C1", "2", "GND"),
        ("C2", "1", "VBAT"),
        ("C2", "2", "GND"),
        ("R1", "1", "IGN_SW"),
        ("R1", "2", "IN_VIGN"),
        ("R2", "1", "IN_VIGN"),
        ("R2", "2", "GND"),
    ]
    return out


PASSIVE_NETS = build_passive_nets()

def iter_footprints(board):
    for fp in board.GetFootprints():
        if hasattr(fp, "GetReference"):
            yield fp
        else:
            yield pcbnew.Cast_to_FOOTPRINT(fp)


def mm(x, y=None):
    if y is None:
        return FromMM(x)
    return VECTOR2I(FromMM(x), FromMM(y))


def load_fp(pretty, name):
    fp = pcbnew.FootprintLoad(str(FP_BASE / pretty), name)
    if fp is None:
        raise RuntimeError(f"Cannot load {pretty}:{name}")
    return fp


def ensure_net(board, name):
    ni = board.FindNet(name)
    if ni is not None and ni.GetNetCode() > 0:
        return ni
    ni = pcbnew.NETINFO_ITEM(board, name)
    board.Add(ni)
    return ni


def set_pad_net(board, fp, pin, netname):
    ni = ensure_net(board, netname)
    for pad in fp.Pads():
        if pad.GetNumber() == pin:
            pad.SetNet(ni)


def fix_j2_pads(fp):
    pads = sorted([p for p in fp.Pads() if p.GetNumber() in ("1", "2")], key=lambda p: p.GetNumber())
    if len(pads) < 2:
        return
    pads[0].SetFPRelativePosition(mm(0, 0))
    pads[1].SetFPRelativePosition(mm(0, 2.54))


def place_fp(fp, x, y, rot):
    fp.SetPosition(mm(x, y))
    fp.SetOrientation(pcbnew.EDA_ANGLE(rot, pcbnew.DEGREES_T))


def add_edge_cuts(board, w, h):
    for d in list(board.GetDrawings()):
        if d.GetLayer() == Edge_Cuts:
            board.Remove(d)

    def add_line(x1, y1, x2, y2):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetLayer(Edge_Cuts)
        seg.SetStart(mm(x1, y1))
        seg.SetEnd(mm(x2, y2))
        seg.SetWidth(FromMM(0.1))
        board.Add(seg)

    add_line(0, 0, w, 0)
    add_line(w, 0, w, h)
    add_line(w, h, 0, h)
    add_line(0, h, 0, 0)


def add_track(board, x1, y1, x2, y2, width_mm, netname, layer=F_Cu):
    if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
        return
    ni = ensure_net(board, netname)
    tr = PCB_TRACK(board)
    tr.SetStart(mm(x1, y1))
    tr.SetEnd(mm(x2, y2))
    tr.SetWidth(FromMM(width_mm))
    tr.SetLayer(layer)
    tr.SetNet(ni)
    board.Add(tr)


def pad_center_mm(pad):
    p = pad.GetPosition()
    return ToMM(p.x), ToMM(p.y)


def collect_net_points(board, netname):
    pts = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            if pad.GetNumber() == "":
                continue
            if pad.GetNetname() != netname:
                continue
            x, y = pad_center_mm(pad)
            pts.append((x, y, ref))
    # dedupe
    uniq = []
    for x, y, ref in pts:
        if any(abs(x - ux) < 0.2 and abs(y - uy) < 0.2 for ux, uy, _ in uniq):
            continue
        uniq.append((x, y, ref))
    return uniq


def route_manhattan(board, x1, y1, x2, y2, width, net, layer=F_Cu):
    if abs(x1 - x2) < 0.05 and abs(y1 - y2) < 0.05:
        return
    add_track(board, x1, y1, x2, y1, width, net, layer)
    add_track(board, x2, y1, x2, y2, width, net, layer)


def route_net_star(board, netname, width, layer=F_Cu, prefer_refs=None):
    pts = collect_net_points(board, netname)
    if len(pts) < 2:
        return 0
    connected = set()
    if prefer_refs:
        for i, (_, _, ref) in enumerate(pts):
            if ref in prefer_refs:
                connected.add(i)
                break
    if not connected:
        connected.add(0)
    routed = 0
    while len(connected) < len(pts):
        best = None
        for i in connected:
            x1, y1, _ = pts[i]
            for j, (x2, y2, _) in enumerate(pts):
                if j in connected:
                    continue
                d = abs(x1 - x2) + abs(y1 - y2)
                if best is None or d < best[0]:
                    best = (d, i, j)
        if best is None:
            break
        _, i, j = best
        x1, y1, _ = pts[i]
        x2, y2, _ = pts[j]
        route_manhattan(board, x1, y1, x2, y2, width, netname, layer)
        connected.add(j)
        routed += 1
    return routed


def clear_tracks(board):
    for t in list(board.GetTracks()):
        board.Remove(t)


def clear_copper_zones(board):
    for z in list(board.Zones()):
        if not z.GetIsRuleArea():
            board.Remove(z)


def add_rect_zone(board, netname, layer, x1, y1, x2, y2, clearance=0.2, min_thickness=0.25):
    ni = ensure_net(board, netname)
    z = ZONE(board)
    z.SetNet(ni)
    z.SetLayer(layer)
    z.SetIsRuleArea(False)
    z.SetLocalClearance(FromMM(clearance))
    z.SetMinThickness(FromMM(min_thickness))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    poly = SHAPE_POLY_SET()
    poly.NewOutline()
    for x, y in [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]:
        c = mm(x, y)
        poly.Append(c.x, c.y)
    z.SetOutline(poly)
    board.Add(z)
    return z


def add_keepout_no_pour(board, x1, y1, x2, y2):
    z = ZONE(board)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(False)
    z.SetDoNotAllowVias(False)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowCopperPour(True)
    z.SetDoNotAllowFootprints(False)
    z.SetLayerSet(pcbnew.LSET.AllCuMask())
    poly = SHAPE_POLY_SET()
    poly.NewOutline()
    for x, y in [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]:
        c = mm(x, y)
        poly.Append(c.x, c.y)
    z.SetOutline(poly)
    board.Add(z)
    return z


def count_open_nets(board):
    """Estimate unconnected ratsnest edges ignoring zones (tracks only)."""
    pads_by_net = defaultdict(list)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNumber() == "":
                continue
            n = pad.GetNetname()
            if n:
                pads_by_net[n].append(pad_center_mm(pad))

    open_nets = []
    unc = 0
    for net, pts in pads_by_net.items():
        if len(pts) < 2:
            continue
        # union-find on pad centers + track ends
        parent = {}

        def key(pt, tol=0.4):
            return (round(pt[0] / tol), round(pt[1] / tol))

        def find(a):
            parent.setdefault(a, a)
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        pad_keys = [key(p) for p in pts]
        for k in pad_keys:
            parent.setdefault(k, k)

        for t in board.GetTracks():
            if t.GetNetname() != net:
                continue
            # PCB_VIA is a subclass; duck-type via GetStart==GetEnd or class name
            cls = type(t).__name__
            if cls == "PCB_VIA" or (hasattr(t, "GetStart") and t.GetStart() == t.GetEnd()):
                pos = t.GetPosition() if hasattr(t, "GetPosition") else t.GetStart()
                vx, vy = ToMM(pos.x), ToMM(pos.y)
                k = key((vx, vy))
                parent.setdefault(k, k)
                for px, py in pts:
                    if abs(px - vx) < 0.6 and abs(py - vy) < 0.6:
                        union(key((px, py)), k)
                continue
            a = key((ToMM(t.GetStart().x), ToMM(t.GetStart().y)))
            b = key((ToMM(t.GetEnd().x), ToMM(t.GetEnd().y)))
            union(a, b)
            for end in (t.GetStart(), t.GetEnd()):
                ex, ey = ToMM(end.x), ToMM(end.y)
                for px, py in pts:
                    if abs(px - ex) < 0.6 and abs(py - ey) < 0.6:
                        union(key((px, py)), key((ex, ey)))

        roots = {find(k) for k in pad_keys}
        comps = len(roots)
        if comps > 1:
            unc += comps - 1
            open_nets.append((net, comps, len(pts)))
    return unc, open_nets


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



def main():
    print("=== pdmrazora nest + route ===")
    shutil.copy(PCB_PATH, BACKUP)

    # ---- Phase 1: place ----
    board = pcbnew.LoadBoard(str(PCB_PATH))
    before_unc, before_open = count_open_nets(board)
    print(f"BEFORE unconnected~{before_unc} open_nets={len(before_open)}")

    fps = {}
    for fp in board.GetFootprints():
        fps[fp.GetReference()] = fp
    if "J2" in fps:
        fix_j2_pads(fps["J2"])

    for ref, (pretty, name, value) in FOOTPRINT_LIBS.items():
        if ref in fps:
            continue
        print(f"Adding {ref}")
        fp = load_fp(pretty, name)
        fp.SetReference(ref)
        fp.SetValue(value)
        board.Add(fp)
        fps[ref] = fp

    layout = dict(LAYOUT)
    for unum, (rr, cc, rp) in ADIO_PASSIVES.items():
        ux, uy, _ = layout[f"U{unum}"]
        layout[rr] = (ux - 6.0, uy - 3.5, 0.0)
        layout[cc] = (ux - 6.0, uy, 0.0)
        layout[rp] = (ux + 6.0, uy - 3.5, 0.0)

    for ref, (x, y, rot) in layout.items():
        place_fp(fps[ref], x, y, rot)
        if ref == "M1000":
            fps[ref].SetValue("Module:mega-mcu144/0.7")

    fix_j2_pads(fps["J2"])
    set_pad_net(board, fps["J2"], "1", "VBAT")
    set_pad_net(board, fps["J2"], "2", "GND")
    for ref, pin, net in PASSIVE_NETS:
        set_pad_net(board, fps[ref], pin, net)

    add_edge_cuts(board, BOARD_W, BOARD_H)
    board.GetDesignSettings().SetAuxOrigin(mm(0, BOARD_H))
    clear_tracks(board)
    clear_copper_zones(board)
    mx, my, _ = layout["M1000"]
    add_keepout_no_pour(board, mx - 0.5, my - 40.5, mx + 42.5, my + 0.5)

    placed_tmp = ROOT / "pdmrazora.placed.kicad_pcb"
    pcbnew.SaveBoard(str(placed_tmp), board)
    print(f"Phase1 saved ({len(fps)} footprints)")
    # Release board before subprocess (SWIG lifetime)
    del board
    del fps
    import gc
    gc.collect()

    # ---- Phase 2 in fresh interpreter ----
    import subprocess
    rc = subprocess.call([sys.executable, str(Path(__file__).resolve()), "--route-only",
                          str(placed_tmp), str(before_unc), str(len(before_open))])
    return rc


def route_only(placed_tmp, before_unc, before_open_n):
    layout = dict(LAYOUT)
    for unum, (rr, cc, rp) in ADIO_PASSIVES.items():
        ux, uy, _ = layout[f"U{unum}"]
        layout[rr] = (ux - 6.0, uy - 3.5, 0.0)
        layout[cc] = (ux - 6.0, uy, 0.0)
        layout[rp] = (ux + 6.0, uy - 3.5, 0.0)

    board = pcbnew.LoadBoard(str(placed_tmp))
    print("Routing power...")
    route_net_star(board, "VBAT", 1.5, prefer_refs={"J2", "F1", "U1"})
    route_net_star(board, "GND", 1.0, prefer_refs={"J2", "M1000"})
    for n in range(1, 5):
        route_net_star(board, f"PWR_OUT{n}", 1.2, prefer_refs={f"U{n}", "J1"})
    print("Routing ADIO outs...")
    for n in range(1, 9):
        route_net_star(board, f"ADIO{n}", 0.5, prefer_refs={f"U{10 + n}", "J1"})

    print("Routing control/sense...")
    for net, w in [
        ("OUT_PWM1", 0.25), ("OUT_PWM2", 0.25), ("OUT_PWM3", 0.25), ("OUT_PWM4", 0.25),
        ("OUT_PWM5", 0.25), ("OUT_PWM6", 0.25), ("OUT_PWM7", 0.25), ("OUT_PWM8", 0.25),
        ("OUT_IO5", 0.25), ("OUT_IO6", 0.25), ("OUT_IO7", 0.25), ("OUT_IO8", 0.25),
        ("IN_AUX1", 0.25), ("IN_AUX2", 0.25), ("IN_AUX3", 0.25), ("IN_AUX4", 0.25),
        ("IN_MAP1", 0.25), ("IN_MAP2", 0.25), ("IN_MAP3", 0.25),
        ("IN_O2S", 0.25), ("IN_O2S2", 0.25),
        ("IN_RES1", 0.25), ("IN_RES2", 0.25), ("IN_RES3", 0.25),
        ("CANH", 0.3), ("CANL", 0.3),
        ("SENSOR_5V", 0.4), ("SENSOR_GND", 0.4),
        ("IGN_SW", 0.3), ("IN_VIGN", 0.25),
    ]:
        route_net_star(board, net, w, prefer_refs={"M1000", "J1"})

    print("Adding pours...")
    add_rect_zone(board, "VBAT", F_Cu, 88, 30, 123, 70, clearance=0.3, min_thickness=0.4)
    add_rect_zone(board, "GND", B_Cu, 1, 50, 55, 103, clearance=0.25, min_thickness=0.3)
    add_rect_zone(board, "GND", F_Cu, 1, 50, 50, 85, clearance=0.25, min_thickness=0.3)
    for i, uref in enumerate(["U1", "U2", "U3", "U4"], start=1):
        ux, uy, _ = layout[uref]
        add_rect_zone(board, f"PWR_OUT{i}", F_Cu, ux - 6, uy - 4, ux + 6, uy + 8, clearance=0.25, min_thickness=0.4)

    print("Filling zones...")
    try:
        ZONE_FILLER(board).Fill(board.Zones())
    except Exception as e:
        print("Zone fill warning:", e)

    after_unc, after_open = count_open_nets(board)
    print(f"AFTER unconnected~{after_unc} open_nets={len(after_open)}")
    for net, comps, pads in after_open:
        print(f"  open: {net} islands={comps} pads={pads}")

    pcbnew.SaveBoard(str(PCB_PATH), board)
    downgrade_to_k8(PCB_PATH)

    ntracks = len(list(board.GetTracks()))
    nfps = len(list(board.GetFootprints()))
    status = ROOT / "scripts" / "nest_route_status.txt"
    with status.open("w") as f:
        f.write(f"board_mm={BOARD_W}x{BOARD_H}\n")
        f.write(f"before_unc={before_unc}\n")
        f.write(f"after_unc={after_unc}\n")
        f.write(f"before_open_nets={before_open_n}\n")
        f.write(f"after_open_nets={len(after_open)}\n")
        f.write(f"tracks={ntracks}\n")
        f.write(f"footprints={nfps}\n")
        for net, comps, pads in after_open:
            f.write(f"open\t{net}\t{comps}\t{pads}\n")
    print("Wrote", status)
    print("Done.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--route-only":
        sys.exit(route_only(sys.argv[2], int(sys.argv[3]), int(sys.argv[4])))
    sys.exit(main())
