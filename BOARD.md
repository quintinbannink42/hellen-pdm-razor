# Board status — PowerCore (`pdmrazora` rev a)

Open with **KiCad 8.x** (Hellen mega-mcu144 0.7 is K8). KiCad 9 also works. KiCad 6/7 will not open this module.

## This commit — split M6 bobbins onto opposite power-field edges

Quintin: *“Split the Vbat & ground bobbins and place them on opposite sides of the board (not on the same side as the m1000) with the drivers inbetween.”*

This is a **placement / floorplan** change. The 25 mm dual-bobbin `J2` footprint is gone from the PCB. VBAT+ and GND are two instances of `pdmrazora:M6_BoltThrough_Bobbin` so they can move independently. East copper that assumed the paired M6 spine was **wiped** (tracks/vias/filled polygons). Zone **outlines** were rewritten for the new entry geometry and are **unfilled**. Signal/power re-route + zone fill is a follow-up — this board is **not DRC-clean**.

[F.Cu floorplan overview](scripts/floorplan_fcu_overview.png)

| Item | Status |
|------|--------|
| Outline | **104 × 93 mm** Razor-class (unchanged; no grow needed) |
| AUX origin | **(0, 93)** |
| M1000 | West `(2, 66)` — **unchanged**; still west of vertical SuperSeal |
| J1 | `(50, 46.5)` rot 90° — **unchanged** EMI wall |
| J2 | **VBAT+** single M6 @ `(92, 11)` — **north** edge of the power field |
| J3 | **GND** single M6 @ `(92, 82)` — **south** edge of the power field |
| M6 pitch | **71 mm** north–south (not 25 mm co-located) |
| Drivers | HP 2×2 east alley @ y=40/53; ADIO 2×4 south of J1 @ y=69.5/77.5 — **between** the bobbins |
| Power entry | F1 ATO placeholder + C1/C2 in the north pocket on the VBAT path; D1 east of F1 |
| Tracks / vias | **0 / 0** (old paired-spine copper stripped; stitch vias live in each bobbin footprint) |
| Zones | **7 unfilled outlines** — GND B full-board, VBAT F north/HP/ADIO, VBAT B north, GND F around J3, M1000 keepout. **No SENSOR pour** |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |
| Footprints | **54** (was 53; J2 split into J2+J3) |
| F1 | ATO placeholder **moved** with the VBAT path; still a placeholder |

`kicad-cli pcb drc` is **not claimed**. Unconnected count will be high until the copper follow-up. Do **not** replay `scripts/cut_crossings_sexp.py` or other 150×130 longhaul scripts.

## Previous commit — zone fill + M6/HP stitch (104×93 EMI split)

Critical-net copper from the previous commit is **unchanged in plan** (no footprint moves, no 150×130 scripts, F1 ATO left). Pours are now **filled** in pcbnew 8.0.9. No SENSOR pour was added (none existed; SENSOR_GND stays off chassis).

That fill assumed **co-located** east M6 bobbins and was **invalidated** by this floorplan (copper stripped).

| Item | Status |
|------|--------|
| Tracks / vias | **385 / 158** (was 385 / 136) — +10 M6 bobbin vias, +12 HP-tab thermal vias |
| Zones filled | **7** copper pours (GND B full-board, GND F M6−, VBAT F entry/HP/ADIO, VBAT B entry + U1/U2 tab island). Keepout punches M1000. |
| Pad connect | **solid** on VBAT/GND (not thermal spokes) |
| SENSOR pour | **None** (not present; not added) |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |
| Footprints | **53** |

## Previous commit — critical-net re-route on the 104×93 floorplan

Mechanical placement from the previous commit is **unchanged** (53 footprints, 104×93 mm, M6 bobbins, vertical SuperSeal EMI wall, M1000 keepout). Old 150×130 copper scripts were **not** reapplied.

