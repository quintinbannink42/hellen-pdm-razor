# Board status — pdmrazora (rev a)

Open with **KiCad 8.x** (Hellen mega-mcu144 0.7 is K8). KiCad 9 also works. KiCad 6/7 will not open this module.

## This commit — cut crossings after the 9-IS south-ring (EN/IS stay 0)

| Item | Status |
|------|--------|
| DRC shorts | **1** (J2 VBAT↔GND only — unchanged) |
| DRC crossings | **106 → 89** (KiCad 9.0.9; PR #1 flake was 106↔107) |
| Unconnected (DRC) | **116** (unchanged) |
| EN/IS unconnected | **0** (all 12 EN + all 12 IS long-haul still closed) |
| Tracks / vias | **346 tracks + 142 vias** (was 327 / 106) |
| AUX1 feeder | B column **70 → 87.4** (J1 pin-gap east of 2 mm pads @66–84; stops AUX1×J1 soldermask graze from promoting to a short) |
| EN SENSOR hop | Pad-approach H that spanned SENSOR_5V x=52 moved to F.Cu (via-in-pad @x=50 + east via) |
| ADIO U-turns | ADIO5–8 long H on F.Cu to x≈129–132; ADIO4 east stub F-hop across MAP1; AUX2/AUX4 F-jog through remainder |
| IS long-haul | **Still closed** — south-ring topology kept; no EN/IS rebuild |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |
| Branding | **Not started** — PowerCore docs rename blocked until copper improves |

See [HARDWARE_BOM.md](HARDWARE_BOM.md) for kILIS / AmpsPerVolt TODOs.

## Floorplan (mm)

| Block | Placement |
|-------|-----------|
| M1000 | Left `(8,52)` — clear Hellen merge keepout |
| ADIO ×8 | Mid-top 2×4 @ y≈16/42, x=70…124 |
| HP ×4 | Lower-right TO-263 @ `(92/115, 68/90)` rot 270° |
| J1 | Bottom edge center |
| Power entry | Left-bottom J2 → F1 → C1/C2/D1; IGN divider above |

## Copper strategy

Prefer **zone fills for power/GND** + **selective Manhattan tracks** (not a dense star mesh):

1. **VBAT** — F.Cu pours: power-entry island, HP island, bottom link, ADIO supply strips
2. **GND** — B.Cu near-full board (keepout punches module) + F.Cu entry/HP islands + stitch vias
3. **PWR_OUT1..4** — local OUT bar north of pin row; B.Cu corridors; short F stubs at J1
4. **ADIO1..8** — local OUT islands; B.Cu corridors left (x≈55–60) / right (x≈140–145); via_y≥53.5 clear of IS
5. **SENSOR_5V** — top B bus (y=5) + right riser (x=147) + taps to R201–R208 pad1
6. **Control/sense** — EN exclusive B.Cu lanes complete; all 12 IS long-haul on gated B south-ring; SELECTED EN/ADIO H F-hops to cut crossings

FreeRouting / aggressive track meshes were skipped (mega-mcu144 padstacks + prior short storms).

## Unconnected / routing status

| Metric | PR #1 (9-IS south-ring) | This commit |
|--------|-------------------------|-------------|
| DRC shorts | **1** | **1** |
| DRC crossings | **106** (flake 107) | **89** |
| DRC unconnected | **116** | **116** |
| EN/IS unconnected | **0** | **0** |
| Tracks | 327 | **346** |
| Vias | 106 | **142** |
| Footprints | 53 | 53 |
| Board outline | 150 × 130 | 150 × 130 |

### Remaining ratsnest / multi-pad gaps

- **GND** pour islands — F.Cu islands outside stitch coverage; B.Cu pour present
- A few **VBAT** zone-to-zone / pad edges
- **PWR_OUT / ADIO / CAN** — mostly restored; a few stub gaps remain after conflict deletes
- **IS long-haul** — closed (AUX2/3, MAP2/3, O2S/O2S2, RES1–3 + prior AUX1/AUX4/MAP1)

## DRC notes

`kicad-cli pcb drc` after this commit (KiCad 9.0.9, three consecutive runs):

| Issue | Notes |
|-------|-------|
| shorting_items (**1**) | Only J2 pin-header VBAT↔GND at 2.54 mm — replace with real M6 later |
| tracks_crossing (**89**) | Down from 106. AUX1 feeder off J1 → EN F-hop over SENSOR x=52 → ADIO5–8/ADIO4 F U-turns → AUX2/AUX4 remainder jogs. Remaining: IS–IS 36, EN–EN 17, EN–IS 10, EN–SENSOR 5 (y=5 east risers). Nested all-12 B south-ring and same-Y via packing still short. |
| solder_mask_bridge | J2 stub / module / via density — non-blocking for this stage |
| J1 malformed courtyard | Pre-existing SuperSeal FP courtyard not closed |
| M1000 padstack | Module artifact; ignore for carrier DRC |

## Schematic sheets

| Sheet | File | Contents |
|-------|------|----------|
| Root | `pdmrazora.kicad_sch` | SuperSeal 26 + M6 + power entry + IGN_SW divider |
| MM144 | `MM144.kicad_sch` | mega-mcu144 0.7 + PINMAP globals |
| HP | `HP.kicad_sch` | HP1–4 BTS50010-1TAD + IS sense |
| ADIO | `ADIO.kicad_sch` | ADIO1–8 BTS7004-1EPP + IS/PU |

## Fab-blocker checklist

| # | Blocker | Status |
|---|---------|--------|
| 1 | Real AMP SuperSeal 26 footprint | **Done** |
| 2 | Final PROFET PNs + sense networks | **Done** |
| 3 | Power entry + IGN_SW divider | **Done** |
| 4 | Place HP/ADIO footprints on PCB | **Done** |
| 5 | create-board / copper finish | **Partial** — EN + all 12 IS long-haul closed; crossings 106→89; GND islands remain |

## Remaining polish

- Cut remaining IS–IS / EN–SENSOR (y=5 east risers) without new shorts (via packing / F1 / SENSOR F @138 still block full nest)
- Finish remaining PWR/ADIO/CAN stub gaps without recreating shorts
- Ideal-diode / reverse-protect controller
- Discrete FET for ADIO PU hard-enable
- Replace J2 pin-header with true M6 mechanical
- ADIO V-sense divider values

## Scripts

- `scripts/surgical_drc_fix.py` — delete shorting/crossing copper by DRC UUID; SENSOR taps + GND stitches
- `scripts/drc_cleanup_route.py` — full selective re-route attempt (reference; denser rebuild)
- `scripts/restore_connectivity.py` — family restore helpers
- `scripts/route_en_is_lanes.py` — gated EN/IS exclusive-lane re-route (prior commit)
- `scripts/route_is_longhaul_thin_en.py` — remaining 9 IS B south-ring + EN B thin
- `scripts/yank_adio_pwr_south.py` — ADIO U-turn Y-shift + orphan PWR south-delete
- `scripts/cut_crossings_sexp.py` — gated S-expr AUX1 J1-gap + EN/ADIO F-hops (this commit)
- `scripts/is_f_west_corridor.py` — F westbound attempt (shorts / via packing; not applied)
- `scripts/copper_status.txt` — before/after metrics
- `scripts/fill_and_route.py` — original pour fill + selective copper (prior commit)
