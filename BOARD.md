# Board status — PowerCore (`pdmrazora` rev a)

Open with **KiCad 8.x** (Hellen mega-mcu144 0.7 is K8). KiCad 9 also works. KiCad 6/7 will not open this module.

## This commit — critical-net re-route on the 104×93 floorplan

Mechanical placement from the previous commit is **unchanged** (53 footprints, 104×93 mm, M6 bobbins, vertical SuperSeal EMI wall, M1000 keepout). Old 150×130 copper scripts were **not** reapplied.

| Item | Status |
|------|--------|
| Tracks / vias | **386 / 165** (was 0 / 0 after the move) |
| EN/IS (HP1–4 + ADIO1–8) | **Connected** (exclusive EN B.Cu south-of-J1 highways + MCU-gap columns; IS local F + B.Cu long-haul to S pads) |
| PWR_OUT1–4 / ADIO1–8 | **Connected** to SuperSeal (F local, B into pins; ADIO F-hops the EN band) |
| VBAT | F.Cu entry spine M6+→F1→C/D + B.Cu east alley to HP tabs; module N27 via **north corridor only** |
| GND | B.Cu full-board pour + local F stubs/vias; **no SENSOR_GND bond**; M6− F island only (no overlapping VBAT F pour) |
| CAN / SENSOR_5V / SENSOR_GND / IGN_SW / IN_VIGN | **Connected** (north/east skirt; SENSOR_5V does not traverse the EN field) |
| USB | On-module only (USB-C is on mega-mcu144) — not a carrier leftover |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |
| Footprints | **53** |

`kicad-cli pcb drc` is **still unavailable** here. Geometric H–V scan (not KiCad DRC) still sees same-layer crossings in the packed east/south field (HP pin-row vs PWR_OUT/IS, ADIO vs sense). **Fill zones in pcbnew** then run DRC; expect shorts ≤ mechanical-redesign baseline (J2 header short is gone) and crossings that need human polish, not a clean DRC.

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
| M6 bobbins | East-north J2 `(91, 14)` — pad1 VBAT+ @ y=14, pad2 GND @ y=39 |
| Power entry | F1 / D1 / C1 / C2 / IGN divider just west of the bobbins |
| HP ×4 | East TO-263 2×2 @ `(80/96, 58/71)` rot 270° |
| ADIO ×8 | South-east 2×4 @ y≈82/89, x=70…97 |

```
x=0                    x=45                 x=68                 x=104
+----------------------+--------------------+--------------------+
| mega-mcu144 (M1000)  | vertical SuperSeal | M6+ / M6− bobbins  |
| quiet / logic        | 26  EMI SPLIT      | HP PROFET + ADIO   |
+----------------------+--------------------+--------------------+
                              y=93
```

## Copper strategy (104×93 EMI split)

Prefer **zone fills for power/GND**; signal long-haul uses exclusive lanes around the SuperSeal (not through MCU west copper except EN/IS/CAN/SENSOR at the connector spine / north corridor).

1. **VBAT** — F.Cu pour islands (entry y≤30, HP tabs, ADIO south) + tracks M6+→F1→bulk; B.Cu east alley x=88 to HP tabs (stops north of EN highways)
2. **GND** — B.Cu near-full board (module keepout punches M1000) + F.Cu M6− island only; stitch vias at every carrier GND pad
3. **EN** — exclusive B.Cu south-of-J1 Y + MCU–J1 gap columns (6 B + 6 F); land on M1000 E pads
4. **IS** — local F.Cu U–R–C; B.Cu unique highways y=73.15–78.1 to M1000 S pads
5. **PWR_OUT / ADIO** — stay east of the pin field except J1 landings; F-hop the EN B band

FreeRouting / dense meshes still skipped (mega-mcu144 padstacks).

## Unconnected / routing status

