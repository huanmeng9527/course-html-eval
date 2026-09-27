# Interaction 4 子项评分细则（v2.2 新增）

`interaction` 维度在 v2.2 拆为 4 个独立子项，每个子项独立 1~5 分，目的是**识别"学生会卡住"的真实教学风险**。

```
interaction_score = mean(subs.values()) × 0.7 + llm_overall_interaction × 0.3
```

---

## 1. answer_tolerance (答案接受度)

衡量问题对学生答案的宽容程度，避免"答得对被判错"。

### 评分锚点

| 分 | 含义 | HTML 信号 |
|---|---|---|
| **5** | 多选 / LLM 评分意图 / 范围接受 | `<input type="radio">` 或 `[data-grader="llm"]` 或 `[data-tolerance="±10%"]` |
| **4** | 模糊匹配（trim + case-insensitive）| `data-fuzzy-match="true"` 或同义词词典 |
| **3** | 精确匹配但提供多种合法输入路径 | `[data-acceptable-answers="..."]` 列出 ≥ 3 个等价答案 |
| **2** | 精确匹配 + 仅 1 个正确答案 + 无提示 | `<input>` 无 `[data-tolerance]` 也无 `[data-fuzzy-match]` |
| **1** | 精确匹配 + 答错后无任何回退 | `<input>` + 无 `<button data-skip>` + 无 LLM grader |

### 关键代码标记

```html
<!-- 5 分：范围接受 -->
<input type="number" data-tolerance="±5%" data-range="15-19">

<!-- 4 分：模糊匹配 -->
<input data-fuzzy-match="true" data-strip-whitespace="true">

<!-- 3 分：多等价答案 -->
<input data-acceptable-answers="0.04,4%,百分之四">

<!-- 2 分：严格精确且无助 -->
<input type="number" step="1" required>
```

### 风险信号 ⚠️

- `<input type="number">` 数量 > 5 且无任何 `[data-tolerance]`
- 答错只显示 "答错了" 而无解释
- 没有"跳过本题"按钮（`[data-skip-question]` 缺失）

---

## 2. hint_progression (渐进提示)

学生答错后能否获得**逐层递进**的提示，从方向到完整答案。

### 评分锚点

| 分 | 含义 | HTML 信号 |
|---|---|---|
| **5** | 自适应多级提示（3+ 层级 + 错误模式感知）| `[data-hint-levels="3"]` + `[data-adaptive-hint]` |
| **4** | 多级固定提示（方向→关键词→完整答案）| `[data-hint-levels="3"]` 但无自适应 |
| **3** | 答错后给方向提示（"提示 1/3"）| `[data-hint]` 单次 + `[data-hint-counter]` |
| **2** | 答错后给模糊反馈（"再想想"）| 仅 `aria-live` 内容 |
| **1** | 无任何提示/反馈 | 无 `[data-hint]`、无 aria-live 反馈区 |

### 提示内容模板

```html
<!-- 5 分：自适应 3 级提示 -->
<div data-hint-levels="3" data-adaptive-hint>
  <button data-hint-trigger="1">提示 1（方向）</button>
  <button data-hint-trigger="2" hidden>提示 2（关键词）</button>
  <button data-hint-trigger="3" hidden>提示 3（答案）</button>
</div>

<!-- 3 分：单次方向提示 -->
<button data-hint="提示：注意核对题目要求" data-hint-counter="1">
```

### 风险信号 ⚠️

- 答错次数 ≥ 3 但仍只给"再想想"
- 无 `[data-hint-counter]`（学生不知道提示用了多少次）
- 提示按钮被 `hidden` 永久隐藏

---

## 3. stuck_detection (卡顿检测)

系统能否主动识别"学生卡住了"并干预。

### 评分锚点

| 分 | 含义 | HTML 信号 |
|---|---|---|
| **5** | 超时检测 + 重试追踪 + 跳过选项 + 求助入口（全有）| 4 个信号都有 |
| **4** | 缺一个 | 3 个信号 |
| **3** | 缺两个 | 2 个信号 |
| **2** | 仅 1 个信号 | 通常是超时或跳过 |
| **1** | 无任何兜底机制 | 4 个信号全无 |

### 关键代码标记

```html
<!-- 5 分：四项齐全 -->
<div data-stuck-timeout="30s">      <!-- 30 秒无操作提示 -->
<div data-retry-counter max="5">     <!-- 重试次数追踪 -->
<button data-skip-question>跳过</button>  <!-- 跳过选项 -->
<button data-help-button>求助</button>     <!-- 求助入口 -->
```

### 风险信号 ⚠️

- 严格数字题 + 无 `data-stuck-timeout`
- 无 `data-skip-question`（死循环风险）
- 仅靠 `disabled` 状态切换（学生被困住只能刷新）

---

## 4. error_feedback (错误反馈)

答错时反馈的**具体程度**和**诊断价值**。

### 评分锚点

| 分 | 含义 | 示例反馈 |
|---|---|---|
| **5** | 精确诊断（指出差几个 / 哪里错了）| "差 2 个像素，再放大左上角" |
| **4** | 方向具体（指出错误类型）| "答案偏大，请重新数" |
| **3** | 方向模糊 | "再仔细看看题目要求" |
| **2** | 否定但无信息 | "答错了" |
| **1** | 无反馈 / 静默失败 | `aria-live` 无内容 |

### 关键 HTML 区域

```html
<!-- 错误反馈区 -->
<div id="errorFeedback" aria-live="polite">
  <!-- 内容应动态填充具体反馈 -->
</div>
```

### 检测方法

- 检查 `aria-live="polite"` 区域数量
- 检查反馈区是否在错误时**真的会显示内容**（不是占位符）
- LLM 子 prompt："错误反馈区是否有具体诊断文本模板？"

---

## ux_risk_alert 触发规则

```python
def compute_ux_risk_alert(stuck_likelihood):
    if stuck_likelihood >= 0.7:
        return "P0_high_stuck_risk"
    elif stuck_likelihood >= 0.4:
        return "medium"
    else:
        return None  # 或 "low"
```

## 风险模块示例

学弟之前问的 Manual-Feature-Classification（数白色像素）就是典型风险模块：

```
answer_tolerance: 3 (有 input 但无 tolerance)
hint_progression: 2 (仅 aria-live 模糊反馈)
stuck_detection: 1 (无超时/跳过/求助/重试)
error_feedback: 3 (方向模糊)
→ interaction_score = 2.5 (及格边缘)
→ stuck_likelihood = 0.30+0.30+0.20+0.20 = 1.00 → 触发 P0_high_stuck_risk
```

**改进建议**（v2.2 强制 P0 在前）：

1. P0：加 `data-stuck-timeout="20s"` + `data-skip-question` 按钮
2. P0：input 加 `data-tolerance="±1"` 容错 1 个像素
3. P1：加 `data-hint-levels="3"` 多级提示
4. P1：errorFeedback 区域填具体诊断文本