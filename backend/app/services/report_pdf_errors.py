"""Public PDF errors contain only fixed codes and translated messages."""

ERRORS = {
    "pdf_disabled": (503, "PDF 归档暂未开放"),
    "pdf_capacity_exceeded": (429, "PDF 准备任务已达容量上限，请稍后重试"),
    "report_not_exportable": (409, "报告尚未完成或完整性校验失败，无法导出"),
    "pdf_not_requested": (409, "请先准备 PDF"),
    "pdf_not_ready": (409, "PDF 尚未准备完成"),
    "pdf_retry_forbidden": (409, "此报告不允许重新生成 PDF 原件"),
    "pdf_source_changed": (409, "报告保存内容与归档来源不一致"),
    "pdf_renderer_unavailable": (503, "PDF 渲染资源未就绪"),
    "pdf_font_unavailable": (503, "PDF 中文字体未就绪"),
    "pdf_render_failed": (503, "PDF 准备失败，请稍后重试"),
    "pdf_render_timeout": (503, "PDF 准备超时"),
    "pdf_storage_unavailable": (503, "PDF 归档存储暂不可用"),
    "pdf_storage_full": (503, "PDF 归档空间不足"),
    "pdf_original_missing": (409, "PDF 原件缺失，请联系维护人员从备份恢复"),
    "pdf_original_corrupt": (409, "PDF 原件校验失败，请联系维护人员从备份恢复"),
    "pdf_range_not_supported": (416, "PDF 下载暂不支持分段请求"),
    "report_not_found": (404, "报告不存在"),
    "idempotency_key_missing": (400, "缺少请求标识"),
    "idempotency_key_invalid": (400, "请求标识必须为 UUID"),
    "idempotency_conflict": (409, "此请求标识已用于其他请求"),
    "idempotency_resource_missing": (409, "原报告已删除，请使用新的请求标识"),
    "pdf_queue_timeout": (503, "PDF 排队超时"),
    "pdf_worker_interrupted": (503, "PDF 准备已中断"),
    "pdf_lease_lost": (409, "PDF 任务执行权限已失效"),
}


def safe_pdf_code(code):
    return code if isinstance(code, str) and code in ERRORS else "pdf_render_failed"


class PdfError(ValueError):
    def __init__(self, code, status_code=None):
        self.code = safe_pdf_code(code)
        default, self.message = ERRORS[self.code]
        self.status_code = status_code or default
        super().__init__(self.code)
