# GMSL2 SerDes Characterization Protocol

**What this measures:** real-world digital link quality through the cable
using the same GMSL2 serializer/deserializer family the Miniscope uses.
For each of the **forward channel** (high-bandwidth data) and **back
channel** (control), at both **3 Gbps and 6 Gbps**, the script captures:

- an **eye diagram** -- a 2D map of bit-error counts across sampling time
  and threshold voltage; the open "eye" in the middle is the safe
  operating region, and
- a **link-margin sweep** -- bit errors vs TX amplitude as the transmit
  swing is reduced in 10 mV steps (1 mV steps near the error onset). The
  lowest error-free amplitude is the link's headroom.

## Equipment

- GMSL2 serializer/deserializer evaluation pair, powered, connected to
  this PC over the I2C adapter
- The cable sample under test

## Steps

1. **Connect the cable** between the serializer and deserializer eval
   boards. Tighten coax connections finger-tight plus a nudge.
2. **Check the link.** Use the *Check link* button -- the deserializer
   must report lock before characterizing. No lock usually means a bad
   connection or a damaged cable.
3. **Hit Go.** The full sequence (2 channels x 2 rates, eye + margin
   each) runs automatically and takes several minutes. Live previews
   appear as each capture completes -- a clearly open eye and a clean
   error-onset curve mean the run is good.
4. **Review and save.** If a preview looks wrong (closed eye on a short
   cable, noisy margin curve), check connections and rerun before saving.
5. **Repeat sessions, not points.** For variability, run the whole
   sequence again as a new session; the pipeline pools repeated sessions.

## Notes

- The script may average several internal repeats per sweep point; only
  final per-point values are stored.
- Eye axis ranges (mV / ps) are recorded in the data files, so captures
  at different settings remain comparable.
