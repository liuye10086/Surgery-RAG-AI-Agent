# 手动验收前检查与启动指南

更新时间：2026-09-08。本文已合并同日环境准备结果；配套[全项目功能与手动测试清单](MANUAL_TEST_CHECKLIST.md)和[验收及修复结果](MANUAL_TEST_RESULTS_2026-09-08.md)。本机依赖和基础模型/PDF资源已准备并验证，以下命令用于换环境或缺少资源时恢复，不要求每次启动重新安装。表中状态是带日期的验证记录，不代表服务此刻正在运行。

## 1. 当前实际状态与需要处理的事项

| 检查项 | 本机结果 | 启动前如何处理 |
| --- | --- | --- |
| 分支 | main，包含本轮尚未提交的验收修复 | 保留当前工作区改动 |
| 数据库版本 | 实际 `0026`，代码 head 也是 `0026` | **当前不需要迁移**，P1/P2/P3 修复没有新增 migration |
| 数据库扩展 | vector 0.8.3、uuid-ossp 1.1、pg_trgm 1.6 | 已具备 |
| 报告/PDF 结构 | 任务、审计、PDF 原件/尝试/交付、清理及删除事实表存在，报告文档列存在 | 不要因旧检查器误报重建数据库 |
| Node/npm | 22.15.0 / 10.9.2 | 已匹配项目基线 |
| 后端项目虚拟环境 | 已建立`backend/.venv`，Python 3.11.4，依赖检查通过 | API与所有worker继续使用此环境，无需重建 |
| OCR | PaddleOCR 3.7.0、PaddlePaddle 3.3.0及模型缓存已具备，合成图片识别通过 | 换电脑时需同时安装包和准备模型缓存 |
| BGE | 复用现有BGE-M3权重，离线加载及1024维归一化编码通过 | 新环境仍需准备完整权重；启动时等待预热完成 |
| DeepSeek/JWT | 已配置；同日真实问答及登录已验收 | 后续网络、额度和凭据状态需按实际情况检查 |
| 报告生成 | 同日已开启开关，独立worker完成报告生成 | 使用时仍需启动报告worker |
| 历史游标签名 | 已补充独立持久密钥，历史读取已验收 | 保留现有配置，不在每次启动时重新生成 |
| PDF | Chromium、字体、私有目录及renderer已配置，真实归档与下载通过 | 使用时仍需启动PDF worker；新环境按第6节重建renderer |
| 账户 | admin、user、ai_operator 各 1 个 | 已有三种身份；跨用户隔离测试另准备操作者 B，不在文档记录密码 |
| 知识库 | 9 个 indexed 文档，源文件均存在 | 可作为问答基础；还需验证向量查询和访问范围 |
| 正式标准 | 两病种各有批准版本，源文件哈希和规则来源绑定检查通过 | 不需为了启动重新上传/解析；AD 为 evidence-only，属既定语义 |
| 模型 | 脂肪肝 10/10、AD 7/7 制品可用 | 不必为启动重新训练；实际生成时继续校验模型输入 |
| 参考数据 | 存在兼容模式参考记录，但无活动数据 release；参考窗口 0 条 | 要测“相似参考病例”成功路径，先核实并显式发布数据版本，再建窗口 |
| 上传目录 | 已存在 | API 从 backend 工作目录启动，注意相对 UPLOAD_DIR 的解析 |
| tracing | LangSmith 关闭 | 本机验收可保持关闭 |

本机基础前后端、报告生成、历史和PDF链路已完成同日验收，保留两份报告；正向相似病例仍缺活动数据release和合格参考窗口。模型就绪检查的available不能替代运行开关、密钥、目录及worker检查。

### 已确认的旧检查器/文档误报

