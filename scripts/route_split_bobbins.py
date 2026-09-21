#!/usr/bin/env python3
"""Critical-net copper on the split-bobbin 104×93 PowerCore (pdmrazora).

Mechanical placement from PR #9 is unchanged. Old 150×130 / paired-M6 copper
scripts are not replayed. SENSOR_GND is not bonded. HELLCORE is not touched.

Layer policy (quiet west / power east, vertical SuperSeal EMI wall):
  - VBAT: F.Cu islands J2 / post-fuse / HP tabs / ADIO; B.Cu J2 + post-fuse +
    east alley that stops north of EN; module N27 via north corridor only
  - GND: B.Cu full-board pour + F.Cu island around J3; stitch vias; no SENSOR pour
  - EN: exclusive B.Cu MCU–J1 gap columns + south-of-J1 / pin-south highways
  - IS: local F.Cu U–R–C; F.Cu long-haul (EN stays on B)
  - PWR_OUT / ADIO: stay east of the SuperSeal pin field except J1 landings
"""
from __future__ import annotations

import math
import re
import sys
import uuid
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "pdmrazora.kicad_pcb"
STATUS = ROOT / "scripts" / "copper_status.txt"
LEFTOVER = ROOT / "scripts" / "unconnected_leftover.txt"

BOARD_W, BOARD_H = 104.0, 93.0
CLR = 0.22

NET_CODE: dict[str, int] = {}
NET_NAME: dict[int, str] = {}

# MCU–J1 gap columns (EN B.Cu). Courtyard west edge ≈44.7; E pads at x=44.
EN_GAP_X = [45.15 + i * 0.40 for i in range(12)]
# South-of-J1 EN highways (y > courtyard 66.25), before ADIO bodies fully pack.
EN_ADIO_HWY = [66.70 + i * 0.38 for i in range(8)]  # 66.70 … 69.36
# IS F.Cu south-west of J3 (pad r=8 at 92,82). Stay x≤82.5, y≥88.2.
# Staircase: sy increases (south) while col decreases (west) so H buses do not
# cross later nets' northbound verticals.
IS_SOUTH_Y = [88.30 + i * 0.28 for i in range(12)]
IS_COL = [38.60 - i * 0.42 for i in range(12)]  # eastmost for northernmost highway
IS_APP_Y = [67.10 + i * 0.28 for i in range(12)]  # unique approach south of M1000 S pads
# PWR_OUT / ADIO unique columns east of pin field (x≳65.2) west of U1 (~76).
PWR_COL = [66.30, 67.90, 69.50, 71.10]
ADIO_COL = [65.40 + i * 0.82 for i in range(8)]


