# resume-bot

可安装即用的 Hermes Skill：Telegram 收简历 → TEK 模板标准化 → 回传 DOCX（默认不发邮件）。

## 核心能力

- 支持 PDF / DOCX / TXT 简历文本提取
- 将结构化 JSON 填充到 `muban/简历模板 TEK.docx`
- 使用 himalaya 发送带附件邮件
- 更新 `tracker.json` 和 `errors.log`
- 适配 Telegram + Hermes channel_prompts 工作流

## 快速开始

```bash
python3 scripts/resume_bot_pipeline.py bootstrap-uv
python3 scripts/resume_bot_pipeline.py init-llm --deepseek-api-key "<DEEPSEEK_API_KEY>"
python3 scripts/resume_bot_pipeline.py --help
```

`resume_bot_pipeline.py` 会自动使用 `uv` 创建并复用当前 skill 的 `.venv`，首次自动安装依赖，后续无需重复安装。
若仓库存在 `requirements.lock.txt`，会优先按锁定版本安装，保证不同 Hermes 节点环境一致。
如未安装 `uv`，请先参考官方文档安装：<https://docs.astral.sh/uv/getting-started/installation/>

## Hermes 一次性配置

参考目录 `deploy/hermes/`：

- `env.sample`：`.env` 变量示例
- `config.yaml.snippet`：`config.yaml` 合并片段
- `menu.json`：Telegram 菜单单一配置源
- `README.md`：集成步骤与命令示例

生成 bot 目录（含 menu 副本与 quick_commands 片段）：

```bash
python3 scripts/generate_hermes_bot_dir.py
```

更新到 Hermes 安装目录（拉最新代码并刷新环境）：

```bash
bash scripts/update_hermes_skill.sh --restart-gateway
```

## 标准流水线命令

```bash
# 1) 提取文本
python3 scripts/resume_bot_pipeline.py extract \
  --resume "/tmp/resume-bot/input_resume.pdf" \
  --out-text "/tmp/resume-bot/resume_text.txt"

# 2) DeepSeek 解析 + 有效性校验
python3 scripts/resume_bot_pipeline.py llm-parse \
  --text-file "/tmp/resume-bot/resume_text.txt" \
  --out-json "/tmp/resume-bot/resume_data.json"

# 3) 生成并发送
python3 scripts/resume_bot_pipeline.py process \
  --resume "/tmp/resume-bot/input_resume.pdf" \
  --json "/tmp/resume-bot/resume_data.json" \
  --output-docx "/tmp/resume-bot/张三-TEK-标准简历.docx" \
  --candidate-name "张三"
```

默认会自动删除临时输入文件（上传原简历、`resume_data.json`、`resume_email.mml`），避免 `/tmp/resume-bot/` 堆积。

默认不发邮件，直接在 Telegram 回传文件。若需要邮件发送，显式追加：

```bash
--enable-email --to-email "target@example.com"
```

回传 Telegram 完成后，可再执行：

```bash
python3 scripts/resume_bot_pipeline.py cleanup \
  --paths "/tmp/resume-bot/张三-TEK-标准简历.docx" "/tmp/resume-bot/resume_text.txt"
```

## 项目结构

```text
.
├── SKILL.md
├── fill_resume.py
├── scripts/
│   └── resume_bot_pipeline.py
├── deploy/
│   └── hermes/
│       ├── README.md
│       ├── env.sample
│       └── config.yaml.snippet
├── src/
│   ├── config.py
│   ├── extractor.py
│   ├── filler.py
│   ├── utils.py
│   └── test_data.py
└── muban/
    └── 简历模板 TEK.docx
```

## License

MIT
