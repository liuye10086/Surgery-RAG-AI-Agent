import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import OperatorVisitTimelineEditor from '../OperatorVisitTimelineEditor.vue'
import type { LongitudinalVisitInput, OperatorIndicatorCatalog } from '@/api/operator'

const fattyCatalog: OperatorIndicatorCatalog = {
  disease_code: 'fatty_liver',
  catalog_version: 'a'.repeat(64),
  items: [
    {
      code: 'alt',
      name_cn: '谷丙转氨酶',
      name_en: 'ALT',
      aliases: ['ALT'],
      allowed_units: ['U/L'],
      default_unit: 'U/L',
      data_type: 'numeric',
      context_requirements: [],
    },
    {
      code: 'ast',
      name_cn: '谷草转氨酶',
      name_en: 'AST',
      aliases: ['AST'],
      allowed_units: ['U/L'],
      default_unit: 'U/L',
      data_type: 'numeric',
      context_requirements: [],
    },
  ],
}

function visit(indicator = { name: 'alt', value: 42 as number | null, unit: 'U/L' }): LongitudinalVisitInput {
  return {
    visit_date: '2026-01-01',
    indicators: [indicator],
    notes: null,
    visit_context: {},
  }
}

function latestUpdate(wrapper: ReturnType<typeof mount>): LongitudinalVisitInput[] {
  const updates = wrapper.emitted('update') || []
  return updates[updates.length - 1][0] as LongitudinalVisitInput[]
}

describe('OperatorVisitTimelineEditor', () => {
  it('adds and removes indicator rows without converting blank values to zero', async () => {
    const wrapper = mount(OperatorVisitTimelineEditor, {
      props: { visits: [visit()], indicatorCatalog: fattyCatalog },
    })

    await wrapper.find('[aria-label="添加指标"]').trigger('click')
    const added = latestUpdate(wrapper)
    await wrapper.setProps({ visits: added })
    expect(wrapper.findAll('.timeline__indicator')).toHaveLength(2)

    await wrapper.findAll('input[type="number"]')[0].setValue('')
    const latest = latestUpdate(wrapper)
    expect(latest[0].indicators[0].value).toBeNull()

    await wrapper.setProps({ visits: latest })
    await wrapper.findAll('[aria-label="删除指标"]')[1].trigger('click')
    const removed = latestUpdate(wrapper)
    expect(removed[0].indicators).toHaveLength(1)
  })

  it('shows disease-specific labels and applies the selected indicator default unit', async () => {
    const wrapper = mount(OperatorVisitTimelineEditor, {
      props: {
        visits: [visit({ name: '', value: null, unit: '' })],
        indicatorCatalog: fattyCatalog,
      },
    })

    expect(wrapper.text()).toContain('谷丙转氨酶')
    await wrapper.find('select[aria-label="指标名称"]').setValue('alt')

    const latest = latestUpdate(wrapper)
    expect(latest[0].indicators[0]).toEqual({ name: 'alt', value: null, unit: 'U/L' })
  })

  it('keeps an unknown legacy indicator visible with a compatibility warning', () => {
    const wrapper = mount(OperatorVisitTimelineEditor, {
      props: { visits: [visit({ name: 'legacy_x', value: 7, unit: 'legacy' })], indicatorCatalog: fattyCatalog },
    })

    expect(wrapper.text()).toContain('legacy_x')
    expect(wrapper.text()).toContain('历史指标')
  })

  it('edits structured visit context without flattening it into notes', async () => {
    const wrapper = mount(OperatorVisitTimelineEditor, {
      props: { visits: [visit()], indicatorCatalog: fattyCatalog },
    })

    await wrapper.find('details').trigger('click')
    await wrapper.find('[aria-label="检测来源"]').setValue('lab')
    const latest = latestUpdate(wrapper)

    expect(latest[0].visit_context?.source_type).toBe('lab')
    expect(latest[0].notes).toBeNull()
  })

  it('associates stable backend field errors with the exact input', () => {
    const wrapper = mount(OperatorVisitTimelineEditor, {
      props: {
        visits: [visit()],
        indicatorCatalog: fattyCatalog,
        validationIssues: {
          'visits.0.indicators.0.value': '指标数值不能为空',
        },
      },
    })

    const input = wrapper.find('input[aria-label="指标值"]')
    expect(input.attributes('aria-invalid')).toBe('true')
    expect(input.attributes('aria-describedby')).toBe('visits-0-indicators-0-value-error')
    expect(wrapper.text()).toContain('指标数值不能为空')
  })
})
