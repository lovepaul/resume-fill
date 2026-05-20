"""
项目配置 — 所有路径和常量统一管理
"""
from pathlib import Path
from docx.shared import Pt

# 项目根目录 = src/config.py 的上两级
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 模板路径
TEMPLATE_PATH = PROJECT_ROOT / "muban" / "简历模板 TEK.docx"

# 输出根目录
RESULT_DIR = PROJECT_ROOT / "result"

# 字体设置（与金标准对齐）
FONT_NAME = "Microsoft YaHei"
FONT_SIZE = Pt(9)  # 114300 EMU
