import re
from dataclasses import dataclass
from typing import List, Tuple

from app.core.config import settings
from app.ingestion.parser import ExtractedPage


@dataclass
class TextChunk:
    content: str
    page_number: int | None
    chunk_index: int
    metadata: dict


# 章节标题检测：Markdown 标题、中文序号、阿拉伯数字序号、第X章/节
_HEADER_RE = re.compile(
    r"^(?:"
    r"#{1,6}\s+"  # Markdown 标题
    r"|[一二三四五六七八九十百千]+[、.．]\s*"  # 一、二、三...
    r"|\d+(?:\.\d+)*[、.．]\s*"  # 1. 1.1. 2.1、
    r"|第[一二三四五六七八九十百千\d]+[章节][：:.\s]*"  # 第一章、第2节
    r")",
    re.MULTILINE,
)


# 病历标题检测：病例 1、病例一、Case 1、案例 1、案例一等
_CASE_RE = re.compile(
    r"^(?:病例|案例|Case)\s*[一二三四五六七八九十百千\d]+[、.．:\s]*",
    re.MULTILINE | re.IGNORECASE,
)


def _is_header_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(_HEADER_RE.match(stripped))


def _is_case_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(_CASE_RE.match(stripped))


def _split_by_headers(text: str) -> List[Tuple[str | None, str]]:
    """按章节标题切分，返回 [(标题, 正文), ...]。"""
    sections: List[Tuple[str | None, str]] = []
    current_header: str | None = None
    current_body_lines: List[str] = []

    for line in text.split("\n"):
        if _is_header_line(line):
            # 结束上一段
            if current_header is not None or current_body_lines:
                body = "\n".join(current_body_lines).strip()
                sections.append((current_header, body))
            current_header = line.strip()
            current_body_lines = []
        else:
            current_body_lines.append(line)

    # 收尾
    if current_header is not None or current_body_lines:
        body = "\n".join(current_body_lines).strip()
        sections.append((current_header, body))

    return sections


def _split_by_cases(text: str) -> List[Tuple[str | None, str, int]]:
    """按病历标题切分，返回 [(标题, 正文, 起始偏移), ...]。"""
    matches = list(_CASE_RE.finditer(text))
    sections: List[Tuple[str | None, str, int]] = []

    if not matches:
        return sections

    # 第一个病历标题之前的文本作为前言（如果有）
    first_start = matches[0].start()
    if first_start > 0:
        preface = text[:first_start].strip()
        if preface:
            sections.append((None, preface, 0))

    for i, m in enumerate(matches):
        header = m.group(0).strip()
        start = m.start()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        sections.append((header, body, start))

    return sections


def _concat_pages_text(pages: List[ExtractedPage]) -> Tuple[str, List[Tuple[int, int | None]]]:
    """把多页文本拼接起来，并记录每页起始偏移，方便回溯页码。"""
    parts: List[str] = []
    breaks: List[Tuple[int, int | None]] = []
    offset = 0
    for page in pages:
        breaks.append((offset, page.page_number))
        parts.append(page.text)
        offset += len(page.text) + 1  # +1 是换行符
    return "\n".join(parts), breaks


def _page_for_offset(breaks: List[Tuple[int, int | None]], offset: int) -> int | None:
    """根据字符偏移找到对应的页码。"""
    page: int | None = None
    for start, p in breaks:
        if start <= offset:
            page = p
        else:
            break
    return page


def _split_text_into_units(text: str, max_unit_length: int) -> List[str]:
    """把文本拆成语义单元（段落 > 行 > 句子），尽量不在句子中间切断。"""
    units = [u.strip() for u in text.split("\n\n") if u.strip()]

    refined: List[str] = []
    for unit in units:
        if len(unit) > max_unit_length:
            lines = [line.strip() for line in unit.split("\n") if line.strip()]
            refined.extend(lines)
        else:
            refined.append(unit)

    final: List[str] = []
    for unit in refined:
        if len(unit) > max_unit_length:
            final.extend(_split_by_sentences(unit))
        else:
            final.append(unit)

    return final


def _split_by_sentences(text: str) -> List[str]:
    parts = re.split(r"([。\.\?？!！;；]\s*)", text)
    sentences: List[str] = []
    i = 0
    while i < len(parts):
        sentence = parts[i]
        if i + 1 < len(parts):
            sentence += parts[i + 1]
            i += 2
        else:
            i += 1
        sentence = sentence.strip()
        if sentence:
            sentences.append(sentence)
    return sentences or [text]


