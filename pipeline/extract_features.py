#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
course-html-eval v2.4.1 —— 参考实现：预处理 / 特征提取 / 硬规则特征（工作流步骤 1~5）

本文件是 SKILL.md 步骤 1~5 的规范实现；指标公式以代码为准，文档只保留含义与阈值。

指标定义（v2.4.1 精确化，消除实现歧义）
----------------------------------------
alt_coverage       非空 alt 的 <img> 数 / <img> 总数；无 <img> 时记 1.0
aria_label_rate    可访问交互元素 / 交互元素总数
                   交互元素 = button + a[href] + input + select + textarea
                   可访问判定 = aria-label | aria-labelledby | title
                                | 有 <label for> 关联（input/select/textarea）
                                | 非空可见文本（button/a）
heading_skip       标题序列（h1..h6 按文档序）出现 h_n -> h_{n+2} 跳级
stuck_likelihood   v2 信号法：
                   R = 风险信号数（0~5）：
                     hard_gate             文案含 解锁 / "(大于|超过|高于) N%"
                     long_task_no_progress 训练/生成/加载类任务无 进度/预计/耗时 提示
                     open_task_no_example  开放任务（请设计/试试吧/画一条…）且无 示例/看答案
                     resource_fail         加载失败 / 资源不完整类提示
                     deep_chain            第二幕/第三幕/下一关/解锁 出现 >= 3 次
                   M = 缓解机制数（data-hint / data-skip / data-example 属性
                       + 提示|跳过|重置|示例|看答案|hint|skip|reset|demo 类按钮），上限 8
                   L = clamp(0.15 + 0.12*R - 0.05*M, 0, 1)
                   （v1 的文案命中数启发式在 12 模块实测中对 92% 页面误报 P0，已废弃）
text_density       可见字符数 / 原始 KB
js_render_ratio    script 字节数 / 原始字节数
suspected_render_fault  (visible_chars < 300 且 raw_kb >= 2)
                        或 (js_render_ratio > 0.9 且 visible_chars < 500)

用法
----
python pipeline/extract_features.py --modules-dir <modules目录> --out-dir <输出目录>
        [--only 模块名1,模块名2] [--render]

输出
----
<out-dir>/features/<module>.json   特征 + 硬规则指标
<out-dir>/sections/<module>.txt    章节切分文本（步骤 5，作为 LLM 评分证据）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CODE_VERSION = "v2.4.1"

# ---- 文案信号（校准记录：v2.4.1 基于 12 模块实测定标，可按标注数据再调）----
RISK_HINT = r"(提示|跳过|重置|示例|看答案|查看答案|样例|hint|skip|reset|demo|重新开始)"
OPEN_TASK = r"(请设计|先提交|试着调整|试试吧|自定义|画一条|换一种模式|写出一个?|想一个|请想)"
EXAMPLE = r"(示例|样例|看答案|查看答案|演示)"
HARD_GATE = r"(解锁|(大于|超过|高于)\s*\d+\s*%)"
LONG_TASK = r"((训练|生成|处理|加载)[^\n。]{0,40}(轮|epoch))"
PROGRESS = r"(进度|预计|耗时|剩余|每秒|实时)"
RESOURCE_FAIL = r"(加载失败|没有加载成功|资源不完整|请检查.{0,12}完整性)"
DEEP_CHAIN = r"(第二幕|第三幕|第四幕|下一关|解锁)"
PREREQ = r"(上一模块|上一节|前置知识|回顾一下|在上一模块)"
TRANSITION = r"(下一(模块|节|步)|接下来|小结|回顾)"

SECTION_CHAR_CAP = 3200  # 每节 ≤ 3200 字符（≈800 tokens）


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def read_html(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def render_html(path: Path, wait_ms: int = 3000):
    """可选：headless 渲染后取 DOM（用于 JS 渲染页的二次提取）。失败返回 None。"""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        print("[warn] playwright 未安装，--render 跳过（静态提取继续）", file=sys.stderr)
        return None
    try:
        url = path.resolve().as_uri()
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=wait_ms * 4)
            page.wait_for_timeout(wait_ms)
            html = page.content()
            browser.close()
        return html
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 渲染失败({exc.__class__.__name__})，回退静态提取", file=sys.stderr)
        return None


def make_soup(html: str):
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        sys.exit("[error] 缺少依赖：pip install beautifulsoup4 lxml")
    for parser in ("lxml", "html.parser"):
        try:
            return BeautifulSoup(html, parser)
        except Exception:
            continue
    sys.exit("[error] BeautifulSoup 解析失败")