| Item | Status |
|------|--------|
| Tracks / vias | **385 / 136** (was 0 / 0 after the move) |
| EN/IS (HP1–4 + ADIO1–8) | **Connected** (exclusive EN B.Cu south-of-J1 highways + MCU-gap columns; IS local F + B.Cu east-skirt long-haul to S pads) |
| PWR_OUT1–4 / ADIO1–8 | **Connected** to SuperSeal (U1/U2 west of EN band; U3/U4 F-hop; ADIO 0.80 mm columns) |
| VBAT | F.Cu entry spine M6+→F1→C/D + B.Cu east alley to HP tabs; module N27 via **north corridor only** |
| GND | B.Cu full-board pour + sparse local F stubs/vias (no overcrowded east packs); **no SENSOR_GND bond**; M6− F island only |
| CAN / SENSOR_5V / SENSOR_GND / IGN_SW / IN_VIGN | **Connected** (north/east skirt; SENSOR_5V does not traverse the EN field) |
| USB | On-module only (USB-C is on mega-mcu144) — not a carrier leftover |
| J1 courtyard | **39.5 × 29.5 mm** (TE width 39 × catalog vertical D 29). Product-page **39 × 36.5 mm** shroud is on Cmts.User and **does not fit** between M1000 and U1 without moving HP. |
| Via packs (size+0.22) | **0** |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |
| F1 | **ATO placeholder left** (Jeoff: do not block) |
| Footprints | **53** |

`kicad-cli pcb drc` was **not available** in that agent VM. Geometric H–V scan (not KiCad DRC) still saw same-layer crossings in the packed east/south field. Zone fill + DRC is this follow-up.

See [scripts/unconnected_leftover.txt](scripts/unconnected_leftover.txt).

## Previous commit — mechanical / floorplan redesign (Quintin)

| Item | Status |
|------|--------|
| Outline | **150 × 130 → 104 × 93 mm** (Link Razor class: enclosure 103.6 × 93.4) |
| AUX origin | **(0, 93)** — Edge.Cuts bottom-left; no negative board coords |
| J2 | **M6 bolt-through bobbins** (6.5 mm drill / 16 mm Cu / 25 mm pitch / via stitch) — previous 2.54 mm pin-header VBAT↔GND short is gone by construction |
| J1 | **Vertical** SuperSeal 26 (`6473418-1`), rotated 90° as EMI wall |
| EMI split | mega-mcu144 **west** of J1; power / PROFET / M6 **east** |
| M1000 | Keepout aligned to silk/pads (official 0.7 polygon); Value **`Module:mega-mcu144/0.7`** |
| Zones | **GND B.Cu** full-board + **VBAT F.Cu** entry/HP/ADIO islands (GND F only around M6−) + module pour keepout |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |
| Footprints | **53** (non-empty board) |

See [HARDWARE_BOM.md](HARDWARE_BOM.md) for kILIS / AmpsPerVolt TODOs.

## Floorplan (mm)

KiCad origin = Edge.Cuts top-left; Y down. AUX = bottom-left `(0, 93)`.

| Block | Placement |
|-------|-----------|
| M1000 | West `(2, 66)` — 42.2 × 40 mm module, keepout on pads |
| J1 EMI wall | `(50, 46.5)` **rot 90°** — vertical SuperSeal between MCU and power |
| J2 VBAT+ M6 | North power-field edge `(92, 11)` — 16 mm Cu, **not** on the MCU west side |
| J3 GND M6 | South power-field edge `(92, 82)` — opposite J2; 71 mm N–S span |
| Power entry | F1 ATO placeholder `(58, 18)` + C1/C2 in the north pocket on the VBAT path; D1 `(80, 28)` |
| HP ×4 | East alley 2×2 @ `(80/96, 40/53)` rot 270° (tabs face north / VBAT) |
| ADIO ×8 | South of SuperSeal 2×4 @ `(52…76, 69.5/77.5)`, west of J3, **between** the bobbins in Y |

```
x=0                    x=45                 x=74                 x=104
+----------------------+--------------------+--------------------+
| mega-mcu144 (M1000)  | vertical SuperSeal | J2 VBAT+ M6 (north)|
| quiet / logic        | 26  EMI SPLIT      | HP PROFET          |
|                      |                    | ADIO  (between)    |
|                      |                    | J3 GND M6 (south)  |
+----------------------+--------------------+--------------------+
                              y=93
```

Bobbins are **not** paired on the east edge and **not** on the M1000 west side.

## Copper strategy (follow-up)

This floorplan commit **strips** carrier tracks/vias/filled pours. Zone **outlines** are in place for the new geometry; they still need a pcbnew ZONE_FILLER pass after merge.

1. **VBAT** — F.Cu islands: north entry `(58,1)–(103,24)` (J2+F1/C), HP tabs `(74,32)–(103,64)`, ADIO `(48,66)–(82,81)`; B.Cu north entry island
2. **GND** — B.Cu near-full board (module keepout punches M1000) + F.Cu island around J3 `(82,72)–(103,92)`
3. **SENSOR_GND** — stays off chassis; **no SENSOR pour**
4. **EN / IS / PWR_OUT / ADIO / CAN** — open; re-route on this nest. Do **not** replay 150×130 `cut_crossings_sexp.py` / longhaul scripts

