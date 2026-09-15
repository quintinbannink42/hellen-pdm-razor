# Hardware BOM / sense assumptions — pdmrazora rev a

Production-intent parts chosen for Razor-class ratings. Firmware must still calibrate `AmpsPerVolt`.

## Connector

| Ref | PN | Notes |
|-----|-----|-------|
| J1 | **TE Connectivity 9-6437287-8** | AMP SuperSeal 1.0, 26-way, right-angle, Au, **keying 1**. Mating loom: SuperSeal 1.0 26S keying 1 (Link “Connector C”). Footprint: `pdmrazora:TE_9-6437287-8_SuperSeal26` (same PCB pattern as obsolete 6473423-1 / TE drawing 9-1437287-8; pitch 3.0 mm, 4 rows). Pin numbers = TE / [CONNECTOR.md](CONNECTOR.md). |

## High-power (HP1–4)

| Ref | PN | Package | Why |
|-----|-----|---------|-----|
| U1–U4 | **Infineon BTS50010-1TAD** | PG-TO-263-7 (`TO-263-7_TabPin4`) | 1.0 mΩ Power PROFET™ 12 V, IL(NOM) **40–48 A** @ 85 °C, ICL ≥ **150 A** — covers Razor **25 A continuous / 80 A peak** with margin. Automotive VS 3.2–28 V, ISENSE diagnosis. |

### HP current sense

| Param | Value | Notes |
|-------|-------|-------|
| kILIS (typ) | **≈ 52100** | Infineon `dkILIS` / kILIS at IL(NOM); treat as starting point |
| RIS | **2.7 kΩ** (R10/R20/R30/R40) | IIS = IL / kILIS → Vis = IIS · RIS |
| Filter | **10 nF** to GND (C10–C40) | ADC anti-alias / noise stub |
| Target | Vis ≤ ~3.0 V at **~60 A** measurable | 60/52100 · 2700 ≈ **3.1 V** |
| **AmpsPerVolt TODO** | `≈ kILIS / RIS ≈ 19.3 A/V` | Firmware: calibrate on bench; document final in board overlay |

Soft EN from `OUT_PWM1..4`. Optional DIR on `OUT_IO1..4` not wired in rev a.

## ADIO (ADIO1–8)

| Ref | PN | Package | Why |
|-----|-----|---------|-----|
| U11–U18 | **Infineon BTS7004-1EPP** | PG-TSDSO-14-22 | PROFET™ +2 12 V, **4.4 mΩ**, IL(NOM) **15 A** @ 85 °C — headroom above Razor **8 A continuous / ~10 A trip**. Single-channel maps 1:1 to eight ADIO stubs. |

Schematic still uses a simplified 5-pin stub symbol (EN/IS/VBAT/GND/OUT). PCB footprint is full TSDSO-14-22:

| Stub | Chip pin |
|------|----------|
| EN | IN (2); DEN (3) tied to EN on PCB stub |
| IS | IS (4) |
| VBAT | VS thermal pad (15) |
| GND | GND (1) |
| OUT | OUT (8–10, 12–14) |

### ADIO current sense

| Param | Value | Notes |
|-------|-------|-------|
| kILIS (typ) | **≈ 20000** | at IL(NOM) |
| RIS | **4.7 kΩ** (R101–R108) | Vis = (IL / kILIS) · RIS |
| Filter | **10 nF** (C101–C108) | |
| At 10 A | Vis ≈ 2.35 V | ADC-safe on 3.3 V Hellen analogs |
| **AmpsPerVolt TODO** | `≈ kILIS / RIS ≈ 4.26 A/V` | Calibrate per channel |

### Soft pull-ups

| Ref | Value | Net |
|-----|-------|-----|
| R201–R208 | **4.7 kΩ** to **SENSOR_5V** | Series toward ADIOn node; **enable with FET/GPIO** already labeled (`OUT_IO9..13`, `IO1..3` per PINMAP). Rev a wires R to ADIO node + SENSOR_5V; discrete N-FET high-side enable still TODO if hard disconnect required. |

Voltage sense dividers to `IN_TPS` / `IN_PPS` / … are labeled on the ADIO sheet (V-sense stubs); ratio TBD with SENSOR_5V domain.

## Power entry

| Ref | PN / value | Role |
|-----|------------|------|
| J2 | M6 stud stubs | VBAT+ / GND |
| F1 | **150 A Mega / fusible-link TBD** | Input fuse placeholder |
| — | Ideal-diode / P-FET note | Reverse-polarity strategy (not a placed controller yet) |
| D1 | **SMBJ33CA** (24–40 V automotive TVS class) | VBAT ↔ GND |
| C1 | **100 µF 50 V** stub | Bulk |
| C2 | **100 nF** | HF bypass |
| R1 / R2 | **100 kΩ / 10 kΩ** | IGN_SW → **IN_VIGN** ≈ **11:1** (V = Vin · 10/110) for Hellen `H144_IN_VBATT` path |

**SENSOR_GND** (SuperSeal pins 6 & 12): keep as AGND island — **do not** bond to chassis or power-GND star.

## Firmware TODOs

1. Set `AmpsPerVolt` HP ≈ 19.3 and ADIO ≈ 4.26, then two-point calibrate.
2. Confirm IN_AUX3/AUX4 orientation on mega-mcu144 **0.7**.
3. `protected_gpio` bank: HP1–4 + ADIO1–4 first.
4. VBATT scaler: match R1/R2 11:1 in board config.