- `scripts/check_operator_report_generation_readonly.py` 把 schema_ready 写成 `head == "0024"`，所以实际 0026 也会显示 false。其 preflight 的 PASS 只代表该阶段检查，不代表可开放全部报告功能。
- `scripts/check_database_readonly.py` 仍要求旧约束 `ck_operator_idempotency_keys_scope`、`ck_operator_idempotency_keys_resource_type`；0024 已正式合并为 `ck_operator_idempotency_keys_scope_resource`。本机新约束实际存在。
- `database/README.md` 和部分报告发布章节有历史“当前 head 0021/0024”表述，当前应以 Alembic 代码 head `0026` 为准。
- 数据库检查的 `active_releases_match=false` 则是真实的数据发布缺项；两病种 `build_reference_case_windows.py` dry-run 均返回 `active_release_missing`，不能把这项也当误报。

本次仅记录这些检查器维护问题，没有扩大任务去修改其代码。不要通过 stamp、downgrade、导入 schema.sql 或重复建库消除误报。

## 2. 数据库到底要不要更新

对当前已检查的本机库：**不用，0026 已到最新。** 下列是你换环境/换数据库后可重复做的只读确认。

在项目根目录的 PowerShell：

```powershell
Set-Location 'C:\Users\86182\Desktop\Surgery RAG-Agent\backend'
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic heads
```

二者应为 `0026`。若换到较旧且已纳入 Alembic 的数据库，先备份、核对该版本迁移前置条件、停止相关写入，然后才执行 `python -m alembic upgrade head`。未知旧库不能直接 stamp；全新空库需管理员先安装 vector 扩展，再由普通应用账号升级。详见 [部署指南](DEPLOY.md)。

当前相似病例的缺项是“数据 release/参考索引”，与“表结构 migration”不同；重复 `alembic upgrade head` 不会自动补齐它。

## 3. 建立一致的本地运行环境

以下从项目根目录执行，仅用于新环境或缺少依赖时恢复。本机`backend/.venv`已安装完成，不必重复创建；不要用`.superpowers/p2/ocr-venv`验证环境代替项目运行环境。创建前确认`py -3.11 --version`为3.11.4。

```powershell
Set-Location 'C:\Users\86182\Desktop\Surgery RAG-Agent'
py -3.11 -m venv backend/.venv
& .\backend\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
& .\backend\.venv\Scripts\python.exe -m pip check
& .\backend\.venv\Scripts\python.exe -c "import paddle, paddleocr; print(paddle.__version__, paddleocr.__version__)"
& .\backend\.venv\Scripts\python.exe -m playwright install chromium

Set-Location frontend
node --version
npm --version
npm ci
```

预期Python 3.11.4、Node 22.15.0、npm 10.9.2；OCR版本3.7.0 / Paddle 3.3.0。项目显式固定NumPy 2.3.5、pandas 3.0.5、scikit-learn 1.9.0、joblib 1.5.3；模型制品自身的依赖兼容检查仍保留。当前代码已在Windows禁用不兼容的MKLDNN；不需要改回旧`use_gpu`参数。默认CPU路径即可。

### 资源准备与依赖文件的分工

| 内容 | 如何恢复 | 本机同日准备结果 |
|---|---|---|
| Python包 | 使用项目`.venv`执行`pip install -r backend/requirements.txt`；PyTorch等间接依赖由pip安装 | 已安装，`pip check`通过 |
| 前端包 | 在frontend执行`npm ci`，沿用`package-lock.json` | 已安装，单元/契约测试及build通过 |
| BGE-M3模型权重 | 应用首次加载按`EMBEDDING_MODEL`下载，优先ModelScope、再回退HuggingFace；也可复用完整缓存 | 已有缓存实际离线编码通过，没有重新下载整套BGE权重 |
| OCR模型权重 | PaddleOCR首次初始化会准备模型；离线环境需预先复制完整缓存 | 已从旧测试缓存复制到运行账号默认`.paddlex`缓存，并实际识别通过 |
| Chromium与Headless Shell | 使用同一`.venv`执行`python -m playwright install chromium`；安装Python的playwright包不等于安装浏览器 | 已下载匹配当前Playwright的浏览器 |
| PDF字体、许可、renderer | 按第6节准备两套Noto字体和许可，再构建当前环境的manifest | 已复用带许可字体并构建验证renderer |
| PostgreSQL及扩展 | 单独安装数据库服务及vector、uuid-ossp、pg_trgm；核对已有库迁移状态 | 本机已有，不由requirements安装 |

