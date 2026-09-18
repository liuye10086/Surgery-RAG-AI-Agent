# 数值报告展示调整计划

用户已批准按 PDF 审查中的三项建议实施：版本信息集中末尾、统一数值展示精度、优化参考分页。

目标：改善页面和新 PDF 的阅读体验，保留保存事实、统一报告模板和既有归档原件。

实施设计：前端预测结果及比较基线固定显示两位小数，四舍五入并提示展示舍入，缺失仍显示破折号；历史实测记录不改精度。后端在验证保存正文后，通过 Markdown treeprocessor 调整打印用表格和参考分组，不修改 canonical 正文生成器、schema、输入值或完整性指纹。PDF 保持单一 report_pdf.html，为新版数值报告使用局部样式；版本说明集中末尾；参考附录以记录块控制分页，不强制固定总页数。

使用项目现有 Vue、Python Markdown、Bleach、Jinja2、Playwright；不添加依赖，遵循 docs/DESIGN_SPEC.md 的暖杏蓝样式。沿用用户指定的本机测试环境，保留 docker-compose.test.yml 的现有删除记录。

- [x] 回归测试：数值舍入/缺失值，页面版本顺序，PDF 参考分组及正文未变。
- [x] 展示实现：NumericReportView.vue、pdf_generator.py、report_pdf.html。
- [x] 验证：相关 pytest、单 worker Vitest、契约及构建；生成独立新 renderer，实际生成两病种新报告与归档 PDF，检查六页或实际页数；旧报告读取及旧 PDF 字节保持不变。
- [x] 交付：新 PDF、检查结果及后续状态；不因展示调整重新训练模型或自动提交推送。

实际结果见[展示调整验收记录](../notes/2026-09-15-numeric-report-presentation-result.md)。最终两病种各两页，原归档字节验证保持。
