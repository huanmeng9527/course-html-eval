# 报告与输入 Schema（v2.4.1）

本文件定义 course-html-eval v2.4.1 的输入/输出数据格式。参考实现：
`pipeline/extract_features.py`（特征提取）与 `pipeline/aggregate.py`（聚合）。

---

## 1. 评分输入文件（`--scores`，LLM 产出）

```jsonc
{
  "meta": {
    "rubric": "course-html-eval v2.4",
    "tier": "standard (3 passes/page)",
    "dim_order": ["accuracy","coverage","structure","readability","a11y",
                  "pedagogy","visualization","interaction","learnability","flow"],
    "scoring_mode": "LLM strict anti-bias prompt (v2.4.1)",
    "date": "2026-09-27"
  },
  "modules": {
    "<Module>": {
      "page_type": "tool",                  // 兜底用；特征文件存在时以特征为准
      "passes": [[10 维], [10 维], [10 维]], // 3 次整页评分（扰动协议，见 pipeline/llm_prompt.md）
      "interaction_subs": {"answer_tolerance":4,"hint_progression":4,"stuck_detection":3,"error_feedback":4},
      "llm_overall": 4.6,                    // v2.4.1 已纳入 schema（1~5，锚点见 llm_prompt.md）
      "learnability_subs": {"concept_jumps":4,"operation_chain_length":4,"back_navigation":4},
      "flow_subs": {"section_order":5,"transition_quality":4},  // v2.4.1: transition_quality 1~5
      "evidence": "总体证据描述（原文摘录）",
      "improvements": [
        {"priority":"P0|P1|P2","action":"...","impact_dim":"维度名","cost_hours":2}
      ]
    }
  },
  "gold_standard_0_10": { "<Module>": 9 },   // 可选，校准用
  "calibration_excluded": ["CourseMap"]      // 可选，不参与 ρ 计算
}
```

约束：
- `passes` 每行长度 = `dim_order` 长度；3 行缺一不可（否则自洽校验按 unstable 处理）
- `transition_quality` 必须在 1~5（v2.4 示例中的 10 是笔误）
- 诊断子项（`learnability_subs` / `flow_subs`）**仅展示与改进定位**，不参与加权

---

## 2. 特征文件（`features/<module>.json`）

由 `pipeline/extract_features.py` 产出，字段即其源码 docstring 中的指标定义。
聚合器消费的字段：

| 字段 | 用途 |
|---|---|
| `page_type` / `page_type_source` | 权重表选择（`name_fallback` 时报告中保留来源标记） |
| `alt_coverage` < 0.8 | a11y 扣 0.5 |
| `aria_label_rate` < 0.5 | a11y 扣 0.5 |
| `heading_skip` = true | structure 扣 0.3 |
| `stuck.likelihood` | ux_risk_alert 阈值判断（默认 0.25，`--stuck-threshold` 可调） |
| `text_density` < 60 字符/KB | coverage/visualization 置信度降 medium |
| `suspected_render_fault` | 总分封顶 85 + coverage/visualization 置信度 low |

---

## 3. 单页报告（`report.json` 内 `modules.<name>`）

```jsonc
{
  "module": "Activation-Func-Module",
  "total_score": 87.5,
  "grade": "A-",
  "page_type": "tool",
  "page_type_source": "static",
  "confidence_cap_applied": false,
  "dimensions": {
    "<dim>": {
      "score": 4.2,             // 3 次均值（unstable 修复后 / 硬规则叠加后）
      "weight": 0.10,           // 该 page_type 的权重
      "confidence": "high|medium|low",
                                // 仅反映 3 次评分一致性（不确定性）：std<=0.3 high /
                                // <=0.8 medium / 否则 low；单次评分无自洽证据 → low；
                                // 与分数高低无关
      "confidence_original": "high",   // 仅被强制改写时出现：改写前的置信度
      "confidence_overridden": true,   // 仅被强制改写时出现
      "confidence_note": "...",        // 仅被强制改写时出现：改写原因
      "std": 0.24,              // 3 次评分总体标准差
      "unstable": false, "unstable_fixed": false,
      "hard_rule_adjusted": false,
      "subs": {},               // 仅 interaction/learnability/flow 有
      "note": "subs 仅诊断展示，不参与加权"
    }
  },
  "hard_rules": {
    "alt_coverage": 0.95, "aria_label_rate": 0.4, "heading_skip": false,
    "stuck_likelihood": 0.27, "stuck_risk_signals": ["open_task_no_example"],
    "rule_notes": ["aria_label_rate<0.5: a11y-0.5"]
  },
  "ux_risk_alert": null,        // P0_high_stuck_risk | medium | null
  "static_confidence": {"text_density": 86.8, "js_render_ratio": 0.42,
                        "suspected_render_fault": false},
  "evidence": "...",
  "improvements": [ ... ]
}
```

报告顶层另含：`schema_version`、`pipeline_fingerprint`（pipeline/weights/prompt/extractor
版本 + rubric + scoring_mode + date + fingerprint_id）、`stuck_threshold`、`calibration`。

---

## 4. 批量汇总（`--batch` → `report_summary.md`）

1. 排名表（总分 / 等级 / 类型 / stuck / 告警 / 封顶）
2. 10 维均值
3. 硬规则统计（alt / aria / heading_skip / P0 / 封顶页数）
4. 改进建议聚类（按 优先级 × impact_dim 计数 + 示例）
5. 校准块（n / ρ / 平均偏差 / 剔除清单 / 方法学注记）
6. 置信度提示（疑似渲染故障页清单）

---

## 5. 等级分档（v2.4.1 文档化）

| 等级 | 分数 | 等级 | 分数 |
|---|---|---|---|
| A+ | ≥ 95 | B | ≥ 75 |
| A | ≥ 90 | B- | ≥ 70 |
| A- | ≥ 85 | C+ | ≥ 65 |
| B+ | ≥ 80 | C | ≥ 60 |
| | | D | < 60 |

---

## 6. 口径备忘（v2.4 → v2.4.1 变更）

1. **`llm_overall` 入 schema**：v2.4 聚合公式引用它但 prompt 未要求输出——已修复
2. **`transition_quality` 尺度修正**：示例中 10 → 1~5
3. **评分口径**：standard = 每页整体评 3 次，节文本作证据注入（非逐节调用）
4. **stuck v2 信号法**：替代 v1 文案启发式（v1 实测 92% 页面误报 P0）
5. **置信度封顶**：`suspected_render_fault` → 总分 ≤ 85，coverage/visualization 置信 low
6. **不稳定修复**：std > 1.0 → 剔除离中位数最远的一次取均值，保留标记
7. **等级分档**：见第 5 节（v2.4 未文档化）
8. **权重行归一**：tool 行合计 0.98、nav 1.01、docs 1.09——代码按 active 权重归一化，
   表格数字不再声称"合计 1.00"
9. **诊断子项**：learnability_subs / flow_subs 不参与加权（v2.4 未说明卷积方式）