def uid(tag: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pdmrazora-split-route/{tag}"))


def rot_xy(ox, oy, rot, lx, ly):
    r = math.radians(rot)
    c, s = math.cos(r), math.sin(r)
    return ox + lx * c - ly * s, oy + lx * s + ly * c


def extract_top_items(body: str) -> list[str]:
    items, i, n = [], 0, len(body)
    while i < n:
        while i < n and body[i] in " \t\n\r":
            i += 1
        if i >= n:
            break
        if body[i] != "(":
            raise RuntimeError(f"expected '(' at {i}: {body[i:i+40]!r}")
        depth, start, in_str = 0, i, False
        while i < n:
            ch = body[i]
            if in_str:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == '"':
                    in_str = False
                i += 1
                continue
            if ch == '"':
                in_str = True
                i += 1
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    i += 1
                    items.append(body[start:i].strip("\n"))
                    break
            i += 1
        else:
            raise RuntimeError("unbalanced sexp")
    return items


def item_head(item: str) -> str:
    m = re.match(r"\s*\(([^\s\n]+)", item)
    return m.group(1) if m else ""


def fp_ref(item: str) -> str | None:
    m = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', item)
    return m.group(1) if m else None


def parse_at(item: str) -> tuple[float, float, float]:
    m = re.search(r"^\s*\(at ([0-9eE+.\-]+) ([0-9eE+.\-]+)(?: ([0-9eE+.\-]+))?\)", item, re.M)
    if not m:
        raise RuntimeError("no (at) in footprint")
    return float(m.group(1)), float(m.group(2)), float(m.group(3) or 0.0)


class Pad:
    __slots__ = ("ref", "num", "x", "y", "net", "layers", "sx", "sy", "kind")

    def __init__(self, ref, num, x, y, net, layers, sx, sy, kind):
        self.ref, self.num = ref, num
        self.x, self.y = x, y
        self.net = net
        self.layers = layers
        self.sx, self.sy = sx, sy
        self.kind = kind


def parse_pads(item: str, ref: str) -> list[Pad]:
    ox, oy, rot = parse_at(item)
    pads: list[Pad] = []
    for m in re.finditer(
        r'\(pad "([^"]*)" (thru_hole|smd|np_thru_hole)[^\n]*\n'
        r"\s*\(at ([0-9eE+.\-]+) ([0-9eE+.\-]+)(?: [0-9eE+.\-]+)?\)\n"
        r"\s*\(size ([0-9eE+.\-]+) ([0-9eE+.\-]+)\)"
        r"([\s\S]*?)(?=\n\t\t\(pad |\n\t\t\(embedded|\n\t\t\(model |\n\t\t\(zone |\n\t\))",
        item,
    ):
        num, kind = m.group(1), m.group(2)
        if kind == "np_thru_hole" or num == "":
            continue
        lx, ly = float(m.group(3)), float(m.group(4))
        sx, sy = float(m.group(5)), float(m.group(6))
        rest = m.group(7)
        lm = re.search(r'\(layers "([^"]+)"(?: "([^"]+)")?(?: "([^"]+)")?\)', rest)
        layers = " ".join(g for g in lm.groups() if g) if lm else ""
        nm = re.search(r'\(net \d+ "([^"]*)"\)', rest)
        net = nm.group(1) if nm else ""
        x, y = rot_xy(ox, oy, rot, lx, ly)
        pads.append(Pad(ref, num, x, y, net, layers, sx, sy, kind))
    return pads


def seg_block(x1, y1, x2, y2, width, layer, net, tag):
    if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
        return ""
    code = NET_CODE[net]
    return (
        "\t(segment\n"
        f"\t\t(start {x1:.4f} {y1:.4f})\n"
        f"\t\t(end {x2:.4f} {y2:.4f})\n"
        f"\t\t(width {width:g})\n"
        f'\t\t(layer "{layer}")\n'
        f"\t\t(net {code})\n"
        f'\t\t(uuid "{uid(tag)}")\n'
        "\t)\n"
    )


def via_block(x, y, net, tag, size=0.6, drill=0.3):
    code = NET_CODE[net]
    return (
        "\t(via\n"
        f"\t\t(at {x:.4f} {y:.4f})\n"
        f"\t\t(size {size:g})\n"
        f"\t\t(drill {drill:g})\n"
        '\t\t(layers "F.Cu" "B.Cu")\n'
        f"\t\t(net {code})\n"
        f'\t\t(uuid "{uid(tag)}")\n'
        "\t)\n"
    )


def zone_rect(net, net_name, layer, uuid_s, pts, priority=None, keepout=False):
    extra = f"\n\t\t(priority {priority})" if priority is not None else ""
    ko = ""
    if keepout:
        ko = """
		(keepout
			(tracks allowed)
			(vias allowed)
			(pads allowed)
			(copperpour not_allowed)
			(footprints allowed)
		)"""
        layer_line = '(layers "F.Cu" "B.Cu")'
        fill = "(fill no"
    else:
        layer_line = f'(layer "{layer}")'
        fill = "(fill yes"
    xy = " ".join(f"(xy {x:g} {y:g})" for x, y in pts)
    return f'''	(zone
		(net {net})
		(net_name "{net_name}")
		{layer_line}
		(uuid "{uuid_s}")
		(hatch edge 0.5){extra}
		(connect_pads
			(clearance 0.3)
		)
		(min_thickness 0.4)
		(filled_areas_thickness no){ko}
		{fill}
			(thermal_gap 0.5)
			(thermal_bridge_width 0.5)
		)
		(polygon
			(pts
				{xy}
			)
		)
	)'''


class Router:
    def __init__(self):
        self.copper: list[str] = []
        self.nseg = 0
        self.nvia = 0
        self.segs: list[tuple[float, float, float, float, str, str, float]] = []
        self.vias: list[tuple[float, float, str]] = []
        self._i = 0

    def _tag(self, pfx: str) -> str:
        self._i += 1
        return f"{pfx}-{self._i}"

    def track(self, x1, y1, x2, y2, width, net, layer="F.Cu"):
        if abs(x1 - x2) < 1e-4 and abs(y1 - y2) < 1e-4:
            return

        def clamp(x, y):
            return max(0.4, min(BOARD_W - 0.4, x)), max(0.4, min(BOARD_H - 0.4, y))

        x1, y1 = clamp(x1, y1)
        x2, y2 = clamp(x2, y2)
        blk = seg_block(x1, y1, x2, y2, width, layer, net, self._tag(f"s-{net}-{layer}"))
        if not blk:
            return
        self.copper.append(blk)
        self.nseg += 1
        self.segs.append((x1, y1, x2, y2, layer, net, width))

    def via(self, x, y, net, size=None, drill=None):
        if size is None:
            if net == "VBAT":
                size, drill = 0.8, 0.4
            elif net == "GND":
                size, drill = 0.6, 0.3
            else:
                size, drill = 0.45, 0.2
        x = max(0.8, min(BOARD_W - 0.8, x))
        y = max(0.8, min(BOARD_H - 0.8, y))
        self.copper.append(via_block(x, y, net, self._tag(f"v-{net}"), size, drill))
        self.nvia += 1
        self.vias.append((x, y, net))

    def manh(self, pts, width, net, layer="F.Cu"):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if abs(x1 - x2) > 1e-4 and abs(y1 - y2) > 1e-4:
                self.track(x1, y1, x2, y1, width, net, layer)
                self.track(x2, y1, x2, y2, width, net, layer)
            else:
                self.track(x1, y1, x2, y2, width, net, layer)

    def manh_vh(self, pts, width, net, layer="F.Cu"):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if abs(x1 - x2) > 1e-4 and abs(y1 - y2) > 1e-4:
                self.track(x1, y1, x1, y2, width, net, layer)
                self.track(x1, y2, x2, y2, width, net, layer)
            else:
                self.track(x1, y1, x2, y2, width, net, layer)


def pads_of(pads, ref, num) -> Pad:
    hits = [p for p in pads if p.ref == ref and p.num == num]
    if not hits:
        raise KeyError(f"{ref}.{num}")
    hits.sort(key=lambda p: p.sx * p.sy)
    return hits[0]


def pads_named(pads, ref, num) -> list[Pad]:
    return [p for p in pads if p.ref == ref and p.num == num]


def segs_cross_same_layer(s1, s2) -> bool:
    x1, y1, x2, y2, lay1, n1, w1 = s1
    x3, y3, x4, y4, lay2, n2, w2 = s2
    if lay1 != lay2 or n1 == n2:
        return False
    h1 = abs(y1 - y2) < 1e-4
    v1 = abs(x1 - x2) < 1e-4
    h2 = abs(y3 - y4) < 1e-4
    v2 = abs(x3 - x4) < 1e-4
    if h1 and v2:
        y, x = y1, x3
        if min(x1, x2) - 0.01 <= x <= max(x1, x2) + 0.01 and min(y3, y4) - 0.01 <= y <= max(y3, y4) + 0.01:
            return True
    if v1 and h2:
        x, y = x1, y3
        if min(y1, y2) - 0.01 <= y <= max(y1, y2) + 0.01 and min(x3, x4) - 0.01 <= x <= max(x3, x4) + 0.01:
            return True
    return False


def count_crossings(rt: Router) -> list[tuple]:
    hits = []
    segs = rt.segs
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            if segs_cross_same_layer(segs[i], segs[j]):
                hits.append((segs[i][5], segs[j][5], segs[i][4]))
    return hits


def count_via_packs(rt: Router) -> list[tuple]:
    hits = []

    def sz(n):
        if n == "VBAT":
            return 0.8
        if n == "GND":
            return 0.6
        return 0.45

    vias = rt.vias
    for i, (x1, y1, n1) in enumerate(vias):
        for x2, y2, n2 in vias[i + 1 :]:
            need = (sz(n1) + sz(n2)) / 2 + 0.22
            d = math.hypot(x1 - x2, y1 - y2)
            if d + 1e-4 < need:
                hits.append((n1, n2, round(d, 3), round(need, 3)))
    return hits


def rebuild_from_lists(rt: Router, segs, vias):
    rt.copper, rt.segs, rt.vias = [], [], []
    rt.nseg = rt.nvia = 0
    seen = set()
    for x, y, net in vias:
        k = (round(float(x), 3), round(float(y), 3), net)
        if k in seen:
            continue
        seen.add(k)
        rt.via(float(x), float(y), net)
    for x1, y1, x2, y2, lay, net, w in segs:
        rt.track(float(x1), float(y1), float(x2), float(y2), float(w), net, lay)


def apply_hops(rt: Router, max_hops=60) -> int:
    POWER = {"VBAT", "GND"}
    total = 0
    for _ in range(max_hops):
        segs = list(rt.segs)
        vias = list(rt.vias)
        victim = None
        for i, s1 in enumerate(segs):
            for s2 in segs[i + 1 :]:
                if s1[5] in POWER or s2[5] in POWER:
                    continue
                if not segs_cross_same_layer(s1, s2):
                    continue

                def score(s):
                    x1, y1, x2, y2, lay, net, w = s
                    power = net.startswith("PWR_OUT")
                    length = abs(x2 - x1) + abs(y2 - y1)
                    return (1 if power else 0, -length)

                victim = s1 if score(s1) < score(s2) else s2
                break
            if victim:
                break
        if not victim:
            break
        x1, y1, x2, y2, lay, net, w = victim
        other = "F.Cu" if lay == "B.Cu" else "B.Cu"
        segs.remove(victim)
        segs.append((x1, y1, x2, y2, other, net, max(0.2, min(w, 0.35))))
        vias.append((x1, y1, net))
        vias.append((x2, y2, net))
        rebuild_from_lists(rt, segs, vias)
        total += 1
    return total


EN_MAP = [
    ("OUT_PWM1", "U1", ["2"], "E27"),
    ("OUT_PWM2", "U2", ["2"], "E17"),
    ("OUT_PWM3", "U3", ["2"], "E16"),
    ("OUT_PWM4", "U4", ["2"], "E15"),
    ("OUT_PWM5", "U11", ["2", "3"], "E14"),
    ("OUT_PWM6", "U12", ["2", "3"], "E26"),
    ("OUT_PWM7", "U13", ["2", "3"], "E25"),
    ("OUT_PWM8", "U14", ["2", "3"], "E28"),
    ("OUT_IO5", "U15", ["2", "3"], "E7"),
    ("OUT_IO6", "U16", ["2", "3"], "E9"),
    ("OUT_IO7", "U17", ["2", "3"], "E23"),
    ("OUT_IO8", "U18", ["2", "3"], "E22"),
]
IS_LOCAL = [
    ("IN_AUX1", "U1", "3", "R10", "C10"),
    ("IN_AUX2", "U2", "3", "R20", "C20"),
    ("IN_AUX3", "U3", "3", "R30", "C30"),
    ("IN_AUX4", "U4", "3", "R40", "C40"),
    ("IN_MAP1", "U11", "4", "R101", "C101"),
    ("IN_MAP2", "U12", "4", "R102", "C102"),
    ("IN_MAP3", "U13", "4", "R103", "C103"),
    ("IN_O2S", "U14", "4", "R104", "C104"),
    ("IN_O2S2", "U15", "4", "R105", "C105"),
    ("IN_RES1", "U16", "4", "R106", "C106"),
    ("IN_RES2", "U17", "4", "R107", "C107"),
    ("IN_RES3", "U18", "4", "R108", "C108"),
]
IS_LONG = [
    ("IN_AUX1", "R10", "S13"),
    ("IN_AUX2", "R20", "S12"),
    ("IN_AUX3", "R30", "S11"),
    ("IN_AUX4", "R40", "S10"),
    ("IN_MAP1", "R101", "S21"),
    ("IN_MAP2", "R102", "S20"),
    ("IN_MAP3", "R103", "S19"),
    ("IN_O2S", "R104", "S16"),
    ("IN_O2S2", "R105", "S15"),
    ("IN_RES1", "R106", "S17"),
    ("IN_RES2", "R107", "S14"),
    ("IN_RES3", "R108", "S18"),
]
HP_OUT = [
    ("PWR_OUT1", "U1", ["14", "20"]),
    ("PWR_OUT2", "U2", ["1", "8"]),
    ("PWR_OUT3", "U3", ["7", "13"]),
    ("PWR_OUT4", "U4", ["19", "26"]),
]
ADIO_OUT = [
    ("ADIO1", "U11", "21", "R201"),
    ("ADIO2", "U12", "15", "R202"),
    ("ADIO3", "U13", "22", "R203"),
    ("ADIO4", "U14", "16", "R204"),
    ("ADIO5", "U15", "23", "R205"),
    ("ADIO6", "U16", "17", "R206"),
    ("ADIO7", "U17", "24", "R207"),
    ("ADIO8", "U18", "18", "R208"),
]
EN_IS = {e[0] for e in EN_MAP} | {e[0] for e in IS_LOCAL}


def tab_of(P, uref) -> Pad:
    tabs = pads_named(P, uref, "4")
    return max(tabs, key=lambda p: p.sx * p.sy)


def route_power(rt: Router, P):
    """VBAT spine J2 north → fuse → HP tabs / ADIO; GND stitches from J3 south."""
    j2 = max(pads_named(P, "J2", "1"), key=lambda p: p.sx * p.sy)
    j3 = max(pads_named(P, "J3", "1"), key=lambda p: p.sx * p.sy)
    f1a, f1b = pads_of(P, "F1", "1"), pads_of(P, "F1", "2")
    c1p, c1g = pads_of(P, "C1", "1"), pads_of(P, "C1", "2")
    c2p, c2g = pads_of(P, "C2", "1"), pads_of(P, "C2", "2")
    d1p, d1g = pads_of(P, "D1", "1"), pads_of(P, "D1", "2")

    # J2 → F1.1 only (do not pour-bypass the fuse). Wide F spine along y=18 / north pocket.
    rt.manh([(j2.x, j2.y), (j2.x, 18.0), (f1a.x, 18.0), (f1a.x, f1a.y)], 2.0, "VBAT")
    # F1.2 → bulk / TVS / south spine. Post-fuse pour covers F1.2+C2; tracks join C1/D1/HP.
    rt.manh([(f1b.x, f1b.y), (c2p.x, f1b.y), (c2p.x, c2p.y)], 1.0, "VBAT")
    rt.manh([(f1b.x, f1b.y), (c1p.x, f1b.y), (c1p.x, c1p.y)], 0.8, "VBAT")
    rt.manh([(f1b.x, f1b.y), (d1p.x, f1b.y), (d1p.x, d1p.y)], 0.8, "VBAT")

    # East F spine x=88 joins north pocket to HP tabs (gap y=24–32 between F islands).
    spine = 88.0
    rt.track(f1b.x, f1b.y, spine, f1b.y, 1.4, "VBAT")
    rt.track(spine, f1b.y, spine, 38.5, 1.4, "VBAT")
    rt.via(spine, 38.5, "VBAT")
    rt.track(spine, 38.5, spine, 51.5, 1.2, "VBAT", "B.Cu")  # B alley under HP, north of EN south-hwys
    for uref, tap_y in (("U1", 38.5), ("U2", 38.5), ("U3", 51.5), ("U4", 51.5)):
        tab = tab_of(P, uref)
        rt.track(tab.x, tab.y, tab.x, tap_y, 1.0, "VBAT")
        rt.manh([(spine, tap_y), (tab.x, tap_y)], 1.0, "VBAT", "B.Cu")
        rt.via(tab.x, tap_y, "VBAT")

    # HP F island → ADIO F island jumper. Stay east of C30 (x≈80, y=65.5) and
    # north of ADIO columns (x≈65–71).
    rt.track(85.6, 63.8, 85.6, 66.4, 0.9, "VBAT")
    rt.track(85.6, 66.4, 76.0, 66.4, 0.8, "VBAT")
    rt.track(76.0, 66.4, 76.0, 69.5, 0.8, "VBAT")

    # Module VBAT N27 — north corridor only (quiet west, y≈3.4).
    n27 = pads_of(P, "M1000", "N27")
    rt.track(spine, 8.0, spine, 3.4, 0.5, "VBAT")
    rt.via(spine, 3.4, "VBAT")
    rt.manh([(spine, 3.4), (n27.x, 3.4), (n27.x, n27.y)], 0.5, "VBAT", "B.Cu")

    def gnd_stitch(px, py, src=None, w=0.4):
        for vx, vy, n in rt.vias:
            if n == "GND" and (px - vx) ** 2 + (py - vy) ** 2 < 2.2**2:
                if src is not None:
                    rt.track(src.x, src.y, vx, vy, w, "GND")
                return
            if (px - vx) ** 2 + (py - vy) ** 2 < 1.05**2:
                if src is not None:
                    rt.track(src.x, src.y, vx, vy, w, "GND")
                return
        if src is not None:
            rt.track(src.x, src.y, px, py, w, "GND")
        rt.via(px, py, "GND")

    # J3 south bobbin — extra stitches just outside 16 mm Cu, inside GND F island.
    for ang in (20, 70, 110, 160, 200, 250, 290, 340):
        rad = math.radians(ang)
        gnd_stitch(j3.x + 9.4 * math.cos(rad), j3.y + 9.4 * math.sin(rad))
    gnd_stitch(d1g.x + 2.0, d1g.y, d1g, 0.5)
    gnd_stitch(c1g.x, c1g.y + 1.6, c1g, 0.4)
    gnd_stitch(c2g.x, c2g.y + 1.6, c2g, 0.4)
    r2g = pads_of(P, "R2", "2")
    gnd_stitch(r2g.x, r2g.y + 1.6, r2g, 0.3)
    # HP GND (pin 1) — south of pin row, away from EN/IS.
    for uref, oy in (("U1", 2.8), ("U2", 2.8), ("U3", 2.8), ("U4", 2.8)):
        g = pads_of(P, uref, "1")
        gnd_stitch(g.x, g.y + oy, g, 0.4)
    for uref in [f"U{n}" for n in range(11, 19)]:
        g = pads_of(P, uref, "1")
        gnd_stitch(g.x - 1.7, g.y, g, 0.3)
    for ref in (
        [f"R{n}" for n in (10, 20, 30, 40)]
        + [f"R{n}" for n in range(101, 109)]
        + [f"C{n}" for n in (10, 20, 30, 40)]
        + [f"C{n}" for n in range(101, 109)]
    ):
        num = "1" if ref.startswith("R") else "2"
        try:
            g = pads_of(P, ref, num)
        except KeyError:
            continue
        if g.net != "GND":
            continue
        gnd_stitch(g.x, g.y + (1.4 if ref.startswith("R") else -1.4), g, 0.25)


def route_hp_out(rt: Router, P):
    """HP OUT: leave the pin row south (U1/U2) or east-then-south (U3/U4) so IS/EN stay clear."""
    for idx, (net, uref, jpins) in enumerate(HP_OUT):
        outs = [pads_of(P, uref, n) for n in ("5", "6", "7")]
        ys = [p.y for p in outs]
        xs = [p.x for p in outs]
        cy = sum(ys) / len(ys)
        rt.track(min(xs), cy, max(xs), cy, 0.9, net)
        for p in outs:
            rt.track(p.x, p.y, p.x, cy, 0.7, net)
        cx = sum(xs) / 3
        col = PWR_COL[idx]
        jps = [pads_of(P, "J1", jp) for jp in jpins]
        mid_y = sum(p.y for p in jps) / 2
        if uref in {"U1", "U2"}:
            # IS/R go north of the pin row; escape south then west on F, hop to B at the column.
            ey = 50.50 + idx * 0.55
            rt.track(cx, cy, cx, ey, 0.7, net)
            rt.manh([(cx, ey), (col, ey)], 0.7, net)
            rt.via(col, ey, net)
            rt.manh_vh([(col, ey), (col, mid_y)], 0.6, net, "B.Cu")
        else:
            # U3/U4 IS/R sit south at y=65.5 — east on F, B.Cu west in the y≈64 band
            # (south of HP EN B at y≤63, north of ADIO EN B at y≥66.7).
            ex, ey = 101.2, 64.10 + (idx - 2) * 0.50
            rt.manh([(cx, cy), (ex, cy)], 0.7, net)
            rt.via(ex, cy, net)
            rt.manh_vh([(ex, cy), (ex, ey), (col, ey)], 0.6, net, "B.Cu")
            rt.via(col, ey, net)
            rt.manh_vh([(col, ey), (col, mid_y)], 0.6, net, "B.Cu")
        rt.via(col, mid_y, net)
        for jp in jps:
            rt.manh([(col, mid_y), (jp.x, mid_y), (jp.x, jp.y)], 0.7, net)


def route_adio_out(rt: Router, P):
    """Local F at the chip; exclusive columns east of pin field; F-hop EN B band."""
    for idx, (net, uref, jpin, rp) in enumerate(ADIO_OUT):
        outs = [pads_of(P, uref, n) for n in ("8", "9", "10", "12", "13", "14")]
        ox = outs[0].x
        ys = [p.y for p in outs]
        rt.track(ox, min(ys), ox, max(ys), 0.40, net)
        for p in outs:
            rt.track(p.x, p.y, ox, p.y, 0.28, net)
        r = pads_of(P, rp, "2")
        # Offset off the chip centerline (IS / thermal pad Y) so OUT does not sit on IS.
        mid_y = (min(ys) + max(ys)) / 2 + (0.55 if idx % 2 == 0 else -0.55)
        rt.manh([(r.x, r.y), (ox, r.y), (ox, mid_y)], 0.28, net)
        j = pads_of(P, "J1", jpin)
        col = ADIO_COL[idx]
        # South of EN B south-hwys (~66.7–69.4) and north of SuperSeal pins (≤55.5).
        hop_s = 72.80 + (idx % 2) * 0.50
        hop_n = 65.90 - (idx % 2) * 0.40
        rt.manh([(ox, mid_y), (col, mid_y), (col, hop_s)], 0.25, net)
        rt.via(col, hop_s, net)
        rt.track(col, hop_s, col, hop_n, 0.25, net, "F.Cu")
        rt.via(col, hop_n, net)
        rt.manh_vh([(col, hop_n), (col, j.y), (j.x, j.y)], 0.25, net, "B.Cu")


def route_en(rt: Router, P):
    """Exclusive B.Cu: HP uses pin-south band y≈56.6–63; ADIO uses south-of-J1 Y; gap columns to E pads."""
    w = 0.15
    for idx, (net, uref, pins, mpad) in enumerate(EN_MAP):
        coords = [pads_of(P, uref, pn) for pn in pins]
        if len(coords) > 1:
            rt.track(coords[0].x, coords[0].y, coords[1].x, coords[1].y, 0.22, net)
        sx, sy = coords[0].x, coords[0].y
        m = pads_of(P, "M1000", mpad)
        gap_x = EN_GAP_X[idx]
        hp = uref in {"U1", "U2", "U3", "U4"}
        if hp:
            # U1/U2 pins sit in the SuperSeal Y-span — drop south into the pin-south band first.
            hwy = 56.60 + idx * 0.45 if idx < 4 else sy
            vx = sx - 1.35 if uref in {"U1", "U3"} else sx - 1.55
            rt.track(sx, sy, vx, sy, w, net)
            rt.via(vx, sy, net)
            rt.manh_vh([(vx, sy), (vx, hwy), (gap_x, hwy)], w, net, "B.Cu")
        else:
            adio_i = idx - 4
            hwy = EN_ADIO_HWY[adio_i]
            vx, vy = sx - 1.20, sy
            rt.track(sx, sy, vx, vy, w, net)
            rt.via(vx, vy, net)
            rt.manh_vh([(vx, vy), (vx, hwy), (gap_x, hwy)], w, net, "B.Cu")
        rt.manh_vh([(gap_x, hwy if hp else EN_ADIO_HWY[idx - 4]), (gap_x, m.y), (m.x, m.y)], w, net, "B.Cu")


def route_is_local(rt: Router, P):
    w = 0.22
    for net, uref, upin, rref, cref in IS_LOCAL:
        u = pads_of(P, uref, upin)
        r = pads_of(P, rref, "2")
        c = pads_of(P, cref, "1")
        if uref in {"U1", "U2"}:
            # R/C sit north of the TO-263 (y=32). Stay on F, north of the pin row, east of GND pad1.
            bus_y = u.y - 2.20
            vx = r.x + 1.15
            rt.manh([(u.x, u.y), (u.x, bus_y), (vx, bus_y), (vx, r.y), (r.x, r.y)], w, net)
            rt.manh([(r.x, r.y), (c.x, r.y), (c.x, c.y)], w, net)
        elif uref in {"U3", "U4"}:
            # R/C sit south (y=65.5). Vertical at IS x only, then along RIS Y — not through OUT.
            rt.manh([(u.x, u.y), (u.x, r.y), (r.x, r.y)], w, net)
            rt.manh([(r.x, r.y), (c.x, r.y), (c.x, c.y)], w, net)
        else:
            # ADIO pin-row is packed on F — local IS under the package on B.
            rt.via(u.x, u.y, net)
            rt.manh([(u.x, u.y), (r.x, u.y), (r.x, r.y)], w, net, "B.Cu")
            rt.via(r.x, r.y, net)
            rt.manh([(r.x, r.y), (c.x, r.y), (c.x, c.y)], w, net)


def route_is_long(rt: Router, P):
    """F.Cu long-haul (EN owns B gap columns). Staircase south skirt west of J3; HP via north-of-J1."""
    w = 0.20
    hp_north = {"R10", "R20"}
    hp_south = {"R30", "R40"}
    for idx, (net, rref, mpad) in enumerate(IS_LONG):
        r = pads_of(P, rref, "2")
        m = pads_of(P, "M1000", mpad)
        sy, col, app = IS_SOUTH_Y[idx], IS_COL[idx], IS_APP_Y[idx]
        if rref in hp_north:
            # Unique north-pocket Y and MCU–J1 F-gap X (EN is on B in that gap).
            ny = 23.70 + idx * 0.45
            gx = 47.10 + idx * 0.40
            nx = r.x + 1.10
            rt.track(r.x, r.y, nx, r.y, w, net)
            rt.manh([(nx, r.y), (nx, ny), (gx, ny)], w, net)
            rt.manh_vh([(gx, ny), (gx, app), (m.x, app), (m.x, m.y)], w, net)
        elif rref in hp_south:
            # U3/U4 sense at y=65.5: drop south into the staircase instead of hauling through ADIO.
            nx = r.x + 1.10
            rt.track(r.x, r.y, nx, r.y, w, net)
            rt.manh([(nx, r.y), (nx, sy), (col, sy)], w, net)
            rt.manh_vh([(col, sy), (col, app), (m.x, app), (m.x, m.y)], w, net)
        else:
            rt.manh([(r.x, r.y), (r.x, sy), (col, sy)], w, net)
            rt.manh_vh([(col, sy), (col, app), (m.x, app), (m.x, m.y)], w, net)


def route_system(rt: Router, P):
    jign = pads_of(P, "J1", "4")
    r1a, r1b = pads_of(P, "R1", "1"), pads_of(P, "R1", "2")
    r2a = pads_of(P, "R2", "1")
    # IGN_SW lives on SuperSeal; go north of the pin field then east to R1.
    rt.manh([(jign.x, jign.y), (jign.x, 24.2), (r1a.x, 24.2), (r1a.x, r1a.y)], 0.4, "IGN_SW")
    rt.manh([(r1b.x, r1b.y), (r2a.x, r1b.y), (r2a.x, r2a.y)], 0.3, "IN_VIGN")
    n26 = pads_of(P, "M1000", "N26")
    vx, vy = 24.2, 22.4
    rt.manh([(r1b.x, r1b.y), (vx, r1b.y), (vx, vy)], 0.25, "IN_VIGN")
    rt.via(vx, vy, "IN_VIGN")
    rt.manh([(vx, vy), (vx, 4.0), (n26.x, 4.0), (n26.x, n26.y)], 0.25, "IN_VIGN", "B.Cu")

    for net, mpad, jpin, lane_y in (("CANH", "W12", "3", 5.2), ("CANL", "W13", "10", 6.0)):
        m = pads_of(P, "M1000", mpad)
        j = pads_of(P, "J1", jpin)
        rt.track(m.x, m.y, 1.4, m.y, 0.3, net)
        rt.via(1.4, m.y, net)
        rt.manh([(1.4, m.y), (1.4, lane_y), (j.x + 3.0, lane_y)], 0.3, net, "B.Cu")
        rt.via(j.x + 3.0, lane_y, net)
        rt.manh([(j.x + 3.0, lane_y), (j.x + 3.0, j.y), (j.x, j.y)], 0.3, net)

    e38 = pads_of(P, "M1000", "E38")
    n30 = pads_of(P, "M1000", "N30")
    w2 = pads_of(P, "M1000", "W2")
    bus_n, bus_s, bus_e = 7.20, 91.20, 82.20  # bus_e west of J3
    rt.track(e38.x, e38.y, 46.8, e38.y, 0.35, "SENSOR_5V")
    rt.via(46.8, e38.y, "SENSOR_5V")
    rt.manh([(1.6, bus_n), (bus_e, bus_n)], 0.35, "SENSOR_5V", "B.Cu")
    rt.manh([(46.8, e38.y), (46.8, bus_n)], 0.35, "SENSOR_5V", "B.Cu")
    rt.manh([(n30.x, n30.y), (n30.x, bus_n)], 0.3, "SENSOR_5V", "B.Cu")
    rt.track(w2.x, w2.y, 1.6, w2.y, 0.3, "SENSOR_5V")
    rt.via(1.6, w2.y, "SENSOR_5V")
    rt.manh([(1.6, w2.y), (1.6, bus_n)], 0.3, "SENSOR_5V", "B.Cu")
    for jp in ("5", "11"):
        j = pads_of(P, "J1", jp)
        ex = j.x + 2.6
        rt.track(j.x, j.y, ex, j.y, 0.35, "SENSOR_5V")
        rt.via(ex, j.y, "SENSOR_5V")
        rt.manh([(ex, j.y), (ex, bus_n)], 0.35, "SENSOR_5V", "B.Cu")
    # South SENSOR_5V bus west of J3, feeding ADIO PU resistors.
    rt.manh([(bus_e, bus_n), (bus_e, bus_s)], 0.30, "SENSOR_5V", "B.Cu")
    for r in range(201, 209):
        rp = pads_of(P, f"R{r}", "1")
        side_x, side_y = rp.x, rp.y + 1.70
        rt.track(rp.x, rp.y, side_x, side_y, 0.25, "SENSOR_5V")
        rt.via(side_x, side_y, "SENSOR_5V")
        rt.manh([(side_x, side_y), (side_x, bus_s), (bus_e, bus_s)], 0.25, "SENSOR_5V", "B.Cu")

    # SENSOR_GND dedicated — tracks only, no pour.
    a, b = pads_of(P, "J1", "6"), pads_of(P, "J1", "12")
    e39, w1 = pads_of(P, "M1000", "E39"), pads_of(P, "M1000", "W1")
    rt.manh([(a.x, a.y), (a.x, b.y), (b.x, b.y)], 0.35, "SENSOR_GND")
    sg_y = 8.1
    rt.track(e39.x, e39.y, 46.4, e39.y, 0.3, "SENSOR_GND")
    rt.via(46.4, e39.y, "SENSOR_GND")
    rt.manh([(46.4, e39.y), (46.4, sg_y), (a.x + 2.2, sg_y)], 0.3, "SENSOR_GND", "B.Cu")
    rt.via(a.x + 2.2, sg_y, "SENSOR_GND")
    rt.manh([(a.x + 2.2, sg_y), (a.x + 2.2, a.y), (a.x, a.y)], 0.3, "SENSOR_GND")
    rt.track(w1.x, w1.y, 1.8, w1.y, 0.3, "SENSOR_GND")
    rt.via(1.8, w1.y, "SENSOR_GND")
    rt.manh([(1.8, w1.y), (1.8, sg_y), (46.4, sg_y)], 0.3, "SENSOR_GND", "B.Cu")


def connectivity(pads: list[Pad], rt: Router):
    parent = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    nodes = []
    for i, p in enumerate(pads):
        if not p.net:
            continue
        key = ("pad", i)
        parent[key] = key
        nodes.append((key, p.x, p.y, p.net, "F.Cu" if "B.Cu" not in p.layers or "F.Cu" in p.layers else "B.Cu", p.kind))

    for i, (x, y, net) in enumerate(rt.vias):
        key = ("via", i)
        parent[key] = key
        nodes.append((key, x, y, net, "VIA", "via"))

    for i, (x1, y1, x2, y2, lay, net, w) in enumerate(rt.segs):
        k1, k2 = ("s", i, 0), ("s", i, 1)
        parent[k1] = k1
        parent[k2] = k2
        union(k1, k2)
        nodes.append((k1, x1, y1, net, lay, "seg"))
        nodes.append((k2, x2, y2, net, lay, "seg"))

    by_net = defaultdict(list)
    for n in nodes:
        by_net[n[3]].append(n)
    SNAP = 0.55
    for net, lst in by_net.items():
        for i, a in enumerate(lst):
            for b in lst[i + 1 :]:
                if abs(a[1] - b[1]) <= SNAP and abs(a[2] - b[2]) <= SNAP:
                    if a[4] == "VIA" or b[4] == "VIA" or a[5] == "thru" or b[5] == "thru" or a[4] == b[4]:
                        union(a[0], b[0])

    def on_seg(px, py, x1, y1, x2, y2, half):
        if abs(y1 - y2) < 1e-3:
            return abs(py - y1) <= half and min(x1, x2) - half <= px <= max(x1, x2) + half
        if abs(x1 - x2) < 1e-3:
            return abs(px - x1) <= half and min(y1, y2) - half <= py <= max(y1, y2) + half
        return False

    for i, (x1, y1, x2, y2, lay, net, w) in enumerate(rt.segs):
        half = w / 2 + 0.35
        for j, (a1, b1, a2, b2, lay2, net2, w2) in enumerate(rt.segs):
            if j == i or net != net2 or lay != lay2:
                continue
            h2 = w2 / 2 + 0.35
            if on_seg(x1, y1, a1, b1, a2, b2, max(half, h2)) or on_seg(x2, y2, a1, b1, a2, b2, max(half, h2)):
                union(("s", i, 0), ("s", j, 0))

    for i, p in enumerate(pads):
        if not p.net:
            continue
        pk = ("pad", i)
        for si, (x1, y1, x2, y2, lay, net, w) in enumerate(rt.segs):
            if net != p.net:
                continue
            if on_seg(p.x, p.y, x1, y1, x2, y2, w / 2 + 0.35):
                union(pk, ("s", si, 0))

    parent.setdefault(("zone", "VBAT"), ("zone", "VBAT"))
    parent.setdefault(("zone", "GND"), ("zone", "GND"))
    for i, p in enumerate(pads):
        if p.net == "VBAT":
            # post-fuse / HP / ADIO islands (J2 island is separate until tracks)
            if (66.5 <= p.x <= 82.5 and 1.0 <= p.y <= 24.0) or (73.0 <= p.x <= 103.0 and 32.0 <= p.y <= 64.0) or (
                48.0 <= p.x <= 82.0 and 66.0 <= p.y <= 81.0
            ):
                union(("pad", i), ("zone", "VBAT"))
        if p.net == "GND" and p.kind == "thru":
            union(("pad", i), ("zone", "GND"))
        if p.net == "GND":
            for x, y, net in rt.vias:
                if net == "GND" and abs(x - p.x) < 2.5 and abs(y - p.y) < 2.5:
                    union(("pad", i), ("zone", "GND"))
                    break
    for i, (x, y, net) in enumerate(rt.vias):
        if net == "GND":
            union(("via", i), ("zone", "GND"))
        if net == "VBAT" and x >= 66:
            union(("via", i), ("zone", "VBAT"))

    open_nets = {}
    grouped = defaultdict(list)
    for i, p in enumerate(pads):
        if p.net:
            grouped[p.net].append(i)
    for net, idxs in grouped.items():
        roots = {find(("pad", i)) for i in idxs}
        if len(roots) > 1:
            open_nets[net] = len(roots)
    return open_nets


def new_zones() -> list[str]:
    """Split-bobbin pours. Fuse not bypassed: J2 island ≠ post-fuse island. No SENSOR pour."""
    z = []
    z.append(zone_rect(2, "GND", "B.Cu", uid("z-gnd-b"), [(1, 1), (103, 1), (103, 92), (1, 92)]))
    # J2 VBAT only (east of fuse). 16 mm pad lives here.
    z.append(zone_rect(1, "VBAT", "F.Cu", uid("z-vbat-f-j2"), [(83.5, 1), (103, 1), (103, 22), (83.5, 22)], priority=1))
    z.append(zone_rect(1, "VBAT", "B.Cu", uid("z-vbat-b-j2"), [(83.5, 1), (103, 1), (103, 22), (83.5, 22)], priority=1))
    # Post-fuse north pocket (F1.2 / C2). Does not include F1.1 at x=58.
    z.append(
        zone_rect(1, "VBAT", "F.Cu", uid("z-vbat-f-nf"), [(66.5, 1), (82.5, 1), (82.5, 24), (66.5, 24)], priority=1)
    )
    z.append(
        zone_rect(1, "VBAT", "B.Cu", uid("z-vbat-b-nf"), [(66.5, 1), (82.5, 1), (82.5, 24), (66.5, 24)], priority=1)
    )
    # HP tabs. B alley east, stops north of EN south-hwys (y≥66.7).
    z.append(zone_rect(1, "VBAT", "F.Cu", uid("z-vbat-f-hp"), [(73, 32), (103, 32), (103, 64), (73, 64)], priority=1))
    z.append(zone_rect(1, "VBAT", "B.Cu", uid("z-vbat-b-hp"), [(86, 32), (103, 32), (103, 61), (86, 61)], priority=1))
    z.append(zone_rect(1, "VBAT", "F.Cu", uid("z-vbat-f-adio"), [(48, 66), (82, 66), (82, 81), (48, 81)], priority=1))
    z.append(zone_rect(2, "GND", "F.Cu", uid("z-gnd-f-j3"), [(82, 72), (103, 72), (103, 92), (82, 92)], priority=1))
    z.append(
        zone_rect(
            0,
            "",
            "F.Cu",
            uid("z-m1000-ko"),
            [(1.5, 25.5), (44.7, 25.5), (44.7, 66.5), (1.5, 66.5)],
            keepout=True,
        )
    )
    return z


def plot_png(rt: Router, pads: list[Pad], path: Path):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    scale = 8
    w, h = int(BOARD_W * scale) + 8, int(BOARD_H * scale) + 8

    def xy(x, y):
        return int(x * scale) + 4, int(y * scale) + 4

    img = Image.new("RGB", (w, h), (18, 18, 22))
    dr = ImageDraw.Draw(img)
    dr.rectangle([xy(0, 0), xy(BOARD_W, BOARD_H)], outline=(80, 80, 90), width=2)
    dr.line([xy(45.5, 4), xy(45.5, 89)], fill=(90, 90, 40), width=1)
    en_set = {e[0] for e in EN_MAP}
    is_set = {e[0] for e in IS_LOCAL}
    for x1, y1, x2, y2, lay, net, width in rt.segs:
        if net == "VBAT":
            col = (220, 70, 70) if lay == "F.Cu" else (160, 40, 90)
        elif net == "GND":
            col = (70, 90, 210)
        elif net.startswith("PWR_OUT"):
            col = (220, 140, 40)
        elif net.startswith("ADIO"):
            col = (40, 180, 120)
        elif net in en_set:
            col = (200, 80, 200)
        elif net in is_set:
            col = (80, 200, 220)
        else:
            col = (180, 180, 100) if lay == "F.Cu" else (100, 140, 200)
        dr.line([xy(x1, y1), xy(x2, y2)], fill=col, width=max(1, int(width * scale)))
    for x, y, net in rt.vias:
        cx, cy = xy(x, y)
        dr.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], outline=(200, 200, 200))
    for p in pads:
        if p.ref in {"J1", "J2", "J3", "M1000", "U1", "U2", "U3", "U4"} or p.ref.startswith("U1"):
            cx, cy = xy(p.x, p.y)
            dr.rectangle([cx - 1, cy - 1, cx + 1, cy + 1], fill=(140, 140, 140))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return True


