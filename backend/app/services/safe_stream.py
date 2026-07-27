"""在流式输出发送前按句执行医疗安全过滤。"""

import re
from dataclasses import dataclass

from app.services.content_filter import filter_output


SAFE_OUTPUT_REPLACEMENT = (
    "该部分内容涉及需要由执业医生结合实际情况判断的诊断或用药信息，"
    "已为您隐藏。请咨询主管医生。"
)

_BOUNDARY_RE = re.compile(r"[。！？；.!?;\n]+")


@dataclass(frozen=True)
class FilteredSegment:
    text: str
    replaced: bool = False
    reason: str | None = None


class SafeSentenceBuffer:
    def __init__(self) -> None:
        self._buffer = ""
        self._last_emitted_was_replacement = False

    def push(self, text: str) -> list[FilteredSegment]:
        if not text:
            return []
        self._buffer += text
        return self._drain_complete_sentences()

    def finish(self) -> list[FilteredSegment]:
        if not self._buffer:
            return []
        tail = self._buffer
        self._buffer = ""
        return self._filter_segment(tail)

    def _drain_complete_sentences(self) -> list[FilteredSegment]:
        results: list[FilteredSegment] = []
        consumed = 0
        for match in _BOUNDARY_RE.finditer(self._buffer):
            end = match.end()
            results.extend(self._filter_segment(self._buffer[consumed:end]))
            consumed = end
        if consumed:
            self._buffer = self._buffer[consumed:]
        return results

    def _filter_segment(self, text: str) -> list[FilteredSegment]:
        result = filter_output(text)
        if result.flagged:
            if self._last_emitted_was_replacement:
                # 不重复展示相同提示，但保留该句的审计原因。
                return [
                    FilteredSegment(
                        text="",
                        replaced=True,
                        reason=result.flag_reason or None,
                    )
                ]
            self._last_emitted_was_replacement = True
            return [
                FilteredSegment(
                    text=SAFE_OUTPUT_REPLACEMENT,
                    replaced=True,
                    reason=result.flag_reason or None,
                )
            ]

        self._last_emitted_was_replacement = False
        return [FilteredSegment(text=text)] if text else []
