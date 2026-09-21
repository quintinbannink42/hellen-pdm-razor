#!/usr/bin/env python3
"""Split VBAT/GND M6 bobbins onto opposite power-side edges (PowerCore).

Mechanical / floorplan only:
- Replace the 25 mm dual-bobbin J2 with two single M6 footprints (J2 VBAT+, J3 GND)
- Keep mega-mcu144 west of the vertical SuperSeal; bobbins stay off that west side
- Place HP + ADIO between the north VBAT bobbin and the south GND bobbin
- Keep Razor-class 104 x 93 mm Edge.Cuts
- Wipe tracks/vias/filled copper that assumed the co-located M6 spine
- Rewrite VBAT/GND zone *outlines* (unfilled). Follow-up zone-fill after merge.

Does not replay 150x130 cut_crossings / longhaul scripts, does not bond SENSOR_GND,
does not touch HELLCORE / Micro Core, does not rename pdmrazora.
"""
from __future__ import annotations

import math
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "pdmrazora.kicad_pcb"
SCH = ROOT / "pdmrazora.kicad_sch"
PRETTY = ROOT / "pdmrazora.pretty"
STATUS = ROOT / "scripts" / "layout_positions.txt"
PNG = ROOT / "scripts" / "floorplan_fcu_overview.png"

BOARD_W = 104.0
BOARD_H = 93.0

