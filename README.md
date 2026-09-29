# course-html-eval

> 课程网页 HTML 质量评估 · 9 维加权 LLM 评分 + 防卡顿告警 · v2.4.3

对教育类课程网页 HTML 做多维度质量评分。基于 **9 维加权 Rubric**（准确性 / 覆盖度 / 结构 / 可读性 / 教学 / 可视化 / 互动 / **可学性** / **学习流**）+ 硬规则指标 + 页面类型自动检测 + interaction 维度拆 4 子项防卡顿。a11y（可访问性）已按评审决策移出加权，仅诊断展示。

适用场景：shuku 用户上传课程内容评估、教学页面质量审核、课程页面自动评分。

---

## ✨ v2.4 新特性

- **加 2 个新维度**：
  - `learnability`（可学性，权重 0.15）— 普通学生能否独立看懂/做对
  - `flow`（学习流，权重 0.10）— 章节顺序、操作链流畅性
- **降 pedagogy 权重**：0.22 → **0.15**（用户校准显示 v2.3 严重偏高）
- **LLM prompt 严格化**：加"5 分只给真正出色"等反偏差指令
- **校准机制**：支持用主观评分作 Spearman 校准金标准（ρ 目标 ≥ 0.7）

---

## ✨ v2.4.1 新特性（参考实现 + 可复现性修复）

12 模块实测（standard 档）暴露的问题，全部在本版修复：

- **pipeline/ 参考实现**：`extract_features.py` / `aggregate.py` / `llm_prompt.md`——指标公式以代码为准，消除"每个评估者实现一套"的复现性问题
- **schema 修正**：`llm_overall` 补进评分 JSON（v2.4 公式引用了它但没要求输出）；`transition_quality: 10` 尺度笔误修正为 1~5
- **评分口径明确**：standard = 每页 3 次**整页**评分 + 扰动协议（文档序/倒序/按节长度，temperature ≥ 0.7），章节文本作证据注入而非逐节调用
- **stuck v2 信号法**：v1 文案启发式实测对 92% 页面误报 P0；v2 改为"风险信号 − 缓解机制"信号法，阈值 0.25（可调）
- **JS 渲染盲区兜底**：`js_render_ratio` / `text_density` / `suspected_render_fault` → 置信度封顶，可选 playwright headless 重提取
- **等级分档文档化**：A+ ≥95 · A ≥90 · A- ≥85 · B+ ≥80 · B ≥75 · B- ≥70 · C+ ≥65 · C ≥60 · D <60；报告 schema 见 `references/report_schema.md`
- **批量汇总报告**：`aggregate.py --batch` 产出 `report_summary.md`（排名/维度分布/违规统计/建议聚类/校准块）
- **校准方法学修订**：金标准须在同一份静态提取文本上采集；样本重秩多时 ρ 需同时报告重秩比例

---

## ✨ v2.4.2 新特性（证据置信度剔除）

- **置信度逻辑修正**：`dim_stats()` 由 mean 阈值（1~5 尺度上不可达）改为**标准差法**——单 pass → low；std ≤ 0.3 → high；≤ 0.8 → medium；否则 low。置信度覆写保留原值（`confidence_original` + `confidence_overridden` 标记）
- **证据置信度剔除**：评分 LLM 自报每维证据置信度（high|medium|low），3 pass 多数票聚合为 `dim_confidence`；**low 的维度不参与加权**（权重归一化到其余维度），分数仍展示并标 `weighted=false`——防止"没看全"的维度按臆测分拉低总分
- **渲染提取一致性修复**：`--render` 同时作用于特征提取与章节切分（此前章节仍读静态 HTML）
- **DeepSeek runner**：`pipeline/llm_runner_deepseek.py`——standard 档 3 pass 扰动评分、指数退避重试、JSON 降级解析、模块粒度断点续跑、`dim_confidence` 生产端

---

## ✨ v2.4.3 新特性（评审决策剔除）

- **决策剔除**：`aggregate.py --exclude-dims a11y` 将指定维度移出加权（如用户决策"本评估场景不考虑无障碍"），权重归一化到其余维度；报告新增 `decision_excluded_dims` 字段与 `rubric_decisions` 决策块
- **建议重分类**：`remap_a11y_improvements()` 将剔除维度下的改进建议按关键词重分类到 readability / learnability / interaction（纯键盘/读屏项标记 `not_tracked`），避免"建议跟着维度一起丢"

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

