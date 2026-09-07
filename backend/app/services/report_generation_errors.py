"""Public error codes never contain exception strings or clinical inputs."""

MESSAGES = {
    "generation_failed": "报告生成失败，请稍后重新生成",
    "prediction_failed": "模型未生成有效结果",
    "model_unavailable": "模型暂时不可用",
    "standard_missing": "正式标准暂不可用",
    "standard_not_approved": "所选标准版本已不再处于批准状态",
    "standard_integrity_failed": "正式标准完整性校验失败",
    "standard_query_failed": "正式标准查询暂不可用",
    "generation_context_changed": "生成上下文已变化，请重新提交",
    "generation_context_integrity_failed": "固定生成上下文完整性校验失败",
    "report_generation_contract_mismatch": "报告生成结果校验失败",
    "queue_timeout": "报告排队超时，请重新生成",
    "run_timeout": "报告执行超时，请重新生成",
    "phase_timeout": "报告生成阶段超时，请重新生成",
    "worker_interrupted": "报告执行被中断，请重新生成",
    "cancelled_by_user": "报告生成已取消",
    "execution_protocol_invalid": "报告执行结果格式无效",
    "child_termination_failed": "报告执行进程未能正常停止",
    "lease_lost": "报告执行权限已失效",
    "report_not_found": "报告不存在",
    "case_not_found": "病例不存在",
    "case_incomplete": "病例年龄、性别或确定阶段资料不完整",
    "invalid_timeline": "病例访视或指标记录无效，请核对后重试",
    "case_archived": "病例已归档，不能生成新报告",
    "disease_disabled": "疾病已停用，不能生成新报告",
    "case_changed": "病例已变化，请刷新后重新生成",
    "report_not_ready": "病例尚未满足报告生成条件",
    "report_jobs_unavailable": "报告服务暂停受理新任务",
    "active_report_exists": "该病例已有生成中的报告",
    "report_capacity_exceeded": "报告任务已达容量上限，请稍后重试",
    "idempotency_key_missing": "缺少 Idempotency-Key",
    "idempotency_key_invalid": "Idempotency-Key 必须是 UUID",
    "idempotency_conflict": "此请求标识已用于其他请求",
    "idempotency_resource_missing": "原报告已删除，请使用新的请求标识",
    "unsupported_report_options": "当前报告不接受自定义模型选项",
    "legacy_generation_unmanaged": "旧版生成任务尚未收敛，请联系维护人员处理",
    "active_report_delete_forbidden": "请先取消报告生成，再删除报告",
    "auth_expired": "登录已过期，请重新登录",
}


def safe_code(code):
    return code if isinstance(code, str) and code in MESSAGES else "generation_failed"


class ReportJobError(ValueError):
    def __init__(self, code, status_code=409, report_id=None):
        self.code = safe_code(code)
        self.message = MESSAGES[self.code]
        self.status_code = status_code
        self.report_id = report_id
        super().__init__(self.code)
