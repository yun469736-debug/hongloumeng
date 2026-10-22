# -*- coding: utf-8 -*-
"""
text_processor.py —— 文本处理工具

将常见格式的文件（Excel / Word / TXT / PDF / CSV / Markdown / HTML 等）
统一提取为纯文本，供后续 embedding 与知识库切割使用。

依赖库（按需安装）：
    pip install openpyxl python-docx pdfplumber beautifulsoup4
    若不想安装 pdfplumber，可安装轻量的 pypdf：pip install pypdf

用法示例：
    from utils.text_processor import extract_text, batch_extract_text

    text = extract_text("知识库/产品手册.pdf")
    docs = batch_extract_text("知识库目录")      # {文件路径: 文本}
"""

from __future__ import annotations

import csv
import html as _html
import io
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Union

PathLike = Union[str, Path]

# 解码候选顺序：优先 UTF-8，其次兼容 Windows 常见中文编码
_ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin-1")


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------
def _decode_bytes(raw: bytes) -> str:
    """对字节流按常见编码依次尝试解码，全部失败时忽略无法解码的字节。"""
    for enc in _ENCODING_CANDIDATES:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="ignore")


def _normalize(text: str) -> str:
    """清洗：去除行尾空白、把连续空行折叠为单个空行、去掉首尾空白。"""
    lines = [ln.rstrip() for ln in text.splitlines()]
    out: List[str] = []
    blank = 0
    for ln in lines:
        if not ln.strip():
            blank += 1
            if blank > 1:
                continue
        else:
            blank = 0
        out.append(ln)
    return "\n".join(out).strip()


def _require(module: str, pip_name: str):
    """惰性导入依赖库，缺失时给出可执行的安装提示。"""
    try:
        return __import__(module)
    except ImportError:
        raise ImportError(
            f"解析此类文件需要 {pip_name}，请先执行：pip install {pip_name}"
        ) from None


# ---------------------------------------------------------------------------
# 各格式读取函数（统一返回 str 文本）
# ---------------------------------------------------------------------------
def read_txt(path: PathLike) -> str:
    """读取纯文本：txt / log / 代码等。"""
    return _decode_bytes(Path(path).read_bytes())


def read_markdown(path: PathLike) -> str:
    """Markdown 按纯文本读取（结构化的标题切割见 knowledge_splitter）。"""
    return read_txt(path)


def read_csv(
    path: PathLike,
    has_header: bool = True,
    separator: Optional[str] = None,
) -> str:
    """
    读取 CSV。默认把第一行作为表头，其余行整理为“字段：值”形式，
    更利于检索与切割；表头缺失时退化为简单的空格拼接。
    """
    text = _decode_bytes(Path(path).read_bytes())
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect if separator is None else None)
    if separator is not None:
        reader = csv.reader(io.StringIO(text), delimiter=separator)

    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return ""

    lines: List[str] = []
    header = rows[0] if (has_header and rows) else None
    body = rows[1:] if header else rows
    for row in body:
        if header and len(header) == len(row):
            pairs = [f"{h}：{c}" for h, c in zip(header, row) if c and c.strip()]
            lines.append("；".join(pairs))
        else:
            lines.append(" ".join(c.strip() for c in row if c.strip()))
    return "\n".join(lines)


def read_xlsx(
    path: PathLike,
    sheet_names: Optional[Sequence[str]] = None,
    include_sheet_name: bool = True,
) -> str:
    """读取 xlsx：遍历（或指定）工作表，逐行拼接非空单元格。"""
    openpyxl = _require("openpyxl", "openpyxl")
    wb = openpyxl.load_workbook(Path(path), read_only=True, data_only=True)
    sections: List[str] = []
    try:
        targets = list(sheet_names) if sheet_names else list(wb.sheetnames)
        for name in targets:
            ws = wb[name]
            lines: List[str] = []
            for row in ws.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    lines.append(" ".join(cells))
            body = "\n".join(lines)
            sections.append(f"【工作表：{name}】\n{body}" if include_sheet_name else body)
    finally:
        wb.close()
    return "\n\n".join(sections)


