# resume-fill

简历 PDF → TEK Word 模板自动填充工具。

配合 [Hermes Agent](https://github.com/nousresearch/hermes-agent) 使用，
可自动将候选人投递的 PDF 简历按公司标准模板转换为格式统一的 Word 文档。

## 快速开始

```bash
pip install -r requirements.txt
python3 fill_resume.py --test
```

## Hermes 集成

作为 Hermes skill 安装后，在对话中直接发送 PDF 路径即可：

```
转换简历 /path/to/简历.pdf
```

Hermes 会自动完成 PDF 解析 → JSON 结构化 → 模板填充全流程。

## License

MIT
