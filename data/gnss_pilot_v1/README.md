# GNSS 合成先导样本

这是依据项目中的《GNSS干扰意图大模型推理-思路》生成的临时测试数据。正式字段由其他负责人确定后，应增加适配器进行转换。本批数据用于开发教师报告生成、证据检查和微调数据打包流程；未经过领域专家审核，不是实际监测记录或有效意图识别基准。

默认 50 条，五类意图各 10 条，每类均为 7 条标准、2 条缺失上下文、1 条上下文冲突。全体合计 35/10/5。标签是生成剧本的设定，不能视为已经通过观测确认的真实动机。

| 文件 | 用途 |
|---|---|
| `preview_5_cases.json` | 每类一条带注释的标准样本，便于先查看数据 |
| `inputs_only.jsonl` | 50 条纯观测输入，可提供给教师或学生模型 |
| `samples_with_annotations.jsonl` | 相同输入与独立 `annotation` 标注，供审核使用 |
| `teacher_prompts.txt` | 每批 5 条的教师提示词，共 10 批；不提供样本的剧本标签 |
| `manifest.json` | 数量、种子、文档摘要哈希和适用限制 |

## 临时字段约定

沿用文档的 `event_meta`、`physical_features`、`spoofing_features`、`spatial_context`、`temporal_context`、`historical_reference` 六个输入模块。调整如下：

- `physical_features.signals` 逐频段记录中心频率、观测带宽、信号类别和接收端功率。L1、B1I、L2 分开表达，不用单个窄带描述冒充多频段覆盖。
- `received_power_dbm` 表示合成的监测接收机输入功率。各类使用相同采样范围，不能据此估算发射功率或作用范围。这里不运行射频传播仿真。
- `spoofing_features.detection_status` 为 `detected`、`not_detected` 或 `unknown`。未检出不能证明不存在；未检出或未知时，欺骗偏移字段为空。
- 位置使用虚构本地 ENU 坐标，单位米；POI 是虚构场景描述，没有查询真实地图。位置缺失时，同时清除依赖定位的速度、运动状态、轨迹和 POI。
- 时间为虚构 UTC 时间，与意图类别独立采样。复发规律未知，历史记录为 `null`。
- `annotation` 中保存 `scenario_intent`、中文标签、难度类型、合成来源和审核状态。整个 `annotation` 禁止作为学生输入。

## 教师报告生成

打开 `teacher_prompts.txt`，逐批交给教师模型。输出采用 JSON 形式，包含候选判断、简短分析依据、替代解释、字段路径/原值/单位对应的证据及所需补充信息。允许 `inconclusive`；不要求教师强行符合生成剧本。

`certainty` 仅描述证据充分程度，尚未校准成概率。报告生成后需逐字段核对，再交给专家复核关键分歧；当前尚未生成教师报告。

这批数据采用独立的 v1 结构，**不能直接交给旧版 `prepare_gnss_inputs.py` 或 `step2_validate_and_pack.py`**：旧版要求扁平标签、EVT 事件编号和 Markdown 报告。后续应针对字段证据结构增加校验和 SFT 转换器，再注册训练数据。不得把此处 `annotation` 整体串入训练输入。

## 重现

在项目根目录执行：

```bash
conda activate gnss-intent
python scripts/gnss/generate_gnss_pilot.py --count 50 --seed 20261117
```

命令会重写当前输出目录内的生成文件。如需保留版本，传入新的 `--out-dir`。数量需为 50 的正整数倍以保持每类 7:2:1。脚本含频段/中心频率、运动状态/速度、缺失上下文和欺骗字段一致性检查。

这 50 条只用于流程开发。后续训练与测试应按场景母本或独立事件分组；不能把同一套简单模板的随机划分结果作为真实泛化能力证明。
