"""Convert local documents into inspectable workflow text."""

import shutil
import subprocess
from pathlib import Path

TEXT_TYPES = {".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml", ".rst"}
SUPPORTED = TEXT_TYPES | {".pdf", ".docx", ".doc", ".jpg", ".jpeg", ".png"}


def extract(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_TYPES:
        text = path.read_text(encoding="utf-8-sig")
    elif suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ValueError("请先解密 PDF 后再上传")
        if len(reader.pages) > 200:
            raise ValueError("PDF 最多 200 页")
        pages = [page.extract_text() or "" for page in reader.pages]
        if any(not page.strip() for page in pages):
            raise ValueError("PDF 含无法提取文字的页面，请先 OCR 或转成图片上传")
        text = "\n\n".join(pages)
    elif suffix == ".docx":
        from docx import Document
        from docx.table import Table

        document = Document(str(path))
        text = "\n".join(
            "\n".join("\t".join(cell.text for cell in row.cells) for row in block.rows)
            if isinstance(block, Table)
            else block.text
            for block in document.iter_inner_content()
        )
    elif suffix == ".doc":
        if not shutil.which("textutil"):
            raise ValueError("旧版 .doc 需要 macOS textutil；请转存为 .docx")
        text = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
    elif suffix in {".jpg", ".jpeg", ".png"}:
        if not shutil.which("tesseract"):
            raise ValueError("图片需要本机 tesseract OCR，请安装后重试")
        languages = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        language = "chi_sim+eng" if "chi_sim" in languages else "eng"
        text = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", language],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        ).stdout
    else:
        raise ValueError("不支持的文件类型")
    if not text.strip():
        raise ValueError("没有提取到文字，请提供可读文字或 OCR 结果")
    if len(text.encode()) > 1_000_000:
        raise ValueError("提取文字超过 1 MB，请拆分文件")
    return text
