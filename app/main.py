from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import timedelta
import shutil
from pathlib import Path

from app.aggregator import generate_medium_digest
from app.arxiv_client import ArxivClient, build_title_pdf_name
from app.config import AppConfig, load_config
from app.downloader import Downloader
from app.github_sync import GitHubSync
from app.md_parser import extract_arxiv_id_from_text, parse_markdown
from app.notifier import Notifier
from app.relevance.deepseek_client import DeepSeekClient
from app.relevance.keyword_rule import KeywordRuleScorer
from app.relevance.scorer import PaperScorer
from app.scheduler import NetworkAwareScheduler
from app.state_db import PaperRecord, StateDB
from app.utils.dates import format_date, parse_date, rolling_window, today_local
from app.utils.file_ops import atomic_write_json, atomic_write_text, ensure_dir
from app.utils.logger import setup_logger


def _markdown_for_scored(title: str, papers: list[dict]) -> str:
    lines = [f"# {title}", "", f"Total: {len(papers)}", ""]
    for p in papers:
        lines.append(f"## {p['title']}")
        lines.append(f"- Relevance: {p['relevance']}")
        lines.append(f"- Combined score: {p['combined_score']:.3f}")
        lines.append(f"- Keyword score: {p['keyword_score']:.3f}")
        topic_ranking = p.get("keyword_topics") or []
        if topic_ranking:
            topic_text = ", ".join(f"{term}({score:.2f})" for term, score in topic_ranking[:5])
            lines.append(f"- Keyword topic ranking: {topic_text}")
            top_term, top_score = topic_ranking[0]
            lines.append(f"- Primary topic relevance: {top_term} ({top_score:.2f})")
        else:
            lines.append("- Keyword topic ranking: none")
        if p.get("llm_score") is not None:
            lines.append(f"- LLM score: {p['llm_score']:.3f}")
        if p.get("url"):
            lines.append(f"- URL: {p['url']}")
        if p.get("summary"):
            lines.append(f"- Summary: {p['summary']}")
        if p.get("reason"):
            lines.append(f"- Reason: {p['reason']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _resolve_range(cfg: AppConfig, start: str | None, end: str | None) -> tuple[str, str]:
    if start and end:
        start_date = parse_date(start)
        end_date = parse_date(end)
    elif start:
        start_date = parse_date(start)
        end_date = start_date
    elif end:
        end_date = parse_date(end)
        start_date = end_date
    else:
        end_date = today_local()
        start_date = end_date - timedelta(days=max(0, cfg.sync.lookback_days - 1))
    return format_date(start_date), format_date(end_date)


def _popup_run_summary(notifier: Notifier, result: dict) -> None:
    sync_result: dict[str, str] = result.get("sync_result", {})
    processed: list[dict] = result.get("processed", [])
    synced_count = sum(1 for v in sync_result.values() if v == "synced")
    failed_sync_count = sum(1 for v in sync_result.values() if v not in ("synced", "skipped"))
    processed_ok_count = sum(1 for p in processed if p.get("status") == "ok")
    already_count = sum(1 for p in processed if p.get("status") == "already_processed")

    if failed_sync_count > 0:
        notifier.popup(
            "PaperWatcher 失败提醒",
            f"抓取存在失败项: {failed_sync_count} 天。请查看日志。",
            level="error",
        )
        return

    if synced_count == 0 and processed_ok_count == 0:
        notifier.popup(
            "PaperWatcher 提醒",
            "已检查完成：没有新的 md 可抓取（或已全部处理）。",
            level="info",
        )
        return

    notifier.popup(
        "PaperWatcher 成功提醒",
        f"本轮完成：新抓取 {synced_count} 天，处理 {processed_ok_count} 天，已处理跳过 {already_count} 天。",
        level="info",
    )


def _process_one_date(
    cfg: AppConfig,
    date_str: str,
    state_db: StateDB,
    scorer: PaperScorer,
    arxiv: ArxivClient,
    downloader: Downloader,
    logger,
) -> dict:
    raw_path = cfg.raw_md_dir / f"{date_str}.md"
    if not raw_path.exists():
        logger.warning("raw markdown missing for %s", date_str)
        return {"date": date_str, "status": "missing_raw"}

    raw_text = raw_path.read_text(encoding="utf-8")
    parsed = parse_markdown(raw_text)
    parsed_map = {item.paper_id: item for item in parsed}
    scored = scorer.score(parsed)

    day_dir = cfg.processed_dir / date_str
    high_pdf_dir = day_dir / "high_pdf"
    ensure_dir(day_dir)
    ensure_dir(high_pdf_dir)

    atomic_write_text(day_dir / "source.md", raw_text)

    scored_payload = []
    high_items: list[dict] = []
    medium_items: list[dict] = []
    irrelevant_items: list[dict] = []

    for s in scored:
        entry = {
            "paper_id": s.paper_id,
            "title": s.title,
            "summary": s.summary,
            "url": s.url,
            "relevance": s.relevance,
            "combined_score": s.combined_score,
            "keyword_score": s.keyword_score,
            "llm_score": s.llm_score,
            "keyword_topics": s.keyword_topics,
            "keyword_negative_topics": s.keyword_negative_topics,
            "reason": s.reason,
            "arxiv_id": None,
            "pdf_path": None,
            "arxiv_metadata": None,
        }

        parsed_entry = parsed_map.get(s.paper_id)
        merged_text = f"{s.url}\n{s.summary}\n{parsed_entry.raw_block if parsed_entry else ''}"
        arxiv_id = arxiv.extract_arxiv_id(merged_text) or extract_arxiv_id_from_text(merged_text)
        entry["arxiv_id"] = arxiv_id

        if s.relevance == "high" and arxiv_id:
            try:
                metadata = arxiv.fetch_metadata(arxiv_id)
                cached_path = state_db.get_pdf_download_path(arxiv_id)
                if cached_path and Path(cached_path).exists():
                    cache_pdf = Path(cached_path)
                else:
                    cache_pdf = arxiv.download_pdf(
                        arxiv_id=arxiv_id,
                        title=metadata.get("title", s.title),
                        target_dir=cfg.pdf_cache_dir,
                        downloader=downloader,
                        max_attempts=cfg.download.max_attempts,
                        base_delay_seconds=cfg.download.base_delay_seconds,
                        max_delay_seconds=cfg.download.max_delay_seconds,
                    )
                    state_db.mark_pdf_download(arxiv_id, s.paper_id, str(cache_pdf), "success", None)

                day_pdf_name = build_title_pdf_name(
                    title=metadata.get("title", s.title),
                    arxiv_id=arxiv_id,
                    target_dir=high_pdf_dir,
                    date_prefix=date_str,
                )
                day_pdf_path = high_pdf_dir / day_pdf_name
                if not day_pdf_path.exists():
                    shutil.copy2(cache_pdf, day_pdf_path)

                entry["pdf_path"] = str(day_pdf_path)
                entry["arxiv_metadata"] = metadata
            except Exception as exc:
                state_db.mark_pdf_download(arxiv_id, s.paper_id, None, "failed", str(exc))
                logger.warning("pdf download failed %s: %s", arxiv_id, exc)

        state_db.upsert_paper(
            PaperRecord(
                paper_id=s.paper_id,
                source_date=date_str,
                title=s.title,
                summary=s.summary,
                url=s.url,
                arxiv_id=arxiv_id,
                relevance=s.relevance,
                combined_score=s.combined_score,
                keyword_score=s.keyword_score,
                llm_score=s.llm_score,
                reason=s.reason,
                metadata={
                    "url": s.url,
                    "arxiv_id": arxiv_id,
                    "pdf_path": entry["pdf_path"],
                    "arxiv_metadata": entry["arxiv_metadata"],
                    "keyword_topics": s.keyword_topics,
                    "keyword_negative_topics": s.keyword_negative_topics,
                },
            )
        )

        scored_payload.append(entry)
        if s.relevance == "high":
            high_items.append(entry)
        elif s.relevance == "medium":
            medium_items.append(entry)
        else:
            irrelevant_items.append(entry)

    atomic_write_text(
        day_dir / "high_relevance.md",
        _markdown_for_scored(f"High Relevance Papers - {date_str}", high_items),
    )
    atomic_write_text(
        day_dir / "medium_relevance.md",
        _markdown_for_scored(f"Medium Relevance Papers - {date_str}", medium_items),
    )
    metadata_payload = {
        "date": date_str,
        "counts": {
            "total": len(scored_payload),
            "high": len(high_items),
            "medium": len(medium_items),
            "irrelevant": len(irrelevant_items),
        },
        "papers": scored_payload,
    }
    atomic_write_json(day_dir / "metadata.json", metadata_payload)
    return {"date": date_str, "status": "ok", **metadata_payload["counts"]}


def run_once(cfg: AppConfig, start: str | None = None, end: str | None = None) -> dict:
    log_file = cfg.project_root / cfg.log.file
    logger = setup_logger(cfg.log.level, log_file)
    notifier = Notifier(
        logger,
        popup_enabled=cfg.notifications.popup_enabled,
        popup_timeout_seconds=cfg.notifications.popup_timeout_seconds,
    )
    state_db = StateDB(cfg.state_db_path)
    downloader = Downloader(timeout_seconds=cfg.download.timeout_seconds)
    github_sync = GitHubSync(cfg, state_db, downloader, logger)
    keyword_scorer = KeywordRuleScorer(cfg.keywords_file)
    llm_client = DeepSeekClient(cfg.deepseek, cfg.llm_cache_dir, logger)
    scorer = PaperScorer(cfg.relevance, keyword_scorer, llm_client)
    arxiv = ArxivClient(timeout_seconds=cfg.download.timeout_seconds)

    try:
        if start or end:
            start_str, end_str = _resolve_range(cfg, start, end)
            start_date = parse_date(start_str)
            end_date = parse_date(end_str)
            notifier.info(f"run once (range mode): {start_str} to {end_str}")
            sync_result = github_sync.sync_date_range(start_date, end_date)
            candidate_dates = sorted(sync_result.keys())
            digest_anchor_date = end_date
            remote_dates = candidate_dates[:]
        else:
            remote_dates = github_sync.list_remote_dates()
            pending_dates = github_sync.select_unsynced_remote_dates(remote_dates=remote_dates)
            sync_result = github_sync.sync_dates(pending_dates)
            if remote_dates:
                start_str = remote_dates[0]
                end_str = remote_dates[-1]
                digest_anchor_date = parse_date(end_str)
            else:
                today_str = format_date(today_local())
                start_str = today_str
                end_str = today_str
                digest_anchor_date = today_local()
            notifier.info(
                f"run once (auto mode): remote={len(remote_dates)}, pending={len(pending_dates)}, latest={end_str}"
            )
            candidate_dates = sorted(sync_result.keys())

        processed: list[dict] = []
        for d in candidate_dates:
            status = sync_result.get(d, "")
            if status not in ("synced", "skipped"):
                processed.append({"date": d, "status": "sync_failed"})
                continue
            metadata_path = cfg.processed_dir / d / "metadata.json"
            if status == "skipped" and metadata_path.exists() and not cfg.sync.reprocess_existing:
                processed.append({"date": d, "status": "already_processed"})
                continue
            day_result = _process_one_date(cfg, d, state_db, scorer, arxiv, downloader, logger)
            processed.append(day_result)

        window_start, window_end = rolling_window(digest_anchor_date, cfg.aggregate.window_days)
        digest_path, changed = generate_medium_digest(
            cfg.processed_dir,
            cfg.digest_dir,
            state_db,
            window_start,
            window_end,
        )
        notifier.info(f"digest {'updated' if changed else 'unchanged'}: {digest_path}")

        result = {
            "start_date": start_str,
            "end_date": end_str,
            "sync_result": sync_result,
            "remote_total_dates": len(remote_dates),
            "processed": processed,
            "digest_path": str(digest_path),
            "digest_changed": changed,
        }
        _popup_run_summary(notifier, result)
        return result
    except Exception as exc:
        notifier.popup(
            "PaperWatcher 失败提醒",
            f"抓取流程执行失败: {exc}",
            level="error",
        )
        raise
    finally:
        state_db.close()


def run_daemon(cfg: AppConfig) -> None:
    logger = setup_logger(cfg.log.level, cfg.project_root / cfg.log.file)
    notifier = Notifier(
        logger,
        popup_enabled=cfg.notifications.popup_enabled,
        popup_timeout_seconds=cfg.notifications.popup_timeout_seconds,
    )

    def _job() -> None:
        run_once(cfg, None, None)

    scheduler = NetworkAwareScheduler(
        _job,
        interval_seconds=cfg.scheduler.interval_seconds,
        network_check_url=cfg.scheduler.network_check_url,
        logger=logger,
        notifier=notifier,
        max_backoff_seconds=cfg.scheduler.max_backoff_seconds,
    )
    scheduler.run_forever()


def run_aggregate(cfg: AppConfig, days: int, end: str | None) -> dict:
    logger = setup_logger(cfg.log.level, cfg.project_root / cfg.log.file)
    state_db = StateDB(cfg.state_db_path)
    end_date = parse_date(end) if end else today_local()
    start_date, end_date = rolling_window(end_date, days)
    digest_path, changed = generate_medium_digest(
        cfg.processed_dir,
        cfg.digest_dir,
        state_db,
        start_date,
        end_date,
    )
    state_db.close()
    logger.info("aggregate done: %s (changed=%s)", digest_path, changed)
    return {
        "start_date": format_date(start_date),
        "end_date": format_date(end_date),
        "digest_path": str(digest_path),
        "digest_changed": changed,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="paper watcher")
    parser.add_argument("--config", default=None, help="path to config yaml")
    subparsers = parser.add_subparsers(dest="command")

    p_once = subparsers.add_parser("run-once", help="run one sync cycle (no date args => auto unsynced remote dates)")
    p_once.add_argument("--start-date", default=None)
    p_once.add_argument("--end-date", default=None)

    p_backfill = subparsers.add_parser("backfill", help="backfill a date range")
    p_backfill.add_argument("--start-date", required=True)
    p_backfill.add_argument("--end-date", required=True)

    p_period = subparsers.add_parser("crawl-period", help="crawl and process papers for a historical date period")
    p_period.add_argument("--start-date", required=True)
    p_period.add_argument("--end-date", required=True)

    subparsers.add_parser("daemon", help="run as daemon with scheduler")

    p_agg = subparsers.add_parser("aggregate", help="build digest from processed results")
    p_agg.add_argument("--days", type=int, default=7)
    p_agg.add_argument("--end-date", default=None)
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    cfg = load_config(args.config)

    if args.command == "daemon":
        run_daemon(cfg)
        return

    if args.command == "aggregate":
        result = run_aggregate(cfg, args.days, args.end_date)
        print(result)
        return

    if args.command == "backfill":
        result = run_once(cfg, args.start_date, args.end_date)
        print(result)
        return

    if args.command == "crawl-period":
        result = run_once(cfg, args.start_date, args.end_date)
        print(result)
        return

    if args.command in (None, "run-once"):
        start = getattr(args, "start_date", None)
        end = getattr(args, "end_date", None)
        result = run_once(cfg, start, end)
        print(result)
        return

    print(asdict(cfg))


if __name__ == "__main__":
    main()
