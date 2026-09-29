#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek API 评分 runner —— course-html-eval v2.4.3（standard 档：每页 3 次扰动评分）

用法（PowerShell）
------------------
$env:DEEPSEEK_API_KEY = "sk-..."
python llm_runner_deepseek.py --sections-dir sections --features-dir features --out llm_scores_deepseek.json

# 评分完成后聚合（含批量汇总）：
python <skill>/pipeline/aggregate.py --features-dir features --scores llm_scores_deepseek.json --out-dir . --batch

安全
----
- API Key 优先从环境变量 DEEPSEEK_API_KEY 读取；未设置时回退读脚本同目录 .api_key 文件（用完即删，勿提交 git）。
- 原始响应落盘 deepseek_raw/ 便于审计，不含 Key。
- 网络异常 / 429 / 5xx 自动重试 4 次（指数退避）；JSON mode 不被支持时自动降级。

口径（对齐 pipeline/llm_prompt.md v2.4.1）
------------------------------------------
- 3 次评分按扰动协议：文档序 / 倒序 / 按节长度升序，temperature >= 0.7
- 单节 < 50 字符跳过（失败模式表）；解析失败 -> 正则抽取 + parse_degraded 标记
- 输出 schema 与 pipeline/aggregate.py 输入契约对齐（passes 为 3x10，DIMS 序）
- 每维证据置信度（high|medium|low）按 3 pass 多数票聚合为 dim_confidence，
  供 aggregate.py 将 low 维度剔除出加权（v2.4.2）
- 模块粒度断点续跑：已写入 --out 的模块自动跳过
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

API_URL_DEFAULT = "https://api.deepseek.com"  # call_api 会追加 /chat/completions
MODEL_DEFAULT = "deepseek-chat"
DIMS = ["accuracy", "coverage", "structure", "readability", "a11y",
        "pedagogy", "visualization", "interaction", "learnability", "flow"]
MIN_SECTION_CHARS = 50
MAX_PROMPT_CHARS = 48000  # ≈16K tokens 安全上限；当前最大模块 ~10KB，远不会触发
ORDER_MODES = ["doc", "reverse", "by_len"]  # 扰动协议：文档序 / 倒序 / 按节长度升序

PROMPT_TEMPLATE = """你是一名严格的教育内容评审专家，对【真实学习体验】打分。你会看到一份课程页面的章节文本（可能不完整）。

### 反偏差指令（必须遵守）
- 5 分只给真正出色的页面，不要因为"看起来专业"就给 5
- 4 分 = 小修即可发布；3 分 = 多处需要修，建议返工；2 分以下 = 不适合发布
- 如果页面让你作为学习者感到困惑、操作卡顿、概念跳跃大，必须扣分
- 不要美化设计良好的页面；证据不足时如实给低置信度，不要脑补补全

【页面类型】<<<PAGE_TYPE>>>
【模块名】<<<MODULE_NAME>>>
【前置模块背景】<<<PREREQ_CONTEXT>>>

【章节内容（证据文本，可能因 JS 渲染而不完整）】
<<<SECTIONS_TEXT>>>

### 评分维度（每维 1~5 分）
1. accuracy       事实准确性
2. coverage       知识覆盖度
3. structure      结构清晰度
4. readability    可读性
5. a11y           可访问性
6. pedagogy       教学设计（先直觉后形式 / 类比 / 循序渐进）
7. visualization  可视化（公式、图表、动图；证据不足时按文本可见部分评）
8. interaction    互动性
9. learnability   可学性
   5 = 看一遍就懂，操作链顺畅
   4 = 大部分能懂，少量卡顿
   3 = 需要反复看才能懂，操作链有跳跃
   2 = 概念跳跃大，普通学生跟不上
   1 = 即使认真读也难懂
10. flow          学习流
   5 = 从头到尾一气呵成，操作链 ≤ 3 步完成
   4 = 流畅但偶有小跳跃
   3 = 章节顺序合理但操作链偏长
   2 = 操作链超过 5 步，章节间过渡突兀
   1 = 顺序混乱，回头率高

### 只输出如下 JSON（不要任何多余文本）
{
  "scores": [
    {"dim": "accuracy", "value": 4, "evidence": "原文摘录（≤40字）", "confidence": "high|medium|low"},
    {"dim": "coverage", "value": 4, "evidence": "...", "confidence": "..."},
    {"dim": "structure", "value": 4, "evidence": "...", "confidence": "..."},
    {"dim": "readability", "value": 4, "evidence": "...", "confidence": "..."},
    {"dim": "a11y", "value": 3, "evidence": "...", "confidence": "..."},
    {"dim": "pedagogy", "value": 4, "evidence": "...", "confidence": "..."},
    {"dim": "visualization", "value": 4, "evidence": "...", "confidence": "..."},
    {"dim": "interaction", "value": 4, "evidence": "...", "confidence": "..."},
    {"dim": "learnability", "value": 4, "evidence": "...", "confidence": "..."},
    {"dim": "flow", "value": 4, "evidence": "...", "confidence": "..."}
  ],
  "llm_overall": 4,
  "interaction_subs": {"answer_tolerance": 3, "hint_progression": 3, "stuck_detection": 2, "error_feedback": 4},
  "learnability_subs": {"concept_jumps": 3, "operation_chain_length": 3, "back_navigation": 3},
  "flow_subs": {"section_order": 4, "transition_quality": 3},
  "improvements": [
    {"priority": "P0|P1|P2", "action": "具体动作", "impact_dim": "维度名", "cost_hours": 2}
  ]
}

### 字段说明（v2.4.1 schema 修正）
- llm_overall（1~5）：总体印象——5 = 愿意直接把该页交给初学者独立使用；3 = 需要陪同指导；1 = 不建议使用。
- transition_quality（1~5）：章节间过渡质量，1~5 尺度。
- interaction_subs / learnability_subs / flow_subs：诊断子项，仅用于报告展示与改进建议定位，
  【不参与】其他维度加权（interaction 例外：4 子项按 0.7 权重卷入 interaction 分）。
- 每个 dim 的 evidence 必须引用章节文本原文片段，禁止无证据打分；confidence=low 表示证据不足。
- improvements 给 3 条；若你判断该页存在让学生卡死的硬伤（无提示的长等待、无退路的硬性门槛），
  第一条必须是缓解该卡顿的 P0 建议。
"""


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------- sections

