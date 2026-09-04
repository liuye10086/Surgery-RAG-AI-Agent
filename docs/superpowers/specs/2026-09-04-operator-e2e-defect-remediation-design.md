# AI 操作者前五项浏览器验收缺陷修复设计

## 1. 背景与目标

管理员账号完成脂肪肝和阿尔茨海默病（AD）电脑端浏览器冒烟后，前四项核心流程可运行，但暴露出标准适用性、标准来源追溯、模型状态文案、输入错误本地化和新建病例状态隔离方面的问题。当前数据库也没有经过批准的非合成参考病例 release，因此参考病例链路必须继续失败关闭，不能用验收病例或合成训练数据填充正式病例池。

本次修复目标是：消除已确认的代码和当前标准数据缺陷，补齐自动化回归与部署门禁，使新报告能准确解释标准规则和模型参与状态；同时明确保留“正式参考病例数据尚未就绪”的安全阻断状态。

## 2. 范围

### 2.1 纳入范围

1. 脂肪肝标准规则的性别适用性判断。
2. manifest 规则与标准原文片段的确定性绑定。
3. 当前数据库已批准版本中既有规则的来源绑定修复。
4. 报告生成前的标准来源完整性校验，以及数据库 postflight 门禁。
5. 阶段模型状态和原因码的准确中文展示。
6. 年龄等统一输入错误的中文展示。
7. 从病例详情和报告页进入“新建病例”时的表单状态隔离。
8. 后端、前端、数据库检查器和双病种浏览器回归。

### 2.2 不纳入范围

1. 不创建、伪造或激活参考病例 release。
2. 不把本次 E2E 验收病例加入正式参考病例池。
3. 不改变现有模型 artifact、模型 active 指针或模型训练结果。
4. 不改变脂肪肝和 AD 已获认可的标准医学内容。
5. 不把所有草稿规则的 `source_segment_id` 改为数据库级非空；草稿和人工审核阶段仍允许暂未绑定，只有已批准/current 运行链路必须来源完整。

## 3. 已确认根因

### 3.1 性别规则未进入 EvidenceBundle 的适用性判断

`StandardRule.sex` 是独立字段。旧的标准解析器会把它追加为 `EqualsNode("sex", rule.sex)`，但 EvidenceBundle 使用的 `standard_evidence.py` 只解析 `rule.applicability`。因此男性脂肪肝病例会同时匹配男性和女性 ALT 参考范围。

### 3.2 manifest 导入主动写入空来源

`standard_manifest_import.py` 创建规则时固定写入 `source_segment_id=None`。当前数据库实际存在标准片段，但脂肪肝 11 条规则和 AD 8 条规则都没有来源外键，导致页面和 PDF 显示 `source unavailable`。

### 3.3 当前门禁没有要求已批准规则来源完整

标准预检会验证文档哈希、版本哈希和 manifest 标识，但没有验证 current approved 规则必须绑定到同版本的原文片段。数据库 postflight 同样没有检查该运行时约束，所以不可追溯数据仍能生成报告。

### 3.4 报告将所有不可用阶段模型统一描述为未配置

模型结果已经保存 `status=incompatible` 和 `reason_code=required_feature_missing`，但报告生成器把所有非 `available` 状态统一写成“尚未配置”。这掩盖了模型存在但输入契约不满足的真实原因。

### 3.5 API 直接展示 Pydantic 英文错误

年龄 121 能被后端正确拒绝，但通用错误路径把 Pydantic 的英文 `msg` 直接交给前端。错误行为安全，但不满足中文操作者界面的可理解性要求。

### 3.6 新建病例存在状态隔离风险

浏览器验收中曾出现一次从既有病例进入新建模式后保留旧字段和访视的现象，后续路径未稳定复现。需要用组件级路径测试分别覆盖病例详情和报告页入口，以确认具体状态转换并防止回归。

## 4. 方案选择

采用完整闭环方案：运行时正确性修复、导入时来源绑定、既有数据修复工具、运行前失败关闭、部署后只读门禁和浏览器回归共同完成。

不采用仅修改页面表现的补丁方案，因为它不能修复数据库中不可追溯的标准规则。也不采用 `source_segment_id NOT NULL` 全表约束，因为该约束会错误阻断合法的草稿和人工审核流程。

## 5. 详细设计

### 5.1 统一有效适用条件

在标准证据服务中提供一个只负责构造运行时条件的内部函数：

```python
def build_effective_applicability(rule: Any) -> ConditionNode:
    node = adapt_v1_applicability(rule.applicability or {})
    if rule.sex:
        node = AllNode(children=(*node.children, EqualsNode("sex", rule.sex)))
    return node
```

