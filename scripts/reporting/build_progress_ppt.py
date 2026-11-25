#!/usr/bin/env python3
"""用标准 OOXML 生成七页可编辑实验汇报；数据直接读取本项目实验记录。

运行：python scripts/reporting/build_progress_ppt.py
标准库即可生成文件。制作环境缺少演示文稿服务运行库，采用原生 PPTX 封装。
"""
import json
import sys
import math
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'deliverables/工业故障大模型_流程与首轮实验_20261124.pptx'
sys.path.insert(0, str(ROOT))
from scripts.industrial.workflow_paths import WorkflowPaths
DATA = WorkflowPaths(ROOT/'data/industrial_v2')
FONT = 'Noto Sans CJK SC'
BLUE='1464B8'; DARK='17212C'; MUTED='61758F'; LIGHT='F4F7FB'; BORDER='B8CEE8'; RED='B3353D'
P='http://schemas.openxmlformats.org/presentationml/2006/main'
A='http://schemas.openxmlformats.org/drawingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS=f'xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"'
EMU=9525

def e(v): return str(round(v*EMU))
def x(v): return escape(str(v), {'"':'&quot;'})
def color(v): return f'<a:srgbClr val="{v}"/>'
def fill(v): return '<a:noFill/>' if v is None else f'<a:solidFill>{color(v)}</a:solidFill>'
def run(s,size=22,c=DARK,bold=False):
    return f'<a:r><a:rPr lang="zh-CN" sz="{round(size*75)}" b="{int(bold)}">{fill(c)}<a:latin typeface="{FONT}"/><a:ea typeface="{FONT}"/><a:cs typeface="{FONT}"/></a:rPr><a:t xml:space="preserve">{x(s)}</a:t></a:r>'
def paragraphs(s,size=22,c=DARK,bold=False,align='l'):
    return ''.join(f'<a:p><a:pPr algn="{align}"><a:lnSpc><a:spcPct val="115000"/></a:lnSpc><a:spcAft><a:spcPts val="700"/></a:spcAft></a:pPr>{run(line,size,c,bold)}<a:endParaRPr lang="zh-CN" sz="{round(size*75)}"/></a:p>' for line in s.split('\n'))