def read_docx(path: PathLike) -> str:
    """读取 docx：段落 + 表格（合并单元格去重）。"""
    docx = _require("docx", "python-docx")
    document = docx.Document(Path(path))
    parts = [p.text.strip() for p in document.paragraphs if p.text.strip()]

    for table in document.tables:
        for row in table.rows:
            seen: List[int] = []
            cells: List[str] = []
            for cell in row.cells:
                if id(cell) in seen:  # 横向合并的单元格会重复出现，去重
                    continue
                seen.append(id(cell))
                t = cell.text.strip()
                if t:
                    cells.append(t)
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def read_pdf(path: PathLike, include_page_marks: bool = False) -> str:
    """
    读取 PDF：优先使用 pdfplumber，缺失时回退 pypdf。
    默认不保留页码标记（避免“第 N 页”噪音混入正文）。
    """
    pages: List[str] = []
    try:
        pdfplumber = _require("pdfplumber", "pdfplumber")
        with pdfplumber.open(Path(path)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
    except ImportError:
        pypdf = _require("pypdf", "pypdf")  # 若 pdfplumber 缺失则用 pypdf 兜底
        reader = pypdf.PdfReader(str(path))
        pages = [p.extract_text() or "" for p in reader.pages]

    parts: List[str] = []
    for i, page_text in enumerate(pages, start=1):
        if page_text.strip():
            parts.append(f"[第 {i} 页]\n{page_text}" if include_page_marks else page_text)
    return "\n".join(parts)


def read_html(path: PathLike) -> str:
    """读取 html：优先用 BeautifulSoup，缺失时回退正则去标签。"""
    raw = Path(path).read_bytes()
    try:
        bs4 = _require("bs4", "beautifulsoup4")
    except ImportError:
        return _html_fallback(raw)

    soup = bs4.BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    return _normalize(soup.get_text("\n"))


def _html_fallback(raw: bytes) -> str:
    """无 BeautifulSoup 时的简易 HTML 清洗。"""
    text = _decode_bytes(raw)
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    return _normalize(_html.unescape(text))


def read_doc(path: PathLike) -> str:
    """老版 Word 二进制 .doc 无法直接解析，给出转换指引。"""
    raise NotImplementedError(
        ".doc 是旧版 Word 二进制格式，请先用 Word / WPS / LibreOffice 另存为 .docx，"
        "或执行：soffice --headless --convert-to docx \"xxx.doc\"，然后再解析。"
    )


def read_xls(path: PathLike) -> str:
    """老版 Excel .xls 需先转换为 .xlsx（或用 pandas+xlrd）。"""
    raise NotImplementedError(
        ".xls 是旧版 Excel 格式，请先用 Excel / WPS 另存为 .xlsx 后再解析，"
        "或执行：soffice --headless --convert-to xlsx \"xxx.xls\"。"
    )


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
_EXTRACTORS: Dict[str, Callable[[PathLike], str]] = {
    ".txt": read_txt,
    ".log": read_txt,
    ".py": read_txt,
    ".md": read_markdown,
    ".markdown": read_markdown,
    ".csv": read_csv,
    ".xlsx": read_xlsx,
    ".xls": read_xls,
    ".docx": read_docx,
    ".doc": read_doc,
    ".pdf": read_pdf,
    ".html": read_html,
    ".htm": read_html,
}


def extract_text(path: PathLike) -> str:
    """
    根据扩展名自动选择解析器，把单个文件提取为纯文本。
    不支持/无法解析的格式会抛出带提示的异常。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"文件不存在：{p}")
    if not p.is_file():
        raise ValueError(f"不是文件：{p}")

    suffix = p.suffix.lower()
    handler = _EXTRACTORS.get(suffix)
    if handler is None:
        supported = "、".join(sorted(_EXTRACTORS))
        raise ValueError(f"暂不支持文件类型「{suffix}」，当前支持：{supported}")
    return _normalize(handler(p))


def batch_extract_text(
    target: PathLike,
    suffixes: Optional[Sequence[str]] = None,
    recursive: bool = True,
    skip_errors: bool = True,
) -> Dict[str, str]:
    """
    批量提取：target 为单文件或目录。
    返回 {文件绝对路径: 文本}，默认静默跳过不支持/读取失败/内容为空的文件。

    target 为目录时可按 suffixes 过滤（如 {".pdf", ".docx"}）。
    """
    p = Path(target)
    files: List[Path] = []
    if p.is_dir():
        it: Iterable[Path] = p.rglob("*") if recursive else p.glob("*")
        files = [f for f in it if f.is_file()]
    elif p.is_file():
        files = [p]
    else:
        raise FileNotFoundError(f"路径不存在：{p}")

    results: Dict[str, str] = {}
    for f in files:
        suffix = f.suffix.lower()
        if suffixes and suffix not in suffixes:
            continue
        if suffix not in _EXTRACTORS:
            continue
        try:
            text = extract_text(f)
        except Exception:
            if not skip_errors:
                raise
            continue
        if text.strip():
            results[str(f.resolve())] = text
    return results

