#!/usr/bin/env python3
"""Mechanical floorplan redesign for PowerCore (pdmrazora).

Does NOT wipe the board: keeps all footprints, nets, and schematic mapping.
Replaces J2 pin-header with M6 bobbins, places vertical SuperSeal as an EMI
wall, shrinks Edge.Cuts to 104 x 93 mm, and aligns M1000 keepout/value.

Old Manhattan copper is dropped (positions are invalid after the move);
coarse VBAT/GND pours are added for the new outline. Full re-route is human polish.
"""
from __future__ import annotations

import re
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "pdmrazora.kicad_pcb"
PRETTY = ROOT / "pdmrazora.pretty"
STATUS = ROOT / "scripts" / "layout_positions.txt"

BOARD_W = 104.0
BOARD_H = 93.0

# Left = mega-mcu144; center = vertical SuperSeal EMI wall; right = power/PROFET.
# Coordinates are KiCad (origin top-left of Edge.Cuts, Y down).
LAYOUT = {
    "M1000": (2.0, 66.0, 0.0),
    "J1": (50.0, 46.5, 90.0),
    "J2": (91.0, 14.0, 0.0),
    "C1": (70.0, 8.5, 0.0),
    "C2": (70.0, 14.0, 0.0),
    "F1": (70.0, 26.0, 90.0),
    "D1": (70.0, 42.0, 90.0),
    "R1": (78.0, 48.0, 0.0),
    "R2": (84.0, 48.0, 0.0),
    "U1": (80.0, 58.0, 270.0),
    "U2": (96.0, 58.0, 270.0),
    "U3": (80.0, 71.0, 270.0),
    "U4": (96.0, 71.0, 270.0),
    "R10": (70.0, 54.0, 0.0),
    "C10": (70.0, 58.0, 0.0),
    "R20": (86.0, 54.0, 0.0),
    "C20": (86.0, 58.0, 0.0),
    "R30": (70.0, 67.0, 0.0),
    "C30": (70.0, 71.0, 0.0),
    "R40": (86.0, 67.0, 0.0),
    "C40": (86.0, 71.0, 0.0),
    "U11": (70.0, 82.0, 0.0),
    "U12": (80.0, 82.0, 0.0),
    "U13": (90.0, 82.0, 0.0),
    "U14": (97.0, 82.0, 0.0),
    "U15": (70.0, 89.0, 0.0),
    "U16": (80.0, 89.0, 0.0),
    "U17": (90.0, 89.0, 0.0),
    "U18": (97.0, 89.0, 0.0),
}

# ADIO passives: north of top row, east/west of bottom row so they stay on-board.
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


