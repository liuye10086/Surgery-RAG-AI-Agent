import html
import re
from app.schemas.report_document import ReportDocument


def escape_text(value: str) -> str:
    text = html.escape(str(value), quote=True)
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", text)


def render_report_document(document: ReportDocument) -> str:
    checked = ReportDocument.model_validate(document.model_dump(mode="json"))
    lines = ["# 纵向进展预测报告", ""]
    for section in checked.sections:
        lines.extend([f"## {section.number}. {escape_text(section.title)}", ""])
        for paragraph in section.paragraphs:
            lines.extend([escape_text(paragraph), ""])
        for table in section.tables:
            lines.extend([f"### {escape_text(table.title)}", ""])
            lines.append("| " + " | ".join(map(escape_text, table.headers)) + " |")
            lines.append("| " + " | ".join("---" for value in table.headers) + " |")
            for row in table.rows:
                lines.append("| " + " | ".join(map(escape_text, row)) + " |")
            lines.append("")
    return "\n".join(lines)
