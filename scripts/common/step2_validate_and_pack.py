#!/usr/bin/env python3
"""核对教师报告的格式、真实标签和数值引用，打包为 Alpaca 格式的 JSONL。

输入：--meta 指定带标签元数据，--raw 指定教师生成的 Markdown 报告汇总。
输出：--out 指定待审阅训练文件，每行包含 instruction、input、output。
从项目根目录运行：python -m scripts.common.step2_validate_and_pack

这里的自动检查不能证明诊断推断正确。例如，出现了所有测量数字，并不代表
数字与字段对应正确或大小比较正确；人工仍需审阅因果表述和不确定性。
"""
import argparse
import json
import re
from pathlib import Path

# 本文件位于 scripts/common/，向上两级得到项目根目录，避免依赖运行时工作目录。
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
# 写入学生训练数据 instruction 列的通用指令，不是教师服务的完整系统提示词。
# --domain 只选择这里的指令；不会自动切换输入路径、事件 ID 规则或数据结构。
SYSTEM_PROMPTS = {
    "industrial": (
        "你是工业设备故障与态势感知分析员。根据监测特征 JSON 给出简短排除依据和结构化报告；"
        "每个物理测量值须原样引用。缺失上下文时降低置信度并提出补充排查建议。"
    ),
    "gnss": (
        "你是 GNSS 干扰事件分析员。根据监测特征 JSON 给出简短排除依据和结构化报告；"
        "所有测量数值及频段须原样引用。测向或位置上下文缺失时降低置信度并说明补充观测。"
    ),
}
# 从证据链文本提取整数和小数，按文本形式核对；不支持完整的科学计数法语法。
NUM_RE = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?(?![\d.])")
# 只识别此列表中的 GNSS 频段，前后边界防止从更长名称中截取子串。
BAND_RE = re.compile(r"(?<!\w)(?:L1|L2|L5|B1I|B2I|B3I|E1|E5a|E5b)(?!\w)")
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


def bands(value):
    """递归遍历输入字段值，收集字符串中出现的受支持频段；不检查字典键名。"""
    if isinstance(value, dict):
        return {band for child in value.values() for band in bands(child)}
    if isinstance(value, list):
        return {band for child in value for band in bands(child)}
    if isinstance(value, str):
        return set(BAND_RE.findall(value))
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
    missing_bands = sorted(bands(clean_input) - set(BAND_RE.findall(evidence)))
    if missing_bands:
        return f"正文未原样引用频段：{missing_bands}"
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


def main():
    """读取输入、逐报告质检，在满足完整性要求后写出训练文件。"""
    parser = argparse.ArgumentParser()
    # 默认处理工业训练集；处理其它数据时需显式提供匹配结构的 meta/raw/out。
    parser.add_argument("--meta", type=Path, default=DATA / "industrial_v1/train_meta.json")
    parser.add_argument("--raw", type=Path, default=DATA / "industrial_v1/teacher_raw.txt")
    parser.add_argument("--out", type=Path, default=DATA / "industrial_v1/train_sft_review.jsonl")
    parser.add_argument("--domain", choices=SYSTEM_PROMPTS, default="industrial")
    parser.add_argument("--require-complete", action="store_true",
                        help="所有元数据样本都必须有且仅有一份合格报告")
    parser.add_argument("--forbid-smoke", action="store_true",
                        help="拒绝包含规则模板自检标记的报告")
    args = parser.parse_args()
    # 建立 ID → 记录的索引，后面据此找到每份报告对应的标签和测量值。
    meta = json.loads(args.meta.read_text(encoding="utf-8"))
    meta_map = {rec["event_meta"]["event_id"]: rec for rec in meta}
    if len(meta_map) != len(meta):
        raise ValueError("元数据含重复事件 ID")
    if not args.raw.exists():
        raise SystemExit(f"教师回复文件尚未创建：{args.raw}")
    blocks = BLOCK_RE.findall(args.raw.read_text(encoding="utf-8"))
    # 代码块外的文本不会进入打包数据；没有报告块时直接报错。
    if not blocks:
        raise ValueError("未找到独立的 Markdown 代码块")
    if args.forbid_smoke and any("此文本仅用于脚本通路测试" in block for block in blocks):
        # 识别已知模板自检标记；没有标记也不代表报告一定由模型独立生成。
        raise SystemExit("发现规则模板自检报告，不能作为正式教师数据")
    accepted, seen = [], set()  # accepted 保存合格训练行；seen 记录已遇到的合法事件 ID。
    for idx, block in enumerate(blocks, 1):
        id_match = ID_RE.search(block)
        if not id_match or id_match.group() not in meta_map:
            print(f"[拒绝] 块 {idx}: 无效事件 ID")
            continue
        eid = id_match.group()
        if eid in seen:
            print(f"[拒绝] {eid}: 重复事件 ID")
            continue
        seen.add(eid)
        # ID 在内容检查前登记：同次运行中，首份不合格也不会采用后续重复报告。
        rec = meta_map[eid]
        reason = validate(block, rec)
        if reason:
            print(f"[拒绝] {eid}: {reason}")
            continue
        clean_input = {k: v for k, v in rec.items() if k not in
                       ("ground_truth_intent", "case_type", "data_source")}
        # Alpaca 格式：通用任务指令、无标签输入 JSON 字符串、规范化后的教师报告。
        accepted.append({
            "instruction": SYSTEM_PROMPTS[args.domain],
            "input": json.dumps(clean_input, ensure_ascii=False, separators=(",", ":")),
            "output": normalize_conclusion(block, rec).strip(),
        })
        print(f"[通过] {eid} ({rec['case_type']})")
    if args.require_complete and (len(accepted) != len(meta) or len(blocks) != len(meta)):
        # 要求每个事件恰有一份合格报告；失败发生在写文件前，已有输出不会被本次改写。
        raise SystemExit(f"正式数据未打包：合格 {len(accepted)}/{len(meta)}，报告块 {len(blocks)}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 JSONL：一条训练样本占一行，中文不转义；同名文件在这里会被覆盖。
    # 未启用 require-complete 时，仅写入通过的子集，不会补齐失败或缺失样本。
    with args.out.open("w", encoding="utf-8") as stream:
        for item in accepted:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"合格 {len(accepted)}/{len(blocks)}；输出 {args.out}")
    if not accepted:
        # 没有合格报告时仍写出空文件，并以非零退出码告诉调用方失败。
        raise SystemExit(1)


if __name__ == "__main__":
    # 直接执行或 python -m 时启动；被其它脚本 import 时只提供函数和常量。
    main()
