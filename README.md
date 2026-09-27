# course-html-eval

> 课程网页 HTML 质量评估 · 8 维 LLM 评分 + 防卡顿告警 · v2.3

对教育类课程网页 HTML 做多维度质量评分。基于 8 维 Rubric（准确性 / 覆盖度 / 结构 / 可读性 / 教学 / 可视化 / 互动 / a11y）+ 硬规则指标 + 页面类型自动检测 + **interaction 维度拆 4 子项防卡顿**。

适用场景：shuku 用户上传课程内容评估、教学页面质量审核、课程页面自动评分。

---

## ✨ v2.3 新特性

- **删除 code 维度**（教学网页基本无代码，0 权重维度是噪音）→ **8 维评分**
- **interaction 权重提升**：0.05 → 0.08（各页型统一 +0.03）
- **interaction 拆 4 子项**：防卡顿（详见后文）
- **`ux_risk_alert` 字段**：自动识别高卡顿风险模块
- **三档配置**：lite / standard / strict，按成本/精度权衡

---

## 三档配置

| 档位 | 独立指标数 | LLM 调用 | 适用 |
|---|---|---|---|
| `lite` | 8 | 1 次/页 | 大批量内容快审 |
| `standard`（默认）| 12 | 3 次/页 | shuku 用户内容评分 |
| `strict` | 39 | 9 次/页 | 学术 / 极限准确度 |

```python
evaluate(html, tier="standard")  # 默认
evaluate(html, tier="lite")      # 省钱模式
evaluate(html, tier="strict")    # 严谨模式
```

---

## 8 维评分 Rubric

| 维度 | 含义 | teaching 权重 | 4 档页面类型动态切换 |
|---|---|---|---|
| accuracy | 事实准确性 | 0.10 | teaching / tool / nav / docs |
| coverage | 知识覆盖度 | 0.10 | teaching / tool / nav / docs |
| structure | 结构清晰度 | 0.15 | teaching / tool / nav / docs |
| readability | 可读性 | 0.15 | teaching / tool / nav / docs |
| pedagogy | 教学设计 | **0.22** ↓ | teaching / tool / nav / docs |
| visualization | 可视化 | 0.08 | teaching / tool / nav / docs |
| **interaction** | 互动性 | **0.08** ↑ | teaching / tool / nav / docs |
| a11y | 可访问性 | 0.12 | teaching / tool / nav / docs |

页面类型自动检测（teaching/tool/nav/docs）后切换权重表。**code 维度已在 v2.3 删除**。

---

## 🛡️ interaction 4 子项（v2.2/v2.3 防卡顿核心）

`interaction` 维度拆 4 子项，独立 1~5 分，识别"学生会卡住"的真实教学风险：

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

---

## 📦 文件结构

```
course-html-eval/
├── SKILL.md                              # 主流程（v2.3）
├── README.md                             # 本文档
├── LICENSE                               # MIT
└── references/
    ├── rubric_full.md                   # 8 维评分 1~5 锚点
    ├── calibration_schema.md            # 校准数据集 schema
    ├── hard_rules.md                    # 硬规则映射表
    └── interaction_robustness.md        # interaction 4 子项详细细则
```

---

## 输出示例（standard 档）

```json
{
  "total_score": 87.5,
  "grade": "A-",
  "page_type": "teaching",
  "dimensions": {
    "accuracy":    {"score": 4.2, "weight": 0.10, "confidence": "high"},
    "pedagogy":    {"score": 4.5, "weight": 0.22, "confidence": "high"},
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

## 完整流程

1. 预处理与解析（BeautifulSoup）
2. 结构化特征提取（含防卡顿特征）
3. 页面类型自动检测
4. 硬规则提取（4 个：alt/heading/aria/**stuck_likelihood**）
5. 章节切分
6. LLM 8 维评分（**interaction 拆 4 子项**）
7. Self-Consistency 校验（standard+）
8. 硬规则叠加
9. 维度加权与总分（归一化 0~100）
10. 改进建议生成（**ux_risk_alert=P0 强制置顶**）
11. 输出报告（含 interaction_subs + ux_risk_alert + stuck_likelihood）

---

## 触发词

`课程质量评分` / `shuku 内容评分` / `course html eval` / `教学网页评估` / `content quality rubric` / `评估这个课程页面`

---

## 版本历史

| 版本 | 主要变更 |
|---|---|
| **v2.3** | 删除 code 维度（8 维）/ interaction 0.05→0.08 / pedagogy 0.25→0.22 |
| v2.2 | interaction 拆 4 子项 / ux_risk_alert / stuck_likelihood 硬规则 |
| v2.1 | 三档配置 lite/standard/strict / 硬规则 8→3 |
| v2 | 页面类型自动检测 + 权重归一化 + JSON 解析兜底 |
| v1 | 初版 9 维评分 |

---

## 许可

MIT License