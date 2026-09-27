# course-html-eval

> 课程网页 HTML 质量评估 · 10 维 LLM 评分 + 防卡顿告警 · v2.4

对教育类课程网页 HTML 做多维度质量评分。基于 **10 维 Rubric**（准确性 / 覆盖度 / 结构 / 可读性 / 教学 / 可视化 / 互动 / a11y / **可学性** / **学习流**）+ 硬规则指标 + 页面类型自动检测 + interaction 维度拆 4 子项防卡顿。

适用场景：shuku 用户上传课程内容评估、教学页面质量审核、课程页面自动评分。

---

## ✨ v2.4 新特性

- **加 2 个新维度**：
  - `learnability`（可学性，权重 0.15）— 普通学生能否独立看懂/做对
  - `flow`（学习流，权重 0.10）— 章节顺序、操作链流畅性
- **降 pedagogy 权重**：0.22 → **0.15**（用户校准显示 v2.3 严重偏高）
- **LLM prompt 严格化**：加"5 分只给真正出色"等反偏差指令
- **校准金标准**：学弟 11 模块主观评分（CourseMap 剔除），Spearman ρ 目标 ≥ 0.7

---

## 三档配置

| 档位 | 独立指标数 | LLM 调用 | 适用 |
|---|---|---|---|
| `lite` | 10 | 1 次/页 | 大批量内容快审 |
| `standard`（默认）| 14 | 3 次/页 | shuku 用户内容评分 |
| `strict` | 45 | 9 次/页 | 学术 / 极限准确度 |

```python
evaluate(html, tier="standard")  # 默认
evaluate(html, tier="lite")      # 省钱模式
evaluate(html, tier="strict")    # 严谨模式
```

---

## 10 维评分 Rubric

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
| **learnability** ⭐ | **可学性（学生能否独立看懂/做对）** | **0.15** |
| **flow** ⭐ | **学习流（章节顺序、操作链流畅性）** | **0.10** |
| **合计** | | **1.00** |

页面类型自动检测（teaching/tool/nav/docs）后切换权重表。`code` 维度在 v2.3 已删除。

---

## 🛡️ interaction 4 子项（v2.2/v2.4 沿用）

`interaction` 维度拆 4 子项，识别"学生会卡住"的真实教学风险：

| 子项 | 评估什么 | 防什么问题 |
|---|---|---|
| `answer_tolerance` | 答案接受宽容度 | 答得对被判错 |
| `hint_progression` | 渐进提示系统 | 学生卡住没方向 |
| `stuck_detection` | 卡顿主动检测 | 学生卡死没人管 |
| `error_feedback` | 错误反馈具体度 | "再想想"式空洞反馈 |

```
interaction_score = mean(4 子项) × 0.7 + llm_overall_interaction × 0.3
```

### `ux_risk_alert` 触发规则

```python
stuck_likelihood = (
    (0.30 if has_strict_number_input else 0) +
    (0.30 if not has_hint_progression else 0) +
    (0.20 if not has_skip_option      else 0) +
    (0.20 if not has_stuck_timeout    else 0)
)

if stuck_likelihood >= 0.7:  ux_risk_alert = "P0_high_stuck_risk"
elif stuck_likelihood >= 0.4: ux_risk_alert = "medium"
else:                         ux_risk_alert = None
```

**v2.4 新增风险信号**：`learnability + flow 双向 < 3` → `P0_complex_for_learners`

---

## 🎓 校准金标准（v2.4 新增）

学弟主观评分（满分 10）作为 Spearman 校准金标准：

| 模块 | 学弟分 | 模块 | 学弟分 |
|---|---|---|---|
| Activation-Func-Module | 9 | Loss-Guide-2 | 9 |
| Convolution-Kernel-Intro | 8 | LeNet5-CNN-Lab | 7 |
| Digital-Image-Module | 9 | Manual-Feature-Classification | 7 |
| Face-Recog-Lab | 10 | MLP_playground | 7 |
| Gradient-Descent-Module | 7 | Neuron-Guide | 7 |
| Loss-Guide | 8 | ~~CourseMap~~ | ~~2（技术故障，剔除）~~ |

**校准流程**：
1. 跑 v2.4 LLM 评分（11 模块）
2. Spearman ρ ≥ 0.7 → 通过；< 0.7 → 调权重或 prompt

---

## 📦 文件结构

```
course-html-eval/
├── SKILL.md                              # 主流程（v2.4, 11.5K bytes）
├── README.md                             # 本文档
├── LICENSE                               # MIT
└── references/
    ├── rubric_full.md                   # 10 维评分 1~5 锚点
    ├── calibration_schema.md            # 校准数据集 schema + v1 校准集
    ├── hard_rules.md                    # 硬规则映射表
    ├── interaction_robustness.md        # interaction 4 子项细则
    └── learnability_flow.md             # learnability 3 子项 + flow 2 子项细则
```

---

## 输出示例（standard 档）

```json
{
  "total_score": 87.5,
  "grade": "A-",
  "page_type": "teaching",
  "dimensions": {
    "accuracy": {"score": 4.2, "weight": 0.10, "confidence": "high"},
    "pedagogy": {"score": 4.5, "weight": 0.15, "confidence": "high"},
    "learnability": {
      "score": 3.5, "weight": 0.15, "confidence": "high",
      "subs": {
        "concept_jumps": 3,
        "operation_chain_length": 4,
        "back_navigation": 3
      }
    },
    "flow": {
      "score": 4.0, "weight": 0.10, "confidence": "high",
      "subs": {"section_order": 4, "transition_quality": 4}
    },
    "interaction": {
      "score": 3.5, "weight": 0.06, "confidence": "high",
      "subs": {"answer_tolerance": 3, "hint_progression": 2, "stuck_detection": 2, "error_feedback": 4}
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

## 完整流程

1. 预处理与解析（BeautifulSoup）
2. 结构化特征提取（含防卡顿 + 可学性特征）
3. 页面类型自动检测
4. 硬规则提取（4 个：alt/heading/aria/stuck_likelihood）
5. 章节切分
6. LLM 10 维评分（**严格化 prompt** / interaction 拆 4 子项 / learnability 拆 3 子项 / flow 拆 2 子项）
7. Self-Consistency 校验（standard+）
8. 硬规则叠加
9. 维度加权与总分（归一化 0~100）
10. 改进建议生成（**ux_risk_alert=P0 强制置顶**）
11. 输出报告（含 10 维度 + interaction_subs + learnability_subs + flow_subs）

---

## 触发词

`课程质量评分` / `shuku 内容评分` / `course html eval` / `教学网页评估` / `content quality rubric` / `评估这个课程页面`

---

## 版本历史

| 版本 | 主要变更 |
|---|---|
| **v2.4** | 加 learnability + flow 2 维（10 维）/ pedagogy 0.22→0.15 / 严格化 prompt / 学弟 11 模块评分作校准金标准 |
| v2.3 | 删除 code 维度（8 维）/ interaction 0.05→0.08 |
| v2.2 | interaction 拆 4 子项 / ux_risk_alert / stuck_likelihood 硬规则 |
| v2.1 | 三档配置 lite/standard/strict / 硬规则 8→3 |
| v2 | 页面类型自动检测 + 权重归一化 + JSON 解析兜底 |
| v1 | 初版 9 维评分 |

---

## 许可

MIT License