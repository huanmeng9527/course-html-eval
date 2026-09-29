#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
course-html-eval v2.4.1 —— 参考实现：自洽校验 / 硬规则叠加 / 加权聚合 / 校准 / 批量汇总
（工作流步骤 7~11）

用法
----
python pipeline/aggregate.py --features-dir <features目录> --scores <llm_scores.json> \
        --out-dir <输出目录> [--stuck-threshold 0.25] [--batch]

关键口径（v2.4.1 明确）
----------------------
- interaction = mean(interaction_subs 4 子项) × 0.7 + llm_overall × 0.3
  （llm_overall 由评分 prompt 输出，锚点见 pipeline/llm_prompt.md）
- learnability_subs / flow_subs 仅作诊断展示与改进建议定位，不参与维度加权
- 自洽校验：维度 std > 1.0 → unstable；修复 = 剔除离中位数最远的一次后取均值
- 维度置信度只反映评分一致性：std <= 0.3 → high / <= 0.8 → medium / 否则 low；
  单次评分无自洽证据 → low（与分数高低无关，mean 不参与判断）
- 置信度封顶：suspected_render_fault = true → total 封顶 85，
  coverage / visualization 置信度强制 low（JS 渲染页静态提取不完整；
  强制改写保留原值于 confidence_original，并标 confidence_overridden）
- 证据置信度剔除（v2.4.2）：输入 dim_confidence（评分 LLM 自报，3 pass 多数票）中
  为 low 的维度不参与加权，权重归一化到其余维度；分数仍展示并标 weighted=false。
  无 dim_confidence 字段时行为与 v2.4.1 完全一致（向后兼容）
- 决策性剔除（v2.4.3）：--exclude-dims a11y 将维度整体移出加权（评审决策：
  纯无障碍项不计分），权重归一化到其余维度；同时把 impact_dim=a11y 的改进建议
  按性质重分类——公式/文字替代→readability、图表文字替代→learnability、
  错误兜底/防卡死→interaction、纯键盘/屏幕阅读器→not_tracked（不追踪）
- 等级分档：A+ >=95 | A >=90 | A- >=85 | B+ >=80 | B >=75 | B- >=70
            | C+ >=65 | C >=60 | D <60
- 权重表（tool/nav/docs 行）不完全归一，代码按 active 维度实际权重归一化

评分输入 schema 见 references/report_schema.md。
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

CODE_VERSION = "v2.4.3"  # v2.4.3: --exclude-dims 决策性剔除（a11y 移出加权）+ a11y 改进建议重分类

DIMS = ["accuracy", "coverage", "structure", "readability", "a11y",
        "pedagogy", "visualization", "interaction", "learnability", "flow"]

WEIGHTS = {
    # teaching 行合计 1.00；tool/nav/docs 行来自 SKILL.md 权重表（不完全归一，按 active 归一化）
    "teaching": {"accuracy": 0.10, "coverage": 0.10, "structure": 0.10, "readability": 0.10,
                 "a11y": 0.08, "pedagogy": 0.15, "visualization": 0.06, "interaction": 0.06,
                 "learnability": 0.15, "flow": 0.10},
    "tool":     {"accuracy": 0.08, "coverage": 0.08, "structure": 0.10, "readability": 0.08,
                 "a11y": 0.08, "pedagogy": 0.05, "visualization": 0.13, "interaction": 0.13,
                 "learnability": 0.15, "flow": 0.10},
    "nav":      {"accuracy": 0.05, "coverage": 0.05, "structure": 0.27, "readability": 0.15,
                 "a11y": 0.10, "pedagogy": 0.02, "visualization": 0.08, "interaction": 0.06,
                 "learnability": 0.10, "flow": 0.13},
    "docs":     {"accuracy": 0.12, "coverage": 0.12, "structure": 0.12, "readability": 0.18,
                 "a11y": 0.10, "pedagogy": 0.15, "visualization": 0.03, "interaction": 0.04,
                 "learnability": 0.13, "flow": 0.10},
}

GRADE_BANDS = [(95, "A+"), (90, "A"), (85, "A-"), (80, "B+"),
               (75, "B"), (70, "B-"), (65, "C+"), (60, "C"), (-1e9, "D")]

CONFIDENCE_CAP = 85.0   # suspected_render_fault 时的总分封顶
DENSITY_FLOOR = 60.0    # text_density < 60 字符/KB → coverage/visualization 置信度降为 medium


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def grade_of(total: float) -> str:
    for floor, g in GRADE_BANDS:
        if total >= floor:
            return g
    return "D"


