# Spec: agreement statistics and scorer (`stats.py`)

Standard library only. No network, no model call. It reads no reader data and no log; it works on lists you pass in.

## Input
Plain lists, one entry per unit (a marked item). A third list gives the cluster id for each unit: the label it came from. Units from one label stay together in the interval.

## Figures
| Function | Gives |
|---|---|
| `kappa(a, b)` | Cohen's kappa, any number of categories. `UNDEFINED` when chance agreement is 1 (for example every rater says "absent"). Never 1.0, never a crash. |
| `weighted_kappa(a, b, weights, order)` | `linear` or `quadratic` weights for ordered severity. `order` lists the categories low to high. |
| `krippendorff_alpha_nominal(units)` | Nominal alpha. One list per unit, one value per rater, `None` for missing. 3 or more raters allowed. A unit with fewer than 2 values is left out. `UNDEFINED` if nothing varies. |
| `raw_agreement`, `positive_agreement`, `negative_agreement`, `prevalence` | Raw = share of equal calls. Positive = 2a/(2a+b+c). Negative = 2d/(2d+b+c). Prevalence = mean of the two readers' share of "fault present". |
| `sensitivity_false_alarms(ref, model, labels)` | Sensitivity as found, of, and share. False alarms per clean label as a separate figure. A clean label is a label with no reference fault. Only false alarms inside clean labels count. No merged accuracy figure exists. |
| `bootstrap_interval(a, b, clusters, seed, resamples)` | 95 percent percentile interval for kappa. Whole labels are resampled with replacement. Defaults: 2000 resamples, fixed seed, `random.Random(seed)`. Resamples where kappa is undefined are dropped and counted (`bootstrap_detail`). Returns `None` if fewer than half remain. |
| `verdict(kappa, half_width, target=0.8, max_half_width=0.12)` | `PASS` only if kappa is above the target and the half-width is at most 0.12. Otherwise `NOT SHOWN: interval too wide`, `NOT SHOWN: kappa below target` or `NOT SHOWN: kappa undefined`. Interval is checked first. |
| `report(a, b, clusters)` | All of the above in one dict, plus `n_units`, `n_labels` and `pilot`. |

`pilot` is `PILOT` when there are fewer than 100 units or fewer than 40 labels.

The target 0.8 and the limit 0.12 are a proposal until ED confirms (plan, open item 4). They are arguments, not fixed.

## Scorer
`score(reader_a, reader_b, model, adjudicated=None)` takes rows as dicts: `label`, `unit`, `call` (0 or 1); reader rows also `author`. Adjudicated rows hold `label`, `unit`, `call` and `decided_by` (who decided: a third reader, or the two readers together).

It raises `ScorerError` and returns no figure when:
- a reader input is missing or empty;
- any reader row holds a field with "model" in its name;
- a row names no author, a file holds more than one author, or both files name the same author;
- the readers' units differ, a unit repeats, or the model rows are missing or do not match.

With good input it gives reader agreement (`report`) and the model against the reference.

Reference rule:
- Primary reference: a human adjudicated answer for every unit where the readers differ, stored with `decided_by`. Units where they agree keep the agreed call. The primary figures carry the model kappa, sensitivity and false alarms, and the names in `adjudicated_by`.
- Secondary, labelled: the units where both readers agree. Disagreements are left out, so this figure can look better than the primary. It sits under `agreed_only_secondary` and is never the headline.
- Always reported: `units_readers_disagree` and `units_without_adjudicated_answer`. A row with no call or no `decided_by` is not an answer.
- If any answer is missing, `model_vs_reference` says "NOT SHOWN" with the count. No primary figure is given. An adjudicated row for a unit the readers agree on, or for an unknown unit, is refused.

The output carries "NOT REVIEWED". If reader kappa is not above target it says to fix the marking rules first (plan, Reliability a).

Command line: `python stats.py reader_a.json reader_b.json model.json [adjudicated.json]`. The first three files are needed. Any error prints to stderr, exits with code 2 and prints nothing on stdout.

## Where the expected values come from
No published worked example could be checked from files on disk. The two reporting-guide notes we hold list report fields only and are not full text. So every expected value in `tests/test_stats.py` is hand-worked, with the arithmetic in the test comment. The formulas are the standard ones: kappa = (po - pe)/(1 - pe); weighted kappa = 1 - Do/De; alpha = 1 - Do/De from the coincidence matrix.

## Checks
`tests/test_stats.py`. Planted tables with kappa 0.60, 0.80 and 0.90 are recovered within 0.02. Hand-worked: 2x2 table 20/5/10/15 (kappa 0.40), a 3x3 table (linear 119/169, quadratic 97/122), an alpha example with a missing value (1/3). Each planted bad case must fail the check it targets. Reference check: a 20-unit table where the agreed-only model kappa is 0.75 and the adjudicated kappa is 0.40; one missing answer gives NOT SHOWN.
