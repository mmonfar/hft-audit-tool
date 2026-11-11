"""Agreement statistics and scorer for the audit tool. Standard library only.

No network, no model call. Reads only the files you pass in.
Spec: docs/specs/stats.md.
"""
import json
import random
import sys

UNDEFINED = "UNDEFINED"
DEFAULT_SEED = 20261109
DEFAULT_RESAMPLES = 2000
DEFAULT_TARGET = 0.8
MAX_HALF_WIDTH = 0.12
MIN_UNITS = 100
MIN_LABELS = 40


class ScorerError(Exception):
    """The scorer refuses to give a figure."""


# ------------------------------------------------------------------ helpers

def _check_pair(a, b):
    if len(a) != len(b):
        raise ValueError("the two lists must have the same length")
    if not a:
        raise ValueError("no units")


def _categories(a, b, order=None):
    if order is not None:
        return list(order)
    return sorted(set(a) | set(b), key=lambda v: (str(type(v)), v))


def _matrix(a, b, cats):
    idx = {c: i for i, c in enumerate(cats)}
    k = len(cats)
    m = [0] * (k * k)
    for x, y in zip(a, b):
        m[idx[x] * k + idx[y]] += 1
    return m


def _weights(k, kind):
    w = [0.0] * (k * k)
    for i in range(k):
        for j in range(k):
            if kind == "nominal":
                w[i * k + j] = 0.0 if i == j else 1.0
            else:
                d = abs(i - j) / (k - 1) if k > 1 else 0.0
                w[i * k + j] = d if kind == "linear" else d * d
    return w


def _kappa_from_matrix(m, k, w):
    n = sum(m)
    if n == 0:
        return UNDEFINED
    rows = [sum(m[i * k:(i + 1) * k]) for i in range(k)]
    cols = [sum(m[i * k + j] for i in range(k)) for j in range(k)]
    obs = sum(w[t] * m[t] for t in range(k * k)) / n
    exp = sum(w[i * k + j] * rows[i] * cols[j] for i in range(k) for j in range(k)) / (n * n)
    if exp == 0:
        return UNDEFINED
    return 1.0 - obs / exp


# -------------------------------------------------------------------- kappa

def kappa(a, b):
    """Cohen's kappa for any number of categories. Returns UNDEFINED if chance agreement is 1."""
    _check_pair(a, b)
    cats = _categories(a, b)
    return _kappa_from_matrix(_matrix(a, b, cats), len(cats), _weights(len(cats), "nominal"))


def weighted_kappa(a, b, weights="linear", order=None):
    """Weighted kappa for ordered categories. weights: 'linear' or 'quadratic'."""
    if weights not in ("linear", "quadratic"):
        raise ValueError("weights must be 'linear' or 'quadratic'")
    _check_pair(a, b)
    cats = _categories(a, b, order)
    return _kappa_from_matrix(_matrix(a, b, cats), len(cats), _weights(len(cats), weights))


def krippendorff_alpha_nominal(units):
    """units: list of lists, one list per unit, one value per rater, None = missing.
    Units with fewer than 2 values are left out. Returns UNDEFINED if nothing varies."""
    o = {}
    for u in units:
        vals = [v for v in u if v is not None]
        m = len(vals)
        if m < 2:
            continue
        for i, c in enumerate(vals):
            for j, k_ in enumerate(vals):
                if i != j:
                    o[(c, k_)] = o.get((c, k_), 0.0) + 1.0 / (m - 1)
    n = sum(o.values())
    if n < 2:
        return UNDEFINED
    nc = {}
    for (c, _), v in o.items():
        nc[c] = nc.get(c, 0.0) + v
    denom = n * n - sum(v * v for v in nc.values())      # sum over c != k of n_c * n_k
    if denom == 0:
        return UNDEFINED
    d_obs = sum(v for (c, k_), v in o.items() if c != k_)
    return 1.0 - (n - 1) * d_obs / denom


# ------------------------------------------------- simple agreement figures

def raw_agreement(a, b):
    _check_pair(a, b)
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


def _cells(a, b, positive=1):
    _check_pair(a, b)
    p = [x == positive for x in a]
    q = [y == positive for y in b]
    both = sum(1 for x, y in zip(p, q) if x and y)
    only_a = sum(1 for x, y in zip(p, q) if x and not y)
    only_b = sum(1 for x, y in zip(p, q) if y and not x)
    neither = len(a) - both - only_a - only_b
    return both, only_a, only_b, neither


def positive_agreement(a, b, positive=1):
    both, ba, bb, _ = _cells(a, b, positive)
    d = 2 * both + ba + bb
    return UNDEFINED if d == 0 else 2 * both / d


def negative_agreement(a, b, positive=1):
    _, ba, bb, neither = _cells(a, b, positive)
    d = 2 * neither + ba + bb
    return UNDEFINED if d == 0 else 2 * neither / d


