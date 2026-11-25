# 教师服务器配置与运行

SSH：`ssh zbwang@172.30.5.103 -p 17253`。项目在 `/data/zbwang/GNSS_LLM`；模型、缓存和教师环境放在 `/data/zbwang`。

## 已配置环境（2026-11-24 记录）

| 项目 | 配置 |
| --- | --- |
| 系统与驱动 | Ubuntu 20.04，NVIDIA 535.183.01 |
| GPU | 8 张 RTX 6000 Ada，每张约 46 GiB；教师使用 GPU 1、2 |
| 教师模型 | `/data/zbwang/models/Qwen2.5-32B-Instruct` |
| 推断环境 | `/data/zbwang/envs/gnss-teacher-vllm` |
| 软件 | Python 3.10、PyTorch 2.5.1+cu121、vLLM 0.7.3、Transformers 4.53.3 |
| 并行与精度 | tensor parallel 2，BF16，上下文最大 4096 token |
| API | `http://127.0.0.1:8000/v1/chat/completions`，本机绑定 |
| Python 头文件 | `/data/zbwang/build/Python-3.10.16`，启动脚本通过 CPATH 提供给 Triton |

固定旧版 vLLM 用于适配现有驱动，环境定义与本地学生微调环境分开维护。参考 [vLLM 0.7.3 GPU 安装说明](https://docs.vllm.ai/en/v0.7.3/getting_started/installation/gpu/)。

## 启动与检查

```bash
cd /data/zbwang/GNSS_LLM
bash scripts/server/start_teacher_server.sh
```

另开终端检查：

```bash
curl -s http://127.0.0.1:8000/v1/models
nvidia-smi
```

可以在 tmux 中启动，既有服务会话名为 `gnss_teacher_server`。服务加载后即使 GPU 利用率为 0，显存仍被模型占用；收到请求后才开始计算。重新启动前先检查已有服务，停止时在对应会话按 Ctrl-C。

## 生成与审阅

```bash
cd /data/zbwang/GNSS_LLM
source /data/zbwang/envs/gnss-teacher-vllm/bin/activate
python -m scripts.industrial.generate_teacher_reports --dry-run
python -m scripts.industrial.generate_teacher_reports --workers 4
python -m scripts.industrial.review_teacher_reports --workers 4
```

输入为 `data/industrial/02_teacher/input/train_meta.json`，原文输出到 `02_teacher/output/teacher_responses.jsonl`。脚本剥离真实标签，逐条保存并支持续跑。当前 214 条报告已经生成，已有完整审阅时可用 `review_teacher_reports --offline` 重现，避免重复请求。

教师接收原始测量、公开规则和程序计算的派生量／触发检查，因此报告属于规则辅助生成。审阅只通过另一次请求提取报告原句，再由程序验算，不将模型评语当作事实。完整五步流程和所有文件用途统一见 [工业故障流程](industrial_fault_workflow.md)。

服务器更新时使用同一仓库提交及新的 `data/industrial/` 布局，保留 `/data/zbwang` 中已有基础模型和环境。