BGE的优先缓存根目录是运行账号的`~/.cache/surgery-rag`，HuggingFace回退使用其缓存机制。OCR旧测试缓存位于`.superpowers/p2/ocr-cache`，如指定其他缓存，需在进程启动前设置`PADDLE_PDX_CACHE_HOME`为绝对路径。缓存必须属于实际运行API/worker的账号可读取的位置；文件存在不等于加载成功。新环境应执行一次BGE编码和虚构图片OCR识别验证。预热会占用时间和内存，加载期间不要连续重启。

模型权重、浏览器、字体不是Python包，不能作为条目加入requirements。本次仅补齐NumPy/pandas的显式声明；requirements中其他未固定版本及间接依赖仍由pip解析，因此不是完整环境锁文件。更换Playwright、Chromium、FontTools、字体或渲染相关源码后，必须重新构建renderer manifest；保留已发布PDF原件。

## 4. 检查 backend/.env

文件已存在，**不要用 .env.example 覆盖现有配置**。只补需要的项；不要把真实密钥提交 Git。全部进程加载同一环境，修改后重启相关进程。

- [ ] DATABASE_URL 指向本次手动验收要用的本机库；VECTOR_STORE_CONNECTION_STRING 留空复用它，或确实指向同一套索引。
- [ ] JWT_SECRET 是固定非占位密钥；DeepSeek Key/base URL/model 正确。Key 已填写不等于网络调用已通过。
- [ ] UPLOAD_DIR 指向现有 uploads；若是 `../uploads`，从 backend 目录启动。
- [ ] 历史密钥独立生成，至少 32 字节，持久保存，不与 JWT 共用，不随每次重启更换。
- [ ] 报告和 PDF 的 ENABLED 先开启，ACCEPTING 在相应 worker/资料校验通过后再开启；完整手动验收最终需要四个开关均为 True。
- [ ] 本地保持并发 1；不要为了排队提示直接增大并发。

可在自己的终端生成一次历史密钥并填入 `.env`：

