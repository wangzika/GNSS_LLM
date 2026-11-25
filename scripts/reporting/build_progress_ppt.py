#!/usr/bin/env python3
"""生成五页可编辑流程说明：工作内容、输入输出、目录结构与代码入口。

运行：python scripts/reporting/build_progress_ppt.py
标准库即可生成文件。制作环境缺少演示文稿服务运行库，采用原生 PPTX 封装。
"""
import json
import argparse
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'deliverables/工业故障诊断_五步流程说明_20261125.pptx'

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
    return ''.join(f'<a:p><a:pPr algn="{align}"><a:lnSpc><a:spcPct val="115000"/></a:lnSpc><a:spcAft><a:spcPts val="0"/></a:spcAft></a:pPr>{run(line,size,c,bold)}<a:endParaRPr lang="zh-CN" sz="{round(size*75)}"/></a:p>' for line in s.split('\n'))

class Slide:
    def __init__(self,title,number):
        self.elements=[]; self.id=1; self.rels=[];self.number=number
        self.box(30,22,14,14,BLUE,None)
        self.text(title,58,14,1140,48,36,DARK,True)
        self.line(30,64,1225,64,BORDER,1)
        self.text('工业故障分析流程   2026.11.25',55,681,1000,25,14,MUTED)
        self.text(f'{number:02d} / 05',1125,681,100,25,14,MUTED,align='r')
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
    def tree(self, text, l=650, t=158, w=575, h=390):
        before = len(self.elements)
        self.text(text, l, t, w, h, 21)
        self.elements[before] = self.elements[before].replace(
            f'typeface="{FONT}"', 'typeface="DejaVu Sans Mono"')

    def xml(self):
        return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld {NS}><p:cSld><p:bg><p:bgPr>{fill("FFFFFF")}<a:effectLst/></p:bgPr></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'+''.join(self.elements)+'</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'

def relationships(rows):
    return '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="{rid}" Type="{typ}" Target="{target}"/>' for rid,typ,target in rows)+'</Relationships>'


