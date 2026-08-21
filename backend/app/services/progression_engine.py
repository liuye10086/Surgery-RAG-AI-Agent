"""Feature extraction and inference for longitudinal progression prediction."""

import json
from collections import defaultdict
from functools import lru_cache
from math import isfinite
from pathlib import Path
from typing import Any

import joblib

from app.services.prediction_engine import _BANDS


MODEL_DIR = Path(__file__).resolve().parents[1] / "ml_models"
DISCLAIMER = (
    "本次风险评估基于机器学习模型，训练数据为人工按疾病进展规则构造的历史病例"
    "（含真实病例的构造化随访轨迹与合成病例），已确认交叉验证准确率接近满分主要"
    "反映训练数据构造规则本身的可分性，不代表模型在真实临床场景下的泛化能力。"
    "本结果仅供内部技术参考，不得作为独立的临床决策依据，请结合其他检查手段综合判断。"
)


def _as_finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _linear_slope(observations: list[tuple[int, float]]) -> float | None:
    if len(observations) < 2:
        return None
    x_mean = sum(index for index, _ in observations) / len(observations)
    y_mean = sum(value for _, value in observations) / len(observations)
    denominator = sum((index - x_mean) ** 2 for index, _ in observations)
    if denominator == 0:
        return None
    numerator = sum(
        (index - x_mean) * (value - y_mean)
        for index, value in observations
    )
    return numerator / denominator


def extract_features(visits: list[dict]) -> dict[str, dict[str, float | int | None]]:
    """Extract per-indicator longitudinal features without DB/model dependencies."""
    ordered_visits = sorted(
        visits,
        key=lambda visit: str(visit.get("visit_date") or ""),
    )
    observations: dict[str, list[tuple[int, float]]] = defaultdict(list)

    for visit_index, visit in enumerate(ordered_visits):
        for indicator in visit.get("indicators") or []:
            name = str(indicator.get("name") or "").strip().lower()
            value = _as_finite_float(indicator.get("value"))
            if not name or value is None:
                continue
            observations[name].append((visit_index, value))

    features = {}
    for name, indicator_observations in observations.items():
        values = [value for _, value in indicator_observations]
        first = values[0]
        last = values[-1]
        delta = last - first
        features[name] = {
            "first": first,
            "last": last,
            "delta": delta,
            "delta_pct": None if first == 0 else delta / first,
            "slope": _linear_slope(indicator_observations),
            "rises_count": sum(
                current > previous
                for previous, current in zip(values, values[1:])
            ),
            "n_observations": len(values),
        }
    return features


@lru_cache(maxsize=None)
def load_model(dataset: str) -> tuple[Any, dict]:
    """Load and cache one trained model plus its feature-order metadata."""
    model_path = MODEL_DIR / f"{dataset}_progression_model.joblib"
    meta_path = MODEL_DIR / f"{dataset}_progression_model.meta.json"
    missing = [str(path) for path in (model_path, meta_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"该疾病尚无可用进展预测模型（dataset={dataset}）：缺少 "
            + ", ".join(missing)
        )
    model = joblib.load(model_path)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not meta.get("feature_names"):
        raise ValueError(f"进展预测模型元数据缺少特征顺序（dataset={dataset}）")
    return model, meta


def _risk_band(score: float) -> str:
    for threshold, label, _ in _BANDS:
        if score >= threshold:
            return label
    return "极低"


def _feature_vector(
    features: dict[str, dict[str, float | int | None]],
    feature_names: list[str],
) -> list[float]:
    vector = []
    for feature_name in feature_names:
        indicator_name, stat = feature_name.rsplit(".", 1)
        value = features.get(indicator_name, {}).get(stat)
        vector.append(float(value) if value is not None else float("nan"))
    return vector


def _positive_class_probability(model: Any, vector: list[float]) -> float:
    probabilities = model.predict_proba([vector])[0]
    classes = list(model.classes_)
    if 1 not in classes:
        raise ValueError("进展预测模型缺少阳性类别")
    return float(probabilities[classes.index(1)])


def predict_progression(dataset: str, visits: list[dict]) -> dict:
    """Predict progression risk with disclosures tied to model performance."""
    model, meta = load_model(dataset)
    features = extract_features(visits)
    score = min(
        max(
            _positive_class_probability(
                model,
                _feature_vector(features, meta["feature_names"]),
            ),
            0.0,
        ),
        1.0,
    )
    feature_summary = [
        {
            "indicator": indicator,
            "first": summary["first"],
            "last": summary["last"],
            "slope": summary["slope"],
            "rises_count": summary["rises_count"],
        }
        for indicator, summary in sorted(features.items())
    ]
    cv_auc_mean = float(meta["cv_auc_mean"])
    return {
        "risk_band": _risk_band(score),
        "risk_score": round(score, 4),
        "feature_summary": feature_summary,
        "model_meta": {
            "trained_on": int(meta["trained_on"]),
            "cv_auc_mean": cv_auc_mean,
            "cv_auc_std": float(meta["cv_auc_std"]),
        },
        "disclaimer": DISCLAIMER,
        "model_caveat": (
            f"交叉验证准确率：{cv_auc_mean:.4f}（该数值主要反映训练数据构造方式，"
            "不直接等同于真实世界预测准确率）"
        ),
    }
