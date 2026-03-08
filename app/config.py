from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import yaml


LLM_PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "env_keys": ["DEEPSEEK_API_KEY"],
        "api_format": "openai_compatible",
        "requires_key": True,
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "kimi-k2-turbo-preview",
        "env_keys": ["KIMI_API_KEY", "MOONSHOT_API_KEY"],
        "api_format": "openai_compatible",
        "requires_key": True,
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus-latest",
        "env_keys": ["QWEN_API_KEY", "DASHSCOPE_API_KEY"],
        "api_format": "openai_compatible",
        "requires_key": True,
    },
    "gpt": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "env_keys": ["OPENAI_API_KEY"],
        "api_format": "openai_compatible",
        "requires_key": True,
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com",
        "model": "gemini-1.5-flash",
        "env_keys": ["GEMINI_API_KEY"],
        "api_format": "gemini",
        "requires_key": True,
    },
    "openai_compatible": {
        "base_url": "http://127.0.0.1:8000/v1",
        "model": "local-model",
        "env_keys": ["LLM_API_KEY"],
        "api_format": "openai_compatible",
        "requires_key": False,
    },
    "local": {
        "base_url": "http://127.0.0.1:8000/v1",
        "model": "local-model",
        "env_keys": ["LLM_API_KEY"],
        "api_format": "openai_compatible",
        "requires_key": False,
    },
}


def _normalize_provider(provider: str) -> str:
    value = provider.strip().lower().replace("-", "_")
    alias = {
        "openai": "gpt",
        "chatgpt": "gpt",
        "moonshot": "kimi",
        "dashscope": "qwen",
        "openai_compat": "openai_compatible",
    }
    return alias.get(value, value)


@dataclass(slots=True)
class GitHubConfig:
    owner: str
    repo: str
    branch: str
    path_template: str
    raw_url_template: str | None
    token: str
    timeout_seconds: int


@dataclass(slots=True)
class SyncConfig:
    lookback_days: int
    catch_up_from_last_success: bool
    reprocess_existing: bool
    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float


@dataclass(slots=True)
class RelevanceConfig:
    high_threshold: float
    medium_threshold: float
    keyword_weight: float
    llm_weight: float
    llm_mode: str
    llm_trigger_low: float
    llm_trigger_high: float
    llm_max_calls_per_run: int


@dataclass(slots=True)
class DeepSeekConfig:
    provider: str
    api_format: str
    requires_key: bool
    enabled: bool
    api_key: str
    model: str
    base_url: str
    timeout_seconds: int
    max_attempts: int
    max_input_chars: int


@dataclass(slots=True)
class DownloadConfig:
    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float
    timeout_seconds: int


@dataclass(slots=True)
class AggregateConfig:
    window_days: int


@dataclass(slots=True)
class SchedulerConfig:
    interval_seconds: int
    network_check_url: str
    max_backoff_seconds: int


@dataclass(slots=True)
class LogConfig:
    level: str
    file: str


@dataclass(slots=True)
class NotificationConfig:
    popup_enabled: bool
    popup_timeout_seconds: int


@dataclass(slots=True)
class AppConfig:
    project_root: Path
    data_dir: Path
    raw_md_dir: Path
    processed_dir: Path
    digest_dir: Path
    cache_dir: Path
    llm_cache_dir: Path
    pdf_cache_dir: Path
    state_db_path: Path
    keywords_file: Path
    github: GitHubConfig
    sync: SyncConfig
    relevance: RelevanceConfig
    deepseek: DeepSeekConfig
    download: DownloadConfig
    aggregate: AggregateConfig
    scheduler: SchedulerConfig
    log: LogConfig
    notifications: NotificationConfig


def _get(data: dict[str, Any], path: str, default: Any) -> Any:
    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _first_non_empty(*values: Any) -> str:
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def _resolve_llm_api_key(raw_cfg: dict[str, Any], provider: str) -> str:
    defaults = LLM_PROVIDER_DEFAULTS.get(provider, LLM_PROVIDER_DEFAULTS["deepseek"])
    key = _first_non_empty(
        _get(raw_cfg, "llm.api_key", ""),
        _get(raw_cfg, "deepseek.api_key", ""),
    )
    if key:
        return key

    env_keys = list(defaults.get("env_keys", []))
    if provider in ("openai_compatible", "local"):
        env_keys.append("LLM_API_KEY")
    for env_key in env_keys:
        value = os.getenv(env_key, "").strip()
        if value:
            return value
    return ""


