# 工业故障教师数据与 GNSS 推断实验

当前主线是 AI4I 工业故障实验：准备样本 → 划分数据 → 教师生成报告 → 质检与审阅 → 学生模型微调 → 留出集评估。

截至 2026-11-24，已扩充到 AI4I 全部 306 条单故障事件，划分为训练 214／验证 31／测试 61。214 条教师报告已生成并完成本轮审阅，保留 134 条训练数据；50 条拒绝，30 条工具磨损样本列为不确定。结果已同步本地，正式学生微调已完成（4 分 18 秒）。当前模型在对齐输入后的验证集上全部预测多数类，35.5% 准确率未超过多数类基线，尚未证明有效故障判断能力。报告采用公开规则辅助生成。

## 目录导航

| 目录 | 内容 |
| --- | --- |
| `scripts/industrial/` | 工业样本准备、划分、教师生成／重试、学生推断和评估 |
| `scripts/common/` | 共用报告质检、训练环境检查 |
| `scripts/server/` | GPU 服务器上的教师 API 启动脚本 |
| `scripts/gnss/` | GNSS 合成先导数据及旧格式适配工具 |
| `configs/industrial/` | 工业学生训练和推断配置 |
| `configs/gnss/` | GNSS 训练配置 |
| `data/industrial_source/` | 原始 AI4I CSV、抽取的 50 条内部元数据 |
| `data/industrial_v1/` | 保留的旧先导实验；35 条报告复核后保留 20 条 |
| `data/industrial_v2/` | 当前主实验，按六阶段 `input/`、`output/` 组织，见[目录说明](data/industrial_v2/README.md) |
| `data/gnss_pilot_v1/` | 尚未经过专家审核的 GNSS 合成先导样本 |
| `outputs/` | 模型训练输出；`legacy_smoke/` 保留早期自检权重 |
| `docs/reference/` | 原始方案文档 |
| `LlamaFactory/` | 已安装的第三方训练框架源码，保留原位置以兼容现有环境 |

今后新增实验数据沿用 `阶段/input/`、`阶段/output/` 规范，路径集中在 `scripts/industrial/workflow_paths.py`；跨阶段输入使用相对链接，避免重复副本。v1 历史目录保持兼容。

## 从这里开始

- [全量扩充与审阅说明](docs/industrial_v2_review.md)
- [新版逐事件审阅结果](data/industrial_v2/04_review/output/REVIEW.md)
- [工业故障流程与文件用途](docs/industrial_fault_workflow.md)
- [教师服务器环境、启动与生成命令](docs/teacher_server_setup.md)
- [GNSS 先导样本说明](data/gnss_pilot_v1/README.md)
- [本次整理的移动与删除清单](docs/project_cleanup_20261124.json)

所有命令从项目根目录执行。Python 脚本支持模块形式，例如：

```bash
python -m scripts.industrial.industrial_generate_teacher --help
python -m scripts.common.step2_validate_and_pack --help
```

服务器项目根目录为 `/data/zbwang/GNSS_LLM`，模型、缓存和推断环境均位于 `/data/zbwang`。教师原始报告、报告汇总和待审阅训练文件已同步至本地 `data/industrial_v1/`，与服务器源文件哈希一致，可在本地审阅。

## 训练环境

本机 Conda 环境名为 `gnss-intent`，基础定义见 `environment.yml`。现有环境通过可编辑安装使用 `LlamaFactory/`；不要直接移动该目录。

```bash
conda activate gnss-intent
python -m scripts.common.check_runtime
```

本轮审阅已完成，当前训练入口为 `data/industrial_v2/05_finetune/input/train_sft_clean.jsonl`（链接到第四步输出，134 条），对应配置 `configs/industrial/qwen_industrial_v2_qlora_8gb.yaml`。配置使用相对路径，可在本机或服务器项目根目录执行；服务器教师推断环境与学生微调环境分开维护。

## 代码、数据与演示文稿发布

GitHub 仓库：https://github.com/wangzika/GNSS_LLM ，分支 `master`。

本次发布包含脚本、配置、原始 AI4I CSV、v1/v2 数据划分、教师报告、审阅记录、134条 SFT 数据、验证预测、实验统计与七页 PPT。数据来源、CC BY 4.0 归属及适用限制见 [数据说明](data/DATASET_CARD.md)。基础模型、LoRA 权重、环境和缓存不提交。

七页汇报保存在 `deliverables/`，每页分别说明整体流程、数据准备、教师证据链、微调、评估、当前结果和首轮问题。可从实验记录重新生成：

```bash
python scripts/reporting/build_progress_ppt.py
```

教师“推理链”在本文档中指公开分析依据和可核对的证据，不代表模型内部思考。当前模型尚未超过多数类基线。

重建本机学生训练环境（现有环境无需重复安装）：

```bash
conda env create -f environment.yml
conda activate gnss-intent
git clone https://github.com/hiyouga/LlamaFactory.git LlamaFactory
git -C LlamaFactory checkout fc4f229430a2bb30cfbf47dd0ce3f37429821804
python -m pip install torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -e ./LlamaFactory
python -m pip install -r requirements-local.txt
```

`docs/reference/` 中原始研究方案文档在本机与服务器保留，未纳入公开发布。Git 忽略的旧审阅归档不会影响当前 clean 文件及逐事件最终裁定的使用。
