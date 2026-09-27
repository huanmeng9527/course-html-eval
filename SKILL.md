---
name: "course-html-eval"
description: "课程质量评分 shuku score course html eval. 评估HTML(准确性/教学/可读性/a11y), 输出8维评分+改进建议."
status: active
version: "v2.3"
date: "2026-09-27T09:46:00.000Z"
changelog: "v2.2→v2.3: 删除 code 维度（权重恒为0）/ interaction 各页型 +0.03（teaching 0.05→0.08, tool 0.15→0.18, nav 0.08→0.11, docs 0.03→0.06）/ 8 维评分"
---

# 课程网页 HTML 质量评估 (v2.3)

对教育类课程网页 HTML 做 LLM 多维度质量评分。  
适用：shuku 用户上传的课程内容评估、教学页面质量审核、课程页面自动评分标准建立。

**核心特性**：
- **8 维评分 Rubric**（accuracy / coverage / structure / readability / pedagogy / visualization / interaction / a11y，**v2.3 已删除 code**）
- **v2.2 新增**：interaction 拆为 4 子项（防卡顿）
- 三档配置：lite / standard（默认）/ strict
- 12 个独立指标（standard 档）
- 页面类型自动检测 + 动态权重
- 硬规则 + LLM 评分双轨防幻觉
- **v2.2 新增**：`ux_risk_alert` 字段，自动识别高卡顿风险模块

---

## 三档配置

| 档位 | 独立指标数 | LLM 调用 | 适用 |
|---|---|---|---|
| **lite** | 8 | 1 次/页 | 大批量内容快筛 |
| **standard**（默认）| 12 | 3 次/页 | shuku 用户内容评分 |
| **strict** | 39 | 9 次/页 | 学术 / 极限准确度 |

---

## 工作流

### 1. 预处理与解析

- 接收输入 + tier 参数
- 编码检测 → 标准化 UTF-8
- BeautifulSoup 解析（lxml）
- 移除 script / style / nav / footer

**完成标准**：得到可遍历的 soup 对象。

### 2. 结构化特征提取

- 字符数 / 词数 / 段落数
- 章节数（h1/h2/h3）+ 层级深度
- 代码块数 / 图片数 / 链接数
- 互动元素数（input/button/select/form/canvas）
- **v2.2 新增**：检测严格输入元素（`type="number"`、`data-strict-match` 等标记）
- **v2.2 新增**：检测防卡顿元素（`data-hint`、`data-skip`、`data-stuck-timeout`、`data-retry-counter`）

**完成标准**：features dict 非空 + 防卡顿特征字段填充。

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

### 4. 硬规则提取（**v2.2 新增 stuck_likelihood**）

| 指标 | 算法 | 阈值 |
|---|---|---|
| `alt_coverage` | `<img>` 中 `alt` 属性非空比例 | < 0.8 → a11y 扣 0.5 |
| `heading_skip` | 相邻 heading 跳级 | 出现 → structure 扣 0.3 |
| `aria_label_rate` | 交互元素 aria-label 覆盖率 | < 0.5 → a11y 扣 0.5 |
| **`stuck_likelihood`** ⭐ | **综合估分（见下）** | **≥ 0.7 → 触发 ux_risk_alert** |

#### `stuck_likelihood` 计算（**v2.2 新增**）

```python
def compute_stuck_likelihood(features):
    score = 0.0
    if features["has_strict_number_input"]:    score += 0.30
    if not features["has_hint_progression"]:    score += 0.30
    if not features["has_skip_option"]:         score += 0.20
    if not features["has_stuck_timeout"]:       score += 0.20
    return min(1.0, score)
```

阈值：`≥ 0.7` → P0 告警；`0.4~0.7` → warning；`< 0.4` → 安全。

### 5. 章节切分

按 `<section>` / 标题切分语义段，每段 ≤ 800 tokens。

### 6. LLM 多维度评分（**v2.2 新增 4 子项**）

对每个章节调 LLM，**`interaction` 维度拆为 4 子项**：

```
【interaction 子项评分要求】
1. answer_tolerance (答案接受度)
2. hint_progression (渐进提示)
3. stuck_detection (卡顿检测)
4. error_feedback (错误反馈)

输出格式：
{
  "scores": [{"dim":"interaction","value":4,"evidence":"..."}],
  "interaction_subs": {
    "answer_tolerance": 3,
    "hint_progression": 2,
    "stuck_detection": 2,
    "error_feedback": 4
  },
  ...
}
```

**interaction 加权**：`interaction_score = mean(interaction_subs) × 0.7 + llm_overall × 0.3`

调用参数：`temperature=0.2`, `max_tokens=2000`。

### 7. Self-Consistency 校验（**tier ≥ standard**）

3 次评分取均值，标准差 > 1.0 标 `unstable`。4 子项也参与均值计算。

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

### 10. 改进建议生成（**v2.2 新增 ux_risk_alert 处理**）

```
基于评分弱点：
- interaction 子项 answer_tolerance: 2
- ux_risk_alert: P0_high_stuck_risk

请生成 3~5 条改进建议，每条：
{
  "priority": "P0|P1|P2",
  "action": "具体动作",
  "impact_dim": "影响的维度",
  "cost_hours": 实施工时
}

如果 ux_risk_alert=P0，**第一条建议必须是缓解卡顿**的具体方案。
```

