# 工业故障与 GNSS 先导数据说明

## 来源与许可

工业原始数据为 UCI 的 **AI4I 2020 Predictive Maintenance Dataset**，DOI：[10.24432/C5HS5C](https://doi.org/10.24432/C5HS5C)。官方页面：[UCI AI4I 2020](https://archive.ics.uci.edu/dataset/601/ai4i%2B2020%2Bpredictive%2Bmaintenance%2Bdataset)。原始数据采用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)；复用原始记录与其结构化派生内容时需保留该归属及许可说明，并注明本项目进行了筛选、重排、上下文补充与报告生成。

原始数据是合成铣削过程记录，不是本项目采集的工厂现场数据。教师模型来源为 [Qwen2.5-32B-Instruct](https://huggingface.co/Qwen/Qwen2.5-32B-Instruct)，训练学生为 Qwen2.5-3B-Instruct。仓库不包含这些基础模型权重。

## 版本与文件

- `industrial_source/`：原始 CSV 与早期 50 条带标签内部元数据。
- `industrial_v1/`：早期 35/5/10 划分，旧版报告重审后接受 20 条。
- `industrial_v2/`：全部 306 条独立单故障事件，训练/验证/测试为 214/31/61。保留旧 50 条的划分归属，同一物理输入不跨集合。
- `industrial_v2/train_sft_clean.jsonl`：214 条教师训练报告审阅后保留的 134 条 Alpaca 训练样本，三类数量为 PWF 36、HDF 56、OSF 42。
- `industrial_v2/teacher_responses.jsonl` 与 `teacher_raw.txt`：完整 214 条模型回答及汇总，不应直接把全部回答视为可训练数据。
- `industrial_v2/final_review_decisions.jsonl`、`REVIEW.md`：134 接受、50 拒绝、30 不确定的逐条记录。拒绝包含格式、比较或证据问题及保守筛选，并不等于每条最终类别都错误。
- `source_provenance.jsonl`：事件 ID 与原始 UDI、Product ID、划分对应，用于来源追溯，不应作为诊断输入。
- `validation_*`、`test_*`：纯输入和参考标签独立存放；预测脚本不读取标签。测试集截至本次发布尚未用于最终评估。
- `gnss_pilot_v1/`：50 条临时合成场景，剧本意图不是已确认真实动机，未通过领域专家认证。

## 生成与审阅

教师请求移除 `ground_truth_intent`、`case_type`、`data_source`，但加入程序计算的温差、轴功率、磨损负荷以及公开规则的触发检查。这是**规则辅助报告生成**，不是教师独立盲诊断能力的测量。`<think>` 标签仅封装供公开阅读的简短分析依据，不表示取得模型内部思考。

审阅结合字段、标签、规则和文本比较检查，以及 Codex 代理对分析段的复核。同一教师服务另一次请求只提取报告原句与比较结构，程序验算真假；提取模型和正则仍可能漏检或误读。不是外部独立专家评审。部分中文类别名在打包时补齐英文名，风险/不确定性限定保留，原始回答未改写。

## 限制与已知结果

1. 不含正常样本和多故障样本，任务限于所选故障类别。
2. 运行模式、车间区域是随机补充背景；缺失上下文的固定置信度要求未做概率校准。
3. TWF/RNF 实际发生含随机机制，不能仅凭当前物理特征确定。TWF 的 30 条训练事件未进入确定标签训练文件。
4. 8.6 K 等边界处存在公开规则重算与源标注不一致的事件，训练审阅进行了保守剔除。
5. 划分按独立事件行保留，不构成生产批次或时间泛化验证。
6. 首轮学生训练后，对齐输入的验证结果全部预测为 HDF，准确率35.5%，等于多数类基线。134条训练数据不代表已经获得有效诊断模型。
7. 原始、标签提取修正、消息位置对齐三种验证结果分别保存。应保持评估协议一致，不能选择性报告较好的指标。

完整流程见 `docs/industrial_v2_review.md` 和 `docs/industrial_fault_workflow.md`。原始模板自检权重、环境、缓存、旧审阅归档与日志不在本次 Git 发布范围内。