EvidenceBundle 和既有 resolver 都复用这一逻辑，不再各自拼接条件。有效适用性哈希覆盖规范化后的 `applicability` 与独立 `sex` 字段，使哈希与实际参与判断的条件一致。历史报告保存的旧哈希保持不可变；只有新报告使用新哈希。

预期状态：

- 性别与规则一致：继续判断其他适用条件。
- 病例未记录性别：`missing_context`。
- 性别与规则不一致：`not_applicable`。
- 只有状态为 `calculable` 且全部条件匹配的脂肪肝规则才产生数值范围解释。

### 5.2 manifest 原文片段解析与绑定

新增独立的来源匹配函数，输入为 `ReferenceStandardVersion` 和 manifest entry，输出唯一 `StandardSegment`。匹配顺序固定为：

1. 限定 `segment.version_id == version.id`。
2. 使用 manifest source 中存在的 `paragraph_index`、`table_index`、`row_index` 和 `column_index` 过滤。
3. 对规范化换行和首尾空白后的 `raw_text` 做完全相等比较。
4. 必须恰好匹配一条；零匹配返回 `source_segment_missing`，多匹配返回 `source_segment_ambiguous`。

`import_manifest_rules` 在创建任何新规则前先完成全部来源解析。只要一条失败，整个事务不写入规则，防止部分可追溯、部分不可追溯的版本进入审核。

规则的 `source_segment_id` 使用唯一匹配结果，不复制原文内容，也不依赖本机文件路径。

### 5.3 既有规则来源修复工具

增加只处理 manifest 导入规则的命令行工具。默认 dry-run，显式 `--apply` 才修改数据库：

```text
python scripts/bind_standard_rule_sources.py --standard fatty_liver
python scripts/bind_standard_rule_sources.py --standard ad
python scripts/bind_standard_rule_sources.py --standard fatty_liver --apply
python scripts/bind_standard_rule_sources.py --standard ad --apply
```

工具通过规则 `applicability._manifest_entry_id` 找到已批准 manifest entry，再调用与导入流程相同的唯一来源匹配函数。写入前验证：

- 标准、current version、manifest 的疾病和版本标签一致。
- 文档 SHA-256 与 manifest 一致。
- 规则和来源片段属于同一版本。
- 现有非空来源若与确定结果不同，则失败，不自动覆盖。
- 所有计划修改先完整计算；任何异常时不提交部分结果。

输出只包含版本、规则数量、待绑定数量、已一致数量和稳定错误码，不输出数据库连接串或完整医学原文。当前本地数据库先执行 dry-run，确认 19 条规则全部唯一匹配后才执行 apply。

### 5.4 标准运行时和部署门禁

`preflight_standard` 对 current approved version 增加以下要求：

- 每条运行规则必须有 `source_segment_id`。
- 关联片段必须存在且属于同一版本。
- 片段 `raw_text` 不能为空。
- manifest entry 的来源定位和规范化原文必须与关联片段一致。

任一条件失败统一产生稳定的 `standard_integrity_failed`，并在模型加载前停止报告生成。

`scripts/check_database_readonly.py --phase postflight` 增加按病种汇总的来源完整性检查，至少返回：规则总数、已绑定数、跨版本来源数、空原文数和是否匹配。postflight 只有两个 current approved 标准均满足来源完整性时，证据存储部分才通过。

参考病例 release 继续作为独立的运行时检查。修复完成后，只要正式参考数据尚未激活，整体 postflight 仍应返回 `FAIL`，并明确唯一剩余原因是 `active_releases_match=false`，不能把该状态误报为代码修复失败。

### 5.5 阶段模型状态文案

后端报告生成器建立稳定的状态文案映射，页面摘要沿用相同语义：

| 状态/原因 | 中文说明 |
| --- | --- |
| `available` | 阶段模型已参与本次推理 |
| `not_configured`、`model_missing` | 当前未配置可用的阶段模型 |
| `incompatible + required_feature_missing` | 阶段模型存在，但本次输入缺少必需特征，因此未预测下一阶段 |
| `not_applicable` | 当前基线阶段不适用阶段预测 |
| `failed`、`prediction_failed` | 阶段模型推理失败，未生成阶段预测 |
| 其他未知状态 | 阶段模型不可用，未生成阶段预测，并保留稳定原因码供技术附录追溯 |

同一映射覆盖第 5 节、第 6 节和第 6.1 节，避免同一报告出现互相矛盾的描述。

### 5.6 API 校验错误中文化

在统一的请求校验异常处理层根据 Pydantic 错误 `type`、字段路径和约束上下文生成中文消息，不匹配英文 `msg` 文本。首批覆盖操作者病例链路使用的错误：

