"""The frontend document DTO includes the saved trained report contract."""

from scripts.generate_report_document_types import generate, ts


def test_trained_report_and_recursive_json_evaluation_are_generated():
    generated = generate()
    assert 'export interface NumericReportDocumentV2 {' in generated
    assert 'schema_version: "numeric_report_document.v2"' in generated
    assert 'prediction: TrainedNumericPrediction' in generated
    assert 'baseline_predictions: (NumericTaskPrediction)[]' in generated
    assert 'export type JsonValue =' in generated
    assert 'evaluation: { [key: string]: JsonValue }' in generated
    assert generated.split('export type AnyReportDocument = ')[1].strip().endswith(' | NumericReportDocumentV2')


def test_recursive_json_dictionary_keeps_its_value_type():
    assert ts({'type': 'object', 'additionalProperties': {'$ref': '#/$defs/JsonValue'}}) == '{ [key: string]: JsonValue }'