def prevalence(a, b, positive=1):
    """Mean of the two readers' share of 'fault present'."""
    both, ba, bb, _ = _cells(a, b, positive)
    n = len(a)
    return ((both + ba) / n + (both + bb) / n) / 2


def sensitivity_false_alarms(reference, model, labels):
    """Two separate figures. Never merged.
    Sensitivity: reference faults the model also marked, x of n.
    False alarms per clean label: model marks on units in labels with no reference fault,
    divided by the number of such clean labels."""
    if not (len(reference) == len(model) == len(labels)):
        raise ValueError("lists must have the same length")
    faults = sum(1 for r in reference if r == 1)
    found = sum(1 for r, m in zip(reference, model) if r == 1 and m == 1)
    dirty = {lab for r, lab in zip(reference, labels) if r == 1}
    clean = set(labels) - dirty
    alarms = sum(1 for r, m, lab in zip(reference, model, labels) if lab in clean and m == 1)
    return {
        "sensitivity_found": found,
        "sensitivity_of": faults,
        "sensitivity": UNDEFINED if faults == 0 else found / faults,
        "clean_labels": len(clean),
        "false_alarms": alarms,
        "false_alarms_per_clean_label": UNDEFINED if not clean else alarms / len(clean),
    }


# ---------------------------------------------------------------- bootstrap

def bootstrap_detail(a, b, clusters, seed=DEFAULT_SEED, resamples=DEFAULT_RESAMPLES):
    """Cluster bootstrap of kappa: resample whole labels with replacement."""
    _check_pair(a, b)
    if len(clusters) != len(a):
        raise ValueError("one cluster id per unit")
    cats = _categories(a, b)
    k = len(cats)
    idx = {c: i for i, c in enumerate(cats)}
    per = {}
    for x, y, c in zip(a, b, clusters):
        m = per.setdefault(c, [0] * (k * k))
        m[idx[x] * k + idx[y]] += 1
    tables = [per[c] for c in sorted(per, key=str)]
    w = _weights(k, "nominal")
    rng = random.Random(seed)
    n_lab = len(tables)
    values = []
    undefined = 0
    for _ in range(resamples):
        tot = [0] * (k * k)
        for t in rng.choices(range(n_lab), k=n_lab):
            row = tables[t]
            for j in range(k * k):
                tot[j] += row[j]
        v = _kappa_from_matrix(tot, k, w)
        if v == UNDEFINED:
            undefined += 1
        else:
            values.append(v)
    values.sort()
    return {"values": values, "undefined": undefined, "resamples": resamples}


