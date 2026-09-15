# Board status — pdmrazora (rev a)

Open with **KiCad 8.x** (Hellen mega-mcu144 0.7 is K8). KiCad 9 also works. KiCad 6/7 will not open this module.

## This commit — nest + pour scaffolding

| Item | Status |
|------|--------|
| Nested floorplan | **Done** — 53 footprints on **150 × 130 mm** |
| Edge.Cuts | **Done** — rectangle 0,0 → 150,130; `aux_axis_origin 0 130`; no negative coords |
| M1000 mega-mcu144 0.7 | **(8, 52) rot 0°**; Value `Module:mega-mcu144/0.7`; pour keepout under module |
| J1 SuperSeal 26 | **Bottom edge** `(75, 109.5)` for harness access |
| J2 M6 stubs | Near power entry `(14, 95)`; pad geometry repaired to 2.54 mm pitch |
| HP U1–U4 | Grouped lower-right with thermal pour stubs toward connector |
| ADIO U11–U18 | Grouped mid-board; sense/PU under each device |
| Passives | F1/TVS/bulk/IGN divider + HP/ADIO RIS/C/PU placed next to drivers |
| Copper routing | **Partial** — pour outlines for VBAT / GND / PWR_OUTn / ADIOn (fill in Pcbnew); length routing of control/sense still ratsnest |
| HELLCORE | **Not touched** |

See [HARDWARE_BOM.md](HARDWARE_BOM.md) for kILIS / AmpsPerVolt TODOs.

## Floorplan (mm)

| Block | Placement |
|-------|-----------|
| M1000 | Left `(8,52)` — clear Hellen merge keepout |
| ADIO ×8 | Mid-top 2×4 @ y≈16/42, x=70…124 |
| HP ×4 | Lower-right TO-263 @ `(92/115, 68/90)` rot 270° |
| J1 | Bottom edge center |
| Power entry | Left-bottom J2 → F1 → C1/C2/D1; IGN R1/R2 above |

## Unconnected / routing status

| Metric | Before nest | After this commit |
|--------|-------------|-------------------|
| Multi-pad open nets (approx) | **42** | **~44** (ratsnest; pours unfilled) |
| Tracks | 0 | 0 (pours carry power after **Edit → Fill all zones**) |
| Footprints on PCB | 15 | **53** |
| Board outline | missing / 180×140 claimed | **150 × 130** Edge.Cuts |

### Ratsnest still open (fill pours first, then route)

Priority order for interactive routing:

1. **VBAT / GND** — fill F.Cu VBAT + B.Cu GND pours; stitch any pads outside pours
2. **PWR_OUT1..4** — pour stubs from HP toward J1 dual pins; fat traces / pour merge
3. **ADIO1..8** — pour stubs from each BTS7004 toward SuperSeal ADIO pins
4. **EN/PWM** `OUT_PWM1..8`, `OUT_IO5..8` → M1000 east pads
5. **ISENSE** `IN_AUX*`, `IN_MAP*`, `IN_O2S*`, `IN_RES*` → M1000
6. **CANH/CANL**, **SENSOR_5V/GND**, **IGN_SW → R1/R2 → IN_VIGN**

Full star autoroute was attempted (pcbnew manhattan / FreeRouting DSN); FreeRouting failed on mega-mcu144 padstacks; aggressive track meshes introduced many shorts — **not shipped**. Pour + interactive finish is the safe path.

## DRC notes (acceptable / known)

| Issue | Notes |
|-------|-------|
| J2 VBAT↔GND clearance | Pin-header stub pads at 2.54 mm; replace with real M6 footprint later |
| J1 malformed courtyard | Pre-existing SuperSeal FP courtyard not closed |
| M1000 padstack “no outer layers” | Module artifact; ignore for carrier DRC |
| Unconnected after open | Expected until pours filled + ratsnest routed |
| solder_mask_bridge (few) | J2 / module — non-blocking for this stub stage |

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
| 3 | Power entry + IGN_SW divider | **Done** (PCB parts placed) |
| 4 | Place HP/ADIO footprints on PCB | **Done** — nested |
| 5 | create-board / copper finish | **Partial** — pours outlined; fill + route ratsnest next |

## Remaining polish

- Fill zones in Pcbnew, then route remaining ratsnest (control/sense + pour gaps)
- Ideal-diode / reverse-protect controller
- Discrete FET for ADIO PU hard-enable
- Replace J2 pin-header with true M6 mechanical
- ADIO V-sense divider values
