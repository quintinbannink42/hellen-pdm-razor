# PowerCore pin map — mega-mcu144 (H144 / STM32F767ZI)

Symbols from `firmware/config/boards/hellen_meta.h` (`H144_*`).  
Edge nets on the KiCad symbol are unprefixed (`OUT_PWM1`, `IN_VIGN`, …).

**Module:** [mega-mcu144](https://github.com/andreika-git/hellen-one/tree/master/modules/mega-mcu144) rev ≥ 0.4 (prefer **0.7**).  
**Must drive** `OUT_PWR_EN` / `H144_GP8` (PE10) high so switched analogs / 5 V / SD come up.

## High-power outputs (4)

| Chan | Enable / PWM | Edge | H144 / STM32 | DIR (optional) | Edge | Current sense | Edge / ADC |
|------|--------------|------|--------------|----------------|------|---------------|------------|
| HP1 | EN | OUT_PWM1 | `H144_OUT_PWM1` PD13 | DIR | OUT_IO1 `H144_OUT_IO1` PD3 | IS | IN_AUX1 `H144_IN_AUX1_ANALOG` EFI_ADC_8 |
| HP2 | EN | OUT_PWM2 | `H144_OUT_PWM2` PC6 | DIR | OUT_IO2 `H144_OUT_IO2` PA9 | IS | IN_AUX2 `H144_IN_AUX2_ANALOG` EFI_ADC_14 |
| HP3 | EN | OUT_PWM3 | `H144_OUT_PWM3` PC7 | DIR | OUT_IO3 `H144_OUT_IO3` PG14 | IS | IN_AUX3 (verify AUX3/4 flip on 0.7) EFI_ADC_7 |
| HP4 | EN | OUT_PWM4 | `H144_OUT_PWM4` PC8 | DIR | OUT_IO4 `H144_OUT_IO4` PG5 | IS | IN_AUX4 EFI_ADC_15 |

## ADIO (8) — separate current + voltage sense

| Chan | EN edge | H144 EN | Current (I) | Voltage (V) | Pull-up EN |
|------|---------|---------|-------------|-------------|------------|
| ADIO1 | OUT_PWM5 | `H144_OUT_PWM5` PC9 | IN_MAP1 EFI_ADC_10 | IN_TPS EFI_ADC_4 | OUT_IO9 `H144_OUT_IO9` PG13 |
| ADIO2 | OUT_PWM6 | `H144_OUT_PWM6` PD14 | IN_MAP2 EFI_ADC_11 | IN_PPS EFI_ADC_3 | OUT_IO10 `H144_OUT_IO10` PG12 |
| ADIO3 | OUT_PWM7 | `H144_OUT_PWM7` PD15 | IN_MAP3 EFI_ADC_2 | IN_TPS2 mux EFI_ADC_20 | OUT_IO11 `H144_OUT_IO11` PG2 |
| ADIO4 | OUT_PWM8 | `H144_OUT_PWM8` PD12 | IN_O2S EFI_ADC_0 | IN_PPS2 mux EFI_ADC_19 | OUT_IO12 `H144_OUT_IO12` PA8 |
| ADIO5 | OUT_IO5 | `H144_OUT_IO5` PD2 | IN_O2S2 EFI_ADC_1 | IN_CLT EFI_ADC_12 | OUT_IO13 `H144_OUT_IO13` PG6 |
| ADIO6 | OUT_IO6 | `H144_OUT_IO6` PG11 | IN_RES1 PF9 | IN_IAT EFI_ADC_13 | IO1 `H144_GP_IO1` PD4 |
| ADIO7 | OUT_IO7 | `H144_OUT_IO7` PG3 | IN_RES2 PF10 | IN_AT1 mux EFI_ADC_29 | IO2 `H144_GP_IO2` PD7 |
| ADIO8 | OUT_IO8 | `H144_OUT_IO8` PG4 | IN_RES3 PF8 | IN_AT2 mux EFI_ADC_28 | IO3 `H144_GP_IO3` PG10 |

Muxed V channels (TPS2/PPS2/AT1/AT2) need `ADC_MUX_PIN` = PF2 (`H144_GP9`) and PWR_EN already high.

Freq / digital capture for ADIO5–8 when used as inputs: `H144_IN_D_1`–`4` (PE12–15) and/or digital companions on CLT/IAT/AUX.

## System

| Function | Edge | H144 / STM32 |
|----------|------|--------------|
| USB | USBID / USBM / USBP | PA10 / PA11 / PA12 |
| CAN | CANH / CANL | PD0 / PD1 (on-module xcvr) |
| VBATT sense | IN_VIGN | `H144_IN_VBATT` PA5 EFI_ADC_5 |
| Board temp | IN_SENS1 | PF3 (ADC3 path) |
| PWR_EN | OUT_PWR_EN | `H144_GP8` PE10 |
| LEDs | LED_* | PG0 / PG1 / PE7 / PE8 |

## Spares (rev 1.1+)

`OUT_INJ1`–`8`, `IGN1`–`8`, `IO4`–`7`, `IN_CRANK`/`CAM`/`VSS`, `IN_SENS2`–`4`, SPI2/3, I2C, UART2/8 — FAULT lines, second CAN, extra digitals.

## Firmware notes

- Firmware overlay: [fw-powercore](https://github.com/quintinbannink42/fw-powercore) (`SHORT_BOARD_NAME=powercore`).
- Prefer template [fw-custom-hellen144-f4](https://github.com/rusefi/fw-custom-hellen144-f4) (F7 CPU in our `meta-info.env`) or Hellen boards using `hellen-common144.mk` / `hellen-common-mega144.mk`.
- Hardware frame: [hellen-example](https://github.com/rusefi/hellen-example).
- `protected_gpio` covers 8 channels: map **HP1–4 + ADIO1–4** first; ADIO5–8 protection is TODO / second bank.
- Confirm IN_AUX3/AUX4 orientation against mega-mcu144 **0.7** schematic before PCB.
