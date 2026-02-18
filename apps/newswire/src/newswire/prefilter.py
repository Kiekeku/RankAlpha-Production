from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

try:
    import joblib  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    joblib = None


MATERIAL_PATTERNS = [
    re.compile(r"\b(acquire|acquisition|merger|merge|buy(?:s|out)?|takeover)\b", re.I),
    re.compile(r"\b(earnings|EPS|revenue|guidance|outlook|forecast|results)\b", re.I),
    re.compile(r"\b(bankruptcy|chapter\s?11|restructuring)\b", re.I),
    re.compile(r"\b(SEC|FTC|DOJ|FDA|FAA|EPA|CPSC)\b", re.I),
    re.compile(r"\b(recall|halt(?:s|ing)?|suspend(?:s|ing)?|probe|investigation)\b", re.I),
    re.compile(r"\b(appoints?|resigns?|steps\s+down|CEO|CFO|CTO|Chairman)\b", re.I),
    re.compile(r"\b(contract|order|award|deal)\b", re.I),
    re.compile(r"\b(downgrade|upgrade|price\s*target)\b", re.I),
]

RUMOR_WORDS = re.compile(
    r"\b(report(?:edly)?|rumor(?:s|ed)?|may|could|considering|weighing|exploring)\b", re.I
)

MONEY_RE = re.compile(r"\$\s?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)(?:\s*(B|bn|M|m|K|k))?", re.I)
PCT_RE = re.compile(r"([+\-]?[0-9]+(?:\.[0-9]+)?)\s?%")


@dataclass
class MaterialityResult:
    score: float  # 0..1
    reason: str
    model_prob: Optional[float] = None


class MaterialityPrefilter:
    """First-pass materiality filter.

    - If `NEWS_TFIDF_MODEL_PATH` exists, use the loaded scikit-learn pipeline to compute probability on title+snippet.
    - Combine with cheap lexical/amount/source heuristics to produce a final score in [0,1].
    - If model is absent, rely on heuristics only.
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        path = model_path or os.environ.get("NEWS_TFIDF_MODEL_PATH")
        if path and os.path.exists(path) and joblib is not None:
            try:
                self.model = joblib.load(path)
            except Exception:
                self.model = None

    def _amount_score(self, text: str) -> float:
        score = 0.0
        for m in MONEY_RE.finditer(text or ""):
            val = m.group(1).replace(",", "")
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
            # Heuristic tiers
            if amt >= 500_000_000:
                score = max(score, 1.0)
            elif amt >= 100_000_000:
                score = max(score, 0.8)
            elif amt >= 25_000_000:
                score = max(score, 0.6)
            elif amt >= 5_000_000:
                score = max(score, 0.4)
        for m in PCT_RE.finditer(text or ""):
            try:
                pct = abs(float(m.group(1)))
            except Exception:
                continue
            if pct >= 20:
                score = max(score, 0.8)
            elif pct >= 10:
                score = max(score, 0.6)
            elif pct >= 5:
                score = max(score, 0.4)
        return min(1.0, score)

    def _trigger_score(self, text: str) -> float:
        if not text:
            return 0.0
        hits = sum(1 for p in MATERIAL_PATTERNS if p.search(text))
        if hits == 0:
            return 0.0
        # 1 hit -> 0.5, 2 -> 0.7, 3+ -> 0.9
        return 0.9 if hits >= 3 else (0.7 if hits == 2 else 0.5)

    def _rumor_penalty(self, text: str) -> float:
        return 0.2 if RUMOR_WORDS.search(text or "") else 0.0

    def _model_prob(self, title: str, snippet: str) -> Optional[float]:
        if self.model is None:
            return None
        text = (title or "").strip()
        if snippet:
            text += "\n" + snippet.strip()
        try:
            proba = self.model.predict_proba([text])[0]
            # assume class 1 = material
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

        # Lightweight source prior: official and regulators get a boost
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

        # Combine; prefer model when present (plain TF‑IDF first pass)
        if m_prob is not None:
            score = 0.6 * m_prob + 0.2 * t_score + 0.15 * a_score + src_boost - rumor
        else:
            score = 0.45 * t_score + 0.40 * a_score + src_boost - rumor

        # Fast‑track: official/regulator + clear trigger should be considered material enough for review
        if src_boost >= 0.2 and t_score >= 0.5:
            score = max(score, 0.75)

        score = max(0.0, min(1.0, score))
        reason = f"triggers={t_score:.2f} amount={a_score:.2f} model={m_prob if m_prob is not None else 'n/a'} src_boost={src_boost:.2f} rumor={rumor:.2f}"
        return MaterialityResult(score=score, reason=reason, model_prob=m_prob)