def uid(tag: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pdmrazora-layout/{tag}"))


def fmt_at(x: float, y: float, rot: float) -> str:
    if abs(rot) < 1e-9:
        return f"(at {x:g} {y:g})"
    # KiCad writes -90 for 270 on some footprints; keep 0-359.
    r = rot if rot < 180 else rot - 360
    if abs(r - 0) < 1e-9:
        return f"(at {x:g} {y:g})"
    return f"(at {x:g} {y:g} {r:g})"


def extract_top_items(body: str) -> list[str]:
    """Split kicad_pcb inner body into top-level s-expr items (tab-indented)."""
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
    """pad number -> (netcode, netname). Ignores NC pads that have no net."""
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


def make_superseal_vertical() -> str:
    """Same TE 4x7 / 3 mm pin numbers as CONNECTOR.md; vertical housing courtyard."""
    pads = []
    # Row y, x positions matching existing RA footprint / drawing 9-1437287-8
    rows = [
        (-14.5, [-9, -6, -3, 0, 3, 6, 9], list(range(1, 8))),
        (-12.0, [-7.5, -4.5, -1.5, 1.5, 4.5, 7.5], list(range(8, 14))),
        (-9.0, [-7.5, -4.5, -1.5, 1.5, 4.5, 7.5], list(range(14, 20))),
        (-6.5, [-9, -6, -3, 0, 3, 6, 9], list(range(20, 27))),
    ]
    for y, xs, nums in rows:
        for x, num in zip(xs, nums):
            pads.append(
                f'''	(pad "{num}" thru_hole circle
		(at {x:g} {y:g})
		(size 2 2)
		(drill 1.3)
		(layers "*.Cu" "*.Mask")
		(remove_unused_layers no)
		(uuid "{uid(f"ss-pad-{num}")}")
	)'''
            )
    mount = []
    for i, x in enumerate((-16.25, 16.25)):
        mount.append(
            f'''	(pad "" np_thru_hole circle
		(at {x:g} 0)
		(size 3.3 3.3)
		(drill 3.3)
		(layers "F&B.Cu" "*.Mask")
		(uuid "{uid(f"ss-mtg-{i}")}")
	)'''
        )
    silk_nums = [
        ("1", -10.75, -16.2),
        ("7", 10.75, -16.2),
        ("20", -10.25, -4.4),
        ("26", 10.2, -4.4),
    ]
    silk = []
    for txt, x, y in silk_nums:
        silk.append(
            f'''	(fp_text user "{txt}"
		(at {x:g} {y:g} 0)
		(layer "F.SilkS")
		(uuid "{uid(f"ss-silk-{txt}")}")
		(effects
			(font
				(size 1 1)
				(thickness 0.15)
			)
		)
	)'''
        )
    return f'''(footprint "TE_6473418-1_SuperSeal26_Vertical"
	(version 20240108)
	(generator "pcbnew")
	(generator_version "8.0")
	(layer "F.Cu")
	(descr "TE/AMP SuperSeal 1.0 26-way VERTICAL header; PN 6473418-1. Courtyard is TE width 39 mm x catalog vertical length D 29 mm (fits M1000–HP gap). Cmts.User shows product-page 39x36.5 mm shroud which does NOT fit this EMI-wall nest. Same 3.0 mm 4-row PCB pattern as 9-1437287-8.")
	(tags "TE AMP SuperSeal 1.0 26 6473418-1 6437288-6 vertical Connector C")
	(property "Reference" "REF**"
		(at 0 -24 0)
		(unlocked yes)
		(layer "F.SilkS")
		(uuid "{uid("ss-ref")}")
		(effects
			(font
				(size 1 1)
				(thickness 0.15)
			)
		)
	)
	(property "Value" "6473418-1"
		(at 0 6 0)
		(unlocked yes)
		(layer "F.Fab")
		(uuid "{uid("ss-val")}")
		(effects
			(font
				(size 1 1)
				(thickness 0.15)
			)
		)
	)
	(property "Footprint" "pdmrazora:TE_6473418-1_SuperSeal26_Vertical"
		(at 0 0 0)
		(unlocked yes)
		(layer "F.Fab")
		(hide yes)
		(uuid "{uid("ss-fp")}")
		(effects
			(font
				(size 1.27 1.27)
			)
		)
	)
	(property "Datasheet" "https://www.te.com/en/product-6473418-1.html"
		(at 0 0 0)
		(unlocked yes)
		(layer "F.Fab")
		(hide yes)
		(uuid "{uid("ss-ds")}")
		(effects
			(font
				(size 1.27 1.27)
			)
		)
	)
	(property "Description" "AMP SuperSeal 1.0 26pos vertical Au — Link Connector C pin numbers"
		(at 0 0 0)
		(unlocked yes)
		(layer "F.Fab")
		(hide yes)
		(uuid "{uid("ss-desc")}")
		(effects
			(font
				(size 1.27 1.27)
			)
		)
	)
	(attr through_hole)
	(fp_rect
		(start -19.5 -23.95)
		(end 19.5 5.05)
		(stroke
			(width 0.2)
			(type solid)
		)
		(fill no)
		(layer "F.SilkS")
		(uuid "{uid("ss-silk-rect")}")
	)
	(fp_rect
		(start -19.5 -23.95)
		(end 19.5 5.05)
		(stroke
			(width 0.2)
			(type solid)
		)
		(fill no)
		(layer "B.SilkS")
		(uuid "{uid("ss-bsilk-rect")}")
	)
	(fp_rect
		(start -19.5 -23.95)
		(end 19.5 5.05)
		(stroke
			(width 0.1)
			(type solid)
		)
		(fill no)
		(layer "F.Fab")
		(uuid "{uid("ss-fab-body")}")
	)
	(fp_rect
		(start -19.75 -24.2)
		(end 19.75 5.3)
		(stroke
			(width 0.05)
			(type solid)
		)
		(fill no)
		(layer "F.CrtYd")
		(uuid "{uid("ss-crtyd")}")
	)
	(fp_rect
		(start -19.5 -31.45)
		(end 19.5 5.05)
		(stroke
			(width 0.12)
			(type dash)
		)
		(fill no)
		(layer "Cmts.User")
		(uuid "{uid("ss-shroud-365")}")
	)
	(fp_text user "VERTICAL / EMI SPLIT"
		(at 0 -19 0)
		(layer "Cmts.User")
		(uuid "{uid("ss-emi")}")
		(effects
			(font
				(size 0.9 0.9)
				(thickness 0.12)
			)
		)
	)
	(fp_text user "${{REFERENCE}}"
		(at 0 2.2 0)
		(unlocked yes)
		(layer "F.Fab")
		(uuid "{uid("ss-fabref")}")
		(effects
			(font
				(size 1 1)
				(thickness 0.15)
			)
		)
	)
{chr(10).join(silk)}
{chr(10).join(mount)}
{chr(10).join(pads)}
)
'''


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
		)
		(placement
			(enabled no)
			(sheetname "")
		)"""
    fill = "(fill no" if keepout else "(fill yes"
    layer_line = (
        f'(layers {layer})' if " " in layer and not layer.startswith("F.") and "F.Cu" in layer
        else f'(layers {layer})' if layer.startswith('"F.Cu"')
        else f'(layer "{layer}")'
    )
    if keepout:
        layer_line = '(layers "F.Cu" "B.Cu")'
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
        if n <= 14:
            out[r] = (ux - 3.0, uy - 6.5, 0.0)
            out[c] = (ux + 3.0, uy - 6.5, 0.0)
            out[pu] = (ux, uy - 4.0, 0.0)
        else:
            out[r] = (ux - 4.4, uy, 0.0)
            out[c] = (ux + 4.4, uy, 0.0)
            out[pu] = (ux, uy - 3.2, 0.0)
    return out


def patch_m1000(item: str) -> str:
    item = re.sub(
        r'\(property "Value" "Module:mega[-_]mcu144/0\.[0-9]+"',
        '(property "Value" "Module:mega-mcu144/0.7"',
        item,
        count=1,
    )
    # Align keepout with silk / pads (official 0.7 polygon).
    item = re.sub(
        r"\(pts\s*\n\s*\(xy 35\.199999 -3\.099999\) \(xy -6\.900001 -3\.099999\) \(xy -6\.900001 -42\.999998\) \(xy 35\.200002 -42\.999998\)\s*\)",
        "(pts\n\t\t\t\t\t(xy 42.199999 -0.099999) (xy 0.099999 -0.099999) (xy 0.099999 -39.999998) (xy 42.200002 -39.999998)\n\t\t\t\t)",
        item,
        count=1,
    )
    if "42.199999 -0.099999" not in item:
        # fallback: any keepout polygon inside this footprint
        item = re.sub(
            r"(\(keepout[\s\S]*?\(polygon\s*\(pts\s*)\([^)]+\) \([^)]+\) \([^)]+\) \([^)]+\)",
            r"\1(xy 42.199999 -0.099999) (xy 0.099999 -0.099999) (xy 0.099999 -39.999998) (xy 42.200002 -39.999998)",
            item,
            count=1,
        )
    return item


def main() -> int:
    layout = apply_adio_offsets(LAYOUT)
    ss_mod = make_superseal_vertical()
    (PRETTY / "TE_6473418-1_SuperSeal26_Vertical.kicad_mod").write_text(ss_mod)
    m6_mod = (PRETTY / "M6_BoltThrough_Bobbin_x2.kicad_mod").read_text()

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
    embedded = None
    for it in items:
        head = item_head(it)
        if head in skipped:
            skipped[head] += 1
            continue
        if head == "embedded_fonts":
            embedded = it
            continue
        if head == "footprint":
            ref = fp_ref(it)
            if ref == "J1":
                j1_old = it
                continue
            if ref == "J2":
                j2_old = it
                continue
            if ref == "M1000":
                it = patch_m1000(it)
            if ref in layout:
                x, y, rot = layout[ref]
                it = set_fp_at(it, x, y, rot)
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
        sys.exit("J1 or J2 missing — abort (board would lose power/connector)")

    j1_nets = fp_pad_nets(j1_old)
    j2_nets = fp_pad_nets(j2_old)
    required_j1 = {str(n) for n in range(1, 27)} - {"2", "9", "25"}
    missing = required_j1 - set(j1_nets)
    if missing:
        sys.exit(f"J1 pad nets missing {sorted(missing, key=int)}: {sorted(j1_nets)}")
    if j2_nets.get("1", (None, None))[1] != "VBAT" or j2_nets.get("2", (None, None))[1] != "GND":
        print("warn: J2 nets", j2_nets, file=sys.stderr)

    j1_uuid = re.search(r'\(uuid "([^"]+)"\)', j1_old).group(1)
    j2_uuid = re.search(r'\(uuid "([^"]+)"\)', j2_old).group(1)
    j1x, j1y, j1r = layout["J1"]
    j2x, j2y, j2r = layout["J2"]
    j1_fp = pretty_to_pcb_fp(
        ss_mod, "pdmrazora:TE_6473418-1_SuperSeal26_Vertical", j1_uuid, j1x, j1y, j1r, j1_nets, "J1"
    )
    j2_fp = pretty_to_pcb_fp(
        m6_mod, "pdmrazora:M6_BoltThrough_Bobbin_x2", j2_uuid, j2x, j2y, j2r, j2_nets, "J2"
    )
    new_items.append(j1_fp)
    new_items.append(j2_fp)

    # Graphics + zones for the shrunk board.
    graphics = [
        gr_line(0, 0, BOARD_W, 0, "Edge.Cuts", uid("edge-n")),
        gr_line(BOARD_W, 0, BOARD_W, BOARD_H, "Edge.Cuts", uid("edge-e")),
        gr_line(BOARD_W, BOARD_H, 0, BOARD_H, "Edge.Cuts", uid("edge-s")),
        gr_line(0, BOARD_H, 0, 0, "Edge.Cuts", uid("edge-w")),
        gr_line(45.5, 4, 45.5, BOARD_H - 4, "Dwgs.User", uid("emi-line"), width=0.2),
        gr_text("MCU  mega-mcu144 0.7", 4, 8, "Dwgs.User", uid("txt-mcu")),
        gr_text("EMI SPLIT  (vertical SuperSeal)", 46.5, 8, "Dwgs.User", uid("txt-emi"), 1.0),
        gr_text("POWER / PROFET  (HP+ADIO+M6)", 70, 4.5, "Dwgs.User", uid("txt-pwr"), 1.0),
        gr_text("J1 TE 6473418-1 vertical SuperSeal 26", 46.5, 90, "Cmts.User", uid("txt-j1"), 1.0),
        gr_text("J2 M6 bolt-through bobbins VBAT+/GND", 70, 2.5, "Cmts.User", uid("txt-j2"), 1.0),
    ]
    mx, my, _ = layout["M1000"]
    zones = [
        zone_rect(2, "GND", "B.Cu", uid("z-gnd-b"), 1, 1, BOARD_W - 1, BOARD_H - 1),
        zone_rect(1, "VBAT", "F.Cu", uid("z-vbat-f"), 67, 1, BOARD_W - 1, BOARD_H - 1, priority=0),
        zone_rect(2, "GND", "F.Cu", uid("z-gnd-f"), 67, 1, BOARD_W - 1, BOARD_H - 1, priority=0),
        # Module pour keepout aligned with M1000 silk (42.2 x 40).
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
    if embedded:
        new_items.append(embedded)

    # Recreate inner with original-style newlines between items.
    inner_out = "\n".join(new_items)
    pcb_out = header_open + inner_out + "\n)\n"
    if "(kicad_pcb" not in pcb_out or "(footprint" not in pcb_out:
        sys.exit("refusing to write empty/broken pcb")
    fp_count = pcb_out.count("\n\t(footprint ")
    if fp_count < 50:
        sys.exit(f"too few footprints ({fp_count}) — abort")

    shutil.copy(PCB, PCB.with_suffix(".kicad_pcb.bak_pre_layout"))
    PCB.write_text(pcb_out)

    # positions dump
    lines = [f"{ref}=({x}, {y}, {r})" for ref, (x, y, r) in sorted(layout.items())]
    lines.append(f"BOARD={BOARD_W}x{BOARD_H}")
    STATUS.write_text("\n".join(lines) + "\n")

    print(f"wrote {PCB} footprints={fp_count}")
    print("removed", skipped)
    print(f"J1 pads with nets: {len(j1_nets)}  J2: {j2_nets}")
    print(f"aux_axis_origin 0 {BOARD_H}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