### 端到端跑通（DeepSeek）

```powershell
# 1) 特征提取（--render 可选 playwright 渲染，JS 页建议开启）
python pipeline/extract_features.py --modules-dir <模块目录> --out-dir <输出目录> --render

# 2) DeepSeek 评分（3 pass/页；Key 从环境变量或脚本同目录 .api_key 读取）
$env:DEEPSEEK_API_KEY = "sk-..."
python pipeline/llm_runner_deepseek.py --sections-dir <输出目录>/sections --features-dir <输出目录>/features --out <输出目录>/llm_scores.json

# 3) 聚合出报告（a11y 已按评审决策移出加权）
python pipeline/aggregate.py --features-dir <输出目录>/features --scores <输出目录>/llm_scores.json --out-dir <输出目录> --batch --exclude-dims a11y
```

---

## 评分 Rubric（加权 9 维）

| 维度 | 含义 | teaching 权重 |
|---|---|---|
| accuracy | 事实准确性 | 0.10 |
| coverage | 知识覆盖度 | 0.10 |
| structure | 结构清晰度 | 0.10 |
| readability | 可读性 | 0.10 |
| ~~a11y~~ | 可访问性（v2.4.3 评审决策移出加权，仅诊断展示） | — |
| pedagogy | 教学设计 | **0.15** ↓ |
| visualization | 可视化 | 0.06 |
| interaction | 互动性 | 0.06 |
| **learnability** ⭐ | **可学性（学生能否独立看懂/做对）** | **0.15** |
| **flow** ⭐ | **学习流（章节顺序、操作链流畅性）** | **0.10** |
| **合计** | | **0.92**（按参与加权维度归一化） |

页面类型自动检测（teaching/tool/nav/docs）后切换权重表。`code` 维度在 v2.3 已删除；a11y 维度在 v2.4.3 评审决策移出加权（运行时传 `--exclude-dims a11y`）。

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

### `ux_risk_alert` 触发规则（v2.4.1 = stuck v2 信号法）

```python
# R = 风险信号数（各 1 分）：硬性门槛 / 无进度长任务 / 无示例开放任务 / 资源加载失败 / ≥3 级深链
# M = 缓解机制数（上限 8）：data-hint / data-skip / example 及提示类按钮
stuck_likelihood = max(0.0, min(1.0, 0.15 + 0.12 * R - 0.05 * M))

if stuck_likelihood >= 0.25:   ux_risk_alert = "P0_high_stuck_risk"  # --stuck-threshold 可调
elif stuck_likelihood >= 0.15: ux_risk_alert = "medium"
else:                          ux_risk_alert = None
```

**v1 废弃说明**：v1 文案启发式（阈值 0.7）在 12 模块实测对 92% 页面误报 P0，告警失去区分度，已废弃；阈值 0.25 为初始经验值，建议用带标注的真实卡顿数据再校准。
**v2.4 风险信号保留**：`learnability + flow 双向 < 3` → `P0_complex_for_learners`。
实现：`pipeline/extract_features.py::stuck_v2`。

---

## 🎓 校准（可选）

可用自己的主观评分作 Spearman 校准金标准（数据集 schema 见 `references/calibration_schema.md`）：

1. 对同一批页面采集人工主观评分（0~10），写入评分 JSON 的 `gold_standard_0_10` 字段
2. 跑 LLM 评分后，`aggregate.py` 自动计算 Spearman ρ（并列值取平均秩）
3. ρ ≥ 0.7 → 通过；< 0.7 → 调权重或 prompt

**方法学注意**：
- 金标准必须在**同一份静态提取文本**上采集——若金标准者看完整交互版、LLM 只看静态提取版，比较对象不一致，会混淆"rubric 偏差"与"评审对象差异"
- 样本量小且重秩多时 Spearman ρ 本身不稳定，需同时报告重秩比例

---

## 📦 文件结构