```powershell
& .\backend\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

最终需要核对的配置名：

```dotenv
REPORT_HISTORY_CURSOR_SECRET=<刚生成的持久密钥>
REPORT_JOBS_ENABLED=True
REPORT_JOBS_ACCEPTING=True
REPORT_PDF_ENABLED=True
REPORT_PDF_ACCEPTING=True
REPORT_ARCHIVE_ROOT=<本机绝对私有目录>
REPORT_PDF_RENDERER_MANIFEST=<当前环境构建的manifest.json绝对路径>
```

尖括号均为说明，不能原样粘贴为配置值。历史列表/生成报告/归档 PDF 是不同功能，开启其中一个不会自动配置其余功能。

## 5. 参考数据、标准和模型

只读核查（从根目录，项目依赖装好后）：

```powershell
& .\backend\.venv\Scripts\python.exe scripts/check_longitudinal_readiness.py
& .\backend\.venv\Scripts\python.exe scripts/check_database_readonly.py --phase postflight
& .\backend\.venv\Scripts\python.exe scripts/build_reference_case_windows.py --dataset fatty_liver
& .\backend\.venv\Scripts\python.exe scripts/build_reference_case_windows.py --dataset ad
```

前述旧检查器误报需要结合第 1 节判断。`check_longitudinal_readiness.py` 当前整体为 degraded：模型可用；参考数据尚未显式发布；模型分数尚未校准；AD 标准只有证据解释。这些状态不应被表述成“模型文件不存在”。

要测试参考病例成功匹配，需核实 `data/generated` 对应数据的正式 release ID 和内容 SHA-256，与来源登记一致，再通过 `scripts/import_longitudinal.py --dataset <fatty_liver或ad> --release-id <经核实的ID> --data-content-sha256 <经核实的哈希> --activate` 发布。之后先 dry-run，确认统计与准入结果，再对两病种分别运行 `build_reference_case_windows.py --dataset ... --apply`。这些是写库步骤，本次未执行；不要使用 `--reset` 清空现有记录，也不要随意编造 release/来源或把合成数据标作真实来源。

没有通过准入的参考病例时，应验收明确的“无合格病例/索引未就绪”说明；不能要求系统凑出相似病例。模型 registry 文件上的 release 身份与数据库参考记录的活动 release 是两套相关配置，前者存在不会自动补后者。

两份当前批准标准的源文件和哈希已验证存在。重新向量化聊天文档不会创建标准版本或参考病例窗口。临时测试种子只用于独立测试库，不能导入现有业务库补齐缺项。

## 6. PDF 额外准备

只有 API 和生成报告 worker 不足以准备 PDF，还需要 Chromium、固定字体、renderer manifest、独立 PDF worker 和持久私有目录。

1. 建立项目外的本地私有持久目录，例如 `%LOCALAPPDATA%\SurgeryRAG\report-archives`，按 Windows ACL 限定本机服务账号/管理员访问。不要配置到 uploads、网页静态目录、网络盘或目录联接。
2. 准备 NotoSansCJKsc-Regular.otf、NotoSans-Regular.ttf 及分别命名为 LICENSE、LICENSE-latin 的许可。字体官方来源和制品规则见 [报告运维手册的固定渲染制品](OPERATOR_REPORT_OPERATIONS.md#固定渲染制品)。
3. 用将要运行后端的 `.venv` 构建当前 Windows renderer：

```powershell
& .\backend\.venv\Scripts\python.exe scripts/build_report_pdf_renderer_manifest.py --font-dir '<字体绝对目录>' --output-dir '<渲染制品绝对目录>'
```

4. 将输出的 manifest.json 绝对路径写进 `.env`，连同 REPORT_ARCHIVE_ROOT 一起配置。以前隔离测试成功的 manifest 不自动适用于新 `.venv`；Python、Playwright、Chromium、字体、模板或相关源码变化后需重新构建。
5. 启动 PDF worker，确认无 renderer/目录错误，再开放 PDF_ACCEPTING。已归档原件持续下载原字节，不能用重新生成替代原件恢复。

## 7. 手动启动顺序（PowerShell）

下列是多个独立终端；先确保数据库运行、配置及依赖已就绪。端口本次未得出可靠探测结果，手动确认 8000/5173 没有旧实例占用。

### 终端 A：后端 API

```powershell
Set-Location 'C:\Users\86182\Desktop\Surgery RAG-Agent\backend'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

等待 BGE 预热、向量库初始化和 `Application startup complete`。然后在另一个终端访问：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

预期 `status=ok`。API 文档：`http://127.0.0.1:8000/docs`。启动过程会初始化 LangChain 内部向量表/索引，因此不是纯只读动作；本次没有替你启动。

### 终端 B：前端

```powershell
Set-Location 'C:\Users\86182\Desktop\Surgery RAG-Agent\frontend'
node .\node_modules\vite\bin\vite.js --host 127.0.0.1 --port 5173 --strictPort
```

访问 `http://127.0.0.1:5173`；Vite `/api` 默认代理到 `http://localhost:8000`。若旧终端留有 E2E_API_PROXY，先核对/清除错误覆盖。`/health` 直接访问后端端口。

此处直接调用本项目Vite，沿用本机已验证的启动方式，避免npm转发参数后仍仅监听`::1`的问题；前端依赖管理仍只使用npm。

### 终端 C：报告生成 worker

```powershell
Set-Location 'C:\Users\86182\Desktop\Surgery RAG-Agent\backend'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m app.workers.report_worker
```

REPORT_JOBS_ENABLED 必须为 True；常驻无任务时等待是正常现象。不要用 `--once` 代替完整手动验收的常驻 worker。

### 终端 D：PDF worker

```powershell
Set-Location 'C:\Users\86182\Desktop\Surgery RAG-Agent\backend'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m app.workers.report_pdf_worker
```

REPORT_PDF_ENABLED 必须为 True；只有点“准备 PDF”后才有任务。

