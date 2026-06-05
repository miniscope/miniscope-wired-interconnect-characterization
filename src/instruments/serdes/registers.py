"""
GMSL2 register map for the MAX96717 serializer / MAX96716A deserializer pair.

Addresses and bit positions are taken from the ADI "GMSL2 Link Margin
Application Note" (Rev 1.2) and the eye-mapping algorithm, as used by the
lab's gmsl2-cable-tester scripts. Constants only -- no I/O.
"""

from __future__ import annotations

# I2C device addresses (8-bit datasheet form; the bridge accepts 7-bit too).
SER_ADDR = 0x80  # MAX96717 serializer
DES_ADDR = 0x98  # MAX96716A deserializer

SER_DEV_ID_EXPECTED = 0xBF
DES_DEV_ID_EXPECTED = 0xBE

# ---- Common registers (both SER and DES) -----------------------------------
REG_DEV_ID = 0x000D  # device ID
REG_REG1 = 0x0001  # link-rate config (SER TX_RATE[3:2], DES RX_RATE[1:0])
REG_CTRL0 = 0x0010  # [7] RESET_ALL, [5] RESET_ONESHOT
REG_CTRL3 = 0x0013  # [3] LOCKED, [2] ERROR, [1] CMU_LOCKED
REG_CNT0 = 0x0022  # decode error counter (read clears)

# Link-rate codes (2-bit fields in REG1).
RATE_CODE_3G = 0x01
RATE_CODE_6G = 0x02

# ---- Serializer (MAX96717) RLMS registers -----------------------------------
REG_SER_RLMS3 = 0x1403  # global adapt [7]
REG_SER_RLMS4 = 0x1404  # EOM enable/disable
REG_SER_RLMS84 = 0x1484  # replica amp LSB [7]
REG_SER_RLMS85 = 0x1485  # replica amp MSBs + manual enable [7]
REG_SER_RLMS95 = 0x1495  # manual TX amplitude: [7] enable, [5:0] code
REG_SER_RLMSA4 = 0x14A4  # periodic adapt [5:0]
REG_SER_RLMSBA = 0x14BA  # minimum tune amplitude
REG_SER_RLMSC8 = 0x14C8  # TX amplitude code (Algorithm #2) [6:0]
REG_SER_RLMSC9 = 0x14C9  # main FFE
REG_SER_RLMSCA = 0x14CA  # replica FFE
REG_SER_RLMSCE = 0x14CE  # TX control / SION / FFE disable

# Serializer pattern generator (PRBS eye source).
REG_SER_VTX1 = 0x024F  # PATGEN_CLK_SRC
REG_SER_VTX29 = 0x026B  # VID_PRBS_EN, PATGEN_MODE

# ---- Deserializer (MAX96716A) RLMS registers (Phy A) ------------------------
REG_DES_RLMS3 = 0x1403  # global adapt [7]
REG_DES_RLMS4 = 0x1404  # EOM [1] periodic, [0] enable toggle
REG_DES_RLMS34 = 0x1434  # observation count low
REG_DES_RLMS35 = 0x1435  # observation count high
REG_DES_RLMS37 = 0x1437  # eye monitor ctrl: [4] done, [3] clear, [2] start, [1] EMP, [0] polarity
REG_DES_RLMS38 = 0x1438  # error count low
REG_DES_RLMS39 = 0x1439  # error count high
REG_DES_RLMS3A = 0x143A  # hit count low
REG_DES_RLMS3B = 0x143B  # hit count high
REG_DES_RLMS49 = 0x1449  # error channel power [2]
REG_DES_RLMS58 = 0x1458  # voltage threshold 0 [6:0]
REG_DES_RLMS59 = 0x1459  # voltage threshold 1 [6:0]
REG_DES_RLMS95 = 0x1495  # manual TX amplitude (reverse link)
REG_DES_RLMSA4 = 0x14A4  # periodic adapt [5:0]

# Phase register pairs (P1, P0) by lane, for the eye monitor.
REG_DES_PHASE = {
    "fwd_6g": (0x143F, 0x143E),  # RLMS3F / RLMS3E
    "fwd_3g": (0x14AD, 0x14AC),  # RLMSAD / RLMSAC
    "rev_187m": (0x14B7, 0x14B6),  # RLMSB7 / RLMSB6
}

# Algorithm starting TX amplitudes (mV), from the app note.
SER_TX_START_MV = 410  # forward (Algorithm #1 / #2)
DES_TX_START_MV = 250  # reverse (Algorithm #3); default code 0x69
DES_TX_DEFAULT_CODE = 0x69  # ~250 mV; restore target if the reverse link drops

# Eye-monitor grid extents (register-code space).
MAX_PHASE = 128  # phase sweeps 0..127
MAX_VTH = 64  # vth sweeps 0..63 per polarity