# KiCad origin = Edge.Cuts top-left; Y down. AUX = bottom-left (0, 93).
# Power field is east of the vertical SuperSeal (J1 courtyard x≈44.7–74.2, y≈26.8–66.3).
# M1000 stays west. Bobbins sit on the north and south edges of the POWER field.
LAYOUT = {
    "M1000": (2.0, 66.0, 0.0),
    "J1": (50.0, 46.5, 90.0),
    # Opposite edges of the power/driver field (not the MCU west side).
    "J2": (92.0, 11.0, 0.0),  # VBAT+ M6, north
    "J3": (92.0, 82.0, 0.0),  # GND M6, south
    # Power entry rides the VBAT path in the north pocket (north of SuperSeal).
    "C1": (62.0, 8.0, 0.0),
    "C2": (70.0, 8.0, 0.0),
    "F1": (58.0, 18.0, 0.0),  # ATO placeholder, still a placeholder
    "D1": (80.0, 28.0, 90.0),
    "R1": (74.0, 23.0, 0.0),
    "R2": (78.0, 23.0, 0.0),
    # HP 2x2 in the east alley; rot 270 so TO-263 tabs face north (VBAT).
    "U1": (80.0, 40.0, 270.0),
    "U2": (96.0, 40.0, 270.0),
    "U3": (80.0, 53.0, 270.0),
    "U4": (96.0, 53.0, 270.0),
    # Sense parts stay off the TO-263 bodies: one row north of tabs, one south of pins.
    "R10": (76.0, 32.0, 0.0),
    "C10": (80.0, 32.0, 0.0),
    "R20": (92.0, 32.0, 0.0),
    "C20": (96.0, 32.0, 0.0),
    "R30": (76.0, 65.5, 0.0),
    "C30": (80.0, 65.5, 0.0),
    "R40": (92.0, 65.5, 0.0),
    "C40": (96.0, 65.5, 0.0),
    # ADIO 2x4 south of SuperSeal, west of the GND bobbin, between bobbins in Y.
    "U11": (52.0, 69.5, 0.0),
    "U12": (60.0, 69.5, 0.0),
    "U13": (68.0, 69.5, 0.0),
    "U14": (76.0, 69.5, 0.0),
    "U15": (52.0, 77.5, 0.0),
    "U16": (60.0, 77.5, 0.0),
    "U17": (68.0, 77.5, 0.0),
    "U18": (76.0, 77.5, 0.0),
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

CONN_01X01 = '''		(symbol "Connector_Generic:Conn_01x01"
			(pin_names
				(offset 1.016)
				hide
			)
			(exclude_from_sim no)
			(in_bom yes)
			(on_board yes)
			(property "Reference" "J"
				(at 0 2.54 0)
				(effects
					(font
						(size 1.27 1.27)
					)
				)
			)
			(property "Value" "Conn_01x01"
				(at 0 -2.54 0)
				(effects
					(font
						(size 1.27 1.27)
					)
				)
			)
			(property "Footprint" ""
				(at 0 0 0)
				(effects
					(font
						(size 1.27 1.27)
					)
					(hide yes)
				)
			)
			(property "Datasheet" "~"
				(at 0 0 0)
				(effects
					(font
						(size 1.27 1.27)
					)
					(hide yes)
				)
			)
			(property "Description" "Generic connector, single row, 01x01, script generated (kicad-library-utils/schlib/autogen/connector/)"
				(at 0 0 0)
				(effects
					(font
						(size 1.27 1.27)
					)
					(hide yes)
				)
			)
			(property "ki_keywords" "connector"
				(at 0 0 0)
				(effects
					(font
						(size 1.27 1.27)
					)
					(hide yes)
				)
			)
			(property "ki_fp_filters" "Connector*:*_1x??_*"
				(at 0 0 0)
				(effects
					(font
						(size 1.27 1.27)
					)
					(hide yes)
				)
			)
			(symbol "Conn_01x01_1_1"
				(rectangle
					(start -1.27 1.27)
					(end 1.27 -1.27)
					(stroke
						(width 0.254)
						(type default)
					)
					(fill
						(type background)
					)
				)
				(rectangle
					(start -1.27 0.127)
					(end 0 -0.127)
					(stroke
						(width 0.1524)
						(type default)
					)
					(fill
						(type none)
					)
				)
				(pin passive line
					(at -5.08 0 0)
					(length 3.81)
					(name "Pin_1" (effects
							(font
								(size 1.27 1.27)
							)
						))
					(number "1" (effects
							(font
								(size 1.27 1.27)
							)
						))
				)
			)
		)
'''

J2_J3_SCH = '''	(symbol
		(lib_id "Connector_Generic:Conn_01x01")
		(at 35 35 0)
		(unit 1)
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(dnp no)
		(uuid "ec62a57a-2242-4d2c-8cb4-02550fc8b156")
		(property "Reference" "J2"
			(at 35 32.5 0)
			(effects
				(font
					(size 1.27 1.27)
				)
			)
		)
		(property "Value" "M6_VBAT"
			(at 35 37.5 0)
			(effects
				(font
					(size 1.27 1.27)
				)
			)
		)
		(property "Footprint" "pdmrazora:M6_BoltThrough_Bobbin"
			(at 35 35 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(property "Datasheet" "~"
			(at 35 35 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(property "Description" "M6 bolt-through bobbin VBAT+ (north power-field edge)"
			(at 35 35 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(pin "1"
			(uuid "580ed1c2-f9c5-4acc-9977-68f1c52e4715")
		)
	)
	(wire
		(pts (xy 29.92 35.0) (xy 19.76 35.0))
		(stroke
			(width 0)
			(type default)
		)
		(uuid "582721d1-3fd9-4760-b372-8eb4f71b03e6")
	)
	(global_label "VBAT"
		(at 19.76 35.0 0)
		(shape input)
		(effects
			(font
				(size 1.27 1.27)
			)
			(justify right)
		)
		(uuid "c463eee5-7cce-4df2-8e52-d76814625aad")
	)
	(symbol
		(lib_id "Connector_Generic:Conn_01x01")
		(at 35 45 0)
		(unit 1)
		(exclude_from_sim no)
		(in_bom yes)
		(on_board yes)
		(dnp no)
		(uuid "SCH_J3_UUID")
		(property "Reference" "J3"
			(at 35 42.5 0)
			(effects
				(font
					(size 1.27 1.27)
				)
			)
		)
		(property "Value" "M6_GND"
			(at 35 47.5 0)
			(effects
				(font
					(size 1.27 1.27)
				)
			)
		)
		(property "Footprint" "pdmrazora:M6_BoltThrough_Bobbin"
			(at 35 45 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(property "Datasheet" "~"
			(at 35 45 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(property "Description" "M6 bolt-through bobbin GND (south power-field edge)"
			(at 35 45 0)
			(effects
				(font
					(size 1.27 1.27)
				)
				(hide yes)
			)
		)
		(pin "1"
			(uuid "SCH_J3_PIN_UUID")
		)
	)
	(wire
		(pts (xy 29.92 45.0) (xy 19.76 45.0))
		(stroke
			(width 0)
			(type default)
		)
		(uuid "SCH_J3_WIRE_UUID")
	)
	(global_label "GND"
		(at 19.76 45.0 0)
		(shape input)
		(effects
			(font
				(size 1.27 1.27)
			)
			(justify right)
		)
		(uuid "68fc02b0-c3e6-4b4b-bd53-acccc1067981")
	)
'''


def uid(tag: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pdmrazora-split-bobbins/{tag}"))


def fmt_at(x: float, y: float, rot: float) -> str:
    if abs(rot) < 1e-9:
        return f"(at {x:g} {y:g})"
    r = rot if rot < 180 else rot - 360
    if abs(r) < 1e-9:
        return f"(at {x:g} {y:g})"
    return f"(at {x:g} {y:g} {r:g})"


def extract_top_items(body: str) -> list[str]:
    items = []
    i = 0
    n = len(body)
    while i < n:
        while i < n and body[i] in " \t\n\r":
            i += 1
        if i >= n:
            break
        if body[i] != "(":
            raise RuntimeError(f"expected '(' at {i}: {body[i:i+40]!r}")
        depth = 0
        start = i
        in_str = False
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


def fp_pad_nets(item: str) -> dict[str, tuple[str, str]]:
    nets: dict[str, tuple[str, str]] = {}
    current: str | None = None
    for line in item.splitlines():
        m = re.search(r'\(pad\s+"([^"]*)"', line)
        if m:
            current = m.group(1) or None
            continue
        if not current:
            continue
        nm = re.search(r'\(net\s+(\d+)\s+"([^"]*)"\)', line)
        if nm:
            nets[current] = (nm.group(1), nm.group(2))
    return nets


def set_fp_at(item: str, x: float, y: float, rot: float) -> str:
    new_at = fmt_at(x, y, rot)
    out, n = re.subn(r"^\t\(at [^\n]+\)", f"\t{new_at}", item, count=1, flags=re.M)
    if n != 1:
        out, n = re.subn(r"\(at [0-9eE+.\- ]+\)", new_at, item, count=1)
        if n != 1:
            raise RuntimeError("could not set footprint (at)")
    return out


def inject_pad_nets(item: str, nets: dict[str, tuple[str, str]]) -> str:
    for num, (code, name) in nets.items():
        pat = re.compile(
            rf'(\(pad "{re.escape(num)}"[\s\S]*?)(\(uuid "[^"]+"\))',
        )

        def add_net(m: re.Match, code=code, name=name) -> str:
            head = m.group(1)
            if "(net " in head:
                head = re.sub(
                    r'\(net\s+\d+\s+"[^"]*"\)',
                    f'(net {code} "{name}")',
                    head,
                    count=1,
                )
                return head + m.group(2)
            return head + f'(net {code} "{name}")\n\t\t\t' + m.group(2)

        item, n = pat.subn(add_net, item)
        if n < 1:
            print(f"warn: no pad {num} to attach net {name}", file=sys.stderr)
    return item


def remap_uuids(item: str, salt: str) -> str:
    """KiCad requires unique UUIDs; two instances of one .kicad_mod would collide."""

    def repl(m: re.Match) -> str:
        return f'(uuid "{uid(salt + "/" + m.group(1))}")'

    return re.sub(r'\(uuid "([^"]+)"\)', repl, item)


def set_prop(item: str, name: str, value: str) -> str:
    pat = re.compile(rf'\(property "{re.escape(name)}" "[^"]*"')
    out, n = pat.subn(f'(property "{name}" "{value}"', item, count=1)
    if n != 1:
        raise RuntimeError(f"could not set property {name}")
    return out


def pretty_to_pcb_fp(mod_text: str, lib_name: str, fp_uuid: str, x, y, rot, nets, ref: str) -> str:
    pretty_lines = mod_text.strip().splitlines()
    first = re.sub(
        r'^\(footprint\s+"[^"]+"',
        f'(footprint "{lib_name}"',
        pretty_lines[0],
        count=1,
    )
    body_lines = ["\t" + first]
    did_at = False
    for line in pretty_lines[1:-1]:
        body_lines.append("\t" + line)
        if not did_at and line.strip().startswith("(layer "):
            body_lines.append(f'\t\t(uuid "{fp_uuid}")')
            body_lines.append(f"\t\t{fmt_at(x, y, rot)}")
            did_at = True
    body_lines.append("\t" + pretty_lines[-1])
    item = "\n".join(body_lines)
    item = item.replace('(property "Reference" "REF**"', f'(property "Reference" "{ref}"')
    if nets:
        item = inject_pad_nets(item, nets)
    return item


def zone_rect(net, net_name, layer, uuid_s, x1, y1, x2, y2, keepout=False, priority=None) -> str:
    extra = ""
    if priority is not None:
        extra += f"\n\t\t(priority {priority})"
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
    fill = "(fill no" if keepout else "(fill yes"
    if keepout:
        layer_line = '(layers "F.Cu" "B.Cu")'
    else:
        layer_line = f'(layer "{layer}")'
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
				(xy {x1:g} {y1:g}) (xy {x2:g} {y1:g}) (xy {x2:g} {y2:g}) (xy {x1:g} {y2:g})
			)
		)
	)'''


def gr_line(x1, y1, x2, y2, layer, uuid_s, width=0.1) -> str:
    return f'''	(gr_line
		(start {x1:g} {y1:g})
		(end {x2:g} {y2:g})
		(stroke
			(width {width})
			(type default)
		)
		(layer "{layer}")
		(uuid "{uuid_s}")
	)'''


def gr_text(txt, x, y, layer, uuid_s, size=1.2) -> str:
    return f'''	(gr_text "{txt}"
		(at {x:g} {y:g} 0)
		(layer "{layer}")
		(uuid "{uuid_s}")
		(effects
			(font
				(size {size} {size})
				(thickness 0.15)
			)
			(justify left bottom)
		)
	)'''


def apply_adio_offsets(layout: dict) -> dict:
    out = dict(layout)
    for n, (r, c, pu) in ADIO_PASSIVES.items():
        ux, uy, _ = layout[f"U{n}"]
        # SuperSeal courtyard occupies y≤66.25, so keep passives south of that.
        # 8 mm ADIO pitch cannot take 0603 between chips; cluster south / between rows.
        if n <= 14:
            out[r] = (ux - 2.8, 82.2, 0.0)
            out[c] = (ux + 2.8, 82.2, 0.0)
            out[pu] = (ux, 73.5, 0.0)
        else:
            out[r] = (ux - 2.8, 86.5, 0.0)
            out[c] = (ux + 2.8, 86.5, 0.0)
            out[pu] = (ux, 81.5, 0.0)
    return out


def sanitize_k8(text: str) -> str:
    text = re.sub(r"\n\t\t\(tenting [^\n]+\)", "", text)
    text = re.sub(r"\n\t\t\(embedded_fonts (yes|no)\)", "", text)
    text = re.sub(r"\n\t\(embedded_fonts (yes|no)\)", "", text)
    text = re.sub(r"\n\t\t\(legacy_teardrops (yes|no)\)", "", text)
    text = re.sub(r' "In\d+\.Cu"', "", text)
    text = re.sub(r'\n\t+"In\d+\.Cu"', "", text)
    text = re.sub(r"\(version \d+\)", "(version 20240108)", text, count=1)
    text = re.sub(
        r'\(generator_version "[^"]+"\)',
        '(generator_version "8.0")',
        text,
        count=1,
    )
    return text


def patch_schematic() -> None:
    sch = SCH.read_text()
    if "Connector_Generic:Conn_01x01" not in sch:
        needle = '\t\t(symbol "Connector_Generic:Conn_01x02"'
        if needle not in sch:
            sys.exit("Conn_01x02 lib symbol missing — abort schematic patch")
        sch = sch.replace(needle, CONN_01X01 + needle, 1)
    old = re.search(
        r'\t\(symbol\n\t\t\(lib_id "Connector_Generic:Conn_01x02"\)[\s\S]*?'
        r'\(uuid "68fc02b0-c3e6-4b4b-bd53-acccc1067981"\)\n\t\)\n',
        sch,
    )
    if not old:
        if '(property "Reference" "J3"' in sch and "M6_BoltThrough_Bobbin\"" in sch:
            print("schematic already split")
            return
        sys.exit("could not find J2 Conn_01x02 block to replace")
    sch = sch[: old.start()] + J2_J3_SCH + sch[old.end() :]
    sch = sch.replace(
        "M6+ = VBAT, M6- = GND (bolt-through bobbins)",
        "M6+ J2 north = VBAT, M6- J3 south = GND (split bobbins, drivers between)",
    )
    sch = sch.replace("SCH_J3_UUID", uid("sch-j3"))
    sch = sch.replace("SCH_J3_PIN_UUID", uid("sch-j3-pin"))
    sch = sch.replace("SCH_J3_WIRE_UUID", uid("sch-j3-wire"))
    SCH.write_text(sch)
    print(f"patched {SCH}")


def fp_world_pads(item: str) -> list[tuple[str, float, float, float]]:
    """(netname or padnum, x, y, radius_mm) for thru/smd circular-ish pads."""
    at = re.search(r"^\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", item, re.M)
    if not at:
        return []
    ax, ay = float(at.group(1)), float(at.group(2))
    ang = math.radians(float(at.group(3) or 0))
    ca, sa = math.cos(ang), math.sin(ang)
    out = []
    current = None
    net = ""
    size = 1.0
    px = py = 0.0
    for line in item.splitlines():
        m = re.search(r'\(pad "([^"]*)"', line)
        if m:
            current = m.group(1)
            net = ""
            continue
        if current is None:
            continue
        am = re.search(r"\(at ([-\d.]+) ([-\d.]+)", line)
        if am and "pad" not in line[:20]:
            px, py = float(am.group(1)), float(am.group(2))
        sm = re.search(r"\(size ([-\d.]+) ([-\d.]+)\)", line)
        if sm:
            size = max(float(sm.group(1)), float(sm.group(2)))
        nm = re.search(r'\(net\s+\d+\s+"([^"]*)"\)', line)
        if nm:
            net = nm.group(1)
        if line.strip() == ")" and current is not None:
            wx = ax + px * ca - py * sa
            wy = ay + px * sa + py * ca
            out.append((net or current, wx, wy, size / 2))
            current = None
    return out


def write_floorplan_png(items: list[str], layout: dict) -> None:
    """Stdlib PPM→PNG-ish F.Cu overview (pads + outline + EMI + zones)."""
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except ImportError:
        write_floorplan_ppm(items, layout)
        return
    scale = 12  # px per mm
    margin = 24
    w = int(BOARD_W * scale) + 2 * margin
    h = int(BOARD_H * scale) + 2 * margin
    im = Image.new("RGB", (w, h), (18, 22, 18))
    dr = ImageDraw.Draw(im)

    def xy(x, y):
        return margin + x * scale, margin + y * scale

    # board
    dr.rectangle([xy(0, 0), xy(BOARD_W, BOARD_H)], outline=(200, 200, 200), width=2)
    # EMI
    dr.line([xy(45.5, 4), xy(45.5, BOARD_H - 4)], fill=(120, 180, 255), width=2)
    # zones (unfilled outlines)
    zone_cols = {
        "VBAT": (180, 40, 40),
        "GND": (40, 90, 180),
        "": (80, 80, 80),
    }
    for it in items:
        if item_head(it) != "zone":
            continue
        net = re.search(r'\(net_name "([^"]*)"\)', it)
        name = net.group(1) if net else ""
        pts = re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", it)
        if len(pts) < 4:
            continue
        poly = [xy(float(a), float(b)) for a, b in pts[:4]]
        col = zone_cols.get(name, (100, 100, 100))
        dr.polygon(poly, outline=col)
    net_col = {"VBAT": (200, 50, 50), "GND": (50, 90, 200)}
    for it in items:
        if item_head(it) != "footprint":
            continue
        at = re.search(r"^\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", it, re.M)
        if not at:
            continue
        ax, ay = float(at.group(1)), float(at.group(2))
        ang = float(at.group(3) or 0)
        ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        for pm in re.finditer(r'\(pad "([^"]*)"[\s\S]*?\n\t\t\)', it):
            block = pm.group(0)
            am = re.search(r"\(at ([-\d.]+) ([-\d.]+)", block)
            sm = re.search(r"\(size ([-\d.]+) ([-\d.]+)\)", block)
            nm = re.search(r'\(net \d+ "([^"]*)"\)', block)
            if not am or not sm:
                continue
            px, py = float(am.group(1)), float(am.group(2))
            sx, sy = float(sm.group(1)), float(sm.group(2))
            wx = ax + px * ca - py * sa
            wy = ay + px * sa + py * ca
            col = net_col.get(nm.group(1) if nm else "", (170, 170, 90))
            r = max(sx, sy) / 2 * scale
            x, y = xy(wx, wy)
            dr.ellipse([x - r, y - r, x + r, y + r], outline=col, width=1)
    colors = {
        "J2": (220, 40, 40),
        "J3": (50, 90, 210),
        "J1": (200, 200, 80),
        "M1000": (80, 200, 120),
        "F1": (220, 160, 60),
    }
    for it in items:
        if item_head(it) != "footprint":
            continue
        ref = fp_ref(it) or "?"
        at = re.search(r"^\t\t\(at ([-\d.]+) ([-\d.]+)", it, re.M)
        if not at:
            continue
        ax, ay = float(at.group(1)), float(at.group(2))
        col = colors.get(ref, (160, 160, 160))
        if ref.startswith("U") and ref[1:].isdigit():
            n = int(ref[1:])
            col = (210, 90, 40) if n <= 4 else (180, 140, 40)
        if ref == "J1":
            dr.rectangle([xy(44.7, 26.75), xy(74.2, 66.25)], outline=col, width=2)
        elif ref == "M1000":
            dr.rectangle([xy(2.1, 26.0), xy(44.3, 66.0)], outline=col, width=2)
        elif ref == "F1":
            dr.rectangle([xy(52.35, 15.95), xy(72.85, 22.45)], outline=col, width=2)
        lx, ly = xy(ax, ay)
        dr.text((lx + 4, ly - 10), ref, fill=(230, 230, 230))
    # bobbin silk rings
    for ref in ("J2", "J3"):
        x, y, _ = layout[ref]
        px, py = xy(x, y)
        r = 8 * scale
        col = colors[ref]
        dr.ellipse([px - r, py - r, px + r, py + r], outline=col, width=3)
    dr.text(xy(4, 6), "MCU  mega-mcu144", fill=(80, 200, 120))
    dr.text(xy(47, 6), "EMI / SuperSeal", fill=(120, 180, 255))
    dr.text(xy(76, 3), "POWER  VBAT N / GND S", fill=(220, 80, 80))
    im.save(PNG)
    print(f"wrote {PNG} {im.size}")


def write_floorplan_ppm(items: list[str], layout: dict) -> None:
    scale = 8
    margin = 16
    w = int(BOARD_W * scale) + 2 * margin
    h = int(BOARD_H * scale) + 2 * margin
    pix = [[(18, 22, 18) for _ in range(w)] for _ in range(h)]

    def setp(x, y, col):
        if 0 <= x < w and 0 <= y < h:
            pix[y][x] = col

    def line(x0, y0, x1, y1, col):
        n = max(abs(x1 - x0), abs(y1 - y0), 1)
        for i in range(n + 1):
            setp(x0 + (x1 - x0) * i // n, y0 + (y1 - y0) * i // n, col)

    def xy(x, y):
        return int(margin + x * scale), int(margin + y * scale)

    x0, y0 = xy(0, 0)
    x1, y1 = xy(BOARD_W, BOARD_H)
    line(x0, y0, x1, y0, (200, 200, 200))
    line(x1, y0, x1, y1, (200, 200, 200))
    line(x1, y1, x0, y1, (200, 200, 200))
    line(x0, y1, x0, y0, (200, 200, 200))
    a, b = xy(45.5, 4)
    c, d = xy(45.5, BOARD_H - 4)
    line(a, b, c, d, (120, 180, 255))
    for ref, (x, y, _) in layout.items():
        px, py = xy(x, y)
        col = (160, 160, 160)
        if ref == "J2":
            col = (220, 40, 40)
        elif ref == "J3":
            col = (50, 90, 210)
        elif ref == "M1000":
            col = (80, 200, 120)
        elif ref == "J1":
            col = (200, 200, 80)
        r = 8 if ref in ("J2", "J3") else 3
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    setp(px + dx, py + dy, col)
    ppm = ROOT / "scripts" / "floorplan_fcu_overview.ppm"
    with ppm.open("w") as f:
        f.write(f"P3\n{w} {h}\n255\n")
        for row in pix:
            f.write(" ".join(f"{r} {g} {b}" for r, g, b in row) + "\n")
    # Prefer PNG name if convert exists.
    dest = PNG
    try:
        import subprocess

        subprocess.run(["convert", str(ppm), str(dest)], check=True, capture_output=True)
        ppm.unlink(missing_ok=True)
        print(f"wrote {dest}")
    except Exception:
        dest = ppm
        print(f"wrote {dest} (install pillow/imagemagick for png)")


def assert_floorplan(layout: dict) -> None:
    mx, my, _ = layout["M1000"]
    j1x, j1y, _ = layout["J1"]
    j2x, j2y, _ = layout["J2"]
    j3x, j3y, _ = layout["J3"]
    assert mx < 45, "M1000 must stay west of the EMI wall"
    assert j1x > mx, "J1 must be east of M1000"
    assert j2x > 74 and j3x > 74, "bobbins must sit in the power field, not the MCU west side"
    assert j2y < 25, "VBAT bobbin should be on the north power edge"
    assert j3y > 70, "GND bobbin should be on the south power edge"
    for ref in ("U1", "U2", "U3", "U4", "U11", "U18"):
        x, y, _ = layout[ref]
        assert j2y < y < j3y, f"{ref} must sit between the bobbins in Y"
        assert x > 45, f"{ref} must not sit on the MCU west side"
    for ref, (x, y, _) in layout.items():
        assert 1 < x < BOARD_W - 1, f"{ref} x off-board {x}"
        assert 1 < y < BOARD_H - 1, f"{ref} y off-board {y}"
        if ref.startswith("U") or ref in {"J2", "J3", "J1", "F1", "M1000"}:
            # 16 mm pad / SuperSeal body keep ~2 mm copper-to-edge
            assert y > 8 or ref not in {"J2", "J3"}, ref
    # Independent footprints — pitch is the north–south span, not 25 mm.
    pitch = abs(j3y - j2y)
    assert pitch > 40, f"split pitch too small ({pitch})"
    print(f"floorplan ok: M6 pitch {pitch:g} mm N–S, board {BOARD_W:g}x{BOARD_H:g}")


def main() -> int:
    layout = apply_adio_offsets(LAYOUT)
    assert_floorplan(layout)
    patch_schematic()

    m6_mod = (PRETTY / "M6_BoltThrough_Bobbin.kicad_mod").read_text()
    if '(footprint "M6_BoltThrough_Bobbin"' not in m6_mod:
        sys.exit("single bobbin footprint missing")

    raw = PCB.read_text()
    if not raw.startswith("(kicad_pcb"):
        sys.exit("pcb is empty or not kicad_pcb — abort")
    m = re.match(r"(\(kicad_pcb\n)([\s\S]*)(\n\)\s*)$", raw)
    if not m:
        sys.exit("unexpected pcb wrapper")
    header_open, inner, _close = m.group(1), m.group(2), m.group(3)
    items = extract_top_items(inner)
    items = [it if it.startswith("\t") else "\t" + it for it in items]

    j1_old = j2_old = None
    new_items = []
    skipped = {"segment": 0, "via": 0, "zone": 0, "gr_line": 0, "gr_text": 0, "gr_rect": 0}
    for it in items:
        head = item_head(it)
        if head in skipped:
            skipped[head] += 1
            continue
        if head == "footprint":
            ref = fp_ref(it)
            if ref == "J1":
                j1_old = it
                new_items.append(it)  # keep existing vertical SuperSeal
                continue
            if ref == "J2":
                j2_old = it
                continue
            if ref == "J3":
                continue
            if ref in layout:
                x, y, rot = layout[ref]
                it = set_fp_at(it, x, y, rot)
            new_items.append(it)
            continue
        if head == "title_block":
            it = re.sub(
                r'\(comment 1 "[^"]*"\)',
                '(comment 1 "PowerCore PDM (pdmrazora) - Razor-class 104x93 - split M6 bobbins opposite power edges")',
                it,
            )
            new_items.append(it)
            continue
        if head == "setup":
            it = re.sub(
                r"\(aux_axis_origin [0-9.]+ [0-9.]+\)",
                f"(aux_axis_origin 0 {BOARD_H:g})",
                it,
            )
            new_items.append(it)
            continue
        new_items.append(it)

    if j1_old is None or j2_old is None:
        sys.exit("J1 or J2 missing — abort")
    j2_nets = fp_pad_nets(j2_old)
    if j2_nets.get("1", (None, None))[1] != "VBAT":
        print("warn: old J2 pad1", j2_nets, file=sys.stderr)
    gnd_net = j2_nets.get("2", ("2", "GND"))
    vbat_net = j2_nets.get("1", ("1", "VBAT"))

    j2_uuid = re.search(r'\(uuid "([^"]+)"\)', j2_old).group(1)
    j3_uuid = uid("fp-j3")
    j2x, j2y, j2r = layout["J2"]
    j3x, j3y, j3r = layout["J3"]
    j2_fp = pretty_to_pcb_fp(
        m6_mod, "pdmrazora:M6_BoltThrough_Bobbin", j2_uuid, j2x, j2y, j2r, {"1": vbat_net}, "J2"
    )
    j2_fp = set_prop(j2_fp, "Value", "M6_VBAT")
    j3_fp = pretty_to_pcb_fp(
        m6_mod, "pdmrazora:M6_BoltThrough_Bobbin", j3_uuid, j3x, j3y, j3r, {"1": gnd_net}, "J3"
    )
    j3_fp = remap_uuids(j3_fp, "j3")
    j3_fp = re.sub(r'\(uuid "[^"]+"\)', f'(uuid "{j3_uuid}")', j3_fp, count=1)
    j3_fp = set_prop(j3_fp, "Value", "M6_GND")
    new_items.append(j2_fp)
    new_items.append(j3_fp)

    graphics = [
        gr_line(0, 0, BOARD_W, 0, "Edge.Cuts", uid("edge-n")),
        gr_line(BOARD_W, 0, BOARD_W, BOARD_H, "Edge.Cuts", uid("edge-e")),
        gr_line(BOARD_W, BOARD_H, 0, BOARD_H, "Edge.Cuts", uid("edge-s")),
        gr_line(0, BOARD_H, 0, 0, "Edge.Cuts", uid("edge-w")),
        gr_line(45.5, 4, 45.5, BOARD_H - 4, "Dwgs.User", uid("emi-line"), width=0.2),
        gr_text("MCU  mega-mcu144 0.7", 4, 8, "Dwgs.User", uid("txt-mcu")),
        gr_text("EMI SPLIT  (vertical SuperSeal)", 46.5, 8, "Dwgs.User", uid("txt-emi"), 1.0),
        gr_text("POWER  VBAT N / drivers / GND S", 68, 4.5, "Dwgs.User", uid("txt-pwr"), 1.0),
        gr_text("J1 TE 6473418-1 vertical SuperSeal 26", 46.5, 90, "Cmts.User", uid("txt-j1"), 1.0),
        gr_text("J2 M6 VBAT+ north   J3 M6 GND south", 68, 2.5, "Cmts.User", uid("txt-j2"), 1.0),
    ]
    mx, my, _ = layout["M1000"]
    zones = [
        zone_rect(2, "GND", "B.Cu", uid("z-gnd-b"), 1, 1, BOARD_W - 1, BOARD_H - 1),
        # VBAT follows entry (north) -> HP tabs (east alley) -> ADIO (south of J1).
        zone_rect(1, "VBAT", "F.Cu", uid("z-vbat-f-n"), 58, 1, BOARD_W - 1, 24, priority=0),
        zone_rect(1, "VBAT", "F.Cu", uid("z-vbat-f-hp"), 74, 32, BOARD_W - 1, 64, priority=0),
        zone_rect(1, "VBAT", "F.Cu", uid("z-vbat-f-adio"), 48, 66, 82, 81, priority=0),
        zone_rect(1, "VBAT", "B.Cu", uid("z-vbat-b-n"), 58, 1, BOARD_W - 1, 24, priority=0),
        zone_rect(2, "GND", "F.Cu", uid("z-gnd-f"), 82, 72, BOARD_W - 1, BOARD_H - 1, priority=0),
        zone_rect(
            0,
            "",
            "F.Cu",
            uid("z-m1000-ko"),
            mx - 0.5,
            my - 40.5,
            mx + 42.7,
            my + 0.5,
            keepout=True,
        ),
    ]
    new_items.extend(graphics)
    new_items.extend(zones)

    inner_out = "\n".join(new_items)
    pcb_out = sanitize_k8(header_open + inner_out + "\n)\n")
    if "(kicad_pcb" not in pcb_out or "(footprint" not in pcb_out:
        sys.exit("refusing to write empty/broken pcb")
    fp_count = pcb_out.count("\n\t(footprint ")
    if fp_count < 50:
        sys.exit(f"too few footprints ({fp_count}) — abort")
    if "M6_BoltThrough_Bobbin_x2" in pcb_out:
        sys.exit("dual-bobbin footprint still on the board — abort")
    if pcb_out.count("M6_BoltThrough_Bobbin") < 2:
        sys.exit("expected two single-bobbin footprints")

    PCB.write_text(pcb_out)

    lines = [f"{ref}=({x}, {y}, {r})" for ref, (x, y, r) in sorted(layout.items())]
    lines.append(f"BOARD={BOARD_W}x{BOARD_H}")
    lines.append(f"M6_PITCH_NS={abs(j3y - j2y)}")
    STATUS.write_text("\n".join(lines) + "\n")

    # Re-parse for the overview plot.
    raw2 = PCB.read_text()
    mm = re.match(r"(\(kicad_pcb\n)([\s\S]*)(\n\)\s*)$", raw2)
    plot_items = extract_top_items(mm.group(2))
    write_floorplan_png(plot_items, layout)

    print(f"wrote {PCB} footprints={fp_count}")
    print("removed", skipped)
    print(f"J2 VBAT {vbat_net} @ ({j2x},{j2y})  J3 GND {gnd_net} @ ({j3x},{j3y})")
    print(f"aux_axis_origin 0 {BOARD_H}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
