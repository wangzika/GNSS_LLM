# 数据来源与实验限制

工业数据来自 UCI 的 **AI4I 2020 Predictive Maintenance Dataset**，DOI：[10.24432/C5HS5C](https://doi.org/10.24432/C5HS5C)，[官方说明](https://archive.ics.uci.edu/dataset/601/ai4i%2B2020%2Bpredictive%2Bmaintenance%2Bdataset)，采用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。复用原始记录与派生内容时保留来源和许可，并注明本项目做了筛选、重排、背景补充与报告生成。

AI4I 是合成铣削过程数据，并非本项目采集的工厂现场测量。当前只维护 `data/industrial/`；完整文件清单及流程见 [工业故障流程](../docs/industrial_fault_workflow.md)。

- 原始 10,000 行，339 行总故障标记；保留 306 条唯一单故障，划分 214／31／61。
- 当前划分表用原始 UDI 和 CSV 哈希固定，与旧版本代码无依赖。
- 教师为 Qwen2.5-32B-Instruct，学生为 Qwen2.5-3B-Instruct；基础权重不在仓库内。
- 唯一教师原文：`industrial/02_teacher/output/teacher_responses.jsonl`，214 条。
- 唯一正式训练文件：`industrial/03_review/output/train_sft.jsonl`，134 条，PWF 36、HDF 56、OSF 42。
- 最终裁定：接受 134、拒绝 50、不确定 30。拒绝含保守筛选，不表示每条类别都错误。
- 当前学生预测与合并指标在 `industrial/05_evaluation/output/`。保留与训练消息格式一致的协议；早期错误协议记录在 Git 历史中。

教师请求没有真实标签，但有公开规则、程序派生量和触发检查，属于**规则辅助报告生成**。`<think>` 只封装公开分析依据，不代表模型内部思考。审阅时同一教师服务提取原句，Python 验算，并加入保守文本检查和 Codex 争议裁定；不是独立外部专家认证。

当前任务不含正常类与多故障类。运行模式、车间区域是随机背景，固定置信度要求未经校准。TWF/RNF 实际发生含随机性，当前观测不能确认，因此 30 条 TWF 训练事件不进入确定标签训练。部分公开规则边界与源标签不一致，审阅进行了保守剔除。集合按独立事件行划分，不证明时间或批次泛化。

当前对齐验证全部预测 HDF，全类别准确率 35.5%，等于多数类基线；31 份报告均有已列出的派生量计算错误，尚未证明有效诊断能力。61 条测试事件尚未用于最终评估。

GNSS 是独立工作，`gnss_pilot_v1/` 为 50 条临时合成场景，剧本意图不是已确认真实动机，尚未经过领域专家认证；本次工业清理不改动它。