def _labelled(el, labelled_ids: set) -> bool:
    if (el.get("aria-label") or "").strip():
        return True
    if (el.get("aria-labelledby") or "").strip():
        return True
    if (el.get("title") or "").strip():
        return True
    if el.name in ("input", "select", "textarea"):
        fid = el.get("id")
        if fid and fid in labelled_ids:
            return True
    if el.name in ("button", "a") and el.get_text(strip=True):
        return True
    return False


def detect_page_type(soup, text: str, module_name: str):
    """返回 (page_type, source)。source: static=静态规则命中 | name_fallback=兜底启发式"""
    sections = soup.find_all("section")
    section_count = len(sections) if sections else len(soup.find_all(["h2"]))
    has_nav_layer = soup.find("nav") is not None
    canvas_count = len(soup.find_all("canvas"))
    form_count = len(soup.find_all("form"))
    paras = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
    avg_para_len = (sum(len(p) for p in paras) / len(paras)) if paras else 0

    if has_nav_layer and section_count <= 2:
        return "nav", "static"
    if canvas_count >= 2 and form_count >= 1:
        return "tool", "static"
    if avg_para_len > 200 and form_count == 0:
        return "docs", "static"

    # v2.4.1 兜底：JS 渲染页往往没有 <nav> 标签、canvas 在渲染前也不存在，
    # 静态三规则全部落空会误判成 teaching。实测 CourseMap 即此情况。
    name = module_name.lower()
    if re.search(r"playground|lab|tool", name):
        return "tool", "name_fallback"
    if re.search(r"map|nav|catalog|index", name) and section_count <= 3:
        return "nav", "name_fallback"
    return "teaching", "name_fallback"


def stuck_v2(soup, text: str) -> dict:
    risks = []
    if re.search(HARD_GATE, text):
        risks.append("hard_gate")
    if re.search(LONG_TASK, text) and not re.search(PROGRESS, text):
        risks.append("long_task_no_progress")
    if re.search(OPEN_TASK, text) and not re.search(EXAMPLE, text):
        risks.append("open_task_no_example")
    if re.search(RESOURCE_FAIL, text):
        risks.append("resource_fail")
    if len(re.findall(DEEP_CHAIN, text)) >= 3:
        risks.append("deep_chain")

    mitig = 0
    for attr in ("data-hint", "data-skip", "data-example"):
        mitig += len(soup.find_all(attrs={attr: True}))
    mitig += sum(
        1 for b in soup.find_all(["button", "a"]) if re.search(RISK_HINT, b.get_text(strip=True))
    )
    mitig = min(mitig, 8)

    likelihood = clamp(0.15 + 0.12 * len(risks) - 0.05 * mitig, 0.0, 1.0)
    return {
        "likelihood": round(likelihood, 2),
        "risk_signals": risks,
        "risk_count": len(risks),
        "mitigation_count": mitig,
    }


def extract_sections(soup) -> list:
    nodes = soup.find_all("section")
    if not nodes:
        seen, uniq = set(), []
        for h in soup.find_all(["h2", "h3"]):
            parent = h.parent
            if parent is not None and id(parent) not in seen:
                seen.add(id(parent))
                uniq.append(parent)
        nodes = uniq
    sections = [n.get_text(" ", strip=True) for n in nodes]
    sections = [s for s in sections if s]
    if not sections:
        sections = [soup.get_text(" ", strip=True)]
    out = []
    for s in sections:
        while len(s) > SECTION_CHAR_CAP:
            out.append(s[:SECTION_CHAR_CAP])
            s = s[SECTION_CHAR_CAP:]
        if s:
            out.append(s)
    return out


