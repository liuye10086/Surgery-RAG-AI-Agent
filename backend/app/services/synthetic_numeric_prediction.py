"""Baseline adapter with no admission, database, training, or outcome access."""

import hashlib
import inspect
from pathlib import Path
import sys
from types import CodeType

from app.services import prediction_calculation
from app.schemas.synthetic_numeric_prediction import (
    NumericAlgorithmIdentity, SyntheticNumericInput, SyntheticNumericPrediction,
)
from app.services.prediction_calculation import predict_baselines, project_calculation_inputs
from app.services.synthetic_prediction_cases import add_calendar_months, canonical_json


SOURCE_FILES = (
    "backend/app/schemas/synthetic_prediction_cases.py",
    "backend/app/schemas/synthetic_numeric_prediction.py",
    "backend/app/services/synthetic_prediction_cases.py",
    "backend/app/services/prediction_calculation.py",
    "backend/app/services/synthetic_numeric_prediction.py",
)


def _source_hashes():
    root = Path(__file__).resolve().parents[3]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


_LOADED_SOURCE_HASHES = _source_hashes()


def _verify_loaded_code():
    """Compile fixed sources without executing them; reject stale imported functions/validators."""
    root = Path(__file__).resolve().parents[3]
    for name in SOURCE_FILES:
        module_name = name.removeprefix("backend/").removesuffix(".py").replace("/", ".")
        module = sys.modules[module_name]
        functions = []
        for item in vars(module).values():
            if getattr(item, "__module__", None) != module_name:
                continue
            if inspect.isfunction(item):
                functions.append(item)
            elif inspect.isclass(item):
                for member in vars(item).values():
                    function = member.__func__ if isinstance(member, (classmethod, staticmethod)) else member
                    if inspect.isfunction(function) and function.__module__ == module_name:
                        functions.append(function)
        compiled = compile((root / name).read_bytes(), module.__file__, "exec", dont_inherit=True)
        codes, pending = {}, [compiled]
        while pending:
            code = pending.pop()
            codes[code.co_qualname] = code
            pending.extend(c for c in code.co_consts if isinstance(c, CodeType))
        if any(f.__code__ != codes.get(f.__code__.co_qualname) for f in functions):
            raise ValueError("numeric_loaded_code_mismatch")


def _payload(value):
    # Dump and reparse also rejects nested instances modified after validation.
    return value.model_dump(mode="python") if hasattr(value, "model_dump") else value


def _canonical_input(raw):
    value = SyntheticNumericInput.model_validate(_payload(raw)).model_dump(mode="json")
    value["packets"].sort(key=lambda p: p["horizon_months"])
    for p in value["packets"]:
        p["input_observations"].sort(key=lambda r: (r["measured_on"], r["observation_id"]))
    return value


def _sha(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def numeric_input_sha256(raw):
    return _sha(_canonical_input(raw))


def numeric_algorithm_identity():
    """Read only fixed implementation files; never resolve caller-supplied paths."""
    if _source_hashes() != _LOADED_SOURCE_HASHES:
        raise ValueError("numeric_implementation_changed")
    _verify_loaded_code()
    # Include evaluated schema/defaults and the baseline selector, not only source bytes.
    implementation = {
        "source_sha256": _LOADED_SOURCE_HASHES,
        "input_schema": SyntheticNumericInput.model_json_schema(),
        "result_schema": SyntheticNumericPrediction.model_json_schema(),
        "baseline_models": prediction_calculation.MODELS,
        "tasks": prediction_calculation.TASKS,
    }
    if _source_hashes() != _LOADED_SOURCE_HASHES:
        raise ValueError("numeric_implementation_changed")
    return NumericAlgorithmIdentity(implementation_sha256=_sha(implementation), parameters_sha256=_sha({}))


def predict_synthetic_numeric(raw, *, expected_algorithm=None):
    value = _canonical_input(raw)
    algorithm = numeric_algorithm_identity()
    if expected_algorithm is not None and NumericAlgorithmIdentity.model_validate(_payload(expected_algorithm)) != algorithm:
        raise ValueError("numeric_algorithm_mismatch")
    features = project_calculation_inputs(value["packets"])
    baselines = [p for p in predict_baselines(features) if p["model_id"] == "last_value"]
    if len(baselines) != 2 or len({p["sample_id"] for p in baselines}) != 2:
        raise ValueError("numeric_calculation_failed")
    indexed = {p["sample_id"]: p for p in baselines}
    indicator, unit = ("mmse", "分") if value["disease_code"] == "ad" else ("alt", "U/L")
    predictions = []
    parsed = SyntheticNumericInput.model_validate(value)
    for packet in parsed.packets:
        prediction = indexed.get(packet.sample_id)
        expected_status = "valid" if packet.input_status == "available" else "abstain"
        if prediction is None or prediction["status"] != expected_status:
            raise ValueError("numeric_calculation_failed")
        predictions.append({
            "task_id": packet.task_id, "indicator": indicator, "unit": unit,
            "horizon_months": packet.horizon_months,
            "target_date": add_calendar_months(parsed.anchor_date, packet.horizon_months),
            "status": packet.input_status, "value": prediction["value"], "reason": packet.input_reason,
        })
    result = SyntheticNumericPrediction(
        disease_code=parsed.disease_code, subject_id=parsed.subject_id,
        dependency_group_id=parsed.dependency_group_id, anchor_date=parsed.anchor_date,
        source=parsed.source, input_sha256=_sha(value), algorithm=algorithm, predictions=predictions,
    )
    return validate_numeric_prediction(result, parsed, algorithm)


def validate_numeric_prediction(result, raw_input, expected_algorithm):
    """Bind values to saved input and supplied pinned identity, without loading current code identity."""
    value = _canonical_input(raw_input)
    parsed = SyntheticNumericInput.model_validate(value)
    result = SyntheticNumericPrediction.model_validate(_payload(result))
    algorithm = NumericAlgorithmIdentity.model_validate(_payload(expected_algorithm))
    if (result.disease_code, result.subject_id, result.dependency_group_id, result.anchor_date,
        result.source, result.input_sha256, result.algorithm) != (
        parsed.disease_code, parsed.subject_id, parsed.dependency_group_id, parsed.anchor_date,
        parsed.source, _sha(value), algorithm
    ):
        raise ValueError("numeric_prediction_identity_mismatch")
    packets = {p.task_id: p for p in parsed.packets}
    for prediction in result.predictions:
        packet = packets[prediction.task_id]
        anchor = next((r for r in packet.input_observations if r.observation_id == packet.anchor_observation_id), None)
        expected_value = anchor.value if packet.input_status == "available" else None
        if (prediction.status, prediction.value, prediction.reason) != (
            packet.input_status, expected_value, packet.input_reason
        ):
            raise ValueError("numeric_prediction_value_mismatch")
    return result
