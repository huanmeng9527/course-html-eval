---
name: "course-html-eval"
description: "课程质量评分 shuku score course html eval. 评估HTML教学页多维度质量(准确性/覆盖度/可学性/学习流等10维), 输出评分+改进建议."
status: active
version: "v2.4.1"
date: "2026-09-27T18:30:00.000Z"
changelog: "v2.4→v2.4.1: 提供 pipeline/ 参考实现（消除实现歧义）/ 定义 llm_overall 并修正 transition_quality 尺度 / 明确 standard=每页3次整页评分+扰动协议 / stuck v2 信号法（v1 实测 92% 页面误报 P0）/ 新增 JS 渲染盲区置信度封顶 / 定义等级分档与报告 schema / 批量汇总报告 / 校准方法学修订"
---

# 课程网页 HTML 质量评估 (v2.4.3)

对教育类课程网页 HTML 做 LLM 多维度质量评分。  
适用：shuku 用户上传的课程内容评估、教学页面质量审核、课程页面自动评分标准建立。

**v2.4 核心改进**：
- 加 **learnability**（可学性）和 **flow**（学习流）2 个新维度 → 解决 v2.3 的"内容设计分高，但真实学不会"问题
- **降低 pedagogy 权重** 0.22 → 0.15 → 用户数据显示 pedagogy 维度 v2.3 严重偏高
- **用户主观评分作 Spearman 校准金标准**（11 模块，CourseMap 剔除）

---

## 10 维评分 Rubric（v2.4）

| 维度 | 含义 | teaching 权重 |
|---|---|---|
| accuracy | 事实准确性 | 0.10 |
| coverage | 知识覆盖度 | 0.10 |
| structure | 结构清晰度 | 0.10 |
| readability | 可读性 | 0.10 |
| a11y | 可访问性 | 0.08 |
| pedagogy | 教学设计 | **0.15** ↓ |
| visualization | 可视化 | 0.06 |
| interaction | 互动性 | 0.06 |
| **learnability** ⭐ | **可学性（普通学生能否独立看懂/做对）** | **0.15** |
| **flow** ⭐ | **学习流（章节顺序、操作链流畅性）** | **0.10** |
| **合计** | | **1.00** |

---

## 三档配置

| 档位 | 独立指标数 | LLM 调用 | 适用 |
|---|---|---|---|
| **lite** | 10 | 1 次/页 | 大批量内容快筛 |
| **standard**（默认）| 14 | 3 次/页 | shuku 用户内容评分 |
| **strict** | 45 | 9 次/页 | 学术 / 极限准确度 |

> **调用口径（v2.4.1 明确）**：档位中的"LLM 调用"指**每页整体评分**的次数；章节切分文本（步骤 5）作为证据注入 prompt，**不逐节独立调用**。逐节模式仅 strict 档选用，节分 → 页分用长度加权平均。3 次评分必须按步骤 6 的扰动协议执行（顺序打乱 + temperature ≥ 0.7），否则自洽校验无效。

---

## 工作流

### 1. 预处理与解析

- 接收输入 + tier 参数
- BeautifulSoup 解析（lxml）
- 移除 script / style / nav / footer

**完成标准**：得到可遍历的 soup 对象。

> **v2.4.1**：步骤 1~5 的规范实现见 `pipeline/extract_features.py`——指标公式以代码为准，本文档只保留含义与阈值，消除"每个评估者实现一套"的复现性问题。

### 2. 结构化特征提取

- 字符数 / 词数 / 段落数 / 章节数（h1/h2/h3）
- **v2.4 新增**：检测 `prerequisites` 标注（前后置概念是否清晰）
- **v2.4 新增**：检测章节间过渡元素（衔接词、"下一步"按钮、回顾链接）
- **v2.2 保留**：检测严格输入元素 / 防卡顿元素（`data-hint` / `data-skip` 等）
- **v2.4.1 新增**：`text_density`（可见字符/原始 KB）、`js_render_ratio`（script 字节占比）、
  `suspected_render_fault` 标记 → 用于步骤 9 的置信度封顶（JS 渲染页静态提取不完整，不能按完整页面扣分）

### 3. 页面类型自动检测

```python
def detect_page_type(features):
    if features["has_nav_layer"] and features["section_count"] <= 2: return "nav"
    if features["canvas_count"] >= 2 and features["form_count"] >= 1: return "tool"
    if features["avg_paragraph_length"] > 200 and features["form_count"] == 0: return "docs"
    return "teaching"
```