SEC_RE = re.compile(r"(?m)^\[(?:S(\d+)|Section (\d+))\][ \t]*")


def load_sections(txt_path: Path):
    """解析 sections/<module>.txt -> [(header, body), ...]；<50 字的节跳过。"""
    text = txt_path.read_text(encoding="utf-8")
    matches = list(SEC_RE.finditer(text))
    secs = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if len(body) >= MIN_SECTION_CHARS:
            secs.append((m.group(0).strip(), body))
    return secs


def build_sections_text(secs, mode: str) -> str:
    items = list(secs)
    if mode == "reverse":
        items.reverse()
    elif mode == "by_len":
        items.sort(key=lambda hb: len(hb[1]))
    body = "\n\n".join(f"{h} {b}" for h, b in items)
    if len(body) > MAX_PROMPT_CHARS:
        body = body[:MAX_PROMPT_CHARS] + "\n…(超出安全上限已截断)"
    return body


def build_prompt(secs, page_type: str, module_name: str, mode: str) -> str:
    return (PROMPT_TEMPLATE
            .replace("<<<PAGE_TYPE>>>", page_type)
            .replace("<<<MODULE_NAME>>>", module_name)
            .replace("<<<PREREQ_CONTEXT>>>", "无（未提供）")
            .replace("<<<SECTIONS_TEXT>>>", build_sections_text(secs, mode)))


# ---------------------------------------------------------------- API

def call_api(api_key, base_url, model, prompt, temperature, timeout=180):
    """DeepSeek OpenAI 兼容接口；JSON mode + 400 降级 + 4 次重试。返回 (content, usage, err)。"""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": 4096,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    last_err = None
    for attempt in range(4):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                time.sleep(2 ** attempt * 2)
                continue
            if resp.status_code == 400 and payload.get("response_format"):
                payload.pop("response_format")  # 服务端不支持 JSON mode -> 降级重试
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"], data.get("usage", {}), None
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            time.sleep(2 ** attempt * 2)
    return None, None, last_err


