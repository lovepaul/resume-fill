#!/usr/bin/env python3
"""
根据 deploy/hermes/menu.json 生成 Hermes bot 目录与配置片段。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_MENU_FILE = Path("deploy/hermes/menu.json")
DEFAULT_TARGET_DIR = Path.home() / ".hermes" / "bots" / "resume-bot"


def load_menu(menu_file: Path) -> dict:
    if not menu_file.exists():
        raise FileNotFoundError(f"menu 文件不存在: {menu_file}")
    data = json.loads(menu_file.read_text(encoding="utf-8"))
    commands = data.get("menu_commands", [])
    if not commands:
        raise ValueError("menu_commands 不能为空")
    seen = set()
    for item in commands:
        cmd = item.get("command", "")
        if not cmd.startswith("/"):
            raise ValueError(f"非法命令（必须以 / 开头）: {cmd}")
        if cmd in seen:
            raise ValueError(f"重复命令: {cmd}")
        seen.add(cmd)
        cmd_type = item.get("type", "")
        if cmd_type not in {"exec", "alias"}:
            raise ValueError(f"{cmd} 的 type 必须是 exec 或 alias")
        if cmd_type == "exec" and not item.get("exec"):
            raise ValueError(f"{cmd} 的 exec 命令不能为空")
        if cmd_type == "alias" and not item.get("target"):
            raise ValueError(f"{cmd} 的 alias target 不能为空")
    return data


def render_quick_commands_yaml(menu_data: dict) -> str:
    lines = ["quick_commands:"]
    for item in menu_data["menu_commands"]:
        key = item["command"].lstrip("/")
        cmd_type = item["type"]
        lines.append(f"  {key}:")
        lines.append(f"    type: {cmd_type}")
        if cmd_type == "exec":
            lines.append(f"    command: {json.dumps(item['exec'], ensure_ascii=False)}")
        else:
            lines.append(f"    target: {item['target']}")
    return "\n".join(lines) + "\n"


def render_menu_markdown(menu_data: dict) -> str:
    rows = ["# Bot Menu", ""]
    rows.append(f"- bot_name: `{menu_data.get('bot_name', 'resume-bot')}`")
    rows.append(
        f"- telegram.custom_menu: `{menu_data.get('telegram', {}).get('custom_menu', True)}`"
    )
    rows.append(
        f"- telegram.tool_progress: `{menu_data.get('telegram', {}).get('tool_progress', False)}`"
    )
    rows.append("")
    rows.append("## Commands")
    rows.append("")
    for item in menu_data["menu_commands"]:
        rows.append(
            f"- `{item['command']}` ({item.get('type', 'unknown')}): {item.get('description', '')}"
        )
    rows.append("")
    return "\n".join(rows)


def generate(menu_file: Path, target_dir: Path) -> None:
    menu_data = load_menu(menu_file)
    target_dir.mkdir(parents=True, exist_ok=True)

    menu_copy = target_dir / "menu.json"
    quick_commands = target_dir / "quick_commands.generated.yaml"
    menu_md = target_dir / "BOT-MENU.md"

    menu_copy.write_text(
        json.dumps(menu_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    quick_commands.write_text(render_quick_commands_yaml(menu_data), encoding="utf-8")
    menu_md.write_text(render_menu_markdown(menu_data), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "target_dir": str(target_dir),
                "generated_files": [
                    str(menu_copy),
                    str(quick_commands),
                    str(menu_md),
                ],
            },
            ensure_ascii=False,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Hermes bot directory from menu")
    parser.add_argument("--menu-file", type=Path, default=DEFAULT_MENU_FILE)
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generate(menu_file=args.menu_file, target_dir=args.target_dir)


if __name__ == "__main__":
    main()