def dim_stats(passes, idx: int) -> dict:
    """3 次评分的均值 + 自洽校验。std > 1.0 → unstable：剔除离中位数最远的一次。

    confidence 只反映评分一致性（不确定性），与分数高低无关：
    单次评分无自洽证据 → low；std <= 0.3 → high；std <= 0.8 → medium；否则 low。
    """
    vals = [float(p[idx]) for p in passes]
    mean = sum(vals) / len(vals)
    std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    unstable = std > 1.0
    used = vals
    fixed = False
    if unstable and len(vals) >= 3:
        med = sorted(vals)[len(vals) // 2]
        far = max(vals, key=lambda v: abs(v - med))
        used = list(vals)
        used.remove(far)
        mean = sum(used) / len(used)
        fixed = True
    if len(vals) < 2:
        conf = "low"      # 单次评分：无自洽证据，不能因 std=0 而给 high
    elif std <= 0.3:
        conf = "high"     # 修复：原 mean <= 0.3 在 1~5 分制下不可达，且错把分数高低当置信度
    elif std <= 0.8:
        conf = "medium"
    else:
        conf = "low"
    return {"score": round(mean, 2), "confidence": conf, "std": round(std, 2),
            "unstable": bool(unstable), "unstable_fixed": bool(fixed)}


def _override_confidence(dim: dict, new_conf: str, note: str) -> None:
    """强制改写维度置信度时保留原值并打标，避免覆盖后无法追溯。"""
    if not dim.get("confidence_overridden"):
        dim["confidence_original"] = dim.get("confidence")
        dim["confidence_overridden"] = True
    dim["confidence"] = new_conf
    dim["confidence_note"] = note


def apply_hard_rules(scores: dict, feats: dict | None) -> dict:
    notes = []
    if feats:
        if feats.get("alt_coverage", 1.0) < 0.8:
            scores["a11y"] -= 0.5
            notes.append("alt_coverage<0.8: a11y-0.5")
        if feats.get("aria_label_rate", 1.0) < 0.5:
            scores["a11y"] -= 0.5
            notes.append("aria_label_rate<0.5: a11y-0.5")
        if feats.get("heading_skip", False):
            scores["structure"] -= 0.3
            notes.append("heading_skip: structure-0.3")
    for k in scores:
        scores[k] = round(clamp(scores[k], 1.0, 5.0), 2)
    return {"notes": notes, "scores": scores}


def weighted_total(scores: dict, page_type: str,
                   exclude: frozenset = frozenset()) -> float:
    """加权总分。exclude 中的维度（如证据置信度 low）不参与加权，权重归一化到其余维度。"""
    weights = WEIGHTS.get(page_type, WEIGHTS["teaching"])
    active = {k: w for k, w in weights.items()
              if scores.get(k) is not None and k not in exclude}
    if not active and exclude:  # 兜底：全被剔除时退回不剔除，避免空分
        active = {k: w for k, w in weights.items() if scores.get(k) is not None}
    total_w = sum(active.values())
    if total_w == 0:
        return 0.0
    return clamp(sum(scores[k] * w for k, w in active.items()) / total_w * 20, 0.0, 100.0)


def ux_alert(stuck: float, thr: float):
    if stuck >= thr:
        return "P0_high_stuck_risk"
    if stuck >= max(thr * 0.6, 0.1):
        return "medium"
    return None


def remap_a11y_improvements(improvements: list) -> list:
    """v2.4.3：a11y 移出加权后，将其名下改进建议按性质重分类。

    - 公式文字替代（含 MathML）→ readability（普通学生也读不懂公式碎片）
    - 错误兜底 / 替代路径 / 防卡死 → interaction（error_feedback / stuck）
    - 图表文字替代描述 → learnability（看不懂图的学生也需要）
    - 纯键盘 / 屏幕阅读器 / ARIA 标签 → not_tracked（决策不计分不追踪）
    """
    out = []
    for imp in improvements:
        imp = dict(imp)
        if imp.get("impact_dim") == "a11y":
            text = imp.get("action", "")
            universal = any(k in text for k in
                            ("公式", "MathML", "文字替代", "替代描述",
                             "卡死", "重试", "替代路径", "错误说明"))
            if not universal:
                imp["impact_dim"] = "not_tracked"
                imp["remap_note"] = "纯无障碍项（键盘/屏幕阅读器），v2.4.3 决策不计分不追踪"
            elif "公式" in text or "MathML" in text:
                imp["impact_dim"] = "readability"
                imp["remap_note"] = "公式可读性问题，自 a11y 重分类（v2.4.3）"
            elif any(k in text for k in ("卡死", "重试", "替代路径", "错误说明")):
                imp["impact_dim"] = "interaction"
                imp["remap_note"] = "错误兜底/防卡死问题，自 a11y 重分类（v2.4.3）"
            else:
                imp["impact_dim"] = "learnability"
                imp["remap_note"] = "可视化文字替代问题，自 a11y 重分类（v2.4.3）"
        out.append(imp)
    return out


def _avg_ranks(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        r = (i + j) / 2 + 1  # 并列取平均秩
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def spearman(x, y) -> float:
    """Spearman ρ（并列取平均秩）。n=11 且重秩多时结果不稳定，报告时应注明。"""
    rx, ry = _avg_ranks(x), _avg_ranks(y)
    n = len(x)
    if n < 3:
        return float("nan")
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def aggregate_one(name: str, mod: dict, feats: dict | None, stuck_thr: float,
                  decision_excluded: frozenset = frozenset()) -> dict:
    passes = mod["passes"]
    dims = {}
    for i, d in enumerate(DIMS):
        dims[d] = dim_stats(passes, i)

    raw = {d: dims[d]["score"] for d in DIMS}
    rules = apply_hard_rules(raw, feats)
    scores = rules["scores"]
    for d in DIMS:
        if scores[d] != dims[d]["score"]:
            dims[d]["score"] = scores[d]
            dims[d]["hard_rule_adjusted"] = True

    page_type = feats.get("page_type") if feats and feats.get("page_type") else mod.get("page_type", "teaching")
    pt_source = feats.get("page_type_source", "scores") if feats else "scores"

    subs = mod.get("interaction_subs", {})
    llm_overall = float(mod.get("llm_overall", 3.0))
    if subs:
        inter = sum(float(v) for v in subs.values()) / len(subs) * 0.7 + llm_overall * 0.3
    else:
        inter = llm_overall  # fallback：子项缺失时直接用 llm_overall
    dims["interaction"]["score"] = round(clamp(inter * 5 / 5, 1.0, 5.0), 2)
    dims["interaction"]["subs"] = subs
    dims["interaction"]["formula"] = "mean(interaction_subs)*0.7 + llm_overall*0.3"

    subs_diag = {"learnability_subs": mod.get("learnability_subs", {}),
                 "flow_subs": mod.get("flow_subs", {})}
    for d in ("learnability", "flow"):
        dims[d]["subs"] = subs_diag[f"{d}_subs"]
        dims[d]["note"] = "subs 仅诊断展示，不参与加权"

    dim_conf = mod.get("dim_confidence") or {}
    evidence_excluded = {d for d in DIMS if dim_conf.get(d) == "low"}
    excluded = evidence_excluded | (set(decision_excluded) & set(DIMS))
    for d in DIMS:
        if d in dim_conf:
            dims[d]["evidence_confidence"] = dim_conf[d]
    for d in evidence_excluded:
        dims[d]["weighted"] = False
        dims[d]["weight_note"] = "evidence_confidence=low → 剔除出加权，权重归一化到其余维度"
    # v2.4.3 决策性剔除（如 a11y）：与证据置信度剔除合并，权重归一化到其余维度
    for d in set(decision_excluded) & set(DIMS):
        dims[d]["weighted"] = False
        dims[d]["weight_note"] = "decision: 评审决策剔除出加权（v2.4.3），权重归一化到其余维度"

    total = weighted_total({d: dims[d]["score"] for d in DIMS}, page_type,
                           frozenset(excluded))

    cap = False
    fault = bool(feats and feats.get("suspected_render_fault"))
    density = float(feats.get("text_density", 1e9)) if feats else 1e9
    if fault:
        total = min(total, CONFIDENCE_CAP)
        cap = True
        for d in ("coverage", "visualization"):
            _override_confidence(
                dims[d], "low", "suspected_render_fault: 静态提取不完整")
    elif density < DENSITY_FLOOR:
        for d in ("coverage", "visualization"):
            if dims[d]["confidence"] == "high":
                _override_confidence(
                    dims[d], "medium", f"text_density<{DENSITY_FLOOR:.0f} 字符/KB")

    stuck = float(feats.get("stuck", {}).get("likelihood", 0.0)) if feats else 0.0
    alert = ux_alert(stuck, stuck_thr)

    imps = mod.get("improvements", [])
    if "a11y" in decision_excluded:
        imps = remap_a11y_improvements(imps)

    return {
        "module": name,
        "total_score": round(total, 1),
        "grade": grade_of(total),
        "page_type": page_type,
        "page_type_source": pt_source,
        "confidence_cap_applied": cap,
        "evidence_excluded_dims": sorted(evidence_excluded),
        "decision_excluded_dims": sorted(set(decision_excluded) & set(DIMS)),
        "dimensions": dims,
        "hard_rules": {
            "alt_coverage": feats.get("alt_coverage") if feats else None,
            "aria_label_rate": feats.get("aria_label_rate") if feats else None,
            "heading_skip": feats.get("heading_skip") if feats else None,
            "stuck_likelihood": stuck,
            "stuck_risk_signals": feats.get("stuck", {}).get("risk_signals", []) if feats else [],
            "rule_notes": rules["notes"],
        },
        "ux_risk_alert": alert,
        "static_confidence": {
            "text_density": feats.get("text_density") if feats else None,
            "js_render_ratio": feats.get("js_render_ratio") if feats else None,
            "suspected_render_fault": fault,
        },
        "evidence": mod.get("evidence", ""),
        "improvements": imps,
    }


def write_summary(out: Path, results: list, calib: dict, fingerprint: dict) -> None:
    lines = ["# course-html-eval 批量评估汇总", "",
             f"- pipeline: `{CODE_VERSION}`  fingerprint: `{fingerprint['fingerprint_id']}`",
             f"- date: {fingerprint['date']}", ""]
    lines += ["## 排名", "",
              "| # | 模块 | 总分 | 等级 | 类型 | stuck | 告警 | 封顶 |", "|---|---|---|---|---|---|---|---|"]
    ranked = sorted(results, key=lambda r: -r["total_score"])
    for i, r in enumerate(ranked, 1):
        lines.append(
            f"| {i} | {r['module']} | {r['total_score']} | {r['grade']} | {r['page_type']} "
            f"| {r['hard_rules']['stuck_likelihood']} | {r['ux_risk_alert'] or '-'} "
            f"| {'是' if r['confidence_cap_applied'] else '-'} |")
    lines += ["", "## 维度均值", ""]
    lines.append("| 维度 | 均值 | 最低模块 | |" if False else "| 维度 | 均值 |", )
    lines.pop()
    lines.append("| 维度 | 均值 |")
    lines.append("|---|---|")
    for d in DIMS:
        vals = [r["dimensions"][d]["score"] for r in results]
        mean = sum(vals) / len(vals)
        worst = min(results, key=lambda r: r["dimensions"][d]["score"])
        lines.append(f"| {d} | {mean:.2f} |")
    lines += ["", "## 硬规则统计", ""]
    n_alt = sum(1 for r in results if (r["hard_rules"]["alt_coverage"] or 1) < 0.8)
    n_aria = sum(1 for r in results if (r["hard_rules"]["aria_label_rate"] or 1) < 0.5)
    n_skip = sum(1 for r in results if r["hard_rules"]["heading_skip"])
    n_p0 = sum(1 for r in results if r["ux_risk_alert"] == "P0_high_stuck_risk")
    n_cap = sum(1 for r in results if r["confidence_cap_applied"])
    lines += [f"- alt<0.8: {n_alt} 页 / aria<0.5: {n_aria} 页 / heading_skip: {n_skip} 页",
              f"- P0 卡顿告警: {n_p0} 页 / 置信度封顶: {n_cap} 页", ""]
    lines += ["## 改进建议聚类（按优先级 × 维度）", ""]
    cluster: dict = {}
    for r in results:
        for imp in r["improvements"]:
            key = (imp.get("priority", "?"), imp.get("impact_dim", "?"))
            cluster.setdefault(key, []).append((r["module"], imp.get("action", "")))
    for (pri, dim), items in sorted(cluster.items()):
        lines.append(f"- **{pri} × {dim}** ×{len(items)}：如 {items[0][0]} — {items[0][1][:60]}")
    if calib:
        lines += ["", "## 校准", "",
                  f"- n={calib['n']}  Spearman ρ={calib['spearman_rho']}  平均偏差={calib['mean_bias']}",
                  f"- 剔除: {', '.join(calib['excluded']) or '无'}",
                  "- 注：金标准需在同一份静态提取文本上采集；n<15 且重秩多时 ρ 不稳定，仅作方向性参考", ""]
    lines += ["## 置信度提示", ""]
    faulted = [r["module"] for r in results if r["static_confidence"]["suspected_render_fault"]]
    lines.append(f"- 疑似 JS 渲染故障（总分封顶 85）: {', '.join(faulted) or '无'}")
    ev_excl = {r["module"]: r["evidence_excluded_dims"] for r in results
               if r.get("evidence_excluded_dims")}
    lines.append("- 证据置信度 low 剔除出加权: "
                 + ("; ".join(f"{m}: {','.join(ds)}" for m, ds in ev_excl.items()) or "无"))
    dec_excl = {r["module"]: r["decision_excluded_dims"] for r in results
                if r.get("decision_excluded_dims")}
    lines.append("- 评审决策剔除出加权（v2.4.3）: "
                 + ("; ".join(f"{m}: {','.join(ds)}" for m, ds in dec_excl.items()) or "无"))
    (out / "report_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="course-html-eval v2.4.1 aggregator")
    ap.add_argument("--features-dir", required=True)
    ap.add_argument("--scores", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--stuck-threshold", type=float, default=0.25)
    ap.add_argument("--exclude-dims", default="",
                    help="逗号分隔的决策性剔除维度（如 a11y）：不参与加权，权重归一化到其余维度；"
                         "a11y 剔除时同步重分类其名下改进建议")
    ap.add_argument("--batch", action="store_true", help="额外产出 report_summary.md")
    args = ap.parse_args()

    fdir = Path(args.features_dir)
    scores = json.loads(Path(args.scores).read_text(encoding="utf-8"))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    decision_excluded = frozenset(
        d.strip() for d in args.exclude_dims.split(",") if d.strip())

    today = datetime.date.today().isoformat()
    fingerprint = {
        "pipeline": CODE_VERSION,
        "weights_version": "v2.4",
        "prompt_version": "v2.4.1",
        "extractor": CODE_VERSION,
        "rubric": scores.get("meta", {}).get("rubric"),
        "scoring_mode": scores.get("meta", {}).get("scoring_mode"),
        "excluded_dims": sorted(decision_excluded),
        "date": today,
    }
    fingerprint["fingerprint_id"] = f"{CODE_VERSION}|{fingerprint['rubric']}|{today}"

    results = []
    for name, mod in scores.get("modules", {}).items():
        fpath = fdir / f"{name}.json"
        feats = json.loads(fpath.read_text(encoding="utf-8")) if fpath.exists() else None
        results.append(aggregate_one(name, mod, feats, args.stuck_threshold,
                                     decision_excluded))

    gold = scores.get("gold_standard_0_10") or {}
    excluded = set(scores.get("calibration_excluded") or [])
    totals = {r["module"]: r["total_score"] for r in results}
    pairs = [(m, totals[m], g * 10) for m, g in gold.items()
             if m in totals and m not in excluded]
    calib = None
    if len(pairs) >= 5:
        rho = spearman([p[1] for p in pairs], [p[2] for p in pairs])
        bias = sum(t - g for _, t, g in pairs) / len(pairs)
        calib = {"n": len(pairs), "spearman_rho": round(rho, 3),
                 "mean_bias": round(bias, 1), "excluded": sorted(excluded),
                 "method_note": "金标准应与 LLM 评审同一份静态提取文本；重秩多时 ρ 仅供参考"}

    report = {
        "schema_version": CODE_VERSION,
        "pipeline_fingerprint": fingerprint,
        "stuck_threshold": args.stuck_threshold,
        "modules": {r["module"]: r for r in results},
    }
    if decision_excluded:
        report["rubric_decisions"] = {
            "excluded_dims": sorted(decision_excluded),
            "reason": "评审决策：纯无障碍项不计分（v2.4.3）；"
                      "a11y 名下普适性问题重分类至 readability/learnability/interaction",
        }
    if calib:
        report["calibration"] = calib
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.batch:
        write_summary(out, results, calib, fingerprint)

    ranked = sorted(results, key=lambda r: -r["total_score"])
    for i, r in enumerate(ranked, 1):
        print(f"{i:>2}. {r['module']:<32} {r['total_score']:>5} {r['grade']:>2} "
              f"{r['page_type']:<8} alert={r['ux_risk_alert'] or '-'}")
    if calib:
        print(f"calibration: n={calib['n']} rho={calib['spearman_rho']} bias={calib['mean_bias']}")
    print(f"done -> {out / 'report.json'}")


if __name__ == "__main__":
    main()