def _group_units_into_chunks(
    units: List[str],
    header: str | None,
    page_number: int | None,
    source_type: str,
    start_index: int,
    max_chunk_size: int,
) -> Tuple[List[TextChunk], int]:
    """把同一章节内的语义单元组合成 chunk，必要时保留标题。"""
    chunks: List[TextChunk] = []
    current_units: List[str] = []
    current_length = 0
    index = start_index

    header_prefix = f"{header}\n" if header else ""
    prefix_len = len(header_prefix)

    for unit in units:
        unit_len = len(unit)

        # 单个单元就超限：单独成块，前面仍带标题
        if prefix_len + unit_len > max_chunk_size:
            if current_units:
                content = header_prefix + "\n".join(current_units)
                chunks.append(
                    TextChunk(
                        content=content.strip(),
                        page_number=page_number,
                        chunk_index=index,
                        metadata={
                            "source_type": source_type,
                            "strategy": "header_aware",
                            "header": header,
                        },
                    )
                )
                index += 1
                current_units = []
                current_length = 0

            content = (header_prefix + unit).strip()
            chunks.append(
                TextChunk(
                    content=content,
                    page_number=page_number,
                    chunk_index=index,
                    metadata={
                        "source_type": source_type,
                        "strategy": "header_aware",
                        "header": header,
                    },
                )
            )
            index += 1
            continue

        # 加入当前 chunk 会超限，先结束当前 chunk
        if current_units and current_length + unit_len + 1 > max_chunk_size - prefix_len:
            content = header_prefix + "\n".join(current_units)
            chunks.append(
                TextChunk(
                    content=content.strip(),
                    page_number=page_number,
                    chunk_index=index,
                    metadata={
                        "source_type": source_type,
                        "strategy": "header_aware",
                        "header": header,
                    },
                )
            )
            index += 1
            current_units = []
            current_length = 0

        current_units.append(unit)
        current_length += unit_len + 1

    if current_units:
        content = header_prefix + "\n".join(current_units)
        chunks.append(
            TextChunk(
                content=content.strip(),
                page_number=page_number,
                chunk_index=index,
                metadata={
                    "source_type": source_type,
                    "strategy": "header_aware",
                    "header": header,
                },
            )
        )
        index += 1

    return chunks, index


def _chunk_by_headers(pages: List[ExtractedPage], max_chunk_size: int) -> List[TextChunk]:
    source_type = pages[0].source_type if pages else ""
    chunks: List[TextChunk] = []
    index = 0

    for page in pages:
        sections = _split_by_headers(page.text)
        for header, body in sections:
            if not body and not header:
                continue

            full_text = f"{header}\n{body}" if header else body
            if len(full_text) <= max_chunk_size:
                # 整个章节能放下，单独成一个 chunk
                chunks.append(
                    TextChunk(
                        content=full_text.strip(),
                        page_number=page.page_number,
                        chunk_index=index,
                        metadata={
                            "source_type": source_type,
                            "strategy": "header_aware",
                            "header": header,
                        },
                    )
                )
                index += 1
            else:
                # 章节太长，内部再按段落/句子切分，每块保留章节标题
                units = _split_text_into_units(body, max_chunk_size)
                section_chunks, index = _group_units_into_chunks(
                    units,
                    header,
                    page.page_number,
                    source_type,
                    index,
                    max_chunk_size,
                )
                chunks.extend(section_chunks)

    return chunks