```
course-html-eval/
├── SKILL.md                              # 主流程（v2.4.3）
├── README.md                             # 本文档
├── LICENSE                               # MIT
├── pipeline/                             # ★ 参考实现（公式以代码为准）
│   ├── extract_features.py              # 步骤 1~5：解析/特征/页型检测/stuck v2（--render 可选 playwright）
│   ├── llm_runner_deepseek.py           # ★ v2.4.2 步骤 6 实现：DeepSeek 3 pass 扰动评分 + dim_confidence
│   ├── aggregate.py                     # 步骤 7~11：自洽/硬规则/加权/分档/封顶/校准 ρ（--batch / --exclude-dims）
│   └── llm_prompt.md                    # 步骤 6：完整 prompt 模板（锚点 + 子项定义 + 扰动协议）
└── references/
    ├── rubric_full.md                   # 评分 1~5 锚点
    ├── calibration_schema.md            # 校准数据集 schema
    ├── hard_rules.md                    # 硬规则映射表
    ├── interaction_robustness.md        # interaction 4 子项细则
    ├── learnability_flow.md             # learnability 3 子项 + flow 2 子项细则
    └── report_schema.md                 # ★ 报告与输入 schema（1.1，v2.4.2/v2.4.3 增补）
```

---

## 输出示例（standard 档）

```json
{
  "schema_version": "1.1",
  "fingerprint": {"url": "...", "html_sha1": "...", "extracted_at": "2026-09-27T00:00:00Z", "page_type_source": "static"},
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
  "hard_rules": {"alt_coverage": 0.95, "aria_label_rate": 0.40, "heading_skip": false, "stuck_likelihood": 0.27},
  "ux_risk_alert": null,
  "improvements": [
    {"priority":"P0","action":"加入渐进式提示系统（方向→关键词→答案）",
     "impact_dim":"interaction (hint_progression + stuck_detection)","cost_hours":4}
  ]
}
```

完整字段定义见 `references/report_schema.md`（v2.4.1 新增）。

---

## 完整流程

1. 预处理与解析（BeautifulSoup）→ `pipeline/extract_features.py`
2. 结构化特征提取（含防卡顿 + 可学性 + 渲染盲区指标 `text_density` / `js_render_ratio`）
3. 页面类型自动检测（静态规则 + 名称兜底，输出 `page_type_source`）
4. 硬规则提取（4 个：alt/heading/aria/stuck_likelihood **v2 信号法**）
5. 章节切分（≤ 800 tokens，作为证据注入 prompt）
6. LLM 多维评分（**严格化 prompt** / 整页 3 次 + 扰动协议 / interaction 拆 4 子项 / learnability 拆 3 子项 / flow 拆 2 子项）→ `pipeline/llm_prompt.md`
7. Self-Consistency 校验（standard+，unstable → 剔离群取均值）→ `pipeline/aggregate.py::dim_stats`
8. 硬规则叠加
9. 维度加权与总分（归一化 0~100 / 等级分档 / 渲染故障置信度封顶）
10. 改进建议生成（**ux_risk_alert=P0 强制置顶**）
11. 输出报告（schema 1.1，含 fingerprint / 全维度 + 子项）；多页时 `aggregate.py --batch` 产出 `report_summary.md`

---

## 触发词

`课程质量评分` / `shuku 内容评分` / `course html eval` / `教学网页评估` / `content quality rubric` / `评估这个课程页面`

---

## 版本历史

| 版本 | 主要变更 |
|---|---|
| **v2.4.3** | 评审决策剔除 `--exclude-dims` / 剔除维度改进建议重分类（remap_a11y_improvements）/ 报告 `decision_excluded_dims` + `rubric_decisions` |
| **v2.4.2** | 证据置信度剔除（dim_confidence 3 pass 多数票，low 维度不参与加权）/ dim_stats 置信度标准差法修正 / 覆写保留原值 / --render 章节一致性修复 / DeepSeek runner 入库 |
| **v2.4.1** | pipeline/ 参考实现 / llm_overall + transition_quality schema 修正 / standard=每页 3 次+扰动协议 / stuck v2 信号法 / JS 渲染置信度封顶 / 等级分档 + 报告 schema / 批量汇总 / 校准方法学 |
| **v2.4** | 加 learnability + flow 2 维 / pedagogy 0.22→0.15 / 严格化 prompt / 主观评分校准机制 |
| v2.3 | 删除 code 维度（8 维）/ interaction 0.05→0.08 |
| v2.2 | interaction 拆 4 子项 / ux_risk_alert / stuck_likelihood 硬规则 |
| v2.1 | 三档配置 lite/standard/strict / 硬规则 8→3 |
| v2 | 页面类型自动检测 + 权重归一化 + JSON 解析兜底 |
| v1 | 初版 9 维评分 |

---

## 许可

MIT License