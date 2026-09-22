# course-html-eval

> 课程网页 HTML 质量评估 · 9 维 LLM 评分 + 改进方案

对教育类课程网页 HTML 做多维度质量评分。基于 9 维 Rubric（准确性 / 覆盖度 / 结构 / 可读性 / 教学 / 代码 / 可视化 / 互动 / 可访问性）+ 硬规则指标 + 页面类型自动检测。

适用场景：shuku 用户上传课程内容评估、教学页面质量审核、课程页面自动评分。

## 三档配置

| 档位 | 独立指标数 | LLM 调用 | 适用 |
|---|---|---|---|
| `lite` | 9 | 1 次/页 | 大批量内容快审 |
| `standard`（默认）| 12 | 3 次/页 | shuku 用户内容评分 |
| `strict` | 36 | 9 次/页 | 学术 / 极限准确度 |

```python
evaluate(html, tier="standard")  # 默认
evaluate(html, tier="lite")      # 省钱模式
evaluate(html, tier="strict")    # 严谨模式
```

## 9 维评分 Rubric

| 维度 | 含义 | 默认权重 |
|---|---|---|
| accuracy | 事实准确性 | 0.10 |
| coverage | 知识覆盖度 | 0.10 |
| structure | 结构清晰度 | 0.15 |
| readability | 可读性 | 0.15 |
| pedagogy | 教学设计 | 0.25 |
| code | 代码质量 | 0.00 |
| visualization | 可视化 | 0.08 |
| interaction | 互动性 | 0.05 |
| a11y | 可访问性 | 0.12 |

页面类型自动检测后切换权重表：`teaching` / `tool` / `nav` / `docs`。

## 文件结构

```
course-html-eval/
├── SKILL.md                       # 主流程（v2.1）
├── README.md
├── LICENSE
└── references/
    ├── rubric_full.md             # 9 维评分 1~5 锚点定义
    ├── calibration_schema.md      # 校准数据集 schema
    └── hard_rules.md              # 硬规则映射表
```

## 输出示例（standard 档）

```json
{
  "total_score": 87.5,
  "grade": "A-",
  "page_type": "teaching",
  "dimensions": {
    "accuracy": {"score": 4.2, "weight": 0.10, "confidence": "high"},
    "pedagogy": {"score": 4.5, "weight": 0.25, "confidence": "high"},
    "a11y":     {"score": 4.0, "weight": 0.12, "confidence": "high",
                 "hard_rule_delta": -0.5}
  },
  "improvements": [
    {"priority":"P0","action":"...","impact_dim":"可读性","cost_hours":2}
  ]
}
```

## 完整流程

1. 预处理与解析（BeautifulSoup）
2. 结构化特征提取
3. 页面类型自动检测
4. 硬规则提取（3 个核心规则）
5. 章节切分
6. LLM 多维度评分（按 tier 调 1/3/9 次）
7. Self-Consistency 校验（standard+）
8. 硬规则叠加（standard+）
9. 维度加权与总分（归一化 0~100）
10. 改进建议生成（standard+）
11. 输出报告（按 tier 裁剪）

## 触发词

`课程质量评分` / `shuku 内容评分` / `course html eval` / `教学网页评估` / `content quality rubric` / `评估这个课程页面`

## 版本

- **v2.1**（当前）：硬规则 8→3，加三档配置 lite/standard/strict
- **v2**：页面类型自动检测 + 权重归一化 + JSON 解析兜底
- **v1**：初版 9 维评分

## 许可

MIT License
