#!/usr/bin/env python3
"""逐条调用本地 OpenAI 兼容接口，保存工业故障教师报告并支持续跑。

默认读取训练集元数据，但发送给模型的请求会剔除真实标签等内部字段。
脚本只收集原始回答；报告是否合格由 step2_validate_and_pack.py 检查。
"""
import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.industrial.industrial_prepare_workflow import model_input  # 复用“去掉答案字段”的输入转换。
from scripts.industrial.step1_prepare_inputs import LABELS
from scripts.industrial.workflow_paths import WorkflowPaths

# 项目根目录和默认数据目录；命令行参数可覆盖具体输入/输出文件。
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/industrial_v2"

# 所有事件共用的教师指令：列出可选类别，但不提供任何事件的真实答案。
# <think> 在本项目中用于简短、可公开的排除依据；不要把它当成未公开的内部推理。
SYSTEM = (
    "你是工业设备故障分析员。以下是 AI4I 模拟数据，运行模式和车间区域是后加的随机背景，"
    "不能当作故障成因。可选标签的完整写法是：" + "；".join(LABELS.values()) + "。"
    "请使用 AI4I 数据集公开的故障判定规则："
    "HDF：process_temp_k-air_temp_k<8.6 K 且 rotational_speed_rpm<1380；"
    "PWF：轴功率 torque_nm×rotational_speed_rpm×2π/60 小于3500 W或大于9000 W；"
    "OSF：tool_wear_min×torque_nm 超过 equipment_grade 对应阈值 L=11000、M=12000、H=13000 min·Nm。"
    "TWF：刀具磨损在200至240分钟有风险，但是否实际故障含随机性；"
    "RNF：与测量值无关，不能从本输入确定。"
    "优先用确定性规则判定；若只有 TWF 风险，结论可写工具严重磨损故障，但须写明不是确定性证据；"
    "若没有任何规则证据，须明确不确定，不得编造故障原因。"
    "下方派生量和规则检查仅由原始输入计算，不是原始数据集标注；"
    "规则检查的 true/false 已由程序计算，禁止重新猜测或颠倒比较结果。"
    "每个事件只输出一个独立的 markdown 代码块，严格按下面顺序逐行书写，不能改变标题或顺序：\n"
    "```markdown\n事件 ID: <完整ID>\n"
    "<think>至少80个汉字、至少三句，逐项说明触发规则及排除其他规则的数值依据，必须包含‘排除’</think>\n"
    "### 监测事件意图推理报告\n结论：<完整标签>\n"
    "### 关键支撑证据链\n- 五项原始测量值和派生量、阈值\n```\n"
    "证据链原样写出全部五项 physical_features 数值、使用的派生量、判定阈值。"
    "若触发 PWF，明确写 shaft_power_w 是小于3500还是大于9000；"
    "若触发 HDF，明确写温差小于8.6且转速小于1380；"
    "不能只抄正常区间而不说明当前值与边界的比较。"
    "空间上下文缺失时写明置信度不高于65%及补充排查建议；"
    "待机区与物理值矛盾时写明‘物理强证据覆盖环境弱证据’。"
    "如果物理证据不足以区分标签，应明确说明不确定，不能编造证据或强行猜测。"
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


def read_records(path):
    """读取训练元数据，并在调用模型前检查事件 ID 是否唯一。"""
    records = json.loads(path.read_text(encoding="utf-8"))
    ids = [rec["event_meta"]["event_id"] for rec in records]
    if len(ids) != len(set(ids)):
        raise ValueError("元数据含重复事件 ID")
    return records


def read_existing(path, model):
    """读取之前逐条保存的回答，供断点续跑时跳过已完成事件。"""
    saved = {}
    if not path.exists():
        return saved
    with path.open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            # 同一个回复文件只允许一种模型，避免混合不同教师的报告。
            if row.get("model") != model:
                raise ValueError(f"第 {line_no} 行使用其他模型；请换一个 --responses 文件")
            eid = row["event_id"]
            if eid in saved:
                raise ValueError(f"回复文件含重复事件 ID：{eid}")
            saved[eid] = row["response"]
    return saved


def request_report(url, model, rec, timeout, max_tokens, retries):
    """将单条无答案事件发给教师服务，并返回模型生成的原始文本。"""
    eid = rec["event_meta"]["event_id"]
    # model_input 会去掉 ground_truth_intent、case_type 和 data_source。
    payload = json.dumps(model_input(rec), ensure_ascii=False, separators=(",", ":"))
    context = rec.get("spatial_context") or {}
    if context.get("operating_mode") is None or context.get("workshop_zone") is None:
        context_hint = (
            "本事件的空间上下文缺失。请在报告标题之后另写两行："
            "置信度：60%；补充排查建议：复核设备位置、运行模式和传感器读数。"
        )
    elif context.get("workshop_zone") == "Idle_Standby_Bay":
        context_hint = (
            "本事件的待机区是随机背景，不能推翻物理故障证据。"
            "请在报告标题之后原样写出：物理强证据覆盖环境弱证据。"
        )
    else:
        context_hint = ""
    # 请求格式与 vLLM 的 OpenAI 兼容聊天接口一致；一次只处理一个事件。
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content":
             f"请分析事件 {eid}：\n{payload}\n"
             "由上述输入计算的派生量（非标签）：\n"
             f"{json.dumps(derived_measurements(rec), ensure_ascii=False, separators=(',', ':'))}\n"
             f"{context_hint}"},
        ],
        "temperature": 0.2,  # 降低输出的随机性，方便复核和重现格式。
        "max_tokens": max_tokens,  # 限制单条报告最多生成多少 token。
    }, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    # 如果服务要求令牌，从环境变量读取，不把密钥写进脚本或数据文件。
    if os.environ.get("TEACHER_API_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['TEACHER_API_KEY']}"
    # 网络错误或空回复可重试；每次请求失败后稍等再试。
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.load(response)
            # 只取第一个候选回答；此处不判断结论对错。
            text = result["choices"][0]["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("模型返回空文本")
            return text.strip()
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as exc:
            if attempt == retries:
                raise RuntimeError(f"{eid} 请求失败，已重试 {retries} 次：{exc}") from exc
            time.sleep(min(2 ** attempt, 8))


def write_raw(path, records, saved):
    """按元数据顺序重建教师原始报告；缺少的事件不会被伪造或补标签。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    # 先写临时文件再替换，避免重建途中留下半截报告。
    temporary = path.with_name(path.name + ".tmp")
    texts = [saved[rec["event_meta"]["event_id"]] for rec in records
             if rec["event_meta"]["event_id"] in saved]
    temporary.write_text("\n\n".join(texts) + ("\n" if texts else ""), encoding="utf-8")
    temporary.replace(path)


def generate_reports(pending, args):
    """按设定并发请求教师；最多保留两倍并发数的待完成任务。"""
    if args.workers == 1:
        for rec in pending:
            yield rec, request_report(args.url, args.model, rec, args.timeout,
                                      args.max_tokens, args.retries)
        return
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        remaining = iter(pending)
        in_flight = {}

        def fill_queue():
            while len(in_flight) < args.workers * 2:
                rec = next(remaining, None)
                if rec is None:
                    break
                future = executor.submit(request_report, args.url, args.model, rec,
                                         args.timeout, args.max_tokens, args.retries)
                in_flight[future] = rec

        fill_queue()
        while in_flight:
            completed, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in completed:
                rec = in_flight.pop(future)
                yield rec, future.result()
            fill_queue()


def main():
    """解析参数，确认待处理事件，逐条请求教师并保存进度。"""
    parser = argparse.ArgumentParser(description=__doc__)
    # 输入：含标签的内部元数据；输出：逐条回复 JSONL 和汇总后的 Markdown 文本。
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--meta", type=Path)
    parser.add_argument("--responses", type=Path)
    parser.add_argument("--raw", type=Path)
    # 默认连接本机 vLLM；模型名必须与服务加载的模型一致。
    parser.add_argument("--url", default="http://127.0.0.1:8000/v1/chat/completions")
    parser.add_argument("--model", default="Qwen/Qwen2.5-32B-Instruct")
    parser.add_argument("--max-tokens", type=int, default=900)  # 单条回答的 token 上限。
    parser.add_argument("--timeout", type=int, default=180)  # 单次请求超时秒数。
    parser.add_argument("--retries", type=int, default=2)  # 失败后的额外重试次数。
    parser.add_argument("--limit", type=int, help="本次最多新生成多少条，便于先试跑")
    parser.add_argument("--workers", type=int, default=1,
                        help="同时请求教师的事件数；大批量可从 4 开始试，默认 1")
    parser.add_argument("--only-id", action="append", default=[],
                        help="只生成指定事件；可重复使用，适合在独立输出文件中重试被拒绝报告")
    parser.add_argument("--dry-run", action="store_true", help="只检查输入和待处理数量")
    args = parser.parse_args()
    if (args.max_tokens <= 0 or args.timeout <= 0 or args.workers <= 0
            or args.retries < 0 or (args.limit is not None and args.limit <= 0)):
        parser.error("max-tokens/timeout/limit/workers 必须为正数，retries 不能为负")
    layout = WorkflowPaths(args.data_dir)
    args.meta = args.meta or layout.input("03_teacher", "train_meta.json")
    args.responses = args.responses or layout.file("teacher_responses.jsonl")
    args.raw = args.raw or layout.file("teacher_raw.txt")
    records = read_records(args.meta)
    saved = read_existing(args.responses, args.model)
    # 防止把旧实验的回复混入当前训练元数据。
    ids = {rec["event_meta"]["event_id"] for rec in records}
    if set(args.only_id) - ids:
        raise ValueError(f"--only-id 含元数据之外的事件：{sorted(set(args.only_id) - ids)}")
    if set(saved) - ids:
        raise ValueError("已有回复包含当前元数据之外的事件，请换一个 --responses 文件")
    only_ids = set(args.only_id)
    pending = [rec for rec in records
               if rec["event_meta"]["event_id"] not in saved
               and (not only_ids or rec["event_meta"]["event_id"] in only_ids)]
    print(f"总数 {len(records)}；已保存 {len(saved)}；待生成 {len(pending)}")
    # dry-run 只检查数量，不连接模型，也不写文件。
    if args.dry_run:
        return
    # limit 只限制本次新生成的数量；下次运行仍可接着生成余下事件。
    if args.limit is not None:
        pending = pending[:args.limit]
    args.responses.parent.mkdir(parents=True, exist_ok=True)
    with args.responses.open("a", encoding="utf-8") as stream:
        for rec, report in generate_reports(pending, args):
            eid = rec["event_meta"]["event_id"]
            stream.write(json.dumps({"event_id": eid, "model": args.model,
                                     "response": report}, ensure_ascii=False) + "\n")
            # 每完成一条就落盘，服务中断后可从下一条继续。
            stream.flush()
            saved[eid] = report
            print(f"已保存 {eid} ({len(saved)}/{len(records)})")
    # 汇总文件可交给下一步质检；其中可能有格式错误或结论不一致的报告。
    write_raw(args.raw, records, saved)
    print(f"原始报告：{args.raw}；当前 {len(saved)}/{len(records)}，需再运行质检。")


if __name__ == "__main__":
    main()