- `less_than_equal`：必须小于或等于指定上限。
- `greater_than_equal`：必须大于或等于指定下限。
- `missing`：必填字段不能为空。
- `int_parsing`、`int_type`：必须填写整数。
- 字符串长度、枚举值和列表数量边界。

响应继续保留稳定 `code`、`field` 和 `issues` 结构；未知错误使用不泄露内部信息的中文兜底。前端只展示服务端结构化中文消息，不维护第二套校验翻译表。

### 5.7 新建病例状态隔离

首先增加组件测试，分别模拟：

1. 在病例详情页点击侧边栏“新建病例”。
2. 在历史报告页点击侧边栏“新建病例”。
3. 点击工作区内“新建纵向病例”。

每条路径都必须得到新的表单对象：疾病、基线阶段、备注、日期、指标和检测上下文为空；年龄和性别使用产品既有的明确默认值，不引用旧病例对象；报告与预测摘要清空；任何异步详情响应不能覆盖新建态。

若失败测试确认是异步竞态，则在选择状态中加入请求身份校验或新建态令牌；若只是入口未调用统一 reset，则所有入口改为调用同一个 `startNewCase()`。只实施失败测试证明需要的最小修复。

## 6. 数据流和事务边界

```text
approved manifest
→ 在同一版本内唯一解析原文片段
→ 事务性创建规则并绑定 source_segment_id
→ current approved 标准预检验证来源和有效适用条件
→ 模型调用
→ 构建 EvidenceBundle（性别、上下文、原文位置均已固定）
→ 保存不可变证据快照和哈希
→ 页面、历史报告、PDF 共用同一快照
```

既有数据修复流程为：

```text
dry-run 全量解析
→ 19 条规则均唯一匹配
→ 显式 apply 单事务更新
→ postflight 来源完整性通过
→ 双病种新报告冒烟
```

## 7. 失败处理与安全性

- 来源缺失、歧义、跨版本或原文不一致：失败关闭，不生成新报告。
- 性别缺失：不选择性别限定规则，不推测性别。
- 性别不匹配：规则标记为不适用，不参与数值解释。
- 既有来源冲突：修复工具停止，不覆盖人工绑定。
- 阶段模型输入不完整：保留结局和趋势结果，只准确说明阶段模型未参与原因。
- 参考病例 release 缺失：标准和模型结果可保存为 `partial/reference_index_stale`，不读取旧索引。
- 历史报告不重算、不回写，保持原有快照和哈希。
- 日志和工具输出不包含患者标签、自由文本病例、完整医学原文或数据库凭据。

## 8. 测试与验收

每项修复采用测试驱动：先加入最小失败测试并确认因目标缺陷失败，再实施最小修复并运行专项回归。

### 8.1 后端

- 男性病例只匹配男性 ALT 规则，女性病例只匹配女性规则。
- 性别缺失和不匹配分别产生 `missing_context` 与 `not_applicable`。
- 适用性哈希随规则性别变化。
- manifest 来源唯一匹配成功；缺失、歧义、跨版本全部失败。
- 修复工具 dry-run 不写数据库，apply 幂等，冲突时完整回滚。
- current approved 规则来源缺失时，标准预检在模型前失败。
- 阶段模型各状态和原因码生成准确中文文案。
- 年龄 121 返回结构化中文错误，不出现 Pydantic 英文消息。

### 8.2 前端

- 三个新建入口均清空旧病例、报告和预测状态。
- 年龄越界错误显示后端返回的中文字段消息。
- 阶段模型摘要区分未配置、缺少特征、不适用和推理失败。
- 继续遵循 `docs/DESIGN_SPEC.md` 的颜色、排版、错误状态和无障碍规范；本次不重新设计布局。

### 8.3 数据库和浏览器

- 当前本地数据库 19 条规则全部绑定同版本非空原文片段。
- 来源完整性检查通过；参考病例 release 检查继续按真实状态失败。
- 新建脂肪肝男性病例只展示男性 ALT 标准。
- 新建 AD CDR 病例在上下文完整时显示 `evidence_only`，不做数值诊断。
- 两病种阶段模型缺少特征时显示准确原因。
- 历史报告和 PDF 继续使用保存快照，完整性验证通过。

## 9. 完成标准

1. 所有新增回归测试均完成红—绿验证。
2. 后端相关专项、前端组件测试和生产构建通过。
3. 标准来源修复 dry-run 与 apply 输出可审计，重复执行不产生新修改。
4. 当前数据库只有正式参考病例 release 缺失这一项部署阻断。
5. 脂肪肝和 AD 浏览器冒烟结果与本设计一致。
6. 不删除本次 E2E 病例或历史报告，不创建虚假参考病例数据。
