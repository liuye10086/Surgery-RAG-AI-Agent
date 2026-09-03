"""Manifest-backed indicator names, units, aliases, and model mappings."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import unicodedata
from typing import Any

from app.schemas.operator_indicator_catalog import (
    OperatorIndicatorCatalogItem,
    OperatorIndicatorCatalogOut,
)
from app.services.disease_catalog import DISEASE_CAPABILITIES
from app.services.standard_manifest import load_standard_manifest


class IndicatorCatalogError(ValueError):
    pass


class IndicatorCatalogUnavailableError(IndicatorCatalogError):
    pass


class IndicatorNotFoundError(IndicatorCatalogError):
    pass


@dataclass(frozen=True)
class CatalogIndicator:
    code: str
    name_cn: str | None
    name_en: str
    aliases: tuple[str, ...]
    allowed_units: tuple[str, ...]
    default_unit: str | None
    data_type: str
    context_requirements: tuple[str, ...]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _token(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return " ".join(normalized.split())


def _unit_token(value: Any) -> str:
    return _token(value).replace(" ", "")


UNIT_ALIASES = {
    "u/l": "U/L",
    "μmol/l": "μmol/L",
    "µmol/l": "μmol/L",
    "umol/l": "μmol/L",
    "kg/m2": "kg/m²",
    "10^9/l": "10⁹/L",
}


# Standard manifests use their reviewed names; model features retain the
# historical keys below. Every cross-name mapping is explicit and auditable.
MODEL_CODE_ALIASES: dict[str, dict[str, str]] = {
    "ad": {
        "nfl": "plasma_nfl",
        "NfL": "plasma_nfl",
        "NfL/GFAP": "plasma_nfl",
        "p-tau217": "plasma_ptau217",
        "Plasma p-tau217": "plasma_ptau217",
        "aβ42/aβ40": "abeta_ratio",
        "Aβ42/Aβ40": "abeta_ratio",
        "CSF Aβ42/Aβ40": "abeta_ratio",
    }
}


def _model_code(disease_code: str, manifest_code: str) -> str:
    aliases = MODEL_CODE_ALIASES.get(disease_code, {})
    for raw, mapped in aliases.items():
        if _token(raw) == _token(manifest_code):
            return mapped
    return manifest_code


class OperatorIndicatorCatalog:
    def __init__(self, disease_code: str, version: str, items: tuple[CatalogIndicator, ...]):
        self.disease_code = disease_code
        self.catalog_version = version
        self.items = items
        aliases: dict[str, CatalogIndicator] = {}
        for item in items:
            for name in (item.code, item.name_en, item.name_cn, *item.aliases):
                key = _token(name)
                if not key:
                    continue
                previous = aliases.get(key)
                if previous is not None and previous.code != item.code:
                    raise IndicatorCatalogUnavailableError(
                        f"指标别名冲突：{name} -> {previous.code}/{item.code}"
                    )
                aliases[key] = item
        self._aliases = aliases
        self._by_code = {item.code: item for item in items}

    def resolve_indicator(self, raw_name: str) -> CatalogIndicator:
        item = self._aliases.get(_token(raw_name))
        if item is None:
            raise IndicatorNotFoundError(f"未知指标：{raw_name}")
        return item

    def normalize_unit(self, indicator_code: str, raw_unit: str) -> str:
        item = self._by_code.get(indicator_code)
        if item is None:
            raise IndicatorNotFoundError(f"未知指标：{indicator_code}")
        unit = str(raw_unit or "").strip()
        canonical = UNIT_ALIASES.get(_unit_token(unit), unit)
        allowed = {_unit_token(value): value for value in item.allowed_units}
        if _unit_token(canonical) not in allowed:
            expected = "、".join(item.allowed_units) or "目录未定义"
            raise IndicatorCatalogError(
                f"指标 {indicator_code} 的单位 {unit} 不合法，应使用：{expected}"
            )
        return allowed[_unit_token(canonical)]

    def to_schema(self) -> OperatorIndicatorCatalogOut:
        return OperatorIndicatorCatalogOut(
            disease_code=self.disease_code,
            catalog_version=self.catalog_version,
            items=[
                OperatorIndicatorCatalogItem(
                    code=item.code,
                    name_cn=item.name_cn,
                    name_en=item.name_en,
                    aliases=list(item.aliases),
                    allowed_units=list(item.allowed_units),
                    default_unit=item.default_unit,
                    data_type=item.data_type,
                    context_requirements=list(item.context_requirements),
                )
                for item in self.items
            ],
        )


def load_operator_indicator_catalog(
    disease_code: str,
    root: Path | str | None = None,
) -> OperatorIndicatorCatalog:
    if disease_code not in DISEASE_CAPABILITIES:
        raise IndicatorCatalogUnavailableError("该疾病未配置 AI 操作者指标目录")
    root_path = Path(root).resolve() if root is not None else _project_root()
    manifest_path = root_path / "standard_manifests" / f"{disease_code}.v1.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = load_standard_manifest(manifest_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise IndicatorCatalogUnavailableError("指标目录文件不可用") from exc
    if manifest.review_state != "approved" or manifest.dataset != disease_code:
        raise IndicatorCatalogUnavailableError("指标目录尚未通过审核")

    supported = DISEASE_CAPABILITIES[disease_code].indicators
    grouped: dict[str, dict[str, Any]] = {}
    for entry in manifest.entries:
        if entry.review_status != "approved":
            continue
        source = entry.indicator
        code = _model_code(disease_code, source.canonical_key)
        if code not in supported:
            continue
        item = grouped.setdefault(
            code,
            {
                "code": code,
                "name_cn": source.name_cn,
                "name_en": source.name_en,
                "aliases": [],
                "allowed_units": list(supported[code].units),
                "default_unit": source.default_unit,
                "data_type": source.data_type,
                "context_requirements": set(),
            },
        )
        item["name_cn"] = item["name_cn"] or source.name_cn
        item["name_en"] = item["name_en"] or source.name_en
        item["aliases"].extend(
            [source.canonical_key, source.name_en, source.name_cn, *source.aliases]
        )
        if entry.rule is not None:
            item["context_requirements"].update(
                str(key) for key in (entry.rule.applicability or {})
            )
    items: list[CatalogIndicator] = []
    for code, raw in sorted(grouped.items()):
        aliases = tuple(
            sorted(
                {
                    str(value)
                    for value in [code, *raw["aliases"]]
                    if isinstance(value, str) and _token(value)
                },
                key=_token,
            )
        )
        default_unit = raw["default_unit"]
        if default_unit is not None:
            default_unit = UNIT_ALIASES.get(_unit_token(default_unit), default_unit)
        items.append(
            CatalogIndicator(
                code=code,
                name_cn=raw["name_cn"],
                name_en=raw["name_en"],
                aliases=aliases,
                allowed_units=tuple(raw["allowed_units"]),
                default_unit=default_unit,
                data_type=raw["data_type"],
                context_requirements=tuple(sorted(raw["context_requirements"])),
            )
        )
    if not items:
        raise IndicatorCatalogUnavailableError("指标目录没有可用的操作者指标")
    return OperatorIndicatorCatalog(
        disease_code,
        hashlib.sha256(manifest_bytes).hexdigest(),
        tuple(items),
    )


__all__ = [
    "CatalogIndicator",
    "IndicatorCatalogError",
    "IndicatorCatalogUnavailableError",
    "IndicatorNotFoundError",
    "OperatorIndicatorCatalog",
    "load_operator_indicator_catalog",
]