def main() -> int:
    raw = PCB.read_text()
    if not raw.startswith("(kicad_pcb"):
        sys.exit("pcb missing — abort")
    m = re.match(r"(\(kicad_pcb\n)([\s\S]*)(\n\)\s*)$", raw)
    if not m:
        sys.exit("unexpected pcb wrapper")
    header, inner = m.group(1), m.group(2)
    items = extract_top_items(inner)
    items = [it if it.startswith("\t") else "\t" + it for it in items]

    for it in items:
        mm = re.match(r'\t\(net (\d+) "([^"]*)"\)', it)
        if mm:
            NET_CODE[mm.group(2)] = int(mm.group(1))
            NET_NAME[int(mm.group(1))] = mm.group(2)

    pads: list[Pad] = []
    new_items = []
    skipped = {"segment": 0, "via": 0, "zone": 0}
    fp_count = 0
    refs = set()
    for it in items:
        head = item_head(it)
        if head in skipped:
            skipped[head] += 1
            continue
        if head == "footprint":
            ref = fp_ref(it) or "?"
            refs.add(ref)
            pads.extend(parse_pads(it, ref))
            fp_count += 1
        new_items.append(it)

    if fp_count < 50:
        sys.exit(f"too few footprints ({fp_count}) — abort")
    if "J3" not in refs or "J2" not in refs:
        sys.exit("split bobbins J2/J3 missing — abort")
    if "M6_BoltThrough_Bobbin_x2" in raw:
        sys.exit("dual-bobbin footprint still on the board — abort")

    rt = Router()
    route_power(rt, pads)
    route_hp_out(rt, pads)
    route_adio_out(rt, pads)
    route_is_local(rt, pads)
    route_en(rt, pads)
    route_is_long(rt, pads)
    route_system(rt, pads)

    mxy = [(p.x, p.y) for p in pads if p.ref == "M1000"]
    sig = [(x, y, n) for x, y, n in rt.vias if n != "GND"]
    cleaned = []
    for x, y, n in rt.vias:
        if any(abs(x - px) < 0.5 and abs(y - py) < 0.5 for px, py in mxy):
            continue
        if n == "GND" and any(math.hypot(x - sx, y - sy) < 1.2 for sx, sy, _ in sig):
            continue
        cleaned.append((x, y, n))
    if len(cleaned) != len(rt.vias):
        rebuild_from_lists(rt, rt.segs, cleaned)

    hops = apply_hops(rt, max_hops=0)
    crosses = count_crossings(rt)
    via_packs = count_via_packs(rt)
    open_nets = connectivity(pads, rt)

    zones = new_zones()
    copper_txt = "".join(rt.copper)
    inner_out = "\n".join(new_items) + "\n" + "\n".join(zones) + "\n" + copper_txt
    pcb_out = header + inner_out + ")\n"
    if pcb_out.count("\n\t(footprint ") < 50:
        sys.exit("refusing to write broken pcb")
    if "(kicad_pcb" not in pcb_out[:40]:
        sys.exit("header lost")
    if "pdmrazora" not in pcb_out:
        sys.exit("stem lost")

    PCB.write_text(pcb_out)

    en_open = sorted(n for n in open_nets if n in EN_IS)
    crit = {
        "VBAT",
        "GND",
        "PWR_OUT1",
        "PWR_OUT2",
        "PWR_OUT3",
        "PWR_OUT4",
        *EN_IS,
        *[a[0] for a in ADIO_OUT],
        "CANH",
        "CANL",
        "SENSOR_5V",
        "SENSOR_GND",
        "IGN_SW",
        "IN_VIGN",
    }
    leftover_crit = {n: open_nets[n] for n in sorted(open_nets) if n in crit and n != "GND"}
    leftover_other = {n: open_nets[n] for n in sorted(open_nets) if n not in crit and n != "GND"}
    gnd_islands = open_nets.get("GND", 1)

    STATUS.write_text(
        "\n".join(
            [
                f"tracks={rt.nseg}",
                f"vias={rt.nvia}",
                f"footprints={fp_count}",
                f"geom_crossings={len(crosses)}",
                f"via_packs={len(via_packs)}",
                f"hops={hops}",
                f"open_nets={len(open_nets)}",
                f"en_is_open={len(en_open)}",
                f"gnd_pad_islands_before_pour={gnd_islands}",
                "strategy=sexp_split_bobbins_vbat_n_gnd_s_emi_split",
                "kicad_cli=pending_fill",
                "hellcore=untouched",
                "fuse=ATO_placeholder_untouched",
                "sensor_pour=absent_not_added",
            ]
        )
        + "\n"
    )
    lines = [
        "# Leftover unconnected nets (pad islands after track/via/zone-outline snap)",
        "",
        "## GND",
        f"- GND: {gnd_islands} pad islands before zone fill; J3 south bobbin + B.Cu pour + stitches. No SENSOR_GND bond.",
        "",
        "## Critical signal nets",
    ]
    if leftover_crit:
        for n, k in leftover_crit.items():
            lines.append(f"- {n}: {k} islands")
    else:
        lines.append("- none")
    lines += [
        "",
        "## Other (DIR, PU FET, V-sense, USB-on-module, unused MM144)",
    ]
    if leftover_other:
        for n, k in leftover_other.items():
            lines.append(f"- {n}: {k} islands")
    else:
        lines.append("- none")
    lines += [
        "",
        "USBID/USBM/USBP live only on M1000 (USB-C is on the module).",
        "OUT_IO9–13 / IO1–3 PU FET not stuffed (BOARD.md TODO).",
        "IN_TPS/PPS/CLT/IAT/AT* ADIO V-sense dividers not stuffed.",
        "OUT_IO1–4 HP DIR not stuffed.",
        "F1 ATO fuse placeholder not replaced (Jeoff: do not block). J2 pour is split from post-fuse pour.",
        "",
        "## Notes",
        f"- Via pairs closer than size+clearance: {len(via_packs)}.",
        "- Old 150×130 south-ring / cut_crossings_sexp.py scripts were not replayed.",
        "- Mechanical PR #9 placements were not moved.",
    ]
    LEFTOVER.write_text("\n".join(lines) + "\n")

    plot_png(rt, pads, Path("/opt/cursor/artifacts/copper_f_overview_preroute.png"))
    plot_png(rt, pads, ROOT / "scripts" / "copper_overview.png")

    print(f"footprints={fp_count} tracks={rt.nseg} vias={rt.nvia} hops={hops}")
    sig_cross = [(a, b, l) for a, b, l in crosses if a not in ("VBAT", "GND") and b not in ("VBAT", "GND")]
    print(f"signal_signal_crossings={len(sig_cross)} via_packs={len(via_packs)} geom={len(crosses)}")
    print(f"open_nets={len(open_nets)} en_is_open={en_open}")
    print("crit leftover", leftover_crit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
