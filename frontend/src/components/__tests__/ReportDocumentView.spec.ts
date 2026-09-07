import {mount} from '@vue/test-utils'
import {describe,it,expect} from 'vitest'
import LongitudinalReportView from '@/components/LongitudinalReportView.vue'

describe('saved report document view',()=>{
  it('hides untrusted content and download on integrity failure',()=>{
    const wrapper=mount(LongitudinalReportView,{props:{report:{status:'completed',integrity_status:'invalid'} as never,
      renderedContent:'<p>UNTRUSTED_REPORT</p>'},global:{stubs:{'el-button':{template:'<button><slot /></button>'}}}})
    expect(wrapper.text()).not.toContain('UNTRUSTED_REPORT')
    expect(wrapper.text()).not.toContain('下载 PDF')
    expect(wrapper.text()).toContain('完整性校验失败')
  })
})