FreeRouting / dense meshes still skipped (mega-mcu144 padstacks).

## Unconnected / routing status

| Metric | This floorplan | Previous fill (invalidated) |
|--------|----------------|-----------------------------|
| DRC shorts / crossings | **not claimed** (copper stripped) | 199 shorts / 178 crossings (paired-M6 nest) |
| Unconnected | **Up** — all carrier nets open | 100 |
| EN/IS unconnected | **Open** | 0 |
| Tracks / vias | **0 / 0** | 385 / 158 |
| Footprints / outline | **54** / 104×93 | 53 / 104×93 |

## DRC notes

`kicad-cli pcb drc` is **not run / not claimed** on this placement-only board.

| Issue | Notes |
|-------|-------|
| J1 courtyard | Closed `fp_rect`. **Width 39 mm** (TE). **Length 29 mm** (catalog vertical D). Product-page **36.5 mm** shroud is Cmts.User only. |
| M1000 padstack | Module artifact (`padstack_invalid`); ignore for carrier DRC. Keepout outline matches silk `(0.1,0)…(42.2,−40)`. |
| M6 pads | 16 mm Cu on opposite edges — old “GND pad vs VBAT spine” short from the 25 mm pair is gone by construction |

## Schematic sheets

| Sheet | File | Contents |
|-------|------|----------|
| Root | `pdmrazora.kicad_sch` | SuperSeal 26 **vertical** + **split M6 bobbins** (J2 VBAT+ / J3 GND) + power entry + IGN_SW divider |
| MM144 | `MM144.kicad_sch` | mega-mcu144 0.7 + PINMAP globals |
| HP | `HP.kicad_sch` | HP1–4 BTS50010-1TAD + IS sense |
| ADIO | `ADIO.kicad_sch` | ADIO1–8 BTS7004-1EPP + IS/PU |

## Fab-blocker checklist

| # | Blocker | Status |
|---|---------|--------|
| 1 | Real AMP SuperSeal 26 footprint | **Done** (vertical 6473418-1; same pin numbers as CONNECTOR.md) |
| 2 | Final PROFET PNs + sense networks | **Done** |
| 3 | Power entry + IGN_SW divider | **Done** |
| 4 | Place HP/ADIO footprints on PCB | **Done** (re-nested between split M6 bobbins on 104×93) |
| 5 | create-board / copper finish | **Open** — tracks wiped; zone outlines unfilled; re-route + fill is follow-up |

## Remaining polish (human)

- **Follow-up:** re-route EN/IS/PWR_OUT/ADIO/CAN/SENSOR and fill the new VBAT/GND zone outlines. Do **not** claim DRC-clean until that lands
- Do **not** replay `scripts/cut_crossings_sexp.py` or other 150×130 longhaul scripts
- Confirm SENSOR_GND stays off chassis GND (no SENSOR pour)
- TE **6473418-1**: courtyard is 39×29 mm (fits the EMI wall). Product-page 39×36.5 mm shroud **does not fit** without nudging HP/M1000 — verify against the TE drawing before fab
- M6 hardware: two independent copper bobbins + M6×8 button-head, 4 N·m, 25 mm² cable (CONNECTOR.md) — north VBAT / south GND
- ADIO/HP packing between the bobbins is still tight — nudge before fab
- F1 remains the ATO blade placeholder (now on the north VBAT path)
- Ideal-diode / reverse-protect controller
- Discrete FET for ADIO PU hard-enable (`OUT_IO9–13`, `IO1–3`)
- ADIO V-sense divider values (`IN_TPS` / `IN_PPS` / …)

## Scripts

- `scripts/split_bobbins_floorplan.py` — **this commit**: split J2/J3 single M6 footprints, opposite-edge placement, wipe paired-spine copper, rewrite zone outlines
- `scripts/layout_positions.txt` — current footprint XY
- `scripts/floorplan_fcu_overview.png` — F.Cu pad/outline overview of the new nest
- `scripts/fill_zones_104x93.py` — previous fill (paired-M6 nest; do not re-run blindly)
- `scripts/route_critical_nets.py` — previous 104×93 sexp router (paired-M6 nest; do not re-run blindly)
- `scripts/layout_redesign.py` — original 104×93 shrink + dual-bobbin J2
- Older copper scripts (`cut_crossings_sexp.py`, `route_is_longhaul_thin_en.py`, …) target the **old** 150×130 nest and must not be re-applied blindly
