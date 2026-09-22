# 硬规则映射表（v2 新增）

硬规则指标是把 HTML 解析出的可量化特征直接折算成分数扣减项，目的是**减少对 LLM 主观判断的依赖**，让客观缺陷无法被 LLM 评分掩盖。

## 1. 可访问性 a11y 相关

### `alt_coverage` (图片 alt 覆盖率)

| 值范围 | 影响 |
|---|---|
| ≥ 0.95 | 不扣分 |
| 0.80 ~ 0.95 | a11y -0.2 |
| 0.50 ~ 0.80 | a11y -0.5 |
| < 0.50 | a11y -1.0 |

**理由**：图片 alt 是屏幕阅读器依赖的核心 a11y 信号，缺失严重时直接扣大分。

### `aria_label_rate` (交互元素 aria-label 覆盖率)

| 值范围 | 影响 |
|---|---|
| ≥ 0.90 | 不扣分 |
| 0.50 ~ 0.90 | a11y -0.3 |
| < 0.50 | a11y -0.5 |

**理由**：表单元素缺少 aria-label 时，键盘用户和读屏用户无法独立操作。

### `lang_attr` (html 是否有 lang 属性)

- 缺失：a11y -0.3
- 存在：不扣分

**理由**：`<html lang="zh-CN">` 是文档级元数据，缺失会破坏所有读屏软件的 TTS 行为。

## 2. 结构 structure 相关

### `heading_depth` (最大 heading 级别)

| 值 | 影响 |
|---|---|
| 1~3 | 不扣分（标准） |
| 4 | structure -0.3 |
| 5+ | structure -0.5 |

**理由**：超过 h4 通常意味着作者在滥用 heading 当样式钩子。

### `heading_skip` (相邻 heading 跳级)

- 出现 h1→h3 或 h2→h4：structure -0.3
- 无跳级：不扣分

**理由**：跳级会让 TOC 工具和读屏用户失去导航线索。

### `section_count` (章节数)

- < 3 且 page_type=teaching：structure -0.3（教学页应至少 3 stage）
- ≥ 3：不扣分

## 3. 内容覆盖

### `meta_description` 缺失

- 警告（非扣分）：影响 SEO 分享卡，不影响内容质量

### `i18n_coverage` 低

- < 0.3：仅记录 info，不扣分
- 教学页建议 ≥ 0.5 以便后续国际化

## 4. 链接健康

### 死链（HEAD 请求返回 ≥ 400）

- 单个死链：warning + structure -0.1（最多 -0.3 累计）
- 多个死链（≥ 3 个）：structure -0.5 + warning

### 内链 vs 外链

- 内链全部正常：不扣分
- 外链占比 > 80%：warning（用户离开风险）

## 5. 复合规则示例代码

```python
def compute_hard_rule_deltas(features, hard_rules, page_type):
    """返回各维度的硬规则扣分 dict。"""
    deltas = {
        "a11y": 0.0,
        "structure": 0.0,
        "readability": 0.0,
        "visualization": 0.0,
        "interaction": 0.0,
    }
    
    # a11y 扣分
    alt = hard_rules.get("alt_coverage", 1.0)
    if alt < 0.5:      deltas["a11y"] -= 1.0
    elif alt < 0.8:    deltas["a11y"] -= 0.5
    elif alt < 0.95:   deltas["a11y"] -= 0.2
    
    aria = hard_rules.get("aria_label_rate", 1.0)
    if aria < 0.5:     deltas["a11y"] -= 0.5
    elif aria < 0.9:   deltas["a11y"] -= 0.3
    
    if not hard_rules.get("lang_attr", False):
        deltas["a11y"] -= 0.3
    
    # structure 扣分
    if hard_rules.get("heading_depth", 0) > 4:
        deltas["structure"] -= 0.5
    elif hard_rules.get("heading_depth", 0) > 3:
        deltas["structure"] -= 0.3
    
    if hard_rules.get("heading_skip", False):
        deltas["structure"] -= 0.3
    
    if page_type == "teaching" and features.get("section_count", 0) < 3:
        deltas["structure"] -= 0.3
    
    # 死链
    dead = hard_rules.get("dead_link_count", 0)
    if dead >= 3:       deltas["structure"] -= 0.5
    elif dead >= 1:     deltas["structure"] -= min(0.3, dead * 0.1)
    
    return deltas


def apply_hard_rules(llm_scores, deltas):
    """把硬规则扣分应用到 LLM 评分上。"""
    adjusted = {}
    for dim, score in llm_scores.items():
        delta = deltas.get(dim, 0.0)
        adjusted[dim] = max(0.0, min(5.0, score + delta))
    return adjusted
```

## 6. 阈值校准建议

默认阈值是基于 Web 内容 a11y 通用经验值。如需调整：

- **专业教育平台**：可把 alt_coverage 阈值上调到 0.98（要求所有图片有 alt）
- **入门 UGC**：可放宽到 0.7（避免新作者挫败）
- **多语言课程**：i18n_coverage 应要求 ≥ 0.8

建议在 `quick_calibration` 阶段测试不同阈值组合。