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
    assert ' | NumericReportDocumentV2' in generated.split('export type AnyReportDocument = ')[1]


def test_history_document_is_generated_from_the_formal_schema():
    from app.schemas.numeric_report_v3 import NumericReportDocumentV3
    from app.schemas.report_document import parse_report_document
    from backend.tests.test_numeric_report_v3 import v3_fixture
    _, publication = v3_fixture()
    parsed = parse_report_document(publication.report_document.model_dump(mode='json'))
    assert isinstance(parsed, NumericReportDocumentV3)
    generated = generate()
    assert 'export interface NumericReportDocumentV3 {' in generated
    assert 'prediction: NumericPredictionV3' in generated
    assert 'baseline_predictions: (NumericTaskPredictionV3)[]' in generated
    assert 'task_algorithms: { [key: string]: NumericTaskAlgorithm }' in generated
    assert 'status: "available" | "abstain" | "error"' in generated
    assert generated.split('export type AnyReportDocument = ')[1].strip().endswith(' | NumericReportDocumentV3')


def test_recursive_json_dictionary_keeps_its_value_type():
    assert ts({'type': 'object', 'additionalProperties': {'$ref': '#/$defs/JsonValue'}}) == '{ [key: string]: JsonValue }'


def test_history_fixed_numeric_tuple_keeps_its_positions():
    assert ts({'type': 'array', 'prefixItems': [{'type': 'number'}, {'type': 'number'}, {'type': 'number'}], 'minItems': 3, 'maxItems': 3}) == '[number, number, number]'


def test_history_discriminated_node_union_keeps_both_node_types():
    assert ts({'oneOf': [{'$ref': '#/$defs/RfBranch'}, {'$ref': '#/$defs/RfLeaf'}]}) == 'RfBranch | RfLeaf'
