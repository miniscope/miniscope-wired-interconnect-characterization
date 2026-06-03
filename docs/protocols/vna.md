# VNA (S-Parameter) Characterization Protocol

**What this measures:** the cable's RF behavior as 2-port S-parameters,
captured to a standard Touchstone `.s2p` file. The pipeline derives
attenuation vs frequency (from S21) and characteristic impedance, which
feed the per-cable wiki pages and the consolidated quality score.

## Equipment

- PicoVNA (or equivalent 2-port VNA) connected to this PC
- Calibration standards (SOLT kit)
- Adapters from the VNA ports to the cable's connectors

## Steps

1. **Calibrate (once per setup).** Run the VNA's SOLT calibration at the
   reference planes where the cable will connect, including any adapters.
   Recalibrate if you change adapters, cables to the VNA, or temperature
   shifts substantially. The app checks calibration before capture.
2. **Connect the cable** between port 1 and port 2.
3. **Capture.** The app runs the sweep and saves the `.s2p`. Review the
   attenuation preview: a smooth, monotonically increasing loss curve is
   expected -- sharp resonant dips usually mean a bad connection.
4. **Repeat sessions** for variability; each capture is its own session.

## Notes

- The `.s2p` is stored raw and unmodified -- all derived quantities are
  computed by the pipeline, so improved analysis can always be re-run on
  old captures.
- Record the calibration type in the session fields; it matters when
  comparing datasets.
