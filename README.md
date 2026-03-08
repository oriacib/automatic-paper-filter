# automatic-paper-filter

This project is a local automation watcher for daily arXiv markdown feeds.
Chinese version: `README.zh-CN.md`.

License: MIT. See [LICENSE](/f:/Plan/project/paper_watcher/LICENSE).

Authorship statement:

- This project is primarily created with AI assistance.
- Final responsibility, review, and deployment decisions remain with the repository owner.

## Module 1: Upstream Relationship and Scope

`automatic-paper-filter` is a downstream consumer of daily markdown outputs generated in the style of:

- upstream reference: `https://github.com/dw-dengwei/daily-arXiv-ai-enhanced`

Default source in this repo is configured to:

- `https://github.com/oriacib/daily-arXiv-ai-enhanced`
- path: `data/{date}.md`

Important defaults and scope:

1. By default, this watcher only supports your currently configured source repository format (`YYYY-MM-DD.md` in `data/`).
2. By default, it follows the same topic coverage as that source feed (currently CV + NLP daily papers in your configured repo).
3. If you want other domains, first generate/publish those markdown files using the upstream method, then point this watcher to that repo.

How to change repository:

- edit [config/config.yaml](/f:/Plan/project/paper_watcher/config/config.yaml)
- change:
  - `github.owner`
  - `github.repo`
  - `github.branch`
  - `github.path_template` (must include `{date}`)
- optional:
  - `github.raw_url_template` (override URL builder)
  - `github.token` or env `GITHUB_TOKEN` (avoid API rate limits)

Minimal example:

```yaml
github:
  owner: "your-owner"
  repo: "your-daily-arxiv-repo"
  branch: "main"
  path_template: "data/{date}.md"
  raw_url_template: null
  token: ""
```

## Module 2: Configuration and Runbook

Use this exact checklist to avoid setup issues.

Preflight checklist:

1. Python `3.11` is available (`python --version`).
2. You can access GitHub from your machine.
3. You are running commands from the project root directory.
4. On Windows, your `python` should not resolve to `...WindowsApps\\python.exe`.

### Step 1: Create runtime environment

Conda (recommended):

```bash
conda env create -f environment.yml
conda activate paper-watcher
```

Or venv:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell venv activation:

```powershell
.venv\Scripts\activate
```

Windows path check (important):

```powershell
(Get-Command python).Source
```

Expected: a real interpreter path such as `...\\miniconda3\\envs\\paper-watcher\\python.exe` or `.venv\\Scripts\\python.exe`.
If it shows `...\\WindowsApps\\python.exe`, use conda/venv activation first, or pass explicit `-PythonExe` full path.

### Step 2: Configure secrets safely

Do not keep API keys in git-tracked yaml files.
For manual testing in current shell, set temporary environment variables:

```bash
export DEEPSEEK_API_KEY="your_deepseek_key"   # default provider
export KIMI_API_KEY="your_kimi_key"
export QWEN_API_KEY="your_qwen_or_dashscope_key"
export OPENAI_API_KEY="your_openai_key"
export GEMINI_API_KEY="your_gemini_key"
export LLM_API_KEY="your_local_or_openai_compatible_key"
export GITHUB_TOKEN="your_github_token"   # optional but recommended
```

Windows PowerShell:

```powershell
$env:DEEPSEEK_API_KEY="your_deepseek_key"
$env:KIMI_API_KEY="your_kimi_key"
$env:QWEN_API_KEY="your_qwen_or_dashscope_key"
$env:OPENAI_API_KEY="your_openai_key"
$env:GEMINI_API_KEY="your_gemini_key"
$env:LLM_API_KEY="your_local_or_openai_compatible_key"
$env:GITHUB_TOKEN="your_github_token"
```

Then keep `llm.api_key: ""` and `github.token: ""` in yaml.
`deepseek.api_key` is legacy-compatible and should also stay empty unless you explicitly use legacy config style.

### Step 3: Verify the two config files

- [config/config.yaml](/f:/Plan/project/paper_watcher/config/config.yaml)
- [config/keywords.yaml](/f:/Plan/project/paper_watcher/config/keywords.yaml)

Must-check values before first run:

1. `github.owner/repo/path_template` match your feed repo.
2. `sync.catch_up_from_last_success: true`.
3. `relevance.llm_mode: ambiguous`.
4. `llm.provider: deepseek` and `llm.enabled: true` (or `false` for offline keyword-only mode).

### Step 4: Run commands

Incremental daily run:

```bash
python -m app.main run-once
```

Historical period crawl:

```bash
python -m app.main crawl-period --start-date 2026-03-01 --end-date 2026-03-07
```

Backfill alias:

```bash
python -m app.main backfill --start-date 2026-03-01 --end-date 2026-03-07
```

Daemon mode:

```bash
python -m app.main daemon
```

Digest-only generation:

```bash
python -m app.main aggregate --days 7
```

### Step 5: Confirm output files

After successful run, check:

