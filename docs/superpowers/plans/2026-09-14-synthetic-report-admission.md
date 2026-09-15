# 合成数值报告B包：来源与接单实施计划

**Goal:** 在明确隔离环境中建立不可编辑的合成病例来源绑定，并通过既有报告任务接口受理新数值任务。

**Architecture:** 来源模块核验固定包并原子导入病例／访视／绑定；接单服务按显式report_kind校验权限和来源，保存固定输入与算法上下文。旧请求哈希及临床标准路径保留；当前旧worker排除新数值上下文，C包实现消费者后再解除该限制。

**Tech Stack:** Python 3.11.4、现有venv／SQLAlchemy／Alembic／pytest；前端维持Node22.15.0与npm10.9.2。

## 约束

- 不写现有业务库；迁移只在本轮新建、绑定127.0.0.1的私有PostgreSQL测试实例验收。
- 只读冻结合成包，不修改A包或旧输出；合成来源不得借缺省／legacy入口丢失标识。
- 普通病例保存／访视增删改拒绝工程输入编辑；既有归档和删除语义保留。
- 新任务仍受原幂等、用户／病例容量、取消和排队超时管理；默认新开关关闭。B包接单不代表生成完成。
- 本轮不实现数值文档发布、完整历史渲染、页面或PDF，不训练、提交、推送、部署。

## 执行步骤

- [x] 1. 来源模块与种子：新增synthetic_case_source schema/service、seed CLI及测试。接口 `build_engineering_binding(case,numeric_input)`、`validate_engineering_case(case)`、`seed_synthetic_cases(session_factory,package_dir,user_id,subject_ids)`。
- [x] 2. 写迁移0027与DB字段；增加默认关闭SYNTHETIC_REPORTS_ENABLED。新字段仅可null或合成绑定对象，downgrade有来源数据时拒绝。
- [x] 3. 先写请求哈希、编辑拒绝、快照／上下文与真实接单测试，再实现。`report_kind=synthetic_numeric`只允许空model_options；缺省仍使用旧v1请求哈希。新增独立合成上下文，内部包含A包输入；最终锁内重读来源、病例、疾病及算法身份，任何变化拒绝。
- [x] 4. 旧readiness对工程病例返回明确类型不匹配；服务端所有接单入口双向约束来源。暂时阻止旧worker认领新数值任务；状态、取消和队列超时照常可用。
- [x] 5. 实际隔离PostgreSQL迁移与HTTP／服务事务验收：两病种、跨用户／角色、禁用疾病、伪造／篡改来源、编辑与legacy绕过、并发同键、幂等冲突／关闭后重放、容量、取消、输入固定及误领防护。旧相关集成回归。
- [x] 6. 同步前端请求类型／调用方检查，相关Vitest／契约与构建；记录本轮结果、既有文件保全、下一步及限制。

相关执行命令（backend目录，集成由本轮隔离启动器注入TEST_DATABASE_URL和DATABASE_URL）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_synthetic_report_admission.py tests/test_synthetic_case_source.py -q
.\.venv\Scripts\python.exe -m pytest tests/integration/test_synthetic_report_admission.py -q
```

具体迁移与报错测试会断言真实列约束、持久行内容、HTTP状态与拒绝后无写入；不能只以mock成功作为B包通过依据。

**下一步：**C包worker、数值报告原子发布及历史读取；其后D包页面／PDF、E包隔离总验收。真实A2–A5及正式阶段三至五保持独立。

执行结果：六项完成，最终301项后端单元、54项隔离集成、115项前端单元与30项契约通过，构建成功。详见[验收记录](../notes/2026-09-14-synthetic-report-admission-result.md)。