> **v2.4.1 兜底**：JS 渲染页往往没有 `<nav>` 标签、canvas 在渲染前也不存在，静态三规则全部落空会误判成 teaching（实测 CourseMap 即此情况）。兜底顺序：① 模块名关键词（`playground|lab|tool → tool`；`map|nav|catalog → nav` 且 section_count ≤ 3）；② 仓库级元数据。实现见 `pipeline/extract_features.py::detect_page_type`——返回值带 `page_type_source`（`static` / `name_fallback`），报告中保留来源标记以便复核。

### 4. 硬规则提取（v2.4.1 精确化：公式以 `pipeline/extract_features.py` 为准）

| 指标 | 精确定义 | 阈值 |
|---|---|---|
| `alt_coverage` | 非空 alt 的 `<img>` / 全部 `<img>`（页面无 img 记 1.0） | < 0.8 → a11y 扣 0.5 |
| `heading_skip` | 标题序列出现 h_n → h_{n+2} 跳级 | 出现 → structure 扣 0.3 |
| `aria_label_rate` | 可访问交互元素（有 aria-label / aria-labelledby / title / 关联 label / 非空文本的 button）÷ button + a[href] + input + select + textarea 总数 | < 0.5 → a11y 扣 0.5 |
| `stuck_likelihood` | **v2 信号法**：R = 风险信号数（硬性门槛 / 无进度长任务 / 无示例开放任务 / 资源加载失败 / ≥3 级深链，各 1 分），M = 缓解机制数（data-hint / data-skip / example 及提示类按钮，上限 8），L = clamp(0.15 + 0.12R − 0.05M, 0, 1) | ≥ 0.25 → 触发 ux_risk_alert（`--stuck-threshold` 可调） |

> **v1 废弃说明**：v1 的 `stuck_likelihood`（文案命中数启发式，阈值 0.7）在 12 模块实测中对 92% 页面误报 P0 告警，失去区分度。v2 改为"风险信号 − 缓解机制"信号法；阈值 0.25 为初始经验值，建议用带标注的真实卡顿数据再校准。

### 5. 章节切分

按 `<section>` / 标题切分语义段，每段 ≤ 800 tokens。

### 6. LLM 多维度评分（**v2.4 严格化 prompt**）

**关键修改**：prompt 增加**反偏差指令**——LLM 默认偏宽松，要求更严格。

**评分口径（v2.4.1 明确）**：standard 档 = 每页整体评 3 次（章节文本作为证据注入 prompt，非逐节调用）；3 次必须按扰动协议执行（文档序 / 倒序 / 按节长度排序，temperature ≥ 0.7）。完整 prompt 模板（含各维度锚点与子项定义）见 `pipeline/llm_prompt.md`。

**评分口径（v2.4.1 明确）**：standard 档 = 每页整体评 3 次（章节文本作为证据注入 prompt，非逐节调用）；3 次必须按扰动协议执行（文档序 / 倒序 / 按节长度排序，temperature ≥ 0.7）。完整 prompt 模板（含各维度锚点与子项定义）见 `pipeline/llm_prompt.md`。

```
你是严格的教育内容评审专家，对**真实学习体验**评分。

⚠️ 反偏差指令：
- 5 分只给真正出色的页面，不要因为"看起来专业"就给 5
- 4 分 = 小修即可发布
- 3 分 = 多处需要修，建议返工
- 2 分以下 = 不适合发布
- 如果页面让你**作为学习者感到困惑、操作卡顿、概念跳跃大**，必须扣分
- 不要美化设计良好的页面

【页面类型】{detected_page_type}
【章节内容】{section_text}

评分 10 维度（每项 1~5）：

1. accuracy      事实准确性
2. coverage      知识覆盖度
3. structure     结构清晰度
4. readability   可读性
5. a11y          可访问性
6. pedagogy      教学设计（先直觉后形式 / 类比 / 循序渐进）
7. visualization 可视化（公式、图表、动图）
8. interaction   互动性
9. learnability  ★ 可学性（普通学生能否独立看懂 / 做对）
   - 5 = 看一遍就懂，操作链顺畅
   - 4 = 大部分能懂，少量卡顿
   - 3 = 需要反复看才能懂，操作链有跳跃
   - 2 = 概念跳跃大，普通学生跟不上
   - 1 = 即使认真读也难懂
10. flow         ★ 学习流（章节顺序、操作链流畅、回头率）
   - 5 = 从头到尾一气呵成，操作链 ≤ 3 步完成
   - 4 = 流畅但偶有小跳跃
   - 3 = 章节顺序合理但操作链偏长
   - 2 = 操作链超过 5 步，章节间过渡突兀
   - 1 = 顺序混乱，回头率高

输出 JSON：
{
  "scores": [
    {"dim":"accuracy","value":4,"evidence":"原文：xxx","confidence":"high|medium|low"},
    ...
  ],
  "llm_overall": 4,
  "interaction_subs": {
    "answer_tolerance": 3, "hint_progression": 2,
    "stuck_detection": 2, "error_feedback": 4
  },
  "learnability_subs": {
    "concept_jumps": 2,
    "operation_chain_length": 4,
    "back_navigation": 3
  },
  "flow_subs": {
    "section_order": 4,
    "transition_quality": 4
  },
  ...
}
```

