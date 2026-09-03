"""Public schema for the operator's disease-specific indicator catalog."""

from pydantic import BaseModel, ConfigDict, Field


class OperatorIndicatorCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=100)
    name_cn: str | None = Field(None, max_length=200)
    name_en: str = Field(..., min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)
    allowed_units: list[str] = Field(default_factory=list)
    default_unit: str | None = Field(None, max_length=50)
    data_type: str = Field(..., min_length=1, max_length=32)
    context_requirements: list[str] = Field(default_factory=list)


class OperatorIndicatorCatalogOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disease_code: str = Field(..., min_length=1, max_length=50)
    catalog_version: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    items: list[OperatorIndicatorCatalogItem] = Field(default_factory=list)
