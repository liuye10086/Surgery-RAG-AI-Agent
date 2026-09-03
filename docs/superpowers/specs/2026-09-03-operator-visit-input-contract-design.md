# 访视录入与模型输入校验设计规格

**日期：** 2026-09-03  
**适用流程：** AI 操作者、脂肪肝与阿尔茨海默病、电脑端  
**关联核查项：**《AI 操作者流程核查》第 2、3 项

## 1. 目标与范围

将“录入多次访视”和“校验指标、单位、年龄、性别、基线阶段”合并为一个可独立验收的访视输入契约。操作者能够在同一病例工作区录入完整时间线，系统保存规范化数据，并在调用模型前阻止不安全或不兼容的输入。

本规格包含：

- 访视和指标行的完整编辑能力；
- 疾病专属指标目录、别名和单位规范化；
- 访视检测上下文的结构化保存；
- 年龄、性别、基线阶段与时间线的统一校验；
- 聚合保存、报告 readiness、快照和审计的联动；
- 旧病例、旧报告和旧输入快照的兼容；
- 后端、前端、真实 PostgreSQL 和浏览器验收。

不包含：

- 新增疾病或新模型；
- 改变当前模型算法、训练数据或报告模板；
- 恢复单访视公开写接口；
- 自动修复历史病例或重新计算历史报告；
- 将医疗参考范围异常误当作结构性输入错误。

## 2. 当前基线与已确认规则

- `operator_cases` 是操作者唯一业务病例，`operator_case_visits` 保存时间线。
- 病例创建和修改使用聚合接口；访视不提供绕过聚合审计的公开写路由。
- 病例保存允许 `1–10` 次有效访视。
- 报告最低访视数从活动数据清单读取，当前脂肪肝和 AD 均为 `3`，前端和病例 schema 不得硬编码该门槛。
- 访视按日期升序保存并生成连续 `visit_index`；`visit_index` 不是客户端可写字段。
- 同一病例日期不能重复；同一访视规范化后不能存在重复指标代码。
- 年龄为 `0–120` 的整数；性别为 `male` 或 `female`；基线阶段使用疾病专属稳定英文代码。
- 病例行锁、归档只读、疾病停用保护和输入快照完整性继续生效。
- 历史报告读取自身快照，不因病例更正而重算。

## 3. 设计原则

1. 单一规范化入口：创建、聚合修改、导入、快照和报告前复核全部调用同一套指标与时间线规范化服务。
2. 后端最终裁决：前端提供即时反馈，但不能替代后端校验。
3. 失败关闭：目录、模型契约或输入无法确认时，拒绝新的写入或报告生成，不猜测单位、阶段或风险。
4. 兼容而不改写：旧数据可读取；新保存和新报告使用规范化结构；不批量修复历史 JSONB。
5. 临床异常与格式错误分离：超出参考范围可以作为临床状态提示，只有不可能的量表值、非法单位、未知指标等才阻止保存。
6. 最小披露：日志和审计不记录姓名、联系方式、指标数值、访视日期或完整请求体。

## 4. 权威目录与稳定代码

### 4.1 目录来源

新增 `operator_indicator_catalog` 服务，读取已审核的 `standard_manifests/fatty_liver.v1.json` 和 `standard_manifests/ad.v1.json`，并通过 SHA-256 和 manifest `review_state=approved` 校验。目录服务只返回后端疾病能力和当前模型支持的指标交集。

manifest 的 `canonical_key`、`name_cn`、`name_en`、`aliases`、`default_unit`、`data_type`、`specimen_or_modality` 和 `applicability` 是展示与输入契约的来源。manifest 不可读取或校验失败时，目录接口返回稳定的不可用错误；既有病例仍可读取，新的病例写入和报告生成安全停止。

### 4.2 模型代码映射

模型代码和标准 manifest 存在历史命名差异时，必须使用显式映射表，不能依靠模糊字符串匹配：

| 模型规范代码 | manifest 代码/别名 | 说明 |
|---|---|---|
| `plasma_nfl` | `nfl`、`NfL`、`NfL/GFAP` | 统一为模型输入代码 `plasma_nfl` |
| `plasma_ptau217` | `p-tau217`、`Plasma p-tau217` | 统一为模型输入代码 `plasma_ptau217` |
| `abeta_ratio` | `aβ42/aβ40`、`Aβ42/Aβ40`、`CSF Aβ42/Aβ40` | 只有在模型契约声明支持时才开放 |

