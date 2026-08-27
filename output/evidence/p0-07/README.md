# P0-07 匿名验收证据

日期：2026-08-27

本目录只保存匿名报告的桌面页面证据，不包含患者身份、数据库连接信息、本机路径或 traceback。项目当前只验收电脑端，移动端不在本任务范围内。

## 桌面页面

- `fatty-liver-report-desktop.png`：脂肪肝完整报告摘要、目录和观察图表。
- `fatty-liver-report-signals-review.png`：脂肪肝关键进展信号与后续章节。
- `ad-report-desktop.png`：AD 完整报告摘要、目录和观察图表。
- `ad-report-signals-review.png`：AD 关键进展信号、CDR 阶段相关观察与人工复核内容。

## PDF

- `../../pdf/p0-07-fatty-liver-longitudinal-report.pdf`：脂肪肝匿名完整报告，3 页。
- `../../pdf/p0-07-ad-longitudinal-report.pdf`：AD 匿名完整报告，3 页。

两份 PDF 均已用 Poppler 逐页渲染检查中文、图表、表格、分页、页眉页脚、页码、空白页、截断和重叠。页面、历史详情和 PDF 均读取生成时保存的报告正文。

## 验证摘要

- 后端相关专项回归：326 passed，5 个既有框架弃用警告。
- 前端 Node 合约：23 passed。
- 前端 TypeScript 检查和生产构建：通过。
- 匿名真实数据库验收：病例修改后，两份历史报告正文哈希均保持不变。
- 全量 pytest：运行到约 64% 后按项目方要求中止；中止前出现 2 个失败标记但未输出失败详情，因此不声称全量通过。
- 新生产模型：未修改、未训练、未上线。
