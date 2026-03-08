# 论文自动筛选器

本项目用于自动追踪并处理每日 arXiv 论文 Markdown 源。
English README: `README.md`。

许可证：MIT，详见 [LICENSE](/f:/Plan/project/paper_watcher/LICENSE)。

创作声明：

- 本项目主要由 AI 辅助生成与迭代。
- 最终审核、责任归属与上线决策由仓库维护者承担。

## 上游仓库关系

`automatic-paper-filter` 是一个下游消费器，它依赖上游项目产出的日报 Markdown：

- 上游参考项目：`https://github.com/dw-dengwei/daily-arXiv-ai-enhanced`

当前默认配置绑定到我本人仓库：

- `https://github.com/oriacib/daily-arXiv-ai-enhanced`
- 路径模板：`data/{date}.md`

请注意本人仓库默认范围：

1. 默认仅支持当前配置仓库的文件结构（`data/` 下 `YYYY-MM-DD.md`）。
2. 默认仅跟随该仓库目前提供的领域内容（当前是 CV 与 NLP 日报）。
3. 如果你要爬取其他领域，请先按上游项目的方法生成并发布对应领域 Markdown，然后把本项目指向新仓库。

如何切换仓库：

- 修改 [config/config.yaml](/f:/Plan/project/paper_watcher/config/config.yaml)
- 重点字段：
  - `github.owner`
  - `github.repo`
  - `github.branch`
  - `github.path_template`（必须包含 `{date}`）
- 可选字段：
  - `github.raw_url_template`
  - `github.token`（或环境变量 `GITHUB_TOKEN`）

最小示例：

```yaml
github:
  owner: "your-owner"
  repo: "your-daily-arxiv-repo"
  branch: "main"
  path_template: "data/{date}.md"
  raw_url_template: null
  token: ""
```

## 配置与运行手册

按下面步骤执行，首次部署基本可直接跑通。

运行前检查：

1. 已安装 Python `3.11`（可执行 `python --version` 验证）。
2. 当前机器可访问 GitHub。
3. 命令执行目录在项目根目录。
4. Windows 下 `python` 不应解析到 `...WindowsApps\\python.exe`。

### 第 1 步：创建运行环境

Conda（推荐）：

```bash
conda env create -f environment.yml
conda activate paper-watcher
```

或 venv：

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell 激活 venv：

```powershell
.venv\Scripts\activate
```

Windows 路径检查（非常重要）：

```powershell
(Get-Command python).Source
```

期望值是实际解释器路径，如 `...\\miniconda3\\envs\\paper-watcher\\python.exe` 或 `.venv\\Scripts\\python.exe`。
如果显示 `...\\WindowsApps\\python.exe`，请先激活 conda/venv，或在后续命令里显式填写 `-PythonExe` 绝对路径。

### 第 2 步：配置密钥（推荐环境变量）

不要把密钥长期写在 git 跟踪的 yaml 文件中。
如果只是手动测试，可先在当前终端会话临时设置：

Linux/macOS：

```bash
export DEEPSEEK_API_KEY="your_deepseek_key"
export KIMI_API_KEY="your_kimi_key"
export QWEN_API_KEY="your_qwen_or_dashscope_key"
export OPENAI_API_KEY="your_openai_key"
export GEMINI_API_KEY="your_gemini_key"
export LLM_API_KEY="your_local_or_openai_compatible_key"
export GITHUB_TOKEN="your_github_token"   # 可选，但建议配置
```

Windows PowerShell：

```powershell
$env:DEEPSEEK_API_KEY="your_deepseek_key"
$env:KIMI_API_KEY="your_kimi_key"
$env:QWEN_API_KEY="your_qwen_or_dashscope_key"
$env:OPENAI_API_KEY="your_openai_key"
$env:GEMINI_API_KEY="your_gemini_key"
$env:LLM_API_KEY="your_local_or_openai_compatible_key"
$env:GITHUB_TOKEN="your_github_token"
```

随后让 yaml 中保持：

- `llm.api_key: ""`
- `github.token: ""`

`deepseek.api_key` 仅用于兼容旧配置，除非你明确使用旧风格，否则也建议保持为空。

### 第 3 步：核对配置文件

- [config/config.yaml](/f:/Plan/project/paper_watcher/config/config.yaml)
- [config/keywords.yaml](/f:/Plan/project/paper_watcher/config/keywords.yaml)

首次运行前至少确认：

1. `github.owner/repo/path_template` 指向你的真实源仓库。
2. `sync.catch_up_from_last_success: true`。
3. `relevance.llm_mode: ambiguous`。
4. `llm.provider: deepseek` 且 `llm.enabled: true`（若仅关键词筛选可设 `false`）。

### 第 4 步：运行命令

日常增量执行：

```bash
python -m app.main run-once
```

按时间段回溯抓取：

```bash
python -m app.main crawl-period --start-date 2026-03-01 --end-date 2026-03-07
```

回溯别名命令：

```bash
python -m app.main backfill --start-date 2026-03-01 --end-date 2026-03-07
```

后台常驻：

```bash
python -m app.main daemon
```

仅生成聚合摘要：

```bash
python -m app.main aggregate --days 7
```

### 第 5 步：检查输出是否正确

运行成功后应看到：

1. `data/raw_md/YYYY-MM-DD.md`
2. `data/processed/YYYY-MM-DD/high_relevance.md`
3. `data/processed/YYYY-MM-DD/medium_relevance.md`
4. `data/processed/YYYY-MM-DD/high_pdf/`
5. `data/digest/YYYY-MM-DD_to_YYYY-MM-DD.md`