**interaction 加权（v2.4.1）**：`mean(interaction_subs) × 0.7 + llm_overall × 0.3`
（v2.4 公式引用了 `llm_overall` 但评分 schema 未要求输出——已补进上方 JSON；锚点：5 = 愿意直接交给初学者独立使用，3 = 需陪同指导，1 = 不建议使用）

**子项用途（v2.4.1 明确）**：`learnability_subs` / `flow_subs` 仅作诊断展示与改进建议定位，**不参与维度加权**（interaction 例外：4 子项按 0.7 卷入 interaction 分）。

### 7. Self-Consistency 校验（tier ≥ standard）

3 次评分取均值，标准差 > 1.0 标 `unstable`。

**v2.4.1 补充**：3 次评分必须按步骤 6 的扰动协议执行——同会话零扰动自评的 std 必然偏小，校验形同虚设。判定 unstable 后：剔除离中位数最远的一次取均值，保留 `unstable_fixed` 标记。实现见 `pipeline/aggregate.py::dim_stats`。

### 8. 硬规则叠加

```python
def apply_hard_rules(llm_scores, hard_rules):
    s = llm_scores.copy()
    if hard_rules["alt_coverage"] < 0.8:    s["a11y"] -= 0.5
    if hard_rules["heading_skip"]:          s["structure"] -= 0.3
    if hard_rules["aria_label_rate"] < 0.5: s["a11y"] -= 0.5
    return s
```

### 9. 维度加权与总分

```python
def weighted_total(scores, weights):
    active = {k: w for k, w in weights.items() if scores.get(k) is not None}
    total_w = sum(active.values())
    if total_w == 0: return 0
    return sum(scores[k] * w for k, w in active.items()) / total_w * 20
```

> **v2.4.1 注**：tool 行权重合计 0.98、nav 1.01、docs 1.09，与"合计 1.00"不符——公式按 active 权重归一化，结果不受影响，但表格数字不再声称合计为 1。

**等级分档（v2.4.1 文档化）**：A+ ≥ 95 · A ≥ 90 · A- ≥ 85 · B+ ≥ 80 · B ≥ 75 · B- ≥ 70 · C+ ≥ 65 · C ≥ 60 · D < 60

**置信度封顶（v2.4.1 新增）**：当 `suspected_render_fault = true`（内容疑似 JS 渲染、静态提取不完整）时，coverage / visualization 置信度强制降为 low，且**总分封顶 85**。可用 headless 渲染（`pipeline/extract_features.py --render`，需 playwright）重新提取后解除封顶。`text_density < 60 字符/KB` 时 coverage / visualization 置信度降为 medium。

**证据置信度剔除（v2.4.2 新增）**：评分 LLM 自报的每维证据置信度（high|medium|low）按 3 pass 多数票聚合为 `dim_confidence`，其中 **low 的维度不参与加权**（权重归一化到其余维度），分数仍展示并标 `weighted=false`——防止"没看全"的维度按臆测分拉低总分。无该字段时行为与 v2.4.1 一致。

**评审决策剔除（v2.4.3 新增）**：`aggregate.py --exclude-dims a11y` 可将指定维度移出加权（如用户决策"本评估场景不考虑无障碍"），权重归一化到其余维度；同时 `remap_a11y_improvements()` 将剔除维度下的改进建议按关键词重分类到 readability / learnability / interaction（纯键盘/读屏项标记 `not_tracked`），避免"建议跟着维度一起丢"。报告新增 `decision_excluded_dims` 字段与 `rubric_decisions` 决策块。

### 10. 改进建议生成

```
基于以下评分弱点：
- learnability: 2.5
- flow: 3.0
- interaction 子项 stuck_detection: 1
- ux_risk_alert: P0_high_stuck_risk

请生成 3~5 条改进建议：
{
  "priority": "P0|P1|P2",
  "action": "具体动作",
  "impact_dim": "影响的维度（learnability / flow / interaction / pedagogy）",
  "cost_hours": 实施工时
}

如果 ux_risk_alert=P0，第一条建议必须是缓解卡顿。
```

