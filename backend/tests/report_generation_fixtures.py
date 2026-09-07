"""Independent temporary copies of checked-in, reviewed demonstration assets."""

import shutil
from app.services.model_paths import MODEL_DIR
from app.services.longitudinal_release_set import load_disease_release_set
from app.schemas.report_document import ReportGenerationContext
from app.services.operator_indicator_catalog import load_operator_indicator_catalog
from backend.tests.report_document_fixtures import context_payload


def pinned_suite_fixture(tmp_path, disease="fatty_liver"):
    root = tmp_path / "registry"
    shutil.copytree(MODEL_DIR, root)
    release = load_disease_release_set(disease, root)
    catalog = load_operator_indicator_catalog(disease)
    context = context_payload()
    context.update(
        disease_code=disease,
        release_set_id=release.release_set_id,
        release_set_sha256=release.record_sha256,
        data_release_id=release.data_release_id,
        dataset_manifest_sha256=release.dataset_manifest_sha256,
        split_sha256=release.split_sha256,
        indicator_catalog_sha256=catalog.catalog_version,
        indicator_labels=[
            {
                "code": i.code,
                "label": i.name_cn or i.name_en,
                "allowed_units": list(i.allowed_units),
                "context_requirements": list(i.context_requirements),
            }
            for i in catalog.items
        ],
    )
    return ReportGenerationContext.model_validate(context), root