高相关 PDF 命名格式：

- `YYYY-MM-DD_Title.pdf`（自动清理非法字符）

### 第 6 步：设置开机自启动

Windows（若你要看到桌面弹窗，建议此方式）：

```powershell
# 1) 持久化到用户环境（只需执行一次）
setx DEEPSEEK_API_KEY "your_deepseek_key"
setx GITHUB_TOKEN "your_github_token"
# 如果你使用其他提供商，请持久化对应密钥：
# setx KIMI_API_KEY "..."
# setx QWEN_API_KEY "..."
# setx OPENAI_API_KEY "..."
# setx GEMINI_API_KEY "..."
# setx LLM_API_KEY "..."    # local/openai_compatible

# 2) 注销并重新登录，让计划任务会话读取到新环境变量

# 3) 获取你当前 Python 绝对路径（不能是 WindowsApps 占位路径）
# (Get-Command python).Source

# 4) 使用当前用户会话安装任务，并指定 python 绝对路径
powershell -ExecutionPolicy Bypass -File scripts/install_task_windows.ps1 `
  -TaskName "PaperWatcher" `
  -TriggerMode Logon `
  -RunAsCurrentUser `
  -PythonExe "C:\path\to\your\python.exe"
```

安装脚本已采用更安全默认值：`RunLevel=Limited`、`RestartCount=3`、`RestartIntervalMinutes=5`。
仅在确有需要时再提升权限（`-RunLevel Highest`）。

若使用 `-TriggerMode Startup` 且主体为 `SYSTEM`，通常看不到桌面弹窗。
安装后建议立即验证：

```powershell
schtasks /Query /TN PaperWatcher /FO LIST /V
schtasks /Run /TN PaperWatcher
```

Linux：

```bash
bash scripts/install_service_linux.sh
```

Linux 下若使用 systemd 自启动，请确保服务进程可读取到 API 密钥环境变量（例如写入服务用户环境，或在 service 文件中添加 `Environment=`）。

## 配置项作用、推荐值与详细调参

### A) `config/config.yaml`

| 字段 | 作用 | 推荐值 | 何时调整 |
|---|---|---|---|
| `github.owner/repo/branch` | 源仓库定位 | 你的日报仓库 | 更换源仓库时改 |
| `github.path_template` | 日期文件路径模板 | `data/{date}.md` | 文件目录或命名不同就改 |
| `github.token` | GitHub API 认证 | 文件留空，走环境变量 | 触发限流时配置 |
| `sync.lookback_days` | 首次无历史时回看窗口 | `2` | 首次要拉更久历史可调大 |
| `sync.catch_up_from_last_success` | 是否从上次成功日期后补抓 | `true` | 日常保持 true |
| `sync.reprocess_existing` | 是否重处理已处理日期 | `false` | 规则改版后临时设 true |
| `relevance.high_threshold` | 高相关阈值 | `0.72` | 想下载更多 PDF 可下调 |
| `relevance.medium_threshold` | 中相关阈值 | `0.45` | 周报太多可上调 |
| `relevance.llm_mode` | LLM 调用策略 | `ambiguous` | `off` 最省钱，`all` 召回高 |
| `relevance.llm_trigger_low/high` | 触发 LLM 的灰区区间 | `0.2 / 0.65` | 区间越窄越省钱 |
| `relevance.llm_max_calls_per_run` | 每轮 LLM 调用上限 | `30` | 按预算调成 10/20/50 |
| `llm.provider` | LLM 后端选择 | `deepseek` | 可切换 `kimi/qwen/gpt/gemini/local/openai_compatible` |
| `llm.enabled` | 是否启用 LLM 打分 | `true` | 无网或零成本可设 false |
| `llm.api_key` | LLM 密钥 | 文件留空 | 用对应环境变量更安全 |
| `llm.model` | 模型名 | 留空（自动默认） | 需要指定特定模型时修改 |
| `llm.base_url` | 接口地址 | 留空（自动默认） | 对接代理网关或本地部署时修改 |
| `aggregate.window_days` | 聚合窗口天数 | `7` | 可改为 3/14 等 |
| `scheduler.interval_seconds` | 守护轮询间隔 | `1800` | 需要更快同步可下调 |

### B) `config/keywords.yaml`

推荐使用分组+分级结构：

- `core_keywords`：核心主题词
- `method_keywords`：方法路线词
- `property_keywords`：性质目标词
- `exclude_keywords`：排除词

每组可配置层级：

- `must`
- `strong`
- `weak`
- `exclude`

权重生效逻辑：

1. `level_weights` 控制层级强弱（must > strong > weak）。
2. `category_weights` 控制分组权重（core 常设更高）。
3. 标题命中乘 `title_multiplier`。
4. 摘要命中乘 `summary_multiplier`。

调参建议：

1. 无关论文太多进中高相关：
   - 提高 `high_threshold` / `medium_threshold`
   - 增加 `exclude_keywords`
   - 精简 `weak` 词
2. 漏掉太多目标论文：
   - 增加 `core_keywords.must/strong`
   - 适当降低阈值
3. API 成本过高：
   - 降低 `llm_max_calls_per_run`
   - 缩窄 `llm_trigger_low/high`
   - 保持 `llm_mode: ambiguous`

兼容说明：

- 旧版 `positive/negative` 关键词格式仍可用，但不建议继续扩展，建议迁移到新分组结构。
