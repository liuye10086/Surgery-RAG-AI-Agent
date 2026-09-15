import type { SyntheticNumericReportDocumentV1 } from '@/types/report-document'

export function syntheticDocument(disease: 'ad' | 'fatty_liver' = 'ad'): SyntheticNumericReportDocumentV1 {
  const indicator = disease === 'ad' ? 'mmse' : 'alt'
  const unit = disease === 'ad' ? '分' : 'U/L'
  const source = { source_kind: 'synthetic', is_synthetic: true, generator_version: 'synthetic-prediction.v1', run_id: 'test-run', manifest_sha256: 'a'.repeat(64), input_file_sha256: 'b'.repeat(64) } as const
  const algorithm = { model_id: 'last_value', algorithm_version: 'synthetic_numeric.last_value.v1', input_schema_version: 'synthetic_numeric_input.v1', implementation_sha256: 'c'.repeat(64), parameters_sha256: 'd'.repeat(64), clinical_validity_claim: false, production_enabled: false } as const
  const packets = ([6, 12] as const).map(horizon_months => ({ sample_id: `test-${horizon_months}`, subject_id: 'test-subject', dependency_group_id: 'test-group', task_id: `${disease}.${indicator}.${horizon_months}m`, horizon_months, anchor_date: '2026-01-31', anchor_observation_id: 'anchor', input_observations: [{ observation_id: 'anchor', indicator, measured_on: '2026-01-31', known_on: '2026-01-31', value: 0, unit, method: 'test-method' }], input_status: 'available', input_reason: null, history_coverage: 'complete', history_state: 'confirmed_none', source } as const))
  return {
    schema_version: 'synthetic_numeric_report_document.v1', template_version: 'synthetic_numeric_report.zh-CN.v1',
    identity: { report_id: 7, batch_id: 'test-batch', anonymous_case_code: 'CASE-TEST-2345', disease_code: disease, disease_name: disease === 'ad' ? '阿尔茨海默病' : '脂肪肝', age: 60, sex: 'male', baseline_stage: 'dementia', created_at: '2026-02-01T00:00:00Z', anchor_date: '2026-01-31' },
    generation_context: { schema_version: 'synthetic_numeric_generation_context.v1', disease_code: disease, numeric_input_sha256: 'e'.repeat(64), engineering_source_sha256: 'f'.repeat(64), algorithm, template_version: 'synthetic_numeric_report.zh-CN.v1' },
    numeric_input: { schema_version: 'synthetic_numeric_input.v1', disease_code: disease, subject_id: 'test-subject', dependency_group_id: 'test-group', anchor_date: '2026-01-31', source, packets: packets.map(packet => ({ ...packet, input_observations: [...packet.input_observations] })) },
    prediction: { schema_version: 'synthetic_numeric_prediction.v1', disease_code: disease, subject_id: 'test-subject', dependency_group_id: 'test-group', anchor_date: '2026-01-31', source, input_sha256: 'e'.repeat(64), algorithm, predictions: ([6, 12] as const).map(horizon_months => ({ task_id: `${disease}.${indicator}.${horizon_months}m`, indicator, unit, horizon_months, target_date: horizon_months === 6 ? '2026-07-31' : '2027-01-31', status: 'available', value: 0, reason: null })) },
  }
}
