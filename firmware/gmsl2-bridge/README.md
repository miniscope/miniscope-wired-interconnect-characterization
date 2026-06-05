# gmsl2-bridge — Raspberry Pi Pico Firmware

MicroPython firmware for the Raspberry Pi Pico (RP2040). A generic I2C
pass-through bridge between the bench PC and the GMSL2 dev kit (MAX96717
serializer + MAX96716A deserializer). **All algorithm logic runs on the host**
in `src/instruments/serdes/real.py`; the Pico only executes register reads and
writes on demand. This is the real transport behind
`src.instruments.serdes.pico_bridge.PicoBridgeI2C`.

## Wiring

| Pico pin | Signal | Dev kit |
|---|---|---|
| GP0 (pin 1) | SDA | SDA |
| GP1 (pin 2) | SCL | SCL |
| GND (pin 3) | GND | GND |

> **Do not** connect the Pico 3V3 pin to the dev kit. Power the Pico from USB only.

## Install

1. Flash the latest MicroPython UF2 for the Pico
   ([micropython.org/download/RPI_PICO](https://micropython.org/download/RPI_PICO/)):
   hold **BOOTSEL**, plug in USB, release, drag the UF2 onto the `RPI-RP2` drive.
2. Copy `main.py` onto the Pico with [Thonny](https://thonny.org)
   (File → Save as → "Raspberry Pi Pico") or `mpremote`:
   ```bash
   pip install mpremote
   mpremote connect auto cp main.py :main.py
   ```
3. Reset. The firmware auto-runs and prints:
   `# gmsl2-bridge v1.0 ready, I2C @ 100 kHz, GP0/GP1`

## Host port

The driver defaults to `/dev/pico`. On Linux, create a persistent symlink:

```bash
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="2e8a", ATTRS{idProduct}=="0005", SYMLINK+="pico"' \
    | sudo tee /etc/udev/rules.d/99-pico.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

On Windows pass the COM port explicitly, e.g.
`RealSerdesDriver(port="COM5")`. Verify the bridge responds:

```bash
python -c "import serial,time; s=serial.Serial('/dev/pico',115200,timeout=2); \
time.sleep(1.5); s.write(b'PING\n'); print(s.readline().decode().strip())"  # -> PONG
```

## Serial protocol

ASCII, `\n`-terminated, 115200 baud. Lines beginning with `#` are banner /
comment lines and are ignored by the host. Both 8-bit (`0x80`, `0x98`) and
7-bit (`0x40`, `0x4C`) addresses are accepted. Errors reply `ERR <reason>`.

| Command | Example | Response |
|---|---|---|
| `PING` | `PING` | `PONG` |
| `ID` | `ID` | `ID gmsl2-bridge v1.0` |
| `SCAN` | `SCAN` | `SCAN 0x40,0x4C` |
| `R <addr> <reg>` | `R 0x98 0x000D` | `OK 0xBE` |
| `W <addr> <reg> <val>` | `W 0x80 0x0010 0x80` | `OK` |
| `RM <addr> <reg> <n>` | `RM 0x98 0x1438 2` | `OK 0x00,0x01` |
| `WM <addr> <reg> <v1,v2,...>` | `WM 0x80 0x024F 0x0D,0x81` | `OK` |
| `FREQ <hz>` | `FREQ 400000` | `OK` |

Source: adapted from the lab's
[gmsl2-cable-tester](https://github.com/Aharoni-Lab/gmsl2-cable-tester) repo.
