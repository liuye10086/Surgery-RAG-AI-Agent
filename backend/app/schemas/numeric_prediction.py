"""Source-independent numeric contracts, preserving the frozen strict task rules."""

from typing import Literal

from pydantic import Field, model_validator

from app.schemas.synthetic_numeric_prediction import (
    Identifier, Sha, StrictNumericModel, NumericPredictionInput,
    SyntheticNumericInput, NumericAlgorithmIdentity, SyntheticNumericPrediction,
)


class PredictionPacketSource(StrictNumericModel):
    source_kind: Literal['synthetic', 'real']
    is_synthetic: bool = Field(strict=True)
    dataset_id: Identifier
    dataset_version: Identifier
    run_id: Identifier
    generator_version: Identifier | None

    @model_validator(mode='after')
    def consistent_source(self):
        if self.is_synthetic != (self.source_kind == 'synthetic'):
            raise ValueError('prediction_source_flag_mismatch')
        if (self.generator_version is not None) != self.is_synthetic:
            raise ValueError('prediction_source_generator_mismatch')
        return self


class PredictionSource(PredictionPacketSource):
    manifest_sha256: Sha
    input_file_sha256: Sha


class NumericInputPacket(NumericPredictionInput):
    source: PredictionPacketSource


class NumericInput(SyntheticNumericInput):
    schema_version: Literal['numeric_input.v1'] = 'numeric_input.v1'
    source: PredictionSource
    packets: list[NumericInputPacket] = Field(min_length=2, max_length=2)


class NumericAlgorithm(NumericAlgorithmIdentity):
    algorithm_version: Literal['numeric.last_value.v1'] = 'numeric.last_value.v1'
    input_schema_version: Literal['numeric_input.v1'] = 'numeric_input.v1'


class NumericPrediction(SyntheticNumericPrediction):
    schema_version: Literal['numeric_prediction.v1'] = 'numeric_prediction.v1'
    source: PredictionSource
    algorithm: NumericAlgorithm