def extract_features(module_dir: Path, render: bool = False,
                     return_html: bool = False):
    html_path = module_dir / "index.html"
    if not html_path.exists():
        raise FileNotFoundError(str(html_path))

    html = read_html(html_path)
    if render:
        rendered = render_html(html_path)
        if rendered:
            html = rendered

    raw_len = len(html.encode("utf-8", errors="replace"))
    soup = make_soup(html)

    script_bytes = sum(len(str(s).encode("utf-8", errors="replace")) for s in soup.find_all("script"))
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)

    imgs = soup.find_all("img")
    alt_coverage = (
        sum(1 for i in imgs if (i.get("alt") or "").strip()) / len(imgs) if imgs else 1.0
    )

    labelled_ids = {lb.get("for") for lb in soup.find_all("label") if lb.get("for")}
    interact = [
        el
        for el in soup.find_all(["button", "a", "input", "select", "textarea"])
        if el.name in ("button", "input", "select", "textarea")
        or (el.name == "a" and el.get("href") is not None)
    ]
    aria_label_rate = (
        sum(1 for el in interact if _labelled(el, labelled_ids)) / len(interact)
        if interact
        else 1.0
    )

    level_map = {f"h{i}": i for i in range(1, 7)}
    seq = [level_map[h.name] for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])]
    heading_skip = any(seq[i + 1] - seq[i] >= 2 for i in range(len(seq) - 1))

    headings = {f"h{i}": len(soup.find_all(f"h{i}")) for i in (1, 2, 3)}
    secs = soup.find_all("section")
    section_count = len(secs) if secs else headings["h2"]
    strict_inputs = sum(
        1
        for el in soup.find_all("input")
        if el.get("type") in ("number", "range", "email")
        or any(k in el.attrs for k in ("min", "max", "pattern"))
    )
    anti_stuck_elements = sum(
        len(soup.find_all(attrs={a: True})) for a in ("data-hint", "data-skip", "data-example")
    )

    raw_kb = raw_len / 1024
    text_density = len(text) / max(raw_kb, 0.1)
    js_render_ratio = script_bytes / max(raw_len, 1)
    suspected_fault = (len(text) < 300 and raw_kb >= 2) or (
        js_render_ratio > 0.9 and len(text) < 500
    )

    page_type, pt_source = detect_page_type(soup, text, module_dir.name)
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z]+", text))

    feats = {
        "schema_version": CODE_VERSION,
        "module": module_dir.name,
        "page_type": page_type,
        "page_type_source": pt_source,
        "raw_bytes": raw_len,
        "raw_kb": round(raw_kb, 1),
        "visible_chars": len(text),
        "word_count": cjk + latin_words,
        "paragraph_count": len([p for p in soup.find_all("p") if p.get_text(strip=True)]),
        "headings": headings,
        "section_count": section_count,
        "canvas_count": len(soup.find_all("canvas")),
        "form_count": len(soup.find_all("form")),
        "button_count": len(soup.find_all("button")),
        "input_count": len(soup.find_all("input")),
        "slider_count": len(soup.find_all("input", attrs={"type": "range"})),
        "image_count": len(imgs),
        "alt_coverage": round(alt_coverage, 3),
        "aria_label_rate": round(aria_label_rate, 3),
        "heading_skip": bool(heading_skip),
        "stuck": stuck_v2(soup, text),
        "text_density": round(text_density, 1),
        "js_render_ratio": round(js_render_ratio, 3),
        "suspected_render_fault": bool(suspected_fault),
        "prerequisite_bar": bool(re.search(PREREQ, text)),
        "transition_count": len(re.findall(TRANSITION, text)),
        "strict_input_count": strict_inputs,
        "anti_stuck_elements": anti_stuck_elements,
    }
    if return_html:
        return feats, html
    return feats
    if return_html:
        return feats, html
    return feats


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="course-html-eval v2.4.1 feature extractor")
    ap.add_argument("--modules-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", default="", help="逗号分隔的模块名过滤")
    ap.add_argument("--render", action="store_true", help="尝试 headless 渲染后提取（需 playwright）")
    args = ap.parse_args()

    root = Path(args.modules_dir)
    if not root.exists():
        sys.exit(f"[error] modules-dir 不存在: {root}")

    if (root / "index.html").exists():
        module_dirs = [root]
    else:
        module_dirs = sorted(d for d in root.iterdir() if (d / "index.html").exists())
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    if only:
        module_dirs = [d for d in module_dirs if d.name in only]
    if not module_dirs:
        sys.exit("[error] 未找到含 index.html 的模块目录")

    out = Path(args.out_dir)
    (out / "features").mkdir(parents=True, exist_ok=True)
    (out / "sections").mkdir(parents=True, exist_ok=True)

    for d in module_dirs:
        feats, html_used = extract_features(d, render=args.render, return_html=True)
        (out / "features" / f"{d.name}.json").write_text(
            json.dumps(feats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # 章节切分与特征提取必须同源：--render 时两者都用渲染后 DOM
        soup = make_soup(html_used)
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        secs = extract_sections(soup)
        body = "\n\n".join(f"[S{i+1}] {s}" for i, s in enumerate(secs))
        (out / "sections" / f"{d.name}.txt").write_text(body, encoding="utf-8")
        print(
            f"{d.name}  type={feats['page_type']}({feats['page_type_source']})  "
            f"chars={feats['visible_chars']}  density={feats['text_density']}  "
            f"stuck={feats['stuck']['likelihood']}  risks={feats['stuck']['risk_signals']}  "
            f"mitig={feats['stuck']['mitigation_count']}  "
            f"fault={feats['suspected_render_fault']}"
        )

    print(f"done: {len(module_dirs)} modules -> {out}")


if __name__ == "__main__":
    main()
