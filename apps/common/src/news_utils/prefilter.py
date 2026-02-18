from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Pattern, Tuple

try:
    import joblib  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    joblib = None


# ---- Defaults (used when env overrides are absent) -------------------------
DEFAULT_MATERIAL_REGEXES: List[str] = [
    r"\b(acquire|acquisition|merger|merge|buy(?:s|out)?|takeover)\b",
    r"\b(earnings|EPS|revenue|guidance|outlook|forecast|results)\b",
    r"\b(bankruptcy|chapter\s?11|restructuring)\b",
    r"\b(SEC|FTC|DOJ|FDA|FAA|EPA|CPSC)\b",
    r"\b(recall|halt(?:s|ing)?|suspend(?:s|ing)?|probe|investigation)\b",
    r"\b(appoints?|resigns?|steps\s+down|CEO|CFO|CTO|Chairman)\b",
    r"\b(contract|order|award|deal)\b",
    r"\b(downgrade|upgrade|price\s*target)\b",
]

DEFAULT_RUMOR_REGEX: str = (
    r"\b(report(?:edly)?|rumor(?:s|ed)?|may|could|considering|weighing|exploring)\b"
)

MONEY_RE = re.compile(r"\$\s?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)(?:\s*(B|bn|M|m|K|k))?", re.I)
PCT_RE = re.compile(r"([+\-]?[0-9]+(?:\.[0-9]+)?)\s?%")


def _parse_regex_list_env(var_name: str, defaults: List[str]) -> List[Pattern]:
    """Parse an env var into a list of compiled regex patterns.

    Supports:
      - JSON array of regex strings: ["\\b(foo|bar)\\b", "baz"]
      - String separated by ';;': "\\bfoo\\b;;\\bbar\\b"
      - Newline‑separated patterns
    Returns defaults if env is not set or invalid. Invalid entries are skipped.
    """
    raw = os.environ.get(var_name)
    patterns: List[str] = []
    if raw:
        s = raw.strip()
        # Try JSON first
        if s.startswith("["):
            try:
                arr = json.loads(s)
                if isinstance(arr, list):
                    patterns = [str(x) for x in arr if isinstance(x, (str, int, float))]
            except Exception:
                patterns = []
        # Fallback to ';;' or newline separation
        if not patterns:
            if ";;" in s:
                patterns = [p.strip() for p in s.split(";;") if p.strip()]
            elif "\n" in s:
                patterns = [p.strip() for p in s.splitlines() if p.strip()]
            else:
                # Single pattern provided; use as-is
                patterns = [s]
    if not patterns:
        patterns = list(defaults)
    out: List[Pattern] = []
    for p in patterns:
        try:
            out.append(re.compile(p, re.I))
        except Exception:
            # Skip invalid patterns silently
            continue
    return out


def _load_rumor_regex() -> Pattern:
    """Load rumor regex from env.

    - NEWS_RUMOR_REGEX: full regex pattern (preferred)
    - NEWS_RUMOR_WORDS: comma/space‑separated tokens -> compiled into \b(?:... )\b
    Falls back to DEFAULT_RUMOR_REGEX.
    """
    rx = os.environ.get("NEWS_RUMOR_REGEX")
    if rx:
        try:
            return re.compile(rx, re.I)
        except Exception:
            pass
    words = os.environ.get("NEWS_RUMOR_WORDS")
    if words:
        toks = [w.strip() for w in re.split(r"[,\s]+", words) if w.strip()]
        if toks:
            pat = r"\b(?:" + "|".join(re.escape(t) for t in toks) + r")\b"
            try:
                return re.compile(pat, re.I)
            except Exception:
                pass
    return re.compile(DEFAULT_RUMOR_REGEX, re.I)


# ---- Tier parsing helpers ---------------------------------------------------
DEFAULT_AMOUNT_TIERS: List[Tuple[float, float]] = [
    (500_000_000.0, 1.0),
    (100_000_000.0, 0.8),
    (25_000_000.0, 0.6),
    (5_000_000.0, 0.4),
]

DEFAULT_PCT_TIERS: List[Tuple[float, float]] = [
    (20.0, 0.8),
    (10.0, 0.6),
    (5.0, 0.4),
]


def _parse_amount_with_units(s: str) -> Optional[float]:
    try:
        s = (s or "").strip().replace(",", "")
        m = re.match(r"^([0-9]+(?:\.[0-9]+)?)([KkMmBb]|bn)?$", s)
        if not m:
            # try accepting scientific notation
            return float(s)
        val = float(m.group(1))
        unit = (m.group(2) or "").lower()
        if unit in ("b", "bn"):
            val *= 1_000_000_000.0
        elif unit == "m":
            val *= 1_000_000.0
        elif unit == "k":
            val *= 1_000.0
        return float(val)
    except Exception:
        return None


