"""Audit the actual model boundary without storing private feature values."""

from dataclasses import dataclass
import hashlib
import json

from app.schemas.report_document import (
    InputAudit,
    InputFieldAudit,
    ModelRunAudit,
    TrainingDisclosure,
)


@dataclass(frozen=True)
class AuditedPrediction:
    prediction: dict
    model_runs: list[ModelRunAudit]


def fingerprint_input_row(names: list[str], values: dict) -> str:
    body = {
        "schema_version": "model_input_audit.v1",
        "columns": names,
        "values": [values[name] for name in names],
    }
    return hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def describe_fields(contract, values: dict) -> list[InputFieldAudit]:
    required = set(contract.required_features)
    allowed = set(contract.allowed_missing_features)
    return [
        InputFieldAudit(
            name=name,
            state=(
                "present"
                if values.get(name) is not None
                else "allowed_missing"
                if name in allowed and name not in required
                else "required_missing"
            ),
        )
        for name in contract.feature_names
    ]


class InputAuditCollector:
    def __init__(self):
        self.audits: dict[str, InputAudit] = {}

    def prepared(self, task, audit):
        self.audits[task] = audit

    def invoking(self, task):
        audit = self.audits[task]
        self.audits[task] = InputAudit.model_validate(
            {**audit.model_dump(), "model_invoked": True}
        )

    def failed(self, task, code):
        if task in self.audits:
            self.audits[task].reason_code = code

    def finalize(self, suite, prediction):
        statuses = [
            prediction["model_status"]["outcome"],
            prediction["model_status"]["stage"],
        ]
        statuses.extend(row["model_status"] for row in prediction["trend_predictions"])
        entries = dict(suite.outcomes)
        if hasattr(suite.stage, "metadata"):
            entries[suite.stage.status.task] = suite.stage
        entries.update(
            {
                entry.status.task: entry
                for entry in getattr(suite, "trends", {}).values()
            }
        )
        runs = []
        for status in statuses:
            task = status.get("task")
            if not task:
                continue
            entry = entries.get(task)
            meta = getattr(entry, "metadata", None)
            audit = self.audits.get(task)
            if audit is None:
                # No feature preparation happened; report this explicitly rather than
                # claiming missing clinical values from an unexecuted input boundary.
                audit = InputAudit(
                    task=task, fields=[], reason_code=status["reason_code"]
                )
            elif status["status"] != "available":
                audit.reason_code = status["reason_code"]
            training = getattr(meta, "audit", None)
            data = getattr(meta, "dataset_contract", None)
            horizon = getattr(meta, "horizon", None)
            output = getattr(
                meta, "output_contract", getattr(meta, "score_contract", None)
            )
            target = (
                getattr(meta, "target", None) or status.get("target") or "未记录目标"
            )
            label = {
                "cirrhosis_or_hcc": "肝硬化或肝癌",
                "hcc": "肝癌",
                "dementia": "痴呆",
                "next_stage": "下一阶段",
            }.get(
                target,
                "下一次随访指标方向"
                if target.startswith("next_visit_direction:")
                else target,
            )
            runs.append(
                ModelRunAudit(
                    task=task,
                    target_label=label,
                    runtime=status,
                    input_audit=audit,
                    horizon_kind=horizon.kind if horizon else "days",
                    horizon_days=horizon.value
                    if horizon
                    else status.get("horizon_days"),
                    training=TrainingDisclosure(
                        synthetic_in_formal_metrics=getattr(
                            training, "synthetic_in_formal_metrics", None
                        ),
                        clinical_validity_claim=getattr(
                            training, "clinical_validity_claim", None
                        ),
                        production_enabled=getattr(meta, "production_enabled", None),
                        training_file_sha256=getattr(
                            data, "training_file_sha256", None
                        ),
                        composition_note="未记录训练样本构成",
                    ),
                    score_threshold=(
                        getattr(output, "threshold", None)
                        if getattr(output, "threshold", None) is not None
                        else 0.5
                    )
                    if status["artifact_type"] == "outcome" and meta
                    else None,
                    risk_band_rule_version="longitudinal_risk_band.v1"
                    if status["artifact_type"] == "outcome" and meta
                    else None,
                )
            )
        return runs


def run_audited_prediction(snapshot, adapter, suite, *, visits=None, minimum_visits=3):
    from app.services.longitudinal_prediction import (
        run_longitudinal_prediction,
        prediction_result_to_dict,
    )

    if visits is not None and "visits" in snapshot and visits != snapshot["visits"]:
        raise ValueError("audit_visits_mismatch")
    visit_rows = snapshot.get("visits") if visits is None else visits
    if visit_rows is None:
        raise ValueError("audit_visits_missing")
    collector = InputAuditCollector()
    prediction = prediction_result_to_dict(
        run_longitudinal_prediction(
            snapshot,
            visit_rows,
            adapter,
            suite,
            audit_collector=collector,
            minimum_visits=minimum_visits,
        )
    )
    return AuditedPrediction(prediction, collector.finalize(suite, prediction))