### 11. 输出报告

```json
{
  "total_score": 87.5,
  "grade": "A-",
  "page_type": "teaching",
  "dimensions": {
    "accuracy": {"score": 4.2, "weight": 0.10, "confidence": "high"},
    "interaction": {
      "score": 3.5, "weight": 0.08, "confidence": "high",
      "subs": {
        "answer_tolerance": 3.0,
        "hint_progression": 2.5,
        "stuck_detection": 2.0,
        "error_feedback": 4.0
      }
    }
  },
  "hard_rules": {"alt_coverage": 0.95, "stuck_likelihood": 0.85},
  "ux_risk_alert": "P0_high_stuck_risk",
  "improvements": [
    {"priority":"P0","action":"加入渐进式提示系统（方向→关键词→答案）",
     "impact_dim":"interaction (hint_progression + stuck_detection)","cost_hours":4}
  ]
}
```

---

## 🎯 默认权重表（teaching 页面，**v2.3 已更新**）

| 维度 | 权重 | 折算 100 分制 | 评估成本 |
|---|---|---|---|
| pedagogy 教学设计 | **0.22** | 22 分 | 1 次 LLM |
| structure 结构清晰度 | 0.15 | 15 分 | 1 次 |
| readability 可读性 | 0.15 | 15 分 | 1 次 |
| a11y 可访问性 | 0.12 | 12 分 | 1 次 + 硬规则 |
| coverage 知识覆盖度 | 0.10 | 10 分 | 1 次 |
| accuracy 事实准确性 | 0.10 | 10 分 | 1 次 |
| visualization 可视化 | 0.08 | 8 分 | 1 次 |
| **interaction 互动性** | **0.08** ↑ | **8 分** ↑ | **1 次 + 4 子项** |
| **合计** | **1.00** | **100 分** | — |

`code` 维度在 v2.3 已删除（教学网页基本无代码，0 权重维度是噪音）。

---

## 🔄 4 档页面类型的权重切换（**v2.3 已更新**）

| 维度 | teaching | tool | nav | docs |
|---|---|---|---|---|
| pedagogy | **0.22** ↓ | 0.10 | 0.05 | **0.17** ↓ |
| structure | 0.15 | 0.15 | **0.27** ↓ | 0.15 |
| readability | 0.15 | 0.10 | 0.20 | 0.20 |
| a11y | 0.12 | 0.12 | 0.12 | 0.12 |
| coverage | 0.10 | 0.10 | 0.05 | 0.15 |
| accuracy | 0.10 | 0.10 | 0.05 | 0.15 |
| visualization | 0.08 | **0.15** ↓ | 0.10 | 0.05 |
| **interaction** | **0.08** ↑ | **0.18** ↑ | **0.11** ↑ | **0.06** ↑ |
| ~~code~~ | ~~删除~~ | ~~删除~~ | ~~删除~~ | ~~删除~~ |
| **合计** | **1.00** | **1.00** | **0.95** | **1.05** |

**变化说明**（v2.2 → v2.3）：
- `code` 行整行删除
- `interaction` 各页型 +0.03：teaching 0.05→0.08, tool 0.15→0.18, nav 0.08→0.11, docs 0.03→0.06
- 各页型从最大维度匀出权重：teaching 匀自 pedagogy；tool/nav/docs 也匀自对应的最大维度

`nav` 合计 0.95，`docs` 合计 1.05——都是**归一化公式自动校正**，总分仍到 100 满分。

---

## 失败模式

| 故障 | 兜底 |
|---|---|
| HTML 不可解析 | 退回纯文本模式评分（5/8 维有效）|
| LLM 调用超时 | 标 `unscored`，不阻塞其他章节 |
| LLM 返回非 JSON | 正则抽取分数 + 标 `parse_degraded` |
| 章节过短（< 50 字）| 跳过 |
| interaction 子项缺失 | fallback 到 interaction 总分平均 |

---

## 触发词

`课程质量评分` / `shuku 内容评分` / `course html eval` / `教学网页评估` / `content quality rubric` / `评估这个课程页面`

---

## v2.1 → v2.2 → v2.3 变更摘要

| 项 | v2.1 | v2.2 | **v2.3** |
|---|---|---|---|
| 评分维度数 | 9 维 | 9 维 | **8 维（删 code）** |
| interaction 权重 | 0.05 | 0.05 | **0.08**（teaching 档）|
| pedagogy 权重 | 0.25 | 0.25 | **0.22**（teaching 档）|
| interaction 拆 4 子项 | 否 | 是 | 是 |
| 硬规则指标 | 3 | 4（+stuck_likelihood）| 4（不变）|
| 独立指标数（standard）| 12 | 13 | **12** |
| 输出字段 | standard | +ux_risk_alert | +ux_risk_alert |
| 改进建议优先级 | LLM 自由 | P0 强制置顶 | P0 强制置顶 |

## 参考资源

- 8 维评分完整锚点：`references/rubric_full.md`（**v2.3 需删 code 部分**）
- 校准数据集 schema：`references/calibration_schema.md`
- 硬规则映射表：`references/hard_rules.md`
- **v2.2 新增**：interaction 4 子项评分细则：`references/interaction_robustness.md`