import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import OperatorCaseWorkspace from '../OperatorCaseWorkspace.vue'

function existingCase() {
  return {
    id: 3, user_id: 7, disease_id: 11, anonymous_case_code: 'CASE-OLD', age: 56, sex: 'male', baseline_stage: 'pre_cirrhosis', notes: null, status: 'active',
    visits: [{ id: 1, case_id: 3, visit_date: '2026-01-01', visit_index: 1, indicators: [{ name: 'ALT', value: 42, unit: 'U/L' }], notes: null }],
    disease: { id: 11, code: 'fatty_liver', name: '脂肪肝', operator_enabled: true },
  } as any
}

function mountWorkspace(props: Record<string, unknown>) {
  return mount(OperatorCaseWorkspace, { props })
}

describe('OperatorCaseWorkspace', () => {
  it.each([
    { verified: true, enabled: true, report_kind: 'numeric_prediction' },
    { verified: true, enabled: false, report_kind: 'numeric_prediction' },
    { verified: false, enabled: false, report_kind: null },
  ])('keeps version-bound inputs read-only and gates numeric action: %j', async (prediction) => {
    const wrapper = mountWorkspace({ model: { ...existingCase(), prediction: { ...prediction, input_readonly: true } }, readiness: { ready: true, blockers: [] } })
    expect(wrapper.text()).toContain('已绑定版本的输入只读')
    expect(wrapper.text()).not.toMatch(/合成|工程/)
    expect(wrapper.text()).toContain('只读')
    expect(wrapper.text()).not.toContain('保存病例')
    expect(wrapper.findAll('input, select, textarea')).toHaveLength(0)
    expect(wrapper.text()).toContain('42 U/L')
    expect(wrapper.findAll('input:not(:disabled), select:not(:disabled), textarea:not(:disabled)')).toHaveLength(0)
    if (prediction.verified && prediction.enabled) {
      expect(wrapper.get('.action-bar__report').text()).toBe('生成报告')
      await wrapper.get('.action-bar__report').trigger('click')
      expect(wrapper.emitted('generate-report')).toHaveLength(1)
    } else {
      expect(wrapper.find('.action-bar__report').exists()).toBe(false)
      expect(wrapper.emitted('generate-report')).toBeUndefined()
    }
  })
  it.each(['archived', 'disabled'])('blocks editing and report generation for %s cases with a reason', async (mode) => {
    const model = existingCase()
    if (mode === 'archived') model.status = 'archived'
    else model.disease.operator_enabled = false
    const wrapper = mountWorkspace({ model, readiness: { ready: true, blockers: [] } })
    expect(wrapper.get('.profile-grid input').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.action-bar__report').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain(mode === 'archived' ? '病例已归档' : '疾病已停用')
  })
  it('starts a new case with exactly one initial visit', () => {
    const wrapper = mount(OperatorCaseWorkspace)
    expect(wrapper.findAll('.timeline__card')).toHaveLength(1)
    expect(wrapper.find('.timeline__error').exists()).toBe(false)
  })

  it('keeps the last visit undeletable and emits aggregate save with a reason for edits', async () => {
    const model = {
      id: 3, user_id: 7, disease_id: 11, anonymous_case_code: 'CASE-ABCD', age: 56, sex: 'male', baseline_stage: 'pre_cirrhosis', notes: null, status: 'active',
      visits: [{ id: 1, case_id: 3, visit_date: '2026-01-01', visit_index: 1, indicators: [{ name: 'ALT', value: 42, unit: 'U/L' }], notes: null }],
      disease: { id: 11, code: 'fatty_liver', name: '脂肪肝', operator_enabled: true },
    } as any
    const wrapper = mount(OperatorCaseWorkspace, { props: { model } })
    expect(wrapper.find('.timeline__card header button').attributes('disabled')).toBeDefined()
    await wrapper.find('.profile-grid input').setValue('57')
    await wrapper.find('.action-bar button').trigger('click')
    expect(wrapper.find('.reason-dialog').exists()).toBe(true)
    await wrapper.find('.reason-dialog textarea').setValue('更正年龄')
    await wrapper.findAll('.reason-dialog button')[1].trigger('click')
    const saved = wrapper.emitted('save')?.[0][0] as Record<string, unknown>
    expect(saved).toMatchObject({ age: 57, change_reason: '更正年龄' })
    expect(saved).not.toHaveProperty('disease_id')
  })

  it('resets disease-specific fields and requests a new catalog when disease changes', async () => {
    const wrapper = mount(OperatorCaseWorkspace, {
      props: { diseases: [{ id: 11, code: 'fatty_liver', name: '脂肪肝' }] },
    })

    await wrapper.find('.profile-grid select').setValue('11')

    expect(wrapper.emitted('disease-change')?.[0]).toEqual(['fatty_liver'])
    expect((wrapper.find('select[aria-label="指标名称"]').element as HTMLSelectElement).value).toBe('')
  })

  it('rebuilds a blank draft when model changes from an existing case to null', async () => {
    const wrapper = mountWorkspace({ model: existingCase() })

    await wrapper.setProps({ model: null })

    expect((wrapper.find('.profile-grid input[type="number"]').element as HTMLInputElement).value).toBe('0')
    expect((wrapper.get('[aria-label="指标名称"]').element as HTMLSelectElement).value).toBe('')
    expect(wrapper.text()).not.toContain('CASE-OLD')
  })
})
