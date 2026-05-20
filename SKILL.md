---
name: resume-fill
description: 简历 PDF → TEK Word 模板自动填充。用户发送 PDF 简历路径，Hermes 自动解析并生成 .docx。
category: productivity
---

# 简历自动填充 (resume-fill)

将 PDF 简历按照 TEK 公司模板自动转换为格式统一的 Word 文档。

## 安装

```bash
# 作为 Hermes skill 安装
hermes skill install github:yourname/resume-fill

# 或手动安装依赖
pip install -r requirements.txt
```

## 依赖

- PyMuPDF (fitz) — PDF 文本提取
- python-docx — Word 模板操作

## 用法

### 方式 1：配合 Hermes 使用（推荐）

在 Hermes 中直接发送 PDF 简历路径：

```
转换简历 /path/to/简历.pdf
```

Hermes 会自动：
1. 提取 PDF 文本
2. LLM 解析为结构化 JSON
3. 调用 `fill_resume.py --json`
4. 输出到 `result/YYYYMMDD/`

### 方式 2：命令行独立使用

```bash
# 从 JSON 数据填充
python3 fill_resume.py --json data.json

# 指定输出路径
python3 fill_resume.py --json data.json -o /path/to/output.docx

# 内置测试数据验证
python3 fill_resume.py --test
```

## 项目结构

```
resume-fill/
├── muban/
│   └── 简历模板 TEK.docx      # Word 模板
├── src/
│   ├── config.py              # 路径和常量配置
│   ├── utils.py               # 字体、段落操作工具
│   ├── extractor.py           # PDF 文本提取
│   ├── filler.py              # 模板填充核心
│   └── test_data.py           # 内置测试数据
├── result/                    # 输出目录（运行时自动创建）
│   └── YYYYMMDD/
│       └── xxx_简历_TEK.docx
├── fill_resume.py             # CLI 入口
├── requirements.txt
└── SKILL.md
```

## 输入 JSON 数据结构

```json
{
    "resource_info": {
        "city": "所在城市",
        "language": "语言能力",
        "birth": "YYYY/MM",
        "gender": "男/女",
        "interview_time": "可面试时间",
        "status": "在职/离职"
    },
    "summary_items": ["技能/优势描述...", ...],
    "education": [
        {"period": "YYYY.MM – YYYY.MM", "school": "学校", "degree": "学位, 专业"}
    ],
    "employment_history": [
        {"time": "2021.03 – Now", "employer": "公司简称", "role": "职位"}
    ],
    "roles": [
        {
            "period": "2021.03-至今",
            "company": "公司全称",
            "title": "职位",
            "responsibilities": ["职责1", "职责2"],
            "achievements": ["业绩1"]
        }
    ],
    "projects": [
        {
            "period": "2021.03-至今",
            "name": "项目名",
            "description": "项目描述",
            "tech_stack": "技术栈",
            "responsibilities": ["职责1"],
            "achievements": ["业绩1"]
        }
    ]
}
```

## 模板说明

模板 `muban/简历模板 TEK.docx` 是 TEK 公司的标准简历模板，
包含 Resource Information / Summary / Education / Employment History /
Role and Accomplishment / Project Experience 等模块。

如需更换模板，替换 `muban/` 目录下的文件即可。
