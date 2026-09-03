import pytest


def test_catalog_resolves_chinese_alt_alias_to_model_code():
    from app.services.operator_indicator_catalog import load_operator_indicator_catalog

    catalog = load_operator_indicator_catalog("fatty_liver")
    item = catalog.resolve_indicator("谷丙转氨酶")
    assert item.code == "alt"
    assert item.name_cn == "谷丙转氨酶"
    assert item.default_unit == "U/L"


def test_catalog_maps_ad_manifest_names_to_model_keys():
    from app.services.operator_indicator_catalog import load_operator_indicator_catalog

    catalog = load_operator_indicator_catalog("ad")
    assert catalog.resolve_indicator("NfL").code == "plasma_nfl"
    assert catalog.resolve_indicator("Plasma p-tau217").code == "plasma_ptau217"


def test_catalog_exposes_only_context_fields_the_visit_contract_can_capture():
    from app.services.operator_indicator_catalog import load_operator_indicator_catalog

    fatty = load_operator_indicator_catalog("fatty_liver")
    ad = load_operator_indicator_catalog("ad")

    assert fatty.resolve_indicator("ALT").context_requirements == ()
    assert ad.resolve_indicator("MMSE").context_requirements == (
        "assessment_language",
        "education_years",
        "scale_version",
    )
    assert ad.resolve_indicator("NfL").context_requirements == (
        "device_name",
        "method",
        "specimen",
    )


def test_catalog_normalizes_explicit_unit_aliases():
    from app.services.operator_indicator_catalog import load_operator_indicator_catalog

    catalog = load_operator_indicator_catalog("fatty_liver")
    assert catalog.normalize_unit("alt", "u/l") == "U/L"


def test_catalog_rejects_missing_manifest(tmp_path):
    from app.services.operator_indicator_catalog import (
        IndicatorCatalogUnavailableError,
        load_operator_indicator_catalog,
    )

    with pytest.raises(IndicatorCatalogUnavailableError):
        load_operator_indicator_catalog("fatty_liver", root=tmp_path)
