# PILOT note (hft-team-04)

**PILOT, 20 made-up development cases, one run.** NOT REVIEWED.

## What this is
- A small trial of the three-step pre-check (reader, rule checker, referee) on 20 made-up cases.
- All 20 cases are development cases. No held-out case is created, read or named.
- Names are invented. The data is synthetic.
- Expected answers were written and hashed before the run (`pilot/cases/EXPECTED_HASH.json`). The hash of each answer is stored in the log row of its run.

## The 20 cases
- 12 with one planted fault (labels and alerts; rule ids from the rule list).
- 4 clean.
- 2 unreadable. They must end UNABLE TO CHECK, never "no findings".
- 2 planted traps: one fake quote (must be dropped) and one repeated sentence (the repeat detector must fire). A trap is planted in the rule checker answer by the runner; the reader still runs on the real model.

## Time
Plan for about 15 to 20 minutes per case-run with gpt-oss:20b (3 agent steps, 4 to 7 minutes each, from the 8 Nov demo). 20 cases once = about 5 to 7 hours.
Measured 9 Nov (real run, gpt-oss:20b, pilot_run.log): 20 cases took 66 minutes (17:38 to 18:44 UTC), about 3.3 minutes per case. The plan above was too slow by about 5x; use the measured time. Run it in the background: one model job at a time, keep_alive 0, a log line before every call.

## How to read the result
- `pilot/pilot_result.json` holds, per case, the expected answer and the final state. It also holds counts only (x of n): found, missed, false alarms, UNABLE TO CHECK.
- Every figure is labelled "PILOT, 20 made-up development cases, one run".
- There is no accuracy figure, no percent and no kappa. There is no team-versus-single-model claim. That is a later study.
- Status is RUNNING until all 20 cases are saved, then COMPLETE. The run saves after each case and can be started again to resume.

## Limits
- This is a pre-check. It does not replace a human factors engineer.
- This is not a medical device. No clinical use.
- Model: gpt-oss:20b only (stub for tests). No MedGemma.
- Independence and data notice: the cases are made up and tied to no real product, site or employer.
- Licence: AGPL-3.0 with commercial use on request; content CC BY-NC.

## Re-judged by code (hft-team-08)
**PILOT, 20 made-up development cases, re-judged by code, same model outputs.** NOT REVIEWED. No model was called. The saved model outputs from `pilot/pilot_run.sqlite` went through the changed referee (`python pilot/rejudge.py`). Result file: `pilot/rejudge_result.json`.

| Count | Before (one run) | After (re-judged) |
|---|---|---|
| Faults found | 9 of 12 | 12 of 12 |
| Faults missed | 3 of 12 | 0 of 12 |
| Cases with an extra finding (false alarm) | 5 of 20 | 1 of 20 |
| Clean cases left clean | 3 of 4 | 4 of 4 |
| UNABLE TO CHECK | 3 of 20 | 3 of 20 |
| Traps caught | 2 of 2 | 2 of 2 |

- Three of the 12 faults (P03, P04, P08) are now found by a code rule alone, with no model finding. The model found 9 of 12. The reason text on those findings says "found by code rule, no model finding".
- The one remaining extra finding is P08: the model's quote does not hold the `[OK]` button, so the referee marks it DISPUTED for a human to look at.
- P10: the extra `WARNING` finding under ALT-02 is dropped. ALT-02 compares several alerts on one screen; one signal word in one alert cannot show that.
- The fixes were written as general code rules and tested on new sentences. They were also checked against these same 20 cases, so these counts are not a test on unseen cases. Counts only. No accuracy claim.
