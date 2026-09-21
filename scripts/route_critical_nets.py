#!/usr/bin/env python3
"""Route critical nets on the 104×93 PowerCore floorplan (sexp, no pcbnew).

Does not move footprints, does not wipe the board, does not touch HELLCORE.
Old 150×130 copper scripts must not be reapplied.

Layer policy (EMI split: MCU west / power east, SuperSeal as wall):
  - VBAT: F.Cu east pour + wide F spines; module VBAT via north corridor only
  - GND: B.Cu full-board pour + stitches; no SENSOR_GND bond
  - PWR_OUT / ADIO: stay east of the SuperSeal pin field except J1 landings
  - EN: exclusive B.Cu lanes around J1 south/north spine to M1000 E pads
  - IS: local F.Cu U–R–C; exclusive F.Cu long-haul to M1000 S pads
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
CLR = 0.22  # netclass 0.2 + slop
VIA_R = 0.30  # 0.6 mm via

NET_CODE: dict[str, int] = {}
NET_NAME: dict[int, str] = {}


def uid(tag: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pdmrazora-route/{tag}"))


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
        self.kind = kind  # smd / thru


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
		)
		(placement
			(enabled no)
			(sheetname "")
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
        # clamp lightly inside board
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

    def via(self, x, y, net, size=0.6, drill=0.3):
        x = max(0.6, min(BOARD_W - 0.6, x))
        y = max(0.6, min(BOARD_H - 0.6, y))
        self.copper.append(via_block(x, y, net, self._tag(f"v-{net}"), size, drill))
        self.nvia += 1
        self.vias.append((x, y, net))

    def manh(self, pts, width, net, layer="F.Cu"):
        """Axis-aligned path. If a point pair is diagonal, go H then V."""
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


def pad_map(pads: list[Pad]) -> dict[tuple[str, str], Pad]:
    out = {}
    for p in pads:
        out[(p.ref, p.num)] = p
    return out


def pads_of(pads, ref, num) -> Pad:
    hits = [p for p in pads if p.ref == ref and p.num == num]
    if not hits:
        raise KeyError(f"{ref}.{num}")
    # prefer the smaller (signal) pad if duplicated (HP tab vs pin share "4")
    hits.sort(key=lambda p: p.sx * p.sy)
    return hits[0]


def pads_named(pads, ref, num) -> list[Pad]:
    return [p for p in pads if p.ref == ref and p.num == num]


def net_pads(pads, net) -> list[Pad]:
    return [p for p in pads if p.net == net]


def aabb_intersect(a, b) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return ax1 <= bx2 and ax2 >= bx1 and ay1 <= by2 and ay2 >= by1


def seg_aabb(x1, y1, x2, y2, half):
    return (
        min(x1, x2) - half,
        min(y1, y2) - half,
        max(x1, x2) + half,
        max(y1, y2) + half,
    )


def segs_cross_same_layer(s1, s2) -> bool:
    x1, y1, x2, y2, lay1, n1, w1 = s1
    x3, y3, x4, y4, lay2, n2, w2 = s2
    if lay1 != lay2 or n1 == n2:
        return False
    # axis-aligned only
    h1 = abs(y1 - y2) < 1e-4
    v1 = abs(x1 - x2) < 1e-4
    h2 = abs(y3 - y4) < 1e-4
    v2 = abs(x3 - x4) < 1e-4
    half = (w1 + w2) / 2 + CLR - 0.02
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


def hop_crossing_segs(rt: Router) -> int:
    """Replace B.Cu victims that cross with an F.Cu hop (vias at both ends)."""
    n = 0
    segs = list(rt.segs)
    # rebuild copper from remaining + hops — easier to append hops by splitting later
    # We instead scan and for B crossings, convert the *shorter* B seg to F hop
    # by adding vias + F overlay and deleting conceptually (we filter copper text).
    to_skip = set()
    extras = []
    for i, s1 in enumerate(segs):
        if i in to_skip:
            continue
        for j, s2 in enumerate(segs):
            if j <= i or j in to_skip:
                continue
            if not segs_cross_same_layer(s1, s2):
                continue
            # prefer hopping the thinner / shorter non-power net
            def score(s):
                x1, y1, x2, y2, lay, net, w = s
                power = net in {"VBAT", "GND", "PWR_OUT1", "PWR_OUT2", "PWR_OUT3", "PWR_OUT4"}
                length = abs(x2 - x1) + abs(y2 - y1)
                return (1 if power else 0, -length, w)

            victim_i = i if score(s1) < score(s2) else j
            if victim_i in to_skip:
                continue
            x1, y1, x2, y2, lay, net, w = segs[victim_i]
            other = "F.Cu" if lay == "B.Cu" else "B.Cu"
            extras.append((x1, y1, x2, y2, other, net, max(0.2, w)))
            extras.append(("via", x1, y1, net))
            extras.append(("via", x2, y2, net))
            to_skip.add(victim_i)
            n += 1
    if not n:
        return 0
    new_copper = []
    new_segs = []
    new_vias = list(rt.vias)
    idx = 0
    for blk, seg in zip(rt.copper, rt.segs + [None] * (len(rt.copper) - len(rt.segs))):
        # copper list is segs and vias interleaved — rebuild from segs/vias instead
        break
    # rebuild from structured lists
    kept_segs = [s for k, s in enumerate(rt.segs) if k not in to_skip]
    for x1, y1, x2, y2, lay, net, w in extras:
        if x1 == "via":
            continue
        kept_segs.append((x1, y1, x2, y2, lay, net, w))
    extra_vias = [(t[1], t[2], t[3]) for t in extras if t[0] == "via"]
    rt.copper = []
    rt.segs = []
    rt.vias = []
    rt.nseg = 0
    rt.nvia = 0
    seen_v = set()
    for x, y, net in list(new_vias) + extra_vias:
        key = (round(x, 3), round(y, 3), net)
        if key in seen_v:
            continue
        seen_v.add(key)
        rt.via(x, y, net)
    # wait, we lost original vias not in extra — new_vias was copy of old then we zeroed
    return n


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


def apply_hops(rt: Router, max_hops=80) -> int:
    """Hop the shorter *signal* track of a same-layer crossing onto the other layer.

    VBAT/GND crossings are left for zone fill (pours keep clearance around tracks).
    """
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


# --- net maps (must match schematic / previous successful EN/IS work) ---
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


def route_power(rt: Router, P):
    j2p = pads_of(P, "J2", "1")
    j2g = pads_of(P, "J2", "2")
    f1a = pads_of(P, "F1", "1")
    f1b = pads_of(P, "F1", "2")
    c1p = pads_of(P, "C1", "1")
    c1g = pads_of(P, "C1", "2")
    c2p = pads_of(P, "C2", "1")
    c2g = pads_of(P, "C2", "2")
    d1p = pads_of(P, "D1", "1")
    d1g = pads_of(P, "D1", "2")

    # VBAT: M6+ → fuse → bulk → HP tabs. Stay x≳67.
    rt.manh([(j2p.x, j2p.y), (f1a.x, j2p.y), (f1a.x, f1a.y)], 2.0, "VBAT")
    rt.manh([(f1b.x, f1b.y), (c1p.x, f1b.y), (c1p.x, c1p.y)], 1.2, "VBAT")
    rt.manh([(f1b.x, f1b.y), (c2p.x, f1b.y), (c2p.x, c2p.y)], 0.8, "VBAT")
    rt.manh([(f1b.x, f1b.y), (d1p.x, f1b.y), (d1p.x, d1p.y)], 0.8, "VBAT")

    # VBAT long-haul on B.Cu in the U1–U2 alley, stopping north of the EN B highways (y≥66.9).
    spine_x = 88.0
    rt.manh([(f1b.x, f1b.y), (spine_x, f1b.y)], 1.2, "VBAT")
    rt.via(spine_x, f1b.y, "VBAT")
    rt.track(spine_x, f1b.y, spine_x, 64.4, 1.2, "VBAT", "B.Cu")
    for uref, tap_y in (("U1", 52.2), ("U2", 52.2), ("U3", 64.4), ("U4", 64.4)):
        tabs = pads_named(P, uref, "4")
        tab = max(tabs, key=lambda p: p.sx * p.sy)
        rt.via(tab.x, tap_y, "VBAT")
        rt.track(tab.x, tap_y, tab.x, tab.y, 1.0, "VBAT")
        rt.manh([(spine_x, tap_y), (tab.x, tap_y)], 1.0, "VBAT", "B.Cu")

    # ADIO VS tabs sit inside the VBAT F.Cu ADIO island — no extra stubs (avoids F crossings).

    # Module VBAT N27 — necessary west crossing via north corridor (B.Cu, y=3.2)
    n27 = pads_of(P, "M1000", "N27")
    rt.track(spine_x, 8.0, spine_x, 3.2, 0.5, "VBAT")
    rt.via(spine_x, 3.2, "VBAT")
    rt.manh([(spine_x, 3.2), (n27.x, 3.2), (n27.x, n27.y)], 0.5, "VBAT", "B.Cu")
    rt.via(n27.x, n27.y, "VBAT")

    # GND stitches: every carrier GND pad → B.Cu, plus M6 already has footprint vias
    rt.via(j2g.x - 9.2, j2g.y, "GND")
    rt.via(j2g.x + 9.2, j2g.y, "GND")
    rt.via(d1g.x - 1.6, d1g.y, "GND")
    rt.track(d1g.x, d1g.y, d1g.x - 1.6, d1g.y, 0.5, "GND")
    for p, ox, oy in (
        (c1g, 0.0, 1.4),
        (c2g, 0.0, 1.4),
    ):
        vx, vy = p.x + ox, p.y + oy
        rt.track(p.x, p.y, vx, vy, 0.4, "GND")
        rt.via(vx, vy, "GND")

    r2g = pads_of(P, "R2", "2")
    rt.track(r2g.x, r2g.y, r2g.x, r2g.y + 1.5, 0.3, "GND")
    rt.via(r2g.x, r2g.y + 1.5, "GND")

    # HP / ADIO / sense GND
    for uref in ["U1", "U2", "U3", "U4"]:
        g = pads_of(P, uref, "1")
        vx, vy = g.x - 0.2, g.y + 2.6
        rt.track(g.x, g.y, vx, vy, 0.4, "GND")
        rt.via(vx, vy, "GND")
    for uref in [f"U{n}" for n in range(11, 19)]:
        g = pads_of(P, uref, "1")
        vx, vy = g.x, g.y + 1.35
        rt.track(g.x, g.y, vx, vy, 0.3, "GND")
        rt.via(vx, vy, "GND")
    for ref in (
        [f"R{n}" for n in (10, 20, 30, 40)]
        + [f"R{n}" for n in range(101, 109)]
        + [f"C{n}" for n in (10, 20, 30, 40)]
        + [f"C{n}" for n in range(101, 109)]
    ):
        # R*: pad1 GND; C*: pad2 GND
        num = "1" if ref.startswith("R") else "2"
        try:
            g = pads_of(P, ref, num)
        except KeyError:
            continue
        if g.net != "GND":
            continue
        vx, vy = g.x, g.y + (1.3 if ref.startswith("R") else -1.3)
        rt.track(g.x, g.y, vx, vy, 0.25, "GND")
        rt.via(vx, vy, "GND")

    # GND plane is the B.Cu zone; only local F stubs + vias (no B.Cu GND buses
    # that would cross EN/IS/ADIO long-haul).


def route_hp_out(rt: Router, P):
    """F.Cu to unique columns; F vertical crosses EN B band; B.Cu into J1 pins."""
    esc_y = [71.55, 72.05, 84.15, 84.70]
    ax = [73.10, 72.55, 72.00, 71.45]  # south nets → west columns
    for idx, (net, uref, jpins) in enumerate(HP_OUT):
        outs = [pads_of(P, uref, n) for n in ("5", "6", "7")]
        ys = [p.y for p in outs]
        xs = [p.x for p in outs]
        cy = sum(ys) / len(ys)
        rt.track(min(xs), cy, max(xs), cy, 1.0, net)
        for p in outs:
            rt.track(p.x, p.y, p.x, cy, 0.8, net)
        cx = sum(xs) / 3
        ey, col = esc_y[idx], ax[idx]
        rt.manh([(cx, cy), (cx, ey), (col, ey)], 0.8, net)
        rt.via(col, ey, net)
        # F-hop only the EN B band (y=66.9–71.1); rest of the north run is B.Cu
        hop_s, hop_n = 71.22, 66.78
        if ey > hop_s + 0.2:
            rt.track(col, ey, col, hop_s, 0.6, net, "B.Cu")
            rt.via(col, hop_s, net)
        rt.track(col, hop_s, col, hop_n, 0.6, net, "F.Cu")
        rt.via(col, hop_n, net)
        jps = [pads_of(P, "J1", jp) for jp in jpins]
        mid_y = sum(p.y for p in jps) / 2
        rt.manh_vh([(col, hop_n), (col, mid_y)], 0.7, net, "B.Cu")
        rt.via(col, mid_y, net)
        for jp in jps:
            rt.manh([(col, mid_y), (jp.x, mid_y), (jp.x, jp.y)], 0.8, net)


def route_adio_out(rt: Router, P):
    """Local F.Cu at the chip; exclusive B.Cu columns east of the SuperSeal pin field."""
    for idx, (net, uref, jpin, rp) in enumerate(ADIO_OUT):
        outs = [pads_of(P, uref, n) for n in ("8", "9", "10", "12", "13", "14")]
        ox = outs[0].x
        ys = [p.y for p in outs]
        rt.track(ox, min(ys), ox, max(ys), 0.45, net)
        for p in outs:
            rt.track(p.x, p.y, ox, p.y, 0.3, net)
        r = pads_of(P, rp, "2")
        # PU tap into the OUT bar (not a dangling stub at PU Y)
        mid_y = (min(ys) + max(ys)) / 2
        rt.manh([(r.x, r.y), (ox, r.y), (ox, mid_y)], 0.3, net)
        j = pads_of(P, "J1", jpin)
        # B column east of pin field; F-hop across EN B highways at y=66.9–71.1
        col = 68.05 + idx * 0.32
        rt.track(ox, mid_y, col, mid_y, 0.3, net)
        rt.via(col, mid_y, net)
        hop_s, hop_n = 72.15, 65.35
        rt.manh_vh([(col, mid_y), (col, hop_s)], 0.28, net, "B.Cu")
        rt.via(col, hop_s, net)
        rt.track(col, hop_s, col, hop_n, 0.28, net, "F.Cu")
        rt.via(col, hop_n, net)
        rt.manh_vh([(col, hop_n), (col, j.y), (j.x, j.y)], 0.28, net, "B.Cu")
        rt.via(j.x, j.y, net)


def route_en(rt: Router, P):
    """Exclusive lanes around J1: 6 B + 6 F columns in the MCU–SuperSeal gap."""
    w = 0.22
    for idx, (net, uref, pins, mpad) in enumerate(EN_MAP):
        coords = [pads_of(P, uref, pn) for pn in pins]
        if len(coords) > 1:
            rt.track(coords[0].x, coords[0].y, coords[1].x, coords[1].y, 0.25, net)
        sx, sy = coords[0].x, coords[0].y
        m = pads_of(P, "M1000", mpad)
        use_f_gap = idx >= 6
        # South highways get west gap columns so a westbound never crosses a
        # neighbour's northbound (verticals only exist north of their own hwy).
        if not use_f_gap:
            gap_x = 46.50 - idx * 0.28
        else:
            gap_x = 46.64 - (idx - 6) * 0.28
        hwy = 66.90 + idx * 0.38  # 66.90 .. 71.08 (south of courtyard y=65)
        vx, vy = sx - 1.25, sy
        rt.track(sx, sy, vx, vy, w, net)
        rt.via(vx, vy, net)
        # B west on private hwy into the gap
        rt.manh_vh([(vx, vy), (vx, hwy), (gap_x, hwy)], w, net, "B.Cu")
        if use_f_gap:
            rt.via(gap_x, hwy, net)
            rt.manh_vh([(gap_x, hwy), (gap_x, m.y), (m.x, m.y)], w, net, "F.Cu")
        else:
            rt.manh_vh([(gap_x, hwy), (gap_x, m.y), (m.x, m.y)], w, net, "B.Cu")


def route_is_local(rt: Router, P):
    w = 0.22
    for net, uref, upin, rref, cref in IS_LOCAL:
        u = pads_of(P, uref, upin)
        r = pads_of(P, rref, "2")
        c = pads_of(P, cref, "1")
        if uref in {"U1", "U2", "U3", "U4"}:
            # HP IS: private vertical east of R (away from GND pad1), unique per channel
            bus_y = u.y + 2.55
            vx = r.x + 1.20 + (0.0 if uref in {"U1", "U2"} else 0.55)
            rt.manh([(u.x, u.y), (u.x, bus_y), (vx, bus_y), (vx, r.y), (r.x, r.y)], w, net)
            rt.manh([(r.x, r.y), (c.x, r.y), (c.x, c.y)], w, net)
        else:
            # ADIO IS under package on B (F pin-row is packed)
            rt.via(u.x, u.y, net)
            rt.manh([(u.x, u.y), (r.x, u.y), (r.x, r.y)], w, net, "B.Cu")
            rt.via(r.x, r.y, net)
            rt.manh([(r.x, r.y), (c.x, r.y), (c.x, c.y)], w, net)


def route_is_long(rt: Router, P):
    """F.Cu private column to a unique highway, then B.Cu west to S pads (EN is B further north)."""
    w = 0.20
    for idx, (net, rref, mpad) in enumerate(IS_LONG):
        r = pads_of(P, rref, "2")
        m = pads_of(P, "M1000", mpad)
        hwy = 73.15 + idx * 0.45
        if r.x < 78:
            col = 69.60 - idx * 0.40
        else:
            col = 98.40 + (idx % 4) * 0.55
        rt.manh([(r.x, r.y), (col, r.y), (col, hwy)], w, net)
        rt.via(col, hwy, net)
        rt.manh([(col, hwy), (m.x, hwy), (m.x, m.y)], w, net, "B.Cu")


def route_system(rt: Router, P):
    # IGN_SW J1.4 → R1.1 (local, east of wall)
    jign = pads_of(P, "J1", "4")
    r1a = pads_of(P, "R1", "1")
    r1b = pads_of(P, "R1", "2")
    r2a = pads_of(P, "R2", "1")
    rt.manh([(jign.x, jign.y), (r1a.x, jign.y), (r1a.x, r1a.y)], 0.4, "IGN_SW")
    rt.manh([(r1b.x, r1b.y), (r2a.x, r1b.y), (r2a.x, r2a.y)], 0.3, "IN_VIGN")
    # IN_VIGN → N26 via north corridor B
    n26 = pads_of(P, "M1000", "N26")
    vx, vy = r1b.x - 2.2, r1b.y
    rt.track(r1b.x, r1b.y, vx, vy, 0.25, "IN_VIGN")
    rt.via(vx, vy, "IN_VIGN")
    rt.manh([(vx, vy), (vx, 4.0), (n26.x, 4.0), (n26.x, n26.y)], 0.25, "IN_VIGN", "B.Cu")
    rt.via(n26.x, n26.y, "IN_VIGN")

    # CAN: W pads (MCU west) → north B → J1 pins 3/10 through north corridor
    for net, mpad, jpin, lane_y in (("CANH", "W12", "3", 5.2), ("CANL", "W13", "10", 6.0)):
        m = pads_of(P, "M1000", mpad)
        j = pads_of(P, "J1", jpin)
        rt.track(m.x, m.y, 1.4, m.y, 0.3, net)
        rt.via(1.4, m.y, net)
        rt.manh([(1.4, m.y), (1.4, lane_y), (j.x + 3.0, lane_y)], 0.3, net, "B.Cu")
        rt.via(j.x + 3.0, lane_y, net)
        rt.manh([(j.x + 3.0, lane_y), (j.x + 3.0, j.y), (j.x, j.y)], 0.3, net)

    # SENSOR_5V: skirt east/south so we do not run B.Cu through the EN/IS field
    e38 = pads_of(P, "M1000", "E38")
    n30 = pads_of(P, "M1000", "N30")
    w2 = pads_of(P, "M1000", "W2")
    bus_n, bus_s, bus_e = 7.20, 91.15, 102.15
    rt.track(e38.x, e38.y, 46.8, e38.y, 0.35, "SENSOR_5V")
    rt.via(46.8, e38.y, "SENSOR_5V")
    rt.manh([(1.6, bus_n), (bus_e, bus_n), (bus_e, bus_s)], 0.35, "SENSOR_5V", "B.Cu")
    rt.manh([(46.8, e38.y), (46.8, bus_n)], 0.35, "SENSOR_5V", "B.Cu")
    rt.via(n30.x, n30.y, "SENSOR_5V")
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
    for r in range(201, 209):
        rp = pads_of(P, f"R{r}", "1")
        side = rp.x - 1.7
        rt.track(rp.x, rp.y, side, rp.y, 0.25, "SENSOR_5V")
        rt.via(side, rp.y, "SENSOR_5V")
        rt.manh([(side, rp.y), (side, bus_s), (bus_e, bus_s)], 0.25, "SENSOR_5V", "B.Cu")

    # SENSOR_GND dedicated (do not via-stitch to GND pour except isolated tracks)
    a = pads_of(P, "J1", "6")
    b = pads_of(P, "J1", "12")
    e39 = pads_of(P, "M1000", "E39")
    w1 = pads_of(P, "M1000", "W1")
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
    """Union-find pads of the same net via tracks/vias (endpoint snap 0.45 mm)."""
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

    # snap same-net endpoints
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

    # T-junctions: a segment endpoint sitting on another same-net/same-layer (or via) segment
    def on_seg(px, py, x1, y1, x2, y2, half):
        if abs(y1 - y2) < 1e-3:
            return abs(py - y1) <= half and min(x1, x2) - half <= px <= max(x1, x2) + half
        if abs(x1 - x2) < 1e-3:
            return abs(px - x1) <= half and min(y1, y2) - half <= py <= max(y1, y2) + half
        return False

    for i, (x1, y1, x2, y2, lay, net, w) in enumerate(rt.segs):
        half = w / 2 + 0.35
        for j, (a1, b1, a2, b2, lay2, net2, w2) in enumerate(rt.segs):
            if j == i or net != net2:
                continue
            if lay != lay2:
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
    # zone-assisted: pads inside VBAT F east / GND B board
    for i, p in enumerate(pads):
        if p.net == "VBAT" and p.x >= 67.0 and 1.0 <= p.y <= 92.0:
            union(("pad", i), ("zone", "VBAT"))
        if p.net == "GND" and p.kind == "thru":
            union(("pad", i), ("zone", "GND"))
        # SMD GND with a nearby via is pour-complete after fill
        if p.net == "GND":
            for x, y, net in rt.vias:
                if net == "GND" and abs(x - p.x) < 2.5 and abs(y - p.y) < 2.5:
                    union(("pad", i), ("zone", "GND"))
                    break

    # connect GND vias to GND zone (B pour)
    for i, (x, y, net) in enumerate(rt.vias):
        if net == "GND":
            union(("via", i), ("zone", "GND"))
        if net == "VBAT" and x >= 66:
            union(("via", i), ("zone", "VBAT"))

    open_nets = {}
    grouped = defaultdict(list)
    for i, p in enumerate(pads):
        if not p.net:
            continue
        grouped[p.net].append(i)
    for net, idxs in grouped.items():
        roots = {find(("pad", i)) for i in idxs}
        if len(roots) > 1:
            open_nets[net] = len(roots)
    return open_nets


def new_zones() -> list[str]:
    """Non-overlapping pours. GND F east island removed (B.Cu plane owns GND)."""
    z = []
    z.append(zone_rect(2, "GND", "B.Cu", uid("z-gnd-b"), [(1, 1), (103, 1), (103, 92), (1, 92)]))
    # VBAT F: power-entry north (stops before M6− y=31) + HP/ADIO east strip
    z.append(
        zone_rect(
            1,
            "VBAT",
            "F.Cu",
            uid("z-vbat-entry"),
            [(67, 1), (103, 1), (103, 30), (67, 30)],
            priority=1,
        )
    )
    z.append(
        zone_rect(
            1,
            "VBAT",
            "F.Cu",
            uid("z-vbat-hp"),
            [(74, 50), (103, 50), (103, 74), (74, 74)],
            priority=1,
        )
    )
    z.append(
        zone_rect(
            1,
            "VBAT",
            "F.Cu",
            uid("z-vbat-adio"),
            [(67, 79), (103, 79), (103, 92), (67, 92)],
            priority=1,
        )
    )
    # small GND F island around M6− only (does not overlap VBAT islands)
    z.append(
        zone_rect(
            2,
            "GND",
            "F.Cu",
            uid("z-gnd-m6"),
            [(83, 31), (103, 31), (103, 47), (83, 47)],
            priority=1,
        )
    )
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
    scale = 8  # px/mm
    w, h = int(BOARD_W * scale) + 8, int(BOARD_H * scale) + 8

    def xy(x, y):
        return int(x * scale) + 4, int(y * scale) + 4

    img = Image.new("RGB", (w, h), (18, 18, 22))
    dr = ImageDraw.Draw(img)
    dr.rectangle([xy(0, 0), xy(BOARD_W, BOARD_H)], outline=(80, 80, 90), width=2)
    # EMI line
    dr.line([xy(45.5, 4), xy(45.5, 89)], fill=(90, 90, 40), width=1)
    colors = {
        "VBAT": (200, 60, 60),
        "GND": (60, 80, 200),
        "F.Cu": (180, 50, 50),
        "B.Cu": (50, 90, 200),
    }
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
        r = 2
        cx, cy = xy(x, y)
        dr.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(200, 200, 200))
    for p in pads:
        if p.ref in {"J1", "J2", "M1000", "U1", "U2", "U3", "U4"} or p.ref.startswith("U1"):
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
    header, inner, _ = m.group(1), m.group(2), m.group(3)
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
    for it in items:
        head = item_head(it)
        if head in skipped:
            skipped[head] += 1
            continue
        if head == "footprint":
            ref = fp_ref(it) or "?"
            pads.extend(parse_pads(it, ref))
            fp_count += 1
        new_items.append(it)

    if fp_count < 50:
        sys.exit(f"too few footprints ({fp_count}) — abort")
    if skipped["segment"] + skipped["via"] > 50:
        print(f"warn: removed existing copper segments={skipped['segment']} vias={skipped['via']}")

    rt = Router()
    route_power(rt, pads)
    route_hp_out(rt, pads)
    route_adio_out(rt, pads)
    route_is_local(rt, pads)
    route_en(rt, pads)
    route_is_long(rt, pads)
    route_system(rt, pads)

    hops = apply_hops(rt, max_hops=0)
    crosses = count_crossings(rt)
    open_nets = connectivity(pads, rt)

    # rebuild PCB
    zones = new_zones()
    copper_txt = "".join(rt.copper)
    inner_out = "\n".join(new_items) + "\n" + "\n".join(zones) + "\n" + copper_txt
    pcb_out = header + inner_out + ")\n"
    if pcb_out.count("\n\t(footprint ") < 50:
        sys.exit("refusing to write broken pcb")
    if "(kicad_pcb" not in pcb_out[:40]:
        sys.exit("header lost")

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
                f"hops={hops}",
                f"open_nets={len(open_nets)}",
                f"en_is_open={len(en_open)}",
                f"gnd_pad_islands_before_pour={gnd_islands}",
                f"strategy=sexp_104x93_emi_split_exclusive_en_b_is_f",
                "kicad_cli=unavailable",
                "hellcore=untouched",
            ]
        )
        + "\n"
    )
    lines = ["# Leftover unconnected nets (pad islands after track/via/zone-outline snap)", ""]
    lines.append("## GND")
    lines.append(
        f"- GND: {gnd_islands} pad islands before zone fill; carrier pads are via-stitched to the B.Cu pour (M1000 G pads are module-internal)."
    )
    lines.append("")
    lines.append("## Critical signal nets")
    if leftover_crit:
        for n, k in leftover_crit.items():
            lines.append(f"- {n}: {k} islands")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Other (DIR, PU FET, V-sense, USB-on-module, unused MM144)")
    if leftover_other:
        for n, k in leftover_other.items():
            lines.append(f"- {n}: {k} islands")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("USBID/USBM/USBP live only on M1000 (USB-C is on the module).")
    lines.append("OUT_IO9–13 / IO1–3 PU FET not stuffed (BOARD.md TODO).")
    lines.append("IN_TPS/PPS/CLT/IAT/AT* ADIO V-sense dividers not stuffed.")
    lines.append("OUT_IO1–4 HP DIR not stuffed.")
    LEFTOVER.write_text("\n".join(lines) + "\n")

    art = Path("/opt/cursor/artifacts/copper_f_b_overview.png")
    plot_png(rt, pads, art)
    # also local copy
    plot_png(rt, pads, ROOT / "scripts" / "copper_overview.png")

    print(f"footprints={fp_count} tracks={rt.nseg} vias={rt.nvia} hops={hops}")
    sig_cross = [(a, b, l) for a, b, l in crosses if a not in ("VBAT", "GND") and b not in ("VBAT", "GND")]
    print(f"signal_signal_crossings={len(sig_cross)}")
    if crosses[:12]:
        from collections import Counter

        print("cross sample", Counter((a, b, l) for a, b, l in crosses[:40]))
    print(f"open_nets={len(open_nets)} en_is_open={en_open}")
    print("crit leftover", leftover_crit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
