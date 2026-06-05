"""
GMSL2 I2C Bridge — Raspberry Pi Pico (MicroPython)
Generic command-driven I2C bridge for GMSL2 SerDes register access.

Reusable for: link margin, eye mapper, register dumps, ad-hoc debugging.
The Pico performs ZERO algorithm logic — it only executes I2C transactions
on demand. All algorithms run on the host PC.

Wiring:
  Pico GP0 (pin 1)  -> Dev Kit SDA
  Pico GP1 (pin 2)  -> Dev Kit SCL
  Pico GND (pin 3)  -> Dev Kit GND
  (Power Pico from USB; do NOT connect 3V3 to dev kit)

Serial protocol (ASCII, \\n-terminated, 115200 baud):
  PING                     -> PONG
  SCAN                     -> SCAN 0x40,0x4C,...    (7-bit addresses found)
  ID                       -> ID gmsl2-bridge v1.0
  R <addr> <reg>           -> OK <hex_value>        e.g. R 0x98 0x000D -> OK 0xBE
  W <addr> <reg> <val>     -> OK
  WM <addr> <reg> <v1,v2,..> -> OK                  (multi-byte burst write)
  RM <addr> <reg> <n>      -> OK <h1>,<h2>,..,<hn>  (multi-byte read)
  FREQ <hz>                -> OK                    (re-init bus at given freq)

Address handling:
  Both 8-bit (0x80, 0x98 — as in ADI datasheets) and 7-bit (0x40, 0x4C)
  forms are accepted. The firmware normalizes to 7-bit internally.

Errors:
  Any failure replies with: ERR <message>
  Unknown command:           ERR unknown_cmd
  Bad arg count or parse:    ERR bad_args
  I2C NAK / bus error:       ERR i2c_<exception>

Install:
  1. Flash MicroPython on the Pico
  2. Copy this file as main.py
  3. Reset; firmware auto-runs and prints a banner
"""

from machine import I2C, Pin
import sys
import time

# ---- Pin / bus configuration ------------------------------------------------
SDA_PIN     = 0          # GP0
SCL_PIN     = 1          # GP1
I2C_ID      = 0          # Pico I2C peripheral 0
I2C_FREQ    = 100_000    # 100 kHz default; safe for any GMSL2 dev kit

# ---- Globals ----------------------------------------------------------------
i2c = None
FW_VERSION = "gmsl2-bridge v1.0"


# =============================================================================
# I2C helpers
# =============================================================================
def init_i2c(freq=I2C_FREQ):
    """(Re)initialize the I2C peripheral."""
    global i2c
    i2c = I2C(I2C_ID, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=freq)
    time.sleep_ms(10)


def normalize_addr(addr):
    """
    Accept either 8-bit (datasheet) or 7-bit (MicroPython) I2C address.
    Anything > 0x77 is treated as 8-bit and right-shifted by 1.
    """
    if addr > 0x77:
        return addr >> 1
    return addr


def reg_to_bytes(reg):
    """Pack a 16-bit register address as big-endian [hi, lo]."""
    return bytes([(reg >> 8) & 0xFF, reg & 0xFF])


def i2c_read(addr8_or_7, reg, n=1):
    """Read n bytes from a 16-bit register address."""
    addr = normalize_addr(addr8_or_7)
    i2c.writeto(addr, reg_to_bytes(reg), False)  # repeated start
    return i2c.readfrom(addr, n)


def i2c_write(addr8_or_7, reg, payload):
    """Write payload bytes to a 16-bit register address."""
    addr = normalize_addr(addr8_or_7)
    i2c.writeto(addr, reg_to_bytes(reg) + bytes(payload))


# =============================================================================
# Command parser
# =============================================================================
def parse_int(tok):
    """Parse an int from a token; supports 0x prefix or decimal."""
    tok = tok.strip()
    if tok.lower().startswith("0x"):
        return int(tok, 16)
    return int(tok, 10)


def parse_int_list(tok):
    """Parse a comma-separated list of ints (e.g. '0x29,0x55,12')."""
    return [parse_int(t) for t in tok.split(",") if t.strip()]


def handle_command(line):
    """Dispatch a single command line. Returns the response string (no newline)."""
    parts = line.strip().split()
    if not parts:
        return ""  # empty line, no response
    cmd = parts[0].upper()
    args = parts[1:]

    try:
        if cmd == "PING":
            return "PONG"

        if cmd == "ID":
            return f"ID {FW_VERSION}"

        if cmd == "SCAN":
            found = i2c.scan()
            if not found:
                return "SCAN none"
            return "SCAN " + ",".join(f"0x{a:02X}" for a in found)

        if cmd == "FREQ":
            if len(args) != 1:
                return "ERR bad_args"
            init_i2c(parse_int(args[0]))
            return "OK"

        if cmd == "R":
            if len(args) != 2:
                return "ERR bad_args"
            addr = parse_int(args[0])
            reg  = parse_int(args[1])
            data = i2c_read(addr, reg, 1)
            return f"OK 0x{data[0]:02X}"

        if cmd == "W":
            if len(args) != 3:
                return "ERR bad_args"
            addr = parse_int(args[0])
            reg  = parse_int(args[1])
            val  = parse_int(args[2]) & 0xFF
            i2c_write(addr, reg, [val])
            return "OK"

        if cmd == "RM":
            if len(args) != 3:
                return "ERR bad_args"
            addr = parse_int(args[0])
            reg  = parse_int(args[1])
            n    = parse_int(args[2])
            if n < 1 or n > 64:
                return "ERR bad_count"
            data = i2c_read(addr, reg, n)
            return "OK " + ",".join(f"0x{b:02X}" for b in data)

        if cmd == "WM":
            if len(args) != 3:
                return "ERR bad_args"
            addr = parse_int(args[0])
            reg  = parse_int(args[1])
            payload = parse_int_list(args[2])
            if not payload or len(payload) > 64:
                return "ERR bad_count"
            i2c_write(addr, reg, payload)
            return "OK"

        return "ERR unknown_cmd"

    except (ValueError, IndexError):
        return "ERR bad_args"
    except OSError as e:
        # I2C NAK or bus error
        return f"ERR i2c_{e.args[0] if e.args else 'fail'}"
    except Exception as e:
        return f"ERR {type(e).__name__}"


# =============================================================================
# Main loop
# =============================================================================
def main():
    init_i2c()
    # Banner — host script can ignore lines until it sees one starting with OK/ID/PONG
    print(f"# {FW_VERSION} ready, I2C @ {I2C_FREQ//1000} kHz, GP{SDA_PIN}/GP{SCL_PIN}")

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                continue
            response = handle_command(line)
            if response:
                print(response)
        except KeyboardInterrupt:
            print("# interrupted")
            break
        except Exception as e:
            print(f"ERR loop_{type(e).__name__}")


if __name__ == "__main__":
    main()
