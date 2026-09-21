#!/usr/bin/env python3
"""Cut DRC crossings with S-expr edits (no pcbnew SaveBoard / zone fill).

Phases, each DRC-gated (shorts ≤ baseline, EN/IS unc = 0):
  1. Nudge IN_AUX1 B feeder 70 → 87.4 (J1 pin-gap, east of 2 mm pads @66–84).
  2. F-hop EN pad-approach H that span SENSOR_5V x=52.
  3. F-hop ADIO5–8 U-turn H across IS feeders (east via in RES2/RES3 gap).
  4. F-hop ADIO4 east stub across MAP1 x=73 (east of VBAT F @x=70).
  5. F-hop AUX2 feeder through ADIO remainder (vias off ADIO H Y).
  6. F-hop OUT_IO6 bot highway across MAP1 x=73.
  7. Jog AUX4 feeder to x=139 through ADIO Y (east of SENSOR F @138).

Does not touch HELLCORE / Micro Core. Keeps K8 headers (text-level only).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path("/workspace")
PCB = ROOT / "pdmrazora.kicad_pcb"
STATUS = ROOT / "scripts" / "copper_status.txt"
SNAP = Path("/tmp/drc/pdmrazora.cut_snap.kicad_pcb")
BASE = Path("/tmp/drc/pdmrazora.cut_base.kicad_pcb")
DRC_JSON = Path("/tmp/drc/cut_gate.json")

NET_NAME: dict[int, str] = {}

SEG_RE = re.compile(
    r"\t\(segment\n"
    r"\t\t\(start ([0-9.-]+) ([0-9.-]+)\)\n"
    r"\t\t\(end ([0-9.-]+) ([0-9.-]+)\)\n"
    r"\t\t\(width ([0-9.]+)\)\n"
    r"\t\t\(layer \"([^\"]+)\"\)\n"
    r"\t\t\(net (\d+)\)\n"
    r"\t\t\(uuid \"([^\"]+)\"\)\n"
    r"\t\)\n",
    re.M,
)

EN_IS = {
    "OUT_PWM1", "OUT_PWM2", "OUT_PWM3", "OUT_PWM4",
    "OUT_PWM5", "OUT_PWM6", "OUT_PWM7", "OUT_PWM8",
    "OUT_IO5", "OUT_IO6", "OUT_IO7", "OUT_IO8",
    "IN_AUX1", "IN_AUX2", "IN_AUX3", "IN_AUX4",
    "IN_MAP1", "IN_MAP2", "IN_MAP3", "IN_O2S",
    "IN_O2S2", "IN_RES1", "IN_RES2", "IN_RES3",
}
EN_HOP = {
    "OUT_IO5", "OUT_IO6", "OUT_IO7", "OUT_IO8",
    "OUT_PWM3", "OUT_PWM4", "OUT_PWM5", "OUT_PWM6",
    "OUT_PWM7", "OUT_PWM8",
}

AUX1_OLD = 70.0
AUX1_NEW = 87.4


def parse_nets(text: str) -> None:
    NET_NAME.clear()
    for m in re.finditer(r'\t\(net (\d+) "([^"]*)"\)', text):
        NET_NAME[int(m.group(1))] = m.group(2)


def via_block(x, y, net, size=0.6, drill=0.3):
    return (
        "\t(via\n"
        f"\t\t(at {x:g} {y:g})\n"
        f"\t\t(size {size:g})\n"
        f"\t\t(drill {drill:g})\n"
        '\t\t(layers "F.Cu" "B.Cu")\n'
        f"\t\t(net {net})\n"
        f'\t\t(uuid "{uuid.uuid4()}")\n'
        "\t)\n"
    )


def seg_block(x1, y1, x2, y2, width, layer, net):
    if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
        return ""
    return (
        "\t(segment\n"
        f"\t\t(start {x1:g} {y1:g})\n"
        f"\t\t(end {x2:g} {y2:g})\n"
        f"\t\t(width {width:g})\n"
        f'\t\t(layer "{layer}")\n'
        f"\t\t(net {net})\n"
        f'\t\t(uuid "{uuid.uuid4()}")\n'
        "\t)\n"
    )


def run_drc():
    DRC_JSON.parent.mkdir(parents=True, exist_ok=True)
    if DRC_JSON.exists():
        DRC_JSON.unlink()
    proc = subprocess.run(
        ["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error",
         "--output", str(DRC_JSON), str(PCB)],
        capture_output=True, text=True,
    )
    err = (proc.stderr or "") + (proc.stdout or "")
    if not DRC_JSON.exists() or "Saved DRC Report" not in err:
        raise RuntimeError(err[-800:])
    return json.loads(DRC_JSON.read_text())


def metrics(drc):
    shorts = sum(1 for v in drc["violations"] if v["type"] == "shorting_items")
    cross = sum(1 for v in drc["violations"] if v["type"] == "tracks_crossing")
    unc = len(drc.get("unconnected_items", []))
    return shorts, cross, unc


def en_is_unc(drc):
    pat = re.compile(r"\[([^\]]+)\]")
    n, open_nets = 0, set()
    for item in drc.get("unconnected_items", []):
        nets = set()
        for it in item.get("items", []):
            m = pat.search(it.get("description", ""))
            if m:
                nets.add(m.group(1))
        hit = nets & EN_IS
        if hit:
            n += 1
            open_nets |= hit
    return n, sorted(open_nets)


def classify(drc):
    pat = re.compile(r"\[([^\]]+)\]")
    EN = {x for x in EN_IS if x.startswith("OUT_")}
    IS_ = {x for x in EN_IS if x.startswith("IN_")}

    def fam(n):
        if n in EN:
            return "EN"
        if n in IS_:
            return "IS"
        if n.startswith("ADIO"):
            return "ADIO"
        if "SENSOR" in n:
            return "SENSOR"
        return "OTH"

    pairs = Counter()
    for v in drc["violations"]:
        if v["type"] != "tracks_crossing":
            continue
        nets = set()
        for it in v.get("items", []):
            m = pat.search(it.get("description", ""))
            if m:
                nets.add(m.group(1))
        ns = sorted(nets)
        if len(ns) >= 2:
            pairs["-".join(sorted([fam(ns[0]), fam(ns[1])]))] += 1
    return dict(pairs)


def dump_shorts(drc):
    extra = 0
    for v in drc["violations"]:
        if v["type"] != "shorting_items":
            continue
        blob = json.dumps(v)
        if "J2" in blob and "VBAT" in blob and "GND" in blob:
            continue
        extra += 1
        print("  SHORT", [it.get("description", "")[:100] for it in v["items"]])
    return extra


def restore():
    shutil.copy2(SNAP, PCB)


def commit_snap():
    shutil.copy2(PCB, SNAP)


def phase_aux1(text: str) -> tuple[str, int]:
    """Rewrite AUX1 B corners that sit on x=70."""
    parse_nets(text)
    nrep = 0
    old, new = AUX1_OLD, AUX1_NEW

    def repl(m):
        nonlocal nrep
        x1, y1, x2, y2 = map(float, m.group(1, 2, 3, 4))
        width = float(m.group(5))
        layer = m.group(6)
        net = int(m.group(7))
        name = NET_NAME.get(net, "")
        if name != "IN_AUX1" or layer != "B.Cu":
            return m.group(0)
        ch = False
        nx1, nx2 = x1, x2
        if abs(x1 - old) < 0.08:
            nx1 = new
            ch = True
        if abs(x2 - old) < 0.08:
            nx2 = new
            ch = True
        if not ch:
            return m.group(0)
        nrep += 1
        print(f"  AUX1 ({x1:g},{y1:g})-({x2:g},{y2:g}) → ({nx1:g},{y1:g})-({nx2:g},{y2:g})")
        return seg_block(nx1, y1, nx2, y2, width, layer, net)

    return SEG_RE.sub(repl, text), nrep


def phase_en_x52(text: str) -> tuple[str, int]:
    parse_nets(text)
    nrep = 0

    def repl(m):
        nonlocal nrep
        x1, y1, x2, y2 = map(float, m.group(1, 2, 3, 4))
        width = float(m.group(5))
        layer = m.group(6)
        net = int(m.group(7))
        name = NET_NAME.get(net, "")
        if layer != "B.Cu" or name not in EN_HOP:
            return m.group(0)
        if abs(y1 - y2) > 0.08:
            return m.group(0)
        y = y1
        xa, xb = (x1, x2) if x1 < x2 else (x2, x1)
        if not (8.0 <= y <= 48.7 and xa <= 50.15 and xb >= 52.40):
            return m.group(0)
        east = xb if xb < 55.0 else 55.50
        nrep += 1
        print(f"  EN {name} y={y:g} F 50-{east:g}"
              + (f" B {east:g}-{xb:g}" if xb - east > 0.05 else ""))
        body = via_block(50.0, y, net) + via_block(east, y, net)
        body += seg_block(50.0, y, east, y, width, "F.Cu", net)
        if xb - east > 0.05:
            body += seg_block(east, y, xb, y, width, "B.Cu", net)
        return body

    return SEG_RE.sub(repl, text), nrep


def phase_adio_uturn(text: str) -> tuple[str, int]:
    """F-hop ADIO5–8 U-turn H across IS feeders; east via in RES2/RES3 gap."""
    parse_nets(text)
    nrep = 0
    mid = {"ADIO5": 129.10, "ADIO6": 130.00, "ADIO7": 130.90, "ADIO8": 131.80}

    def repl(m):
        nonlocal nrep
        x1, y1, x2, y2 = map(float, m.group(1, 2, 3, 4))
        width = float(m.group(5))
        layer = m.group(6)
        net = int(m.group(7))
        name = NET_NAME.get(net, "")
        if layer != "B.Cu" or name not in mid:
            return m.group(0)
        if abs(y1 - y2) > 0.08:
            return m.group(0)
        y = y1
        xa, xb = (x1, x2) if x1 < x2 else (x2, x1)
        if not (105.20 <= y <= 107.10 and xa <= 80 and xb >= 130):
            return m.group(0)
        mx = mid[name]
        nrep += 1
        print(f"  ADIO {name} y={y:g} F {xa:g}-{mx:g} B {mx:g}-{xb:g}")
        # Preserve left-to-right vs original: west via at xa (J1 side).
        body = via_block(xa, y, net) + via_block(mx, y, net)
        body += seg_block(xa, y, mx, y, width, "F.Cu", net)
        body += seg_block(mx, y, xb, y, width, "B.Cu", net)
        return body

    return SEG_RE.sub(repl, text), nrep


def phase_adio4_map1(text: str) -> tuple[str, int]:
    """F-hop ADIO4 U-turn east stub across MAP1 x=73, east of VBAT F @x=70."""
    parse_nets(text)
    nrep = 0
    split = 71.10

    def repl(m):
        nonlocal nrep
        x1, y1, x2, y2 = map(float, m.group(1, 2, 3, 4))
        width = float(m.group(5))
        layer = m.group(6)
        net = int(m.group(7))
        name = NET_NAME.get(net, "")
        if name != "ADIO4" or layer != "B.Cu":
            return m.group(0)
        if abs(y1 - y2) > 0.08:
            return m.group(0)
        y = y1
        if abs(y - 106.9) > 0.08:
            return m.group(0)
        xa, xb = (x1, x2) if x1 < x2 else (x2, x1)
        if xa > 60.5 or xb < 73.0:
            return m.group(0)
        nrep += 1
        print(f"  ADIO4 y={y:g} B {xa:g}-{split:g} F {split:g}-{xb:g}")
        body = seg_block(xa, y, split, y, width, "B.Cu", net)
        body += via_block(split, y, net)
        body += seg_block(split, y, xb, y, width, "F.Cu", net)
        body += via_block(xb, y, net)
        return body

    return SEG_RE.sub(repl, text), nrep


def phase_aux2_adio(text: str) -> tuple[str, int]:
    """F-hop AUX2 feeder through ADIO remainder; vias off ADIO H Y."""
    parse_nets(text)
    nrep = 0
    y0, y1 = 104.35, 107.85

    def repl(m):
        nonlocal nrep
        x1, y1s, x2, y2s = map(float, m.group(1, 2, 3, 4))
        width = float(m.group(5))
        layer = m.group(6)
        net = int(m.group(7))
        name = NET_NAME.get(net, "")
        if layer != "B.Cu" or name != "IN_AUX2":
            return m.group(0)
        if abs(x1 - x2) > 0.08:
            return m.group(0)
        x = x1
        if abs(x - 135.5) > 0.08:
            return m.group(0)
        ya, yb = (y1s, y2s) if y1s < y2s else (y2s, y1s)
        if ya > y0 - 0.2 or yb < y1 + 0.2:
            return m.group(0)
        nrep += 1
        print(f"  AUX2 x={x:g} F {y0:g}-{y1:g}")
        if y1s < y2s:
            body = seg_block(x, y1s, x, y0, width, "B.Cu", net)
            body += via_block(x, y0, net)
            body += seg_block(x, y0, x, y1, width, "F.Cu", net)
            body += via_block(x, y1, net)
            body += seg_block(x, y1, x, y2s, width, "B.Cu", net)
        else:
            body = seg_block(x, y1s, x, y1, width, "B.Cu", net)
            body += via_block(x, y1, net)
            body += seg_block(x, y1, x, y0, width, "F.Cu", net)
            body += via_block(x, y0, net)
            body += seg_block(x, y0, x, y2s, width, "B.Cu", net)
        return body

    return SEG_RE.sub(repl, text), nrep


def phase_io6_map1(text: str) -> tuple[str, int]:
    """F-hop OUT_IO6 bot highway across MAP1 x=73."""
    parse_nets(text)
    nrep = 0
    west, east = 71.80, 74.20

    def repl(m):
        nonlocal nrep
        x1, y1, x2, y2 = map(float, m.group(1, 2, 3, 4))
        width = float(m.group(5))
        layer = m.group(6)
        net = int(m.group(7))
        name = NET_NAME.get(net, "")
        if layer != "B.Cu" or name != "OUT_IO6":
            return m.group(0)
        if abs(y1 - y2) > 0.08 or abs(y1 - 53.70) > 0.08:
            return m.group(0)
        xa, xb = (x1, x2) if x1 < x2 else (x2, x1)
        if xa > 72.0 or xb < 74.0:
            return m.group(0)
        nrep += 1
        print(f"  IO6 y=53.7 F {west:g}-{east:g}")
        body = seg_block(xa, y1, west, y1, width, "B.Cu", net)
        body += via_block(west, y1, net)
        body += seg_block(west, y1, east, y1, width, "F.Cu", net)
        body += via_block(east, y1, net)
        body += seg_block(east, y1, xb, y1, width, "B.Cu", net)
        return body

    return SEG_RE.sub(repl, text), nrep


def phase_aux4_jog(text: str) -> tuple[str, int]:
    """Jog AUX4 feeder to x=139 through ADIO Y (east of SENSOR F @138)."""
    parse_nets(text)
    nrep = 0
    y0, y1 = 104.35, 107.85
    jx = 139.00

    def repl(m):
        nonlocal nrep
        x1, y1s, x2, y2s = map(float, m.group(1, 2, 3, 4))
        width = float(m.group(5))
        layer = m.group(6)
        net = int(m.group(7))
        name = NET_NAME.get(net, "")
        if layer != "B.Cu" or name != "IN_AUX4":
            return m.group(0)
        if abs(x1 - x2) > 0.08:
            return m.group(0)
        x = x1
        if abs(x - 138.25) > 0.08:
            return m.group(0)
        ya, yb = (y1s, y2s) if y1s < y2s else (y2s, y1s)
        if ya > y0 - 0.2 or yb < y1 + 0.2:
            return m.group(0)
        nrep += 1
        print(f"  AUX4 x={x:g} jog {jx:g} F {y0:g}-{y1:g}")
        body = seg_block(x, ya, x, y0, width, "B.Cu", net)
        body += seg_block(x, y0, jx, y0, width, "B.Cu", net)
        body += via_block(jx, y0, net)
        body += seg_block(jx, y0, jx, y1, width, "F.Cu", net)
        body += via_block(jx, y1, net)
        body += seg_block(jx, y1, x, y1, width, "B.Cu", net)
        body += seg_block(x, y1, x, yb, width, "B.Cu", net)
        return body

    return SEG_RE.sub(repl, text), nrep


PHASES = [
    ("aux1_87.4", phase_aux1),
    ("en_x52", phase_en_x52),
    ("adio5-8", phase_adio_uturn),
    ("adio4_map1", phase_adio4_map1),
    ("aux2_adio", phase_aux2_adio),
    ("io6_map1", phase_io6_map1),
    ("aux4_jog139", phase_aux4_jog),
]


def gate(label, fn, s0) -> bool:
    text = PCB.read_text()
    new, n = fn(text)
    if n == 0:
        print(f"  {label}: no matches — skip")
        return False
    PCB.write_text(new)
    drc = run_drc()
    s, c, u = metrics(drc)
    e, opn = en_is_unc(drc)
    extra = dump_shorts(drc)
    print(f"  GATE {label}: n={n} shorts={s} extra={extra} cross={c} unc={u} "
          f"en_is={e} classes={classify(drc)}")
    if s > s0 or e != 0:
        print(f"  FAIL {label} open={opn} — restore")
        restore()
        return False
    print(f"  KEEP {label}")
    commit_snap()
    return True


def main():
    print("=== cut crossings (S-expr, no pcbnew save) ===")
    SNAP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PCB, BASE)
    shutil.copy2(PCB, SNAP)

    drc0 = run_drc()
    s0, c0, u0 = metrics(drc0)
    e0, _ = en_is_unc(drc0)
    print(f"BEFORE shorts={s0} cross={c0} unc={u0} en_is={e0} classes={classify(drc0)}")
    if e0 != 0:
        print("baseline EN/IS not closed — abort")
        return 1

    kept = []
    for label, fn in PHASES:
        print(f"\n-- phase {label} --")
        if gate(label, fn, s0):
            kept.append(label)

    drc1 = run_drc()
    s1, c1, u1 = metrics(drc1)
    e1, open1 = en_is_unc(drc1)
    print(f"\nAFTER shorts={s1} cross={c1} unc={u1} en_is={e1} open={open1} "
          f"classes={classify(drc1)}")
    dump_shorts(drc1)

    tr = len(re.findall(r"\(segment\n", PCB.read_text()))
    vias = len(re.findall(r"\t\(via\n", PCB.read_text()))
    with STATUS.open("w") as f:
        f.write(f"before_shorts={s0}\n")
        f.write(f"before_crossings={c0}\n")
        f.write(f"before_unc={u0}\n")
        f.write(f"before_en_is_unc={e0}\n")
        f.write(f"after_shorts={s1}\n")
        f.write(f"after_crossings={c1}\n")
        f.write(f"after_unc={u1}\n")
        f.write(f"after_en_is_unc={e1}\n")
        f.write(f"after_tracks={tr}\n")
        f.write(f"after_vias={vias}\n")
        f.write(f"kept_phases={','.join(kept)}\n")
        f.write("strategy=aux1_j1gap_en_x52_adio_fhop_aux2_aux4jog_sexp\n")
        f.write("note=S-expr hops; no pcbnew save; EN/IS unrebuilt; HELLCORE untouched\n")

    # Require a real cut vs the PR #1 claim of 106, not DRC flake 106↔107.
    target = min(c0, 106) - 5
    if s1 > s0 or e1 != 0 or c1 > target:
        print(f"FAIL s {s0}->{s1} c {c0}->{c1} (need <= {target}) e {e1}")
        # Keep whatever gated phases passed; they are already on SNAP/PCB.
        # Only hard-restore if shorts/EN-IS broke (gate already restored those).
        if s1 > s0 or e1 != 0:
            shutil.copy2(BASE, PCB)
            return 1
        if c1 >= min(c0, 106):
            print("no crossing cut vs 106 — restore baseline")
            shutil.copy2(BASE, PCB)
            return 1
        print(f"partial cut {c0}->{c1} kept phases={kept}")
        return 0
    print(f"OK crossings {c0} -> {c1} (delta {c1 - c0}) phases={kept}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
