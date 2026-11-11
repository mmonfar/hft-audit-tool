"""Agreement statistics and scorer tests. Synthetic tables only. Stdlib + pytest.

Every expected value has its working or its source in the comment above it.
No published value is quoted here: none could be checked from files on disk
(the two reporting-guide notes list report fields, not worked examples),
so all expected values are hand-worked. The working is shown.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import stats  # noqa: E402


def table(a, b, c, d):
    """2x2 rows. a = both 1, b = A 1 / B 0, c = A 0 / B 1, d = both 0.
    Each unit is its own label unless clusters are passed in by the caller."""
    rows = [(1, 1)] * a + [(1, 0)] * b + [(0, 1)] * c + [(0, 0)] * d
    A = [r[0] for r in rows]
    B = [r[1] for r in rows]
    return A, B, list(range(len(rows)))


# ---------------------------------------------------------------- Cohen kappa

def test_kappa_hand_worked_20_5_10_15():
    # Table a=20, b=5, c=10, d=15. N=50.
    # po = (20+15)/50 = 0.70.
    # A says 1: 25 of 50. B says 1: 30 of 50.
    # pe = (25*30 + 25*20) / 50^2 = (750 + 500) / 2500 = 0.50.
    # kappa = (0.70 - 0.50) / (1 - 0.50) = 0.40.
    A, B, _ = table(20, 5, 10, 15)
    assert stats.kappa(A, B) == pytest.approx(0.40, abs=0.005)


def test_kappa_other_tables_give_other_values():
    # Planted bad case: a different table must NOT give 0.40.
    # Table 25/0/0/25: po = 1, pe = 0.5, kappa = 1.0.
    A, B, _ = table(25, 0, 0, 25)
    assert stats.kappa(A, B) == pytest.approx(1.0, abs=1e-9)
    # Table 10/15/15/10: po = 0.4, pe = 0.5, kappa = (0.4-0.5)/0.5 = -0.2.
    A, B, _ = table(10, 15, 15, 10)
    assert stats.kappa(A, B) == pytest.approx(-0.2, abs=1e-9)


@pytest.mark.parametrize("target", [0.60, 0.80, 0.90])
def test_kappa_planted_tables(target):
    # Equal marginals (50 percent each), so pe = 0.5 and kappa = 2*po - 1.
    # po = (1 + target) / 2 -> 0.80, 0.90, 0.95. N = 1000.
    # Disagreements split evenly between b and c, so marginals stay 500/500.
    n = 1000
    dis = round(n * (1 - (1 + target) / 2))      # 200, 100, 50
    agree = n - dis
    a = d = agree // 2
    b = c = dis // 2
    A, B, _ = table(a, b, c, d)
    assert stats.kappa(A, B) == pytest.approx(target, abs=0.02)


def test_kappa_three_categories():
    # Table (rows A, cols B), categories x, y, z:
    #   x: 6 2 0 / y: 1 5 1 / z: 0 1 4. N = 20.
    # po = (6+5+4)/20 = 0.75. Row sums 8,7,5. Col sums 7,8,5.
    # pe = (8*7 + 7*8 + 5*5)/400 = (56+56+25)/400 = 137/400 = 0.3425.
    # kappa = (0.75-0.3425)/(1-0.3425) = 0.4075/0.6575 = 0.619772.
    A, B = _three_by_three()
    assert stats.kappa(A, B) == pytest.approx(0.4075 / 0.6575, abs=1e-6)


def _three_by_three():
    cells = {(0, 0): 6, (0, 1): 2, (0, 2): 0,
             (1, 0): 1, (1, 1): 5, (1, 2): 1,
             (2, 0): 0, (2, 1): 1, (2, 2): 4}
    A, B = [], []
    for (i, j), n in cells.items():
        A += [i] * n
        B += [j] * n
    return A, B


def test_kappa_undefined_when_all_one_category():
    # Both readers say 0 for every unit: pe = 1, kappa = 0/0.
    # Must return UNDEFINED, never 1.0 and never a crash. Raw agreement still shown.
    A, B, cl = table(0, 0, 0, 30)
    assert stats.kappa(A, B) == "UNDEFINED"
    assert stats.raw_agreement(A, B) == 1.0
    rep = stats.report(A, B, cl, seed=1, resamples=50)
    assert rep["kappa"] == "UNDEFINED"
    assert rep["raw_agreement"] == 1.0
    assert rep["verdict"].startswith("NOT SHOWN")


# ------------------------------------------------------------ weighted kappa

def test_weighted_kappa_linear_hand_worked():
    # Same 3x3 table as above, N=20, row sums 8,7,5, col sums 7,8,5.
    # Linear weight w = |i-j| / 2 (so 0, 0.5, 1).
    # Observed disagreement: cells off by 1 are (0,1)=2, (1,0)=1, (1,2)=1, (2,1)=1,
    #   total 5 units * 0.5 = 2.5; off by 2: none. Do = 2.5/20 = 0.125.
    # Expected: off by 1 pairs r_i*c_j: r0c1=64, r1c0=49, r1c2=35, r2c1=40 = 188;
    #   off by 2: r0c2=40, r2c0=35 = 75. De = (188*0.5 + 75*1)/400 = 169/400 = 0.4225.
    # kappa_w = 1 - 0.125/0.4225 = 1 - 50/169 = 119/169 = 0.704142.
    A, B = _three_by_three()
    assert stats.weighted_kappa(A, B, weights="linear") == pytest.approx(119 / 169, abs=1e-6)


def test_weighted_kappa_quadratic_hand_worked():
    # Same table. Quadratic weight w = (i-j)^2 / 4 (so 0, 0.25, 1).
    # Do = 5 units * 0.25 / 20 = 0.0625.
    # De = (188*0.25 + 75*1)/400 = (47+75)/400 = 122/400 = 0.305.
    # kappa_w = 1 - 0.0625/0.305 = 1 - 25/122 = 97/122 = 0.795082.
    A, B = _three_by_three()
    assert stats.weighted_kappa(A, B, weights="quadratic") == pytest.approx(97 / 122, abs=1e-6)


def test_weighted_kappa_differs_from_unweighted_and_between_weights():
    # Planted bad case: weights must matter. 0.6198 (plain) != 0.7041 != 0.7951.
    A, B = _three_by_three()
    plain = stats.kappa(A, B)
    lin = stats.weighted_kappa(A, B, weights="linear")
    quad = stats.weighted_kappa(A, B, weights="quadratic")
    assert len({round(plain, 4), round(lin, 4), round(quad, 4)}) == 3


def test_weighted_kappa_respects_given_order():
    # Same labels as words; order given by the caller, not by alphabet.
    # low=0, mid=1, high=2 must give the same answer as the numbers.
    A, B = _three_by_three()
    words = ["low", "mid", "high"]
    Aw = [words[i] for i in A]
    Bw = [words[i] for i in B]
    got = stats.weighted_kappa(Aw, Bw, weights="linear", order=words)
    assert got == pytest.approx(119 / 169, abs=1e-6)


def test_weighted_kappa_bad_weights_name_refused():
    A, B = _three_by_three()
    with pytest.raises(ValueError):
        stats.weighted_kappa(A, B, weights="cubic")


# ------------------------------------------------------ Krippendorff alpha

def test_alpha_nominal_hand_worked_with_missing():
    # Units (three raters; None = missing):
    #   u1: 1 1 1     u2: 1 2 -     u3: 2 2 2     u4: 1 1 2     u5: 2 - -
    # u5 has one value only and cannot be paired: it is left out.
    # Coincidence matrix: each unit adds (ordered pairs) / (m - 1), m = values in the unit.
    #   u1 (m=3): 1-1 ordered pairs = 6, /2 = 3        -> o11 += 3
    #   u2 (m=2): (1,2) and (2,1), /1                  -> o12 += 1, o21 += 1
    #   u3 (m=3): 2-2 ordered pairs = 6, /2 = 3        -> o22 += 3
    #   u4 (m=3): 1-1: 2 ordered, /2 = 1               -> o11 += 1
    #             (1,2) and (2,1): 2 each, /2 = 1 each -> o12 += 1, o21 += 1
    # So o11=4, o12=2, o21=2, o22=3. n = 11. n1 = 6, n2 = 5.
    # alpha = 1 - (n-1) * (o12+o21) / (n1*n2 + n2*n1) = 1 - 10*4/60 = 1/3.
    units = [[1, 1, 1], [1, 2, None], [2, 2, 2], [1, 1, 2], [2, None, None]]
    assert stats.krippendorff_alpha_nominal(units) == pytest.approx(1 / 3, abs=1e-9)


def test_alpha_perfect_and_chance_cases():
    # All units fully agree, two categories used: Do = 0, alpha = 1.
    assert stats.krippendorff_alpha_nominal([[1, 1, 1], [2, 2, 2], [1, 1, 1], [2, 2, 2]]) == pytest.approx(1.0)
    # Two raters, 2 units, values (1,2) and (2,1): o12 = o21 = 2, n = 4, n1 = n2 = 2.
    # alpha = 1 - 3 * 4 / (2*2*2) = 1 - 12/8 = -0.5.
    assert stats.krippendorff_alpha_nominal([[1, 2], [2, 1]]) == pytest.approx(-0.5, abs=1e-9)


def test_alpha_undefined_when_one_category_only():
    assert stats.krippendorff_alpha_nominal([[1, 1], [1, 1, 1]]) == "UNDEFINED"
    assert stats.krippendorff_alpha_nominal([[1, None], [None, 2]]) == "UNDEFINED"  # nothing pairable


# --------------------------------------------- prevalence, agreement figures

def test_agreement_figures_hand_worked():
    # Table 20/5/10/15, N=50.
    # raw agreement = 35/50 = 0.70.
    # positive agreement = 2a/(2a+b+c) = 40/55 = 0.727273.
    # negative agreement = 2d/(2d+b+c) = 30/45 = 0.666667.
    # prevalence = mean of the two readers' share of 1: (25/50 + 30/50)/2 = 0.55.
    A, B, _ = table(20, 5, 10, 15)
    assert stats.raw_agreement(A, B) == pytest.approx(0.70)
    assert stats.positive_agreement(A, B) == pytest.approx(40 / 55)
    assert stats.negative_agreement(A, B) == pytest.approx(30 / 45)
    assert stats.prevalence(A, B) == pytest.approx(0.55)


def test_rare_fault_high_raw_agreement_low_kappa():
    # a=10, b=25, c=25, d=940, N=1000. po = 950/1000 = 0.95.
    # A says 1: 35, B says 1: 35. pe = (35*35 + 965*965)/1e6 = (1225 + 931225)/1e6 = 0.93245.
    # kappa = (0.95 - 0.93245)/(1 - 0.93245) = 0.01755/0.06755 = 0.2598.
    # positive agreement = 20/(20+50) = 0.2857. Prevalence = 0.035.
    A, B, cl = table(10, 25, 25, 940)
    rep = stats.report(A, B, cl, seed=1, resamples=50)
    assert rep["raw_agreement"] == pytest.approx(0.95)
    assert rep["kappa"] == pytest.approx(0.01755 / 0.06755, abs=1e-6)
    assert rep["kappa"] < 0.3
    assert rep["positive_agreement"] == pytest.approx(20 / 70)
    assert rep["prevalence"] == pytest.approx(0.035)


# ------------------------------------------------ sensitivity, false alarms

def test_sensitivity_and_false_alarms_hand_worked():
    # Labels L1..L5, two units each. Reference (ref) and model (mod):
    #   L1: ref 1,1  mod 1,0     (2 faults, 1 found)
    #   L2: ref 1,0  mod 1,0     (1 fault, 1 found)
    #   L3: ref 0,0  mod 1,0     (clean label, 1 false alarm)
    #   L4: ref 0,0  mod 0,0     (clean label, none)
    #   L5: ref 0,0  mod 1,1     (clean label, 2 false alarms)
    # Faults in reference: 3. Found: 2. Sensitivity = 2 of 3.
    # Clean labels (no reference fault anywhere in the label): L3, L4, L5 = 3.
    # False alarms in clean labels: 1 + 0 + 2 = 3. Per clean label = 3/3 = 1.0.
    ref = [1, 1, 1, 0, 0, 0, 0, 0, 0, 0]
    mod = [1, 0, 1, 0, 1, 0, 0, 0, 1, 1]
    lab = ["L1", "L1", "L2", "L2", "L3", "L3", "L4", "L4", "L5", "L5"]
    out = stats.sensitivity_false_alarms(ref, mod, lab)
    assert out["sensitivity_found"] == 2
    assert out["sensitivity_of"] == 3
    assert out["sensitivity"] == pytest.approx(2 / 3)
    assert out["clean_labels"] == 3
    assert out["false_alarms"] == 3
    assert out["false_alarms_per_clean_label"] == pytest.approx(1.0)


def test_sensitivity_and_false_alarms_are_never_merged():
    out = stats.sensitivity_false_alarms([1, 0], [1, 1], ["a", "b"])
    assert "sensitivity" in out and "false_alarms_per_clean_label" in out
    for key in out:
        assert "accuracy" not in key and "combined" not in key and "f1" not in key.lower()


def test_sensitivity_no_faults_is_undefined_not_zero():
    out = stats.sensitivity_false_alarms([0, 0], [0, 1], ["a", "b"])
    assert out["sensitivity"] == "UNDEFINED"
    assert out["sensitivity_of"] == 0


# ---------------------------------------------------------------- bootstrap

def _planted_400():
    # a=190, d=190, b=10, c=10: po = 0.95, pe = 0.5, kappa = 0.90. N = 400.
    return table(190, 10, 10, 190)


def test_bootstrap_repeatable_and_seed_matters():
    A, B, cl = _planted_400()
    one = stats.bootstrap_interval(A, B, cl, seed=7)
    two = stats.bootstrap_interval(A, B, cl, seed=7)
    other = stats.bootstrap_interval(A, B, cl, seed=8)
    assert one == two
    assert one != other


def test_bootstrap_defaults_are_2000_and_fixed_seed():
    import inspect
    sig = inspect.signature(stats.bootstrap_interval)
    assert sig.parameters["resamples"].default == 2000
    assert isinstance(sig.parameters["seed"].default, int)


def test_bootstrap_interval_contains_point_estimate_and_is_sensible():
    # Normal approximation for kappa 0.9, N 400, balanced: SE ~ sqrt(po(1-po)/N)/(1-pe)
    # = sqrt(0.95*0.05/400)/0.5 = 0.01090/0.5 = 0.0218; 1.96*SE = 0.043.
    # The bootstrap half-width must be near that (0.03 to 0.06).
    A, B, cl = _planted_400()
    lo, hi = stats.bootstrap_interval(A, B, cl, seed=1)
    k = stats.kappa(A, B)
    assert lo < k < hi
    assert 0.03 < (hi - lo) / 2 < 0.06


def test_cluster_bootstrap_wider_than_independent():
    # 30 labels with 4 units each. Within a label every unit is the same:
    # 10 labels all (1,1), 10 labels all (0,0), 5 labels all (1,0), 5 labels all (0,1).
    # Same 120 rows; once with the label as cluster, once with one cluster per row.
    A, B, cl = [], [], []
    plan = [(1, 1, 10), (0, 0, 10), (1, 0, 5), (0, 1, 5)]
    lab = 0
    for x, y, nlab in plan:
        for _ in range(nlab):
            for _ in range(4):
                A.append(x)
                B.append(y)
                cl.append(lab)
            lab += 1
    lo_c, hi_c = stats.bootstrap_interval(A, B, cl, seed=3)
    lo_i, hi_i = stats.bootstrap_interval(A, B, list(range(len(A))), seed=3)
    assert (hi_c - lo_c) > 1.3 * (hi_i - lo_i)


def test_bootstrap_resamples_by_label_not_by_row():
    # Planted bad case: two labels. Label X holds 3 agreeing 1s. Label Y holds 3 agreeing 0s.
    # Resampling by label can give X,X (all 1: kappa undefined) or Y,Y (undefined) or X,Y.
    # Resampling by row would almost never give all-same rows (probability 2/64 per draw of 6).
    # Count of undefined replicates must therefore be about half of 2000 (1000 +- 150).
    A = [1, 1, 1, 0, 0, 0]
    B = list(A)
    cl = ["X", "X", "X", "Y", "Y", "Y"]
    info = stats.bootstrap_detail(A, B, cl, seed=5)
    assert 850 <= info["undefined"] <= 1150


# ------------------------------------------------------------------ verdict

def test_verdict_pass_needs_kappa_above_and_narrow_interval():
    assert stats.verdict(0.90, 0.05) == "PASS"
    assert stats.verdict(0.90, 0.12) == "PASS"          # at the limit is allowed
    assert stats.verdict(0.90, 0.121) == "NOT SHOWN: interval too wide"
    assert stats.verdict(0.80, 0.05) == "NOT SHOWN: kappa below target"   # equal is not above
    assert stats.verdict(0.70, 0.05) == "NOT SHOWN: kappa below target"
    assert stats.verdict(0.85, 0.05, target=0.9) == "NOT SHOWN: kappa below target"
    assert stats.verdict("UNDEFINED", 0.0) == "NOT SHOWN: kappa undefined"


def test_verdict_refuses_tiny_sample_with_kappa_080():
    # 20 units: a=9, d=9, b=1, c=1 -> po = 0.9, pe = 0.5, kappa = 0.80 exactly.
    A, B, cl = table(9, 1, 1, 9)
    assert stats.kappa(A, B) == pytest.approx(0.80)
    rep = stats.report(A, B, cl, seed=1)
    assert rep["verdict"] == "NOT SHOWN: interval too wide"
    assert rep["pilot"] == "PILOT"


def test_report_passes_on_large_planted_high_kappa():
    A, B, cl = _planted_400()
    rep = stats.report(A, B, cl, seed=1)
    assert rep["verdict"] == "PASS"
    assert rep["pilot"] == ""                            # 400 units, 400 labels
    for key in ("kappa", "ci_low", "ci_high", "half_width", "prevalence", "raw_agreement",
                "positive_agreement", "negative_agreement", "n_units", "n_labels"):
        assert key in rep


def test_pilot_marker_rules():
    # fewer than 100 units, or fewer than 40 labels -> PILOT
    A, B, _ = table(45, 5, 5, 45)                        # 100 units
    assert stats.pilot_marker(100, 40) == ""
    assert stats.pilot_marker(99, 40) == "PILOT"
    assert stats.pilot_marker(100, 39) == "PILOT"
    rep = stats.report(A, B, [i // 5 for i in range(100)], seed=1, resamples=100)   # 20 labels
    assert rep["pilot"] == "PILOT"


# ------------------------------------------------------------------- scorer

def rows(author, calls, labels, **extra):
    out = []
    for i, (c, lab) in enumerate(zip(calls, labels)):
        r = {"label": lab, "unit": f"u{i}", "author": author, "call": c}
        r.update(extra)
        out.append(r)
    return out


def _model_rows(calls, labels):
    return [{"label": lab, "unit": f"u{i}", "call": c} for i, (c, lab) in enumerate(zip(calls, labels))]


LABELS = ["L1", "L1", "L2", "L2", "L3", "L3", "L4", "L4"]
CALLS_A = [1, 0, 1, 0, 0, 0, 0, 0]
CALLS_B = [1, 0, 1, 0, 0, 0, 0, 1]
MODEL = [1, 0, 0, 0, 1, 0, 0, 0]


def test_score_with_two_readers_gives_figures():
    out = stats.score(rows("ann", CALLS_A, LABELS), rows("bob", CALLS_B, LABELS), _model_rows(MODEL, LABELS))
    assert out["readers"]["n_units"] == 8
    assert out["readers"]["pilot"] == "PILOT"
    assert "NOT REVIEWED" in out["note"]
    # One disagreement (u7) and no adjudicated answer: primary reference NOT SHOWN.
    assert out["units_readers_disagree"] == 1
    assert out["units_without_adjudicated_answer"] == 1
    assert out["model_vs_reference"].startswith("NOT SHOWN")
    # Agreed-only figures are kept, but only as a labelled secondary: 7 of 8 units.
    sec = out["agreed_only_secondary"]
    assert "secondary" in sec["label"].lower()
    assert sec["reference_units"] == 7
    # Reference faults: u0, u2 -> 2. Model found u0 only -> 1 of 2.
    assert sec["model_vs_reference"]["sensitivity_found"] == 1
    assert sec["model_vs_reference"]["sensitivity_of"] == 2
    assert "accuracy" not in json.dumps(out).lower()


# Hand-worked table: dropping reader disagreements raises model kappa.
# 20 units. Readers agree on 16: reference 8 fault / 8 clean.
#   Model on those 16: both 1 = 7, ref 1 model 0 = 1, ref 0 model 1 = 1, both 0 = 7.
#   Agreed-only: po = 14/16 = 0.875; pe = (8*8 + 8*8)/16^2 = 0.5;
#   kappa = (0.875 - 0.5)/(1 - 0.5) = 0.75.
# Readers disagree on 4 hard units (h0..h3). Adjudicated: h0 = 1, h1 = 1, h2 = 0, h3 = 0.
#   Model says h0 = 0, h1 = 0, h2 = 1, h3 = 1: all four wrong.
#   Full reference (20): both 1 = 7, ref 1 model 0 = 1 + 2 = 3, ref 0 model 1 = 1 + 2 = 3, both 0 = 7.
#   po = 14/20 = 0.70; ref faults 10, model faults 10; pe = (10*10 + 10*10)/400 = 0.50;
#   kappa = (0.70 - 0.50)/(1 - 0.50) = 0.40.
def _hard_case(adjudicated="full"):
    easy_ref = [1] * 8 + [0] * 8
    easy_model = [1] * 7 + [0] + [1] + [0] * 7
    hard_a = [1, 1, 0, 0]
    hard_b = [0, 0, 1, 1]
    hard_adj = [1, 1, 0, 0]
    hard_model = [0, 0, 1, 1]
    calls_a = easy_ref + hard_a
    calls_b = easy_ref + hard_b
    labels = [f"L{i // 2}" for i in range(20)]
    ra, rb = rows("ann", calls_a, labels), rows("bob", calls_b, labels)
    model = _model_rows(easy_model + hard_model, labels)
    adj = [{"label": labels[16 + i], "unit": f"u{16 + i}", "call": hard_adj[i], "decided_by": "carla"}
           for i in range(4)]
    if adjudicated == "none":
        adj = None
    elif adjudicated == "partial":
        adj = adj[:3]
    return ra, rb, model, adj


def test_adjudicated_reference_differs_from_agreed_only():
    ra, rb, model, adj = _hard_case()
    out = stats.score(ra, rb, model, adj)
    assert out["units_readers_disagree"] == 4
    assert out["units_without_adjudicated_answer"] == 0
    primary = out["model_vs_reference"]
    assert primary["kappa"] == pytest.approx(0.40, abs=1e-9)
    assert primary["reference_units"] == 20
    sec = out["agreed_only_secondary"]
    assert "secondary" in sec["label"].lower()
    assert sec["model_kappa"] == pytest.approx(0.75, abs=1e-9)
    assert sec["model_kappa"] > primary["kappa"]


@pytest.mark.parametrize("case", ["none", "partial"])
def test_missing_adjudicated_answer_gives_not_shown(case):
    ra, rb, model, adj = _hard_case(case)
    out = stats.score(ra, rb, model, adj)
    assert out["model_vs_reference"].startswith("NOT SHOWN")
    assert out["units_readers_disagree"] == 4
    assert out["units_without_adjudicated_answer"] == (4 if case == "none" else 1)
    assert "agreed_only_secondary" in out


def test_adjudicated_answer_needs_who_decided():
    ra, rb, model, adj = _hard_case()
    del adj[0]["decided_by"]
    out = stats.score(ra, rb, model, adj)
    assert out["units_without_adjudicated_answer"] == 1
    assert out["model_vs_reference"].startswith("NOT SHOWN")


def test_adjudicated_row_for_unknown_unit_refused():
    ra, rb, model, adj = _hard_case()
    adj.append({"label": "Lx", "unit": "nope", "call": 1, "decided_by": "carla"})
    with pytest.raises(stats.ScorerError):
        stats.score(ra, rb, model, adj)


def test_no_disagreements_needs_no_adjudication():
    labels = LABELS
    out = stats.score(rows("ann", CALLS_A, labels), rows("bob", CALLS_A, labels), _model_rows(MODEL, labels))
    assert out["units_readers_disagree"] == 0
    assert out["model_vs_reference"]["sensitivity_of"] == 2


@pytest.mark.parametrize("which", ["a", "b"])
def test_score_missing_reader_prints_nothing_and_errors(which):
    a = rows("ann", CALLS_A, LABELS)
    b = rows("bob", CALLS_B, LABELS)
    args = {"a": (None, b), "b": (a, None)}[which]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        with pytest.raises(stats.ScorerError):
            stats.score(args[0], args[1], _model_rows(MODEL, LABELS))
    assert buf.getvalue() == ""


def test_score_empty_reader_refused():
    with pytest.raises(stats.ScorerError):
        stats.score([], rows("bob", CALLS_B, LABELS), _model_rows(MODEL, LABELS))


def test_score_refuses_model_field_in_reader_rows():
    for field in ("model", "model_call", "model_output"):
        a = rows("ann", CALLS_A, LABELS, **{field: 1})
        with pytest.raises(stats.ScorerError, match="model"):
            stats.score(a, rows("bob", CALLS_B, LABELS), _model_rows(MODEL, LABELS))
    # also when only the second file holds it, and only in one row
    b = rows("bob", CALLS_B, LABELS)
    b[3]["model_finding"] = "x"
    with pytest.raises(stats.ScorerError, match="model"):
        stats.score(rows("ann", CALLS_A, LABELS), b, _model_rows(MODEL, LABELS))


def test_score_refuses_one_author_only():
    # same author in both files
    with pytest.raises(stats.ScorerError, match="author"):
        stats.score(rows("ann", CALLS_A, LABELS), rows("ann", CALLS_B, LABELS), _model_rows(MODEL, LABELS))
    # no author named at all
    b = rows("bob", CALLS_B, LABELS)
    for r in b:
        del r["author"]
    with pytest.raises(stats.ScorerError, match="author"):
        stats.score(rows("ann", CALLS_A, LABELS), b, _model_rows(MODEL, LABELS))
    # one file mixes two authors
    a = rows("ann", CALLS_A, LABELS)
    a[0]["author"] = "bob"
    with pytest.raises(stats.ScorerError, match="author"):
        stats.score(a, rows("bob", CALLS_B, LABELS), _model_rows(MODEL, LABELS))


def test_score_refuses_units_that_do_not_match():
    b = rows("bob", CALLS_B, LABELS)[:-1]
    with pytest.raises(stats.ScorerError):
        stats.score(rows("ann", CALLS_A, LABELS), b, _model_rows(MODEL, LABELS))


def test_score_refuses_missing_model_rows():
    with pytest.raises(stats.ScorerError):
        stats.score(rows("ann", CALLS_A, LABELS), rows("bob", CALLS_B, LABELS), None)


def test_cli_one_reader_file_exits_with_error_and_no_figure(tmp_path):
    a = tmp_path / "a.json"
    m = tmp_path / "m.json"
    a.write_text(json.dumps(rows("ann", CALLS_A, LABELS)), encoding="utf-8")
    m.write_text(json.dumps(_model_rows(MODEL, LABELS)), encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with pytest.raises(SystemExit) as ex:
            stats.main([str(a), str(m)])
    assert ex.value.code not in (0, None)
    assert out.getvalue() == ""
    assert err.getvalue() != ""


def test_cli_full_run_prints_json(tmp_path):
    a, b, m = tmp_path / "a.json", tmp_path / "b.json", tmp_path / "m.json"
    a.write_text(json.dumps(rows("ann", CALLS_A, LABELS)), encoding="utf-8")
    b.write_text(json.dumps(rows("bob", CALLS_B, LABELS)), encoding="utf-8")
    m.write_text(json.dumps(_model_rows(MODEL, LABELS)), encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert stats.main([str(a), str(b), str(m)]) == 0
    assert json.loads(out.getvalue())["readers"]["pilot"] == "PILOT"


# ------------------------------------------------------------ housekeeping

def test_stats_imports_only_stdlib():
    import re
    src = (ROOT / "stats.py").read_text(encoding="utf-8")
    allowed = set(sys.stdlib_module_names)
    for m in re.findall(r"^\s*(?:import|from)\s+([a-zA-Z_]\w*)", src, re.M):
        assert m in allowed, m


def test_every_worked_example_carries_its_working():
    # Each test named *hand_worked* must hold at least 3 comment lines before its first assert.
    text = Path(__file__).read_text(encoding="utf-8")
    parts = text.split(chr(10) + "def test_")[1:]
    found = 0
    for part in parts:
        if "hand_worked" not in part.split("(")[0]:
            continue
        found += 1
        head = part.split("assert")[0]
        assert head.count("    # ") >= 3, part.split("(")[0]
    assert found >= 6
