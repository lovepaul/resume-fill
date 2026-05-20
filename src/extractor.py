"""
PDF 文本提取
"""
import fitz  # PyMuPDF


def extract_pdf_text(pdf_path: str) -> str:
    """使用 PyMuPDF 提取 PDF 全文"""
    doc = fitz.open(pdf_path)
    full_text = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            full_text.append(text)
    doc.close()
    return "\n".join(full_text)
