"""工业实验统一路径：阶段拥有输出，下游 input 使用相对符号链接复用。

新实验默认使用六阶段目录；已存在的 v1 扁平目录仍可只读/续跑兼容。
所有新产物的归属在此登记，避免各脚本再次往版本根目录堆文件。
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGES = {
    "01_prepare": "原始数据准备",
    "02_split": "训练、验证、测试划分",
    "03_teacher": "教师报告生成",
    "04_review": "报告检查与审阅",
    "05_finetune": "学生微调",
    "06_evaluation": "留出集推断与评估",
}

OUTPUTS = {
    "01_prepare": ["events_meta.json"],
    "02_split": ["manifest.json", "source_provenance.jsonl", "train_meta.json",
                 "validation_meta.json", "validation_inputs.jsonl", "validation_labels.jsonl",
                 "test_meta.json", "test_inputs.jsonl", "test_labels.jsonl",
                 "teacher_prompts_blind.txt"],
    "03_teacher": ["teacher_responses.jsonl", "teacher_raw.txt"],
    "04_review": ["report_audit.jsonl", "report_audit_recomputed.jsonl",
                  "final_review_decisions.jsonl", "audit_summary.json", "local_verification.json",
                  "train_sft_clean.jsonl", "train_sft_review.jsonl", "REVIEW.md"],
    "05_finetune": ["sequence_length_check.json"],
    "06_evaluation": ["validation_error_analysis.json"],
}
OWNERS = {name: (stage, "output") for stage, names in OUTPUTS.items() for name in names}
OWNERS["agent_review_decisions.jsonl"] = ("04_review", "input")

# 输入只指向上游产物，不复制数据；真实标签仅供审阅和评分，不能送入推断模型。
INPUTS = {
    "02_split": ["events_meta.json"],
    "03_teacher": ["train_meta.json", "teacher_prompts_blind.txt"],
    "04_review": ["train_meta.json", "teacher_responses.jsonl", "teacher_raw.txt"],
    "05_finetune": ["train_sft_clean.jsonl"],
    "06_evaluation": ["validation_inputs.jsonl", "validation_labels.jsonl",
                      "test_inputs.jsonl", "test_labels.jsonl"],
}


class WorkflowPaths:
    def __init__(self, root, structured=None):
        self.root = Path(root)
        # 只有已有旧版扁平数据才使用旧布局；新版本一律分阶段。
        self.structured = (not (self.root / "train_meta.json").exists()
                           if structured is None else structured)

    def output_dir(self, stage):
        return self.root / stage / "output" if self.structured else self.root

    def file(self, name):
        """定位归属文件；预测与评分的新文件自动进入第六步 output。"""
        if Path(name).name != name:
            raise ValueError("文件名不能带目录；自定义完整路径请使用脚本的路径参数")
        if not self.structured:
            return self.root / name
        if name in OWNERS:
            stage, side = OWNERS[name]
        elif name.startswith(("validation_", "test_")):
            stage, side = "06_evaluation", "output"
        else:
            raise ValueError(f"未登记的流程文件：{name}；请在 workflow_paths.py 中明确归属")
        return self.root / stage / side / name

    def input(self, stage, name):
        return self.root / stage / "input" / name if self.structured else self.root / name

    def audit(self, name):
        if Path(name).name != name:
            raise ValueError("--audit-name 只接受文件名")
        return self.output_dir("04_review") / name

    @property
    def archive(self):
        return self.output_dir("04_review") / "archive"

    def initialize(self, source_csv=None, legacy_dir=None):
        """准备新阶段目录和相对链接；链接目标允许由后续阶段再生成。"""
        if not self.structured:
            self.root.mkdir(parents=True, exist_ok=True)
            return
        for stage in STAGES:
            for side in ("input", "output"):
                folder = self.root / stage / side
                folder.mkdir(parents=True, exist_ok=True)
                readme = folder / "README.md"
                if not readme.exists():
                    description = ("本阶段消费的输入。上游文件使用相对符号链接，只有一份真实数据。\n"
                                   "请勿编辑或覆盖上游链接；审阅追加裁定文件属于本阶段人工输入。"
                                   if side == "input" else
                                   "本阶段产生的结果。新产物保存在这里；更换实验参数请使用新的版本目录。\n"
                                   "模型权重与完整训练日志仍由训练 YAML 的 output_dir 指定，不提交大权重。")
                    readme.write_text(f"# {stage} {STAGES[stage]}：{side}\n\n{description}\n",
                                      encoding="utf-8")
        for stage, names in INPUTS.items():
            for name in names:
                self.link(self.input(stage, name), self.file(name))
        if source_csv is not None:
            self.link(self.input("01_prepare", "raw_ai4i2020.csv"), Path(source_csv))
        if legacy_dir is not None:
            # 保留旧划分只需这三份文件，不链接整个目录以免引入新版本循环引用。
            for name in ("train_meta.json", "validation_inputs.jsonl", "test_inputs.jsonl"):
                self.link(self.input("01_prepare", "v1_" + name), Path(legacy_dir) / name)
        # 已发布的小型训练统计仍由 results 管理，只在第五步提供入口。
        results = ROOT / "results" / self.root.name
        for name in ("train_results.json", "trainer_log.jsonl", "adapter_config.json"):
            if (results / name).is_file():
                self.link(self.output_dir("05_finetune") / name, results / name)

    @staticmethod
    def link(link, target):
        relative = os.path.relpath(target.absolute(), link.parent.absolute())
        if link.is_symlink() and os.readlink(link) == relative:
            return
        if link.exists() or link.is_symlink():
            raise FileExistsError(f"输入已存在且不是预期链接：{link}")
        link.symlink_to(relative)
