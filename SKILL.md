---
name: "course-html-eval"
description: "课程质量评分 shuku score course html eval. 评估HTML(准确性/教学/可读性/a11y), 输出9维评分+改进建议."
status: proposal
version: "v2.1"
date: "2026-09-22T09:13:00.000Z"
changelog: "v2→v2.1: 硬规则 8→3（保留最核心的3 个）/ 加三档配置 lite/standard/strict / 默认 standard"
---

# 课程网页 HTML 质量评估 (v2.1)

对教育类课程网页 HTML 做 LLM 多维度质量评分。  
适用：shuku 用户上传的课程内容评估、教学页面质量审核、课程页面自动评分标准建立。

**核心特性**：
- 9 维评分 Rubric（准确性 / 覆盖度 / 结构 / 可读性 / 教学 / 可视化 / 互动 / a11y / 代码）
- 三档配置：**lite / standard（默认）/ strict**
- 12 个独立指标（standard 档）
- 页面类型自动检测 + 动态权重
- 硬规则 + LLM 评分双轨防幻觉

---

## 三档配置（**v2.1 新增**）

| 档位 | 独立指标数 | LLM 调用 | self-consistency | 适用 |
|---|---|---|---|---|
| **lite** | 9（仅 LLM 维度）| 1 次/页 | 关闭 | 内容审核快筛 / 大批量 |
| **standard**（默认）| 12（LLM + 3 硬规则）| 3 次/页 | 启用 | shuku 用户内容评分 |
| **strict** | 36（含派生量 + 全部辅助）| 9 次/页 | 启用 + 多模型交叉 | 学术研究 / 极限准确度 |

**配置入口**：

```python
evaluate(html, tier="standard")        # 默认
evaluate(html, tier="lite")            # 省钱模式
evaluate(html, tier="strict")          # 严谨模式
```

**完成标准**：根据 tier 决定后几步是否执行。

---

## 工作流

### 1. 预处理与解析

- 接收输入 + tier 参数
- 编码检测 → 标准化 UTF-8
- BeautifulSoup 解析（lxml）
- 移除 script / style / nav / footer

**完成标准**：得到可遍历的 soup 对象。

### 2. 结构化特征提取

写入 features dict：

- 字符数 / 词数 / 段落数（去除空白）
- 章节数（h1/h2/h3 数）+ 章节层级深度
- 代码块数（pre/code）/ 图片数
- 链接数 + 互动元素数（input/button/select/form/canvas）
- 公式数（KaTeX/MathJax）/ 视频数

**完成标准**：features dict 非空，所有字段为 int / float。

### 3. 页面类型自动检测

```python
def detect_page_type(features):
    if features["has_nav_layer"] and features["section_count"] <= 2:
        return "nav"
    if features["canvas_count"] >= 2 and features["form_count"] >= 1:
        return "tool"
    if features["avg_paragraph_length"] > 200 and features["form_count"] == 0:
        return "docs"
    return "teaching"
```

**权重表**（按页面类型）：

| 维度 | teaching | tool | nav | docs |
|---|---|---|---|---|
| pedagogy | 0.25 | 0.10 | 0.05 | 0.20 |
| structure | 0.15 | 0.15 | 0.30 | 0.15 |
| readability | 0.15 | 0.10 | 0.20 | 0.20 |
| a11y | 0.12 | 0.12 | 0.12 | 0.12 |
| coverage | 0.10 | 0.10 | 0.05 | 0.15 |
| accuracy | 0.10 | 0.10 | 0.05 | 0.15 |
| visualization | 0.08 | 0.18 | 0.10 | 0.05 |
| interaction | 0.05 | 0.15 | 0.08 | 0.03 |

**完成标准**：输出 `{page_type: str, weights: dict}`。

### 4. 硬规则提取（**v2.1 精简为 3 个**）

只保留最关键、客观、最难被 LLM 误判的 3 个硬规则：

| 指标 | 算法 | 阈值 |
|---|---|---|
| `alt_coverage` | `<img>` 中 `alt` 属性非空比例 | < 0.8 → a11y 扣 0.5 |
| `heading_skip` | 相邻 heading 跳级（h1→h3 等）| 出现 → structure 扣 0.3 |
| `aria_label_rate` | `<input>`/`<button>` 中 aria-label 覆盖率 | < 0.5 → a11y 扣 0.5 |

**其它维度不引入硬规则**（避免噪音）。`lang_attr` / `dead_link` / `i18n` 等只在 `strict` 档启用。

**完成标准**：hard_rules dict 至少有 `alt_coverage` 和 `heading_skip`。

### 5. 章节切分

- 按 `<section>` 或标题（h1/h2）切分语义段
- 短段（< 500 字）整段送；长段按段落级切片，每片 ≤ 800 tokens
- 输出 list[{section_id, title, text, weight, is_core_section}]

**完成标准**：list 长度 ≥ 1，每段 text 非空。

### 6. LLM 多维度评分（核心）

根据 tier 决定调用次数：

- **lite**：单次评分，温度 0.2
- **standard**：3 次评分（温度 0.2 / 0.5 / 0.7，取均值）
- **strict**：3 次评分 × 2 个模型（双盲交叉）

**prompt 模板**：