### 终端 E/F/G：故障收敛与文件清理

要测试超时、worker 退出恢复、删除补偿，还必须运行独立巡检/清理。每段独占一个终端，Ctrl+C 停止；每轮仅处理登记任务，不清空任意目录。

```powershell
# E：报告过期巡检
Set-Location 'C:\Users\86182\Desktop\Surgery RAG-Agent\backend'
while ($true) {
    .\.venv\Scripts\python.exe -m app.workers.report_worker --sweep-only
    Start-Sleep -Seconds 15
}
```

```powershell
# F：PDF 过期巡检
Set-Location 'C:\Users\86182\Desktop\Surgery RAG-Agent\backend'
while ($true) {
    .\.venv\Scripts\python.exe -m app.workers.report_pdf_worker --sweep
    Start-Sleep -Seconds 15
}
```

```powershell
# G：文件清理补偿
Set-Location 'C:\Users\86182\Desktop\Surgery RAG-Agent\backend'
while ($true) {
    .\.venv\Scripts\python.exe ../scripts/manage_report_pdf_archives.py cleanup --once
    Start-Sleep -Seconds 15
}
```

单次 `--sweep-only` / `--sweep` 执行后退出，不是常驻服务。Linux 部署使用现有 systemd service/timer，此处只提供本机手动验收方式。

## 8. 启动后的第一轮确认

- [ ] API 启动完成、/health 返回 ok，前端无代理错误。
- [ ] 三种账号能登录且路由正确；用测试账号操作，先不删既有资料。
- [ ] 问一条已入库知识相关问题，真实模型返回引用并在刷新后保留。
- [ ] 选择脂肪肝/AD，指标目录可加载，虚构的一次访视可保存。
- [ ] 历史列表可读取；三访视病例可按条件受理，worker 从 queued 推进到终态。
- [ ] PDF worker 能准备一份实际原件并下载；确认中文及上标单位正常。
- [ ] 最后再按 [完整清单](MANUAL_TEST_CHECKLIST.md) 测分页、隔离、取消、错误、删除和恢复。

若报告一直 queued，优先看 worker/开关；历史列表失败优先看 cursor secret；PDF 未准备优先看 PDF worker/renderer/目录；参考窗口构建 blocked 则看活动 release。不要因为 /health 为 ok 就跳过这些检查。

## 9. 原始资料路径（仅原始资料验收时需要）

在项目根目录执行，仅给当前 PowerShell 会话设置：

```powershell
$sourceDir='C:\Users\86182\Desktop\项目相关文件-2026-7-9'
$env:FATTY_LIVER_DOC_A=Join-Path $sourceDir '脂肪肝相关病例（1-78例）.docx'
$env:FATTY_LIVER_DOC_B=Join-Path $sourceDir '脂肪肝病例-2026.8.7.docx'
$env:AD_DOC_A=Join-Path $sourceDir 'AD病例（1-73例）.docx'
$env:AD_DOC_B=Join-Path $sourceDir 'AD病例70例.docx'
& .\backend\.venv\Scripts\python.exe -m pytest scripts/tests/test_generate_fatty_liver_longitudinal.py scripts/tests/test_generate_ad_longitudinal.py -q
```

这些变量不是 API 日常启动必需项。不要把聊天上传、原始训练/生成资料、参考病例表、标准文档和模型 registry 混为同一套自动导入流程。

## 10. 验证记录与边界

证据保存在本机 `.superpowers/manual-check/database.json`、`readiness.json`、`report-preflight.json`，配置检查仅输出是否就绪及非敏感计数，未输出密钥或病例内容。

该目录只记录最初只读检查；后续依赖安装、OCR/BGE加载和PDF资源准备记录在`.superpowers/startup-prep/RESULT.md`，完整验收及修复结果见[手动测试结果](MANUAL_TEST_RESULTS_2026-09-08.md)。本次依赖声明补齐只修改文件，没有重装环境、重新下载资源或写数据库；也未从空环境重装验证全部未锁定依赖。GPU和正式参考数据发布仍未执行。
