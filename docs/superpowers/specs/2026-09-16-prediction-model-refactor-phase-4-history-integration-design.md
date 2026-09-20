# 预测模型重构阶段四：合成历史候选的契约与报告接入设计

日期：2026-09-16。版本：0.6。状态：**S1–S5已完成本步验证；实施5／6，剩1步，下一步S6隔离总验收与交接。页面／打印及新renderer已完成，真实数据库／完整链路待S6。**

依据：[总领文档](2026-09-09-prediction-model-refactor-master-design.md)、[阶段三结果与交接](../plans/2026-09-15-prediction-model-refactor-phase-3-offline-comparison.md#12-t6结果解释与阶段交接2026-09-16)、[阶段四实施计划](../plans/2026-09-16-prediction-model-refactor-phase-4-history-integration.md)。阶段三已提交为`bc3cd39`，合成工程6／6完成；用户暂无真实数据，继续合成先行，不回退阶段二、三状态。

## 1. 目标、方案与范围

**建议首版只把AD 12个月的RF历史数值候选接入工程流程，其他三任务继承已验收Ridge参数，所有任务保留末次值对照。** 本阶段验证模型制品、版本、推理、报告与归档是否正确衔接，不补设临床门槛、不宣称真实患者有效。

| 方案 | 取舍 | 决定 |
| --- | --- | --- |
| 完整四任务，逐任务固定算法 | 复用现有每病种6／12月报告，不引入任意能力组合；需要新版本表达混合算法和独立状态 | 推荐采用 |
| 只声明AD 12月能力，其他任务缺省 | 需新增能力集合、报告缺任务语义及更多路由；本期没有必要 | 留给实际需要部分任务的后续版本 |
| 同时接入AD及ALT 12月历史模型 | ALT 12月RF点估计改善，但三个配对区间中两个跨零，节奏增量也不稳定 | 本期不接入，完整结果继续保留 |

AD 12月RF `value_history`相对末次值在三个种子点估计和配对区间均正向，是工程候选选择依据；不是发布或临床准入证明。AD 6月及ALT 6月不支持统一替换，ALT 12月仍有较大不确定性。继承Ridge是保留既有能力，不表示这些任务已经优于末次值。

首版固定任务表：

| task_id | 算法／特征 | 参数来源 | 缺历史时 |
| --- | --- | --- | --- |
| `ad.mmse.6m` | `ridge:main_anchor`／锚点值 | 基包B原参数 | 按原输入可用性计算 |
| `ad.mmse.12m` | `random_forest:history_v1:value_history`／锚点值、最近历史值、历史斜率 | 阶段三首个预定种子20260914的该模型 | 明确弃权，不回填基线 |
| `fatty_liver.alt.6m` | `ridge:main_anchor`／锚点值 | 基包B原参数 | 按原输入可用性计算 |
| `fatty_liver.alt.12m` | `ridge:main_anchor`／锚点值 | 基包B原参数 | 按原输入可用性计算 |

保留现有AI操作者入口、权限、幂等、持久任务、取消／超时／租约、RAG及说明生成、历史和PDF原件。没有新的用户模型选择按钮，也不扩展病种、时距、临床风险分层、真实资料导入、调参或自动重训。

## 2. 已核实事实与冻结的工程选择

规划时只读核对了当前源码、阶段三结果和既有制品：

- `numeric_model_bundle.v1`只允许完整四任务、单特征Ridge及旧评价形状；`numeric_prediction.v2`还要求候选和基线的status/reason一致，不能表达历史候选弃权但基线成功。
- 当前训练报告使用context v2、document v2、fingerprint v5；LLM提示词和生成时校验写明只使用Ridge，不能原地放宽后用于新算法。
- 旧模型的runtime检查绑定整份推理、schema及若干训练来源文件；阶段三协议也绑定历史特征／训练文件。直接编辑这些文件会影响旧制品核验和在途任务。
- 阶段三RF记录没有完整树参数，不能直接加载为线上模型。需要定向重建唯一选定RF并导出新JSON制品；不必重做120次拟合或bootstrap。
- 旧包A、B本次只读加载及runtime核验均通过。配置文件未发现`NUMERIC_MODEL_BUNDLE`赋值，不能据此断言当前运行进程选中了哪一包。

以下是**本阶段隔离工程的固定选择**，不改变活动配置：

| 身份 | 冻结值 |
| --- | --- |
| 继承基包B | `outputs/numeric-acceptance/2026-09-15/model-v2/bundle.json` |
| B canonical bundle SHA-256 | `32b8069f92dab3e104f3668c3639cdc6e5461f5bedf61a4f7590ce2cef478215` |
| 旧包A（兼容回归） | `outputs/numeric-fullflow/2026-09-14/model-v1/bundle.json`；canonical SHA-256 `1de39003420d8a61fe6436d6e0062ad9f921ceb0ef23ed9b9c3f26b9aacb33bc` |
| 历史证据包 | `outputs/synthetic-prediction-history/2026-09-15-v1`，run `hist-fa171097693d166e` |
| 历史manifest原字节SHA-256 | `59a01c52f762d902cbd2a2b6faada56acc80c8b25d27d9ce40b92e7429c0e918` |
| 历史数据摘要 | `8dd120326c41885217e9bac419b38168ba0435ada661779bbfcc14055f33e682` |
| 选择协议 | `numeric_history_selection.v1`：预定seed列表第一项20260914；仅AD 12月RF value_history |
| RF随机状态 | 20260914；与来源seed为不同概念，不能按挑战分数挑选 |
| 新制品目录 | `outputs/numeric-history-integration/2026-09-16-v1`；目录存在即拒绝覆盖 |

上述输出均为本地封存文件，不随代码提交。先验证身份再执行；文件缺失或身份不同则报告缺少条件，不自动切换到其他包。基包B来自另一个120人规模实验，不能用阶段三1200人锚点模型替代它，也不能把不同来源的误差放在一起排名。

## 3. 新版本与模块边界

| 契约 | 保留版本 | 新版本与用途 |
| --- | --- | --- |
| 来源与输入 | `numeric_input.v1`、`numeric_report_input.v1` | 不升版，不增加结局或未来字段 |
| 模型包 | `numeric_model_bundle.v1` | `numeric_model_bundle.v2`，固定四任务混合包 |
| 结果 | `numeric_prediction.v1/v2` | `numeric_prediction.v3`，逐任务算法、独立候选／基线状态 |
| 固定上下文 | `numeric_generation_context.v1/v2` | `numeric_generation_context.v3` |
| 报告 | `numeric_report_document.v1/v2`及既有其他报告 | `numeric_report_document.v3`、`numeric_report.zh-CN.v3` |
| 说明 | `numeric_narrative.prompt.v1`及原叙述schema | `numeric_narrative.prompt.v2`、独立`NumericNarrativeV2`类型 |
| 发布指纹 | v1–v5 | v6；旧分支的计算规则不变 |
| 证据 | `NumericReferenceContext`、`NumericRagEvidence` | 复用原schema及权限过滤 |

新增`numeric_history_*`和`numeric_report_v3*`模块承载新行为；旧`numeric_model_bundle.py`的schema／service、`numeric_prediction.py`、`synthetic_numeric_prediction.py`、阶段三特征／训练／评价及旧说明提示词保持原字节。需要修改的是上层明确的版本分派、数据库约束、报告解析和展示入口。不能通过改旧manifest、豁免旧runtime检查或把旧参数套新算法ID实现兼容。

### 3.1 混合包：保留原始基包，明确四项路由

`NumericHistoryBundle`为严格JSON对象，包含：

- `schema_version=numeric_model_bundle.v2`、固定`selection_version`、`input_schema_version=numeric_input.v1`、`implementation_sha256`、`clinical_validity_claim=false`、`production_enabled=false`。
- `legacy_bundle: NumericModelBundle`：嵌入B的完整原内容，`legacy_bundle_sha256`使用旧canonical规则；不重新拟合或重写旧系数、source及evaluation。保留第四项旧AD 12模型仅作原包身份组成，不会被新路由执行。
- `history_model: NumericHistoryRfModel`：只允许AD 12月RF value_history，保存严格三维标准化、训练身份、参数、树和`parameters_sha256`。
- `task_assignments`恰含四个task，各provider固定为第1节规定的`legacy_ridge`或`history_rf`。缺项、重复、未知任务或错误映射均拒绝；本期不存在“未提供任务”正常状态。
- `history_evidence: NumericHistoryEvidence`：绑定完整历史包、协议和选定模型；保存选定seed三角色×两scope×两个比较（V对末次值、V对H锚点）的12条严格评价记录及对应12条三种子汇总。记录单位、分母、失败／越界、指标、方向和适用配对区间；完整负结果仍在原证据包。结构使用闭合字段schema，拒绝未知字段和任意dict透传；临床状态固定`not_assessable`。

包摘要对完整语义内容计算；有序树／特征不能排序，四任务路由按task_id规范化。各任务的训练与挑战身份按**该任务的来源版本**核验；不同合成批次的局部subject_id不能直接合并成一个全局分区。继承的三任务绑定B原评价，RF绑定历史评价，不能用RF成绩覆盖其他任务的说明。

新包仅用于合成工程，受理时要求输入`source_kind=synthetic`；旧版本仍沿用旧来源行为。来源适配与新模型能力是分开的：输入包身份必须真实可追溯，但不要求当前病例的来源run等于模型训练run。以后真实模型按新来源和评价另行接入，不篡改这一包的声明。

### 3.2 历史投影与资格

新`project_numeric_history_features(packet: NumericInputPacket) -> HistoryFeatureResult`直接接受严格验证的数值输入；不把real来源改成synthetic，也不构造SyntheticPatient。

H资格依次要求：锚点输入可用、历史覆盖complete、状态observed、至少一条严格早于锚点的同指标／单位／方法记录、跨度大于0。记录必须在锚点时已知；日期冲突、非法单位、未来信息仍由输入schema拒绝。最近历史值取最后一条，斜率使用全部历史及锚点与实际日差，通过旧`_ols_slope`纯函数计算。

`HistoryFeatureResult`保存`eligible: bool`、`status=available|abstain|error`、`reason`、`anchor_value/prior_value/slope_per_day/n_pre/span_pre_days`。资格与计算成功分开：已满足H但OLS溢出仍为`eligible=true,status=error`，不能从H分母删掉。

旧投影没有可单独复用的H gate。新入口保持同样的判定顺序，通过所选seed全部4800个输入任务的资格、原因和原始特征逐项等价检查，以及边界单测锁定语义；不声称已经共用同一个资格函数。当前封存输入没有锚点不可用记录；该额外边界中，旧离线概括原因`anchor_not_available`显式映射为在线packet保存的具体输入原因，并逐项单测，不宣称所有输入的原因字符串都原样相同。仅验证输入适配，不使用标签判断资格。

### 3.3 RF导出与推理

RF固定200棵树、max_depth=4、min_samples_leaf=3、bootstrap=true、random_state=20260914、n_jobs=1，其他参数完整沿用阶段三封存配置。只拟合所选seed、AD 12月、training角色、有标签且H合格的原有训练行，按sample_id排序。均值、std（ddof=0）、常量scale=1与三列顺序保持一致。

树采用严格叶／分支联合类型：叶保存有限double值；分支保存整数feature_index（0–2）、double阈值、left/right整数索引。根为0，所有节点恰好可达一次，无环、孤儿、多父或非法索引；树深不超过4，节点最多31。允许单叶树、同一特征重复分裂、相同阈值及未使用某特征；不强制正好31节点。拒绝bool索引、额外字段、重复JSON键、NaN/Inf和未知版本。新bundle文件上限8 MiB、森林恰有200棵树；禁止任意路径、pickle或joblib加载。

纯推理顺序必须与冻结sklearn实现一致：

1. 原值以double使用保存mean/scale标准化。
2. 标准化结果转换IEEE binary32；溢出为任务计算错误。不能提前转换原值，也不能把阈值转float32。
3. 用float32特征与double阈值比较，`<=`走左分支。
4. 按保存的树顺序以double累加叶值，再除以200；不改用`math.fsum`或先舍入。

导出后，对AD 12月全部1200个输入（训练640／验证160／挑战400）的预测逐值、状态和原因回放，要求与封存输出严格一致；正常值共503、弃权697，挑战标签不参与拟合。只有汇总MAE相同不算通过；若出现差异先定位，不自动放宽容差。其余三任务的参数和推理逐值保持B语义。

构建器只写新目录，输出`bundle.json`、`manifest.json`、`replay.json`。记录来源文件原字节／canonical身份、选择规则、运行时、实现摘要、训练身份及各角色回放分母；构建前后核验输入未变。失败不留下可被误用的完成状态。复算入口重新校验参数及回放；默认预检不拟合，显式构建才允许这一次固定合成重建，不重新计算bootstrap。

## 4. 输出、错误与解释

`NumericPredictionV3`保留病种、主体、锚点、来源和输入摘要，顶层使用`numeric.mixed_history.v1`组合身份及bundle摘要；每条候选保存精确task算法描述、特征／资格版本和参数摘要。基线逐项保存`numeric.last_value.v1`身份。两列表均恰有该病种6／12月两项，只要求task、单位、目标日期等身份对应，不要求状态一致。

| 情况 | task status／值 | 报告行为 |
| --- | --- | --- |
| 输入及计算可用 | `available`、有限且合法范围value、reason=null | 显示预测值 |
| 锚点或适用输入不足 | `abstain`、value=null、沿用输入原因 | 显示原因；对应基线按自身输入判定 |
| RF历史不足 | `abstain`、value=null、明确历史原因 | 历史模型未执行；另一时距和基线独立显示 |
| OLS／标准化／推理计算失败 | `error`、value=null、闭合错误码 | 可生成说明不可用的完整报告，不宣称该任务预测成功 |
| 有限结果越界 | `error/prediction_out_of_bounds`、value=null、`raw_prediction`保存原有限值 | 原值仅供后台审计，不作为有效预测展示；不裁剪或回填 |
| 模型缺失、损坏、摘要不符、未知算法或不完整四任务包 | 整个受理／执行硬失败 | 不当作普通弃权，不发布报告 |
| 参考两分支均失败、LLM失败或内容校验失败 | 整个任务失败 | 保留现有规则，不使用模板冒充成功 |

reason闭合集：现有四个输入原因；`history_coverage_incomplete`、`history_not_observed`、`comparable_history_required`；`history_calculation_error`、`standardization_error`、`prediction_calculation_error`、`nonfinite_prediction`、`prediction_out_of_bounds`。`raw_prediction`只允许在有限越界error中出现，其他状态必须为空。离线`valid`显式映射为在线`available`；不修改旧在线`available/unavailable`契约。

不新增外层报告状态或SSE事件。既有审计事件只允许available/unavailable等：v3的abstain和error都发`result_state=unavailable`并保留具体reason_code；已保存v3结果保留完整三态，UI据此区分“历史不足，未预测”和“计算失败”。报告completed只表示报告已保存，不能推断全部任务预测可用。

### 4.1 RAG与LLM

沿用固定参考、病种／访问范围／当前版本过滤、同主体和依赖组排除，以及原检索失败语义。LLM请求只传输入、实际任务状态、冻结算法描述、候选／基线、允许引用；不传整棵森林、训练患者身份或任意来源配置。

新`numeric_narrative.prompt.v2`只要求“结果阅读说明、参考证据说明”两段及限制；明确不同任务可能没有有效预测，不能将报告完成说成全部预测成功。算法／特征及执行状态的完整说明由程序按冻结descriptor和三态渲染，LLM不生成算法方法说明。新validator继续禁止正文数字、来源标签、非法引用和不安全医疗内容，并拒绝Ridge、RandomForest、RF、岭回归、线性回归、随机森林、历史斜率、外推等方法陈述。历史不足的具体原因由确定性表格保证披露，不依靠自由文本推断算法是否执行；叙述中发现与固定状态矛盾的成功断言时拒绝。保留请求和实际响应模型名，不增加自动重试。

旧prompt v1及其validator保持原字节和原规则。新schema独立接纳prompt v2，不能让旧NumericNarrative类型悄然接受新语义。

## 5. 受理、在途任务、持久化与历史

同一个`NUMERIC_MODEL_BUNDLE`配置入口按严格schema版本路由：空值保留原baseline路径，v1进入旧trained v2，v2进入新trained v3。未知／损坏包直接失败。接单预检和最终事务内重新捕获完整上下文并比较，检测版本变化；幂等命中仍返回原报告。

v3上下文固定完整新bundle、完整`numeric_input`及输入／来源绑定摘要、组合`algorithm`及恰四项`task_algorithms`、参考候选、检索设置、prompt全文／摘要／版本、LLM名称和模板版本。四项descriptor严格绑定对应provider参数；结果仍只含本病种两项，S4需核对其descriptor及外层snapshot与保存上下文一致。worker从保存的上下文执行，不重新选择当前包。

- **当前配置换成另一合法包：** 已排队任务仍使用保存版本，旧v2不随新配置变成v3。
- **已保存参数被篡改、运行时代码不兼容、对应prompt或检索设置变化：** 完整性失败，不静默换版本。
- 旧v2受理、worker、prompt、历史核验继续可用；新模块不得使原A/B runtime gate失效。新包runtime摘要覆盖其固定推理／schema依赖及旧包实现身份，报告／UI改动由上下文／模板／renderer身份分别管理。

已新增迁移`0031_numeric_history_publication.py`（实施前静态head确认0030，当前代码head为0031；尚未执行数据库迁移），不新增业务列：扩展fingerprint及engineering evidence允许值至v6，新增v6必须对应document.v3、numeric_prediction、completed及完整snapshot/evidence/document/hash的约束，原v5约束保持。`backend/app/db/models.py`同步。downgrade发现任一v6报告、v3文档或v3任务上下文即拒绝，包含已取消／失败任务，不删除事实。

新v6指纹固定输入快照、context、完整prediction、canonical正文、证据、document和sources。历史读取只使用保存事实及保存版本的纯一致性核验；可以验证保存参数与保存值一致，不能加载当前活动包、重新检索／调用LLM、生成替代预测、补写历史正文或重渲染归档。

## 6. 页面与PDF

不新建页面、路由或选择器。复用`NumericReportView.vue`和`report_pdf.html`：

- v3结果表增加逐任务算法说明；候选按自身三态显示，基线按自身状态显示，不能因候选弃权而隐藏基线。
- 原末尾“模型与生成版本”区域逐任务列出保存的算法与输入特征，取消对v3的全局Ridge假设；旧文档保留旧文义。
- 两位小数只用于展示；保存值、canonical正文与指纹按各自版本规则处理，不把显示舍入写回数值。历史实测精度不变，保留参考片段及分页。
- 不展示后台source绑定、训练身份或越界审计原值；继续明确没有临床有效性结论。
- 修改前完整读取[UI规范](../../DESIGN_SPEC.md)，沿用现有变量、暖杏蓝、表格及可访问性；检查加载、空、部分结果、错误、引用和长表打印。

前端类型仍从`backend/app/schemas/report_document.py`的正式解析入口及schema生成，经`generate_report_document_types.py`更新`frontend/src/types/report-document.ts`；同步operator API、详情／进行中上下文类型，禁止只改组件或手改生成结果。

新增v3打印分支后构建新renderer manifest，API和PDF worker使用一致制品。新PDF在保存事实完整性通过后生成；旧归档重复下载必须保持原字节，缺失／损坏走现有恢复规则。

## 7. 验收与授权边界

阶段四分六步，详见实施计划：S1严格契约与纯推理；S2固定制品构建及回放；S3受理与数据库兼容；S4报告worker及说明；S5页面／PDF；S6隔离总验收与交接。

普通测试使用项目Python3.11.4、Node22.15.0、npm10.9.2和现有依赖，不调用外部LLM、不访问业务库、不下载模型。真实数据库集成不能用mock结果代替，但mock可验证失败分支的业务行为。

S1源码核验补充：复用的旧日期／OLS模块经`synthetic_prediction_cases`在冷启动时导入现有NumPy。新纯推理本身不调用NumPy或sklearn计算、不训练、无文件／网络访问；保留旧源码摘要约束，因此不改旧模块或复制OLS以消除该启动依赖。旧回归中的小型合成夹具拟合属于单元测试，不等同于S2固定模型重建或阶段三实验重跑。

实际集成使用新建、可丢弃的本机`surgery_rag_phase4_test`，显式`TEST_DATABASE_URL`；现有integration fixture会迁移并TRUNCATE，因此**不能指向已有本机演示库或业务库**。迁移编写不等于执行；实际执行该隔离验收需明确对应范围。缺少隔离库、renderer、已有BGE资源或外部LLM运行条件时记录未执行，不回退其他库、不自动下载。

总验收使用一份固定合成病例来源，分别让旧B和新C生成报告；不套用旧验收器“训练run必须等于输入run、两个输入来源必须不同”的专项假设。新入口默认只读预检，实际运行需要`--apply --allow-external-llm`；同一病例可以用于工程版本对照，不将这些报告当新的独立效果评价。

必须覆盖：两病种正常报告；AD历史不足；计算／越界错误；损坏／不完整包；LLM和引用失败；输入与上下文篡改；排队期间切配置仍用原参数；prompt／runtime漂移失败；幂等与取消／超时回归；非所有者详情／下载404、错误角色403及病种权限；真实worker与PDF归档；旧v5历史／原PDF不变；v6迁移和降级保护。计算错误等故障注入只存在测试夹具，不提供生产故障开关。

验收报告区分单测、隔离集成、实际LLM／PDF链路及未执行项。本阶段不会把新包写入真实运行配置、迁移业务库、切换活动版本或发布；阶段五再明确目标环境、发布和回退。

## 8. 当前交付与下一步

规划时只读确认旧A/B制品身份及runtime通过，检查现有契约与兼容限制。随后S1新增严格模型／结果schema、历史投影与纯推理及对应测试；新旧联合回归168项通过，复审发现的证据自洽与导入绑定问题已修复并通过复核。旧A/B实际runtime仍通过，914项范围外文件／删除状态保持，包括既有PDF／页面展示工作及`docker-compose.test.yml`删除。详细命令、失败修复和依赖限制见实施计划第3.2节。

S2新增单模型构建、预检和只读复核工具及46项测试，联合回归197项通过，独立复审Approved。实际用200条原训练记录重建唯一RF并导出200棵树；4800条投影无差异，RF的1200条预测严格相等（503 available／697 abstain／0 error），三个继承任务及全部基线与旧B一致。新包位于`outputs/numeric-history-integration/2026-09-16-v1`，canonical SHA为`a6816ed1a30d9a65ae089f67746e98473f0514732883d98a2843d3bc90db2464`。正式预检、构建、独立只读复核均退出0；旧A/B runtime及921项范围外文件保全通过。制品身份和实际命令见实施计划第3.3节。

S3完成v3固定上下文、严格版本分派、实际受理／readiness接入及0031／ORM兼容约束；旧权限、锁与幂等顺序保留。联合回归161项及2项子测试通过，独立复审Approved；实际C与三种封存合成输入的离线上下文检查通过，A/B/C runtime及923项范围外文件保全通过。真实数据库测试已编写但未执行，专用库尚未配置；静态约束和内存参考目录不代替S6验收。详细记录见实施计划第3.4节。

S4完成独立说明生成／校验、v3 worker、确定性正文、v6发布逻辑与保存历史核验；联合回归300项通过，独立复审Approved。实际C与三种封存输入的离线报告兼容检查通过，说明／参考使用受控替身，不是真实DB/RAG/LLM链路。A/B/C runtime与926项范围外文件保全通过；隔离数据库测试已编写但未执行。详细记录见实施计划第3.5节。

S5完成v3生成类型、页面三态／独立基线／逐任务算法及PDF打印；后端56项、前端79项不同用例、契约30项和构建通过，独立复审Approved。本地4份软件夹具／2个上下文页面及4份共10页PDF检查通过，390px算法版本溢出已修复。新renderer冻结28项源码，manifest SHA为`328b86684e9c123ee776934b93e453a20ae4c49e4dbeb9929bcb0f53406acb6e`（**2026-09-20 该 renderer 已作废**：因 `services/report_document_builder.py` 补入阶段投影规则披露句——它是 renderer 的 28 项源码依赖之一——已按既有规则重建为 `38f18749e2ceed29eb12273c66f2a056e701f01db01b3ada7a5582e433357558`，见[阶段四计划](../plans/2026-09-16-prediction-model-refactor-phase-4-history-integration.md)第 3.6 节。此处保留 S5 当时的值。）；5份旧PDF与旧manifest字节不变，929项范围外文件保全。实际数据库／归档集成只编写未执行，详情及manifest绝对路径见实施计划第3.6节。

**S1–S5已完成本步验证；实施5／6，剩1步S6。下一步：隔离端到端验收与阶段五交接。** 本轮未改变活动配置、连接或迁移数据库、实际归档发布、外部LLM调用、提交或推送；继续合成数据，真实临床有效性仍未验证。