class Slide:
    def __init__(self,title,number):
        self.elements=[]; self.id=1; self.rels=[];self.number=number
        self.box(30,22,14,14,BLUE,None)
        self.text(title,58,14,1140,44,32,DARK,True)
        self.line(30,64,1225,64,BORDER,1)
        self.text('工业故障报告蒸馏实验   2026.11.24',55,681,1000,25,14,MUTED)
        self.text(f'{number:02d} / 07',1125,681,100,25,14,MUTED,align='r')
    def next(self):self.id+=1;return self.id
    def text(self,s,l,t,w,h,size=22,c=DARK,bold=False,align='l'):
        sid=self.next()
        self.elements.append(f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="Text {sid}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{e(l)}" y="{e(t)}"/><a:ext cx="{e(w)}" cy="{e(h)}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="t"/><a:lstStyle/>{paragraphs(s,size,c,bold,align)}</p:txBody></p:sp>')
    def box(self,l,t,w,h,bg=LIGHT,stroke=BORDER,rounded=False):
        sid=self.next();geom='roundRect' if rounded else 'rect'
        self.elements.append(f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="Box {sid}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{e(l)}" y="{e(t)}"/><a:ext cx="{e(w)}" cy="{e(h)}"/></a:xfrm><a:prstGeom prst="{geom}"><a:avLst/></a:prstGeom>{fill(bg)}<a:ln w="12700">{fill(stroke)}</a:ln></p:spPr></p:sp>')
    def line(self,x1,y1,x2,y2,c=BLUE,width=2,arrow=False):
        sid=self.next();flipx=' flipH="1"' if x2<x1 else '';flipy=' flipV="1"' if y2<y1 else ''
        self.elements.append(f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{sid}" name="Connector {sid}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr><p:spPr><a:xfrm{flipx}{flipy}><a:off x="{e(min(x1,x2))}" y="{e(min(y1,y2))}"/><a:ext cx="{e(abs(x2-x1))}" cy="{e(abs(y2-y1))}"/></a:xfrm><a:prstGeom prst="line"><a:avLst/></a:prstGeom><a:ln w="{round(width*EMU)}">{fill(c)}'+('<a:tailEnd type="triangle" w="sm" len="sm"/>' if arrow else '')+'</a:ln></p:spPr></p:cxnSp>')
    def card(self,title,body,l,t,w,h=128,size=21):
        self.box(l,t,w,h,rounded=True);self.text(title,l+16,t+12,w-32,37,24,BLUE,True);self.text(body,l+16,t+52,w-32,h-60,size)
    def table(self,rows,l,t,widths,row_h=43,size=20,highlights=None):
        sid=self.next();w=sum(widths);h=len(rows)*row_h;trs=[]
        for i,row in enumerate(rows):
            cells=[]
            for j,value in enumerate(row):
                bg=BLUE if i==0 else (highlights.get(i,'FFFFFF') if highlights else ('F4F7FB' if i%2 else 'FFFFFF'))
                cells.append('<a:tc><a:txBody><a:bodyPr lIns="90000" tIns="55000" rIns="70000" bIns="25000" anchor="ctr"/><a:lstStyle/>'+paragraphs(str(value),size,'FFFFFF' if i==0 else DARK,i==0)+'</a:txBody><a:tcPr marL="90000" marR="70000">'+fill(bg)+'<a:lnB w="6350">'+fill(BORDER)+'</a:lnB></a:tcPr></a:tc>')
            trs.append(f'<a:tr h="{e(row_h)}">'+''.join(cells)+'</a:tr>')
        self.elements.append(f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{sid}" name="Table {sid}"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="{e(l)}" y="{e(t)}"/><a:ext cx="{e(w)}" cy="{e(h)}"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl><a:tblPr firstRow="1" bandRow="1"/><a:tblGrid>'+''.join(f'<a:gridCol w="{e(v)}"/>' for v in widths)+'</a:tblGrid>'+''.join(trs)+'</a:tbl></a:graphicData></a:graphic></p:graphicFrame>')
    def chart(self,l,t,w,h,chart_index):
        sid=self.next();rid=f'rIdChart{chart_index}';self.rels.append((rid,R+'/chart',f'../charts/chart{chart_index}.xml'))
        self.elements.append(f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{sid}" name="Training loss"/><p:cNvGraphicFramePr/><p:nvPr/></p:nvGraphicFramePr><p:xfrm><a:off x="{e(l)}" y="{e(t)}"/><a:ext cx="{e(w)}" cy="{e(h)}"/></p:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" r:id="{rid}"/></a:graphicData></a:graphic></p:graphicFrame>')
    def xml(self):
        return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld {NS}><p:cSld><p:bg><p:bgPr>{fill("FFFFFF")}<a:effectLst/></p:bgPr></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'+''.join(self.elements)+'</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'

def relationships(rows):
    return '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="{rid}" Type="{typ}" Target="{target}"/>' for rid,typ,target in rows)+'</Relationships>'

def load(name):return json.loads(DATA.file(name).read_text())

def make_slides():
    slides=[]; notes=[]
    s=Slide('工业设备故障诊断：整体流程',1)
    cards=[('01 原始数据','AI4I 2020 合成数据\n10,000 条记录',55,135),('02 数据划分','306 条独立单故障事件\n训练 214 / 验证 31 / 测试 61',465,135),('03 教师报告生成','Qwen2.5-32B + 公开规则\n仅对 214 条训练事件生成报告',875,135),('06 留出集评估','原始数值输入学生模型\n独立标签评分与报告数值检查',55,348),('05 QLoRA 微调','Qwen2.5-3B + 4 bit + LoRA\n134 条数据，4 轮训练',465,348),('04 报告审阅与 SFT','逐字段核对、规则验算与代理复核\n134 接受 / 50 拒绝 / 30 不确定',875,348)]
    for title,body,l,t in cards:s.card(title,body,l,t,350,128,20)
    for a,b in [(405,465),(815,875)]:s.line(a,199,b,199,arrow=True)
    s.line(1050,263,1050,348,arrow=True);s.line(875,412,815,412,arrow=True);s.line(465,412,405,412,arrow=True)
    s.text('SFT 样本结构',55,516,1100,36,24,BLUE,True)
    s.table([['instruction','input','output'],['故障分析任务说明','原始测量 JSON，去除真实标签','教师报告、类别结论与证据引用']],55,562,[285,420,465],40,19)
    slides.append(s);notes.append('数据依据：data/industrial_v2/02_split/output/manifest.json、04_review/output/audit_summary.json；训练依据：results/industrial_v2/train_results.json。原图为用户提供版式参考，重建为可编辑对象。当前为公开规则辅助教师报告蒸馏，未证明纯模型诊断有效。')

    s=Slide('数据准备：从 10,000 条记录到 134 条训练样本',2)
    s.text('原始故障记录筛选',55,100,580,36,25,BLUE,True)
    s.table([['原始 CSV','条数','处理方式'],['非故障记录','9,661','当前任务不纳入'],['单一故障','306','保留并独立划分'],['多种故障同时标记','24','不用于唯一类别任务'],['总故障为 1，子类全为 0','9','标记不明，单列排除']],55,151,[285,85,250],43,19)
    s.text('306 条单故障的类别组成',55,403,600,36,24,BLUE,True)
    s.table([['PWF 电力异常','HDF 散热失效','OSF 机械过载','TWF 工具磨损'],['80','106','78','42']],55,450,[155,155,155,155],43,18)
    s.card('独立划分','训练 214，验证 31，测试 61\n保留旧版 50 条的集合归属\n物理输入无重复、无集合交叉',720,126,505,178,22)
    s.card('训练报告审阅','214 份报告完成生成\n接受 134，拒绝 50，不确定 30\nTWF 随机发生，30 条训练事件不入 clean',720,323,505,182,21)
    s.text('输入字段：空气温度、过程温度、转速、扭矩、刀具磨损及产品类别 L/M/H',55,568,1170,33,21)
    s.text('AI4I 本身为合成数据。运行模式与车间区域为额外随机背景，不是现场实测。',55,615,1170,34,19,MUTED)
    slides.append(s);notes.append('来源：UCI AI4I 2020，https://archive.ics.uci.edu/dataset/601/ai4i%2B2020%2Bpredictive%2Bmaintenance%2Bdataset ，DOI 10.24432/C5HS5C，CC BY 4.0。本地 raw_ai4i2020.csv 统计：10,000=9,661+339，339=306+24+9。306=80+106+78+42。manifest.json、source_provenance.jsonl 可追溯原 UDI。134 为当前保守审阅子集，50 拒绝不等于50份类别结论全错。')

    s=Slide('教师分析依据与证据链：规则辅助的报告生成',3)
    s.card('输入与可重算信息','移除真实标签、case_type、data_source\n温差 = 过程温度 − 空气温度\n轴功率 = 扭矩 × 转速 × 2π / 60\n磨损负荷 = 磨损时间 × 扭矩',55,118,570,204,21)
    s.card('Qwen2.5-32B-Instruct','服务器 GPU 1、2，BF16 双卡并行\nvLLM API，最大上下文 4096 token\n原始测量 + 公开阈值 + 规则检查',695,118,530,204,21)
    s.line(625,220,695,220,arrow=True)
    s.table([['公开规则','故障触发条件'],['HDF','温差 < 8.6 K 且转速 < 1380 rpm'],['PWF','轴功率 < 3500 W 或 > 9000 W'],['OSF','磨损负荷 > L/M/H 的 11000/12000/13000'],['TWF','200～240 min 是风险窗口，实际故障含随机性']],55,340,[130,440],45,18)
    s.box(695,340,530,245,rounded=True)
    s.text('真实报告示例：EVT-20261124-0141',712,353,496,35,22,BLUE,True)
    s.text('原值：301.6 K / 310.1 K / 1326 rpm\n扭矩 48.2 Nm，磨损 77 min\n温差 8.5 K < 8.6 K，转速 < 1380 rpm\n结论：散热系统失效故障\n证据链原样列出五项测量值',712,400,496,160,20)
    s.text('报告包含事件 ID、公开的简短排除依据、结论和证据链。真实标签仅用于事后核对。',55,607,1170,58,20,MUTED)
    slides.append(s);notes.append('生成代码：scripts/industrial/industrial_generate_teacher.py 的 SYSTEM、derived_measurements、request_report。审阅：industrial_build_reports.py 和 industrial_finalize_review.py。示例来自 teacher_responses.jsonl 的 EVT-20261124-0141。<think>在本项目指可公开的简短分析依据，不代表获取或验证模型内部思考。教师收到规则检查布尔值，因此其报告不是独立盲诊断能力证据。阈值来自 UCI 数据集公开规则。')

    s=Slide('学生模型微调：3B QLoRA 首轮试验',4)
    s.table([['项目','本轮设置'],['基础模型','Qwen2.5-3B-Instruct'],['量化与适配器','bitsandbytes 4 bit，LoRA r=8 / α=16'],['训练样本','134 条：PWF 36 / HDF 56 / OSF 42'],['批量与更新','每卡 batch=1，梯度累积 8'],['学习率与轮数','1.5×10⁻⁴，cosine，4 个 epoch'],['精度与长度','BF16，checkpointing，cutoff 1024']],55,125,[165,465],52,20)
    s.text('本地 RTX 5060 Ti 8 GB',735,110,470,36,25,BLUE,True)
    s.text('68 次参数更新，训练耗时 4 分 18 秒\n实际训练模板最长 632 token，无截断',735,158,470,80,21)
    s.text('训练损失曲线',735,258,470,33,23,BLUE,True)
    s.chart(714,300,510,278,1)
    s.text('平均训练 loss = 0.5778。损失下降需要结合留出集判断效果。',55,617,1170,38,20,MUTED)
    slides.append(s);notes.append('配置：configs/industrial/qwen_industrial_v2_qlora_8gb.yaml。数据：train_sft_clean.jsonl。训练结果：train_results.json，trainer_log.jsonl。训练耗时258.0767秒，不含模型加载。图表绘制记录到的每5步训练loss（5到65步），不是验证loss。首轮试验包含4个epoch，不是仅第1个epoch。约1497万参数参与训练。632token来自LLaMA-Factory实际处理器。')

    s=Slide('微调后评估：独立输入、标签与报告检查',5)
    s.card('训练集','134 条报告用于更新参数\nloss 衡量对训练目标的拟合',55,125,350,132,21)
    s.card('验证集','31 条独立事件用于调试方案\n三类子集 27 条，TWF 4 条',465,125,350,132,21)
    s.card('测试集','61 条保留到方案确定后使用\n当前尚未执行最终测试',875,125,350,132,21)
    s.text('推断与评分分开执行',55,303,1150,36,25,BLUE,True)
    s.card('纯输入推断','原始 JSON + 训练一致的任务指令\n基础模型 + LoRA 生成类别和报告\n推断阶段不读取真实标签',55,365,540,174,21)
    s.card('独立标签评分','准确率、Macro-F1、每类命中\n报告结构、原始数值引用完整性\n派生量与程序重算结果是否一致',685,365,540,174,21)
    s.line(595,440,685,440,arrow=True)
    s.text('预测：industrial_predict.py       评分：industrial_evaluate.py',55,558,1170,36,21,BLUE)
    s.text('同时报告全类与三类子集。固定输入协议，并与多数类或基础模型基线比较。',55,612,1170,40,20,MUTED)
    slides.append(s);notes.append('代码：scripts/industrial/industrial_predict.py、industrial_evaluate.py。训练的Alpaca转换器将instruction和input拼接到同一user消息，推断已对齐。当前不向学生输入派生量或规则检查。三类子集按真实标签HDF/PWF/OSF筛选，仍有原始标注边界不一致的限制。原始数值引用完整不代表计算和推断正确。测试集没有用于本轮调试。')

    s=Slide('当前结果：格式学会了，故障判别未超过基线',6)
    s.table([['验证协议','全部 31 条准确率','三类 27 条准确率','全类 Macro-F1'],['原始推断与评分','29.0%（9/31）','33.3%（9/27）','0.224'],['仅修正中文标签提取','35.5%（11/31）','40.7%（11/27）','0.241'],['对齐训练消息后重跑','35.5%（11/31）','40.7%（11/27）','0.131']],55,126,[385,270,270,245],53,21,{3:'FFF1F0'})
    s.box(55,389,1170,98,'FFF1F0','E2B6B8',True)
    s.text('对齐输入后，31 条全部预测为“散热系统失效”',75,401,1130,39,28,RED,True)
    s.text('散热失效 11/11；电力异常 0/8；机械过载 0/8；工具磨损 0/4',75,446,1130,32,22)
    s.table([['报告格式','原始数值引用','派生量计算','多数类基线'],['完整 31/31','完整 31/31','存在错误 31/31','始终猜 HDF：35.5%']],55,531,[292,292,293,293],43,21)
    s.text('本轮结果显示模板拟合，尚无可靠的故障判断能力证据。',55,632,1170,32,21,RED)
    slides.append(s);notes.append('各行来自 validation_metrics.json、validation_metrics_three_classes.json、validation_metrics_reparsed.json、validation_metrics_aligned.json、validation_metrics_aligned_three_classes.json。仅标签修正行的三类11/27按同一原始报告与新提取口径计算，不是重新训练的改进。对齐后的31条全部HDF，等于多数类基线，Macro-F1反而降低。派生量错误指每份报告至少一项明确列出的派生量与重算值不符，不表示所有列出的值都错。')

    s=Slide('首轮试验问题与下一轮改进方向',7)
    s.table([['问题','已确认的表现','处理与下一步'],['消息布局不一致','训练用 user 拼接，旧推断把指令放 system','已对齐并同权重重跑'],['标签提取口径不一致','正确中文类别名未计入命中','已规范化，原报告不改写'],['评审与文字检查会误判','模型评语不可靠，否定句可能被误读','保留原文，提取断言后程序验算'],['教师与学生的输入差异','教师有计算和规则结果，学生仅有原始值','下一轮统一提供可复算派生量'],['长报告与小样本监督','134 条长报告拟合格式，分类偏向单一类别','先训练短类别输出，再生成报告']],55,122,[275,450,445],66,19)
    s.box(55,559,1170,88,LIGHT,BORDER,True)
    s.text('下一轮实验约束',72,568,230,34,23,BLUE,True)
    s.text('保留本轮原始输入基线，工具辅助结果单列报告\n继续使用验证集调试，最终测试集保持留出',328,569,870,68,21)
    slides.append(s);notes.append('诊断依据：validation_error_analysis.json，原始与对齐预测JSONL，LLaMA-Factory AlpacaDatasetConverter与推断脚本的消息布局对照。长报告损失可能由格式主导属于待验证解释，尚未做短答案对照实验，不能把它视为已证实的唯一原因。TWF随机性与8.6K边界标注问题已在数据审阅中单列。后续工具辅助方案不得冒充原始输入纯模型能力提升。')
    return slides,notes


def chart_xml(steps,losses):
    def refs(kind,formula,values):
        tag='strRef' if kind=='str' else 'numRef';cache='strCache' if kind=='str' else 'numCache'
        fmt='' if kind=='str' else '<c:formatCode>0.000</c:formatCode>'
        return f'<c:{tag}><c:f>{formula}</c:f><c:{cache}>{fmt}<c:ptCount val="{len(values)}"/>'+''.join(f'<c:pt idx="{i}"><c:v>{x(v)}</c:v></c:pt>' for i,v in enumerate(values))+f'</c:{cache}></c:{tag}>'
    text_style=f'<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="1200"><a:latin typeface="{FONT}"/><a:ea typeface="{FONT}"/></a:defRPr></a:pPr><a:endParaRPr lang="zh-CN"/></a:p></c:txPr>'
    return f'''<?xml version="1.0" encoding="UTF-8"?><c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="{A}" xmlns:r="{R}"><c:lang val="zh-CN"/><c:chart><c:autoTitleDeleted val="1"/><c:plotArea><c:layout/><c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/><c:ser><c:idx val="0"/><c:order val="0"/><c:tx><c:v>训练 loss</c:v></c:tx><c:spPr><a:ln w="28000">{fill(BLUE)}</a:ln></c:spPr><c:marker><c:symbol val="circle"/><c:size val="4"/></c:marker><c:cat>{refs('str',f"'Loss'!$A$2:$A${len(steps)+1}",steps)}</c:cat><c:val>{refs('num',f"'Loss'!$B$2:$B${len(losses)+1}",losses)}</c:val><c:smooth val="0"/></c:ser><c:axId val="100"/><c:axId val="200"/></c:lineChart><c:catAx><c:axId val="100"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="b"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>{text_style}<c:crossAx val="200"/><c:crosses val="autoZero"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/></c:catAx><c:valAx><c:axId val="200"/><c:scaling><c:orientation val="minMax"/><c:max val="2"/><c:min val="0"/></c:scaling><c:delete val="0"/><c:axPos val="l"/><c:majorGridlines/><c:numFmt formatCode="0.0" sourceLinked="0"/><c:majorTickMark val="none"/><c:tickLblPos val="nextTo"/>{text_style}<c:crossAx val="100"/><c:crosses val="autoZero"/><c:crossBetween val="between"/><c:majorUnit val="0.5"/></c:valAx></c:plotArea><c:plotVisOnly val="1"/></c:chart><c:externalData r:id="rId1"><c:autoUpdate val="0"/></c:externalData></c:chartSpace>'''


def xlsx_bytes(steps,losses):
    import io
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels',relationships([('rId1',R+'/officeDocument','xl/workbook.xml')]))
        z.writestr('xl/workbook.xml',f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="{R}"><sheets><sheet name="Loss" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels',relationships([('rId1',R+'/worksheet','worksheets/sheet1.xml')]))
        rows=['<row r="1"><c r="A1" t="inlineStr"><is><t>更新步数</t></is></c><c r="B1" t="inlineStr"><is><t>训练loss</t></is></c></row>']
        rows += [f'<row r="{i}"><c r="A{i}" t="inlineStr"><is><t>{step}</t></is></c><c r="B{i}"><v>{loss}</v></c></row>' for i,(step,loss) in enumerate(zip(steps,losses),2)]
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(rows)+'</sheetData></worksheet>')
    return mem.getvalue()


def main():
    slides,notes=make_slides()
    metrics=ROOT/'results/industrial_v2/trainer_log.jsonl'
    if not metrics.exists():metrics=ROOT/'outputs/industrial/qwen2.5-3b-industrial-v2-lora/trainer_log.jsonl'
    records=[json.loads(s) for s in metrics.read_text().splitlines() if s.strip()]
    records=[r for r in records if 'loss' in r]
    steps=[r['current_steps'] for r in records];losses=[r['loss'] for r in records]
    overrides=[]
    def override(path,ctype):overrides.append(f'<Override PartName="/{path}" ContentType="{ctype}"/>')
    files={}
    files['_rels/.rels']=relationships([('rId1',R+'/officeDocument','ppt/presentation.xml'),('rId2','http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties','docProps/core.xml'),('rId3',R+'/extended-properties','docProps/app.xml')])
    files['ppt/presentation.xml']=f'<p:presentation {NS}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rIdMaster"/></p:sldMasterIdLst><p:notesMasterIdLst><p:notesMasterId r:id="rIdNotesMaster"/></p:notesMasterIdLst><p:sldIdLst>'+''.join(f'<p:sldId id="{255+i}" r:id="rId{i}"/>' for i in range(1,8))+'</p:sldIdLst><p:sldSz cx="12192000" cy="6858000" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>'
    files['ppt/_rels/presentation.xml.rels']=relationships([('rIdMaster',R+'/slideMaster','slideMasters/slideMaster1.xml'),('rIdNotesMaster',R+'/notesMaster','notesMasters/notesMaster1.xml')]+[(f'rId{i}',R+'/slide',f'slides/slide{i}.xml') for i in range(1,8)])
    emptytree='<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/></p:spTree>'
    clrmap='<p:clrMap accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" bg1="lt1" bg2="lt2" folHlink="folHlink" hlink="hlink" tx1="dk1" tx2="dk2"/>'
    files['ppt/slideMasters/slideMaster1.xml']=f'<p:sldMaster {NS}><p:cSld>{emptytree}</p:cSld>{clrmap}<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>'
    files['ppt/slideMasters/_rels/slideMaster1.xml.rels']=relationships([('rId1',R+'/slideLayout','../slideLayouts/slideLayout1.xml'),('rId2',R+'/theme','../theme/theme1.xml')])
    files['ppt/slideLayouts/slideLayout1.xml']=f'<p:sldLayout {NS} type="blank" preserve="1"><p:cSld name="Blank">{emptytree}</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>'
    files['ppt/slideLayouts/_rels/slideLayout1.xml.rels']=relationships([('rId1',R+'/slideMaster','../slideMasters/slideMaster1.xml')])
    theme_colors=''.join(f'<a:{name}>{color(val)}</a:{name}>' for name,val in [('dk1',DARK),('lt1','FFFFFF'),('dk2',MUTED),('lt2',LIGHT),('accent1',BLUE),('accent2',RED),('accent3','32836A'),('accent4','DBA241'),('accent5','7293BA'),('accent6','8C709F'),('hlink',BLUE),('folHlink','7A548D')])
    fontset=f'<a:latin typeface="{FONT}"/><a:ea typeface="{FONT}"/><a:cs typeface="{FONT}"/>'
    files['ppt/theme/theme1.xml']=f'<a:theme xmlns:a="{A}" name="Academic Blue"><a:themeElements><a:clrScheme name="Blue">{theme_colors}</a:clrScheme><a:fontScheme name="Noto CJK"><a:majorFont>{fontset}</a:majorFont><a:minorFont>{fontset}</a:minorFont></a:fontScheme><a:fmtScheme name="Simple"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst>'+''.join('<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>' for _ in range(3))+'</a:lnStyleLst><a:effectStyleLst>'+''.join('<a:effectStyle><a:effectLst/></a:effectStyle>' for _ in range(3))+'</a:effectStyleLst><a:bgFillStyleLst>'+''.join('<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' for _ in range(3))+'</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>'
    files['ppt/notesMasters/notesMaster1.xml']=f'<p:notesMaster {NS}><p:cSld>{emptytree}</p:cSld>{clrmap}<p:notesStyle/></p:notesMaster>'
    files['ppt/notesMasters/_rels/notesMaster1.xml.rels']=relationships([('rId1',R+'/theme','../theme/theme1.xml')])
    for i,(slide,note) in enumerate(zip(slides,notes),1):
        files[f'ppt/slides/slide{i}.xml']=slide.xml()
        files[f'ppt/slides/_rels/slide{i}.xml.rels']=relationships([('rIdLayout',R+'/slideLayout','../slideLayouts/slideLayout1.xml'),('rIdNotes',R+'/notesSlide',f'../notesSlides/notesSlide{i}.xml')]+slide.rels)
        note_shape=f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Notes"/><p:cNvSpPr/><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{paragraphs(note,16)}</p:txBody></p:sp>'
        tree=emptytree.replace('</p:spTree>',note_shape+'</p:spTree>')
        files[f'ppt/notesSlides/notesSlide{i}.xml']=f'<p:notes {NS}><p:cSld>{tree}</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>'
        files[f'ppt/notesSlides/_rels/notesSlide{i}.xml.rels']=relationships([('rId1',R+'/notesMaster','../notesMasters/notesMaster1.xml'),('rId2',R+'/slide',f'../slides/slide{i}.xml')])
        override(f'ppt/slides/slide{i}.xml','application/vnd.openxmlformats-officedocument.presentationml.slide+xml')
        override(f'ppt/notesSlides/notesSlide{i}.xml','application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml')
    files['ppt/charts/chart1.xml']=chart_xml(steps,losses)
    files['ppt/charts/_rels/chart1.xml.rels']=relationships([('rId1',R+'/package','../embeddings/loss.xlsx')])
    files['ppt/embeddings/loss.xlsx']=xlsx_bytes(steps,losses)
    files['docProps/core.xml']='<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>工业设备故障诊断：流程与首轮试验</dc:title><dc:creator>GNSS_LLM Project</dc:creator><dc:description>七页实验汇报。数据截至2026-11-24。</dc:description></cp:coreProperties>'
    files['docProps/app.xml']='<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>GNSS_LLM OOXML Builder</Application><Slides>7</Slides><Notes>7</Notes><PresentationFormat>On-screen Show (16:9)</PresentationFormat></Properties>'
    for path,ct in [('ppt/presentation.xml','presentation.main'),('ppt/slideMasters/slideMaster1.xml','slideMaster'),('ppt/slideLayouts/slideLayout1.xml','slideLayout'),('ppt/notesMasters/notesMaster1.xml','notesMaster')]:override(path,'application/vnd.openxmlformats-officedocument.presentationml.'+ct+'+xml')
    override('ppt/theme/theme1.xml','application/vnd.openxmlformats-officedocument.theme+xml')
    override('ppt/charts/chart1.xml','application/vnd.openxmlformats-officedocument.drawingml.chart+xml')
    override('docProps/core.xml','application/vnd.openxmlformats-package.core-properties+xml')
    override('docProps/app.xml','application/vnd.openxmlformats-officedocument.extended-properties+xml')
    files['[Content_Types].xml']='<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="xlsx" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"/>'+''.join(overrides)+'</Types>'
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(OUT,'w',zipfile.ZIP_DEFLATED) as z:
        for path,content in files.items():z.writestr(path,content)
    print(OUT)

if __name__=='__main__':main()