目录条目返回稳定 `code`，前端显示中英文名称；数据库 `indicators[].name` 继续保存稳定代码，以兼容现有特征和报告逻辑。

### 4.3 单位策略

- 每个指标有明确的 canonical unit 和允许 alias 集合。
- 只做经过目录明确批准的空白、大小写和 Unicode 归一化；不凭经验进行维度换算。
- `IU/L` 与 `U/L` 不自动视为等价，除非目录明确声明等价和换算规则。
- 没有默认单位的 AD 生物标志物必须由操作者填写实际单位。
- 规范化后只保存 canonical unit；原始别名不进入模型输入、报告正文或日志。

## 5. 后端输入契约

### 5.1 结构

保留现有指标结构 `{name, value, unit}`，其中 `name` 在规范化后必须是稳定代码。`VisitCreate` 和 `VisitOut` 增加可选的 `visit_context`：

```text
visit_context:
  source_type: lab | imaging | assessment | clinical | other
  facility_name: string <= 200
  device_name: string <= 200
  method: string <= 200
  specimen: string <= 100
  is_baseline: boolean
  treatment_change: string <= 2000
  diagnosis_change: string <= 2000
  scale_version: string <= 100
  assessment_language: string <= 50
  education_years: integer 0..30
  education_adjusted: boolean | null
  imaging_type: string <= 100
```

所有字段均可缺省；目录根据指标类型声明哪些上下文用于标准解释。上下文缺失不伪造默认值：需要上下文的标准规则降级为 evidence-only，并在 readiness/报告局限性中提示。

### 5.2 规范化流程

实现 `normalize_operator_timeline(disease_code, visits)` 的扩展版本，依次完成：

1. 检查 `1–10` 次访视；
2. 将日期转换为 ISO 日期并拒绝重复；
3. 解析指标目录别名为稳定代码；
4. 拒绝未知指标、跨疾病指标和规范化后的重复指标；
5. 将单位解析为 canonical unit；
6. 拒绝空值、布尔值、NaN、Infinity 和明确不可能的量表值；
7. 校验上下文字段长度、枚举和值域；
8. 按日期排序并生成 `visit_index=1..N`；
9. 返回不可变的规范化访视对象。

结构性错误在病例保存时返回 422；错误响应继续使用 `{code, message, field}`，并增加可选 `issues[]` 以一次返回多个字段错误。`field` 使用例如 `visits.1.indicators.0.value` 的稳定路径。

### 5.3 年龄、性别、阶段

复用现有 `validate_operator_case_profile`：

- 年龄、性别、基线阶段缺失或非法时，保存返回字段级错误；
- 旧病例允许读取，但补齐前不能生成新报告；
- 阶段别名只在明确兼容入口转换，规范化后必须保存稳定代码；
- 终末阶段仍可保存，但 readiness 返回 `prediction_not_applicable`。

### 5.4 审计与快照

聚合保存继续写入不可变变更审计。为避免医疗数据泄露，新的时间线 diff 只记录操作类型、字段名、指标数量变化和规范化时间线哈希，不记录指标值、访视日期、上下文正文或完整 before/after。输入快照则完整保存本次报告所需的规范化访视，用于报告追溯和完整性校验。

## 6. 数据库设计

新增 Alembic `0021_operator_case_visit_context`：

- `operator_case_visits.visit_context JSONB NOT NULL DEFAULT '{}'`；
- 增加 `jsonb_typeof(visit_context) = 'object'` 检查；
- 保留日期唯一、访视序号唯一和正数约束；
- ORM、`database/schema.sql`、只读检查器和结构契约测试同步更新；
- 不删除或重写既有访视；旧行使用空对象兼容读取。

JSONB 只负责存储结构；疾病语义、上下文依赖和指标单位由应用层目录服务校验，不新增不可维护的数据库枚举或疾病名称 CHECK。

## 7. API 设计

新增只读接口：

```text
GET /v1/operator/diseases/{disease_code}/indicators
```

返回：

```json
{
  "disease_code": "fatty_liver",
  "catalog_version": "<manifest sha256>",
  "items": [
    {
      "code": "alt",
      "name_cn": "谷丙转氨酶",
      "name_en": "ALT",
      "aliases": ["丙氨酸氨基转移酶"],
      "allowed_units": ["U/L"],
      "default_unit": "U/L",
      "data_type": "numeric",
      "context_requirements": []
    }
  ]
}
```

病例创建、聚合保存、readiness 和报告生成继续使用现有资源路径和权限边界。保存返回规范化后的指标和 `visit_context`；客户端不能提交 `id`、`case_id`、`visit_index`、匿名编号、用户 ID 或状态。