def parse_response(content: str):
    """返回 (dict|None, degraded: bool)。"""
    s = content.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s), False
    except Exception:
        pass
    i, j = s.find("{"), s.rfind("}")
    if 0 <= i < j:
        try:
            return json.loads(s[i:j + 1]), False
        except Exception:
            pass
    vals = {}
    for m in re.finditer(r'"dim"\s*:\s*"([a-zA-Z_]+)"\s*,\s*"value"\s*:\s*([\d.]+)', s):
        vals[m.group(1)] = float(m.group(2))
    if len(vals) >= 8:
        return ({"scores": [{"dim": d, "value": vals[d], "evidence": "", "confidence": "low"}
                            for d in DIMS if d in vals]}, True)
    return None, True


def dim_value(pass_json, dim):
    """返回 (value, evidence, confidence)；缺分时 value=None。"""
    for item in pass_json.get("scores", []):
        if item.get("dim") == dim:
            try:
                return (clamp(float(item["value"]), 1.0, 5.0),
                        str(item.get("evidence", "")),
                        str(item.get("confidence", "")))
            except Exception:
                return None, "", ""
    return None, "", ""


def majority_conf(votes):
    """3 pass 证据置信度多数票；平票取中位档（low<medium<high），全缺省 low。"""
    order = ["low", "medium", "high"]
    votes = [v for v in votes if v in order]
    if not votes:
        return "low"
    counts = {c: votes.count(c) for c in order}
    top = max(counts.values())
    winners = [c for c in order if counts[c] == top]
    return winners[0] if len(winners) == 1 else order[1]


def build_entry(pass_results, page_type):
    """通过校验的 pass 结果列表 -> aggregate.py 输入契约。"""
    passes_rows = []
    degraded = False
    overalls = []
    evid_parts = []
    improvements = []
    subs = {"interaction_subs": {}, "learnability_subs": {}, "flow_subs": {}}
    conf_votes = {d: [] for d in DIMS}
    for parsed, deg in pass_results:
        degraded = degraded or deg
        row = []
        for d in DIMS:
            v, ev, cf = dim_value(parsed, d)
            if v is None:
                v = clamp(float(parsed.get("llm_overall", 3.0) or 3.0), 1.0, 5.0)
                degraded = True
            row.append(round(v, 2))
            if ev:
                evid_parts.append(f"{d}: {ev}")
            if cf:
                conf_votes[d].append(cf)
        passes_rows.append(row)
        try:
            if parsed.get("llm_overall") is not None:
                overalls.append(clamp(float(parsed["llm_overall"]), 1.0, 5.0))
        except Exception:
            pass
        if not improvements and isinstance(parsed.get("improvements"), list) and parsed["improvements"]:
            improvements = parsed["improvements"][:4]
        for k in subs:
            v = parsed.get(k)
            if not subs[k] and isinstance(v, dict) and v:
                subs[k] = v
    evidence = "; ".join(evid_parts)[:600]
    llm_overall = round(sum(overalls) / len(overalls), 2) if overalls else 3.0
    entry = {
        "page_type": page_type,
        "passes": passes_rows,
        "interaction_subs": subs["interaction_subs"],
        "llm_overall": llm_overall,
        "learnability_subs": subs["learnability_subs"],
        "flow_subs": subs["flow_subs"],
        "dim_confidence": {d: majority_conf(conf_votes[d]) for d in DIMS},
        "evidence": evidence,
        "improvements": improvements,
    }
    if degraded:
        entry["parse_degraded"] = True
    return entry


# ---------------------------------------------------------------- main

def out_json(modules: dict) -> dict:
    return {
        "meta": {
            "rubric": "course-html-eval v2.4",
            "tier": "standard (3 passes/page)",
            "dim_order": DIMS,
            "scoring_mode": "DeepSeek API strict anti-bias prompt (v2.4.1, 3-pass perturbation)",
            "date": datetime.date.today().isoformat(),
        },
        "modules": modules,
    }


def save_out(out_path: Path, modules: dict) -> None:
    out_path.write_text(json.dumps(out_json(modules), ensure_ascii=False, indent=2),
                        encoding="utf-8")


