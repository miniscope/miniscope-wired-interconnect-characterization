# Round-Trip Loop Resistance Protocol

**What this measures:** the combined DC resistance of the coax center
conductor plus the shield return path, for one cable sample at its full
length. The analysis pipeline turns these values into round-trip
resistivity (ohm/m) and, combined with each Miniscope's power model, into
the minimum supply voltage users need for a given cable and length.

## Equipment

- LCR meter (or a 4-wire-capable multimeter)
- A shorting fixture or solder bridge for the far cable end
- The cable sample, with its actual connectors installed

## Steps

1. **Short the far end.** Connect the center conductor to the shield at
   the far end of the cable (shorting fixture preferred over a solder
   blob so the cable is reusable).
2. **Zero the meter.** Short the meter leads together and zero/relative
   the reading so lead resistance is excluded.
3. **Measure.** Connect the meter between the center conductor and shield
   at the near end. Record the DC resistance reading in ohms.
4. **Repeat.** Take at least 3 readings, reconnecting the meter between
   readings. Enter each reading as its own row -- the pipeline averages
   and reports spread automatically.
5. **Note anything unusual** (intermittent contact, connector wiggle
   sensitivity) in the notes field.

## Things that will bite you

- A dirty or loose short at the far end adds tens of milliohms and shows
  up as inflated resistivity. If readings drift, re-make the short.
- Temperature matters at the milliohm level; record the ambient
  temperature in the session fields.
- Do NOT divide by two: the pipeline knows this is a round-trip value and
  names everything `roundtrip_*` accordingly.
