# 工业故障分析：五步流程与文件说明

当前只维护一套工业流程，数据位于 `data/industrial/`。流程为：**数据预处理 → 教师生成 → 报告审阅 → 学生微调 → 推断评估**。前两项“原始数据准备”和“集合划分”已经合并为数据预处理。

当前实验：306 条单故障事件，训练／验证／测试为 214／31／61；214 条教师报告审阅后保留 134 条；学生已完成 4 轮训练。验证准确率 35.5%，全部预测多数类 HDF，尚未超过多数类基线。测试集尚未运行。

所有命令在项目根目录执行。本机 `/home/wzb/GNSS_LLM`，教师服务器 `/data/zbwang/GNSS_LLM`。

## 程序入口

| 文件 | 具体作用 |
| --- | --- |
| `scripts/industrial/preprocess_data.py` | 数据预处理：读取原 CSV、筛选单故障、构造字段、划分训练／验证／测试，分离模型输入与标签 |
| `scripts/industrial/generate_teacher_reports.py` | 调用教师 API 生成报告，逐条保存，支持断点续跑和请求失败重试 |
| `scripts/industrial/review_teacher_reports.py` | 一次完成格式／数值／规则检查、文字断言验算、争议裁定和正式训练数据导出 |
| `configs/industrial/student_qlora_8gb.yaml` | 学生 QLoRA 训练配置，交给 LLaMA-Factory 执行 |
| `scripts/industrial/evaluate_student.py` | 同一个入口完成学生推断及评分，合并保存全类别与三类指标 |
| `scripts/industrial/common.py` | 共用路径、标签、任务指令、公开派生量和报告结构检查函数，无独立业务流程 |
| `scripts/industrial/check_workflow.py` | 唯一一致性检查入口；临时重现预处理、审阅、评分，不加载模型，不留下测试文件 |
| `scripts/common/check_runtime.py` | 检查训练 Python、PyTorch、CUDA 和 GPU 是否可用 |
| `scripts/server/start_teacher_server.sh` | 启动服务器教师模型 API |

旧抽样、旧划分、扩充、重试合并、迁移、基础打包等脚本已经移除；当前入口不导入旧代码。历史实验通过 Git 查看。

## 文件组织规则

```text
data/industrial/
├── 01_preprocess/{input,output}/    数据预处理
├── 02_teacher/{input,output}/       教师报告生成
├── 03_review/{input,output}/        报告审阅
├── 04_finetune/{input,output}/      学生微调
└── 05_evaluation/{input,output}/    推断与评估
```

每个输出只保存在所属步骤。下游 `input/` 使用相对符号链接引用上游输出，不再复制数据。不为每个子目录重复生成 README。模型大权重按 YAML 的 `output_dir` 保存，小型训练统计直接放第四步 output，不再单独维护重复的 results 目录。

## 1. 数据预处理：01_preprocess

唯一业务入口：`preprocess_data.py`。这一步同时完成筛选和集合划分。

| 位置 | 文件 | 用途 |
| --- | --- | --- |
| `input/` | `raw_ai4i2020.csv` | 唯一原始 CSV：10,000 行，含 339 条总故障标记 |
| `input/` | `split_assignments.json` | 当前 306 条事件的原 CSV UDI → 集合固定对应表，含 CSV 哈希和种子 |
| `output/` | `train_meta.json` | 214 条内部训练事件，含真实标签，不能直接作为模型请求 |
| `output/` | `validation_inputs.jsonl`、`test_inputs.jsonl` | 31／61 条不带答案的模型输入 |
| `output/` | `validation_labels.jsonl`、`test_labels.jsonl` | 独立参考标签，仅供评分 |
| `output/` | `source_provenance.jsonl` | 事件 ID → 原始 UDI、产品 ID、集合的来源记录 |
| `output/` | `manifest.json` | 样本量、类别数、种子、原 CSV 哈希、划分方式和限制 |

保留条件为 `Machine failure=1` 且只命中一种故障子类，共 306 行：PWF 80、HDF 106、OSF 78、TWF 42。正常行、多故障行和无子类故障行不纳入当前任务。AI4I 是合成数据，运行模式和车间区域是本项目额外生成的随机背景。

当前划分已固化为独立输入表，重现时不再读取任何旧版本数据。所有物理输入唯一且不跨集合；这不是按生产批次或时间的留出验证。

当前目录已有实验结果，重现请指定新的目录：

```bash
python -m scripts.industrial.preprocess_data --out-dir /tmp/industrial_reproduce
```

默认使用种子 42 和固定表，精确重现当前划分与模拟上下文。确需新随机划分时使用 `--new-split --seed 43` 并指定新输出目录；新目录还需独立的训练注册和输出配置。脚本不会覆盖已有目录，也不生成教师报告或启动训练。

## 2. 教师报告生成：02_teacher

| 位置 | 文件 | 用途 |
| --- | --- | --- |
| `input/` | `train_meta.json` | 指向预处理输出；构造请求时剥离真实标签、案例类型与来源 |
| `output/` | `teacher_responses.jsonl` | 唯一教师报告原文，当前 214 条，每条含事件 ID、模型名和回复 |

```bash
# 在 GPU 服务器项目根目录，服务未启动时执行：
bash scripts/server/start_teacher_server.sh
# 另开终端：
python -m scripts.industrial.generate_teacher_reports --dry-run
python -m scripts.industrial.generate_teacher_reports --workers 4
```

教师是 Qwen2.5-32B-Instruct，经 vLLM 本机 API 调用。请求不含真实答案，但提供公开规则、程序计算的温差、轴功率、磨损负荷及规则检查，因此属于规则辅助报告生成。`<think>` 是公开的简短分析依据，不是模型内部思考。

