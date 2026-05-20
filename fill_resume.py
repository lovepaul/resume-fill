#!/usr/bin/env python3
"""
fill_resume — 简历自动填充 CLI
===============================
从结构化 JSON 数据按 TEK 模板生成 Word 简历。

用法:
  python3 fill_resume.py --json data.json         # 从 JSON 填充（Hermes 工作流）
  python3 fill_resume.py --json data.json -o out.docx
  python3 fill_resume.py --test                    # 内置测试数据
  python3 fill_resume.py resume.pdf                # 仅提取 PDF 文本

Hermes 工作流:
  用户发送 PDF 路径 → Hermes 解析为 JSON
  → fill_resume.py --json data.json → result/YYYYMMDD/xxx.docx
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

from src.extractor import extract_pdf_text
from src.filler import fill_template
from src.config import PROJECT_ROOT, TEMPLATE_PATH, RESULT_DIR


def make_output_path(source_name: str, output_arg: str = None) -> Path:
    """生成输出路径：result/YYYYMMDD/ 下"""
    if output_arg:
        return Path(output_arg)

    today = datetime.now().strftime("%Y%m%d")
    out_dir = RESULT_DIR / today
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = Path(source_name).stem
    return out_dir / f"{stem}_简历_TEK.docx"


# ── 入口 ──

def main():
    # --json 模式（Hermes 调用）
    if len(sys.argv) >= 2 and sys.argv[1] == "--json":
        if len(sys.argv) < 3:
            print("用法: fill_resume.py --json <data.json> [-o output.docx]")
            sys.exit(1)

        json_path = sys.argv[2]
        if not os.path.exists(json_path):
            print(f"❌ JSON 文件不存在: {json_path}")
            sys.exit(1)

        output_arg = None
        if "-o" in sys.argv:
            idx = sys.argv.index("-o")
            if idx + 1 < len(sys.argv):
                output_arg = sys.argv[idx + 1]

        output_path = make_output_path(json_path, output_arg)

        print("=" * 60)
        print("  简历自动填充系统")
        print("=" * 60)

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        print(f"\n📋 加载数据: {json_path}")
        print(f"   Summary: {len(data.get('summary_items', []))} 条")
        print(f"   工作经历: {len(data.get('roles', []))} 段")
        print(f"   项目经历: {len(data.get('projects', []))} 个")

        fill_template(TEMPLATE_PATH, data, output_path)

        output_size = os.path.getsize(str(output_path))
        print(f"\n📊 输出: {output_size:,} bytes")
        print(f"📁 {output_path}")
        return

    # --test 模式（内置测试数据）
    if len(sys.argv) >= 2 and sys.argv[1] == "--test":
        output_arg = None
        if "-o" in sys.argv:
            idx = sys.argv.index("-o")
            if idx + 1 < len(sys.argv):
                output_arg = sys.argv[idx + 1]

        output_path = make_output_path("test_resume", output_arg)

        print("=" * 60)
        print("  简历自动填充系统 — TEST 模式")
        print("=" * 60)

        from src.test_data import get_test_data
        data = get_test_data()
        print(f"\n📋 使用内置测试数据")
        fill_template(TEMPLATE_PATH, data, output_path)

        output_size = os.path.getsize(str(output_path))
        print(f"\n📊 输出: {output_size:,} bytes")
        print(f"📁 {output_path}")
        return

    # PDF 模式（仅提取文本）
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 fill_resume.py --json data.json       # 从 JSON 填充")
        print("  python3 fill_resume.py --test                 # 内置测试数据")
        print("  python3 fill_resume.py resume.pdf             # 提取 PDF 文本")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f"❌ 文件不存在: {pdf_path}")
        sys.exit(1)

    print("=" * 60)
    print("  简历 PDF 文本提取")
    print("=" * 60)
    print(f"\n📥 {pdf_path}")
    pdf_text = extract_pdf_text(pdf_path)
    print(f"  提取 {len(pdf_text)} 字符\n")
    print("─" * 60)
    print(pdf_text[:3000])
    if len(pdf_text) > 3000:
        print(f"\n... (共 {len(pdf_text)} 字符，已截断前 3000)")
    print("─" * 60)
    print("\n💡 请通过 Hermes 客户端发送此 PDF 路径，")
    print("   Hermes 会自动解析内容并调用 --json 模式生成简历。")


if __name__ == "__main__":
    main()
