# 教师模型服务器（172.30.5.103）

## 2026-11-24 实测状态

新增 v2：全部 306 条单故障事件已划分为 214／31／61；214 条训练报告审阅后保留 134 条，已传回本地。v1 的 35/35 仅是早期格式检查，进一步审阅后保留 20 条。详见 [扩充与审阅说明](industrial_v2_review.md)。

- Qwen2.5-32B-Instruct 已在 GPU 1、2 上通过 vLLM 启动；本机 `http://127.0.0.1:8000/v1/models` 返回 200。后台会话为 `gnss_teacher_server`。
- 35 条无标签训练输入已生成 35 条教师原始报告，正式结构与标注质检通过 35/35。`data/industrial_v1/train_sft_review.jsonl` 有 35 个不同事件，训练输入中没有 `ground_truth_intent`。
- 原始回复在 `data/industrial_v1/teacher_responses.jsonl`，汇总在 `teacher_raw.txt`，质检后文件是 `train_sft_review.jsonl`。这些相对路径均位于 `/data/zbwang/GNSS_LLM`。被替换的原版、重试版和并发试验已归档到 `data/industrial_v1/archive/` 便于审计。
- 自动质检仅检查格式、测量值引用、标签和特定上下文要求；训练前仍需人工抽查数值比较与因果表述。工具磨损故障含随机性，风险窗口不能证明故障一定发生。
- 补充逐项核对：35 份报告中的 175/175 个原始测量值键值对均与输入相同；已写出的派生量没有发现数值不一致，部分报告未逐项列出所有可选派生量。

## 已核对的硬件与路径

- 主机：Ubuntu 20.04，NVIDIA 驱动 535.183.01（驱动报告 CUDA 12.2）。
- GPU：8 张 RTX 6000 Ada，每张约 46 GiB；首次配置时 GPU 1、2 空闲。
- 内存：755 GiB；`/data` 剩余约 755 GiB（配置开始时）。
- 项目输入与脚本：`/data/zbwang/GNSS_LLM`。
- 模型权重：`/data/zbwang/models/Qwen2.5-32B-Instruct`。
- 独立推断环境：`/data/zbwang/envs/gnss-teacher-vllm`（Python 3.10、PyTorch 2.5.1+cu121、vLLM 0.7.3、Transformers 4.53.3）。
- Python 3.10 编译头文件：`/data/zbwang/build/Python-3.10.16`。服务器缺少系统级 `Python.h`，启动脚本通过 `CPATH` 让 Triton 使用同版本官方源码的头文件。

使用旧版 CUDA 12.1 vLLM 是为了适配现有 535 驱动；不要在这台服务器直接将该环境升级为要求更高驱动的最新版 vLLM。参考 [vLLM 0.7.3 GPU 安装说明](https://docs.vllm.ai/en/v0.7.3/getting_started/installation/gpu/)。

## 启动与运行

登录 GPU 服务器后：

```bash
cd /data/zbwang/GNSS_LLM
bash scripts/server/start_teacher_server.sh
```

这个命令占用当前终端。它默认让模型在 GPU 1、2 上做双卡并行，且只监听服务器本机的 `127.0.0.1:8000`。另开一个 SSH 终端检查服务并先生成 3 条：

```bash
cd /data/zbwang/GNSS_LLM
curl -s http://127.0.0.1:8000/v1/models
python3 scripts/industrial/industrial_generate_teacher.py --dry-run
python3 scripts/industrial/industrial_generate_teacher.py --limit 3
```

检查 `data/industrial_v1/teacher_responses.jsonl`，确认报告完整、证据引用准确，再运行：

```bash
python3 scripts/industrial/industrial_generate_teacher.py
python3 scripts/common/step2_validate_and_pack.py \
  --meta data/industrial_v1/train_meta.json \
  --raw data/industrial_v1/teacher_raw.txt \
  --out data/industrial_v1/train_sft_review.jsonl --forbid-smoke
```

`teacher_responses.jsonl` 每完成一条就写入；中断后重跑会跳过已保存的事件。`teacher_raw.txt` 是重建的原始报告汇总，仍需质检和人工复核。模型不会收到每条事件的真实标签。质检会拒绝与标注不一致的报告，但不能为了通过质检而把标注送给教师模型。

当前生成脚本会从无标签原始输入计算温差、轴功率、磨损与扭矩乘积，以及公开规则的布尔检查，再把这些结果交给教师写分析报告。检查结果可由输入重新计算，不读取 `ground_truth_intent`。因此这批数据属于**规则辅助的教师报告**，不能作为教师模型独立诊断能力的证据。AI4I 官方还说明 TWF、RNF 含随机机制；这两类的真实发生不能仅凭五项物理特征确定。规则来源：[UCI AI4I 2020 数据集说明](https://archive.ics.uci.edu/dataset/601/ai4i%2B2020%2Bpredictive%2Bmaintenance%2Bdataset)。

对于只漏写英文全称的报告，质检打包时会在已明确写出的中文结论后补全英文类别名，并保留“风险”“不确定”等限定；原始模型回答始终留在 `teacher_responses.jsonl`。待机区证据优先级可写在 `<think>` 或报告正文中。`scripts/industrial/industrial_merge_teacher_retries.py` 只合并通过质检的重试结果，并要求先备份主回复文件。

批量运行时可用 `tmux` 后台执行生成脚本；进度写在 `logs/teacher_generate.log`，逐条原始回答写在 `data/industrial_v1/teacher_responses.jsonl`。全部 35 条生成后，使用 `--require-complete` 进行正式质检：

```bash
python3 scripts/common/step2_validate_and_pack.py \
  --meta data/industrial_v1/train_meta.json \
  --raw data/industrial_v1/teacher_raw.txt \
  --out data/industrial_v1/train_sft_review.jsonl \
  --forbid-smoke --require-complete
```

后续数据量增加时，把同结构的训练元数据放在新的目录，使用独立输出文件，避免与当前 35 条混合。`--workers 4` 允许四条请求同时进入双卡服务，脚本仍逐条落盘并支持续跑；已用 `--workers 2` 的两个事件验证并发和续跑。

```bash
python3 scripts/industrial/industrial_generate_teacher.py \
  --meta data/industrial_v2/train_meta.json \
  --responses data/industrial_v2/teacher_responses.jsonl \
  --raw data/industrial_v2/teacher_raw.txt \
  --workers 4
```

若要后台运行服务，可在 `tmux` 中执行启动脚本，并把日志写到 `logs/teacher_server.log`。停止服务时先确认会话归属，再在对应 `tmux` 会话内按 Ctrl-C。
