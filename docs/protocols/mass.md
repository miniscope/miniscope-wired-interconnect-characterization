# Cable Mass (Mass) Protocol

**What this measures:** the net mass of a coax cable sample, isolated from
the PCBs and SMA connectors it is terminated with. You weigh the whole
assembly and the bare fixture (PCBs + SMA connectors) separately; the net
cable mass is their difference. The analysis pipeline turns these values
into mass per centimetre (g/cm) across lengths, the figure users care about
when budgeting tether mass on a moving animal.

## Equipment

- A balance/scale with enough resolution for the sample (0.01 g for short
  thin coax; 0.1 g is fine for longer cables)
- The cable sample, with its actual end PCBs and SMA connectors installed
- A spare set (or known mass) of the same end PCBs + SMA connectors to use
  as the fixture tare

## Steps

1. **Weigh the fixture.** Put the bare PCB(s) + SMA connector(s) -- the
   non-cable parts that terminate this assembly -- on the balance and record
   the mass in grams as `fixture_mass_g`.
2. **Weigh the assembly.** Put the complete cable assembly (cable + its end
   PCBs + SMA connectors) on the balance and record the mass as
   `assembly_mass_g`.
3. **Repeat.** Take at least 3 weighings, removing and replacing the item
   between readings. Enter each as its own row -- the pipeline computes the
   net mass (`assembly - fixture`), averages, and reports spread
   automatically.
4. **Note anything unusual** (heat-shrink, extra strain relief, residual
   flux) in the notes field, since it adds to the measured mass.

## Things that will bite you

- The fixture mass must be the SAME kind of PCB + connector that is on the
  cable; otherwise the subtraction does not isolate the cable. If the two
  ends differ, weigh both ends together as the fixture.
- `assembly_mass_g` must exceed `fixture_mass_g` -- a non-positive net
  mass means the fixture tare is wrong, and validation will reject it.
- Cable length is NOT entered here: it comes from the session folder, so
  the pipeline can derive mass per centimetre. Do not add a length column.
- Let the balance settle and zero (tare) it empty before each session;
  drift of a few hundredths of a gram is normal and shows up as spread.