def _parse_tiers_env(
    var_name: str, defaults: List[Tuple[float, float]], *, allow_units: bool
) -> List[Tuple[float, float]]:
    raw = os.environ.get(var_name)
    tiers: List[Tuple[float, float]] = []
    if raw:
        s = raw.strip()
        # JSON array of pairs e.g., [[5e8,1.0],[1e8,0.8]]
        if s.startswith("["):
            try:
                arr = json.loads(s)
                if isinstance(arr, list):
                    for item in arr:
                        if (
                            isinstance(item, (list, tuple))
                            and len(item) >= 2
                            and isinstance(item[1], (int, float))
                        ):
                            thr = item[0]
                            val = float(item[1])
                            thr_val = None
                            if isinstance(thr, (int, float)):
                                thr_val = float(thr)
                            elif isinstance(thr, str) and allow_units:
                                thr_val = _parse_amount_with_units(thr)
                            elif isinstance(thr, str):
                                try:
                                    thr_val = float(thr)
                                except Exception:
                                    thr_val = None
                            if thr_val is not None:
                                tiers.append((thr_val, max(0.0, min(1.0, val))))
            except Exception:
                tiers = []
        if not tiers:
            # Parse comma-separated key=value pairs
            # e.g., "500M=1.0,100M=0.8,25M=0.6,5M=0.4" or "20=0.8,10=0.6,5=0.4"
            parts = [p.strip() for p in s.split(",") if p.strip()]
            for p in parts:
                if "=" not in p:
                    continue
                k, v = p.split("=", 1)
                thr_val = None
                if allow_units:
                    thr_val = _parse_amount_with_units(k.strip())
                if thr_val is None:
                    try:
                        thr_val = float(k.strip())
                    except Exception:
                        thr_val = None
                try:
                    sc = float(v.strip())
                except Exception:
                    sc = None
                if thr_val is not None and sc is not None:
                    tiers.append((float(thr_val), max(0.0, min(1.0, float(sc)))))
    if not tiers:
        tiers = list(defaults)
    # Sort descending by threshold so we can take first match or compute max
    tiers.sort(key=lambda t: t[0], reverse=True)
    return tiers


@dataclass
class MaterialityResult:
    score: float  # 0..1
    reason: str
    model_prob: Optional[float] = None


class MaterialityPrefilter:
    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        # Load configurable patterns from env with safe defaults
        self.material_patterns: List[Pattern] = _parse_regex_list_env(
            "NEWS_TRIGGER_REGEXES", DEFAULT_MATERIAL_REGEXES
        )
        self.rumor_regex: Pattern = _load_rumor_regex()
        # Load tiers for amount and percent heuristics
        self.amount_tiers: List[Tuple[float, float]] = _parse_tiers_env(
            "NEWS_AMOUNT_SCORE_TIERS", DEFAULT_AMOUNT_TIERS, allow_units=True
        )
        self.pct_tiers: List[Tuple[float, float]] = _parse_tiers_env(
            "NEWS_PCT_SCORE_TIERS", DEFAULT_PCT_TIERS, allow_units=False
        )
        path = model_path or os.environ.get("NEWS_TFIDF_MODEL_PATH")
        if path and os.path.exists(path) and joblib is not None:
            try:
                self.model = joblib.load(path)
            except Exception:
                self.model = None

    def _amount_score(self, text: str) -> float:
        score = 0.0
        # Absolute dollar amounts
        for m in MONEY_RE.finditer(text or ""):
            val = (m.group(1) or "").replace(",", "")
            amt = None
            try:
                amt = float(val)
            except Exception:
                continue
            unit = (m.group(2) or "").lower()
            if unit in ("b", "bn"):
                amt *= 1_000_000_000
            elif unit in ("m",):
                amt *= 1_000_000
            elif unit in ("k",):
                amt *= 1_000
            for thr, sc in self.amount_tiers:
                if amt >= thr:
                    score = max(score, float(sc))
                    break
        # Percent magnitudes
        for m in PCT_RE.finditer(text or ""):
            try:
                pct = abs(float(m.group(1)))
            except Exception:
                continue
            for thr, sc in self.pct_tiers:
                if pct >= thr:
                    score = max(score, float(sc))
                    break
        return min(1.0, score)

    def _trigger_score(self, text: str) -> float:
        if not text:
            return 0.0
        hits = sum(1 for p in self.material_patterns if p.search(text))
        if hits == 0:
            return 0.0
        return 0.9 if hits >= 3 else (0.7 if hits == 2 else 0.5)

    def _rumor_penalty(self, text: str) -> float:
        return 0.2 if self.rumor_regex.search(text or "") else 0.0

    def _model_prob(self, title: str, snippet: str) -> Optional[float]:
        if self.model is None:
            return None
        text = (title or "").strip()
        if snippet:
            text += "\n" + snippet.strip()
        try:
            proba = self.model.predict_proba([text])[0]
            return float(proba[1]) if len(proba) > 1 else float(proba[0])
        except Exception:
            return None

    def score(
        self, title: str, snippet: str = "", source_domain: str | None = None
    ) -> MaterialityResult:
        text = ((title or "") + "\n" + (snippet or "")).strip()
        t_score = self._trigger_score(text)
        a_score = self._amount_score(text)
        m_prob = self._model_prob(title, snippet)
        rumor = self._rumor_penalty(text)

        src_boost = 0.0
        s = (source_domain or "").lower()
        if (
            s.endswith("sec.gov")
            or s.endswith("fda.gov")
            or s.endswith("faa.gov")
            or s.endswith("ftc.gov")
        ):
            src_boost = 0.2
        elif any(
            s.endswith(d) for d in ("businesswire.com", "globenewswire.com", "prnewswire.com")
        ):
            src_boost = 0.15

        if m_prob is not None:
            score = 0.6 * m_prob + 0.2 * t_score + 0.15 * a_score + src_boost - rumor
        else:
            score = 0.45 * t_score + 0.40 * a_score + src_boost - rumor
        if src_boost >= 0.2 and t_score >= 0.5:
            score = max(score, 0.75)
        score = max(0.0, min(1.0, score))
        reason = f"triggers={t_score:.2f} amount={a_score:.2f} model={m_prob if m_prob is not None else 'n/a'} src_boost={src_boost:.2f} rumor={rumor:.2f}"
        return MaterialityResult(score=score, reason=reason, model_prob=m_prob)
