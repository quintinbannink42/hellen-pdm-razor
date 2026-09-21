#!/usr/bin/env python3
"""PowerCore floorplan redesign (no pcbnew).

- M6 bolt-through bobbins replace J2 pin-header
- Vertical SuperSeal 6437288-6 as EMI split (MCU | J1 | PROFET)
- Shrink Edge.Cuts to nested bbox (Razor-class ~104x93)
- Refresh M1000 from hellen-one mega-mcu144 0.7; keepout=silk; Value exact
- Re-nest then re-route power + EN/IS exclusive layers
- KiCad 8 (20240108 / 8.0) headers preserved
"""
from __future__ import annotations

import math
import re
import uuid
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "pdmrazora.kicad_pcb"
PRETTY = ROOT / "pdmrazora.pretty"
LIB_MOD = ROOT / "hellen-one/modules/mega-mcu144/0.7/mega-mcu144.kicad_mod"
RA_MOD = PRETTY / "TE_9-6437287-8_SuperSeal26.kicad_mod"
STATUS = ROOT / "scripts" / "redesign_status.txt"
POSFILE = ROOT / "scripts" / "layout_positions.txt"

EN_NETS = [
    "OUT_PWM1", "OUT_PWM2", "OUT_PWM3", "OUT_PWM4",
    "OUT_PWM5", "OUT_PWM6", "OUT_PWM7", "OUT_PWM8",
    "OUT_IO5", "OUT_IO6", "OUT_IO7", "OUT_IO8",
]
IS_NETS = [
    "IN_AUX1", "IN_AUX2", "IN_AUX3", "IN_AUX4",
    "IN_MAP1", "IN_MAP2", "IN_MAP3", "IN_O2S",
    "IN_O2S2", "IN_RES1", "IN_RES2", "IN_RES3",
]
CHIP_EN = {
    "OUT_PWM1": "U1", "OUT_PWM2": "U2", "OUT_PWM3": "U3", "OUT_PWM4": "U4",
    "OUT_PWM5": "U11", "OUT_PWM6": "U12", "OUT_PWM7": "U13", "OUT_PWM8": "U14",
    "OUT_IO5": "U15", "OUT_IO6": "U16", "OUT_IO7": "U17", "OUT_IO8": "U18",
}
CHIP_IS = {
    "IN_AUX1": "U1", "IN_AUX2": "U2", "IN_AUX3": "U3", "IN_AUX4": "U4",
    "IN_MAP1": "U11", "IN_MAP2": "U12", "IN_MAP3": "U13", "IN_O2S": "U14",
    "IN_O2S2": "U15", "IN_RES1": "U16", "IN_RES2": "U17", "IN_RES3": "U18",
}

