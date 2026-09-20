# 预测模型重构阶段四：合成历史候选接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将唯一选定的AD 12个月RF历史数值候选接入现有数值报告流程，保持另外三任务和旧报告兼容，完成可复核的隔离验收。

**Architecture:** 新严格JSON混合包嵌入旧B包和一个RF模型，四任务路由固定，候选与末次值基线独立记录状态。新增v3上下文／报告及v6发布分支，复用现有受理、worker、RAG、页面和PDF，旧模型源码及提示词保持不变。

**Tech Stack:** Python 3.11.4；现有NumPy 2.3.5、scikit-learn 1.9.0用于显式构建／测试；新纯推理不调用它们进行计算，但复用的旧日期／OLS模块在冷启动时会间接导入已安装NumPy，不能宣称运行时完全不依赖NumPy。FastAPI、Pydantic、SQLAlchemy、Alembic；Vue 3、TypeScript、Element Plus；Node.js 22.15.0、npm 10.9.2。

日期：2026-09-16（S6 于 2026-09-18 执行）。版本：0.7。状态：**S1–S6全部完成，阶段四合成工程实施6／6。S6 隔离端到端验收以真实 API／独立 worker／真实检索／DeepSeek／Chromium 归档实际执行并退出0（5 份报告、5 次说明生成、5 份归档原件）；迁移与降级、权限、排队版本切换、取消、幂等及旧历史／PDF 保全均有实际证据。未单独演练“既有 v5 行跨 0031 upgrade 的保全”；后端非 integration 回归另有 2 项可追溯到阶段二／三提交的既有失败。** 依据：[阶段四设计](../specs/2026-09-16-prediction-model-refactor-phase-4-history-integration-design.md)、[总领](../specs/2026-09-09-prediction-model-refactor-master-design.md)、[阶段三交接](2026-09-15-prediction-model-refactor-phase-3-offline-comparison.md#12-t6结果解释与阶段交接2026-09-16)。

## Global Constraints

- 用户暂无真实数据，继续合成先行；阶段二、三合成工程均已完成，不把真实资料开放项重新列成本阶段前置工作。
- 只选`ad.mmse.12m`的`random_forest:history_v1:value_history`，来源seed20260914；其余三任务原样继承指定基包B，全部保留独立末次值基线，不重新选优或调参。
- 基包B路径、canonical SHA、历史包manifest原字节SHA及数据身份精确值见设计第2节；只能使用这些冻结输入，不以当前目录“最新文件”自动替代。当前配置文件没有模型包赋值，不宣称B是正在运行的活动包。
- 使用项目`backend/.venv`和上述固定运行时；没有新依赖、环境升级或模型下载，前端仅npm/package-lock.json。
- 新`numeric_model_bundle.v2`、`numeric_prediction.v3`、`numeric_generation_context.v3`、`numeric_report_document.v3`、template v3、prompt v2和fingerprint v6；输入保持`numeric_input.v1`。
- 源码实现摘要覆盖的旧模型模块、阶段三模块及旧提示词保持原字节；不得绕过hash检查或改旧manifest。新推理只使用保存参数，无训练、数据库、磁盘或网络访问。
- 任务结果采用`available|abstain|error`；离线valid显式映射为available。历史不足不回填基线，有限越界不裁剪，制品损坏整体验证失败。报告完成不表示所有预测可用。
- `source_kind=synthetic`、`clinical_validity_claim=false`、`clinical_status=not_assessable`；新包仅接受合成输入。不得复用合成名义日期、成绩或阈值宣布真实临床通过。
- 来源、输入、训练、评价、组合／逐任务算法、prompt、检索、正文及归档身份均可追溯；历史只核验保存事实，不调用当前模型／RAG／LLM替换旧结果。
- 保留工作区既有PDF／页面展示调整及`docker-compose.test.yml`删除；实现前核对diff，不覆盖、恢复或混入无关工作。UI改动前完整读取`docs/DESIGN_SPEC.md`。
- 集成fixture会迁移和TRUNCATE，仅使用明确可丢弃的本机`surgery_rag_phase4_test`；不得回退`DATABASE_URL`或复用已有`surgery_rag_test`。实际LLM／PDF链路只按该步骤明确授权执行。
- 本计划编写不授权执行训练、迁移、外部调用、发布或提交；用户要求执行某步时按该步已写明范围推进。每步交付列实际检查、失败／跳过、剩余和下一步。

## 1. 六步顺序与独立交付

| 步骤 | 交付 | 依赖 | 验收重点 |
| --- | --- | --- | --- |
| S1（已完成） | 严格混合包／任务结果契约、历史投影和纯推理 | 已冻结设计 | 树结构、float32、三态、继承参数、无未来输入 |
| S2（已完成） | 固定RF重建、导出、全量回放和新制品 | S1 | 一个模型、三个角色逐值相等、旧参数不变、输入防漂移 |
| S3（已完成） | v3受理上下文、路由、0031迁移 | S1、S2制品身份 | 双捕获、幂等、权限、完整性及降级保护 |
| S4（已完成） | v3执行、说明、正文、v6发布及历史核验 | S3 | 固定参数、部分结果、LLM拒绝路径、旧任务兼容 |
| S5（已完成） | 页面、类型、打印和新renderer | S4 | 独立结果状态、算法描述、两位小数、旧PDF不变 |
| S6（已完成） | 隔离端到端验收、文档及阶段五交接 | S1–S5 | 实际API／worker／检索／LLM／PDF／权限与版本切换 |

S1–S5各步先写能揭示错误的测试，运行确认预期失败，再最小实现和复核；S6先核验前置条件，缺少条件时保留未执行状态。提交／推送按用户单独指令，不在每步自动执行。

## 2. 文件职责与接口约定

新增文件按单一职责划分，避免把旧版本原地改成多算法平台：

| 新文件（仓库相对路径） | 职责 |
| --- | --- |
| `backend/app/schemas/numeric_history_bundle.py` | 树、RF参数、历史评价、固定路由及混合包schema |
| `backend/app/schemas/numeric_history_prediction.py` | 组合／逐任务算法、三态结果、独立基线 |
| `backend/app/services/numeric_history_features.py` | 严格输入到H资格及历史特征；复用旧OLS纯函数 |
| `backend/app/services/numeric_history_bundle.py` | 严格加载、摘要、runtime核验和无IO推理 |
| `backend/app/services/numeric_history_bundle_build.py` | 唯一RF重建、JSON导出、来源和回放核验 |
| `scripts/build_numeric_history_bundle.py` | 预检、显式构建和只读复核CLI |
| `backend/app/schemas/numeric_report_v3.py` | 固定上下文、报告、发布及新叙述类型 |
| `backend/app/services/numeric_model_dispatch.py` | 从既有配置严格分派baseline／v1包／v2包 |
| `backend/app/services/numeric_report_v3_admission.py` | 捕获v3上下文及readiness |
| `backend/app/services/numeric_report_narrative_v2.py` | 独立prompt v2、请求和保存说明校验 |
| `backend/app/services/numeric_report_v3.py` | 保存事实核验、canonical正文和v6发布 |
| `backend/app/workers/numeric_report_v3.py` | v3固定上下文执行及现有审计协议 |
| `backend/alembic/versions/0031_numeric_history_publication.py` | v6约束及拒绝丢失事实的downgrade |
| `scripts/run_numeric_history_acceptance.py` | 新范围的隔离验收，复用现有进程控制 |
| `scripts/numeric_history_acceptance_browser.py` | 两病种／部分结果的实际页面与归档下载检查 |

固定新接口如下；所有`dict`入口在业务计算前经对应严格schema重解析，类型注解不能代替校验：

```python
project_numeric_history_features(packet: NumericInputPacket) -> HistoryFeatureResult
load_numeric_history_bundle(path: Path) -> NumericHistoryBundle
history_bundle_sha256(bundle: NumericHistoryBundle) -> str
verify_numeric_history_runtime(bundle: NumericHistoryBundle) -> None
predict_tree_json(tree: RfTree, standardized_features: tuple[float, float, float]) -> float
predict_forest_json(features: list[float], model: NumericHistoryRfModel) -> float
predict_numeric_history_bundle(numeric: NumericInput, bundle: NumericHistoryBundle) -> NumericPredictionV3
build_numeric_history_bundle(history_dir: Path, legacy_bundle_path: Path, output_dir: Path) -> dict
verify_numeric_history_bundle(output_dir: Path) -> dict
capture_numeric_v3_context(snapshot: dict, db: Session) -> NumericGenerationContextV3
evaluate_numeric_v3_readiness(case: OperatorCase, db: Session) -> OperatorCaseReportReadiness
generate_numeric_narrative_v2(numeric, prediction, evidence, *, llm_model: str) -> NumericNarrativeV2
validate_numeric_v3_snapshot(snapshot: dict, context) -> tuple[NumericGenerationContextV3, NumericInput]
build_numeric_v3_document(report_id, created_at, snapshot, context, prediction, evidence, narrative) -> NumericReportDocumentV3
build_numeric_v3_publication(snapshot, prediction, document) -> NumericPublicationV3
verify_numeric_v3_integrity(snapshot, snapshot_sha256, fingerprint, prediction, content,
                            evidence, evidence_sha256, document, document_sha256, saved_sources) -> bool
execute_numeric_v3_report(payload: dict, send: Callable[[dict], None]) -> None
```

`NumericHistoryBundle`嵌入完整旧`NumericModelBundle`，通过`legacy_bundle_sha256`验证，另有唯一`history_model`和固定四项`task_assignments`；详细字段、不可变顺序、评价12行及三个角色定义见设计第3节。`RfTree.nodes`用`kind=branch|leaf`作联合类型判别；`HistoryFeatureResult`及结果reason闭合集见设计第3.2／4节。

## S1：严格契约、历史投影与纯推理

**Files:** 新增第2节前四个文件；新增`backend/tests/test_numeric_history_features.py`、`test_numeric_history_bundle.py`、`test_numeric_history_prediction.py`。不修改旧模型schema／service、阶段三源码或旧输入schema。

**Interfaces:** 消费`NumericInput`、`NumericInputPacket`及`NumericModelBundle`；产生`NumericHistoryBundle`、`HistoryFeatureResult`、`NumericPredictionV3`及第2节前七个接口，供S2导出及S3固定上下文使用。

- [x] **1. 建立投影及树边界失败测试。** 复用已有`test_numeric_prediction.numeric_fixture`；树用手写确定性叶值，不能只断言调用成功。例如：

```python
from app.schemas.numeric_prediction import NumericInputPacket
from app.schemas.numeric_history_bundle import RfTree
from app.services.numeric_history_features import project_numeric_history_features
from app.services.numeric_history_bundle import predict_tree_json
from test_numeric_prediction import numeric_fixture

def test_confirmed_no_history_abstains_without_zero_fill():
    packet = numeric_fixture('ad')['packets'][1]
    packet['input_observations'] = [r for r in packet['input_observations']
                                  if r['observation_id'] == packet['anchor_observation_id']]
    packet['history_state'], packet['history_coverage'] = 'confirmed_none', 'complete'
    result = project_numeric_history_features(NumericInputPacket.model_validate(packet))
    assert (result.eligible, result.status, result.reason) == (False, 'abstain', 'history_not_observed')
    assert result.prior_value is None and result.slope_per_day is None

def test_rf_uses_float32_features_and_double_threshold():
    tree = RfTree(nodes=[
        {'kind': 'branch', 'feature_index': 0, 'threshold': 1 + 2**-26, 'left': 1, 'right': 2},
        {'kind': 'leaf', 'value': 10.0}, {'kind': 'leaf', 'value': 20.0},
    ])
    assert predict_tree_json(tree, (1 + 2**-25, 0.0, 0.0)) == 10.0
```

- [x] **2. 运行上述测试确认尚未实现接口导致预期失败。** 在backend运行`.\.venv\Scripts\python.exe -m pytest tests/test_numeric_history_features.py tests/test_numeric_history_bundle.py tests/test_numeric_history_prediction.py -q`；记录失败原因，禁止把环境问题当作有效红灯。
- [x] **3. 实现严格结构与无IO计算。** 按设计实现树可达性／深度／索引、固定路由、证据及hash、输入H资格、原OLS、float32阈值和树顺序归约。固定特征名`['anchor_value','prior_value','slope_per_day']`，新结果中每任务算法与路由一一绑定，baseline只读锚点。组合身份固定`numeric.mixed_history.v1`；运行时摘要仅覆盖模型实现依赖，不能让后续报告／UI编辑使包失效。

```python
# RF单树比较的明确数值规则；在predict_tree_json内应用。
import struct
features32 = tuple(struct.unpack('!f', struct.pack('!f', x))[0]
                   for x in standardized_features)
index = 0
while tree.nodes[index].kind == 'branch':
    node = tree.nodes[index]
    index = node.left if features32[node.feature_index] <= node.threshold else node.right
return tree.nodes[index].value
```

- [x] **4. 补齐实际行为测试并通过。** 包含重复feature合法、单叶合法、环／多父／孤儿／越深／bool索引拒绝、200树顺序、常量列、非有限和float32溢出、乱序输入、未来记录拒绝、H资格与计算error分离；补测锚点不可用时将旧`anchor_not_available`映射为packet具体输入原因的各分支。完整混合包夹具使用旧`bundle_fixture()`保留原基包，200棵明确叶值树及自洽的严格证据，不伪装为正式制品。AD无历史时断言6月候选与两个基线可用、12月abstain；有限越界只保留审计raw值；包损坏必须抛错。阻断训练／sklearn、磁盘、网络仍可执行纯推理。
- [x] **5. 运行S1测试及旧模型／输入回归，独立复审接口与结果语义。** 追加`tests/test_numeric_model_bundle.py tests/test_numeric_prediction.py tests/test_prediction_history_features.py`。只核验纯行为，不加载外部资源；记录新旧测试数并交付S1，剩5步、下一步S2。

## S2：固定制品重建、导出及逐值回放

**Files:** 新增`backend/app/services/numeric_history_bundle_build.py`、`scripts/build_numeric_history_bundle.py`、`backend/tests/test_numeric_history_bundle_build.py`、`scripts/tests/test_build_numeric_history_bundle.py`。输出仅写第2节规定的新目录，不更改来源包。

**Interfaces:** 消费S1 schema／投影／推理、冻结B包、阶段三manifest／协议／原始输入／模型／预测／评价；产生新混合包、manifest、replay和`build_numeric_history_bundle`／`verify_numeric_history_bundle`接口。默认CLI只预检，`--build`显式执行固定重建，`--verify-dir`只读复核已导出参数与回放，不重新拟合。

- [x] **1. 先写构建门控和回放失败测试。** 原包路径缺失、hash错误、重复JSON键、源码／运行时漂移、目录已存在、训练组跨角色、RF预处理／训练身份不一致、任一原始预测差异时失败。预检不得调用fit、创建目录或连接数据库；覆写模型参数但保持汇总MAE不变也必须被逐值检查发现。
- [x] **2. 运行两个新测试文件确认预期失败，再实现单一选择规则。** 只从封存模型记录选`seed=20260914/task=ad.mmse.12m/model_id=random_forest:history_v1:value_history`。复制原训练排序、H资格、label有效性、标准化、训练hash与固定RF配置，定向重建一个模型；不通过旧`fit_history_models`重跑40个候选。资格合格但派生值error时必须失败，不能删行后继续。

```python
SELECTION = {
    'schema_version': 'numeric_history_selection.v1',
    'seed': 20260914,
    'task_id': 'ad.mmse.12m',
    'model_id': 'random_forest:history_v1:value_history',
}
# 回放比较校验身份、状态、原因和每一个未舍入的value。
assert rebuilt_model['training_identity_sha256'] == recorded_model['training_identity_sha256']
assert rebuilt_model['training_data_sha256'] == recorded_model['training_data_sha256']
assert rebuilt_model['training_target_sha256'] == recorded_model['training_target_sha256']
```

上述逐字段比较在构建器内实现；不能仅依赖assert保护生产入口，正式失败抛稳定错误码并让CLI非零退出。

- [x] **3. 实现安全导出及完整验证。** RF将sklearn树数组导出S1严格节点类型，验证200棵树；B完整原样嵌入，三项实际执行的Ridge参数hash不变。`replay.json`保存每角色计数、最大差异和状态差异，另保存新投影全部4800行与旧投影的等价摘要。生成完整状态仅在所有门控通过后写入；源文件在构建前后复核，失败不留下passed清单。
- [x] **4. 运行构建单测通过，再执行一次固定完整重建。** 以下命令已按S2明确范围执行，实际结果见第3.3节：

```powershell
# 仓库根目录；第一条只读，第二条只重建唯一选定RF。
.\backend\.venv\Scripts\python.exe scripts/build_numeric_history_bundle.py --history-dir outputs/synthetic-prediction-history/2026-09-15-v1 --legacy-bundle outputs/numeric-acceptance/2026-09-15/model-v2/bundle.json --output-dir outputs/numeric-history-integration/2026-09-16-v1
.\backend\.venv\Scripts\python.exe scripts/build_numeric_history_bundle.py --history-dir outputs/synthetic-prediction-history/2026-09-15-v1 --legacy-bundle outputs/numeric-acceptance/2026-09-15/model-v2/bundle.json --output-dir outputs/numeric-history-integration/2026-09-16-v1 --build
.\backend\.venv\Scripts\python.exe scripts/build_numeric_history_bundle.py --verify-dir outputs/numeric-history-integration/2026-09-16-v1
```

预检、构建、独立新进程复核均应退出0；指定RF1200行回放含503 available／697 abstain／0 error，逐值差异0，4800行投影差异0。内部验证／挑战只用于回放，不能参与拟合；不是新临床评估或新的bootstrap。

- [x] **5. 复核旧A/B runtime、封存包原字节和三项Ridge行为。** 保留模型构建日志及新身份，错误如实记录；没有修改应用配置。独立复审后交付S2，剩4步、下一步S3。

## S3：v3受理上下文与数据库兼容

**Files:** 新增`backend/app/schemas/numeric_report_v3.py`（本步上下文）、`backend/app/services/numeric_model_dispatch.py`、`backend/app/services/numeric_report_v3_admission.py`、`backend/app/services/numeric_report_narrative_v2.py`（本步冻结PROMPT／PROMPT_VERSION常量）、`backend/alembic/versions/0031_numeric_history_publication.py`；修改`backend/app/services/report_generation_service.py`、`backend/app/db/models.py`及实际readiness调用方`backend/app/api/operator.py`。新增`backend/tests/test_numeric_report_v3_admission.py`、`backend/tests/integration/test_numeric_report_v3_admission.py`，修改`backend/tests/test_alembic_contracts.py`；同步`backend/tests/integration/test_numeric_report_v2.py`虚构模型fixture的runtime替身，以适配新增分派校验。

**Interfaces:** 消费S1加载／runtime及S2真实包；产生`NumericGenerationContextV3`、`capture_numeric_v3_context`、`evaluate_numeric_v3_readiness`，保持HTTP受理契约和旧上下文分支。

- [x] **1. 写默认空配置、旧v1、新v2、未知schema、损坏包和real输入的分派测试。** 只接受设计中冻结的三条路径；新包real输入拒绝，旧路径不受影响。H不足不阻断整份报告受理；缺task不是历史不足。
- [x] **2. 写并实现上下文双捕获。** 新上下文保存完整包、输入／来源、参考、算法、prompt全文／hash、LLM／检索设置和template。schema按任务核验来源、单位、特征及身份；外层仍为`numeric_prediction`、空model_options。预检与事务内重新捕获不相同则拒绝，幂等命中返回保存报告；校验病例归属、角色、病种和病例版本。

```python
# 显式版本路由的结果，不根据字段“像不像”猜测算法。
ROUTES = {
    'numeric_model_bundle.v1': 'numeric_generation_context.v2',
    'numeric_model_bundle.v2': 'numeric_generation_context.v3',
}
# 空配置保持numeric_generation_context.v1；非空未知版本一律失败。
```

路由模块自身严格读取JSON，并调用对应加载器和runtime验证；旧v2受理函数保留，不让旧schema接受v2包。

- [x] **3. 新增0031约束并同步ORM。** 保留旧v5约束，仅扩展允许v6并新增v6/document.v3完整发布约束；条件用`IS TRUE`避免NULL穿透。downgrade以EXISTS检查v6报告／v3文档／任意状态v3任务上下文并拒绝，先检查再删除约束。编写迁移不执行现有数据库迁移。
- [x] **4. 运行S3单测及Alembic静态契约测试。** 在backend运行`.\.venv\Scripts\python.exe -m pytest tests/test_numeric_report_v3_admission.py tests/test_numeric_report_admission.py tests/test_alembic_contracts.py -q`。真实数据库约束、事务和downgrade测试编写在隔离integration文件，本步如无专用库明确未执行，统一纳入S6，不宣称数据库验收已通过。
- [x] **5. 独立复核受理／版本与旧hash保全。** 实际运行配置仍未改变；交付S3，剩3步、下一步S4。

## S4：v3执行、说明生成、发布和历史

**Files:** 完善`backend/app/schemas/numeric_report_v3.py`和`backend/app/services/numeric_report_narrative_v2.py`；新增`backend/app/services/numeric_report_v3.py`、`backend/app/workers/numeric_report_v3.py`；修改`backend/app/workers/report_execution.py`、`backend/app/schemas/report_document.py`、`backend/app/services/report_integrity.py`、`backend/app/services/report_read_service.py`、`backend/app/services/report_generation_service.py`、`backend/app/services/report_generation_errors.py`及`backend/app/services/report_job_repository.py`的必要类型／发布分派。新增`backend/tests/test_numeric_report_v3.py`、`test_numeric_report_narrative_v2.py`、`backend/tests/integration/test_numeric_report_v3.py`。

**Interfaces:** 消费保存的v3上下文、NumericInput和固定参考；产生新叙述、document.v3、fingerprint v6及第2节对应build／verify／execute接口。旧v1–v5解析及指纹算法保持。

- [x] **1. 用新固定夹具写失败测试。** 按既有`test_numeric_report_v2.v2_fixture`模式建立`v3_fixture(disease='ad', history_state='observed')`，使用S1测试混合包、固定时间／输入、空或有界参考和显式保存LLM响应；不通过生产API提供测试模式。断言候选与基线状态可以不同、任务算法不能调换、source/hash/prompt/evidence/document任一篡改均拒绝。
- [x] **2. 实现独立prompt v2与内容校验。** 完整提示词规则见设计4.1；payload包含任务descriptor/status及基线，算法／特征事实由确定性报告段落输出。测试错误算法、把abstain说成成功、正文数字、来源标签、非法引用、过滤拒绝、LLM异常和非法JSON均不发布；旧Ridge-only prompt及validator不修改，不增加自动重试。
- [x] **3. 实现保存事实与v6指纹。** 同时核对snapshot、组合／任务参数、候选／基线、证据和原始响应；历史核验只用保存版本和保存数据。canonical正文由固定v3模板生成，不能让LLM产生数值表；所有影响输出的saved sources纳入指纹。

```python
fingerprint_payload = {
    'version': 'v6',
    'input_snapshot_sha256': compute_input_snapshot_sha256(snapshot),
    'generation_context': document.generation_context.model_dump(mode='json'),
    'prediction_result': document.prediction.model_dump(mode='json'),
    'content': render_numeric_v3_document(document),
    'evidence_snapshot': document.evidence.model_dump(mode='json'),
    'report_document': document.model_dump(mode='json'),
    'sources': numeric_v3_sources(document.evidence),
}
```

`render_numeric_v3_document(document)->str`和`numeric_v3_sources(evidence)->list[dict]`在本步新增于`services/numeric_report_v3.py`，源字段沿用v2的chunk/document/title/content/score。hash采用既有sort_keys、紧凑JSON、allow_nan=false的SHA-256规则。

- [x] **4. 接入worker与历史分派。** 新worker顺序为runtime／上下文校验→纯推理→固定只读RAG→一次LLM→完整性验证→原子发布；v3的abstain/error审计映射为既有unavailable并携reason，避免发送旧审计schema不认识的状态。缺包／坏包／未知算法、检索双失败、LLM失败均硬失败。当前选择包变化不影响排队任务；保存参数或对应prompt/runtime/retrieval变化失败。取消／租约／超时边界复用原实现。
- [x] **5. 运行新旧报告单测并复核。** 在backend运行`.\.venv\Scripts\python.exe -m pytest tests/test_numeric_report_v3.py tests/test_numeric_report_narrative_v2.py tests/test_numeric_report_v2.py tests/test_numeric_report_narrative.py tests/test_numeric_report_publication.py tests/test_report_document_integrity.py -q`；数据库integration留S6。交付S4，剩2步、下一步S5。

## S5：页面、生成类型与PDF

**Files:** 修改`backend/app/schemas/report_document.py`、`scripts/generate_report_document_types.py`并生成`frontend/src/types/report-document.ts`；修改`frontend/src/api/operator.ts`的prediction_result联合类型、`frontend/src/components/LongitudinalReportView.vue`的文档／进行中上下文分派、`frontend/src/components/report/NumericReportView.vue`的展示分支；修改`backend/app/services/pdf_generator.py`、`backend/app/templates/report_pdf.html`及`backend/app/services/report_pdf_renderer_manifest.py`的v3依赖身份。新增`frontend/src/components/__tests__/NumericReportV3.spec.ts`、`backend/tests/test_numeric_history_print_presentation.py`；扩展`backend/tests/integration/test_numeric_report_pdf.py`和`scripts/tests/test_generate_report_document_types.py`。

**Interfaces:** 消费v3 document/context，沿用旧report DTO入口；生成联合类型增加v3，输出页面／打印HTML及新renderer manifest。不改已经归档的PDF或保存正文。

- [x] **1. 完整读取UI规范并冻结本步前的现有未提交展示改动。** 新增测试以当前两位小数、模型版本后置和参考分页行为为基线；不撤销当前工作区调整。
- [x] **2. 先写v3页面和打印失败测试。** 新夹具`mixedDocument()`明确AD6 available、AD12 abstain、两baseline available；逆序传入任务，断言实际页面按6／12顺序。断言AD12预测`—`且基线正常显示、具体原因和RF描述可见；计算error显示“计算失败”；原始raw_prediction和source绑定不能出现在正文；旧v2布局和舍入回归不变。

```typescript
// 在NumericReportV3.spec.ts中，render沿用现有NumericReportV2测试的挂载方式。
const wrapper = render(mixedDocument())
const rows = wrapper.findAll('tbody tr')
expect(rows.map(row => row.text().includes('6 个月'))).toEqual([true, false])
expect(rows[1]!.text()).toContain('历史不足，未预测')
expect(rows[1]!.text()).toContain('22.00') // 该夹具AD12末次值基线
expect(rows[1]!.text()).toContain('随机森林')
```

`mixedDocument`在同一测试文件构造完整v3展示对象：锚点22.0、AD6继承Ridge值14.0、AD12无候选值／history_not_observed、baseline均22.0，明确任务算法、保存说明及空参考；不能从当前在线接口动态生成期望值。

- [x] **3. 生成类型并增加最小分支。** 从root运行`.\backend\.venv\Scripts\python.exe scripts/generate_report_document_types.py`；扩展正式schema解析与DTO联合，手工类型只在原来源处更新。按设计第6节添加逐项算法、三态和独立baseline显示，保留现有loading／empty／failure及正文净化。v3模型版本段逐任务输出，旧v2仍保持旧说明。
- [x] **4. 修改打印分支并构建新renderer。** 新PDF表义与页面一致，显示舍入不回写canonical值；更新后使用既有`scripts/build_report_pdf_renderer_manifest.py --font-dir <已核实的现有字体目录> --output-dir outputs/numeric-history-renderers/2026-09-16-v1`，以项目Python运行，记录返回的manifest绝对路径及摘要供S6设置`REPORT_TEST_RENDERER_MANIFEST`。字体目录须含运维文档规定的中英文字体及许可证；缺少条件则记录未执行，不自动下载。验证长历史／长参考、部分结果、0值和小数、页末拆分；原归档只能按原字节下载。实际Chromium视觉与归档验收纳入S6，不将HTML单测视为PDF验收。
- [x] **5. 完成前后端检查。** backend运行新打印测试、既有`test_numeric_print_presentation.py`和report document PDF相关单测；frontend运行`npm run test:unit -- NumericReportV3.spec.ts NumericReportV2.spec.ts`、`npm run test:contracts`、`npm run build`。若无浏览器／renderer条件，注明实际页面/PDF未验收并保留S6。交付S5，剩1步、下一步S6。

## S6：隔离总验收与阶段五交接

**Files:** 新增`scripts/run_numeric_history_acceptance.py`、`scripts/numeric_history_acceptance_browser.py`、`scripts/tests/test_run_numeric_history_acceptance.py`；完善S3/S4/S5隔离测试；更新`docs/OPERATOR_REPORT_OPERATIONS.md`、本计划、总领文档，新增`docs/superpowers/notes/2026-09-16-numeric-history-integration-result.md`保存实际记录。

**Interfaces:** 消费固定合成病例包B、新C和旧B模型、完整renderer及显式隔离环境；输出API、独立worker、真实参考检索／一次LLM调用、页面、归档PDF和兼容／失败证据。不切换用户已有运行环境。

- [x] **1. 编写并验证只读预检。** 复用现有隔离目标校验和`run_numeric_report_acceptance.OwnedProcesses`，但新runner独立接受同一输入来源及不同模型代际；不改旧runner的既有专项约束。验证目标本机且为指定可丢弃库、拒绝查询参数／PGSERVICE／PGHOSTADDR重定向、端口空闲、各包不可变、renderer匹配、输出新目录。没有`--apply`不连库、不fit、不导入、不启动服务、不创建输出；没有`--allow-external-llm`不得实际调用LLM。运行时禁止打印连接串和密钥。
- [x] **2. 明确隔离目标并准备真实链路。** 仅在获准执行该隔离验收范围后准备`surgery_rag_phase4_test`、迁移0031、必要测试账号／病例及既有模型资源；集成fixture的TRUNCATE只能作用此可丢弃库。用户已有演示数据库不使用；旧配置和被删除docker-compose文件不恢复。测试LLM失败可使用夹具中的受控适配器，完整成功链路仍须实际调用既有DeepSeek，记录请求次数与结果。
- [x] **3. 执行数据库集成及迁移保护测试。** 显式设置`TEST_DATABASE_URL`后，在backend运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/test_numeric_report_v3_admission.py tests/integration/test_numeric_report_v3.py tests/integration/test_numeric_report_pdf.py tests/integration/test_numeric_report_v2.py -q -rs
```

运行前将`backend/.venv/Scripts`加入当前进程PATH，使fixture调用alembic使用项目解释器；不得改变全局运行时。对带stub的数据库integration如实标注，不能与下一项真实链路混为一谈。

- [x] **4. 执行真实端到端验收。** source B=`outputs/synthetic-prediction-cases/2026-09-15-switch-v2`，legacy B与新C见设计第2节；新runner先生成旧v5报告及归档快照，再临时选择C生成两病种v6及AD部分结果，恢复B后验证旧历史和PDF。固定来源中按已验证条件选择有历史／无历史的测试病例，不从完整患者记录临时剪掉历史伪造来源。

```powershell
# 下列renderer路径由S5的新renderer构建结果提供；执行前明确其真实路径及摘要。
$rendererManifest = $env:REPORT_TEST_RENDERER_MANIFEST
if (-not $rendererManifest) { throw 'REPORT_TEST_RENDERER_MANIFEST is required' }
.\backend\.venv\Scripts\python.exe scripts/run_numeric_history_acceptance.py --source-dir outputs/synthetic-prediction-cases/2026-09-15-switch-v2 --legacy-bundle outputs/numeric-acceptance/2026-09-15/model-v2/bundle.json --history-bundle outputs/numeric-history-integration/2026-09-16-v1/bundle.json --renderer $rendererManifest --output outputs/numeric-history-acceptance/2026-09-16-v1
.\backend\.venv\Scripts\python.exe scripts/run_numeric_history_acceptance.py --source-dir outputs/synthetic-prediction-cases/2026-09-15-switch-v2 --legacy-bundle outputs/numeric-acceptance/2026-09-15/model-v2/bundle.json --history-bundle outputs/numeric-history-integration/2026-09-16-v1/bundle.json --renderer $rendererManifest --output outputs/numeric-history-acceptance/2026-09-16-v1 --apply --allow-external-llm
```

命令应退出0并保存完整记录；失败留下失败事实，不覆盖或原地修复既有报告。新runner关闭其拥有的进程，不结束用户原服务。原v5和新v6的PDF重复下载均核对归档原字节，不现场重渲染替代。

- [x] **5. 覆盖并记录以下验收矩阵。** 每项注明实际层级、命令／产物、通过／失败／跳过／未执行及原因：

| 场景 | 必须观察到的行为 |
| --- | --- |
| AD／ALT成功 | AD12 RF、其他Ridge；末次值独立；v6完整发布、页面及PDF一致 |
| 历史不足 | AD12 abstain，AD6及两baseline正常，原因与模型未执行披露一致 |
| 计算error／有限越界 | 单任务无有效值，raw有限值仅审计；不裁剪、不fallback；另一时距不被覆盖 |
| 损坏／缺task／未知算法 | 受理或worker失败，不发布，不伪装为正常未提供 |
| 排队后选择包改变 | 使用已保存版本；旧v2仍按旧Ridge／prompt规则完成 |
| 保存参数篡改／对应runtime或prompt漂移 | 完整性失败，不静默重选 |
| 检索双失败／LLM失败／非法引用／数字 | 不发布；部分检索及空参考按原规则披露 |
| 幂等／取消／超时／租约 | 原幂等报告不重发；取消或失租后不得发布 |
| 所有者／角色／病种 | 非所有者详情、下载404；错误角色403；不合病种权限拒绝 |
| 新旧历史／PDF | 保存值、正文、指纹、引用、归档原字节不变；当前配置失效仍可读已保存历史 |
| 迁移及降级 | 0031约束拒绝不完整v6；任意v3上下文或v6事实存在时downgrade拒绝 |

故障场景放在隔离测试夹具／局部进程适配器中，不新增生产故障参数或污染固定模型包。

- [x] **6. 完成相关全回归、只读独立复审与交接。** 单元测试先覆盖本阶段模块和受影响旧版本，再运行项目要求的后端非integration／e2e回归与前端单元／契约／构建；已有原始资料默认跳过按开发指南记录。禁止为通过修改断言或跳过标准。更新实际结果、制品身份、旧文件／归档保全；全部必要验收通过才记6／6。没有条件的实际链路保留未完成，不能以文档或mock代替。

## 3. 规划与实施记录

### 3.1 规划核验（S1开始前）

本轮读取当前代码、开发与报告运维文档、阶段三交接；确认A/B旧包canonical摘要及runtime门控通过，未假定当前运行进程选中B。独立审计确认RF需float32特征比较、旧源码摘要边界、v3/v6版本分派、0031约束和现有integration的清理边界。本轮没有运行训练、pytest、数据库迁移、API／worker、外部LLM或PDF生成。

详细设计与本计划的候选、基包、seed、输出三态、版本链及六步顺序一致。独立复审未发现阻断项；锚点不可用原因映射的澄清建议已补充并通过定向复核。文档检查通过：36个本地链接均可解析、无尾随空白、`git diff --check`通过；6个步骤的31项实施清单全部未勾选。规划前记录的892个既有文件／删除状态均未变化，范围外没有新增文件。核验记录保存在本机`.tmp/phase4-planning-verification.json`；这些检查只证明规划与工作区保全，不代表功能、临床或阶段四实施验收通过。

### 3.2 S1完成记录（2026-09-16）

用户要求“开始下一步”后完成S1，新增四个实现／schema模块与三个测试文件，未修改旧模型及阶段三源码。实现严格混合包、树／RF参数、12条评价与12条汇总的闭合证据、固定四任务路由、历史投影及纯推理。候选与末次值基线独立；AD无历史时12个月弃权，6个月及基线仍可用；有限越界仅保留审计raw值，模型包损坏硬失败。

**实际验证：**

- RED：首轮26项因新模块缺失失败；实现后通过。随后代码复审发现并复现了矛盾评价仍被接受、实际使用的函数导入绑定漂移漏检，补回归并修复，没有降低断言。
- 新增测试最终103项通过；在backend用项目Python3.11.4执行以下新旧联合回归，**168 passed in 7.19s，0失败、0跳过**：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_numeric_history_features.py tests/test_numeric_history_bundle.py tests/test_numeric_history_prediction.py tests/test_numeric_model_bundle.py tests/test_numeric_prediction.py tests/test_prediction_history_features.py -q
```

- 独立复审的两项重要问题均已消除，定向复核Approved；复核定向测试21 passed、47 deselected，后者是选择范围未选中，不是跳过或失败。
- 旧A/B实际包canonical摘要与实施前相同，runtime门控通过；914项范围外文件／删除状态保全，无意外新增文件。新文件及文档无尾随空白，`git diff --check`通过。
- 独立冷进程证明不导入sklearn或训练模块；推理期间阻断文件、网络和新增NumPy导入后仍得到预期值。启动时沿旧日期／OLS模块导入现有NumPy，初始“冷启动完全不导入NumPy”诊断失败，已明确记录此既有依赖，不声称无NumPy运行时。
- 封存选定12条评价与12条汇总通过完整证据schema交叉校验；外层使用虚构测试身份，因此这只证明字段／关系兼容，不代表S2制品真实性或完整预测回放通过。

**边界：** 既有回归包含小型合成夹具拟合；没有执行S2固定RF重建、阶段三实验／bootstrap重跑、数据库操作、API／worker、外部LLM、前端／PDF验收、提交或推送。测试夹具不属于正式模型或临床证据。受理、报告及页面入口尚未接入新模块。

S1提供额外的`history_implementation_sha256(legacy_implementation_sha256)`文件身份辅助函数，供S2构建和runtime门控使用；纯推理不调用它。实际B／封存manifest的固定身份由S2构建器限定，S1 schema负责严格结构和自洽性；保存预测值与保存输入／参数的一致性由S4验证。详细本机过程记录见`.tmp/phase4-s1-implement-report.md`、`.tmp/phase4-s1-verification.md`及`.tmp/phase4-s1-preservation-result.json`。

### 3.3 S2完成记录（2026-09-16）

按用户“开始下一步”的单步指令，新增构建器、CLI及两个测试文件。固定使用seed20260914和`ad.mmse.12m / random_forest:history_v1:value_history`，仅对200条原训练集合格记录拟合一次RF，导出200棵树；完整嵌入冻结B包，未重新选优、调参或计算bootstrap。默认预检及`--verify-dir`均不拟合。

**实际验证：**

- RED→GREEN：初始17项因新模块缺失失败；随后追加路径清理边界、manifest声明篡改、来源漂移、分区／训练身份、逐值回放与失败清理回归，新测试最终46项通过。扩展测试中出现的夹具generator_version不匹配已修正，未修改来源协议或放宽生产门控。
- 在backend使用项目Python3.11.4运行下列联合回归，**197 passed in 9.92s，0失败、0跳过**。独立代码复核Approved，另行执行46项新测试通过。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_numeric_history_bundle_build.py tests/test_numeric_history_bundle.py tests/test_numeric_history_features.py tests/test_numeric_history_prediction.py tests/test_numeric_model_bundle.py tests/test_numeric_prediction.py ../scripts/tests/test_build_numeric_history_bundle.py ../scripts/tests/test_build_numeric_model_bundle.py -q
```

- 第S2节三条正式CLI分别在新进程执行：只读预检、唯一固定构建、只读复核均退出0，分别报告拟合数0／1／0。预检前后新输出目录均不存在。耗时分别为2.447／332.672／335.629秒。
- 全部4800条历史投影与封存旧投影逐字段一致；等价摘要为`361b8a2dce350df875cb57a8e884bdee910d86ff484ac16c93c1f4b0a5c07f90`。AD 12月1200条预测的身份、状态、原因及未舍入数值严格相等：503 available／697 abstain／0 error，最大绝对差异0、状态差异0。

| 角色 | 输入数 | available | abstain | error | 最大绝对差异／状态差异 |
| --- | ---: | ---: | ---: | ---: | --- |
| training | 640 | 285 | 355 | 0 | 0／0 |
| internal_validation | 160 | 63 | 97 | 0 | 0／0 |
| challenge | 400 | 155 | 245 | 0 | 0／0 |

- 实际混合推理入口与旧B入口逐项比较：其余三任务各1200条结果保持一致，三个参数摘要不变，全部4800条独立末次值基线一致。训练／验证／挑战只按原角色使用；验证与挑战没有参与拟合。
- 新包保存12条来源评价与12条三种子汇总；独立复核重新读取保存的JSON参数、核验完整来源及回放，没有重新拟合。封存57个来源文件和源码／运行时身份在构建、复核前后保持一致。
- 旧A/B实际runtime与canonical摘要仍通过；921项范围外文件／删除状态不变，包括既有PDF／页面调整和`docker-compose.test.yml`删除。没有意外新增文件；新文件及文档的尾随空白、`git diff --check`检查通过。

**新制品（C）：** `outputs/numeric-history-integration/2026-09-16-v1`，仅包含`bundle.json`、`manifest.json`、`replay.json`。输出目录已存在，构建器会拒绝再次覆盖；后续只读复核使用`--verify-dir`。制品按仓库既有规则由Git忽略，源码提交不会自动包含这些输出文件。

| 身份 | SHA-256 |
| --- | --- |
| 新bundle canonical | `a6816ed1a30d9a65ae089f67746e98473f0514732883d98a2843d3bc90db2464` |
| manifest原字节 | `866305d783523d8531f9853907c5d1cee252fa35fa1b85d2a042a4b97527fe76` |
| 新推理实现 | `71e1fd0731cde20009c514c9b756bde8c20c4173e9570e4f84c372aefe33dfb0` |
| RF参数 | `488689549b211375bd2228eea09c12b49acdab3c0c9a053e09e0f676963b1351` |
| 训练身份 | `f1be43d5a79170d58ee62a1458ec0d3b17982949f701322ba030facb498a4d34` |
| 训练数据 | `6a30ff026e0dfe2aa42c1a0c67cd1e2bd1ba4c59d462e2b5702307297df23ce9` |
| 训练目标 | `9dd90a418f4f72c9aac9c7efd89b52f5f7f8669fb00ef6804f776334ea88f97d` |

本机命令／退出码／输出记录位于`.tmp/phase4-s2-preflight-result.json`、`.tmp/phase4-s2-build-result.json`、`.tmp/phase4-s2-verify-result.json`；汇总与保全记录为`.tmp/phase4-s2-artifact-result.json`、`.tmp/phase4-s2-preservation-result.json`，独立审查见`.tmp/phase4-s2-review.md`。

**边界：** 以上仅验证合成工程的模型重建、参数导出与回放一致性；`clinical_validity_claim=false`、`clinical_status=not_assessable`、`production_enabled=false`。没有修改活动配置、操作数据库、调用外部LLM、执行API／worker／页面／PDF集成、提交或推送；这些结果不代表报告接入、阶段四总验收或真实临床有效性已通过。

### 3.4 S3完成记录（2026-09-16）

按用户“开始下一步”完成S3：新增严格v3上下文、显式版本分派、受理捕获、prompt v2常量及0031迁移，接入既有受理服务和实际readiness入口；同步ORM与相关测试。额外只调整旧v2数据库集成fixture的runtime替身，使其虚构模型适配新分派入口的独立校验，未修改生产runtime条件。

**已实现的行为：**

- 空配置继续context v1；bundle v1进入旧context v2；bundle v2进入context v3。未知／损坏、重复JSON键、非字符串版本及超限包失败；首次读取、对应loader/runtime结果和末次有界读取须一致。
- `NumericGenerationContextV3`保存完整`numeric_input`、输入／来源绑定摘要、完整包、组合`algorithm`及恰四项`task_algorithms`、参考候选、LLM与检索设置、prompt全文／摘要及template。四项算法精确绑定对应provider参数；报告结果仍只取本病种两项，S4必须核对保存结果与这些descriptor以及外层snapshot一致。
- 接单预检及最终事务内均完整捕获并比较；保留原角色检查、病例归属、病例／用户／疾病锁、快照版本检查与幂等重放顺序。已有key命中返回原报告，不要求当前配置仍可加载；历史不足不会阻断整份受理。
- 0031与ORM扩展v6并保留旧v5约束；v6与document.v3的完整发布事实使用`IS TRUE`防止NULL穿透。降级在任何DDL之前检查v6报告、v3文档和任意状态v3任务上下文，存在即拒绝。代码迁移链从0030到0031，本轮没有执行数据库迁移。

**实际验证：**

- 实施前旧受理／Alembic测试40项及2项子测试通过；新测试先出现新模块缺失、旧路由未接入、0031缺失及版本／读取变化漏检的预期RED，再完成实现。过程中的无历史fixture状态与UUID字面量错误已修正，未降低生产校验。
- 实现代理最终六文件回归119项及2项子测试通过。主任务另在backend执行以下联合回归：**161 passed、2 subtests passed，0失败、0跳过，10.22秒**。有2条warning，分别来自既有Pydantic配置弃用和旧完整性反例fixture的UUID序列化；未修改无关配置或静默屏蔽警告。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_numeric_report_v3_admission.py tests/test_numeric_report_admission.py tests/test_alembic_contracts.py tests/test_report_generation_service.py tests/test_report_generation_schema.py tests/test_operator_permissions.py tests/test_numeric_report_v2.py tests/test_numeric_report_evidence.py tests/test_numeric_report_publication.py tests/test_report_document_integrity.py -q
```

- 独立任务复审结论为Spec compliant／Approved；没有遗留需要修复的问题。重点复核四任务参数绑定、路由失败关闭、双捕获／权限／幂等、0031 NULL安全和降级检查顺序。
- 对实际C模型包保留真实runtime校验，使用已封存source B的AD有历史、AD无历史、脂肪肝三种输入捕获并严格JSON往返v3上下文，再核对组合算法与纯推理身份一致。三个输入run均不同于训练run；AD无历史时6月available、12月abstain/history_not_observed，其他正常任务available。参考查询使用内存空目录、来源绑定使用显式fixture摘要，因此这是模型与输入／上下文兼容检查，不是真实数据库或RAG验收。
- A、B、C实际包canonical摘要和runtime再次通过，封存历史manifest不变；923项范围外文件／删除状态保全，包括S1/S2源码与制品、旧prompt、既有PDF／页面工作及docker-compose删除。无意外新增文件，Python语法及尾随空白／`git diff --check`检查通过。

**已编写但未执行：** 新隔离integration覆盖两病种真实受理、并发幂等、授权拒绝无残留、病例／上下文漂移回滚、NULL与版本约束、旧v5兼容及保存事实拒绝降级。模块在共享fixture连接／迁移／TRUNCATE前，要求本机PostgreSQL精确`surgery_rag_phase4_test`，拒绝查询参数、fragment及libpq重定向变量；缺配置时明确跳过。当前`TEST_DATABASE_URL`未设置，本轮只检查这些文件语法，没有收集或运行数据库集成用例。真实事务、约束和降级效果统一留S6，不能用上述单测／静态SQL结果替代。

**边界与S4交接：** 本轮没有训练、重建或修改模型包，没有实际数据库连接／迁移、外部LLM调用、活动配置变化、前端／PDF操作、提交或推送。S3仅冻结新prompt常量；S4仍需实现叙述生成与校验、v3 worker、文档／v6发布及历史保存事实核验。S5页面／PDF和S6隔离总验收仍未完成，不能据此启用新报告或宣称临床有效。

本机记录：`.tmp/phase4-s3-implement-report.md`、`.tmp/phase4-s3-review.md`、`.tmp/phase4-s3-regression-result.json`、`.tmp/phase4-s3-actual-context-result.json`、`.tmp/phase4-s3-final-inputs.json`及`.tmp/phase4-s3-preservation-result.json`。

### 3.5 S4完成记录（2026-09-16）

按用户“开始下一步／刚才卡了，继续下一步”完成S4，沿用现有分支和工作区。新增v3报告服务、worker及新旧兼容测试；完善独立说明schema／生成／校验、报告document／publication契约和显式版本分派。`report_generation_service.py`已有通用保存上下文路径，本步无需额外修改。

**已实现的行为：**

- 新`NumericNarrativeV2`与旧叙述独立，保留S3冻结的prompt v2原文；请求仅包含输入、任务descriptor／状态、独立基线和允许引用，不传森林或训练主体。一次受控调用，无自动重试；保存请求与响应模型、原始响应及摘要。拒绝错误方法陈述、正文数字、来源标签、非法引用、不安全内容和与任务状态矛盾的成功断言；正确的否定或部分结果说明有回归覆盖。
- document v3固定输入、完整上下文、候选／基线三态、逐任务算法、参考与说明；canonical正文由程序生成，分别展示候选和末次值基线状态，越界raw值不作为结果展示。v6指纹覆盖快照、上下文、完整预测、正文、证据、文档和sources。
- worker使用受理时保存的模型包，依次执行runtime／上下文校验、纯推理、只读固定参考检索、一次说明生成和完整性验证；仓储仍通过既有事务原子发布。abstain/error审计映射为unavailable并保留reason；当前选择包变化不会替换排队参数，保存参数、prompt、runtime或检索配置漂移失败。
- 新增历史v3/v6分派，保存快照、身份、正文和状态须一致；历史只用保存输入和参数作纯一致性算术，不读取活动包、调用当前检索／LLM／过滤或补写正文。旧v1–v5规则及旧prompt保留。失败／取消／进行中报告保留有效保存上下文并隐藏未发布正文。

**实际验证：**

- 修改前旧报告基线44项通过，有2条既有warning。新功能测试先证明缺失契约、上层历史分派和状态／方法规则的预期失败，再完成实现；无效fixture／配置字段名已修正，不降低生产校验。实现过程及定向RED/GREEN见本机实施报告。
- 主任务在backend执行下列联合回归：**300 passed, 5 warnings in 34.36s**，退出0，0失败、0跳过。5条warning来自既有Pydantic配置弃用、旧反例fixture的UUID序列化、FastAPI旧startup事件两处弃用和Starlette测试客户端的AnyIO别名弃用；未改无关配置或屏蔽warning。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_numeric_report_v3.py tests/test_numeric_report_narrative_v2.py tests/test_numeric_report_v2.py tests/test_numeric_report_narrative.py tests/test_numeric_report_publication.py tests/test_report_document_integrity.py tests/test_numeric_report_v3_admission.py tests/test_numeric_report_admission.py tests/test_numeric_report_evidence.py tests/test_report_generation_service.py tests/test_report_generation_schema.py tests/test_report_generation_audit.py tests/test_report_read_service.py tests/test_report_integrity.py tests/test_report_document_schema.py tests/test_report_worker_process.py tests/test_synthetic_report_execution.py tests/test_synthetic_report_publication.py -q --tb=short
```

- 独立初审发现弃权“已完成预测”和未预测结果“由末次值对照替代”两类说明漏检，已补24项生成／保存响应回归：修复前16失败／8通过，修复后24通过，两个新测试文件85项通过。保存响应重新计算合法摘要后仍须被语义规则拒绝，真实否定与部分成功句保持可用；最终复审Spec compliant／Approved。规则针对明确句式，不宣称对任意自然语言完成语义证明。
- 实际C包保留真实runtime gate，使用严格加载的封存source B，覆盖AD有历史、AD无历史、脂肪肝三场景；依次捕获上下文、纯推理、受控说明响应、构建／解析v6 publication并核验历史。AD无历史时6月available、12月abstain/history_not_observed、两基线available。阻断当前包、预测入口、检索、LLM、过滤并切换当前prompt后，保存完整性仍valid；三份消息通过既有进程协议与8 MiB长度限制。
- 上述说明响应为受控替身，参考查询为空内存目录，来源绑定使用显式fixture摘要，不代表真实数据库、RAG或外部LLM链路。首次兼容检查脚本将schema对象直接交给JSON hash产生TypeError，改为显式JSON序列化后通过；未修改生产逻辑。
- A/B/C包canonical身份与runtime再次通过，封存历史manifest不变；926项范围外文件／删除状态保全。S3 prompt v2常量值、旧prompt与模型源码、既有页面／PDF工作和docker-compose删除均保留。新改Python语法、尾随空白、`git diff --check`通过。

**未执行与交接：** 已编写隔离数据库publication／历史／归属／取消与租约边界测试；模块沿用本机PostgreSQL精确`surgery_rag_phase4_test`的前置防护，拒绝URL选项及libpq重定向。本次仅语法验证，未收集或运行；`TEST_DATABASE_URL`未配置，没有数据库连接、迁移或真实发布。单测中的受控DB／检索／说明替身不替代S6真实事务和完整链路验收。

S5需同步前端生成类型、API联合及详情／进行中分派、页面三态／逐任务算法和独立基线、PDF打印及新renderer；S4通用PDF source DTO可携保存文档，不代表v3 PDF已可渲染。S6继续完成真实数据库、API／worker／RAG／LLM／浏览器／归档及旧版本兼容。没有修改活动配置、启用新模型、训练或改制品、外部调用、UI/PDF改动、提交或推送；继续合成数据，临床有效性仍未验证。

本机记录：`.tmp/phase4-s4-implement-report.md`、`.tmp/phase4-s4-review.md`、`.tmp/phase4-s4-regression-result.json`、`.tmp/phase4-s4-actual-report-result.json`、`.tmp/phase4-s4-final-inputs.json`及`.tmp/phase4-s4-preservation-result.json`。

### 3.6 S5完成记录（2026-09-16）

按用户“开始下一步”完成S5，沿用现有工作区；实施前保存pre-S5原字节。正式`report_document.py`在S4已支持v3，本步保持不变。为新renderer补充`report_pdf_renderer_manifest.py`的实际v3源码依赖，属于本步打印身份范围。

**已实现的行为：**

- schema生成器支持v3所需的固定tuple及判别联合，由脚本生成前端类型；API DTO、完成报告和已验证的进行中／失败／取消上下文均接入v3。进行中状态明确显示“报告正在生成”。
- 页面按6／12月排序，候选与末次值基线分别显示值、状态及原因；历史不足和计算失败不遮蔽可用基线。逐任务显示Ridge／随机森林、输入特征和保存版本，仅展示当前病种。保留两位小数、版本后置、引用转义及既有视觉规范；新增长版本串可在窄屏卡片内换行。
- v3打印先严格解析、核验保存输入／参数对应的预测，并比对保存正文、预测和证据；显示舍入不回写canonical正文或原值。新增v3专用结果表列宽，候选／基线状态独立，参考片段按块分页；旧v2展示与净化保持。
- renderer新增8项v3实际依赖，覆盖严格schema、保存预测核验、RF算术、历史斜率和日期；共28项源码身份。每项新依赖均验证“匹配时可加载，改动临时源码字节后拒绝”。未改旧manifest或重渲染旧原件。
- 新增两病种v3归档集成用例；类级防护先于共享fixture，仅接受明确本机`surgery_rag_phase4_test`，拒绝连接重定向。用独立虚构package创建新病例及visits、一次性绑定来源；实际数据库执行留S6。

**实际验证：**

- 修改前后端打印／类型基线10项、前端v2基线17项通过。新v3测试先呈现分派、行顺序、基线／算法缺失及错误PDF解析的预期失败，再最小实现；tuple／oneOf、renderer漂移也分别经过RED／GREEN。详细过程保存在本机实施记录。
- 后端最终定向回归：**56 passed, 1 warning in 9.92s**，0失败、0跳过。warning为既有Pydantic Settings配置弃用。命令在backend执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_numeric_history_print_presentation.py tests/test_numeric_print_presentation.py tests/test_pdf_generation.py tests/test_longitudinal_pdf_contract.py tests/test_report_document_pdf.py tests/test_synthetic_report_pdf.py tests/test_report_pdf_execution.py ../scripts/tests/test_generate_report_document_types.py -q --tb=short
```

- 前端`npm run test:unit -- NumericReportV3.spec.ts NumericReportV2.spec.ts`：**29通过**；旧详情、文档、synthetic、历史、归档、生成状态及图表的11文件补充回归：**50通过**，合计79项不同用例。`npm run test:contracts`：**30通过、0跳过**；`npm run build`通过。窄屏CSS修复后重新执行定向29项和build通过。保留既有PURE注释、混合导入与chunk大小告警，没有新增依赖或调整构建门槛。
- 独立复审：**Spec compliant／Approved**。初版integration夹具的已有来源重绑被发现并修复，最终使用独立package；2项无库检查实际经过strict loader、visits投影和纯预测，验证AD部分结果／脂肪肝正常结果。新增集成用例仅语法检查，未收集或运行。
- 本地真实Chromium直接挂载生产组件，4份软件夹具及2个仅上下文场景通过；核验实际6／12行、独立基线、两病种算法、长参考／历史和0值。390px下先发现RF版本长串导致页面402px溢出，修复后页面宽度不超viewport，表格仍可单独横滚；控制台／页面错误及失败请求检查通过。该预览没有接入API或数据库。
- 使用实际`generate_pdf`与新manifest生成4份软件夹具PDF，分别2／2／4／2页，共10页PNG逐页检查；未见表格截断、重叠或缺字，长参考标题与正文保持同页，版本后置和显示精度符合保存值。JSON原字节不变。这是本地组件／打印验收，不代替真实worker、归档、下载及权限链路。
- A/B/C canonical身份及runtime再次通过；封存历史manifest不变；929项范围外文件／删除状态保全，包含旧模型与prompt、S1–S4实现、用户既有展示工作及`docker-compose.test.yml`删除。另只读复核5份旧PDF和旧renderer manifest原字节不变。Python语法、生成类型与schema一致性、尾随空白及`git diff --check`通过。
- 验证过程的环境／脚本问题均保留记录：预览脚本最初缺`pypdf`，改用项目已有PyMuPDF后完成；首轮构建遇到测试代码`.at()`不符合既有TypeScript目标，改为兼容索引后通过；单独从backend运行scripts测试的导入路径问题在项目常规联合命令下通过。renderer构建／读取时仍出现既有Playwright退出期pending-task／TargetClosedError诊断，退出码为0，实际PDF生成与检查完成；没有屏蔽诊断。

**新renderer交接：**

```text
REPORT_TEST_RENDERER_MANIFEST=C:/Users/86182/Desktop/Surgery RAG-Agent/outputs/numeric-history-renderers/2026-09-16-v1/328b86684e9c123ee776934b93e453a20ae4c49e4dbeb9929bcb0f53406acb6e/manifest.json
manifest SHA-256=328b86684e9c123ee776934b93e453a20ae4c49e4dbeb9929bcb0f53406acb6e
```

**⚠ 2026-09-20 更新：上面这一版已失效，改用下框。** 原因：当天为满足总领第 6 节第 5 项「规则信号与模型贡献分开」，在 `services/report_document_builder.py` 补入一句阶段投影规则披露；该文件是 renderer 的 **28 项源码依赖之一**，改动即令 09-16 的 manifest 不再匹配工作区（预检报 `frozen_renderer_mismatch`）。已按既有规则重建：

```text
REPORT_TEST_RENDERER_MANIFEST=C:/Users/86182/Desktop/Surgery RAG-Agent/outputs/numeric-history-renderers/2026-09-20-v1/38f18749e2ceed29eb12273c66f2a056e701f01db01b3ada7a5582e433357558/manifest.json
manifest SHA-256=38f18749e2ceed29eb12273c66f2a056e701f01db01b3ada7a5582e433357558
```

**2026-09-20 已按新渲染制品完成复跑**：`outputs/numeric-history-acceptance/2026-09-20-v2` 退出码 0（525.30 秒），renderer 身份 `38f18749…`，5 份报告与全部权限／幂等／版本切换断言一致——当前代码与当前验收记录已一致。`scripts/run_numeric_history_acceptance.py` 的 `RENDERER_SHA` 与 `scripts/tests/test_run_numeric_history_acceptance.py` 中的路径已同步为新的。09-16 的 manifest **原字节保留**——S6 验收（`outputs/numeric-history-acceptance/2026-09-18-v1`–`v4`）记录的是它，属历史事实，未改写。

构建使用本机既有、许可证与字节已核验的Noto CJK／Latin字体，运行时为Windows、项目Python 3.11.4、Playwright 1.62.0、FontTools 4.64.0、Chromium 151.0.7922.34；Node 22.15.0／npm 10.9.2。新目录`outputs/numeric-history-renderers/2026-09-16-v1`按manifest SHA分目录生成；未写入活动配置。该manifest供本机S6使用，不能作为其他操作系统环境的renderer。

**未执行与下一步：** `TEST_DATABASE_URL`仍未配置；没有连接或迁移数据库、运行归档worker、调用外部LLM、启用新模型、提交或推送。新增集成测试的受控说明不等于完整外部链路通过。阶段四实施**5／6，剩1步S6隔离端到端验收与阶段五交接**；继续使用合成数据，真实临床有效性仍未验证。

本机记录：`.tmp/phase4-s5-implement-report.md`、`.tmp/phase4-s5-review.md`、`.tmp/phase4-s5-resource-audit.md`、`.tmp/phase4-s5-browser-qa.md`、`.tmp/phase4-s5-visual/pdf-verification.json`、`.tmp/phase4-s5-visual/browser-verification.json`、`.tmp/phase4-s5-final-inputs.json`、`.tmp/phase4-s5-preservation-result.json`及`.tmp/phase4-s5-old-pdf-check.json`。

### 3.7 S6完成记录（2026-09-18）

按用户“继续完成s6”执行。本轮先核对前次遗留：工作区停在**浏览器失败诊断的 RED 检查点**（3 项新测试失败，实现未写），且集成测试文件在 runner 测试通过之后又被修改，尾部残留 4 行误粘贴的断言。修掉残留行、实现诊断后转为 GREEN。

**两次真实失败与修复（产物全部保留）：**

- v1（`2026-09-18-v1`，退出1、42.42秒、0次LLM）：前端在 `/auth/me` 之后未挂载 OperatorView，受理前点击依赖隐式30秒超时耗尽。当时未留下任何页面证据，这是失败诊断实现的直接动因。
- v2（`2026-09-18-v2`，退出1、123.98秒、1次真实LLM）：报告1已完成，`open_history` 失败。新诊断给出根因：首个 `wait_for_shell` 误把“病例列表 region”当就绪条件，而报告完成后应用停在报告详情面板，该 region 不存在。改为等待**侧边栏导航按钮**（各面板均存在）后，用已完成报告做**零 LLM** 定向复现，确认 `shell_wait=ok`、历史行、`.numeric-report`、结果表 2 行（ALT 6月22.57／基线22.80，12月20.00／基线22.80）、`open_case=ok`、无页面错误。
- v3 退出0、357.44秒、`status=passed`。

**已实现的行为：** 新 runner 默认只读预检（精确本机 `surgery_rag_phase4_test`、拒绝 URL 选项与 libpq 重定向、端口空闲、输出不存在、B/C 包与 renderer 冻结身份、source 清单逐文件摘要），无 `--apply` 不连库／不启动服务／不写入；真实执行另需 `--allow-external-llm`，并在受理前重检身份。失败时保存截图、body 文本、page error 类型、错误位置与**已脱敏 URL**（去凭据／查询／fragment），诊断自身失败只记录阶段与异常类型，异常正文不序列化。

**实际验证：**

- 新 runner 测试：实现诊断后 42 项通过；独立复审的三项加固又新增 9 项，最终 **51 passed**。中途一次单项失败经复现确认为**与在跑的验收争用 18060／15173 端口**，验收结束后重跑全部通过，不是回归。
- 真实 apply 最终轮 `2026-09-18-v4` 退出0（296.84秒）：5 份报告（B脂肪肝／B AD／C AD／C脂肪肝／C AD无历史，报告8–12）全部完成，5 次真实说明生成；`audited_invocations=5`，每份报告 `report_narrative` 恰好 1 次 `invocation_started` 与 1 次 `task_finished`。5 份 `archive/reports/<id>/<uuid>/document.pdf` 与下载字节 SHA-256 逐一相等。`queued_v2_completed_with_c_selected=true`；取消报告13未调用 worker／LLM；5 份报告均验证非所有者 404、doctor 403、幂等重放；恢复 B 与不存在当前包两阶段保存事实与 PDF 原字节不变；`page_errors=[]`。先行一轮 `v3` 在同一链路同样通过（退出0、357.44秒），记录以复审后的 `v4` 为准。
- **独立复审**（只读，覆盖 runner、浏览器驱动与测试）：无阻断项，确认未削弱任何断言——新 runner 相对旧 runner 只增不删，旧 runner 与旧浏览器驱动源码未改动。采纳三项加固：`browser.close()` 异常不再顶替原始失败、`safe_page_url()` 解析失败分支同样剥离 userinfo 并正确处理 IPv6／端口0、补 9 项回归（就绪定位器、URL 脱敏、teardown 不顶替失败）。另记录两项非阻断事实：`validate_prediction` 未在真实链路重算末次值独立性；`body_text` 是诊断中唯一未结构化过滤的通道（已确认当前页面不渲染令牌或原始异常文本）。
- 前端 `npm run test:unit` 23文件／168项、`npm run test:contracts` 30项、`npm run build` 均通过。
- 后端非 integration／e2e 回归：首次整仓运行 5 failed／2278 passed／59 skipped。其中 3 项为本文件测试依赖 Playwright 时受 `backend/tests/test_pdf_generation.py` 向 `sys.modules` 安装 mock 后再 `pop`、令 `playwright` 包半导入影响（`module 'playwright' has no attribute '_impl'`，单文件运行不复现），已改为测试内先丢弃整个 `playwright.*` 层级再重新导入，并在模拟污染下验证（52 项通过）；修复后整仓复跑为 **2 failed／2290 passed／59 skipped／24 subtests passed（1137.68 秒）**。剩余 2 项为可追溯到阶段二／三提交的既有失败（`tests/test_schema_contracts.py` 的 `operator_cases.engineering_source` 未同步进 `database/schema.sql`；`tests/test_cleanup_contracts.py` 的 specs 允许清单未登记阶段一至四设计文档），工作区未修改这两个失败涉及的 SQL／清单文件，非 S6 引入。
- 冻结输入来源 `3b333b09…`、B `32b8069f…`、C `a6816ed1…`、renderer `328b8668…` 在实施前后一致；活动配置未改变，C 包只在验收进程内临时选择。

**边界：** ~~仍未演练“0030 中已有 v5 行、再 upgrade 到 0031 后原行不变”~~ **2026-09-20 已补做该演练并通过**：从验收库取出真实 v5 发布行（2 份报告 + 其 v2 上下文任务 + 关联用户／疾病／病例，共 5 张表 9 行）导入停在 0030 的一次性库，升到 head 后**逐字段比对，5 张表完全一致**；v5 版本值保留、`ck_ai_reports_numeric_history_publication` 如期出现、`ck_ai_reports_fingerprint_version` 现允许 v1–v6。脚本 `.tmp/run-e5-migration-drill.py`。原较弱表述（fresh 升级 + 升级后 v5 兼容 + 真实 downgrade 拒绝）仍然成立且已一并保留。计算 error／有限越界、损坏／缺 task／未知算法、检索双失败／LLM 失败等场景按其真实层级记录为纯函数／stub worker／PG 事务，未在真实外部链路注入。全部结论限于合成数据，`clinical_validity_claim=false`；真实资料仍须独立审核、适配、重新训练评价与版本绑定。

本机记录：`.tmp/phase4-s6-*`、`.tmp/diagnose-phase4-s6-*.py`；结果汇总见[阶段四实施与总验收记录](../notes/2026-09-16-numeric-history-integration-result.md)。

## 4. 下一步与剩余

**已完成：阶段四设计、实施计划及S1–S6；本阶段实施6／6，合成工程结束。**

**阶段四已交付：** 严格混合包与纯推理、固定RF制品与逐值回放、v3受理与0031迁移、v3执行／说明／v6发布与历史核验、页面／类型／打印与新renderer，以及真实 API／worker／RAG／LLM／归档的隔离总验收。

**交接两项保留（不阻塞合成工程）：**

1. **后端 2 项既有失败**：`database/schema.sql` 未同步 ORM 的 `operator_cases.engineering_source`（提交 `2650d27` 引入），以及 `tests/test_cleanup_contracts.py` 的 specs 允许清单未登记阶段一至四设计文档。二者属阶段二／三范围，需单独决定是否补齐后重跑后端回归。
2. ~~**迁移保全未单独演练**：如需声称“既有 v5 行跨 0031 upgrade 原样保留”，须在专用库上做一次 0030→0031 往返用例。~~ **已关闭（2026-09-20）**：往返用例已完成且通过，现可作「既有 v5 行跨 0031 upgrade 原样保留」的声明，详见上文 §3.7 边界段。

**真实资料开放项：** 仍无真实数据。真实资料到位后须独立审核、同契约映射、重新训练与评价、版本绑定并重新验收，不因本轮合成总验收通过而改勾。真实资料冻结与临床评价的开放条目仍按总领文档原口径保留。
