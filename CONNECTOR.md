# PowerCore — Link Razor-compatible connector pinout (match exactly)

PowerCore uses the same AMP SuperSeal 1.0 26-pin (Link “Connector C”) and M6 main-power arrangement as the Link ECU **Razor PDM**, so existing Razor looms plug in.

Sources: Link PDM Quick Start Guide; Link KB inputs/outputs.

## Main power (not on the 26-pin)

| Terminal | Function | Notes |
|----------|----------|-------|
| M6 + | Battery positive | 25 mm² / 4 AWG recommended; torque 4 Nm |
| M6 − | Battery negative / power ground | Same |

## 26-pin AMP SuperSeal 1.0 (Link “Connector C”)

**Board header PN:** TE Connectivity **6437288-6** (SuperSeal 1.0, 26-pos, **vertical**, Au, keying 1). Footprint `pdmrazora:TE_6437288-6_SuperSeal26_V` (same 4-row / 3.0 mm pin pattern as RA 9-6437287-8 / drawing 9-1437287-8; vertical header has **no mounting holes**). Mating plug and **pin numbers are unchanged** vs Link Razor CONNECTOR C.

Viewed looking into wire side of loom connector (or into PDM header).

| Pin | Signal | Notes |
|----:|--------|-------|
| 1 | PWR OUT 2 | High-power; parallel with pin 8; 16 AWG / 1.25 mm² |
| 2 | N/C | |
| 3 | CAN H | |
| 4 | IGN SW | Switched +12 V ignition sense / key-on |
| 5 | SENSOR 5V | ≤50 mA; not tied internally to pin 11 |
| 6 | SENSOR GND | **Do not** bond to chassis |
| 7 | PWR OUT 3 | Parallel with pin 13 |
| 8 | PWR OUT 2 | Parallel with pin 1 |
| 9 | N/C | |
| 10 | CAN L | |
| 11 | SENSOR 5V | Second 5 V pin; spread loads |
| 12 | SENSOR GND | **Do not** bond to chassis |
| 13 | PWR OUT 3 | Parallel with pin 7 |
| 14 | PWR OUT 1 | Parallel with pin 20 |
| 15 | A/D I/O 2 | ADIO2 |
| 16 | A/D I/O 4 | ADIO4 |
| 17 | A/D I/O 6 | ADIO6 |
| 18 | A/D I/O 8 | ADIO8 |
| 19 | PWR OUT 4 | Parallel with pin 26 |
| 20 | PWR OUT 1 | Parallel with pin 14 |
| 21 | A/D I/O 1 | ADIO1 |
| 22 | A/D I/O 3 | ADIO3 |
| 23 | A/D I/O 5 | ADIO5 |
| 24 | A/D I/O 7 | ADIO7 |
| 25 | N/C | |
| 26 | PWR OUT 4 | Parallel with pin 19 |

Also on enclosure (not SuperSeal): **USB-C** for config.

## PowerCore carrier mapping intent

| Razor loom | PowerCore nets |
|------------|----------------|
| M6 + / − | VBAT / GND power entry (fusing, TVS) — M6 bolt-through bobbins on the power plane |
| PWR OUT 1..4 (paired pins) | HP1..HP4 dual SuperSeal feeds from PROFET outs |
| ADIO 1..8 | ADIO front-end I/O |
| CAN H/L | Module CANH/CANL |
| IGN SW | Key sense → divider → `IN_VIGN` path (and/or digital) |
| SENSOR 5V ×2 | `V5A_SWITCHABLE` via PWR_EN |
| SENSOR GND ×2 | AGND / sensor ground island |
| USB-C | Module USB |

MCU module: **mega-mcu144** rev ≥ 0.7. Internal MM144 net assignment: see PINMAP.md.