1. `data/raw_md/YYYY-MM-DD.md`
2. `data/processed/YYYY-MM-DD/high_relevance.md`
3. `data/processed/YYYY-MM-DD/medium_relevance.md`
4. `data/processed/YYYY-MM-DD/high_pdf/`
5. `data/digest/YYYY-MM-DD_to_YYYY-MM-DD.md`

High-PDF naming format:

- `YYYY-MM-DD_Title.pdf` (invalid filename characters auto-sanitized)

### Step 6: Enable startup automation

Windows (recommended for visible popup notifications):

```powershell
# 1) Persist env vars for scheduled task context (run once)
setx DEEPSEEK_API_KEY "your_deepseek_key"
setx GITHUB_TOKEN "your_github_token"
# If you use other providers, persist corresponding key instead:
# setx KIMI_API_KEY "..."
# setx QWEN_API_KEY "..."
# setx OPENAI_API_KEY "..."
# setx GEMINI_API_KEY "..."
# setx LLM_API_KEY "..."    # local/openai_compatible

# 2) Re-login to load user env vars into task session

# 3) Find your current python absolute path (must not be WindowsApps stub)
# (Get-Command python).Source

# 4) Install task with current user context and explicit python path
powershell -ExecutionPolicy Bypass -File scripts/install_task_windows.ps1 `
  -TaskName "PaperWatcher" `
  -TriggerMode Logon `
  -RunAsCurrentUser `
  -PythonExe "C:\path\to\your\python.exe"
```

The installer now defaults to safer settings: `RunLevel=Limited`, `RestartCount=3`, `RestartIntervalMinutes=5`.
Only use higher privilege if you explicitly need it (`-RunLevel Highest`).

If you install with `-TriggerMode Startup` and `SYSTEM`, popups are usually not visible on desktop.
Validate task registration and trigger once:

```powershell
schtasks /Query /TN PaperWatcher /FO LIST /V
schtasks /Run /TN PaperWatcher
```

Linux:

```bash
bash scripts/install_service_linux.sh
```

For Linux service startup, ensure API keys are available to systemd service environment (for example by exporting in the service user profile or adding `Environment=` entries in service file).

## Module 3: Configuration Reference (Purpose, Recommended Values, Tuning)

### A) `config/config.yaml`

| Field | Purpose | Recommended | When to change |
|---|---|---|---|
| `github.owner/repo/branch` | feed repo location | your repo | switch source repo |
| `github.path_template` | date file path template | `data/{date}.md` | if your repo path differs |
| `github.token` | GitHub API auth | empty in file, use env | set when API limited |
| `sync.lookback_days` | first-run fallback window | `2` | raise for longer first bootstrap |
| `sync.catch_up_from_last_success` | incremental catch-up mode | `true` | keep true for daily ops |
| `sync.reprocess_existing` | re-run already processed day | `false` | set true only for re-scoring migrations |
| `relevance.high_threshold` | high relevance cut line | `0.72` | lower to download more PDFs |
| `relevance.medium_threshold` | medium relevance cut line | `0.45` | raise to reduce weekly volume |
| `relevance.llm_mode` | LLM call strategy | `ambiguous` | `off` for keyword-only, `all` for max recall |
| `relevance.llm_trigger_low/high` | gray-zone for LLM calls | `0.2 / 0.65` | narrow range to save cost |
| `relevance.llm_max_calls_per_run` | cost guardrail | `30` | set by budget (e.g. `10`, `50`) |
| `llm.provider` | LLM backend selector | `deepseek` | switch to `kimi/qwen/gpt/gemini/local/openai_compatible` |
| `llm.enabled` | enable LLM scoring | `true` | set false in offline or zero-cost mode |
| `llm.api_key` | LLM auth | empty in file | use provider env vars |
| `llm.model` | LLM model id | empty (auto default) | override provider default model |
| `llm.base_url` | API base URL | empty (auto default) | set custom endpoint/local gateway |
| `aggregate.window_days` | digest period | `7` | set `3`, `14`, etc. |
| `scheduler.interval_seconds` | daemon loop interval | `1800` | lower for faster updates |

### B) `config/keywords.yaml`

This project supports grouped keywords (recommended):

- `core_keywords`: strongest intent topics
- `method_keywords`: model/algorithm route
- `property_keywords`: quality/behavior you care about
- `exclude_keywords`: irrelevant/noise domains

Each group can contain levels:

- `must`
- `strong`
- `weak`
- `exclude`

Weighting model:

1. `level_weights`: importance by level.
2. `category_weights`: importance by group.
3. title matches get multiplied by `title_multiplier`.
4. summary matches get multiplied by `summary_multiplier`.

Tuning strategy:

1. If too many irrelevant papers are medium/high:
   - increase `high_threshold`/`medium_threshold`
   - add more `exclude_keywords`
   - reduce `weak` terms
2. If too few papers are selected:
   - add domain terms to `core_keywords.must/strong`
   - lower thresholds slightly
3. If API cost is high:
   - lower `llm_max_calls_per_run`
   - narrow `llm_trigger_low/high`
   - keep `llm_mode: ambiguous`

Compatibility note:

- legacy `positive/negative` keyword format is still supported, but grouped format is recommended for maintainability.
