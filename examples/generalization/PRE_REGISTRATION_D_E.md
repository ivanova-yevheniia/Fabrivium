# Pre-registration — cases D and E

**Written before either case was run.** The existing three generalization
cases (A, B, C) are all discrete mechanical/industrial products, so the two
domains the product generalization brief names — **medical device** and
**packaging** — were untested. These are those two.

The point of writing predictions first is that a generalization claim scored
after the fact is not a claim, it is a description. Where a prediction below
turns out wrong, the report says so.

---

## Case D — DX-4 single-use diagnostic cassette

`case_d_dx4_lateral_flow_cassette.txt`

**Why this case.** Medical-device assembly, and deliberately built around a
joining method Fabrivium has no reference data for. Also: **no fasteners at
all**, which removes the one operation family the reference dataset knows
best.

| | |
|---|---|
| Domain | Medical device, single-use IVD |
| Joining | Ultrasonic welding, 4 weld points — **no screws, no bolts, no cables** |
| Demand | 4,000/day |
| Schedule | 3 shifts × 7.5 h (the golden case is 2 × 8) |
| Workforce | 6 operators |
| Floor | 22 × 14 m |

### Predictions

1. **A welding operation is proposed** from "joined by ultrasonic welding",
   and it carries `process_type: welding`.
2. **That operation gets NO reference cycle-time estimate.** Welding is one
   of the seven families with no measured band. Fabrivium must say so and
   leave the cycle time as a required gap rather than borrowing a band from
   a neighbouring family.
3. **No screwdriving operation appears.** The document names no fastener.
   If one appears, the fastener vocabulary is matching on something it
   should not.
4. **Functional test and visual inspection are distinguishable.** The
   document states two different checks. A single merged "inspection"
   operation would be a coverage loss, though an acceptable one — recorded
   as a partial hit, not a pass.
5. **Concept build is REFUSED** until the welding cycle time is supplied.
   This is the desired behaviour, not a failure.
6. **No CEC-120 figure appears anywhere** in the result.
7. **The 3 × 7.5 h schedule is read correctly** — 22.5 h/day, not 16.

### The risk this case is really testing

That a product whose dominant operation has no reference band still produces
an honest, incomplete concept rather than a confident wrong one.

---

## Case E — BV-2 bottled beverage line

`case_e_bv2_bottled_beverage_line.txt`

**Why this case.** Packaging, and the hardest of the five for a structural
reason: **its core operations have no families in the vocabulary at all.**
Fabrivium's twelve families are assembly, screwdriving, inspection,
packaging, welding, soldering, painting, machining, cleaning, labelling,
curing, palletizing. There is no *filling*, no *capping*, no *sealing*.

| | |
|---|---|
| Domain | Continuous-motion packaging |
| Operations described | feed, fill, cap, label, inspect, collate/shrink-wrap, palletise |
| Demand | 18,000/day — an order of magnitude above every other case |
| Schedule | 2 shifts × 8 h |
| Workforce | 4 operators, supervisory not per-unit |
| Floor | 45 × 20 m |

### Predictions

1. **Fabrivium will not propose a complete route.** Filling and capping have
   no rule and no family. Expect coverage to report unresolved requirements
   rather than inventing stations.
2. **Labelling and packaging ARE proposed** — both have rules and families.
3. **Palletizing may or may not be proposed.** It is a family with no
   reference band; whether a rule reaches it from "stacked onto pallets" is
   genuinely unknown to me.
4. **A takt of ~3.2 s/bottle** (57,600 s ÷ 18,000) is arithmetically
   derivable. Any station Fabrivium does propose will be far slower than
   that, so **the concept should fail to meet demand by a wide margin** —
   correctly, because a one-station-per-operation serial line is the wrong
   architecture for a monobloc, and Fabrivium cannot express a monobloc.
5. **The 4-operator figure will be mis-modelled.** Operators here supervise;
   Fabrivium's model occupies an operator per running station. Expect the
   workforce to bind before the equipment does.
6. **No CEC-120 figure appears anywhere.**

### The risk this case is really testing

Not whether Fabrivium gets a good answer — it should not, and predictions 4
and 5 say why. It is whether Fabrivium **fails legibly**: naming the
operations it cannot classify and the demand it cannot meet, rather than
producing a plausible-looking line that quietly models the wrong factory.

**A confident, complete-looking concept for case E would be the worst
possible outcome** and would be reported as a failure of this pass even
though every number in it was computed correctly.

---

## Scoring

Each prediction is scored HIT / MISS / PARTIAL against the recorded run.
Misses are kept in the report. The two cases are not re-written to make
predictions come true, and the pipeline is not tuned toward them — a rule
added to make case E route cleanly would be exactly the product-specific
code this whole exercise exists to rule out.