def save_out(out_path: Path, modules: dict) -> None:
    out_path.write_text(json.dumps(out_json(modules), ensure_ascii=False, indent=2),
                        encoding="utf-8")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="DeepSeek scoring runner (course-html-eval v2.4.1)")
    ap.add_argument("--sections-dir", required=True)
    ap.add_argument("--features-dir", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--raw-dir", default="deepseek_raw")
    ap.add_argument("--model", default=MODEL_DEFAULT)
    ap.add_argument("--base-url", default=os.environ.get("DEEPSEEK_BASE_URL", API_URL_DEFAULT))
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--exclude", default="", help="逗号分隔，不参与评分")
    ap.add_argument("--only", default="", help="逗号分隔，只评这些模块（冒烟测试用）")
    ap.add_argument("--dry-run", action="store_true", help="只构建 prompt 不调用 API")
    args = ap.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        kf = Path(__file__).with_name(".api_key")  # 备用：本地密钥文件（用完即删）
        if kf.exists():
            api_key = kf.read_text(encoding="utf-8").strip()
    if not api_key and not args.dry_run:
        sys.exit('[error] DEEPSEEK_API_KEY 未设置（PowerShell: $env:DEEPSEEK_API_KEY="sk-..."）')

    sdir = Path(args.sections_dir)
    fdir = Path(args.features_dir) if args.features_dir else None
    exclude = {x.strip() for x in args.exclude.split(",") if x.strip()}
    only = {x.strip() for x in args.only.split(",") if x.strip()}

    txts = sorted(p for p in sdir.glob("*.txt") if p.stem not in exclude)
    if only:
        txts = [t for t in txts if t.stem in only]
    if not txts:
        sys.exit("[error] sections 目录为空或过滤后为空")

    # 断点续跑：已完成的模块跳过
    done = {}
    out_path = Path(args.out)
    if out_path.exists():
        try:
            done = json.loads(out_path.read_text(encoding="utf-8")).get("modules", {})
        except Exception:
            done = {}
    modules = dict(done)

    raw_dir = Path(args.raw_dir)
    if not args.dry_run:
        raw_dir.mkdir(parents=True, exist_ok=True)

    print(f"modules: {len(txts)} planned, {len(modules)} already done (resume)")
    total_in = total_out = n_calls = 0
    failures = []

    for n, txt in enumerate(txts, 1):
        name = txt.stem
        secs = load_sections(txt)
        if not secs:
            print(f"[{n}/{len(txts)}] {name}: 无有效章节（全部 <50 字符），跳过")
            continue

        pt = "teaching"
        if fdir is not None:
            fj = fdir / f"{name}.json"
            if fj.exists():
                try:
                    pt = json.loads(fj.read_text(encoding="utf-8")).get("page_type", "teaching")
                except Exception:
                    pass

        pass_results = []  # [(parsed|None, degraded)]
        for k, mode in enumerate(ORDER_MODES, 1):
            prompt = build_prompt(secs, pt, name, mode)
            if args.dry_run:
                print(f"[dry] {name} pass{k}({mode}): sections={len(secs)} "
                      f"prompt_chars={len(prompt)} ~tokens={len(prompt) // 2}")
                continue
            content, usage, err = call_api(api_key, args.base_url, args.model,
                                           prompt, args.temperature)
            if content is None:
                print(f"[{n}/{len(txts)}] {name} pass{k} FAILED after retries: {err}")
                pass_results.append((None, True))
                continue
            total_in += (usage or {}).get("prompt_tokens", 0) or 0
            total_out += (usage or {}).get("completion_tokens", 0) or 0
            parsed, degraded = parse_response(content)
            pass_results.append((parsed, degraded))
            (raw_dir / f"{name}_pass{k}.json").write_text(
                json.dumps({"module": name, "pass": k, "order": mode,
                            "degraded": degraded, "content": content, "usage": usage},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{n}/{len(txts)}] {name} pass{k}({mode}) ok "
                  f"in={usage.get('prompt_tokens', '?')} out={usage.get('completion_tokens', '?')}"
                  f"{' DEGRADED' if degraded else ''}")

        if args.dry_run:
            continue
        ok_results = [pr for pr in pass_results if pr[0] is not None]
        if len(ok_results) < 2:
            failures.append(name)
            print(f"[{n}/{len(txts)}] {name}: 有效 pass < 2，标记失败")
            continue
        modules[name] = build_entry(ok_results, pt)
        save_out(out_path, modules)
        print(f"  -> saved {name} ({len(modules)}/{len(txts)})")

    if not args.dry_run:
        print(f"usage: in={total_in} tok, out={total_out} tok, failures={failures}")
        print(f"done -> {out_path}")


if __name__ == "__main__":
    main()
