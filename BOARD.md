# Board status — pdmrazora (rev a)

Open with **KiCad 8.x** (Hellen mega-mcu144 0.7 is K8). KiCad 9 also works. KiCad 6/7 will not open this module.

## This commit — interactive DRC cleanup leftovers

| Item | Status |
|------|--------|
| DRC shorts | **94 → 1** (only known J2 VBAT↔GND 2.54 mm header remains) |
| DRC crossings | **110 → 33** |
| Unconnected (DRC) | **97 → 145** (tradeoff: conflict copper deleted; ~71 are GND pour islands) |
| Tracks / vias | **276 tracks + 117 vias** (was 328 / 82) |
| SENSOR_5V → R201–R208 | **Done** — PU taps + top bus + right-edge riser to J1 |
| GND stitch | **Done** — vias west of sense-R GND pads + island stitches |
| KiCad format | **20240108 / generator_version 8.0** |
| HELLCORE | **Not touched** |

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
6. **Control/sense** — EN/IS partially cleaned by deleting shorting segments; some ratsnest remains for interactive finish

FreeRouting / aggressive track meshes were skipped (mega-mcu144 padstacks + prior short storms).

## Unconnected / routing status

| Metric | Copper commit (a8d03e9) | This commit |
|--------|-------------------------|-------------|
| DRC shorts | **94** | **1** |
| DRC crossings | **110** | **33** |
| DRC unconnected | **97** | **145** |
| Tracks | 328 | **276** |
| Vias | 82 | **117** |
| Footprints | 53 | 53 |
| Board outline | 150 × 130 | 150 × 130 |

### Remaining ratsnest / multi-pad gaps

- **GND** pour islands (~71 DRC items) — F.Cu islands outside stitch coverage; B.Cu pour present
- **EN/IS** long-haul fragments after shorting-segment deletes — need interactive re-route with exclusive lanes
- A few **VBAT** zone-to-zone / pad edges
- **PWR_OUT / ADIO / CAN** — mostly restored; a few stub gaps remain after conflict deletes

## DRC notes

`kicad-cli pcb drc` after this commit:

| Issue | Notes |
|-------|-------|
| shorting_items (**1**) | Only J2 pin-header VBAT↔GND at 2.54 mm — replace with real M6 later |
| tracks_crossing (**33**) | Down from ~110; remaining are non-short crossings / density |
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
| 5 | create-board / copper finish | **Partial** — shorts cleared; SENSOR_5V PUs done; EN/IS + GND islands still need interactive finish |

## Remaining polish

- Interactive re-route of EN/IS fragments (exclusive B.Cu lanes west of ADIO corridors)
- Finish remaining PWR/ADIO/CAN stub gaps without recreating shorts
- Ideal-diode / reverse-protect controller
- Discrete FET for ADIO PU hard-enable
- Replace J2 pin-header with true M6 mechanical
- ADIO V-sense divider values

## Scripts

- `scripts/surgical_drc_fix.py` — delete shorting/crossing copper by DRC UUID; SENSOR taps + GND stitches
- `scripts/drc_cleanup_route.py` — full selective re-route attempt (reference; denser rebuild)
- `scripts/restore_connectivity.py` — family restore helpers
- `scripts/copper_status.txt` — before/after metrics
- `scripts/fill_and_route.py` — original pour fill + selective copper (prior commit)