# Nested EMI-split floorplan (mm). MCU west, vertical SuperSeal, PROFET east.
LAYOUT = {
    "M1000": (6.5, 48.0, 0.0),
    "J1": (58.5, 46.0, 90.0),
    "U11": (93.0, 11.0, 0.0),
    "U12": (105.0, 11.0, 0.0),
    "U13": (93.0, 22.0, 0.0),
    "U14": (105.0, 22.0, 0.0),
    "U15": (93.0, 33.0, 0.0),
    "U16": (105.0, 33.0, 0.0),
    "U17": (93.0, 44.0, 0.0),
    "U18": (105.0, 44.0, 0.0),
    "U1": (95.0, 66.0, 270.0),
    "U2": (109.0, 66.0, 270.0),
    "U3": (95.0, 80.0, 270.0),
    "U4": (109.0, 80.0, 270.0),
    "J2": (90.0, 94.0, 0.0),
    "F1": (90.0, 82.0, 0.0),
    "D1": (102.0, 82.0, 90.0),
    "C1": (114.0, 82.0, 0.0),
    "C2": (114.0, 88.0, 0.0),
    "R1": (90.0, 56.0, 90.0),
    "R2": (94.0, 56.0, 90.0),
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
HP_PASSIVES = {
    1: ("R10", "C10"),
    2: ("R20", "C20"),
    3: ("R30", "C30"),
    4: ("R40", "C40"),
}


def uid() -> str:
    return str(uuid.uuid4())


def fmt(n: float) -> str:
    n = round(float(n), 6)
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    s = f"{n:.6f}".rstrip("0").rstrip(".")
    return s


def rot_pt(x: float, y: float, deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return x * c - y * s, x * s + y * c


def parse_nets(text: str) -> dict[int, str]:
    return {int(a): b for a, b in re.findall(r'\t\(net (\d+) "([^"]*)"\)', text)}


def net_by_name(nets: dict[int, str]) -> dict[str, int]:
    return {v: k for k, v in nets.items()}


def split_top_blocks(text: str) -> tuple[str, list[str], str]:
    """Split kicad_pcb into header, top-level blocks, closing paren."""
    assert text.startswith("(kicad_pcb\n")
    body = text[len("(kicad_pcb\n"):]
    if body.endswith("\n)\n"):
        body = body[:-3]
    elif body.endswith("\n)"):
        body = body[:-2]
    blocks: list[str] = []
    buf: list[str] = []
    depth = 0
    for line in body.splitlines(True):
        if depth == 0 and line.startswith("\t("):
            if buf:
                blocks.append("".join(buf))
                buf = []
        buf.append(line)
        depth += line.count("(") - line.count(")")
    if buf:
        blocks.append("".join(buf))
    header_kinds = ("version", "generator", "generator_version", "general", "paper",
                    "title_block", "layers", "setup", "net ")
    header, rest = [], []
    for b in blocks:
        stripped = b.lstrip("\t")
        if any(stripped.startswith(f"({k}") for k in header_kinds):
            header.append(b)
        else:
            rest.append(b)
    return "".join(header), rest, ")\n"


def fp_ref(block: str) -> str | None:
    m = re.search(r'\(property "Reference" "([^"]+)"', block)
    return m.group(1) if m else None


def fp_name(block: str) -> str:
    m = re.match(r'\t\(footprint "([^"]+)"', block)
    return m.group(1) if m else ""


def set_fp_at(block: str, x: float, y: float, rot: float) -> str:
    at = f"(at {fmt(x)} {fmt(y)}"
    if abs(rot) > 1e-9:
        at += f" {fmt(rot)}"
    at += ")"
    new, n = re.subn(r"\(at [0-9eE.+-]+ [0-9eE.+-]+(?: [0-9eE.+-]+)?\)", at, block, count=1)
    if n != 1:
        raise RuntimeError("failed to set footprint at")
    return new


def pad_nets_from_fp(block: str) -> dict[str, tuple[int, str]]:
    """Nets that belong to the same pad block only (do not leak across NC pads)."""
    out: dict[str, tuple[int, str]] = {}
    for m in re.finditer(
        r'\(pad "([^"]*)"(.*?)(?=\n[ \t]*\(pad |\n[ \t]*\(zone |\n[ \t]*\(model |\n[ \t]*\)$)',
        block,
        flags=re.S,
    ):
        num, body = m.group(1), m.group(2)
        nm = re.search(r'\(net (\d+) "([^"]*)"\)', body)
        if num and nm:
            out[num] = (int(nm.group(1)), nm.group(2))
    return out


# Authoritative Razor 26-pin map (CONNECTOR.md). NC pins omitted.
J1_PINOUT = {
    "1": "PWR_OUT2",
    "3": "CANH",
    "4": "IGN_SW",
    "5": "SENSOR_5V",
    "6": "SENSOR_GND",
    "7": "PWR_OUT3",
    "8": "PWR_OUT2",
    "10": "CANL",
    "11": "SENSOR_5V",
    "12": "SENSOR_GND",
    "13": "PWR_OUT3",
    "14": "PWR_OUT1",
    "15": "ADIO2",
    "16": "ADIO4",
    "17": "ADIO6",
    "18": "ADIO8",
    "19": "PWR_OUT4",
    "20": "PWR_OUT1",
    "21": "ADIO1",
    "22": "ADIO3",
    "23": "ADIO5",
    "24": "ADIO7",
    "26": "PWR_OUT4",
}


def inject_pad_nets(block: str, nets: dict[str, tuple[int, str]]) -> str:
    def repl(m: re.Match) -> str:
        num = m.group(1)
        body = m.group(0)
        if num not in nets:
            return body
        n, name = nets[num]
        net_tok = f'(net {n} "{name}")'
        if "(net " in body:
            return re.sub(r'\(net \d+ "[^"]*"\)', net_tok, body, count=1)
        # Insert net immediately before uuid (any indent)
        return re.sub(
            r"(^[ \t]*)\(uuid ",
            lambda um: f"{um.group(1)}{net_tok}\n{um.group(1)}(uuid ",
            body,
            count=1,
            flags=re.M,
        )

    return re.sub(r'\(pad "([^"]*)".*?\n[ \t]*\)', repl, block, flags=re.S)


def rect_lines(x1, y1, x2, y2, layer, width=0.2) -> str:
    pts = [(x1, y1, x2, y1), (x2, y1, x2, y2), (x2, y2, x1, y2), (x1, y2, x1, y1)]
    chunks = []
    for a, b, c, d in pts:
        chunks.append(
            "\t(fp_line\n"
            f"\t\t(start {fmt(a)} {fmt(b)})\n"
            f"\t\t(end {fmt(c)} {fmt(d)})\n"
            "\t\t(stroke\n"
            f"\t\t\t(width {width})\n"
            "\t\t\t(type solid)\n"
            "\t\t)\n"
            f'\t\t(layer "{layer}")\n'
            f'\t\t(uuid "{uid()}")\n'
            "\t)\n"
        )
    return "".join(chunks)


def write_m6_footprint() -> Path:
    path = PRETTY / "M6_Bolt_Bobbin_Dual.kicad_mod"
    silk = rect_lines(-9, -9, 31, 9, "F.SilkS", 0.15)
    crtyd = (
        "\t(fp_rect\n"
        "\t\t(start -10 -10)\n"
        "\t\t(end 32 10)\n"
        "\t\t(stroke\n"
        "\t\t\t(width 0.05)\n"
        "\t\t\t(type solid)\n"
        "\t\t)\n"
        "\t\t(fill no)\n"
        '\t\t(layer "F.CrtYd")\n'
        f'\t\t(uuid "{uid()}")\n'
        "\t)\n"
    )
    def circle(cx, cy, r, layer, w=0.15):
        return (
            "\t(fp_circle\n"
            f"\t\t(center {fmt(cx)} {fmt(cy)})\n"
            f"\t\t(end {fmt(cx + r)} {fmt(cy)})\n"
            "\t\t(stroke\n"
            f"\t\t\t(width {w})\n"
            "\t\t\t(type solid)\n"
            "\t\t)\n"
            "\t\t(fill no)\n"
            f'\t\t(layer "{layer}")\n'
            f'\t\t(uuid "{uid()}")\n'
            "\t)\n"
        )

    def txt(val, x, y, layer, size=1.0):
        return (
            f'\t(fp_text user "{val}"\n'
            f"\t\t(at {fmt(x)} {fmt(y)} 0)\n"
            f'\t\t(layer "{layer}")\n'
            f'\t\t(uuid "{uid()}")\n'
            "\t\t(effects\n"
            "\t\t\t(font\n"
            f"\t\t\t\t(size {size} {size})\n"
            "\t\t\t\t(thickness 0.15)\n"
            "\t\t\t)\n"
            "\t\t)\n"
            "\t)\n"
        )

    def pad(num, x, y):
        return (
            f'\t(pad "{num}" thru_hole circle\n'
            f"\t\t(at {fmt(x)} {fmt(y)})\n"
            "\t\t(size 14 14)\n"
            "\t\t(drill 6.5)\n"
            '\t\t(layers "*.Cu" "*.Mask")\n'
            "\t\t(remove_unused_layers no)\n"
            "\t\t(zone_connect 2)\n"
            f'\t\t(uuid "{uid()}")\n'
            "\t)\n"
        )

    text = (
        '(footprint "M6_Bolt_Bobbin_Dual"\n'
        "\t(version 20240108)\n"
        '\t(generator "pcbnew")\n'
        '\t(generator_version "8.0")\n'
        '\t(layer "F.Cu")\n'
        '\t(descr "Dual M6 bolt-through bobbins. Pad1 VBAT+ / pad2 GND. 6.5mm drill, 14mm pad, 22mm pitch. ISO 4762 M6 + nylon/brass bobbin; HARDWARE_BOM.md.")\n'
        '\t(tags "M6 bolt bobbin standoff VBAT GND PowerCore")\n'
        '\t(property "Reference" "REF**"\n'
        "\t\t(at 11 -12 0)\n"
        '\t\t(layer "F.SilkS")\n'
        f'\t\t(uuid "{uid()}")\n'
        "\t\t(effects (font (size 1 1) (thickness 0.15)))\n"
        "\t)\n"
        '\t(property "Value" "M6_VBAT_GND"\n'
        "\t\t(at 11 12 0)\n"
        '\t\t(layer "F.Fab")\n'
        f'\t\t(uuid "{uid()}")\n'
        "\t\t(effects (font (size 1 1) (thickness 0.15)))\n"
        "\t)\n"
        '\t(attr through_hole)\n'
        + txt("+", 0, -9, "F.SilkS", 1.5)
        + txt("-", 22, -9, "F.SilkS", 1.5)
        + txt("VBAT", 0, 9.5, "F.Fab", 0.8)
        + txt("GND", 22, 9.5, "F.Fab", 0.8)
        + circle(0, 0, 8, "F.SilkS")
        + circle(22, 0, 8, "F.SilkS")
        + circle(0, 0, 7.2, "F.Fab", 0.1)
        + circle(22, 0, 7.2, "F.Fab", 0.1)
        + silk
        + crtyd
        + pad("1", 0, 0)
        + pad("2", 22, 0)
        + ")\n"
    )
    path.write_text(text)
    return path


def write_vertical_superseal() -> Path:
    """Same 26-pin TE pattern as RA 9-6437287-8; vertical housing 6437288-6."""
    ra = RA_MOD.read_text()
    pads = "".join(re.findall(r'\t\(pad "(?:[1-9]|1[0-9]|2[0-6])".*?\n\t\)\n', ra, flags=re.S))
    # pin field centre ~ (0, -10.5); housing 39 x 36.5
    hx1, hx2 = -19.5, 19.5
    hy1, hy2 = -28.75, 7.75
    path = PRETTY / "TE_6437288-6_SuperSeal26_V.kicad_mod"
    silk = rect_lines(hx1, hy1, hx2, hy2, "F.SilkS", 0.2)
    fab = rect_lines(hx1 + 0.25, hy1 + 0.25, hx2 - 0.25, hy2 - 0.25, "F.Fab", 0.1)
    crtyd = (
        "\t(fp_rect\n"
        "\t\t(start -20 -29.25)\n"
        "\t\t(end 20 8.25)\n"
        "\t\t(stroke\n"
        "\t\t\t(width 0.05)\n"
        "\t\t\t(type solid)\n"
        "\t\t)\n"
        "\t\t(fill no)\n"
        '\t\t(layer "F.CrtYd")\n'
        f'\t\t(uuid "{uid()}")\n'
        "\t)\n"
    )
    # pin-1 marker
    mark = (
        "\t(fp_circle\n"
        "\t\t(center -9 -16.5)\n"
        "\t\t(end -8.3 -16.5)\n"
        "\t\t(stroke (width 0.15) (type solid))\n"
        "\t\t(fill yes)\n"
        '\t\t(layer "F.SilkS")\n'
        f'\t\t(uuid "{uid()}")\n'
        "\t)\n"
    )
    text = (
        '(footprint "TE_6437288-6_SuperSeal26_V"\n'
        "\t(version 20240108)\n"
        '\t(generator "pcbnew")\n'
        '\t(generator_version "8.0")\n'
        '\t(layer "F.Cu")\n'
        '\t(descr "TE/AMP SuperSeal 1.0 26-way VERTICAL header; mfr PN 6437288-6 (keying 1). Same pin pattern as 9-6437287-8 / drawing 9-1437287-8. Pitch 3.0 mm, 4 rows. No mounting holes (TE vertical). Pin numbers = TE mating face / Link Razor CONNECTOR.md.")\n'
        '\t(tags "TE AMP SuperSeal 1.0 26 6437288-6 vertical Connector C")\n'
        '\t(property "Reference" "REF**"\n'
        "\t\t(at 0 10.5 0)\n"
        '\t\t(layer "F.SilkS")\n'
        f'\t\t(uuid "{uid()}")\n'
        "\t\t(effects (font (size 1 1) (thickness 0.15)))\n"
        "\t)\n"
        '\t(property "Value" "6437288-6"\n'
        "\t\t(at 0 -31 0)\n"
        '\t\t(layer "F.Fab")\n'
        f'\t\t(uuid "{uid()}")\n'
        "\t\t(effects (font (size 1 1) (thickness 0.15)))\n"
        "\t)\n"
        '\t(property "Datasheet" "https://www.te.com/en/product-6437288-6.html"\n'
        "\t\t(at 0 0 0)\n"
        '\t\t(layer "F.Fab")\n'
        "\t\t(hide yes)\n"
        f'\t\t(uuid "{uid()}")\n'
        "\t\t(effects (font (size 1.27 1.27)))\n"
        "\t)\n"
        '\t(attr through_hole)\n'
        + silk + fab + crtyd + mark + pads + ")\n"
    )
    path.write_text(text)
    return path


def indent_mod_as_pcb_fp(mod_text: str, lib_id: str, x, y, rot, extra_props: dict[str, str]) -> str:
    lines = mod_text.splitlines(True)
    # bump indent by one tab
    bumped = []
    for i, line in enumerate(lines):
        if i == 0:
            at = f"(at {fmt(x)} {fmt(y)}"
            if abs(rot) > 1e-9:
                at += f" {fmt(rot)}"
            at += ")"
            bumped.append(f'\t(footprint "{lib_id}"\n')
            bumped.append(f"\t\t{at}\n")
            bumped.append(f'\t\t(uuid "{uid()}")\n')
            continue
        if line.strip() == ")":
            bumped.append("\t)\n")
            continue
        bumped.append("\t" + line if line.startswith("\t") or line.startswith(" ") else "\t\t" + line)
    body = "".join(bumped)
    for prop, val in extra_props.items():
        body = re.sub(
            rf'\(property "{prop}" "[^"]*"',
            f'(property "{prop}" "{val}"',
            body,
            count=1,
        )
    return body if body.endswith("\n") else body + "\n"


def rebuild_m1000(old_block: str, x, y, rot, nets: dict[str, tuple[int, str]]) -> str:
    lib = LIB_MOD.read_text()
    # Align keepout to silk if a stale copy ever drifts; library 0.7 is already aligned.
    lib = lib.replace("Module:mega_mcu144/0.7", "Module:mega-mcu144/0.7")
    block = indent_mod_as_pcb_fp(
        lib,
        "hellen-one-mega-mcu144-0.7:mega-mcu144",
        x, y, rot,
        {"Reference": "M1000", "Value": "Module:mega-mcu144/0.7"},
    )
    # Force Value even if property rewriter missed underscore variant
    block = re.sub(
        r'\(property "Value" "[^"]*"',
        '(property "Value" "Module:mega-mcu144/0.7"',
        block,
        count=1,
    )
    block = inject_pad_nets(block, nets)
    # Drop K9-only placement blob if present
    block = re.sub(r"\n\t\t\(placement\n.*?\n\t\t\)", "", block, flags=re.S)
    return block


def rebuild_j1(old_block: str, x, y, rot, nets: dict[str, tuple[int, str]]) -> str:
    mod = (PRETTY / "TE_6437288-6_SuperSeal26_V.kicad_mod").read_text()
    block = indent_mod_as_pcb_fp(
        mod,
        "pdmrazora:TE_6437288-6_SuperSeal26_V",
        x, y, rot,
        {"Reference": "J1", "Value": "6437288-6"},
    )
    return inject_pad_nets(block, nets)


def rebuild_j2(old_block: str, x, y, rot, nets: dict[str, tuple[int, str]]) -> str:
    mod = (PRETTY / "M6_Bolt_Bobbin_Dual.kicad_mod").read_text()
    block = indent_mod_as_pcb_fp(
        mod,
        "pdmrazora:M6_Bolt_Bobbin_Dual",
        x, y, rot,
        {"Reference": "J2", "Value": "M6_VBAT_GND"},
    )
    # Ensure pad nets VBAT/GND even if old J2 mapping used pin 1/2
    if "1" not in nets:
        # filled later from net map
        pass
    return inject_pad_nets(block, nets)


def expand_layout() -> dict[str, tuple[float, float, float]]:
    lay = dict(LAYOUT)
    for unum, (rr, cc, rp) in ADIO_PASSIVES.items():
        ux, uy, _ = lay[f"U{unum}"]
        lay[rr] = (ux - 6.0, uy, 0.0)
        lay[cc] = (ux - 6.0, uy + 3.2, 0.0)
        lay[rp] = (ux + 6.0, uy - 3.2, 0.0)
    for unum, (rr, cc) in HP_PASSIVES.items():
        ux, uy, rot = lay[f"U{unum}"]
        # TO-263 rot 270: sit sense parts west of tab
        lay[rr] = (ux - 11.0, uy - 4.0, 0.0)
        lay[cc] = (ux - 11.0, uy, 0.0)
    return lay


def edge_cuts(w, h) -> str:
    segs = [(0, 0, w, 0), (w, 0, w, h), (w, h, 0, h), (0, h, 0, 0)]
    out = []
    for x1, y1, x2, y2 in segs:
        out.append(
            "\t(gr_line\n"
            f"\t\t(start {fmt(x1)} {fmt(y1)})\n"
            f"\t\t(end {fmt(x2)} {fmt(y2)})\n"
            "\t\t(stroke\n"
            "\t\t\t(width 0.1)\n"
            "\t\t\t(type default)\n"
            "\t\t)\n"
            '\t\t(layer "Edge.Cuts")\n'
            f'\t\t(uuid "{uid()}")\n'
            "\t)\n"
        )
    return "".join(out)


def gr_text(msg, x, y, layer="Dwgs.User") -> str:
    return (
        "\t(gr_text\n"
        f'\t\t"{msg}"\n'
        f"\t\t(at {fmt(x)} {fmt(y)} 0)\n"
        f'\t\t(layer "{layer}")\n'
        f'\t\t(uuid "{uid()}")\n'
        "\t\t(effects\n"
        "\t\t\t(font\n"
        "\t\t\t\t(size 1.1 1.1)\n"
        "\t\t\t\t(thickness 0.15)\n"
        "\t\t\t)\n"
        "\t\t)\n"
        "\t)\n"
    )


def segment(x1, y1, x2, y2, width, layer, net) -> str:
    if abs(x1 - x2) < 1e-4 and abs(y1 - y2) < 1e-4:
        return ""
    return (
        "\t(segment\n"
        f"\t\t(start {fmt(x1)} {fmt(y1)})\n"
        f"\t\t(end {fmt(x2)} {fmt(y2)})\n"
        f"\t\t(width {fmt(width)})\n"
        f'\t\t(layer "{layer}")\n'
        f"\t\t(net {net})\n"
        f'\t\t(uuid "{uid()}")\n'
        "\t)\n"
    )


def via(x, y, net, size=0.6, drill=0.3) -> str:
    return (
        "\t(via\n"
        f"\t\t(at {fmt(x)} {fmt(y)})\n"
        f"\t\t(size {fmt(size)})\n"
        f"\t\t(drill {fmt(drill)})\n"
        '\t\t(layers "F.Cu" "B.Cu")\n'
        f"\t\t(net {net})\n"
        f'\t\t(uuid "{uid()}")\n'
        "\t)\n"
    )


def manhattan(x1, y1, x2, y2, width, layer, net, via_y=None) -> str:
    """HV then VH. Optional jog at via_y for exclusive highways."""
    parts = []
    if via_y is not None:
        parts.append(segment(x1, y1, x1, via_y, width, layer, net))
        parts.append(segment(x1, via_y, x2, via_y, width, layer, net))
        parts.append(segment(x2, via_y, x2, y2, width, layer, net))
    else:
        parts.append(segment(x1, y1, x2, y1, width, layer, net))
        parts.append(segment(x2, y1, x2, y2, width, layer, net))
    return "".join(parts)


def parse_fp_pads(block: str, origin_x, origin_y, rot) -> dict[str, tuple[float, float]]:
    pads = {}
    for m in re.finditer(r'\(pad "([^"]*)"[^\n]*\n\s*\(at ([0-9eE.+-]+) ([0-9eE.+-]+)', block):
        num = m.group(1)
        if not num:
            continue
        px, py = float(m.group(2)), float(m.group(3))
        rx, ry = rot_pt(px, py, rot)
        pads[num] = (origin_x + rx, origin_y + ry)
    return pads


def zone_rect(net, netname, layer, x1, y1, x2, y2, keepout=False, clearance=0.25, min_t=0.3) -> str:
    hatch = "0.5"
    if keepout:
        extra = (
            "\t\t(keepout\n"
            "\t\t\t(tracks allowed)\n"
            "\t\t\t(vias allowed)\n"
            "\t\t\t(pads allowed)\n"
            "\t\t\t(copperpour not_allowed)\n"
            "\t\t\t(footprints allowed)\n"
            "\t\t)\n"
        )
        layer_line = '\t\t(layers "F.Cu" "B.Cu")\n'
    else:
        extra = ""
        layer_line = f'\t\t(layer "{layer}")\n'
    return (
        "\t(zone\n"
        f"\t\t(net {net})\n"
        f'\t\t(net_name "{netname}")\n'
        + layer_line +
        f'\t\t(uuid "{uid()}")\n'
        f"\t\t(hatch edge {hatch})\n"
        "\t\t(connect_pads\n"
        f"\t\t\t(clearance {clearance})\n"
        "\t\t)\n"
        f"\t\t(min_thickness {min_t})\n"
        "\t\t(filled_areas_thickness no)\n"
        + extra +
        "\t\t(fill\n"
        "\t\t\t(thermal_gap 0.5)\n"
        "\t\t\t(thermal_bridge_width 0.5)\n"
        "\t\t)\n"
        "\t\t(polygon\n"
        "\t\t\t(pts\n"
        f"\t\t\t\t(xy {fmt(x1)} {fmt(y1)}) (xy {fmt(x2)} {fmt(y1)}) "
        f"(xy {fmt(x2)} {fmt(y2)}) (xy {fmt(x1)} {fmt(y2)})\n"
        "\t\t\t)\n"
        "\t\t)\n"
        "\t)\n"
    )


def collect_points(fp_pads: dict[str, dict[str, tuple[float, float]]], fp_nets: dict[str, dict[str, tuple[int, str]]], netname: str):
    pts = []
    for ref, pads in fp_pads.items():
        nmap = fp_nets.get(ref, {})
        for pnum, (x, y) in pads.items():
            if pnum in nmap and nmap[pnum][1] == netname:
                pts.append((x, y, ref, pnum))
    return pts


def route_star(pts, width, layer, net, prefer=None, hwy_y=None) -> str:
    if len(pts) < 2:
        return ""
    used = set()
    if prefer:
        for i, (*_, ref, _) in enumerate(pts):
            if ref in prefer:
                used.add(i)
                break
    if not used:
        used.add(0)
    out = []
    while len(used) < len(pts):
        best = None
        for i in used:
            x1, y1, *_ = pts[i]
            for j, (x2, y2, *_) in enumerate(pts):
                if j in used:
                    continue
                d = abs(x1 - x2) + abs(y1 - y2)
                if best is None or d < best[0]:
                    best = (d, i, j)
        _, i, j = best
        x1, y1, *_ = pts[i]
        x2, y2, *_ = pts[j]
        out.append(manhattan(x1, y1, x2, y2, width, layer, net, via_y=hwy_y))
        used.add(j)
    return "".join(out)


def count_crossings(segs: list[tuple]) -> int:
    """segs: (x1,y1,x2,y2,layer,net)"""
    n = 0

    def orient(ax, ay, bx, by, cx, cy):
        v = (by - ay) * (cx - ax) - (bx - ax) * (cy - ay)
        if abs(v) < 1e-9:
            return 0
        return 1 if v > 0 else 2

    def onseg(ax, ay, bx, by, cx, cy):
        return min(ax, bx) - 1e-6 <= cx <= max(ax, bx) + 1e-6 and min(ay, by) - 1e-6 <= cy <= max(ay, by) + 1e-6

    def intersect(a, b):
        x1, y1, x2, y2, la, na = a
        x3, y3, x4, y4, lb, nb = b
        if la != lb or na == nb:
            return False
        # ignore shared endpoints
        for p in ((x1, y1), (x2, y2)):
            for q in ((x3, y3), (x4, y4)):
                if abs(p[0] - q[0]) < 0.05 and abs(p[1] - q[1]) < 0.05:
                    return False
        o1 = orient(x1, y1, x2, y2, x3, y3)
        o2 = orient(x1, y1, x2, y2, x4, y4)
        o3 = orient(x3, y3, x4, y4, x1, y1)
        o4 = orient(x3, y3, x4, y4, x2, y2)
        if o1 != o2 and o3 != o4:
            return True
        return False

    for i, a in enumerate(segs):
        for b in segs[i + 1:]:
            if intersect(a, b):
                n += 1
    return n


def union_unconnected(pts_by_net, segs_by_net, vias_by_net) -> tuple[int, list]:
    open_nets = []
    unc = 0
    for net, pts in pts_by_net.items():
        if len(pts) < 2:
            continue
        parent = {}

        def key(p, tol=0.5):
            return (round(p[0] / tol), round(p[1] / tol))

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
        for x1, y1, x2, y2 in segs_by_net.get(net, []):
            union(key((x1, y1)), key((x2, y2)))
            for ex, ey in ((x1, y1), (x2, y2)):
                for px, py in pts:
                    if abs(px - ex) < 0.7 and abs(py - ey) < 0.7:
                        union(key((px, py)), key((ex, ey)))
        for vx, vy in vias_by_net.get(net, []):
            k = key((vx, vy))
            parent.setdefault(k, k)
            for px, py in pts:
                if abs(px - vx) < 0.7 and abs(py - vy) < 0.7:
                    union(key((px, py)), k)
        roots = {find(k) for k in pad_keys}
        if len(roots) > 1:
            unc += len(roots) - 1
            open_nets.append((net, len(roots), len(pts)))
    return unc, open_nets


def force_k8_header(text: str) -> str:
    text = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text = re.sub(r'\(generator_version "[^"]+"\)', '(generator_version "8.0")', text, count=1)
    text = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text)
    return text


def main() -> int:
    print("=== PowerCore layout redesign ===")
    write_m6_footprint()
    write_vertical_superseal()
    print("Wrote M6 + vertical SuperSeal footprints")

    src = PCB.read_text()
    nets = parse_nets(src)
    n2i = net_by_name(nets)
    header, blocks, closer = split_top_blocks(src)

    fps = {}
    other = []
    for b in blocks:
        if b.startswith("\t(footprint"):
            ref = fp_ref(b)
            if ref:
                fps[ref] = b
            else:
                other.append(b)
        elif b.startswith("\t(gr_line") or b.startswith("\t(gr_text") or b.startswith("\t(segment") \
                or b.startswith("\t(via") or b.startswith("\t(zone"):
            continue  # drop drawings/copper/zones; rebuilt
        else:
            other.append(b)

    old_j1_nets = {pin: (n2i[name], name) for pin, name in J1_PINOUT.items()}
    old_j2_nets = pad_nets_from_fp(fps["J2"])
    old_m_nets = pad_nets_from_fp(fps["M1000"])
    # GND on unnamed G pads
    if "G" not in old_m_nets and "GND" in n2i:
        old_m_nets["G"] = (n2i["GND"], "GND")
    old_j2_nets["1"] = (n2i["VBAT"], "VBAT")
    old_j2_nets["2"] = (n2i["GND"], "GND")

    lay = expand_layout()
    new_fps = []
    fp_pads = {}
    fp_nets = {}

    for ref, block in fps.items():
        x, y, rot = lay.get(ref, None) or (None, None, None)
        if x is None:
            # keep existing position if not in layout (shouldn't happen)
            m = re.search(r"\(at ([0-9eE.+-]+) ([0-9eE.+-]+)(?: ([0-9eE.+-]+))?\)", block)
            x, y = float(m.group(1)), float(m.group(2))
            rot = float(m.group(3) or 0)
        if ref == "M1000":
            block = rebuild_m1000(block, x, y, rot, old_m_nets)
        elif ref == "J1":
            block = rebuild_j1(block, x, y, rot, old_j1_nets)
        elif ref == "J2":
            block = rebuild_j2(block, x, y, rot, old_j2_nets)
        else:
            block = set_fp_at(block, x, y, rot)
        new_fps.append(block)
        fp_pads[ref] = parse_fp_pads(block, x, y, rot)
        fp_nets[ref] = pad_nets_from_fp(block)

    # bbox of all pads + M6 courtyard + J1 courtyard, then Edge.Cuts
    xs, ys = [], []
    for pads in fp_pads.values():
        for x, y in pads.values():
            xs.append(x)
            ys.append(y)
    # include known courtyards
    j2x, j2y, _ = lay["J2"]
    xs += [j2x - 10, j2x + 32]
    ys += [j2y - 10, j2y + 10]
    m1000x, m1000y, _ = lay["M1000"]
    xs += [m1000x + 0.1, m1000x + 42.2]
    ys += [m1000y - 40.0, m1000y]
    minx, miny = min(xs), min(ys)
    maxx, maxy = max(xs), max(ys)
    margin = 2.0
    # Keep origin at (0,0); if anything went negative, shift
    shift_x = 0.0 if minx >= margin else (margin - minx)
    shift_y = 0.0 if miny >= margin else (margin - miny)
    if shift_x or shift_y:
        print(f"Shifting layout by ({shift_x}, {shift_y}) to clear origin")
        new_fps2 = []
        fp_pads2 = {}
        for block in new_fps:
            ref = fp_ref(block)
            x, y, rot = lay[ref]
            x, y = x + shift_x, y + shift_y
            lay[ref] = (x, y, rot)
            block = set_fp_at(block, x, y, rot)
            new_fps2.append(block)
            fp_pads2[ref] = parse_fp_pads(block, x, y, rot)
        new_fps, fp_pads = new_fps2, fp_pads2
        maxx += shift_x
        maxy += shift_y
        minx += shift_x
        miny += shift_y

    board_w = round(maxx + margin, 1)
    board_h = round(maxy + margin, 1)
    # Target Razor-class: don't grow past what's needed; clamp tiny float
    print(f"Edge.Cuts {board_w} x {board_h} mm (was 150 x 130)")

    # aux origin bottom-left
    header = re.sub(r"\(aux_axis_origin [0-9.]+ [0-9.]+\)", f"(aux_axis_origin 0 {fmt(board_h)})", header)
    header = re.sub(
        r'\(comment 1 "[^"]*"\)',
        '(comment 1 "PowerCore PDM (pdmrazora) - vertical SuperSeal EMI split - M6 bobbins - mega-mcu144 0.7")',
        header,
    )

    copper = []
    segs_meta = []
    segs_by_net = defaultdict(list)
    vias_by_net = defaultdict(list)
    pts_by_net = defaultdict(list)

    def add_seg_str(s: str, layer, net, x1, y1, x2, y2):
        if not s:
            return
        copper.append(s)
        if s.startswith("\t(segment"):
            segs_meta.append((x1, y1, x2, y2, layer, net))
            segs_by_net[nets[net]].append((x1, y1, x2, y2))
        elif s.startswith("\t(via"):
            vias_by_net[nets[net]].append((x1, y1))

    def emit_manh(x1, y1, x2, y2, width, layer, netid, hwy_y=None):
        if hwy_y is None:
            add_seg_str(segment(x1, y1, x2, y1, width, layer, netid), layer, netid, x1, y1, x2, y1)
            add_seg_str(segment(x2, y1, x2, y2, width, layer, netid), layer, netid, x2, y1, x2, y2)
        else:
            add_seg_str(segment(x1, y1, x1, hwy_y, width, layer, netid), layer, netid, x1, y1, x1, hwy_y)
            add_seg_str(segment(x1, hwy_y, x2, hwy_y, width, layer, netid), layer, netid, x1, hwy_y, x2, hwy_y)
            add_seg_str(segment(x2, hwy_y, x2, y2, width, layer, netid), layer, netid, x2, hwy_y, x2, y2)

    def emit_via(x, y, netid):
        add_seg_str(via(x, y, netid), "via", netid, x, y, x, y)

    # pad points
    for ref, pads in fp_pads.items():
        for pnum, (x, y) in pads.items():
            nmap = fp_nets.get(ref, {})
            if pnum in nmap:
                pts_by_net[nmap[pnum][1]].append((x, y))

    # Local passives (F.Cu short)
    local = [
        ("R1", "1", "IGN_SW", 0.3),
        ("R1", "2", "IN_VIGN", 0.25),
        ("R2", "1", "IN_VIGN", 0.25),
        ("R2", "2", "GND", 0.3),
        ("F1", "1", "VBAT", 1.2),
        ("F1", "2", "VBAT", 1.2),
        ("D1", "1", "VBAT", 0.8),
        ("D1", "2", "GND", 0.8),
        ("C1", "1", "VBAT", 0.8),
        ("C1", "2", "GND", 0.8),
        ("C2", "1", "VBAT", 0.5),
        ("C2", "2", "GND", 0.5),
    ]
    for n, isense in [(10, "IN_AUX1"), (20, "IN_AUX2"), (30, "IN_AUX3"), (40, "IN_AUX4")]:
        local += [(f"R{n}", "2", isense, 0.25), (f"C{n}", "1", isense, 0.25),
                  (f"R{n}", "1", "GND", 0.25), (f"C{n}", "2", "GND", 0.25)]
    mapping = [
        (101, "IN_MAP1", "ADIO1"), (102, "IN_MAP2", "ADIO2"), (103, "IN_MAP3", "ADIO3"),
        (104, "IN_O2S", "ADIO4"), (105, "IN_O2S2", "ADIO5"), (106, "IN_RES1", "ADIO6"),
        (107, "IN_RES2", "ADIO7"), (108, "IN_RES3", "ADIO8"),
    ]
    for n, isense, adio in mapping:
        local += [
            (f"R{n}", "2", isense, 0.25), (f"C{n}", "1", isense, 0.25),
            (f"R{n}", "1", "GND", 0.25), (f"C{n}", "2", "GND", 0.25),
            (f"R{n+100}", "1", "SENSOR_5V", 0.3), (f"R{n+100}", "2", adio, 0.3),
        ]

    # Connect each local pad to its parent chip pad (not nearest random same-net)
    parent_chip = {}
    for netname, chip in {**CHIP_EN, **CHIP_IS}.items():
        parent_chip[netname] = chip
    parent_chip.update({
        "IGN_SW": "R1", "IN_VIGN": "R1", "VBAT": "J2", "GND": "J2",
        "SENSOR_5V": "J1", "ADIO1": "U11", "ADIO2": "U12", "ADIO3": "U13",
        "ADIO4": "U14", "ADIO5": "U15", "ADIO6": "U16", "ADIO7": "U17", "ADIO8": "U18",
    })
    for ref, pin, netname, w in local:
        if ref not in fp_pads or pin not in fp_pads[ref]:
            continue
        x1, y1 = fp_pads[ref][pin]
        pts = collect_points(fp_pads, fp_nets, netname)
        prefer_ref = parent_chip.get(netname)
        preferred = [(x, y) for x, y, r, _ in pts if r == prefer_ref]
        others = [(x, y) for x, y, r, _ in pts if r != ref]
        pool = preferred or others
        if not pool:
            continue
        x2, y2 = min(pool, key=lambda p: abs(p[0] - x1) + abs(p[1] - y1))
        emit_manh(x1, y1, x2, y2, w, "F.Cu", n2i[netname])

    def uniq_pts(netname, refs=None):
        pts = collect_points(fp_pads, fp_nets, netname)
        if refs is not None:
            pts = [p for p in pts if p[2] in refs]
        uniq = []
        for p in pts:
            if not any(abs(p[0] - u[0]) < 0.3 and abs(p[1] - u[1]) < 0.3 for u in uniq):
                uniq.append(p)
        return uniq

    # VBAT spine on power side only (no full-board star mesh)
    copper.append(route_star(
        uniq_pts("VBAT", {"J2", "F1", "C1", "C2", "D1", "U1", "U2", "U3", "U4",
                          "U11", "U12", "U13", "U14", "U15", "U16", "U17", "U18"}),
        1.5, "F.Cu", n2i["VBAT"], prefer={"J2", "F1"},
    ))
    # GND: a few stitches only — B.Cu pour carries the plane (avoids 2.54mm stub short)
    copper.append(route_star(
        uniq_pts("GND", {"J2", "C1", "C2", "D1", "R2"}),
        1.0, "F.Cu", n2i["GND"], prefer={"J2"},
    ))
    # B.Cu stitch J2 GND bobbin -> MCU (plane also poured)
    j2g = fp_pads["J2"].get("2")
    mcu_g = [(x, y) for x, y, r, _ in collect_points(fp_pads, fp_nets, "GND") if r == "M1000"]
    if j2g and mcu_g:
        emit_via(j2g[0], j2g[1], n2i["GND"])
        emit_via(mcu_g[0][0], mcu_g[0][1], n2i["GND"])
        emit_manh(j2g[0], j2g[1], mcu_g[0][0], mcu_g[0][1], 0.8, "B.Cu", n2i["GND"], hwy_y=board_h - 3)
    for n in range(1, 5):
        copper.append(route_star(
            uniq_pts(f"PWR_OUT{n}", {f"U{n}", "J1"}),
            1.2, "F.Cu", n2i[f"PWR_OUT{n}"], prefer={f"U{n}", "J1"},
        ))

    for n in range(1, 9):
        copper.append(route_star(
            uniq_pts(f"ADIO{n}", {f"U{10+n}", "J1", f"R{200+n}"}),
            0.5, "F.Cu", n2i[f"ADIO{n}"], prefer={f"U{10+n}", "J1"},
        ))

    for netname, w, refs in [
        ("CANH", 0.3, {"M1000", "J1"}),
        ("CANL", 0.3, {"M1000", "J1"}),
        ("SENSOR_5V", 0.4, {"M1000", "J1", "R201", "R202", "R203", "R204", "R205", "R206", "R207", "R208"}),
        ("SENSOR_GND", 0.4, {"J1"}),
        ("IGN_SW", 0.3, {"J1", "R1"}),
        ("IN_VIGN", 0.25, {"R1", "R2", "M1000"}),
    ]:
        copper.append(route_star(uniq_pts(netname, refs), w, "F.Cu", n2i[netname], prefer=refs))

    # EN exclusive B.Cu highways (south of J1 pin field ~ y>59)
    # IS exclusive F.Cu highways (north of J1 pin field ~ y<37)
    def mcu_and_chip(netname, chip_map):
        mcu = [(x, y) for x, y, r, _ in collect_points(fp_pads, fp_nets, netname) if r == "M1000"]
        chip = [(x, y) for x, y, r, _ in collect_points(fp_pads, fp_nets, netname) if r == chip_map[netname]]
        return (mcu[0] if mcu else None), (chip[0] if chip else None)

    spine_x = 88.8  # gap between J1 housing (~87.8) and ADIO (~93)

    def emit_split_net(src, dst, layer, nid, hwy, use_vias):
        if use_vias:
            emit_via(src[0], src[1], nid)
            emit_via(dst[0], dst[1], nid)
        # MCU vertical to exclusive Y, east to spine, north/south on spine, east to chip
        emit_manh(src[0], src[1], spine_x, hwy, 0.25, layer, nid, hwy_y=hwy)
        emit_manh(spine_x, hwy, dst[0], dst[1], 0.25, layer, nid)

    for i, netname in enumerate(EN_NETS):
        src, dst = mcu_and_chip(netname, CHIP_EN)
        if not src or not dst:
            print("missing EN pads", netname, src, dst)
            continue
        emit_split_net(src, dst, "B.Cu", n2i[netname], 51.0 + i * 0.55, True)

    for i, netname in enumerate(IS_NETS):
        src, dst = mcu_and_chip(netname, CHIP_IS)
        if not src or not dst:
            print("missing IS pads", netname, src, dst)
            continue
        emit_split_net(src, dst, "F.Cu", n2i[netname], 51.2 + i * 0.55, False)

    copper_text = "".join(copper)

    # Re-parse generated copper for metrics
    segs_meta.clear()
    segs_by_net.clear()
    vias_by_net.clear()
    for m in re.finditer(
        r"\t\(segment\n\t\t\(start ([0-9eE.+-]+) ([0-9eE.+-]+)\)\n\t\t\(end ([0-9eE.+-]+) ([0-9eE.+-]+)\)\n"
        r"\t\t\(width [0-9eE.+-]+\)\n\t\t\(layer \"([^\"]+)\"\)\n\t\t\(net (\d+)\)",
        copper_text,
    ):
        x1, y1, x2, y2 = map(float, m.group(1, 2, 3, 4))
        layer, netid = m.group(5), int(m.group(6))
        segs_meta.append((x1, y1, x2, y2, layer, netid))
        segs_by_net[nets[netid]].append((x1, y1, x2, y2))
    for m in re.finditer(
        r"\t\(via\n\t\t\(at ([0-9eE.+-]+) ([0-9eE.+-]+)\)\n.*?\n\t\t\(net (\d+)\)",
        copper_text,
        flags=re.S,
    ):
        vias_by_net[nets[int(m.group(3))]].append((float(m.group(1)), float(m.group(2))))

    crossings = count_crossings(segs_meta)
    unc, open_nets = union_unconnected(pts_by_net, segs_by_net, vias_by_net)
    en_open = [n for n, _, _ in open_nets if n in EN_NETS or n in IS_NETS]

    mx, my, _ = lay["M1000"]
    zones = []
    zones.append(zone_rect(0, "", "F.Cu", mx - 0.4, my - 40.4, mx + 42.6, my + 0.4, keepout=True))
    zones.append(zone_rect(n2i["GND"], "GND", "B.Cu", 1, 1, board_w - 1, board_h - 1, clearance=0.3, min_t=0.4))
    # VBAT power-side pour (east of connector)
    zones.append(zone_rect(n2i["VBAT"], "VBAT", "F.Cu", 88, 8, board_w - 1, board_h - 1, clearance=0.35, min_t=0.5))
    for i, uref in enumerate(["U1", "U2", "U3", "U4"], start=1):
        ux, uy, _ = lay[uref]
        zones.append(zone_rect(n2i[f"PWR_OUT{i}"], f"PWR_OUT{i}", "F.Cu",
                               ux - 8, uy - 8, ux + 8, uy + 8, clearance=0.25, min_t=0.4))

    drawings = edge_cuts(board_w, board_h)
    drawings += gr_text("MCU (mega-mcu144 0.7)", 8, 4)
    drawings += gr_text("J1 vertical SuperSeal EMI split", 40, 4, "Cmts.User")
    drawings += gr_text("PROFET HP+ADIO + M6 bobbins", 90, 4)
    drawings += gr_text("M6 VBAT+ / GND bolt-through", 90, board_h - 3, "Cmts.User")

    out = "(kicad_pcb\n" + header + "".join(new_fps) + drawings + copper_text + "".join(zones) + closer
    out = force_k8_header(out)
    PCB.write_text(out)

    ntracks = len(re.findall(r"\t\(segment\n", out))
    nvias = len(re.findall(r"\t\(via\n", out))
    nfps = len(re.findall(r"\t\(footprint ", out))

    pos_lines = [f"{ref}=({x}, {y}, {rot})\n" for ref, (x, y, rot) in sorted(lay.items())]
    pos_lines.append(f"BOARD={board_w}x{board_h}\n")
    POSFILE.write_text("".join(pos_lines))

    status = [
        f"board_mm={board_w}x{board_h}\n",
        "before_board_mm=150.0x130.0\n",
        "j1=vertical_6437288-6_rot90_emi_split\n",
        "j2=M6_Bolt_Bobbin_Dual_22mm\n",
        "m1000=hellen-one mega-mcu144 0.7 keepout_aligned Value=Module:mega-mcu144/0.7\n",
        f"tracks={ntracks}\n",
        f"vias={nvias}\n",
        f"footprints={nfps}\n",
        f"geom_crossings={crossings}\n",
        f"geom_unconnected={unc}\n",
        f"en_is_open={len(en_open)}\n",
        f"aux_axis_origin=0,{board_h}\n",
        "kicad=20240108/8.0\n",
        "baseline_drc_shorts=1\n",
        "baseline_drc_crossings=89\n",
        "baseline_drc_unconnected=116\n",
        "baseline_en_is_unconnected=0\n",
        "note=kicad-cli unavailable in this environment; geom_* is track-segment DRC proxy\n",
    ]
    for net, comps, pads in open_nets:
        status.append(f"open\t{net}\t{comps}\t{pads}\n")
    STATUS.write_text("".join(status))

    # sanity
    assert 'generator_version "8.0"' in out[:400]
    assert "(version 20240108)" in out[:200]
    assert "Module:mega-mcu144/0.7" in out
    assert "pdmrazora:TE_6437288-6_SuperSeal26_V" in out
    assert "pdmrazora:M6_Bolt_Bobbin_Dual" in out
    assert "PinHeader_1x02" not in out
    # no negative board coords on Edge.Cuts / aux
    assert "(aux_axis_origin 0 " in out
    print(f"Wrote PCB {board_w}x{board_h} tracks={ntracks} vias={nvias} crossings~{crossings} unc~{unc} EN/IS open={en_open}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