def _chunk_paragraph_aware(pages: List[ExtractedPage], max_chunk_size: int) -> List[TextChunk]:
    """无章节标题时的 fallback：段落感知分块。"""
    source_type = pages[0].source_type if pages else ""
    units: List[Tuple[str, int | None]] = []
    for page in pages:
        page_units = _split_text_into_units(page.text, max_chunk_size)
        for unit in page_units:
            units.append((unit, page.page_number))

    chunks: List[TextChunk] = []
    current_units: List[Tuple[str, int | None]] = []
    current_length = 0
    index = 0

    for unit, page_number in units:
        unit_len = len(unit)

        if unit_len >= max_chunk_size:
            if current_units:
                chunks.append(
                    TextChunk(
                        content="\n".join(u for u, _ in current_units),
                        page_number=_majority_page([p for _, p in current_units]),
                        chunk_index=index,
                        metadata={
                            "source_type": source_type,
                            "strategy": "paragraph_aware",
                        },
                    )
                )
                index += 1
                current_units = []
                current_length = 0
            chunks.append(
                TextChunk(
                    content=unit,
                    page_number=page_number,
                    chunk_index=index,
                    metadata={
                        "source_type": source_type,
                        "strategy": "paragraph_aware",
                    },
                )
            )
            index += 1
            continue

        if current_units and current_length + unit_len + 1 > max_chunk_size:
            chunks.append(
                TextChunk(
                    content="\n".join(u for u, _ in current_units),
                    page_number=_majority_page([p for _, p in current_units]),
                    chunk_index=index,
                    metadata={
                        "source_type": source_type,
                        "strategy": "paragraph_aware",
                    },
                )
            )
            index += 1
            current_units = []
            current_length = 0

        current_units.append((unit, page_number))
        current_length += unit_len + 1

    if current_units:
        chunks.append(
            TextChunk(
                content="\n".join(u for u, _ in current_units),
                page_number=_majority_page([p for _, p in current_units]),
                chunk_index=index,
                metadata={
                    "source_type": source_type,
                    "strategy": "paragraph_aware",
                },
            )
        )

    return chunks


def _chunk_by_cases(
    pages: List[ExtractedPage],
    max_case_size: int,
    fallback_max_chunk_size: int,
) -> List[TextChunk]:
    """按病历标题分块，尽量把一例完整病历作为一个 chunk。"""
    source_type = pages[0].source_type if pages else ""
    full_text, page_breaks = _concat_pages_text(pages)
    sections = _split_by_cases(full_text)
    chunks: List[TextChunk] = []
    index = 0

    for header, body, start_offset in sections:
        if not header and not body:
            continue

        full_case = f"{header}\n{body}" if header else body
        page_number = _page_for_offset(page_breaks, start_offset)

        if len(full_case) <= max_case_size:
            chunks.append(
                TextChunk(
                    content=full_case.strip(),
                    page_number=page_number,
                    chunk_index=index,
                    metadata={
                        "source_type": source_type,
                        "strategy": "case_aware",
                        "case_header": header,
                    },
                )
            )
            index += 1
            continue

        # 单个病历超出上限：退回章节感知或段落感知，但保留病历标题
        synthetic = [ExtractedPage(text=body, page_number=page_number, source_type=source_type)]
        subchunks = _chunk_by_headers(synthetic, fallback_max_chunk_size)
        for sc in subchunks:
            new_content = (f"{header}\n{sc.content}" if header else sc.content).strip()
            chunks.append(
                TextChunk(
                    content=new_content,
                    page_number=sc.page_number,
                    chunk_index=index,
                    metadata={
                        **sc.metadata,
                        "source_type": source_type,
                        "strategy": "case_aware_fallback",
                        "case_header": header,
                    },
                )
            )
            index += 1

    return chunks


def _majority_page(page_numbers: List[int | None]) -> int | None:
    counts: dict[int | None, int] = {}
    for p in page_numbers:
        counts[p] = counts.get(p, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _has_case_headers(pages: List[ExtractedPage]) -> bool:
    """判断文本中是否存在病历标题。"""
    for page in pages:
        for line in page.text.split("\n"):
            if _is_case_line(line):
                return True
    return False


def _has_meaningful_headers(pages: List[ExtractedPage]) -> bool:
    """判断文本中是否存在章节标题，从而决定使用哪种策略。"""
    header_count = 0
    for page in pages:
        for line in page.text.split("\n"):
            if _is_header_line(line):
                header_count += 1
                if header_count >= 2:
                    return True
    return False


def chunk_pages(pages: List[ExtractedPage]) -> List[TextChunk]:
    if _has_case_headers(pages):
        return _chunk_by_cases(
            pages,
            settings.CASE_CHUNK_MAX_SIZE,
            settings.CHUNK_SIZE,
        )
    if _has_meaningful_headers(pages):
        return _chunk_by_headers(pages, settings.CHUNK_SIZE)
    return _chunk_paragraph_aware(pages, settings.CHUNK_SIZE)
