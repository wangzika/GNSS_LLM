"""工业流程共用定义：五阶段路径、数据字段、公开规则、报告结构检查。

业务入口在 preprocess_data / generate_teacher_reports / review_teacher_reports /
evaluate_student；本文件只提供共用函数，不运行旧流程或合成测试。
"""
import json
import math
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/industrial"
SOURCE_CSV = DATA / "01_preprocess/input/raw_ai4i2020.csv"
SPLIT_ASSIGNMENTS = DATA / "01_preprocess/input/split_assignments.json"
STAGES = {
    "01_preprocess": "数据预处理",
    "02_teacher": "教师报告生成",
    "03_review": "报告审阅",
    "04_finetune": "学生微调",
    "05_evaluation": "推断与评估",
}
OUTPUTS = {
    "01_preprocess": ["manifest.json", "source_provenance.jsonl", "train_meta.json",
                      "validation_inputs.jsonl", "validation_labels.jsonl",
                      "test_inputs.jsonl", "test_labels.jsonl"],
    "02_teacher": ["teacher_responses.jsonl"],
    "03_review": ["report_audit.jsonl", "final_review_decisions.jsonl",
                  "review_summary.json", "train_sft.jsonl"],
    "04_finetune": ["sequence_length_check.json", "train_results.json",
                    "trainer_log.jsonl", "adapter_config.json"],
}
OWNERS = {name: (stage, "output") for stage, names in OUTPUTS.items() for name in names}
INPUTS = {
    "02_teacher": ["train_meta.json"],
    "03_review": ["train_meta.json", "teacher_responses.jsonl"],
    "04_finetune": ["train_sft.jsonl"],
    "05_evaluation": ["validation_inputs.jsonl", "validation_labels.jsonl",
                      "test_inputs.jsonl", "test_labels.jsonl"],
}


class WorkflowPaths:
    """唯一目录规则；只支持当前五阶段布局，不保留旧版本兼容分支。"""
    def __init__(self, root=DATA):
        self.root = Path(root)

    def output_dir(self, stage):
        if stage not in STAGES:
            raise ValueError(f"未知阶段：{stage}")
        return self.root / stage / "output"

    def file(self, name):
        if Path(name).name != name:
            raise ValueError("文件名不能包含目录")
        if name in OWNERS:
            stage, side = OWNERS[name]
        elif name.startswith(("validation_", "test_")):
            stage, side = "05_evaluation", "output"
        else:
            raise ValueError(f"未登记文件归属：{name}")
        return self.root / stage / side / name

    def input(self, stage, name):
        return self.root / stage / "input" / name

    def initialize(self, source_csv=None, assignments=None):
        for stage in STAGES:
            for side in ("input", "output"):
                (self.root / stage / side).mkdir(parents=True, exist_ok=True)
        for stage, names in INPUTS.items():
            for name in names:
                self.link(self.input(stage, name), self.file(name))
        for name, target in (("raw_ai4i2020.csv", source_csv), ("split_assignments.json", assignments)):
            if target is not None:
                self.link(self.input("01_preprocess", name), Path(target))

    @staticmethod
    def link(link, target):
        if link.absolute() == target.absolute():
            return
        relative = os.path.relpath(target.absolute(), link.parent.absolute())
        if link.is_symlink() and os.readlink(link) == relative:
            return
        if link.exists() or link.is_symlink():
            raise FileExistsError(f"输入路径已被其他文件占用：{link}")
        link.symlink_to(relative)


def model_input(record):
    """剥离标签、案例类型和来源，供教师与学生请求共同使用。"""
    return {key: value for key, value in record.items()
            if key not in {"ground_truth_intent", "case_type", "data_source"}}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


LABELS = {
    'TWF': '工具严重磨损故障 (Tool Wear Failure)',
    'HDF': '散热系统失效故障 (Heat Dissipation Failure)',
    'PWF': '驱动电力异常故障 (Power Failure)',
    'OSF': '机械负载过载故障 (Overstrain Failure)',
    'RNF': '偶发性随机系统故障 (Random Failure)',
}

STUDENT_INSTRUCTION = (
    '你是工业设备故障与态势感知分析员。根据监测特征 JSON 给出简短排除依据和结构化报告；'
    '每个物理测量值须原样引用。缺失上下文时降低置信度并提出补充排查建议。'
)

def derived_measurements(rec):
    """仅从无答案的物理测量值计算公开规则所需的派生量。"""
    features = rec["physical_features"]
    grade = rec["event_meta"]["equipment_grade"]
    gap = round(features["process_temp_k"] - features["air_temp_k"], 3)
    power = features["torque_nm"] * features["rotational_speed_rpm"] * 2 * math.pi / 60
    wear_torque = features["tool_wear_min"] * features["torque_nm"]
    limit = {"L": 11000, "M": 12000, "H": 13000}[grade]
    return {
        "temperature_gap_k": gap,
        "shaft_power_w": round(power, 1),
        "wear_torque_min_nm": round(wear_torque, 1),
        "overstrain_limit_min_nm": limit,
        "rule_checks": {
            "HDF_triggered": gap < 8.6 and features["rotational_speed_rpm"] < 1380,
            "PWF_triggered": power < 3500 or power > 9000,
            "OSF_triggered": wear_torque > limit,
            "TWF_risk_window_only": 200 <= features["tool_wear_min"] <= 240,
        },
    }

