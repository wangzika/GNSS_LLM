# 工业故障流程与文件用途

2026-11-25 更新：主流程为 v2，306 条独立单故障事件，划分 214／31／61；教师生成 214 条报告，审阅保留 134 条；学生已完成 4 轮微调。对齐消息格式后的验证准确率为 35.5%，全部预测多数类 HDF，尚未证明有效诊断能力。测试集尚未运行。

所有命令从项目根目录执行。本机 `/home/wzb/GNSS_LLM`，服务器 `/data/zbwang/GNSS_LLM`。v2 完整逐文件说明见 [数据导航](../data/industrial_v2/README.md)，审阅方法见 [扩充与审阅](industrial_v2_review.md)。v1 历史实验保留原布局。

## 统一文件规则

每个实验版本按 `01_prepare → 02_split → 03_teacher → 04_review → 05_finetune → 06_evaluation` 建目录，每步都有 `input/`、`output/`。

输出保存在产生它的步骤；下游 `input/` 使用相对符号链接指向上游输出。数据只存一份，避免复制后版本不一致。路径由 [workflow_paths.py](../scripts/industrial/workflow_paths.py) 统一管理，后续创建新版本时自动沿用。模型权重继续保存在训练 YAML 指定的 `outputs/`，小型已发布统计在 `results/`；第五步提供入口。

## 1. 原始数据准备：01_prepare

| 代码／位置 | 作用 |
| --- | --- |
| `scripts/industrial/industrial_expand_dataset.py` | 从原 CSV 选出全部单故障事件，同时执行下一步分层划分 |
| `scripts/industrial/step1_prepare_inputs.py` | 早期 50 条抽样及字段构造；v2 复用字段构造函数 |
| `01_prepare/input/raw_ai4i2020.csv` | 链接到 `data/industrial_source/raw_ai4i2020.csv` |
| `01_prepare/input/v1_*` | 保留早期 50 条事件的训练／验证／测试归属 |
| `01_prepare/output/events_meta.json` | 306 条完整内部事件快照，含真实标签，不直接发送给模型 |

原始 CSV 共 10,000 行，其中标记故障 339 行；只保留 `Machine failure=1` 且只命中一个故障子类的 306 行。正常行、多故障行和无具体子类的故障行不在本实验内。AI4I 是合成数据；运行模式、车间区域是额外随机背景。

准备与划分由一条命令完成。当前 v2 已存在，不要覆盖；重现实验先指定新目录：

```bash
python -m scripts.industrial.industrial_expand_dataset --out-dir data/industrial_v3
```

该命令只准备与划分数据，不生成报告、不启动训练。新版本训练前还需注册对应数据集并配置独立输出目录。

## 2. 划分训练、验证和测试集：02_split

| 输入／输出 | 文件与用途 |
| --- | --- |
| `02_split/input/` | `events_meta.json` 链接，完整事件快照 |
| `02_split/output/train_meta.json` | 214 条内部训练记录，含标签供审阅 |
| `02_split/output/validation_*` | 31 条验证元数据、纯输入和独立标签 |
| `02_split/output/test_*` | 61 条测试元数据、纯输入和独立标签 |
| `02_split/output/teacher_prompts_blind.txt` | 无标签手工提示词，下一步 input 提供链接 |
| `02_split/output/manifest.json` | 种子 42、集合数量、类别统计及限制 |
| `02_split/output/source_provenance.jsonl` | CSV UDI、产品 ID、集合归属追溯，不作为模型输入 |

v2 在 `industrial_expand_dataset.py` 中按类别约 7:1:2 划分，并保留 v1 中既有事件归属。同一物理输入不跨集合；这不等于按生产时间或批次留出。`industrial_prepare_workflow.py` 是早期小样本的 35／5／10 划分入口，不能用于替代 v2 的全量划分。

## 3. 启动教师并生成报告：03_teacher

教师环境及启动说明见 [教师服务器配置](teacher_server_setup.md)。服务已运行时直接调用。

```bash
bash scripts/server/start_teacher_server.sh
# 另开终端，在服务器项目根目录执行：
python -m scripts.industrial.industrial_generate_teacher --data-dir data/industrial_v2 --dry-run
python -m scripts.industrial.industrial_generate_teacher --data-dir data/industrial_v2 --workers 4
```

| 输入／输出 | 文件与用途 |
| --- | --- |
| `03_teacher/input/train_meta.json` | 上游训练元数据链接，程序构造请求时去除标签等内部字段 |
| `03_teacher/input/teacher_prompts_blind.txt` | 供手工调用；程序不会解析此文本 |
| `03_teacher/output/teacher_responses.jsonl` | 逐事件原始回复，已有 214 条，可断点续跑 |
| `03_teacher/output/teacher_raw.txt` | 按事件顺序汇总的原始报告 |

代码为 `industrial_generate_teacher.py`，教师 Qwen2.5-32B-Instruct，通过本机 vLLM API 调用。请求没有真实标签，但含公开规则、程序计算的温差、轴功率、磨损负荷及规则触发标志，属于规则辅助报告生成。`<think>` 是要求公开输出的简短分析依据，不代表模型内部思考。

## 4. 自动检查与报告审阅：04_review

