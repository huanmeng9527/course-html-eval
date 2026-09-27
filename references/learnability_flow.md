# learnability + flow 评分细则（v2.4 新增）

`learnability`（可学性）和 `flow`（学习流）是 v2.4 新增的 2 个维度，专门解决"页面设计得好但学生学不会"的问题。

---

## 9. learnability 可学性（默认权重 0.15）

衡量**普通学生能否独立看懂 / 做对**，不看设计专业度，看真实学习体验。

### 评分锚点

| 分 | 含义 | 典型信号 |
|---|---|---|
| **5** | 看一遍就懂，操作链顺畅 | 单一明确 CTA，每步 ≤ 2 个决策点 |
| **4** | 大部分能懂，少量卡顿 | 偶有"卡 30 秒"的地方 |
| **3** | 需要反复看才能懂，操作链有跳跃 | 章节间过渡需要回查前一节 |
| **2** | 概念跳跃大，普通学生跟不上 | 突然出现未解释的术语 |
| **1** | 即使认真读也难懂 | 概念与受众能力严重错位 |

### 3 子项（**v2.4 新增**）

#### 9a. concept_jumps（概念跳跃）

| 分 | 信号 |
|---|---|
| 5 | 每个新概念前都有"回想上一节的 xxx" |
| 3 | 部分概念无铺垫直接抛出 |
| 1 | 大量术语首次出现无解释 |

检测方法：
- 检查 `data-prerequisite` 标注
- LLM 子 prompt: "列出本节首次出现的术语，统计无解释的比例"

#### 9b. operation_chain_length（操作链长度）

| 分 | 信号 |
|---|---|
| 5 | 完成核心任务 ≤ 3 步 |
| 3 | 4~5 步 |
| 1 | > 5 步（用户容易中途放弃）|

检测方法：
- 静态分析：trace 用户完成主要任务的最短路径
- LLM 子 prompt: "完成核心任务需要几步？哪一步最复杂？"

#### 9c. back_navigation（回头率）

| 分 | 信号 |
|---|---|
| 5 | 有 breadcrumbs / "返回目录" / "上一节" |
| 3 | 只有顶部菜单 |
| 1 | 完全无导航 |

检测方法：
- 静态分析：`<nav>` 标签 + `href="../*"` 出现频次

### 计算公式

```python
learnability_score = mean([
    concept_jumps,
    operation_chain_length,
    back_navigation
])
```

---

## 10. flow 学习流（默认权重 0.10）

衡量**章节顺序、操作链流畅性、回头率**。

### 评分锚点

| 分 | 含义 | 典型信号 |
|---|---|---|
| **5** | 从头到尾一气呵成，操作链 ≤ 3 步完成 | 完美的 progressive disclosure |
| **4** | 流畅但偶有小跳跃 | 1~2 处需要回查 |
| **3** | 章节顺序合理但操作链偏长 | 4~5 步任务 |
| **2** | 操作链 > 5 步，章节间过渡突兀 | 用户经常迷路 |
| **1** | 顺序混乱，回头率高 | 学生靠反复试错摸索 |

### 2 子项（**v2.4 新增**）

#### 10a. section_order（章节顺序）

| 分 | 信号 |
|---|---|
| 5 | 章节按学习曲线递增，每章都建立在前一节 |
| 3 | 顺序合理但偶有逻辑跳跃 |
| 1 | 章节顺序不合理或重复 |

检测方法：
- LLM 子 prompt: "章节顺序是否符合由浅入深？有没有需要颠倒或合并的章节？"

#### 10b. transition_quality（过渡质量）

| 分 | 信号 |
|---|---|
| 5 | 每章结尾有"接下来..." + 顶部有进度条 |
| 3 | 有"上一节/下一节"按钮 |
| 1 | 完全无过渡元素 |

检测方法：
- 静态分析：`data-next-lesson`、`href="../NextLesson"` 等
- 进度条 `<nav class="progress">`

### 计算公式

```python
flow_score = mean([
    section_order,
    transition_quality
])
```

---

## v2.4 校准示例

### 用户主观评分映射（spearman 校准）

| 模块 | 用户 (10分) | v2.3 估算 (100分) | v2.4 预期 (100分) |
|---|---|---|---|
| Activation-Func-Module | 9 → 90 | 99 (+9) | ~92 (+2) |
| Convolution-Kernel-Intro | 8 → 80 | 88 (+8) | ~82 (+2) |
| Digital-Image-Module | 9 → 90 | 89.5 (-0.5) | ~90 (0) |
| Face-Recog-Lab | 10 → 100 | 91 (-9) | ~95 (-5) |
| Gradient-Descent-Module | 7 → 70 | 92.3 (+22) | ~75 (+5) ← **flow 扣分** |
| Loss-Guide | 8 → 80 | 96.5 (+16) | ~85 (+5) |
| Loss-Guide-2 | 9 → 90 | 92 (+2) | ~90 (0) |
| LeNet5-CNN-Lab | 7 → 70 | 92.3 (+22) | ~72 (+2) ← **flow 扣分** |
| Manual-Feature-Classification | 7 → 70 | 85 (+15) | ~75 (+5) ← **learnability 扣分** |
| MLP_playground | 7 → 70 | 88.5 (+18) | ~75 (+5) ← **learnability 扣分** |
| Neuron-Guide | 7 → 70 | 90.5 (+20) | ~75 (+5) ← **learnability 扣分** |

**v2.4 预期效果**：
- 平均偏差从 +12.5 降到 +3（Spearman ρ 应提升到 0.7+）
- 高操作复杂度的模块（LeNet5、Gradient）通过 `flow` 被识别
- 概念跳跃的模块（MLP、Neuron）通过 `learnability` 被识别

---

## 实施要点

1. **LLM prompt 必须严格化**——明确说"5 分只给真正出色的页面，不要因为看起来专业就给 5"
2. **静态特征 + LLM 评分并用**——back_navigation / transition_quality 用静态分析更准
4. **operation_chain_length 难静态分析**——主要靠 LLM 评估 + 人工抽样验证
5. **学弟的 11 模块评分就是金标准**——任何 v2.4+ 改版，跑一遍 11 模块验证 Spearman ρ

---

## 关联风险信号

| 信号 | 触发 |
|---|---|
| `learnability < 3` | 警告 + 优先级 P1 改进建议 |
| `flow < 3` | 警告 + 优先级 P1 改进建议 |
| `learnability + flow 双向 < 3` | `ux_risk_alert = "P0_complex_for_learners"`（**v2.4 新增**）|