NUM_RE = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?(?![\d.])")
# 接受 ```markdown 或不标语言的独立代码块；DOTALL 允许块内跨行。
BLOCK_RE = re.compile(r"```(?:markdown)?[ \t]*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
# 当前报告接口只支持 EVT-日期-四位序号；不适用于 JAM-SYN 等其它编号格式。
ID_RE = re.compile(r"EVT-\d{8}-\d{4}")
# 找到独立的“结论：...”行；允许中英文冒号和最多三级 Markdown 标题前缀。
CONCLUSION_RE = re.compile(r"(?m)^(#{0,3}\s*结论[：:]\s*)(.+?)\s*$")

def canonical_conclusion(value, full_label):
    """仅补齐类别英文名，并保留教师写出的风险或不确定性限定。"""
    chinese_label = full_label.split(" (", 1)[0]
    # 仅接受完整标签或对应中文名，并允许下列原样限定；其它措辞返回 None。
    # 例如“工具严重磨损故障 风险”可补全英文名，但“结论：不确定”不会被强改成标签。
    for base in (full_label, chinese_label):
        for suffix in ("", " 风险", " (不确定)"):
            if value == base + suffix:
                return full_label + suffix
    return None

def numbers(value):
    """递归收集 JSON 数值，返回去重的字符串集合；数字字符串不会被视为数值。"""
    if isinstance(value, dict):
        return {number for child in value.values() for number in numbers(child)}
    if isinstance(value, list):
        return {number for child in value for number in numbers(child)}
    if isinstance(value, bool) or value is None:
        # bool 在 Python 中也是 int 的子类，必须先排除，避免把真假当作测量值。
        return set()
    if isinstance(value, (int, float)):
        # 保留 JSON 表示，如 60 与 60.0 不同；后续核对的是文本引用形式。
        return {json.dumps(value, ensure_ascii=False)}
    return set()

def validate(block, rec):
    """检查单份报告，返回第一个拒绝原因；全部通过则返回 None。"""
    # 报告中必须只出现一次对应事件 ID；引用其它事件或重复当前 ID 都拒绝。
    eid = rec["event_meta"]["event_id"]
    ids = ID_RE.findall(block)
    if ids != [eid]:
        return "事件 ID 缺失、重复或不匹配"
    think = re.search(r"<think>(.*?)</think>", block, re.DOTALL)
    # <think> 在本项目中是公开的简短分析依据，检查至少 30 个字符且包含“排除”。
    # len() 统计字符，不能理解分析内容是否合理；教师提示词的长度要求可能更严格。
    if not think or len(think.group(1).strip()) < 30 or "排除" not in think.group(1):
        return "缺少完整且有排除依据的 <think>"
    report = block[think.end():]
    # 标题、结论、原始数值与缺失上下文说明均在 </think> 后的正文中检查。
    if "### 监测事件意图推理报告" not in report or "### 关键支撑证据链" not in report:
        return "缺少报告标题或证据链标题"
    conclusion = CONCLUSION_RE.search(report)
    full_label = rec["ground_truth_intent"]
    # 用独立元数据中的真实标签做事后核对，只允许类别名称规范化。
    if not conclusion or canonical_conclusion(conclusion.group(2).strip(), full_label) is None:
        return "结论与标注不一致或未写出完整结论"
    evidence = report.split("### 关键支撑证据链", 1)[1]
    # 删除答案、案例类型和来源，得到学生应看到的纯输入。
    clean_input = {k: v for k, v in rec.items() if k not in
                   ("ground_truth_intent", "case_type", "data_source")}
    found_nums = set(NUM_RE.findall(evidence))
    # event_meta 是事件信息，不作为必须引用的测量数字；其余嵌套输入字段均递归检查。
    # 集合差只能发现缺少的数字，不检查数字对应的字段、出现次数或额外编造的数字。
    expected_nums = numbers({k: v for k, v in clean_input.items() if k != "event_meta"})
    missing_nums = sorted(expected_nums - found_nums)
    if missing_nums:
        return f"正文未原样引用测量数值：{missing_nums}"
    if rec["case_type"] == "MISSING_CONTEXT":
        # 缺失上下文时，正文须有补充检查建议，以及可解析的“置信度：60%”之类表述。
        if "置信度" not in report or not any(term in report for term in ("补充", "排查", "复测")):
            return "缺失上下文样本未说明置信度和补充排查"
        confidences = [int(n) for n in re.findall(r"置信度\s*[：:]?\s*(\d{1,3})\s*%", report)]
        # 所有匹配到的置信度都须在 (0,65]；65% 是项目约定，未经概率校准。
        if not confidences or any(not 0 < confidence <= 65 for confidence in confidences):
            return "缺失上下文样本置信度未降至 65% 以下"
    if rec["case_type"] == "CONFLICTING_EVIDENCE" and "物理强证据覆盖环境弱证据" not in block:
        # 冲突样本的固定说明可出现在分析依据或正文中；这里只检查短语存在。
        return "冲突样本未解释证据优先级"
    return None

def normalize_conclusion(block, rec):
    """只补齐已明确写出的中文故障名，不改变教师报告的诊断类别。"""
    full_label = rec["ground_truth_intent"]
    def replace(match):
        value = match.group(2).strip()
        normalized = canonical_conclusion(value, full_label)
        return match.group(1) + (normalized if normalized is not None else value)

    # 仅处理第一条结论行；保留“风险”“(不确定)”等已允许限定及其余报告文本。
    return CONCLUSION_RE.sub(replace, block, count=1)