def bootstrap_interval(a, b, clusters, seed=DEFAULT_SEED, resamples=DEFAULT_RESAMPLES):
    """95 percent percentile interval (low, high). None if too few usable resamples."""
    info = bootstrap_detail(a, b, clusters, seed, resamples)
    v = info["values"]
    if len(v) < max(10, resamples // 2):
        return None
    lo = v[int(round(0.025 * (len(v) - 1)))]
    hi = v[int(round(0.975 * (len(v) - 1)))]
    return (lo, hi)


# ------------------------------------------------------- verdict and report

def pilot_marker(n_units, n_labels):
    return "PILOT" if n_units < MIN_UNITS or n_labels < MIN_LABELS else ""


def verdict(kappa_value, half_width, target=DEFAULT_TARGET, max_half_width=MAX_HALF_WIDTH):
    if kappa_value == UNDEFINED:
        return "NOT SHOWN: kappa undefined"
    if half_width is None or half_width > max_half_width:
        return "NOT SHOWN: interval too wide"
    if not kappa_value > target:
        return "NOT SHOWN: kappa below target"
    return "PASS"


def report(a, b, clusters, seed=DEFAULT_SEED, resamples=DEFAULT_RESAMPLES, target=DEFAULT_TARGET):
    k = kappa(a, b)
    iv = bootstrap_interval(a, b, clusters, seed, resamples)
    half = None if iv is None else (iv[1] - iv[0]) / 2
    n_labels = len(set(clusters))
    return {
        "kappa": k,
        "ci_low": None if iv is None else iv[0],
        "ci_high": None if iv is None else iv[1],
        "half_width": half,
        "prevalence": prevalence(a, b),
        "raw_agreement": raw_agreement(a, b),
        "positive_agreement": positive_agreement(a, b),
        "negative_agreement": negative_agreement(a, b),
        "n_units": len(a),
        "n_labels": n_labels,
        "pilot": pilot_marker(len(a), n_labels),
        "target": target,
        "verdict": verdict(k, half, target),
    }


# ------------------------------------------------------------------- scorer

def _reader_rows(rows, name):
    if not rows:
        raise ScorerError(f"{name}: reader input missing or empty. No figure given.")
    authors = set()
    for r in rows:
        for key in r:
            if "model" in str(key).lower():
                raise ScorerError(f"{name}: reader rows must not hold a model field ({key}).")
        author = r.get("author")
        if not author:
            raise ScorerError(f"{name}: every row must name its author.")
        authors.add(author)
    if len(authors) != 1:
        raise ScorerError(f"{name}: one file must hold one author, found {len(authors)}.")
    return authors.pop()


def _by_unit(rows, name):
    out = {}
    for r in rows:
        key = (r["label"], r["unit"])
        if key in out:
            raise ScorerError(f"{name}: unit {key} appears twice.")
        out[key] = r["call"]
    return out


def _adjudicated(rows, disputed):
    """Map unit -> adjudicated call. A row without a call (0 or 1) or without
    `decided_by` does not count as an answer. A row for a unit that is not in dispute is refused."""
    out = {}
    for r in rows or []:
        key = (r.get("label"), r.get("unit"))
        if key not in disputed:
            raise ScorerError(f"adjudicated answer for {key}: not a unit the readers disagree on.")
        if key in out:
            raise ScorerError(f"adjudicated: unit {key} appears twice.")
        if r.get("call") in (0, 1) and r.get("decided_by"):
            out[key] = r["call"]
    return out


def score(reader_a, reader_b, model, adjudicated=None):
    """Reader agreement, then model against the reference.
    Primary reference: reader agreement plus a human adjudicated answer (rows with label, unit,
    call, decided_by) for every unit where the readers differ. If any answer is missing the
    primary figure is "NOT SHOWN". The agreed-only figure is a labelled secondary.
    Raises ScorerError, and returns no figure, unless both reader inputs are good."""
    author_a = _reader_rows(reader_a, "reader A")
    author_b = _reader_rows(reader_b, "reader B")
    if author_a == author_b:
        raise ScorerError("both reader files name the same author. Two authors are needed.")
    if not model:
        raise ScorerError("model rows missing.")
    ua = _by_unit(reader_a, "reader A")
    ub = _by_unit(reader_b, "reader B")
    um = _by_unit(model, "model")
    if set(ua) != set(ub):
        raise ScorerError("the two reader files do not hold the same units.")
    if set(um) != set(ua):
        raise ScorerError("model rows do not match the reader units.")
    keys = sorted(ua, key=str)
    a = [ua[k] for k in keys]
    b = [ub[k] for k in keys]
    readers = report(a, b, [k[0] for k in keys])
    agreed = [k for k in keys if ua[k] == ub[k]]
    disputed = {k for k in keys if ua[k] != ub[k]}
    adj = _adjudicated(adjudicated, disputed)
    missing = len(disputed) - len(adj)

    def against(unit_keys, ref):
        r = [ref[k] for k in unit_keys]
        m = [um[k] for k in unit_keys]
        return r, m

    ag_ref, ag_model = against(agreed, ua)
    out = {
        "note": "NOT REVIEWED: a person must read every item.",
        "readers": readers,
        "units_readers_disagree": len(disputed),
        "units_without_adjudicated_answer": missing,
        "agreed_only_secondary": {
            "label": "Secondary: units where both readers agree. Disagreements are left out, so this can look better than the primary.",
            "reference_units": len(agreed),
            "model_kappa": kappa(ag_ref, ag_model) if agreed else UNDEFINED,
            "model_vs_reference": sensitivity_false_alarms(ag_ref, ag_model, [k[0] for k in agreed]),
        },
    }
    if missing:
        out["model_vs_reference"] = (
            f"NOT SHOWN: {missing} of {len(disputed)} disagreements have no adjudicated answer")
    else:
        ref = dict(ua)
        ref.update(adj)
        r, m = against(keys, ref)
        fig = sensitivity_false_alarms(r, m, [k[0] for k in keys])
        fig["kappa"] = kappa(r, m)
        fig["reference_units"] = len(keys)
        fig["reference"] = "Primary: readers agree, or a human adjudicated answer (decided_by stored)."
        fig["adjudicated_by"] = sorted({row["decided_by"] for row in adjudicated or []})
        out["model_vs_reference"] = fig
    if readers["kappa"] == UNDEFINED or readers["kappa"] <= readers["target"]:
        out["readers_note"] = "Reader agreement is not above target. Fix the marking rules first."
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        sys.stderr.write("usage: stats.py reader_a.json reader_b.json model.json (all three needed)\n")
        raise SystemExit(2)
    try:
        data = []
        for p in argv:
            with open(p, encoding="utf-8") as f:
                data.append(json.load(f))
        result = score(*data)
    except (ScorerError, OSError, ValueError, KeyError) as e:
        sys.stderr.write(f"ERROR: {e}\n")
        raise SystemExit(2)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
