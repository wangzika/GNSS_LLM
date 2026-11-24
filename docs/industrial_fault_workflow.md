# 工业故障流程与文件用途

2026-11-24 更新：当前主实验已扩充为 v2（306 条事件，214／31／61 划分），214 条教师报告已完成审阅，保留 134 条训练数据。详见 [新版扩充与审阅](industrial_v2_review.md)。以下保留 v1 流程便于追溯；v1 的 35 条报告重新审阅后保留 20 条，已生成 `train_sft_clean.jsonl`。正式学生微调尚未启动。

命令均在项目根目录执行。服务器根目录为 `/data/zbwang/GNSS_LLM`，生成数据保存在该目录下。

## 1. 从原始 CSV 准备 50 条样本

```bash
python -m scripts.industrial.step1_prepare_inputs --source uci
```

| 文件 | 用途 |
| --- | --- |
| `scripts/industrial/step1_prepare_inputs.py` | 抽取仅命中一个故障类别的样本，补充模拟上下文 |
| `data/industrial_source/raw_ai4i2020.csv` | UCI AI4I 原始 CSV |
| `data/industrial_source/step1_meta_records.json` | 50 条样本，含真实标签，仅用于划分和事后核对 |

AI4I 本身是模拟数据；车间区域和运行模式是额外随机生成的背景。现有 50 条仅覆盖四种故障，不含 RNF。重跑将覆盖抽样元数据；已有实验应保持固定划分。

该脚本不再生成旧版带答案提示词，教师输入统一从下一步获得。

## 2. 划分训练、验证和测试集

```bash
python -m scripts.industrial.industrial_prepare_workflow
```

| 文件 | 用途 |
| --- | --- |
| `scripts/industrial/industrial_prepare_workflow.py` | 按类别分层划分，默认种子 42 |
| `data/industrial_v1/train_meta.json` | 35 条训练事件内部元数据，含标签 |
| `data/industrial_v1/teacher_prompts_blind.txt` | 35 条无答案提示词，供手工调用教师时使用 |
| `data/industrial_v1/validation_inputs.jsonl`、`validation_labels.jsonl` | 5 条验证输入及独立标签 |
| `data/industrial_v1/test_inputs.jsonl`、`test_labels.jsonl` | 10 条测试输入及独立标签 |
| `data/industrial_v1/manifest.json` | 划分种子、数量、类别统计及来源 |

程序生成教师报告时直接读取 `train_meta.json` 并移除标签字段，不解析 `teacher_prompts_blind.txt`。

## 3. 启动教师并生成报告

服务已经运行时直接使用；重启命令及硬件环境见 [教师服务器配置](teacher_server_setup.md)。

```bash
bash scripts/server/start_teacher_server.sh
```

另开终端，在服务器项目根目录执行：

```bash
python -m scripts.industrial.industrial_generate_teacher --dry-run
python -m scripts.industrial.industrial_generate_teacher --workers 4
```

| 文件 | 用途 |
| --- | --- |
| `scripts/server/start_teacher_server.sh` | 在 GPU 1、2 上启动 Qwen2.5-32B 的本机 API |
| `scripts/industrial/industrial_generate_teacher.py` | 生成教师请求、并发调用、逐条落盘及断点续跑 |
| `data/industrial_v1/teacher_responses.jsonl` | 服务器上每条事件的原始模型回答 |
| `data/industrial_v1/teacher_raw.txt` | 按事件顺序汇总的报告，交给质检脚本 |
| `scripts/industrial/industrial_merge_teacher_retries.py` | 先备份，再合并通过质检的重试回答 |

教师请求不提供真实标签，但会加入由输入算出的温差、轴功率、磨损与扭矩乘积和公开规则检查。因此这批报告属于规则辅助生成。刀具磨损故障含随机性，处于风险窗口不等于故障确定发生。

## 4. 自动质检与人工审阅

```bash
python -m scripts.common.step2_validate_and_pack \
  --meta data/industrial_v1/train_meta.json \
  --raw data/industrial_v1/teacher_raw.txt \
  --out data/industrial_v1/train_sft_review.jsonl \
  --forbid-smoke --require-complete
```

`scripts/common/step2_validate_and_pack.py` 核对事件 ID、报告结构、结论类别、测量数值引用和上下文说明。它只补齐已经明确写出的中文类别英文名，并保留风险／不确定性限定，不修正错误诊断。

服务器生成的 `teacher_responses.jsonl`、`teacher_raw.txt`、`train_sft_review.jsonl` 已于 2026-11-24 传回本地并核对哈希，可直接在本地审阅。`train_sft_review.jsonl` 共 35 条；175/175 个原始测量值键值对与输入一致。以上为早期自动格式检查结果。本轮进一步审阅发现比较错误和无依据排除等问题，v1 最终保留 20 条，已生成 `train_sft_clean.jsonl`；详见 `data/industrial_v1/REVIEW.md`。不要再用基础打包命令覆盖已审阅文件，应使用 `industrial_finalize_review.py` 重现最终筛选。

## 5. 微调学生模型

正式训练文件须与训练环境位于同一项目目录。当前待审阅文件已在本地；审阅后生成本地 `train_sft_clean.jsonl` 即可供本机训练使用。

```bash
conda activate gnss-intent
python -m scripts.common.check_runtime
llamafactory-cli train configs/industrial/qwen_industrial_v1_qlora_8gb.yaml
```

| 文件 | 用途 |
| --- | --- |
| `data/dataset_info.json` | 将 `industrial_v1_sft` 映射到正式训练文件及 Alpaca 列 |
| `configs/industrial/qwen_industrial_v1_qlora_8gb.yaml` | Qwen2.5-3B、4 bit QLoRA 的学生训练配置 |
| `outputs/industrial/qwen2.5-3b-industrial-v1-lora/` | 正式训练的目标输出目录，尚未生成 |
| `configs/industrial/qwen_industrial_v1_chat.yaml` | 加载正式适配器的交互推断配置 |

配置的 `cutoff_len: 1024` 沿用早期试验，训练前应使用学生 tokenizer 检查完整输入加报告长度，避免截断证据链。微调配置中的相对路径要求从项目根目录运行。

## 6. 留出集推断与评估

```bash
python -m scripts.industrial.industrial_predict --split validation
python -m scripts.industrial.industrial_evaluate --split validation \
  --predictions data/industrial_v1/validation_predictions.jsonl
python -m scripts.industrial.industrial_predict --split test
python -m scripts.industrial.industrial_evaluate --split test \
  --predictions data/industrial_v1/test_predictions.jsonl
```

`industrial_predict.py` 读取纯输入并加载学生适配器；输出真实预测 JSONL。`industrial_evaluate.py` 读取独立标签，统计准确率、类别命中数及报告证据引用。两步尚未运行，旧空白预测模板已删除。

35／5／10 是流程开发规模，不能据此证明泛化能力。后续扩大数据时应保留独立事件划分、明确来源并完成人工审核。

## 历史产物与 GNSS 工作

早期 0.5B／3B 模板自检权重保存在 `outputs/legacy_smoke/`，仅记录环境通路已跑通。模板自检脚本、重复旧训练配置、旧单样本留出工具和可重新生成的旧产物已删除，详见 [整理清单](project_cleanup_20261124.json)。

GNSS 代码位于 `scripts/gnss/`，临时合成样本在 `data/gnss_pilot_v1/`，训练配置在 `configs/gnss/`。新先导数据与旧扁平 GNSS 格式不同，使用前应阅读该数据目录的说明。
