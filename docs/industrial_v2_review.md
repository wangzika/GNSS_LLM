# 工业故障全量扩充与报告审阅

本批使用原始 AI4I CSV 中全部 306 条“Machine failure=1 且只命中一种故障”的独立事件。原有 50 条未被覆盖，v2 保留它们的训练／验证／测试归属。新版划分为训练 214、验证 31、测试 61。

214 条训练报告已全部生成并完成本轮审阅：接受 134、拒绝 50、不确定 30。最终训练文件的三类分布为电力异常 36、散热失效 56、机械过载 42。所有报告和结果已传回本地。已用 LLaMA-Factory 实际训练模板和处理器检查，134 条序列最长 632 token，当前 1024 上限内且没有截断；此前保存的 tokenizer 对话模板估算为 616 token。记录见 `sequence_length_check.json`，本地模型加载和单批前向／反向验证见 `logs/industrial_v2_preflight.json`。

| 类别 | 全部事件 | 训练 | 验证 | 测试 |
| --- | ---: | ---: | ---: | ---: |
| 电力异常 PWF | 80 | 56 | 8 | 16 |
| 散热失效 HDF | 106 | 74 | 11 | 21 |
| 机械过载 OSF | 78 | 54 | 8 | 16 |
| 工具磨损 TWF | 42 | 30 | 4 | 8 |

运行模式和车间区域仍是随机背景。全部物理输入唯一，训练、验证和测试之间无同一物理输入交叉；这只是独立行划分，没有证明按生产批次或时间泛化。

## 审阅方法

1. 核对原始测量键值、派生量、源标签与可重算规则。
2. 检查事件 ID、报告结构、结论及缺失／冲突上下文说明。
3. 从原文提取大小比较和规则触发说法，由程序重新计算真假；模型提取可能漏检或误读，不能把模型评语当作事实。
4. 代理阅读分析段，记录遗漏的错误或歧义；对无依据排除独立随机故障的报告保守剔除。
5. TWF 只能确认风险窗口，不能确认随机故障实际发生。训练中的 30 条保留报告但不进入确定故障标签的 clean 文件。公开规则与原标注在边界处不一致的样本也单列剔除，不改写标注。

使用同一个教师服务的另一次请求做文字提取，存在相关错误；这不是独立专家评审。干净文件表示通过上述检查的子集，不代表模型已具备真实设备诊断能力。

## 文件与复现

所有文件位于 `data/industrial_v2/`，报告和审阅结果已从服务器同步到本地，关键文件 SHA-256 与源文件一致。

| 文件 | 用途 |
| --- | --- |
| `manifest.json` | 数量、类别、原 CSV 哈希、旧划分保留数量与数据限制 |
| `source_provenance.jsonl` | 事件 ID 到原 CSV UDI、产品 ID、划分的对应，仅用于追溯 |
| `train_meta.json` | 214 条内部训练记录，含标签 |
| `validation_*`、`test_*` | 独立留出集，不交给教师生成训练报告 |
| `teacher_responses.jsonl`、`teacher_raw.txt` | 模型原始回答及顺序汇总 |
| `report_audit_recomputed.jsonl` | 数值、比较句和规则说法验算的逐事件记录 |
| `agent_review_decisions.jsonl` | 代理追加的争议裁定 |
| `final_review_decisions.jsonl`、`REVIEW.md` | 最终逐条接受／拒绝／不确定判定及原因 |
| `audit_summary.json` | 最终训练子集数量和限制 |
| `train_sft_clean.jsonl` | 通过审阅的训练子集；不要求强行凑齐 214 条 |
| `archive/` | 旧审阅方法日志、输出替换前备份 |

从项目根目录执行，扩充脚本要求输出目录不存在，以保护旧数据：

```bash
python -m scripts.industrial.industrial_expand_dataset --out-dir data/industrial_v2
```

在 GPU 服务器项目根目录生成并续跑（当前采用的逐条日志名如下）：

```bash
python -m scripts.industrial.industrial_build_reports \
  --data-dir data/industrial_v2 --workers 6 --attempts 1 \
  --audit-name report_audit_recomputed.jsonl
python -m scripts.industrial.industrial_finalize_review --data-dir data/industrial_v2
```

生成脚本按审阅日志跳过已完成事件。每次原始回答与检查结果都写入日志；最终审阅脚本写出前备份旧输出。不要删除日志后直接重复生成同一批数据。

训练注册名为 `industrial_v2_sft`，配置在 `configs/industrial/qwen_industrial_v2_qlora_8gb.yaml`。本次只扩充并审阅数据，未启动学生训练。

注意：clean 排除 TWF，不应用包含 TWF 的全部留出集准确率冒充三类确定性故障的准确率。评估时应同时报告全类表现、可观测三类子集表现及不确定性，避免只选择容易事件而不披露覆盖率。

## 学生模型验证结果（2026-11-24）

正式 4 轮训练已完成，68 次参数更新，耗时 258.08 秒。原推断脚本把训练中的 user 指令移到 system，且只识别完整英文标签；已改为默认匹配 Alpaca 训练消息布局，同时允许中文类别名。旧布局可用 `--prompt-layout legacy` 复现，旧预测文件保留。

原始评分为 9/31；仅重新提取中文标签后为 11/31。使用同一适配器与对齐的消息格式重跑31条验证事件后，模型全部预测为散热失效，准确率11/31（35.5%），三类子集11/27（40.7%），恰好等于一直预测多数类的基线。全类 Macro-F1为0.131，三类为0.193。31份报告均有至少一个已列出的派生量计算错误，不能据格式完整认为具备诊断能力。

诊断与证据见 `data/industrial_v2/validation_error_analysis.json`；对齐后的预测为 `validation_predictions_aligned.jsonl`，对应统计为 `validation_metrics_aligned.json` 和 `validation_metrics_aligned_three_classes.json`。测试集尚未运行。下一轮应把短类别输出与长报告生成分开比较，并对是否提供程序派生量作明确实验设计；工具辅助的成绩不能冒充纯模型诊断能力。
