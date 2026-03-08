from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class KeywordResult:
    raw_score: float
    normalized_score: float
    matched_positive: list[str]
    matched_negative: list[str]
    positive_ranking: list[tuple[str, float]]
    negative_ranking: list[tuple[str, float]]
    reason: str


@dataclass(slots=True)
class KeywordRuleEntry:
    term: str
    base_weight: float
    topic: str


class KeywordRuleScorer:
    def __init__(self, keywords_file: Path) -> None:
        payload: dict[str, Any] = yaml.safe_load(keywords_file.read_text(encoding="utf-8")) or {}
        self.title_multiplier: float = float(payload.get("title_multiplier", 2.0))
        self.summary_multiplier: float = float(payload.get("summary_multiplier", 1.0))
        self.level_weights: dict[str, float] = {
            "must": float(payload.get("level_weights", {}).get("must", 3.0)),
            "strong": float(payload.get("level_weights", {}).get("strong", 1.8)),
            "weak": float(payload.get("level_weights", {}).get("weak", 0.9)),
            "exclude": float(payload.get("level_weights", {}).get("exclude", 2.4)),
        }
        self.category_weights: dict[str, float] = {
            "core_keywords": float(payload.get("category_weights", {}).get("core_keywords", 1.6)),
            "method_keywords": float(payload.get("category_weights", {}).get("method_keywords", 1.2)),
            "property_keywords": float(payload.get("category_weights", {}).get("property_keywords", 1.0)),
            "exclude_keywords": float(payload.get("category_weights", {}).get("exclude_keywords", 1.0)),
            "flat": float(payload.get("category_weights", {}).get("flat", 1.0)),
        }
        self.positive_rules: list[KeywordRuleEntry] = []
        self.negative_rules: list[KeywordRuleEntry] = []
        self._load_rules(payload)
        self.positive_terms: list[str] = sorted({r.term for r in self.positive_rules})

    def get_positive_terms(self) -> list[str]:
        return self.positive_terms

    def _iter_terms(self, raw_value: Any) -> list[tuple[str, float]]:
        if raw_value is None:
            return []
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        terms: list[tuple[str, float]] = []
        for item in values:
            if isinstance(item, str):
                term = item.strip().lower()
                if term:
                    terms.append((term, 1.0))
            elif isinstance(item, dict):
                term = str(item.get("term", "")).strip().lower()
                extra_weight = float(item.get("weight", 1.0))
                if term:
                    terms.append((term, extra_weight))
        return terms

    def _add_rule(
        self,
        *,
        polarity: str,
        category: str,
        level: str,
        term: str,
        extra_weight: float = 1.0,
    ) -> None:
        level_key = level.lower().strip()
        category_key = category.lower().strip()
        base = self.level_weights.get(level_key, self.level_weights["weak"])
        cat_mul = self.category_weights.get(category_key, 1.0)
        base_weight = base * cat_mul * extra_weight
        topic = f"{category_key}.{level_key}:{term}"
        rule = KeywordRuleEntry(term=term, base_weight=base_weight, topic=topic)
        if polarity == "positive":
            self.positive_rules.append(rule)
        else:
            self.negative_rules.append(rule)

    def _load_rules_legacy(self, payload: dict[str, Any]) -> None:
        for item in payload.get("positive", []):
            term = str(item.get("term", "")).strip().lower()
            if not term:
                continue
            weight = float(item.get("weight", 1.0))
            self.positive_rules.append(
                KeywordRuleEntry(
                    term=term,
                    base_weight=weight,
                    topic=f"legacy.strong:{term}",
                )
            )
        for item in payload.get("negative", []):
            term = str(item.get("term", "")).strip().lower()
            if not term:
                continue
            weight = float(item.get("weight", 1.0))
            self.negative_rules.append(
                KeywordRuleEntry(
                    term=term,
                    base_weight=weight,
                    topic=f"legacy.exclude:{term}",
                )
            )

    def _load_rules(self, payload: dict[str, Any]) -> None:
        if "positive" in payload or "negative" in payload:
            self._load_rules_legacy(payload)
            return

        category_specs: list[tuple[str, str, str]] = [
            ("core_keywords", "positive", "strong"),
            ("method_keywords", "positive", "strong"),
            ("property_keywords", "positive", "weak"),
            ("exclude_keywords", "negative", "exclude"),
        ]
        for category, polarity, default_level in category_specs:
            block = payload.get(category)
            if block is None:
                continue
            if isinstance(block, dict):
                for level in ("must", "strong", "weak", "exclude"):
                    for term, extra in self._iter_terms(block.get(level)):
                        actual_polarity = "negative" if level == "exclude" or polarity == "negative" else polarity
                        self._add_rule(
                            polarity=actual_polarity,
                            category=category,
                            level=level,
                            term=term,
                            extra_weight=extra,
                        )
            else:
                for term, extra in self._iter_terms(block):
                    self._add_rule(
                        polarity=polarity,
                        category=category,
                        level=default_level,
                        term=term,
                        extra_weight=extra,
                    )

        # Support flat style: must/strong/weak/exclude at top-level.
        for level in ("must", "strong", "weak"):
            for term, extra in self._iter_terms(payload.get(level)):
                self._add_rule(
                    polarity="positive",
                    category="flat",
                    level=level,
                    term=term,
                    extra_weight=extra,
                )
        for term, extra in self._iter_terms(payload.get("exclude")):
            self._add_rule(
                polarity="negative",
                category="flat",
                level="exclude",
                term=term,
                extra_weight=extra,
            )

    def score(self, title: str, summary: str) -> KeywordResult:
        title_l = title.lower()
        summary_l = summary.lower()
        positive_score = 0.0
        negative_score = 0.0
        matched_positive: list[str] = []
        matched_negative: list[str] = []
        positive_breakdown: dict[str, float] = {}
        negative_breakdown: dict[str, float] = {}

        for item in self.positive_rules:
            term = item.term
            weight = item.base_weight
            hit_title = term in title_l
            hit_summary = term in summary_l
            if hit_title or hit_summary:
                term_score = 0.0
                if hit_title:
                    term_score += weight * self.title_multiplier
                if hit_summary:
                    term_score += weight * self.summary_multiplier
                positive_score += term_score
                positive_breakdown[item.topic] = positive_breakdown.get(item.topic, 0.0) + term_score
                matched_positive.append(term)

        for item in self.negative_rules:
            term = item.term
            weight = item.base_weight
            hit_title = term in title_l
            hit_summary = term in summary_l
            if hit_title or hit_summary:
                term_score = 0.0
                if hit_title:
                    term_score += weight * self.title_multiplier
                if hit_summary:
                    term_score += weight * self.summary_multiplier
                negative_score += term_score
                negative_breakdown[item.topic] = negative_breakdown.get(item.topic, 0.0) + term_score
                matched_negative.append(term)

        raw_score = positive_score - negative_score
        if raw_score <= 0:
            normalized = 0.0
        else:
            # Cost-first: no keyword hit should stay low; strong hits climb quickly.
            normalized = min(1.0, raw_score / 8.0)
        reason = (
            f"keyword raw={raw_score:.2f}, pos={positive_score:.2f}, neg={negative_score:.2f}, norm={normalized:.2f}, "
            f"+{matched_positive or ['none']}, -{matched_negative or ['none']}"
        )
        positive_ranking = sorted(positive_breakdown.items(), key=lambda x: x[1], reverse=True)
        negative_ranking = sorted(negative_breakdown.items(), key=lambda x: x[1], reverse=True)
        return KeywordResult(
            raw_score=raw_score,
            normalized_score=normalized,
            matched_positive=matched_positive,
            matched_negative=matched_negative,
            positive_ranking=positive_ranking,
            negative_ranking=negative_ranking,
            reason=reason,
        )
