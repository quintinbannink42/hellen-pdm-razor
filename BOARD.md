# Board status — PowerCore (`pdmrazora` rev a)

Open with **KiCad 8.x** (Hellen mega-mcu144 0.7 is K8). KiCad 9 also works. KiCad 6/7 will not open this module.

## This commit — zone fill + M6/HP stitch (104×93 EMI split)

Critical-net copper from the previous commit is **unchanged in plan** (no footprint moves, no 150×130 scripts, F1 ATO left). Pours are now **filled** in pcbnew 8.0.9. No SENSOR pour was added (none existed; SENSOR_GND stays off chassis).

[F.Cu / B.Cu zone-fill overview](https://cursor.com/agents/bc-56c5d6eb-2ed9-5dd9-a950-2d9575ea6b39/artifacts?path=%2Fopt%2Fcursor%2Fartifacts%2Fcopper_fill_fb_overview.png)

| Item | Status |
|------|--------|
| Tracks / vias | **385 / 158** (was 385 / 136) — +10 M6 bobbin vias, +12 HP-tab thermal vias |
| Zones filled | **7** copper pours (GND B full-board, GND F M6−, VBAT F entry/HP/ADIO, VBAT B entry + U1/U2 tab island). Keepout punches M1000. |
| Pad connect | **solid** on VBAT/GND (not thermal spokes) |
| HP VBAT F | Expanded to `(73,48)–(103,77.2)` so TO-263 tabs sit in the pour. U3/U4 tabs still avoid EN B vias (alley at y=64.4). |
| EN/IS / outline / J1 / F1 | **Unchanged** |
| SENSOR pour | **None** (not present; not added) |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |
| Footprints | **53** |

`kicad-cli pcb drc` **8.0.9** (this VM). See [scripts/drc_zonefill.json](scripts/drc_zonefill.json) and [scripts/unconnected_leftover.txt](scripts/unconnected_leftover.txt).

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

1. **VBAT** — F.Cu pour islands (entry y≤30, HP tabs, ADIO south) + tracks M6+→F1→bulk; B.Cu entry island + U1/U2 tab island (stops north of EN y≈66.9) plus alley x=88
2. **GND** — B.Cu near-full board (module keepout punches M1000) + F.Cu M6− island only; stitch vias at every carrier GND pad that fits
3. **EN** — exclusive B.Cu south-of-J1 Y + MCU–J1 gap columns (6 B + 6 F); land on M1000 E pads
4. **IS** — local F.Cu U–R–C; B.Cu unique highways y=73.15–78.1 to M1000 S pads
5. **PWR_OUT / ADIO** — stay east of the pin field except J1 landings; F-hop the EN B band

FreeRouting / dense meshes still skipped (mega-mcu144 padstacks).

## Unconnected / routing status

| Metric | Floorplan-only | Critical-net copper | This fill |
|--------|----------------|---------------------|-----------|
| DRC shorts | J2 short **gone** | not run | **199** (delta **0** vs unfilled copper; packed east + M6 16 mm vs VBAT spine) |
| DRC crossings | ~0 (no tracks) | geometric H–V only | **178** (kicad-cli); geom H–V **585** |
| DRC unconnected | Up (copper stripped) | GND open pre-pour | **100** (was 131 unfilled). VBAT **9→2** |
| EN/IS unconnected | Open | **0** | **0** (not re-opened) |
| Tracks / vias | 0 / 0 | **385 / 136** | **385 / 158** |
| Footprints / outline | 53 / 104×93 | 53 / 104×93 | 53 / 104×93 |

## DRC notes

`kicad-cli pcb drc` **8.0.9** on the filled board (`scripts/drc_zonefill.json`):

| Issue | Notes |
|-------|-------|
| shorting_items | **199**, unchanged vs unfilled copper. Dominant: M6 16 mm GND pad vs VBAT F/B spine; ADIO/IS via-on-track in the east/south field. Not new from this fill. |
| tracks_crossing | **178** kicad-cli / **585** geometric H–V. Human polish in HP/ADIO south. Do **not** replay `cut_crossings_sexp.py`. |
| unconnected_items | **100** (131 unfilled). VBAT 9→2. Remaining GND: M1000 keepout + 13 SMD pads whose via sites collide with EN/ADIO. |
| solder_mask_bridge | **199**. M6 16 mm pads / module padstack. |
| J1 courtyard | Closed `fp_rect`. **Width 39 mm** (TE). **Length 29 mm** (catalog vertical D). Product-page **36.5 mm** shroud is Cmts.User only. |
| M1000 padstack | Module artifact (`padstack_invalid` 22); ignore for carrier DRC. Keepout outline matches silk `(0.1,0)…(42.2,−40)`. |

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
| 5 | create-board / copper finish | **Partial** — pours filled + kicad-cli DRC; east/south crossings + 13 GND vias still human |

## Remaining polish (human)

- Clear remaining H–V crossings in the HP/ADIO south field (PWR_OUT vs IS locals, ADIO vs sense). Do **not** replay `scripts/cut_crossings_sexp.py` (150×130)
- Place GND vias on the 13 leftover SMD pads (ADIO U11–18 / HP U2–U4 / C101 / C107 / D1) without landing on EN/IS columns
- Confirm SENSOR_GND stays off chassis GND (no SENSOR pour was added)
- TE **6473418-1**: courtyard is 39×29 mm (fits the EMI wall). Product-page 39×36.5 mm shroud **does not fit** without nudging HP/M1000 — verify against the TE drawing before fab
- M6 hardware: copper bobbin + M6×8 button-head, 4 N·m, 25 mm² cable (CONNECTOR.md)
- ADIO/HP courtyard packing on the east half is tight — nudge before fab
- F1 remains the ATO blade placeholder
- Ideal-diode / reverse-protect controller
- Discrete FET for ADIO PU hard-enable (`OUT_IO9–13`, `IO1–3`)
- ADIO V-sense divider values (`IN_TPS` / `IN_PPS` / …)

## Scripts

- `scripts/fill_zones_104x93.py` — **this commit**: pcbnew 8 ZONE_FILLER, solid VBAT/GND pours, M6/HP via stitch, kicad-cli DRC
- `scripts/drc_zonefill.json` — compact DRC counts from kicad-cli 8.0.9
- `scripts/unconnected_leftover.txt` — pad-island leftover list
- `scripts/copper_fill_overview.png` — F/B pour overview
- `scripts/route_critical_nets.py` — previous commit: sexp router for VBAT/GND/EN/IS/PWR/ADIO/CAN/SENSOR on 104×93
- `scripts/layout_redesign.py` — 104×93 Edge.Cuts, M6 bobbins, vertical SuperSeal EMI wall, M1000 keepout/value
- `scripts/layout_positions.txt` — current footprint XY
- Older copper scripts (`cut_crossings_sexp.py`, `route_is_longhaul_thin_en.py`, …) target the **old** 150×130 nest and must not be re-applied blindly
