# Independent evaluation protocol template

## Research questions
- Does an intervention change the specific intended measured behavior on an independently defined test set?
- Is general benign utility retained relative to an unchanged baseline?
- Does the effect remain stable across seeds, input variations and repeated measurements?
- Can spurious improvements be explained by a configuration shift, numerical failure or measurement leakage?

## Required methods for any real claims
- Independent control and intervention variants, pre-registered scoring and stop rules.
- Identical evaluation conditions and no training-test overlap.
- Negative controls and appropriate non-sensitive examples.
- Repeated seeds and uncertainty intervals.
- Mechanism-specific checks for gradient flow and numerical stability.
- Explicit limitations and unknowns; no claims from loss-only plots.

## Report schema
- Measurement name; source and evidence ID; model/config identity; evaluation time.
- Sample count, score, uncertainty and retained utility result.
- Failure cases, alternative explanations, independent reviewer verdict.

**Never use toy benchmark results to assert real biological safety.**
