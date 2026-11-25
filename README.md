# 工业故障教师数据与 GNSS 推断实验

当前工业主流程：**数据预处理 → 教师生成 → 报告审阅 → 学生微调 → 推断评估**。只维护一套代码与数据；历史版本在 Git 中查看。

AI4I 中 306 条单故障事件划分为训练 214／验证 31／测试 61。教师报告审阅后保留 134 条训练样本，学生已完成 4 轮微调。当前对齐输入后的验证准确率 35.5%，全部预测 HDF，未超过多数类基线；测试集尚未运行。

## 从这里开始

- [工业故障流程、全部文件用途与运行命令](docs/industrial_fault_workflow.md)
- [教师服务器配置](docs/teacher_server_setup.md)
- [数据来源、许可与实验限制](data/DATASET_CARD.md)
- [GNSS 先导样本说明](data/gnss_pilot_v1/README.md)

| 路径 | 用途 |
| --- | --- |
| `scripts/industrial/preprocess_data.py` | CSV 筛选、字段构造与集合划分，合为一次数据预处理 |
| `scripts/industrial/generate_teacher_reports.py` | 教师 API 批量生成与续跑 |
| `scripts/industrial/review_teacher_reports.py` | 统一检查、审阅与 SFT 导出 |
| `scripts/industrial/evaluate_student.py` | 学生推断、全类别／三类评分与合并指标 |
| `scripts/industrial/common.py` | 共用路径、字段与检查函数 |
| `scripts/industrial/check_workflow.py` | 唯一一致性检查入口，不保存测试产物 |
| `configs/industrial/student_qlora_8gb.yaml` | 唯一工业训练配置 |
| `data/industrial/` | 五步流程，每步 `input/`、`output/` |
| `outputs/industrial/` | 实际 LoRA 权重与完整运行日志，不提交 Git |
| `scripts/server/`、`scripts/common/` | 教师服务启动、GPU 环境检查 |
| `scripts/gnss/`、`configs/gnss/` | 独立 GNSS 研究代码与配置 |
| `deliverables/` | 已交付的七页首轮实验汇报，保留当时的流程图 |
| `LlamaFactory/` | 训练框架源码，现有环境通过 editable 安装使用 |

## 常用命令

从项目根目录执行：

```bash
# 不加载模型的一致性检查
python -m scripts.industrial.check_workflow
# 仅检查教师生成进度
python -m scripts.industrial.generate_teacher_reports --dry-run
# 根据现有预测重算两组指标
python -m scripts.industrial.evaluate_student --mode score
# 学生训练（当前首轮已完成，无需重复执行）
conda activate gnss-intent
llamafactory-cli train configs/industrial/student_qlora_8gb.yaml
```

当前正式训练文件是 `data/industrial/03_review/output/train_sft.jsonl`，训练注册名 `industrial_sft` 指向第四步 input 链接。服务器根目录为 `/data/zbwang/GNSS_LLM`，模型和教师环境均位于 `/data/zbwang`。

## 环境与发布

现有训练环境是 `gnss-intent`。重建时：

```bash
conda env create -f environment.yml
conda activate gnss-intent
git clone https://github.com/hiyouga/LlamaFactory.git LlamaFactory
git -C LlamaFactory checkout fc4f229430a2bb30cfbf47dd0ce3f37429821804
python -m pip install torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -e ./LlamaFactory
python -m pip install -r requirements-local.txt
```

GitHub：https://github.com/wangzika/GNSS_LLM ，分支 `master`。代码、公开数据、当前报告、审阅、验证结果和 PPT 提交 Git；模型权重、环境、缓存和原始研究方案 DOCX 不提交。

旧工业版本、重复导出、一次性迁移／自检代码和旧模板自检权重已清理。当前训练适配器保留原位置。清理前文件可从 Git 提交 `6f76e47` 查看；旧模板自检权重属于未纳入 Git 的可重建试验产物，不再保留。
