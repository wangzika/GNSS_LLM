# industrial_v2 数据导航

本目录按 [工业故障六步流程](../../docs/industrial_fault_workflow.md) 组织。每步都有 `input/`、`output/`，文件内容保持不变。306 条事件 → 214／31／61 划分 → 214 条教师报告 → 134 条训练数据。

```text
industrial_v2/
├── 01_prepare/       原始数据准备
│   ├── input/        原 CSV、v1 固定划分参考的相对链接
│   └── output/       events_meta.json（306 条完整事件快照）
├── 02_split/         数据划分
│   ├── input/        完整事件快照链接
│   └── output/       各集合元数据、纯输入、独立标签、提示词与来源清单
├── 03_teacher/       教师生成
│   ├── input/        训练元数据和无答案提示词链接
│   └── output/       214 条原始回答与报告汇总
├── 04_review/        检查与审阅
│   ├── input/        训练元数据、教师报告链接，以及追加的争议裁定
│   └── output/       审阅日志、最终判定、训练数据、旧版归档
├── 05_finetune/      学生微调
│   ├── input/        已审阅 train_sft_clean.jsonl 链接
│   └── output/       长度检查、results/ 中训练统计的相对链接
├── 06_evaluation/    留出集推断与评估
│   ├── input/        验证／测试纯输入及独立标签链接
│   └── output/       三种验证协议的预测、指标、错误分析
└── layout.json       本次迁移旧路径 → 新路径及原文件 SHA-256
```

`input/` 中的相对符号链接是上游文件的入口，并未复制数据；Git 会保存链接关系。移动或克隆整个项目后仍可使用。不要单独复制本目录而遗漏 `industrial_source/`、`industrial_v1/`、`results/`。真实标签只供审阅和评分；教师和学生请求不会带真实标签。

## 每个文件的用途

下面路径均相对本目录；每个 `input/`、`output/` 内的 README 说明该目录约定。

| 阶段和位置 | 文件 | 作用 |
| --- | --- | --- |
| `01_prepare/input/` | `raw_ai4i2020.csv` | 原始 10,000 行 CSV 链接 |
| 同上 | `v1_train_meta.json`、`v1_validation_inputs.jsonl`、`v1_test_inputs.jsonl` | 保留原 50 条事件的集合归属，不重新混分 |
| `01_prepare/output/` | `events_meta.json` | 合并既有三份元数据，按事件 ID 排序的 306 条完整快照；含标签，不是模型输入 |
| `02_split/output/` | `train_meta.json` | 214 条带标签训练元数据，生成请求前剥离标签 |
| 同上 | `validation_meta.json`、`test_meta.json` | 31／61 条内部留出元数据 |
| 同上 | `validation_inputs.jsonl`、`test_inputs.jsonl` | 不带答案的学生推断输入 |
| 同上 | `validation_labels.jsonl`、`test_labels.jsonl` | 独立参考标签，仅评分读取 |
| 同上 | `manifest.json` | 种子、数量、类别、原 CSV 哈希与限制 |
| 同上 | `source_provenance.jsonl` | 事件到 CSV UDI、产品 ID、集合的追溯表，不送给模型 |
| 同上 | `teacher_prompts_blind.txt` | 手工调用教师的无标签提示词；程序调用直接读元数据 |
| `03_teacher/output/` | `teacher_responses.jsonl` | 完整 214 条教师原始回复，可断点续跑 |
| 同上 | `teacher_raw.txt` | 按元数据顺序汇总的原始报告 |
| `04_review/input/` | `agent_review_decisions.jsonl` | 对争议事件追加的裁定，是最终审阅的输入 |
| `04_review/output/` | `report_audit_recomputed.jsonl` | 当前采用的 214 条验算记录，含原始回复及提取断言 |
| 同上 | `report_audit.jsonl` | 早期审阅日志，仅本地保留，不作为最终判定 |
| 同上 | `final_review_decisions.jsonl` | 最终逐条接受／拒绝／不确定及理由 |
| 同上 | `audit_summary.json` | 134 接受、50 拒绝、30 不确定的汇总 |
| 同上 | `REVIEW.md` | 可阅读的逐事件审阅表 |
| 同上 | `train_sft_clean.jsonl` | 正式训练的 134 条 Alpaca 样本 |
| 同上 | `train_sft_review.jsonl` | 历史兼容导出；当前与 clean 内容相同，不能理解成完整 214 条 |
| 同上 | `local_verification.json` | 原有本地数值、唯一性、标签泄漏、长度和服务器哈希核查记录 |
| 同上 | `archive/` | 被替换的旧审阅输出，完整保留但不提交 Git |
| `05_finetune/output/` | `sequence_length_check.json` | token 长度检查，实际训练框架最大 632，无截断 |
| 同上 | `train_results.json`、`trainer_log.jsonl`、`adapter_config.json` | 指向 `results/industrial_v2/` 的已发布训练统计与配置链接 |
| `06_evaluation/output/` | `validation_predictions.jsonl`、`validation_metrics.json`、`validation_metrics_three_classes.json` | 首版消息布局和标签解析的预测及全类／三类分数 |
| 同上 | `validation_predictions_reparsed.jsonl`、`validation_metrics_reparsed.json`、`validation_metrics_reparsed_three_classes.json` | 保持原报告，仅修正中文结论解析后的结果 |
| 同上 | `validation_predictions_aligned.jsonl`、`validation_metrics_aligned.json`、`validation_metrics_aligned_three_classes.json` | 消息格式对齐训练后的预测与分数；当前主要验证结果 |
| 同上 | `validation_predictions_aligned.jsonl.meta.json` | 对齐推断时的模型、消息布局和生成参数 |
| 同上 | `validation_error_analysis.json` | 错误分析及规则基线参考；规则成绩不是学生成绩 |

## 后续约定

- 版本根目录只放导航和布局清单；新产物进入所属步骤的 `output/`。
- 上一步拥有唯一输出；下一步通过相对链接消费它。不要手工改写输入链接。
- 统一路径定义在 `scripts/industrial/workflow_paths.py`，新增文件先登记归属。
- 扩充脚本创建新版本时自动建立六阶段目录和链接。已经存在的 v1 扁平数据仍兼容。
- 微调的大权重和完整日志仍写入 YAML 的 `outputs/industrial/...`；这里放训练入口、检查与小型统计。它们不随本次整理重新训练。
- 新实验使用新的版本目录和匹配的 dataset_info、训练／推断配置；旧预测文件不要覆盖。

当前对齐验证为 11/31（35.5%），三类为 11/27（40.7%）；全部预测 HDF，未超过多数类基线。测试集尚未运行。本次仅调整文件组织和路径。
