---
name: resume-bot
description: Telegram 简历投递全流程 Skill。处理简历文件、结构化解析、TEK 模板生成、DOCX 回传、tracker 统计与错误日志。邮件发送默认为关闭，可按需开启。用于 Hermes Bot 自动化简历投递场景。
category: productivity
disable-model-invocation: true
---

# Resume Bot Skill

把简历投递工作流打包为可安装、可复用的 Hermes Skill。

## 能力范围

1. 白名单鉴权（`TELEGRAM_ALLOWED_USERS`）
2. 简历文本提取（PDF / DOCX / TXT）
3. LLM 解析后 JSON 填充 TEK 模板
4. 更新 `tracker.json` 与 `errors.log`
5. 将标准 DOCX 回传 Telegram

## 安装

```bash
# 1) 安装 skill（仓库地址按实际替换）
hermes skill install github:<owner>/resume-bot

# 2) 初始化 skill 专用 .venv（uv 管理，首次自动装依赖）
python3 scripts/resume_bot_pipeline.py bootstrap-uv

# 3) 首次初始化 DeepSeek Token（必需）
python3 scripts/resume_bot_pipeline.py init-llm --deepseek-api-key "<DEEPSEEK_API_KEY>"

# 4) 验证流水线命令
python3 scripts/resume_bot_pipeline.py --help
```

## 更新

发布新版本后，在 Hermes 机器可一键更新：

```bash
bash scripts/update_hermes_skill.sh --restart-gateway
```

说明：运行 `extract/process/cleanup` 时会自动重入该 `.venv`，并持续复用，不会每次重复安装依赖（由 `uv` 管理）。
若存在 `requirements.lock.txt`，安装会优先使用锁定文件，确保各环境版本一致。

## 运行前准备

- 模板路径：`muban/简历模板 TEK.docx`
- 发信工具：himalaya（可选，仅在显式开启邮件发送时需要）
- 环境变量：见 `deploy/hermes/env.sample`
- Hermes 配置片段：见 `deploy/hermes/config.yaml.snippet`
- 菜单配置源：`deploy/hermes/menu.json`

可先生成 bot 目录与菜单片段：

```bash
python3 scripts/generate_hermes_bot_dir.py
```

## 标准流程（面向 Telegram）

1. 用户上传简历文件
2. 白名单检查，未授权拒绝
3. 立即回复"✅ 已收到，正在处理您的简历（预计 1-2 分钟）。进度可回复'状态'查询。"
4. 后台执行（不询问邮箱、不发邮件）：
   - 下载文件到 `/tmp/resume-bot/`
   - 提取文本
   - LLM 解析到 `/tmp/resume-bot/resume_data.json`
   - 若 is_valid_resume=false，回复失败原因并停止
   - 生成 `/tmp/resume-bot/姓名-TEK-标准简历.docx`（使用 --skip-email）
5. 使用 send_message 将 DOCX 文件回传给用户（MEDIA:<路径>）
6. 回传成功后 cleanup 删除临时文件（cleanup 后会解锁会话）
7. 最后回复"✅ 转换完成！"

## 命令接口（供 channel_prompts 调用）

### A. 提取文本

```bash
python3 scripts/resume_bot_pipeline.py extract \
  --resume "/tmp/resume-bot/input_resume.pdf" \
  --out-text "/tmp/resume-bot/resume_text.txt"
```

### B. 生成并回传文件

```bash
python3 scripts/resume_bot_pipeline.py llm-parse \
  --text-file "/tmp/resume-bot/resume_text.txt" \
  --out-json "/tmp/resume-bot/resume_data.json"

# 仅当 is_valid_resume=true 时继续
python3 scripts/resume_bot_pipeline.py process \
  --resume "/tmp/resume-bot/input_resume.pdf" \
  --json "/tmp/resume-bot/resume_data.json" \
  --output-docx "/tmp/resume-bot/候选人姓名-TEK-标准简历.docx" \
  --candidate-name "候选人姓名"
```

若你明确要发邮件（默认关闭）：

```bash
python3 scripts/resume_bot_pipeline.py process \
  --resume "/tmp/resume-bot/input_resume.pdf" \
  --json "/tmp/resume-bot/resume_data.json" \
  --to-email "target@example.com" \
  --enable-email \
  --candidate-name "候选人姓名"
```

默认会清理临时输入文件（原简历、`resume_data.json`、`resume_email.mml`），避免临时目录累积。

在回传 Telegram 后，可执行：

```bash
python3 scripts/resume_bot_pipeline.py cleanup \
  --paths "/tmp/resume-bot/候选人姓名-TEK-标准简历.docx" "/tmp/resume-bot/resume_text.txt"
```

## 数据落盘

- `~/.hermes/resume-bot/tracker.json`
- `~/.hermes/resume-bot/errors.log`
- `/tmp/resume-bot/`（中间文件与输出）

## 安全与控制建议

- 仅允许管理员或授权 ID 使用（白名单）
- 菜单固定：`/start /new /clear /status /reset`
- 关闭 tool_progress，避免暴露调试细节
- 与 `approvals.mode: off` 结合时，仅用于可信内部场景
