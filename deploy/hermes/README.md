# Hermes 集成说明（resume-bot）

本目录用于把 `resume-fill` 项目整合成可直接安装使用的 Hermes Skill。

## 目标能力

- Telegram 接收简历文件
- 白名单鉴权
- 生成 TEK 标准 DOCX
- 回传 DOCX 到 Telegram
- 持久化 tracker 与错误日志

## 需要准备

1. Python3（用于执行脚本）
2. `uv`（用于自动创建并管理 `.venv`）
3. himalaya 已配置发件账号（可选，仅在开启邮件发送时使用）
4. Telegram Bot Token 与允许用户 ID
5. 把模板文件放在：`muban/简历模板 TEK.docx`

若未安装 `uv`，请先参考官方文档：<https://docs.astral.sh/uv/getting-started/installation/>

## 一次性配置

1. 将 `env.sample` 内容合并到 `~/.hermes/.env`
2. 根据 `menu.json` 生成 bot 目录与菜单片段：

```bash
python3 scripts/generate_hermes_bot_dir.py
```

默认会生成到：`~/.hermes/bots/resume-bot/`

3. 将 `config.yaml.snippet` 与 `~/.hermes/bots/resume-bot/quick_commands.generated.yaml` 一起合并到 `~/.hermes/config.yaml`
4. 在 Hermes skill 安装目录中，确保可执行命令存在：

```bash
python3 scripts/resume_bot_pipeline.py bootstrap-uv
python3 scripts/resume_bot_pipeline.py init-llm --deepseek-api-key "<DEEPSEEK_API_KEY>"
```

## 一键更新（修 bug 后同步到 Hermes）

当你把代码推到 GitHub 后，在 Hermes 机器执行：

```bash
bash /Users/01-work/jianli/scripts/update_hermes_skill.sh --restart-gateway
```

该命令会自动完成：
- 拉取 skill 仓库最新代码（`git pull --ff-only`）
- 更新 skill `.venv` 依赖
- 重新生成 bot 菜单片段
- 重启 Hermes gateway（传了 `--restart-gateway`）

> 注意：gateway 执行命令时 cwd 可能不是 skill 目录，所以 channel_prompts 里的命令建议统一使用  
> `cd /Users/01-work/jianli && python3 ...` 这种绝对路径前缀（你可替换为自己的实际项目路径）。

说明：
- `resume_bot_pipeline.py` 会自动使用 `uv` 创建并复用 skill 目录下的 `.venv`
- 首次运行自动安装 `requirements.txt`，后续运行不重复安装
- 运行命令会自动重入 `.venv/bin/python` 执行
- 如果仓库里有 `requirements.lock.txt`，会优先按锁定版本安装（推荐提交到 GitHub）
- `quick_commands` 在 Hermes 配置里必须是 mapping（对象），不能是 list

## 两段关键命令（供 channel_prompts 调用）

### Step A: 提取文本

```bash
python3 scripts/resume_bot_pipeline.py extract \
  --resume "/tmp/resume-bot/input_resume.pdf" \
  --out-text "/tmp/resume-bot/resume_text.txt" \
  --require-pdf
```

### Step B: 处理并回传文件

```bash
python3 scripts/resume_bot_pipeline.py llm-parse \
  --text-file "/tmp/resume-bot/resume_text.txt" \
  --out-json "/tmp/resume-bot/resume_data.json"

python3 scripts/resume_bot_pipeline.py process \
  --resume "/tmp/resume-bot/input_resume.pdf" \
  --json "/tmp/resume-bot/resume_data.json" \
  --output-docx "/tmp/resume-bot/张三-TEK-标准简历.docx" \
  --candidate-name "张三" \
  --require-pdf
```

说明：

- `llm-parse` 默认调用 DeepSeek `deepseek-chat`（更省成本）
- Telegram bot 建议开启电子围栏：仅处理 PDF，文字消息与非 PDF 文件只做提示不进入流水线
- 若 `is_valid_resume=false`，应拒绝生成并回用户原因
- 默认不发送邮件，直接在 Telegram 回传 DOCX，避免因邮箱配置卡住
- 附件名与输出名统一为 `姓名-TEK-标准简历.docx`
- 默认会删除临时输入文件（收到的简历、`resume_data.json`、`resume_email.mml`）
- 若需要发邮件，显式加 `--enable-email --to-email "<邮箱>"`
- 若回传 Telegram 完成后删除输出 DOCX，请执行：

```bash
python3 scripts/resume_bot_pipeline.py cleanup \
  --paths "/tmp/resume-bot/张三-TEK-标准简历.docx" "/tmp/resume-bot/resume_text.txt"
```

## 进度与会话打扰控制

- 查询当前任务状态：

```bash
python3 scripts/resume_bot_pipeline.py status
```

- 直接生成可回复给用户的进度文本：

```bash
python3 scripts/resume_bot_pipeline.py status --text
```

- 手动重置卡住状态（给用户 /reset）：

```bash
python3 scripts/resume_bot_pipeline.py reset
```

- 如需同时清理临时目录可用：

```bash
python3 scripts/resume_bot_pipeline.py reset --clear-temp
```

- `process` 运行时会将状态写入 `/tmp/resume-bot/status.json`
- `process` 完成后会进入 `awaiting_delivery`（busy=true），直到执行 `cleanup` 才解锁，避免回传阶段被 `/new` 打断
- 如果已有任务运行，再次调用 `process` 会返回 `busy=true`，可直接用于“忙碌中拒绝新消息”文案

### 实时状态条方案（可选增强）

1. **低成本方案（推荐当前先用）**  
   用户主动发送“状态”或点击 `/status`，bot 返回阶段+百分比+文本进度条。

2. **准实时方案（体验更好）**  
   在“开始处理”后发送一条“处理中”消息，后台每 3-5 秒调用 `status --text`，再通过 Telegram `editMessageText` 更新同一条消息；完成后改成“处理完成”。  
   优点是像实时状态条，缺点是需要对接 Telegram 编辑消息接口。

## 运行时文件

- `~/.hermes/resume-bot/tracker.json`
- `~/.hermes/resume-bot/errors.log`
- `/tmp/resume-bot/`（中间文件与输出）

## Telegram 菜单与 Gate 约束

- `TELEGRAM_ALLOWED_USERS` 控制白名单
- `TELEGRAM_CUSTOM_MENU=true` + `/start /new /clear /status /reset`
- `display.platforms.telegram.tool_progress: off`
- `approvals.mode: off` + `HERMES_YOLO_MODE=1`