## 8. 前端设计

### 8.1 工作区

`OperatorVisitTimelineEditor` 接收当前疾病目录和服务端 readiness：

- 每次访视提供“添加指标”和“删除指标”；
- 指标为疾病专属下拉，展示中文名和英文代码；
- 单位默认为 canonical unit，允许单位 alias 只在目录声明时出现；
- 数值清空保留 `null`，不能转换为 `0`；
- 日期重复、日期缺失、指标重复、数值缺失、单位错误按访视和指标显示；
- 显示 `当前 N/10 次访视` 和 `报告至少需要 M 次`，其中 M 来自 readiness；
- 旧数据中的未知指标显示兼容警告，不自动删除。

### 8.2 上下文面板

每次访视提供折叠的“检测信息”面板。常用字段优先展示；AD 指标出现时显示量表版本、语言和教育年限；脂肪肝影像数据出现时显示影像检查类型。上下文缺失以中性提示表达，不阻断尚可安全保存的数据。

### 8.3 视觉与可访问性

所有新增 UI 遵循 `docs/DESIGN_SPEC.md`：现有暖杏蓝变量、`880px` 内容宽度、卡片/控件圆角、44px 最小控件高度、键盘可操作、标签与错误消息关联、减少动效支持。不得引入新的颜色体系或改变病例工作区布局尺度。

## 9. 错误、并发与兼容

- 目录不可用：新建/修改返回 503 `indicator_catalog_unavailable`；历史读取继续可用。
- 规范化失败：返回 422 和稳定字段路径，不保存部分时间线。
- 行锁和单事务继续保证病例状态与聚合保存一致；归档或停用病例返回 409。
- 同一请求重试沿用现有创建幂等键；修改失败保留前端草稿。
- 新字段采用 additive migration；发布顺序必须是迁移 → 后端 → 前端，避免旧后端因 `extra=forbid` 拒绝新字段。
- 旧报告没有 `visit_context`、目录版本或完整性字段时，仅安全降级显示；不重新计算、不补写。
- `visit_id` 可能因整批替换改变，任何业务逻辑不得将其当作访视序号或外部稳定身份。

## 10. 测试与验收

### 后端

- 目录加载、manifest hash、审批状态和模型代码映射；
- 中英文别名、大小写/Unicode 单位归一化和非法单位；
- 未知/跨疾病/重复指标；NaN、Infinity、布尔值和空值；
- AD 量表安全范围及上下文缺失降级；
- 时间线 1、3、10 次通过，0、11 次失败，日期重复失败；
- 聚合替换、重排、审计脱敏和输入快照；
- 年龄、性别、阶段缺失、冲突、终末阶段和旧病例兼容；
- 真实 PostgreSQL 迁移、约束、回滚保护和双操作者权限隔离。

### 前端

- 指标添加/删除、访视添加/删除和最后一次保护；
- 清空数值保持 `null`；
- 疾病切换刷新目录并阻止跨疾病指标；
- 单位默认值、别名选择和字段级错误；
- 上下文面板按疾病显示；
- 保存 loading 持续到请求和 readiness 刷新结束；
- 归档病例只读、旧指标兼容警告和键盘/ARIA 行为。

### 端到端

在独立 PostgreSQL 测试库和浏览器 harness 中分别验证脂肪肝、AD：创建 1 次访视、补充到 3 次、修改日期并重排、非法输入被拒绝、报告 readiness 正确、报告快照保留上下文，历史报告和 PDF 仍可读取。

当前仍引用已删除 `LongitudinalCaseEditor.vue` 的两个旧 `frontend/tests/*.mjs` 契约测试必须迁移到新工作区路径或删除，并在最终验收中不能留下已知失败测试。

## 11. 发布验收标准

只有以下条件全部满足，才在《AI 操作者流程核查》中将第 2、3 项更新为“仓库实现完成”：

1. Alembic、ORM、schema 快照和只读检查器一致；
2. 后端和前端专项测试、完整回归、真实 PostgreSQL 集成和浏览器 E2E 全部通过；
3. AD 与脂肪肝都能完成目录驱动的 1→3 次访视流程；
4. 非法指标、单位、数值和上下文不会进入模型；
5. 历史病例、报告、PDF 和旧快照保持只读兼容；
6. 生产迁移、备份、迁移后核对和双疾病冒烟在部署窗口完成后，才能表述为生产已上线。

