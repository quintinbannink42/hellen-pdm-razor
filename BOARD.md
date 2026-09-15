# Board status — pdmrazora (rev a)

## Stubbed in this commit

| Item | Status |
|------|--------|
| Hellen-example skeleton (`.gitmodules`, workflows, `revision.txt`, `.gitignore`) | Done |
| Authoritative connector / pin map / spec docs | Done (`CONNECTOR.md`, `PINMAP.md`, …) |
| KiCad frame `pdmrazora.*` | Done — schematic nets match Razor pinout |
| 26-pin SuperSeal symbol + net labels | Done (generic `Conn_02x13_Top_Bottom` placeholder footprint) |
| M6 VBAT+ / GND stubs | Done (schematic + PCB pad placeholders) |
| USB-C | Note on schematic only (module USB when mega-mcu144 is merged) |
| mega-mcu144 ≥ 0.7 module footprint / gerber merge | **Not yet** — submodule present; place module per wiki |
| HP PROFET ×4 power stage | **TODO** block on schematic |
| ADIO ×8 front-end | **TODO** block on schematic |
| Fab outputs under `boards/pdmrazora/` | After create-board Action succeeds |

## Hellen module placement (next steps)

Follow the [hellen-one wiki](https://github.com/andreika-git/hellen-one/wiki) “frame” workflow:

1. Init submodules: `git submodule update --init --recursive`
2. Import mega-mcu144 **0.7+** symbol/footprint from `hellen-one/modules/mega-mcu144/` (versioned folder).
3. Place the module footprint on the frame PCB. Rotation must be a multiple of **90°** (gerber merge constraint).
4. Keep `aux_axis_origin` at the board bottom-left; all coordinates ≥ 0.
5. Connect SuperSeal / M6 nets to module edge pads per [PINMAP.md](PINMAP.md):
   - CANH / CANL → module CAN
   - IGN_SW → divider → `IN_VIGN`
   - SENSOR_5V → `V5A_SWITCHABLE` via `OUT_PWR_EN`
   - SENSOR_GND → AGND island (do **not** bond to chassis)
   - HP1–4 EN/PWM/IS and ADIO1–8 as in PINMAP
6. Design HP PROFET and ADIO stages (still TODO).
7. Push to **`main`** so `.github/workflows/create-board.yaml` can merge module gerbers.

Useful references:

- https://github.com/andreika-git/hellen-one/wiki
- https://wiki.rusefi.com/Hellen-One-Platform
- Example frames: [rusefi/uaefi](https://github.com/rusefi/uaefi), [rusefi/hellen-example](https://github.com/rusefi/hellen-example)

## PCB notes (rev a)

- Outline placeholder ~100×80 mm; enlarge as stages are added.
- Connector footprint is a **placeholder** (not a production SuperSeal FP yet) — replace with a verified AMP SuperSeal 26 footprint before fab.
- Module outline on Eco1.User marks intended mega-mcu144 keepout until the real footprint is placed.