不再生成无人使用的手工提示词文本、重复的 teacher_raw 汇总或独立重试合并文件。模型请求失败由本脚本重试；断点续跑跳过已有事件。更换教师或修改报告时使用独立实验目录。

## 3. 报告审阅：03_review

| 位置 | 文件 | 用途 |
| --- | --- | --- |
| `input/` | `train_meta.json`、`teacher_responses.jsonl` | 上游元数据与教师原文链接 |
| `input/` | `review_overrides.jsonl` | 阅读争议报告后追加的逐事件裁定 |
| `output/` | `report_audit.jsonl` | 初步检查、提取的比较原句和验算结果；用原文 SHA-256 关联报告，不复制全文 |
| `output/` | `final_review_decisions.jsonl` | 综合保守文本检查与争议裁定后的最终接受／拒绝／不确定及原因 |
| `output/` | `review_summary.json` | 最终数量、方法和限制 |
| `output/` | `train_sft.jsonl` | 唯一正式训练文件，134 条 Alpaca 样本，字段为 instruction／input／output |

```bash
python -m scripts.industrial.review_teacher_reports --workers 4
# 当前验算日志已经齐全，可完全离线重现：
python -m scripts.industrial.review_teacher_reports --offline
```

脚本先核对 ID、结构、标签、测量字段和公开规则，再让同一教师服务的另一次请求提取原文断言，由 Python 验算大小比较与规则说法。最后应用保守内容过滤和争议裁定，一次导出最终数据。提取器可能误读或漏检，不是外部独立专家评审。

最终接受 134、拒绝 50、不确定 30。50 条拒绝包含格式、数值、比较、证据问题与保守筛选，并非每条类别结论都错误。30 条 TWF 含随机机制，当前观测不能确认实际故障，保留原报告但不进入确定标签训练。接受的三类为 PWF 36、HDF 56、OSF 42。

## 4. 学生微调：04_finetune

| 位置 | 文件 | 用途 |
| --- | --- | --- |
| `input/` | `train_sft.jsonl` | 第三步的唯一训练文件链接 |
| `output/` | `sequence_length_check.json` | token 长度核查，实际训练框架最长 632，cutoff 1024，无截断 |
| `output/` | `train_results.json` | 已完成训练的平均 loss、耗时等统计 |
| `output/` | `trainer_log.jsonl` | 训练步数与 loss 记录 |
| `output/` | `adapter_config.json` | 已训练 LoRA 的小型配置记录 |

`data/dataset_info.json` 中唯一工业注册名为 `industrial_sft`，指向第四步输入。配置文件为 `configs/industrial/student_qlora_8gb.yaml`。

```bash
conda activate gnss-intent
python -m scripts.common.check_runtime
llamafactory-cli train configs/industrial/student_qlora_8gb.yaml
```

当前 4 轮训练已完成，68 次更新，耗时 258.08 秒，无需因清理重新训练。基础模型 Qwen2.5-3B、4 bit QLoRA、rank 8、学习率 1.5e-4、batch 1、梯度累积 8。当前实际适配器在 `outputs/industrial/qwen2.5-3b-industrial-v2-lora/`；这是已完成训练的路径标识，配置与推断继续指向同一份权重。权重不提交 Git。

## 5. 学生推断与评估：05_evaluation

| 位置 | 文件 | 用途 |
| --- | --- | --- |
| `input/` | `validation_inputs.jsonl`、`test_inputs.jsonl` | 上游纯输入链接，推断只读这些观测 |
| `input/` | `validation_labels.jsonl`、`test_labels.jsonl` | 上游参考标签链接，只有评分读取 |
| `output/` | `validation_predictions.jsonl` | 当前与训练消息格式对齐的 31 条学生预测 |
| `output/` | `validation_metrics.json` | 一份文件保存推断参数、预测哈希、全类别与可观测三类指标及多数类基线 |

同一脚本通过 `--mode` 选择完整运行、仅推断或仅评分，不再维护两套入口。当前默认行为是仅评分，不需要 GPU：

```bash
python -m scripts.industrial.evaluate_student --mode score --split validation
# 新推断使用独立文件名，避免覆盖当前实验：
python -m scripts.industrial.evaluate_student --mode run --split validation \
  --predictions data/industrial/05_evaluation/output/validation_predictions_rerun.jsonl
```

`run` 会生成预测并评分，`predict` 只生成预测，`score` 只评分。全类别和 HDF/PWF/OSF 三类子集同时报告；未识别标签按错误计。原始数值引用完整不代表派生量计算正确，两者分别统计。

当前全类别 11/31（35.5%），Macro-F1 0.131；三类 11/27（40.7%），Macro-F1 0.193。全部预测 HDF，等于多数类基线；31 份报告均有已列出的派生量计算错误。训练 loss 下降未转化为有效分类和计算能力。首轮还发现训练／推断消息位置不一致与中文标签解析遗漏，现已统一；错误协议的历史文件从主目录移除，可通过 Git 查询。

教师有程序派生量辅助，学生当前只有原始测量；134 条长报告训练不足以教会稳定计算与分类。下一轮应比较“短类别目标”和“报告目标”，并明确是否统一提供派生量。测试集 61 条待方案确定后再用于最终评估。

## 日常检查与历史回溯

```bash
python -m scripts.industrial.check_workflow
```

这一条命令检查链接、数据泄漏、重复输入、预处理重现、审阅重现和当前指标重算。只使用临时目录，不调用模型，不生成额外测试文件。

清理前的完整六阶段目录、旧版代码和历史试验在 Git 提交 `6f76e47` 中。可用 `git show 6f76e47:路径` 查看，当前工作树只保留主流程。GNSS 是独立研究方向，仍在 `scripts/gnss/` 与 `data/gnss_pilot_v1/`，本次工业清理不改动它。