| 输入／输出 | 文件与用途 |
| --- | --- |
| `04_review/input/` | 上游训练元数据、原始报告链接，以及 `agent_review_decisions.jsonl` 追加争议裁定 |
| `04_review/output/report_audit_recomputed.jsonl` | 当前逐事件检查、原文断言提取与验算记录 |
| `04_review/output/final_review_decisions.jsonl` | 最终接受／拒绝／不确定及原因 |
| `04_review/output/audit_summary.json`、`REVIEW.md` | 数量汇总和可读逐事件审阅表 |
| `04_review/output/train_sft_clean.jsonl` | 134 条正式 Alpaca 训练数据 |
| `04_review/output/train_sft_review.jsonl` | 历史兼容导出，目前与 clean 一致 |
| `04_review/output/local_verification.json` | 本地唯一性、数值、泄漏、长度及同步核查记录 |
| `04_review/output/archive/` | 输出替换前备份，不提交 Git |

`industrial_build_reports.py` 核对 ID、结构、标签、原始数值及可重算规则；同一教师服务的另一请求提取报告原句，Python 验算比较真假。`industrial_finalize_review.py` 加入保守文本检查与争议裁定。不是外部独立专家评审。

当前审阅已完成，以下是复现命令，会先备份旧输出；只需重现最终筛选时运行第二条即可。无需因为目录变化再次调用教师。

```bash
python -m scripts.industrial.industrial_build_reports \
  --data-dir data/industrial_v2 --workers 6 --attempts 1 \
  --audit-name report_audit_recomputed.jsonl
python -m scripts.industrial.industrial_finalize_review --data-dir data/industrial_v2
```

最终为 134 接受、50 拒绝、30 不确定。拒绝包含格式、比较、证据及保守筛选，不表示每份报告类别都错误。30 条 TWF 无法由现有观测确认随机故障，保留原报告，排除出确定标签训练。`scripts/common/step2_validate_and_pack.py` 仅为基础格式／数值打包，不可用它覆盖已完成的最终审阅结果。

## 5. 微调学生模型：05_finetune

```bash
conda activate gnss-intent
python -m scripts.common.check_runtime
llamafactory-cli train configs/industrial/qwen_industrial_v2_qlora_8gb.yaml
```

上面训练命令用于复现实验；本轮已经训练完成，目录整理无需重新训练。

| 输入／输出与配置 | 用途 |
| --- | --- |
| `05_finetune/input/train_sft_clean.jsonl` | 指向第四步的 134 条已审阅训练样本 |
| `data/dataset_info.json` | `industrial_v2_sft` 注册到上述训练入口 |
| `configs/industrial/qwen_industrial_v2_qlora_8gb.yaml` | Qwen2.5-3B，4 bit QLoRA，rank 8，4 epoch，cutoff 1024 |
| `05_finetune/output/sequence_length_check.json` | 实际训练框架最大 632 token，无截断 |
| `05_finetune/output/` 中三个统计链接 | 指向 `results/industrial_v2/` 的训练结果、日志和适配器配置 |
| `outputs/industrial/qwen2.5-3b-industrial-v2-lora/` | YAML 指定的实际适配器、检查点和完整训练日志；权重不提交 |

本机 RTX 5060 Ti 8GB，68 次更新，训练耗时 258.08 秒。训练 loss 下降仅说明拟合训练目标，需要留出集评估诊断能力。

## 6. 留出集推断与评估：06_evaluation

| 输入／输出 | 用途 |
| --- | --- |
| `06_evaluation/input/validation_inputs.jsonl`、`test_inputs.jsonl` | 纯观测输入，推断脚本只读取这类数据 |
| `06_evaluation/input/validation_labels.jsonl`、`test_labels.jsonl` | 独立参考标签，仅评估脚本读取 |
| `06_evaluation/output/*predictions*.jsonl` | 学生真实预测；自定义新文件名避免覆盖 |
| `06_evaluation/output/*metrics*.json` | 全类／确定性三类准确率、Macro-F1、格式与数值检查 |
| `06_evaluation/output/validation_error_analysis.json` | 错误分析和规则参考，不是学生的规则推断成绩 |

`industrial_predict.py` 默认匹配 Alpaca 训练消息布局，加载 v2 适配器；`industrial_evaluate.py` 与独立标签核对，未识别标签计错。示例使用新的输出名，避免覆盖已有三种协议的记录：

```bash
python -m scripts.industrial.industrial_predict \
  --data-dir data/industrial_v2 --split validation \
  --out data/industrial_v2/06_evaluation/output/validation_predictions_rerun.jsonl
python -m scripts.industrial.industrial_evaluate \
  --data-dir data/industrial_v2 --split validation \
  --predictions data/industrial_v2/06_evaluation/output/validation_predictions_rerun.jsonl \
  --summary-json data/industrial_v2/06_evaluation/output/validation_metrics_rerun.json
python -m scripts.industrial.industrial_evaluate \
  --data-dir data/industrial_v2 --split validation --deterministic-only \
  --predictions data/industrial_v2/06_evaluation/output/validation_predictions_rerun.jsonl \
  --summary-json data/industrial_v2/06_evaluation/output/validation_metrics_rerun_three_classes.json
```

当前保存了首版、仅修正标签解析、对齐消息格式三种验证记录。对齐后 11／31（35.5%），三类子集 11／27（40.7%），Macro-F1 分别 0.131／0.193；全部预测 HDF，等于多数类基线。31 份报告均存在已列出的派生量数值错误。测试集 61 条保持未用，方案确定后再运行最终测试。

## 历史产物与其他任务

v1 的 50 条样本及其 35／5／10 实验保留在 `data/industrial_v1/`，路径管理兼容旧布局。早期模板自检权重在 `outputs/legacy_smoke/`，GNSS 工作在 `scripts/gnss/`、`data/gnss_pilot_v1/`；本次只整理工业 v2 数据。
