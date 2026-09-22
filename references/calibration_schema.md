# 校准数据集 Schema

每条样本：

```json
{
  "page_id": "MLP_playground",
  "source": "https://...",
  "char_count": 12345,
  "human_scores": {
    "accuracy": 4.5,
    "coverage": 4.0,
    "structure": 4.5,
    "readability": 4.0,
    "pedagogy": 5.0,
    "code": 4.5,
    "visualization": 4.0,
    "interaction": 5.0,
    "a11y": 5.0,
    "overall": 4.5
  },
  "human_overall_grade": "A",
  "llm_scores": {
    "accuracy": 4.2,
    "coverage": 4.0,
    "structure": 4.5,
    "readability": 4.0,
    "pedagogy": 5.0,
    "code": 4.5,
    "visualization": 4.0,
    "interaction": 5.0,
    "a11y": 5.0
  },
  "labeled_by": "reviewer_id",
  "labeled_at": "2026-09-22T16:00:00Z"
}
```

校准方法：

- 准备 50~100 页样本（覆盖各种类型：讲解型、实操型、可视化型等）
- 邀请 2~3 位领域专家独立打分
- 计算 **Inter-rater agreement**（Krippendorff's α），目标 α > 0.7
- 取专家均分作为 ground truth
- 跑 LLM 评分，计算 Spearman ρ per dimension
- ρ < 0.5：rubric 描述需重写或换 LLM
- ρ 0.5~0.7：降权重
- ρ > 0.7：通过

## 校准 prompt 模板

```
你是一位资深教育内容评估师。请对以下 HTML 内容做严格的质量评分。
请仅基于你看到的实际内容判断，不要因为"看起来专业"就给高分。
对每条评分给出原文引用作为依据。

【HTML 内容】
<content>
```