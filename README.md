# resume-bot

一个双形态项目：

- **Hermes Skill**：Telegram 收简历 -> 解析 -> 生成 TEK DOCX -> 回传
- **Web 应用**：上传简历后在线转换，含 `/stats` 与 `/nvwa` 管理页

## 导航

- [阅读建议](#阅读建议)
- [Web 子项目入口](#web-子项目入口)
- [Hermes Skill 入口](#hermes-skill-入口)
- [Hermes 快速开始](#hermes-快速开始)
- [Hermes 一次性配置](#hermes-一次性配置)
- [标准流水线命令](#标准流水线命令)
- [项目结构](#项目结构)
- [License](#license)

## 阅读建议

- 只关心 Web 部署与运维：先读 `web/README.md`
- 只关心 Telegram/Hermes：先读本文件的 Hermes 章节
- 想看架构演进：读 `web/ARCHITECTURE_BASELINE.md` 与 `web/IMPLEMENTATION_ROADMAP.md`

## Web 子项目入口

- Web 总文档：`web/README.md`
- 架构基线：`web/ARCHITECTURE_BASELINE.md`
- 实施路线图：`web/IMPLEMENTATION_ROADMAP.md`
- 设计说明：`web/DESIGN.md`
- 后端入口：`web/backend/app.py`
- 前端入口：`web/frontend/src/App.jsx`
- Linux 部署入口：`deploy/linux/install-from-github.sh`

## Hermes Skill 入口

- 技能入口：`SKILL.md`
- 核心流水线：`scripts/resume_bot_pipeline.py`
- 部署配置：`deploy/hermes/README.md`

## Hermes 快速开始

```bash
python3 scripts/resume_bot_pipeline.py bootstrap-uv
python3 scripts/resume_bot_pipeline.py init-llm --deepseek-api-key "<DEEPSEEK_API_KEY>"
python3 scripts/resume_bot_pipeline.py --help
```

说明：

- `resume_bot_pipeline.py` 会自动使用 `uv` 创建并复用 `.venv`
- 存在 `requirements.lock.txt` 时优先按锁定版本安装
- 未安装 `uv` 可参考 [官方安装文档](https://docs.astral.sh/uv/getting-started/installation/)

## Hermes 一次性配置

目录：`deploy/hermes/`

- `env.sample`：`.env` 变量示例
- `config.yaml.snippet`：`config.yaml` 合并片段
- `menu.json`：Telegram 菜单单一配置源
- `README.md`：完整集成步骤

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

# 3) 生成并发送（默认不发邮件）
python3 scripts/resume_bot_pipeline.py process \
  --resume "/tmp/resume-bot/input_resume.pdf" \
  --json "/tmp/resume-bot/resume_data.json" \
  --output-docx "/tmp/resume-bot/张三-TEK-标准简历.docx" \
  --candidate-name "张三"
```

附加说明：

- 默认自动清理临时输入文件，避免 `/tmp/resume-bot/` 堆积
- 若需邮件发送，显式追加：

```bash
--enable-email --to-email "target@example.com"
```

- 回传 Telegram 完成后，可手动清理残留：

```bash
python3 scripts/resume_bot_pipeline.py cleanup \
  --paths "/tmp/resume-bot/张三-TEK-标准简历.docx" "/tmp/resume-bot/resume_text.txt"
```

## 项目结构

```text
.
├── SKILL.md
├── scripts/
│   ├── resume_bot_pipeline.py
│   ├── generate_hermes_bot_dir.py
│   └── update_hermes_skill.sh
├── deploy/
│   ├── hermes/
│   └── linux/
├── src/
│   ├── extractor.py
│   ├── filler.py
│   └── ...
├── web/
│   ├── README.md
│   ├── backend/
│   └── frontend/
└── muban/
    └── 简历模板 TEK.docx
```

## License

MIT