| Metric | 150×130 nest (`main`) | Floorplan-only | This copper |
|--------|----------------------|----------------|-------------|
| DRC shorts | **1** (J2 header) | J2 short **gone**; DRC not run | **Not run** (`kicad-cli` missing) |
| DRC crossings | **89** | ~0 (no tracks) | **Human DRC required** — geometric H–V scan is not KiCad DRC; east/south packing is tight |
| DRC unconnected | **116** | Up (copper stripped) | EN/IS/ADIO/PWR/CAN/SENSOR **track-connected**; GND completes on B pour fill |
| EN/IS unconnected | **0** | Open | **0** (pad-island check) |
| Tracks | 346 | **0** | **386** |
| Vias | 142 | **0** (M6 stitches in footprint) | **165** + M6 footprint stitches |
| Footprints | 53 | **53** | **53** |
| Board outline | 150 × 130 | **104 × 93** | **104 × 93** |

## DRC notes

`kicad-cli pcb drc` was **not available** in the agent VM (no KiCad package). Mechanical intent:

| Issue | Notes |
|-------|-------|
| shorting_items | Previous unique short was J2 pin-header VBAT↔GND @ 2.54 mm. M6 pads are 25 mm apart with 16 mm Cu — will not short each other. Remaining shorts = zone-to-pad after a fill, for a human to check. |
| tracks_crossing | Geometric H–V scan ≈480 in the packed east/south field (not KiCad DRC). Human polish after zone fill. |
| solder_mask_bridge | M6 16 mm pads / module padstack — inspect after pour. |
| J1 courtyard | Closed `fp_rect` (previous RA courtyard was open). TE body is 39 × 36.5 mm; courtyard is pin-field + mounting (~37 × 23.5 mm). **Verify against 6473418-1 drawing** — shroud may need a larger keepout. |
| M1000 padstack | Module artifact; ignore for carrier DRC. Keepout now matches silk `(0.1,0)…(42.2,−40)`. |

## Schematic sheets

| Sheet | File | Contents |
|-------|------|----------|
| Root | `pdmrazora.kicad_sch` | SuperSeal 26 **vertical** + **M6 bobbins** + power entry + IGN_SW divider |
| MM144 | `MM144.kicad_sch` | mega-mcu144 0.7 + PINMAP globals |
| HP | `HP.kicad_sch` | HP1–4 BTS50010-1TAD + IS sense |
| ADIO | `ADIO.kicad_sch` | ADIO1–8 BTS7004-1EPP + IS/PU |

## Fab-blocker checklist

| # | Blocker | Status |
|---|---------|--------|
| 1 | Real AMP SuperSeal 26 footprint | **Done** (vertical 6473418-1; same pin numbers as CONNECTOR.md) |
| 2 | Final PROFET PNs + sense networks | **Done** |
| 3 | Power entry + IGN_SW divider | **Done** |
| 4 | Place HP/ADIO footprints on PCB | **Done** (re-nested on 104×93) |
| 5 | create-board / copper finish | **Partial** — critical nets tracked on 104×93; fill + human DRC still required |

## Remaining polish (human)

- **Fill VBAT/GND zones in pcbnew** and run `kicad-cli pcb drc` — this VM has no KiCad package
- Clear remaining H–V crossings in the HP/ADIO south field (PWR_OUT vs IS locals, ADIO vs sense). Do **not** replay `scripts/cut_crossings_sexp.py` (150×130)
- Confirm no zone-to-zone shorts at the SuperSeal wall after fill; SENSOR_GND must stay off chassis GND
- Confirm TE **6473418-1** 3D/courtyard vs the 39×36.5 mm datasheet body
- M6 hardware: copper bobbin + M6×8 button-head, 4 N·m, 25 mm² cable (CONNECTOR.md)
- ADIO/HP courtyard packing on the east half is tight — nudge before fab
- Ideal-diode / reverse-protect controller
- Discrete FET for ADIO PU hard-enable (`OUT_IO9–13`, `IO1–3`)
- ADIO V-sense divider values (`IN_TPS` / `IN_PPS` / …)

## Scripts

- `scripts/route_critical_nets.py` — **this commit**: sexp router for VBAT/GND/EN/IS/PWR/ADIO/CAN/SENSOR on 104×93
- `scripts/unconnected_leftover.txt` — pad-island leftover list
- `scripts/layout_redesign.py` — 104×93 Edge.Cuts, M6 bobbins, vertical SuperSeal EMI wall, M1000 keepout/value
- `scripts/layout_positions.txt` — current footprint XY
- Older copper scripts (`cut_crossings_sexp.py`, `route_is_longhaul_thin_en.py`, …) target the **old** 150×130 nest and must not be re-applied blindly