### 11. 输出报告

```json
{
  "schema_version": "1.1",
  "fingerprint": {"url": "...", "html_sha1": "...", "extracted_at": "2026-09-27T00:00:00Z", "page_type_source": "static"},
  "total_score": 87.5,
  "grade": "A-",
  "page_type": "teaching",
  "dimensions": {
    "accuracy": {"score": 4.2, "weight": 0.10, "confidence": "high"},
    "learnability": {"score": 3.5, "weight": 0.15, "confidence": "high",
                     "subs": {"concept_jumps": 3, "operation_chain_length": 4, "back_navigation": 3}},
    "flow": {"score": 4.0, "weight": 0.10, "confidence": "high",
             "subs": {"section_order": 4, "transition_quality": 4}},
    "interaction": {"score": 3.5, "weight": 0.06, "confidence": "high",
                    "subs": {"answer_tolerance": 3, "hint_progression": 2, "stuck_detection": 2, "error_feedback": 4}}
  },
  "hard_rules": {"alt_coverage": 0.95, "aria_label_rate": 0.40, "heading_skip": false, "stuck_likelihood": 0.27},
  "ux_risk_alert": null,
  "improvements": [...]
}
```

完整字段定义见 `references/report_schema.md`（v2.4.1 新增）。

---

## 🎯 默认权重表（teaching 页面，**v2.4 已更新**）

| 维度 | v2.3 权重 | **v2.4 权重** | Δ | 理由 |
|---|---|---|---|---|
| accuracy | 0.10 | 0.10 | — | 事实正确性 |
| coverage | 0.10 | 0.10 | — | 知识覆盖 |
| structure | 0.15 | 0.10 | -0.05 | 让位给 learnability |
| readability | 0.15 | 0.10 | -0.05 | 让位给 flow |
| a11y | 0.12 | 0.08 | -0.04 | 缩权重 |
| pedagogy | **0.22** | **0.15** | **-0.07** | 用户数据显示 v2.3 严重偏高 |
| visualization | 0.08 | 0.06 | -0.02 | 缩权重 |
| interaction | 0.08 | 0.06 | -0.02 | 拆 4 子项后聚合分已包含细节 |
| **learnability** | — | **0.15** | **+0.15** | **新维度** |
| **flow** | — | **0.10** | **+0.10** | **新维度** |
| **合计** | **1.00** | **1.00** | 0 | — |

---

## 🔄 4 档页面类型的权重切换（**v2.4 已更新**）

| 维度 | teaching | tool | nav | docs |
|---|---|---|---|---|
| accuracy | 0.10 | 0.08 | 0.05 | 0.12 |
| coverage | 0.10 | 0.08 | 0.05 | 0.12 |
| structure | 0.10 | 0.10 | 0.27 | 0.12 |
| readability | 0.10 | 0.08 | 0.15 | 0.18 |
| a11y | 0.08 | 0.08 | 0.10 | 0.10 |
| pedagogy | **0.15** ↓ | 0.05 | 0.02 | 0.15 |
| visualization | 0.06 | **0.13** | 0.08 | 0.03 |
| interaction | 0.06 | **0.13** | 0.06 | 0.04 |
| **learnability** | **0.15** | **0.15** | **0.10** | **0.13** |
| **flow** | **0.10** | **0.10** | **0.13** | **0.10** |
| **合计** | **1.00** | **1.00** | **1.00** | **1.10** |

各页型新增 `learnability` + `flow` 都给了合理权重：
- **tool** 强调这两个（交互工具能否用得下去）
- **nav** 偏 `flow`（导航逻辑）
- **docs** 偏 `learnability`（长文能不能读懂）

---

## 🎓 校准金标准（**v2.4 新增**）

学弟 12 模块主观评分（满分 10），作为 Spearman 校准金标准：

```yaml
# calibration_set_v1.yaml
gold_standard:
  scale: 0-10
  modules:
    Activation-Func-Module: 9
    Convolution-Kernel-Intro: 8
    CourseMap: 2  # 技术故障，剔除
    Digital-Image-Module: 9
    Face-Recog-Lab: 10
    Gradient-Descent-Module: 7
    Loss-Guide: 8
    Loss-Guide-2: 9
    LeNet5-CNN-Lab: 7
    Manual-Feature-Classification: 7
    MLP_playground: 7
    Neuron-Guide: 7
  excluded: [CourseMap]
```

