#!/usr/bin/env bash
set -euo pipefail

# 一键更新 Hermes skill：
# 1) 拉取远程最新代码（fast-forward）
# 2) 使用 uv 重新 bootstrap skill .venv
# 3) 重新生成 bot 菜单片段
# 4) 可选重启 Hermes gateway

SKILL_DIR="${HERMES_SKILL_DIR:-$HOME/.hermes/skills/resume-bot}"
BRANCH="${HERMES_SKILL_BRANCH:-main}"
RESTART_GATEWAY=false
ALLOW_DIRTY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skill-dir)
      SKILL_DIR="$2"
      shift 2
      ;;
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    --restart-gateway)
      RESTART_GATEWAY=true
      shift
      ;;
    --allow-dirty)
      ALLOW_DIRTY=true
      shift
      ;;
    -h|--help)
      cat <<'EOF'
用法:
  bash scripts/update_hermes_skill.sh [选项]

选项:
  --skill-dir <path>       指定 Hermes skill 安装目录（默认: ~/.hermes/skills/resume-bot）
  --branch <name>          指定更新分支（默认: main）
  --restart-gateway        更新后自动执行 hermes gateway restart
  --allow-dirty            允许存在未提交改动时继续更新（默认遇到脏工作区会退出）
  -h, --help               查看帮助
EOF
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "$SKILL_DIR" ]]; then
  echo "❌ 目录不存在: $SKILL_DIR" >&2
  exit 1
fi

if [[ ! -d "$SKILL_DIR/.git" ]]; then
  echo "❌ 不是 Git 仓库: $SKILL_DIR" >&2
  exit 1
fi

echo "📂 Skill 目录: $SKILL_DIR"
cd "$SKILL_DIR"

if [[ "$ALLOW_DIRTY" != "true" ]]; then
  DIRTY="$(git status --porcelain)"
  if [[ -n "$DIRTY" ]]; then
    echo "❌ 检测到未提交改动，已停止更新。"
    echo "   可先提交/清理后重试，或使用 --allow-dirty 强制继续。"
    exit 2
  fi
fi

echo "🔄 拉取远程分支: origin/$BRANCH"
git fetch origin "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "🐍 更新 skill 运行环境（uv）"
python3 scripts/resume_bot_pipeline.py bootstrap-uv

echo "🧩 重新生成 bot 菜单片段"
python3 scripts/generate_hermes_bot_dir.py

if [[ "$RESTART_GATEWAY" == "true" ]]; then
  echo "♻️ 重启 Hermes gateway"
  hermes gateway restart
fi

echo "✅ 更新完成"