def make_slides():
    """每个阶段一页，不另加封面；数值读取当前已经保存的实验结果。"""
    data = ROOT / 'data/industrial'
    manifest = json.loads((data/'01_preprocess/output/manifest.json').read_text())
    review = json.loads((data/'03_review/output/review_summary.json').read_text())
    training = json.loads((data/'04_finetune/output/train_results.json').read_text())
    metrics = json.loads((data/'05_evaluation/output/validation_metrics.json').read_text())
    counts = manifest['counts']; states = review['status_counts']
    records = [
        dict(title='01  数据预处理',
             work='筛选单故障记录，构造监测字段\n划分数据后，分开保存输入与标签',
             inputs='AI4I 原始 CSV\n固定划分表 split_assignments.json',
             outputs=f"训练 {counts['train']} 条，验证 {counts['validation']} 条，测试 {counts['test']} 条\n内部元数据、纯输入、标签及来源清单",
             result='10,000 条记录，保留 306 条单故障',
             note='运行模式和车间区域是额外模拟背景',
             tree='01_preprocess/\n├─ input/\n│  ├─ raw_ai4i2020.csv\n│  └─ split_assignments.json\n└─ output/\n   ├─ train_meta.json\n   ├─ validation_*.jsonl\n   ├─ test_*.jsonl\n   ├─ source_provenance.jsonl\n   └─ manifest.json',
             tree_note='validation / test 分别包含 inputs 和 labels 文件',
             code='scripts/industrial/preprocess_data.py',
             command='python -m scripts.industrial.preprocess_data --out-dir <新目录>',
             sources=['scripts/industrial/preprocess_data.py', 'data/industrial/01_preprocess/output/manifest.json'],
             details='原始10,000条，标记总故障339条，筛出单一故障306条。固定源UDI划分表保留214/31/61与模拟上下文。train_meta含真实标签，仅构造请求时剥离。验证和测试纯输入不带标签。两个通配文件组分别代表{validation,test}_{inputs,labels}.jsonl。'),
        dict(title='02  教师报告生成',
             work='移除真实标签，批量调用教师 API\n按事件保存原文，支持断点续跑',
             inputs='214 条训练事件的监测特征\n公开规则及程序计算的派生量',
             outputs='214 条教师原始分析报告\n每条保留事件 ID、模型名和回复',
             result='Qwen2.5-32B，BF16 双卡推断',
             note='教师接收规则辅助，真实标签不进入请求',
             tree='02_teacher/\n├─ input/\n│  └─ train_meta.json\n└─ output/\n   └─ teacher_responses.jsonl',
             tree_note='服务启动：scripts/server/start_teacher_server.sh\ninput 链接到预处理输出',
             code='scripts/industrial/generate_teacher_reports.py',
             command='python -m scripts.industrial.generate_teacher_reports --workers 4',
             sources=['scripts/industrial/generate_teacher_reports.py', 'scripts/server/start_teacher_server.sh', 'docs/teacher_server_setup.md'],
             details='教师服务由scripts/server/start_teacher_server.sh启动，GPU1和2，vLLM本机API。请求剥离ground_truth_intent、case_type、data_source，加入温差、轴功率、磨损负荷和规则触发布尔值。这是规则辅助生成，<think>为公开的简短分析依据，不代表获取内部思考。'),
        dict(title='03  报告审阅',
             work='核对结构、标签、数值和公开规则\n提取比较原句，由程序重新验算',
             inputs='训练元数据与教师原始报告\n原句提取结果及程序重算规则',
             outputs=f"{review['clean_count']} 条正式 SFT 训练样本\n自动判定、验算日志与隔离原因",
             result=f"通过 {states['accept']}，拒绝 {states['reject']}，隔离 {states['uncertain']+states.get('needs_review',0)}",
             note=f"30 条不确定、{states.get('needs_review',0)} 条待审，自动排除",
             tree='03_review/\n├─ input/\n│  ├─ train_meta.json\n│  └─ teacher_responses.jsonl\n└─ output/\n   ├─ report_audit.jsonl\n   ├─ final_review_decisions.jsonl\n   ├─ review_summary.json\n   └─ train_sft.jsonl',
             tree_note='审阅日志用内容哈希关联原文，不再复制报告全文',
             code='scripts/industrial/review_teacher_reports.py',
             command='python -m scripts.industrial.review_teacher_reports --offline',
             sources=['scripts/industrial/review_teacher_reports.py', 'data/industrial/03_review/output/review_summary.json'],
             details='同一教师服务的另一次请求只提取报告原句与比较结构，Python验算，再按通用规则自动判定，没有外部裁定覆盖，不是外部独立专家审阅。无法可靠验证的提取自动隔离为needs_review，不进入训练，也不阻塞批处理。30条随机TWF不纳入确定标签训练。SFT字段instruction/input/output。当前离线参数使用已完整保存的验算，不重新请求模型。'),
        dict(title='04  学生微调',
             work='使用 Qwen2.5-3B 进行监督微调\n4 bit 加载基础模型，仅更新 LoRA',
             inputs=f"当前自动训练输入：{review['clean_count']} 条报告\n已完成首轮：134 条历史筛选样本",
             outputs='训练后的 LoRA 适配器\n训练统计、loss 日志和长度检查',
             result=f"{int(training['epoch'])} 轮训练，68 次更新，约 {training['train_runtime']/60:.1f} 分钟",
             note='新数据尚未重训，注册见 data/dataset_info.json',
             tree='04_finetune/\n├─ input/\n│  └─ train_sft.jsonl\n└─ output/\n   ├─ sequence_length_check.json\n   ├─ train_results.json\n   ├─ trainer_log.jsonl\n   └─ adapter_config.json',
             tree_note='实际权重：outputs/industrial/\nqwen2.5-3b-industrial-v2-lora/',
             code='configs/industrial/student_qlora_8gb.yaml',
             command='llamafactory-cli train configs/industrial/student_qlora_8gb.yaml',
             sources=['configs/industrial/student_qlora_8gb.yaml', 'data/dataset_info.json', 'data/industrial/04_finetune/output/train_results.json', 'data/industrial/04_finetune/output/sequence_length_check.json'],
             details='由LLaMA-Factory读取YAML训练，数据注册名industrial_sft由data/dataset_info.json指向第四步input链接。既有模型使用历史134条训练，当前自动筛选数据尚未重训。本地RTX5060Ti 8GB，batch1累积8，LoRA rank8 alpha16，4epoch68更新，耗时258.0767秒。实际处理器最长632token，无截断。大权重按YAML output_dir写入outputs，不在data中重复存放。'),
        dict(title='05  学生推断与评估',
             work='同一入口生成学生报告并评分\n同时报告全类别与可观测三类表现',
             inputs='验证／测试纯输入与已训练适配器\n评分时另读独立参考标签',
             outputs='学生预测 validation_predictions.jsonl\n合并指标 validation_metrics.json',
             result=f"验证 {metrics['all_classes']['accuracy']:.1%}，三类 {metrics['deterministic_classes']['accuracy']:.1%}",
             note='旧 134 条模型全部预测 HDF，未超多数类基线',
             tree='05_evaluation/\n├─ input/\n│  ├─ validation_inputs.jsonl\n│  ├─ validation_labels.jsonl\n│  ├─ test_inputs.jsonl\n│  └─ test_labels.jsonl\n└─ output/\n   ├─ validation_predictions.jsonl\n   └─ validation_metrics.json',
             tree_note='测试集 61 条尚未运行，当前结果来自 31 条验证事件',
             code='scripts/industrial/evaluate_student.py',
             command='python -m scripts.industrial.evaluate_student --mode score',
             sources=['scripts/industrial/evaluate_student.py', 'data/industrial/05_evaluation/output/validation_metrics.json'],
             details='--mode run生成并评分，predict只生成，score仅重算现有预测无需GPU。指标JSON内含推断参数、文件哈希、全类/三类准确率、Macro-F1、标题/数值引用与派生量错误。全类11/31=35.5% MacroF1=0.131，三类11/27=40.7% MacroF1=0.193。所有31条预测HDF且均有派生量错误，测试61条未运行。')
    ]
    slides, notes = [], []
    for index, item in enumerate(records, 1):
        slide = Slide(item['title'], index)
        slide.text('工作内容',55,108,540,34,24,BLUE,True)
        slide.text(item['work'],55,153,555,73,24)
        slide.text('输入',55,253,540,32,24,BLUE,True)
        slide.text(item['inputs'],55,296,555,73,23)
        slide.text('输出',55,384,540,32,24,BLUE,True)
        slide.text(item['outputs'],55,427,555,73,23)
        slide.text(item['result'],55,517,555,34,25,BLUE,True)
        slide.text(item['note'],55,557,555,32,19,MUTED)
        slide.text('文件结构  data/industrial/ 下',650,108,575,34,23,BLUE,True)
        slide.tree(item['tree'])
        slide.text(item['tree_note'],650,490,575,63,19,MUTED)
        slide.line(55,602,1225,602,BORDER,1)
        slide.text('代码入口',55,615,145,31,22,BLUE,True)
        slide.text(item['code'],205,615,1020,32,24)
        slide.text(item['command'],205,650,1020,24,18,MUTED)
        slides.append(slide)
        notes.append(item['details']+'\n来源：'+ '；'.join(item['sources']) +
                     '。流程依据 docs/industrial_fault_workflow.md。共用定义 scripts/industrial/common.py，统一检查 scripts/industrial/check_workflow.py。')
    return slides, notes

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    slides, notes = make_slides()
    count = len(slides)
    overrides=[]
    def override(path,ctype):overrides.append(f'<Override PartName="/{path}" ContentType="{ctype}"/>')
    files={}
    files['_rels/.rels']=relationships([('rId1',R+'/officeDocument','ppt/presentation.xml'),('rId2','http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties','docProps/core.xml'),('rId3',R+'/extended-properties','docProps/app.xml')])
    files['ppt/presentation.xml']=f'<p:presentation {NS}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rIdMaster"/></p:sldMasterIdLst><p:notesMasterIdLst><p:notesMasterId r:id="rIdNotesMaster"/></p:notesMasterIdLst><p:sldIdLst>'+''.join(f'<p:sldId id="{255+i}" r:id="rId{i}"/>' for i in range(1,count+1))+'</p:sldIdLst><p:sldSz cx="12192000" cy="6858000" type="screen16x9"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>'
    files['ppt/_rels/presentation.xml.rels']=relationships([('rIdMaster',R+'/slideMaster','slideMasters/slideMaster1.xml'),('rIdNotesMaster',R+'/notesMaster','notesMasters/notesMaster1.xml')]+[(f'rId{i}',R+'/slide',f'slides/slide{i}.xml') for i in range(1,count+1)])
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
    files['docProps/core.xml']='<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>工业故障诊断：五步流程说明</dc:title><dc:creator>GNSS_LLM Project</dc:creator><dc:description>五页流程说明，每页包含工作内容、输入输出、目录与代码。2026-11-25。</dc:description></cp:coreProperties>'
    files['docProps/app.xml']='<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>GNSS_LLM OOXML Builder</Application><Slides>5</Slides><Notes>5</Notes><PresentationFormat>On-screen Show (16:9)</PresentationFormat></Properties>'
    for path,ct in [('ppt/presentation.xml','presentation.main'),('ppt/slideMasters/slideMaster1.xml','slideMaster'),('ppt/slideLayouts/slideLayout1.xml','slideLayout'),('ppt/notesMasters/notesMaster1.xml','notesMaster')]:override(path,'application/vnd.openxmlformats-officedocument.presentationml.'+ct+'+xml')
    override('ppt/theme/theme1.xml','application/vnd.openxmlformats-officedocument.theme+xml')
    override('docProps/core.xml','application/vnd.openxmlformats-package.core-properties+xml')
    override('docProps/app.xml','application/vnd.openxmlformats-officedocument.extended-properties+xml')
    files['[Content_Types].xml']='<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="xlsx" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"/>'+''.join(overrides)+'</Types>'
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.out,'w',zipfile.ZIP_DEFLATED) as z:
        for path,content in files.items():z.writestr(path,content)
    print(args.out)


if __name__ == "__main__":
    main()
