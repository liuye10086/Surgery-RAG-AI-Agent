# Task A 去重验证记录

任务：prediction-patient-dedup-001（预测统计按患者去重）
日期：2025-01-XX
实施者：Claude-Code

## Step 1: 精确统计（预期去重后数量）

### 脂肪肝
- 原始 confirmed 行数: **675**
- 去重键数量（纵向数据）: 150
- 独立记录数（旧手工/无标签）: 0
- **预期去重后数量: 150**
- 去重率: 77.8%

### 阿尔茨海默病
- 原始 confirmed 行数: **1233**
- 去重键数量（纵向数据）: 270
- 独立记录数（旧手工/无标签）: 0
- **预期去重后数量: 270**
- 去重率: 78.1%

统计方法：使用 TRIM(patient_label) 与生产代码保持一致，DB 列名 `metadata` 而非 ORM 属性名 `case_metadata`。

---

## Step 2: 前端冒烟测试

待完成：
1. 启动服务和前端
2. 登录操作者账号
3. 测试脂肪肝（ALT=70 U/L）
4. 从 Network 面板 SSE 响应读取 `event: indicators` 后的 `data.probability.sample_size`
5. 验证：actual == 150
6. 重复测试 AD（MMSE=20 分）
7. 验证：actual == 270

---

## Step 3: Codex 事后评审

待提交。
