"""Pinned engineering generation identity, independent of persistence services."""

from typing import Literal

from app.schemas.synthetic_numeric_prediction import NumericAlgorithmIdentity, Sha, StrictNumericModel


class SyntheticGenerationContext(StrictNumericModel):
    schema_version: Literal["synthetic_numeric_generation_context.v1"] = "synthetic_numeric_generation_context.v1"
    disease_code: Literal["ad", "fatty_liver"]
    numeric_input_sha256: Sha
    engineering_source_sha256: Sha
    algorithm: NumericAlgorithmIdentity
    template_version: Literal["synthetic_numeric_report.zh-CN.v1"] = "synthetic_numeric_report.zh-CN.v1"
