# PowerCore — Rev 1

**Status:** Rev 1 design baseline  
**Product:** PowerCore (standalone PDM; Link Razor-compatible SuperSeal loom)  
**MCU module:** Hellen mega-mcu144 (STM32F767)  
**Firmware base:** [fw-powercore](https://github.com/quintinbannink42/fw-powercore) (rusEFI custom board)  
**I/O target:** Link ECU Razor PDM I/O + protection parity  

Former working names (docs/history only): `hellen-pdm-razor`, Hellen Razor-class PDM. KiCad stem stays **`pdmrazora`**.

## Goals (rev 1)

Ship a first PowerCore Hellen-One carrier + firmware that can:

1. Drive **4× high-power** channels at **25 A continuous / 80 A peak**, HS (DIR/H-bridge optional if pins allow).
2. Provide **8× ADIO** at **8 A** high-side, with analog/digital input modes and software pull-ups.
3. Log **per-channel current** on high-power outputs (and ADIO when used as outputs).
4. Implement programmable electronic-fuse behaviour (inrush window, overcurrent, trip time, retry/latch, over-temp).
5. Speak **USB** + **CAN**; expose channels in TunerStudio / gauges.

Non-goals for rev 1: sealed Link-style CNC housing, PC “PDM Link” clone UI, full galvanic isolation, second MCU.

## Architecture

```
                    +------------------+
   VBAT ------------| Power entry      |
                    | TVS, reverse,     |
                    | fuse, sense      |
                    +--------+---------+
                             |
              +--------------+--------------+
              |                             |
     +--------v--------+           +--------v--------+
     | HP stage x4     |           | ADIO stage x8   |
     | PROFET / half-  |           | 8 A high-side   |
     | bridge capable  |           | + pin mux       |
     | IS -> ADC       |           | V/I -> ADC      |
     +--------+--------+           +--------+--------+
              | EN/PWM/DIR                  | EN/PWM/PU
              |                             |
              +--------------+--------------+
                             |
                    +--------v---------+
                    | mega-mcu144      |
                    | STM32F767        |
                    | USB / CAN / ADC  |
                    +--------+---------+
                             |
                    +--------v---------+
                    | SuperSeal I/O    |
                    | + USB-C          |
                    +------------------+
```

## Electrical targets (from Link Razor)

| Block | Count | Continuous | Peak / trip notes | Modes |
|-------|------:|------------|-------------------|--------|
| High-power | 4 | 25 A | 80 A safe peak; measure to ~60 A | HS (rev1); LS / half / full bridge stretch |
| ADIO | 8 | 8 A HS out | Fixed ~10 A hardware trip class | Analog in, digital in, HS out; ADIO1–4 PWM out; ADIO5–8 freq/PWM in |
| Supply | — | 6–24 V | 12/16 V nominal | Quiescent &lt;300 mA outputs off |
| Aux | — | 5 V sensor @ 50 mA/pin class | — | Sensor GND separate from chassis |

## Firmware electronic fuse (clone Razor behaviour)

Per high-power channel:

- **Inrush** limit + trip time + duration window after turn-on
- **Overcurrent** limit + trip time after inrush window
- **Fast short** path (~60 A class) → immediate off
- **Retry** (count + delay) or **latch-off**
- **Over-temp** board threshold with hysteresis
- Optional soft-start duty ramp on PWM channels

ADIO outputs: simpler fuse (fixed hardware trip + software trip time / retry / latch).

## Pin budget (mega-mcu144)

Provisional function map — STM32 / MM144 edge names filled from module docs in `PINMAP.md`.

| Function | Count | Notes |
|----------|------:|-------|
| HP_EN / PWM | 4 | TIM PWM ≥10 kHz |
| HP_DIR | 0–4 | Stretch; omit on first spin if copper tight |
| HP_ISENSE ADC | 4 | Continuous current |
| ADIO_EN / PWM | 8 | 4 with PWM timers |
| ADIO_PU | 8 | Soft 4k7 to 5 V |
| ADIO_SENSE ADC | 8–16 | Prefer V+I; 144 should allow at least V **or** I per pin without mux |
| Freq / PWM in | 4 | ADIO5–8 input path |
| VBATT / 5V / TEMP ADC | 3 | |
| USB | 1 | On module |
| CAN | 1 | On module |
| Status LEDs | ≥4 | Module LEDs + carrier if needed |
| PWR_EN | 1 | Switched 5 V sensor rail |

## Rev 1 hardware BOM direction

- **MCU:** Hellen mega-mcu144 module footprint
- **HP switches:** Infineon PROFET+2 / PROFET (e.g. BTS70xx class sized for 25 A continuous + inrush); IS pin to ADC via Rl
- **ADIO switches:** smaller PROFET / high-side (8 A continuous)
- **Connector:** 26-pin SuperSeal family (Razor-like dual pins on HP feeds)
- **USB-C** for config (RusEFI USB)
- **CAN** transceiver on module or carrier as per MM144 edge

## Firmware repo layout (planned)

```
fw-powercore/
  meta-info.env
  board.mk
  board_configuration.cpp   # pin map + defaults
  prepend.txt
  firmware/                 # electronic fuse + channel state machine
  README.md
```

Build via RusEFI custom-board GitHub Action pattern (`rusefi/fw-custom-example`).

## Build order

1. Freeze pin map (`PINMAP.md`) against MM144 edge  
2. Hellen-One KiCad frame + HP/ADIO modules  
3. Bring-up firmware: toggle HP/ADIO, read ADCs in TunerStudio  
4. Electronic-fuse state machine  
5. CAN channel command / status frames  

## Open items for next docs

- Exact MM144 edge → STM32 assignment (`PINMAP.md`)
- Chosen PROFET PNs and sense-resistor cal
- Connector pinout drawing
- CAN DBC draft