def load_config(config_path: str | Path | None = None) -> AppConfig:
    project_root = Path(__file__).resolve().parents[1]
    cfg_path = Path(config_path) if config_path else project_root / "config" / "config.yaml"
    raw_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    data_dir = project_root / "data"
    cache_dir = data_dir / "cache"

    github_token = str(_get(raw_cfg, "github.token", "")).strip()
    if not github_token:
        github_token = os.getenv("GITHUB_TOKEN", "").strip()

    raw_provider = _first_non_empty(
        _get(raw_cfg, "llm.provider", ""),
        _get(raw_cfg, "deepseek.provider", ""),
        "deepseek",
    )
    llm_provider = _normalize_provider(raw_provider)
    provider_defaults = LLM_PROVIDER_DEFAULTS.get(llm_provider, LLM_PROVIDER_DEFAULTS["deepseek"])
    llm_api_key = _resolve_llm_api_key(raw_cfg, llm_provider)

    github = GitHubConfig(
        owner=_get(raw_cfg, "github.owner", ""),
        repo=_get(raw_cfg, "github.repo", ""),
        branch=_get(raw_cfg, "github.branch", "main"),
        path_template=_get(raw_cfg, "github.path_template", "{date}.md"),
        raw_url_template=_get(raw_cfg, "github.raw_url_template", None),
        token=github_token,
        timeout_seconds=int(_get(raw_cfg, "github.timeout_seconds", 20)),
    )

    sync = SyncConfig(
        lookback_days=int(_get(raw_cfg, "sync.lookback_days", 2)),
        catch_up_from_last_success=bool(_get(raw_cfg, "sync.catch_up_from_last_success", True)),
        reprocess_existing=bool(_get(raw_cfg, "sync.reprocess_existing", False)),
        max_attempts=int(_get(raw_cfg, "sync.max_attempts", 5)),
        base_delay_seconds=float(_get(raw_cfg, "sync.base_delay_seconds", 1.0)),
        max_delay_seconds=float(_get(raw_cfg, "sync.max_delay_seconds", 30.0)),
    )

    relevance = RelevanceConfig(
        high_threshold=float(_get(raw_cfg, "relevance.high_threshold", 0.72)),
        medium_threshold=float(_get(raw_cfg, "relevance.medium_threshold", 0.45)),
        keyword_weight=float(_get(raw_cfg, "relevance.keyword_weight", 0.6)),
        llm_weight=float(_get(raw_cfg, "relevance.llm_weight", 0.4)),
        llm_mode=str(_get(raw_cfg, "relevance.llm_mode", "ambiguous")),
        llm_trigger_low=float(_get(raw_cfg, "relevance.llm_trigger_low", 0.2)),
        llm_trigger_high=float(_get(raw_cfg, "relevance.llm_trigger_high", 0.65)),
        llm_max_calls_per_run=int(_get(raw_cfg, "relevance.llm_max_calls_per_run", 30)),
    )

    deepseek = DeepSeekConfig(
        provider=llm_provider,
        api_format=str(
            _first_non_empty(
                _get(raw_cfg, "llm.api_format", ""),
                _get(raw_cfg, "deepseek.api_format", ""),
                provider_defaults["api_format"],
            )
        ),
        requires_key=bool(provider_defaults["requires_key"]),
        enabled=bool(_get(raw_cfg, "llm.enabled", _get(raw_cfg, "deepseek.enabled", False))),
        api_key=llm_api_key,
        model=str(
            _first_non_empty(
                _get(raw_cfg, "llm.model", ""),
                _get(raw_cfg, "deepseek.model", ""),
                provider_defaults["model"],
            )
        ),
        base_url=str(
            _first_non_empty(
                _get(raw_cfg, "llm.base_url", ""),
                _get(raw_cfg, "deepseek.base_url", ""),
                provider_defaults["base_url"],
            )
        ),
        timeout_seconds=int(_get(raw_cfg, "llm.timeout_seconds", _get(raw_cfg, "deepseek.timeout_seconds", 20))),
        max_attempts=int(_get(raw_cfg, "llm.max_attempts", _get(raw_cfg, "deepseek.max_attempts", 3))),
        max_input_chars=int(_get(raw_cfg, "llm.max_input_chars", 900)),
    )

    download = DownloadConfig(
        max_attempts=int(_get(raw_cfg, "download.max_attempts", 5)),
        base_delay_seconds=float(_get(raw_cfg, "download.base_delay_seconds", 1.0)),
        max_delay_seconds=float(_get(raw_cfg, "download.max_delay_seconds", 60.0)),
        timeout_seconds=int(_get(raw_cfg, "download.timeout_seconds", 60)),
    )

    aggregate = AggregateConfig(
        window_days=int(_get(raw_cfg, "aggregate.window_days", 7)),
    )

    scheduler = SchedulerConfig(
        interval_seconds=int(_get(raw_cfg, "scheduler.interval_seconds", 1800)),
        network_check_url=str(_get(raw_cfg, "scheduler.network_check_url", "https://api.github.com")),
        max_backoff_seconds=int(_get(raw_cfg, "scheduler.max_backoff_seconds", 600)),
    )

    log = LogConfig(
        level=str(_get(raw_cfg, "log.level", "INFO")),
        file=str(_get(raw_cfg, "log.file", "data/logs/paper_watcher.log")),
    )

    notifications = NotificationConfig(
        popup_enabled=bool(_get(raw_cfg, "notifications.popup_enabled", True)),
        popup_timeout_seconds=int(_get(raw_cfg, "notifications.popup_timeout_seconds", 8)),
    )

    return AppConfig(
        project_root=project_root,
        data_dir=data_dir,
        raw_md_dir=data_dir / "raw_md",
        processed_dir=data_dir / "processed",
        digest_dir=data_dir / "digest",
        cache_dir=cache_dir,
        llm_cache_dir=cache_dir / "llm_responses",
        pdf_cache_dir=cache_dir / "pdf",
        state_db_path=data_dir / "state.sqlite",
        keywords_file=project_root / "config" / "keywords.yaml",
        github=github,
        sync=sync,
        relevance=relevance,
        deepseek=deepseek,
        download=download,
        aggregate=aggregate,
        scheduler=scheduler,
        log=log,
        notifications=notifications,
    )