```
你是教育内容评审专家。请对以下 HTML 内容从 9 个维度做质量评分（1~5 分）。

【页面类型】{detected_page_type}
【章节内容】{section_text}

评分维度：
1. accuracy     事实准确性
2. coverage     知识覆盖度
3. structure    结构清晰度
4. readability  可读性
5. pedagogy     教学设计
6. code         代码质量
7. visualization 可视化
8. interaction  互动性
9. a11y         可访问性

输出 JSON：
{
  "scores": [
    {"dim":"accuracy","value":4,"evidence":"原文：xxx","confidence":3}
  ],
  "suggestions": ["建议1", "建议2"],
  "warnings": ["潜在错误：..."]
}

评分校准：5=精品 4=良好 3=中等 2=较差 1=差
注意：不编造原文信息；不确定时降低 confidence；不适用的维度输出 N/A。
```

调用参数：`temperature=0.2`, `max_tokens=2000`，要求 JSON。

**完成标准**：每章节有完整 9 维评分 + ≥ 5 条原文引用。

### 7. Self-Consistency 校验（**tier ≥ standard**）

3 次评分取均值，标准差 > 1.0 标 `unstable`（权重减半）。

**完成标准**：得到 `{dim: {mean, std, confidence}}` dict。

### 8. 硬规则叠加（**tier ≥ standard**）

```python
def apply_hard_rules(llm_scores, hard_rules):
    s = llm_scores.copy()
    if hard_rules["alt_coverage"] < 0.8:
        s["a11y"] = max(0, s["a11y"] - 0.5)
    if hard_rules["heading_skip"]:
        s["structure"] = max(0, s["structure"] - 0.3)
    if hard_rules["aria_label_rate"] < 0.5:
        s["a11y"] = max(0, s["a11y"] - 0.5)
    return s
```

**完成标准**：硬规则扣分已应用，a11y 和 structure 受保护。

### 9. 维度加权与总分

```python
def weighted_total(scores, weights):
    """归一化保证总分 0~100。"""
    active = {k: w for k, w in weights.items() if scores.get(k) is not None}
    total_w = sum(active.values())
    if total_w == 0:
        return 0
    return sum(scores[k] * w for k, w in active.items()) / total_w * 20
```

`code` 维度若返回 N/A，自动从 active_weights 中剔除。

**完成标准**：输出 `{total: float 0~100, dimensions: {dim: {score, weight, confidence}}}`。

### 10. 改进建议生成（**tier ≥ standard**）

基于 lowest-3 维度（去除 unstable），让 LLM 生成 3~5 条 actionable 建议：

```
基于评分弱点：
- 可读性: 2.5 (evidence: ...)
- 教学设计: 3.0 (evidence: ...)

请生成 3~5 条改进建议，每条：
{
  "priority": "P0|P1|P2",
  "action": "具体动作",
  "impact_dim": "影响的维度",
  "cost_hours": 实施工时
}

P0=必修 P1=建议 P2=锦上添花。
```

**完成标准**：3~5 条按优先级排序的建议。

### 11. 输出报告（**按 tier 裁剪**）

**lite 模式输出**（最小）：

```json
{
  "total_score": 87.5,
  "grade": "A-",
  "page_type": "teaching",
  "dimensions": {"accuracy": 4.2, "pedagogy": 4.5, ...}
}
```

**standard 模式输出**（推荐）：

```json
{
  "total_score": 87.5,
  "grade": "A-",
  "page_type": "teaching",
  "dimensions": {
    "accuracy": {"score": 4.2, "weight": 0.10, "confidence": "high"},
    "pedagogy": {"score": 4.5, "weight": 0.25, "confidence": "high"},
    "a11y": {"score": 4.0, "weight": 0.12, "confidence": "high", "hard_rule_delta": -0.5}
  },
  "improvements": [
    {"priority":"P0","action":"...","impact_dim":"可读性","cost_hours":2}
  ],
  "warnings": ["..."]
}
```

**strict 模式输出**（全量）：

standard + features + hard_rules + self_consistency_per_call + multi_model_disagreement。

**完成标准**：report dict 序列化成功 + 写入 `evaluation_log/`。

---

## 失败模式

| 故障 | 兜底 |
|---|---|
| HTML 不可解析 | 退回纯文本模式评分（5/9 维有效）|
| LLM 调用超时 | 标 `unscored`，不阻塞其他章节 |
| **LLM 返回非 JSON** | 正则抽取分数 + 标 `parse_degraded` |
| 章节过短（< 50 字）| 跳过该章节 |
| 校准 ρ < 0.7 | 暂停自动评分，触发人工 review |

---

## 触发词

- 课程质量评分 / 课程内容评估 / 教学网页评估
- shuku 内容评分 / shuku 内容质量 / shuku score
- course html eval / course content quality
- 评估这个课程页面 / 给这个 HTML 打分

---

## v2 → v2.1 变更摘要

| 项 | v2 | v2.1 |
|---|---|---|
| 硬规则指标 | 8 个 | **3 个**（alt_coverage / heading_skip / aria_label_rate）|
| 指标总数 | 36 | **12（standard）/ 9（lite）/ 36（strict）** |
| 配置档位 | 无 | **三档 lite / standard / strict** |
| strict 档特性 | 无 | 双盲多模型 + 全量硬规则 |
| 输出按档裁剪 | 否 | 是（lite 仅分数，standard 含改进建议，strict 含全量）|

## 参考资源

- 9 维评分定义完整版：`references/rubric_full.md`
- 校准数据集 schema：`references/calibration_schema.md`
- 硬规则映射表：`references/hard_rules.md`