**校准流程**：
1. 跑 v2.4 LLM 评分（11 模块，剔除 CourseMap）
2. 计算 Spearman ρ（v2.4 输出 vs gold_standard）
3. ρ ≥ 0.7 → 通过；ρ < 0.7 → 调权重或 prompt

**方法学注意（v2.4.1）**：
- 金标准必须在**同一份静态提取文本**上采集——若金标准者看完整交互版、LLM 只看静态提取版，比较对象不一致，会混淆"rubric 偏差"与"评审对象差异"
- n=11 且重秩多（实测四个 7、三个 9）时 Spearman ρ 本身不稳定，报告需同时给出重秩比例
- ρ 计算实现：`pipeline/aggregate.py::spearman`（并列值取平均秩）

**v2.3 baseline 校准结果**：
- 平均偏差 +12.5 分
- Spearman ρ ≈ 0.55（中等，低于 0.7 目标）

**v2.4 预期**：加 learnability/flow + 降 pedagogy + 严格化 prompt，ρ 应提升到 0.7+

---

## 失败模式

| 故障 | 兜底 |
|---|---|
| HTML 不可解析 | 退回纯文本模式评分（5/10 维有效）|
| LLM 调用超时 | 标 `unscored`，不阻塞其他章节 |
| LLM 返回非 JSON | 正则抽取分数 + 标 `parse_degraded` |
| 静态提取文本过少（JS 渲染页） | 步骤 9 置信度封顶；可选 `--render` headless 重提取 |
| 自洽校验 unstable | 剔除离中位数最远的一次取均值，保留 `unstable_fixed` 标记（步骤 7） |
| 静态提取文本过少（JS 渲染页） | 步骤 9 置信度封顶；可选 `--render` headless 重提取 |
| 自洽校验 unstable | 剔除离中位数最远的一次取均值，保留 `unstable_fixed` 标记（步骤 7） |
| 章节过短（< 50 字）| 跳过 |
| interaction 子项缺失 | fallback 到 interaction 总分平均 |
| learnability / flow 子项缺失 | fallback 到对应维度总分 |

---

## 📦 批量汇总报告（v2.4.1 新增）

多页评估时，`pipeline/aggregate.py --batch` 额外产出 `report_summary.md`：

1. 排名表（总分 / 等级 / 页面类型 / stuck / 告警 / 封顶标记）
2. 10 维分布（均值 + 最低分模块）
3. 硬规则违规统计（alt / aria / heading_skip / P0 命中页清单）
4. 改进建议去重聚类（按 优先级 × impact_dim）
5. 校准块（金标准存在时：n / ρ / 平均偏差 / 方法学注记）
6. 置信度提示（疑似渲染故障页清单）

---

## 触发词

`课程质量评分` / `shuku 内容评分` / `course html eval` / `教学网页评估` / `content quality rubric` / `评估这个课程页面`

---

## v2.1 → v2.2 → v2.3 → v2.4 变更摘要

| 项 | v2.1 | v2.2 | v2.3 | **v2.4** |
|---|---|---|---|---|
| 评分维度数 | 9 | 9 | 8 | **10** |
| 新增维度 | — | interaction 4 子项 | 删 code | **learnability + flow** |
| pedagogy 权重 | 0.25 | 0.25 | 0.22 | **0.15** |
| interaction 权重 | 0.05 | 0.05 | 0.08 | **0.06** |
| LLM prompt | 标准 | 标准 | 标准 | **严格化（反正向偏差）** |
| 校准金标准 | 无 | 无 | 无 | **学弟 11 模块评分** |
| Spearman ρ 目标 | — | — | ≥ 0.7 | ≥ 0.7（11 模块实测）|
| **v2.4.1 补充** | — | — | — | **参考实现 + schema 修正 + stuck v2 + 封顶/分档/批量汇总/校准方法学** |

## 参考资源

- 10 维评分锚点：`references/rubric_full.md`
- 校准数据集 schema + v1 校准集：`references/calibration_schema.md`
- 硬规则映射表：`references/hard_rules.md`
- interaction 4 子项细则：`references/interaction_robustness.md`
- **v2.4 新增**：learnability + flow 子项细则：`references/learnability_flow.md`
- **v2.4.1 新增**：参考实现 `pipeline/extract_features.py` / `pipeline/aggregate.py` / `pipeline/llm_prompt.md`
- **v2.4.1 新增**：报告与输入 schema：`references/report_schema.md`