# Explaining why meetings moved

## Volume, rate and mix

The report splits the change in people booked into four parts that add up exactly to the total change. A **new segment** is one with nobody touched in the prior period. It has no old rate to compare, so its meetings get their own line instead of showing up as a rate change. Volume, mix and rate are measured on the segments that existed in the prior period. For each such segment s, in each period:

- V = people touched in the period across those segments, V_s = people touched in segment s
- w_s = V_s / V, the segment's share of people touched
- r_s = people booked in s / V_s, the segment's meeting rate (0 when the segment had nobody)
- R0 = the prior overall rate = sum of w0_s x r0_s

Then, with 0 for the prior period and 1 for the current one:

- **Volume** = (V1 - V0) x R0: the change from touching more or fewer people at the old rate
- **Mix** = V1 x sum of (w1_s - w0_s) x r0_s: the change from touching a different blend of segments
- **Rate** = V1 x sum of w1_s x (r1_s - r0_s): the change in conversion inside segments
- **New segment** = people booked in segments with nobody touched in the prior period

Volume + Mix + Rate + New segment = M1 - M0, exactly. The script computes with exact fractions and checks it. The per-segment table shows each segment's share of the mix and rate parts, so you can see where the change came from.

Why it matters: meetings can rise while every segment converts worse, because the mix moved toward a better segment. Without the split, that looks like a win.

## Two kinds of confidence

Give a count its own confidence and its explanation a separate one.

- The count's confidence comes from the sample: measured, too few to rate, or anecdote.
- The explanation's confidence is "inference" until something tests it.

Keep other possible causes listed until evidence rules them out: list quality, logging gaps, time of year, who was touched, and changes that shipped at the same time.

## Changes that shipped

Log every change to copy, scripts, lists, timing or tools in `funnel/changes.csv` with `date, change, area`.

- No change in the period: say so.
- One change: it may explain part of the movement. That is an inference, not a measurement.
- Two or more changes: they overlap, so none is credited. Run a test if you need to know which one mattered.

## Actions at the end

The report ends with at most three actions, each with its number and its size, or the line "Nothing needs to change." It never pads the list to three.

Candidate actions, in priority order:

1. **Bounce band**: watch or stop band on a measured bounce rate. Size: emails sent.
2. **Logging gaps**: excluded and incomplete rows above `logging_gap_share`. Size: rows.
3. **Quota gap**: the commit target is ahead of people booked and the meeting rate is measured. Size: meetings short.
4. **Clear opener winner**: a test with a clear leader. Size: connects in the test.
5. **Trailing segment**: a segment whose measured meeting rate is clearly below everyone else's. Size: people touched.
6. **Clear drop**: the reply or meeting rate clearly fell against the prior period. Size: people.
7. **Trailing angle**: an angle test past its minimum. Size: first touches.

Within the same priority, the bigger size comes first. When nothing qualifies, the right answer is "Nothing needs to change." That is a result, not a failure.
