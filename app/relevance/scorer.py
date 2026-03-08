from __future__ import annotations

from dataclasses import dataclass

from app.config import RelevanceConfig
from app.md_parser import ArticleEntry
from app.relevance.deepseek_client import DeepSeekClient
from app.relevance.keyword_rule import KeywordRuleScorer


@dataclass(slots=True)
class ScoredPaper:
    paper_id: str
    title: str
    summary: str
    url: str
    relevance: str
    combined_score: float
    keyword_score: float
    llm_score: float | None
    keyword_topics: list[tuple[str, float]]
    keyword_negative_topics: list[tuple[str, float]]
    reason: str


class PaperScorer:
    def __init__(
        self,
        cfg: RelevanceConfig,
        keyword_scorer: KeywordRuleScorer,
        llm_client: DeepSeekClient,
    ) -> None:
        self.cfg = cfg
        self.keyword_scorer = keyword_scorer
        self.llm_client = llm_client

    def score(self, papers: list[ArticleEntry]) -> list[ScoredPaper]:
        results: list[ScoredPaper] = []
        llm_mode = self.cfg.llm_mode.strip().lower()
        positive_terms = self.keyword_scorer.get_positive_terms()
        llm_calls = 0
        llm_budget = max(0, int(self.cfg.llm_max_calls_per_run))
        for paper in papers:
            kw = self.keyword_scorer.score(paper.title, paper.summary)
            keyword_score = kw.normalized_score

            llm_score: float | None = None
            llm_reason = ""
            should_call_llm = False
            if self.llm_client.enabled and llm_mode != "off":
                if llm_mode == "all":
                    should_call_llm = bool(kw.matched_positive)
                else:
                    should_call_llm = (
                        bool(kw.matched_positive)
                        and self.cfg.llm_trigger_low <= keyword_score <= self.cfg.llm_trigger_high
                    )

            if should_call_llm and llm_calls < llm_budget:
                llm_result = self.llm_client.score(paper.title, paper.summary, positive_terms)
                if llm_result:
                    llm_score = float(llm_result["score"])
                    llm_reason = str(llm_result.get("reason", ""))
                    llm_calls += 1

            if llm_score is None:
                combined = keyword_score
            else:
                combined = (
                    self.cfg.keyword_weight * keyword_score
                    + self.cfg.llm_weight * llm_score
                )

            if combined >= self.cfg.high_threshold:
                relevance = "high"
            elif combined >= self.cfg.medium_threshold:
                relevance = "medium"
            else:
                relevance = "irrelevant"

            reason = kw.reason
            if llm_reason:
                reason = f"{reason}; llm={llm_reason}"

            results.append(
                ScoredPaper(
                    paper_id=paper.paper_id,
                    title=paper.title,
                    summary=paper.summary,
                    url=paper.url,
                    relevance=relevance,
                    combined_score=combined,
                    keyword_score=keyword_score,
                    llm_score=llm_score,
                    keyword_topics=kw.positive_ranking,
                    keyword_negative_topics=kw.negative_ranking,
                    reason=reason,
                )
            )

        return results
