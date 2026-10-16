"""Typed field-level comparison of predicted vs. expected extraction JSON.

The public entry point is ``compare(expected, predicted, config)`` which returns a
flat list of ``FieldResult`` leaves — one per scalar position in the expected/
predicted trees — each scored in [0, 1]. Aggregation lives in score.py.

Scoring philosophy: a wrong value is worse than a missing one, and predicting
``null`` where the document truly has nothing is a *correct* act (the skill's
"never guess" rule). So both-null leaves score 1.0 but are flagged trivial so
precision/recall can exclude them.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

MISSING = object()  # a key absent from the JSON entirely (vs. present-but-null)


@dataclass
class FieldResult:
    path: str
    expected: Any
    predicted: Any
    score: float
    status: str  # correct | partial | incorrect | missing | spurious | both_null
    comparator: str
    weight: float = 1.0

    @property
    def trivial(self) -> bool:
        return self.status == "both_null"


@dataclass
class CompareConfig:
    """Per-case comparison configuration (from case.yaml `scoring:`).

    fields: map of path glob -> options, e.g.
        "line_items[].description": {comparator: "fuzzy", threshold: 0.85}
        "total": {comparator: "number", abs_tol: 0.01, weight: 3}
        "line_items": {align_keys: ["sku"]}
    """

    fields: dict[str, dict] = field(default_factory=dict)

    def options_for(self, path: str) -> dict:
        # Normalize list indices to [] so one rule covers all items.
        generic = re.sub(r"\[\d+\]", "[]", path)
        merged: dict = {}
        for pattern, opts in self.fields.items():
            if pattern == generic or pattern == path:
                merged.update(opts)
        return merged


# ---------------------------------------------------------------- scalar compare

_WS = re.compile(r"\s+")


def norm_string(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s))
    return _WS.sub(" ", s).strip().casefold()


_NUM_CLEAN = re.compile(r"[,$€£\s]")


def try_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = _NUM_CLEAN.sub("", v)
        neg = s.startswith("(") and s.endswith(")")
        if neg:
            s = s[1:-1]
        try:
            n = float(s)
        except ValueError:
            return None
        return -n if neg else n
    return None


_DATE_PATTERNS = [
    re.compile(r"^(\d{4})-(\d{2})-(\d{2})"),  # ISO (possibly with time suffix)
]


def try_date(v: Any) -> str | None:
    if not isinstance(v, str):
        return None
    for pat in _DATE_PATTERNS:
        m = pat.match(v.strip())
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def scalar_score(expected: Any, predicted: Any, opts: dict) -> tuple[float, str]:
    """Return (score, comparator_name) for two non-null scalars."""
    comp = opts.get("comparator")

    if comp == "number" or (comp is None and try_number(expected) is not None):
        e, p = try_number(expected), try_number(predicted)
        if e is None or p is None:
            return 0.0, "number"
        abs_tol = float(opts.get("abs_tol", 1e-9))
        rel_tol = float(opts.get("rel_tol", 1e-9))
        ok = abs(e - p) <= max(abs_tol, rel_tol * max(abs(e), abs(p)))
        return (1.0 if ok else 0.0), "number"

    if comp == "date" or (comp is None and try_date(expected) is not None):
        e, p = try_date(expected), try_date(predicted)
        return (1.0 if e is not None and e == p else 0.0), "date"

    if comp == "fuzzy":
        e, p = norm_string(expected), norm_string(predicted)
        if e == p:
            return 1.0, "fuzzy"
        ratio = SequenceMatcher(None, e, p).ratio()
        threshold = float(opts.get("threshold", 0.85))
        return (ratio if ratio >= threshold else 0.0), "fuzzy"

    if isinstance(expected, bool) or isinstance(predicted, bool):
        return (1.0 if expected is predicted else 0.0), "bool"

    return (1.0 if norm_string(expected) == norm_string(predicted) else 0.0), "string"


# ------------------------------------------------------------------- tree walk


def compare(expected: Any, predicted: Any, config: CompareConfig | None = None) -> list[FieldResult]:
    return _walk(expected, predicted, "", config or CompareConfig())


def _leaf(path: str, e: Any, p: Any, score: float, status: str, comp: str, cfg: CompareConfig) -> FieldResult:
    weight = float(cfg.options_for(path).get("weight", 1.0))
    return FieldResult(path or "/", e, p, score, status, comp, weight)


def _walk(e: Any, p: Any, path: str, cfg: CompareConfig) -> list[FieldResult]:
    e_null = e is None or e is MISSING
    p_null = p is None or p is MISSING

    if e_null and p_null:
        return [_leaf(path, None, None, 1.0, "both_null", "null", cfg)]
    if e_null:
        return _null_side(p, path, cfg, spurious=True)
    if p_null:
        return _null_side(e, path, cfg, spurious=False)

    if isinstance(e, dict):
        if not isinstance(p, dict):
            return _null_side(e, path, cfg, spurious=False)
        results: list[FieldResult] = []
        for key in e.keys() | p.keys():
            results += _walk(e.get(key, MISSING), p.get(key, MISSING), f"{path}.{key}" if path else key, cfg)
        return results

    if isinstance(e, list):
        if not isinstance(p, list):
            return _null_side(e, path, cfg, spurious=False)
        if any(isinstance(x, (dict, list)) for x in e + p):
            return _compare_object_lists(e, p, path, cfg)
        return _compare_scalar_lists(e, p, path, cfg)

    if isinstance(p, (dict, list)):
        return [_leaf(path, e, p, 0.0, "incorrect", "type", cfg)]

    score, comp = scalar_score(e, p, cfg.options_for(path))
    status = "correct" if score >= 1.0 else ("partial" if score > 0 else "incorrect")
    return [_leaf(path, e, p, score, status, comp, cfg)]


def _null_side(value: Any, path: str, cfg: CompareConfig, *, spurious: bool) -> list[FieldResult]:
    """One side is null/missing: emit a zero-score leaf per scalar on the other side."""
    status = "spurious" if spurious else "missing"
    if isinstance(value, dict):
        out: list[FieldResult] = []
        for k, v in value.items():
            out += _null_side(v, f"{path}.{k}" if path else k, cfg, spurious=spurious)
        return out or [_leaf(path, None if spurious else value, value if spurious else None, 0.0, status, "null", cfg)]
    if isinstance(value, list):
        out = []
        for i, v in enumerate(value):
            out += _null_side(v, f"{path}[{i}]", cfg, spurious=spurious)
        return out or [_leaf(path, None if spurious else value, value if spurious else None, 0.0, status, "null", cfg)]
    if value is None or value is MISSING:
        return [_leaf(path, None, None, 1.0, "both_null", "null", cfg)]
    e, p = (None, value) if spurious else (value, None)
    return [_leaf(path, e, p, 0.0, status, "null", cfg)]


def _compare_scalar_lists(e: list, p: list, path: str, cfg: CompareConfig) -> list[FieldResult]:
    """Order-insensitive multiset match of scalar lists."""
    # Items are compared with item-level options ("foo[]" rules), not list-level.
    opts = {**cfg.options_for(path), **cfg.options_for(f"{path}[]")}
    remaining = list(p)
    results: list[FieldResult] = []
    for i, ev in enumerate(e):
        best_j, best_score, best_comp = -1, 0.0, "string"
        for j, pv in enumerate(remaining):
            s, comp = scalar_score(ev, pv, opts)
            if s > best_score:
                best_j, best_score, best_comp = j, s, comp
        if best_j >= 0 and best_score > 0:
            pv = remaining.pop(best_j)
            status = "correct" if best_score >= 1.0 else "partial"
            results.append(_leaf(f"{path}[{i}]", ev, pv, best_score, status, best_comp, cfg))
        else:
            results.append(_leaf(f"{path}[{i}]", ev, None, 0.0, "missing", "list", cfg))
    for pv in remaining:
        results.append(_leaf(f"{path}[+]", None, pv, 0.0, "spurious", "list", cfg))
    return results


def _item_similarity(e_item: Any, p_item: Any, path: str, cfg: CompareConfig) -> float:
    leaves = _walk(e_item, p_item, path, cfg)
    scored = [l for l in leaves if not l.trivial]
    if not scored:
        return 1.0
    return sum(l.score for l in scored) / len(scored)


def _compare_object_lists(e: list, p: list, path: str, cfg: CompareConfig) -> list[FieldResult]:
    """Align items (by configured keys, else greedy best-score) then score pairs."""
    opts = cfg.options_for(path)
    align_keys: list[str] = opts.get("align_keys", [])
    min_sim = float(opts.get("min_similarity", 0.3))

    pairs: list[tuple[int, int]] = []
    used_p: set[int] = set()

    if align_keys:
        def key_of(item: Any) -> tuple:
            if not isinstance(item, dict):
                return (norm_string(item),)
            return tuple(norm_string(item.get(k, "")) if item.get(k) is not None else "" for k in align_keys)

        p_by_key: dict[tuple, list[int]] = {}
        for j, pv in enumerate(p):
            p_by_key.setdefault(key_of(pv), []).append(j)
        for i, ev in enumerate(e):
            js = p_by_key.get(key_of(ev), [])
            j = next((j for j in js if j not in used_p), None)
            if j is not None:
                pairs.append((i, j))
                used_p.add(j)
    else:
        sims = sorted(
            ((_item_similarity(ev, pv, f"{path}[{i}]", cfg), i, j) for i, ev in enumerate(e) for j, pv in enumerate(p)),
            key=lambda t: -t[0],
        )
        used_e: set[int] = set()
        for sim, i, j in sims:
            if sim < min_sim:
                break
            if i in used_e or j in used_p:
                continue
            pairs.append((i, j))
            used_e.add(i)
            used_p.add(j)

    results: list[FieldResult] = []
    matched_e = {i for i, _ in pairs}
    for i, j in pairs:
        results += _walk(e[i], p[j], f"{path}[{i}]", cfg)
    for i, ev in enumerate(e):
        if i not in matched_e:
            results += _null_side(ev, f"{path}[{i}]", cfg, spurious=False)
    for j, pv in enumerate(p):
        if j not in used_p:
            results += _null_side(pv, f"{path}[+]", cfg, spurious=True)
    return results
