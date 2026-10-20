#!/usr/bin/env python3
"""build_site.py — 从 data/*.json 生成静态站(docs/): 首页时间线 + 单日页。纯手写 HTML,无依赖。

若 day JSON 里有 summarize.py 生成的 summary: 首页每天卡片直接展示「今日推荐」chips,
单日页顶部展示 AI 总结(整体一段话 + 每个模型是什么/优/劣)。
"""
import json
import os
import html
import re

# 社区条目分区(渲染时按来源+标题分类, 旧数据同样生效)
# 优先级: DGX Spark(最高, 官方论坛全部 + 各社区相关帖) > 部署实践 > NVIDIA 动态 > 一般
SPARK_RE = re.compile(r"(dgx\s?spark|\bgb10\b|\bspark\b)", re.I)
# 部署实践: 量化档位/推理框架/速率/硬件实测 — 能直接指导部署的一手经验
DEPLOY_RE = re.compile(
    r"(quant|gguf|awq|gptq|exl\d|mlx\b|\bq[1-8]\b|q[1-8]_[a-z0-9]|\b\d+-?\s?bit\b|"
    r"llama[-.]?cpp|llamacpp|\bvllm\b|ollama|sglang|ktransformers|megakernel|"
    r"tok/s|toks/s|tokens/s|\bt/s\b|throughput|vram|offload|"
    r"\b(5090|5080|4090|4080|4070|3090|3080|3070|3060|7900|7800|7700|6800|6900|"
    r"9700|9800|xtx)\b|apple silicon|macbook|mac mini|mac studio|\bm[1-4]\s?(pro|max|ultra)\b|"
    r"jetson|orin|ascend|\b310p\b|\b910[ab]?\b|"
    r"run(s|ning)?\s+(it\s+)?(locally|local|natively)|local(ly)?\s+(voice|stt|tts|api|setup|deploy)|"
    r"\bstt\b|\btts\b|no dedicated gpu|fits?\s+(a|on|in)\s|"
    r"i (ran|tested|benchmar)|\bbench\b|context tests?|\d+k\s*(context|ctx))", re.I)
# NVIDIA 动态: 官方发布/硬件生态新闻(不含部署细节的)
NVIDIA_RE = re.compile(r"(nvidia|nemotron|jetson|orin|cuda|tensorrt|\bnccl\b)", re.I)
ZONES = [   # (key, 区块标题, 页眉说明); 顺序即页面展示顺序
    ("spark", "DGX Spark", "NVIDIA 官方论坛 DGX Spark/GB10 + 各社区相关帖 — 最高优先"),
    ("deploy", "部署实践", "量化 / 速率 / 硬件实测 — 能指导部署的一手经验"),
    ("nvidia", "NVIDIA 动态", "nemotron / Jetson / CUDA"),
    ("reddit", "社区讨论", ""),
]

def classify_item(it):
    """按来源+标题分区; NVIDIA 论坛条目整体归属 DGX Spark 区"""
    title = it.get("title", "")
    if it.get("source") == "nvidia-forum" or SPARK_RE.search(title):
        return "spark"
    if DEPLOY_RE.search(title):
        return "deploy"
    if NVIDIA_RE.search(title):
        return "nvidia"
    return "reddit"

STYLE = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"PingFang SC",sans-serif;background:#f8f9fb;color:#1a1d23;line-height:1.6}
.wrap{max-width:960px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:22px;margin-bottom:4px}
.sub{color:#6b7280;font-size:13px;margin-bottom:28px}
.day{background:#fff;border:1px solid #e5e7eb;border-radius:10px;margin-bottom:16px;overflow:hidden}
.day-head{display:flex;justify-content:space-between;align-items:baseline;padding:14px 18px;border-bottom:1px solid #e5e7eb;background:#fafbfc}
.day-head a{color:#1a1d23;text-decoration:none;font-weight:700;font-size:16px}
.day-head .n{color:#6b7280;font-size:13px}
.item{padding:10px 18px;border-bottom:1px solid #f0f1f3;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.item:last-child{border-bottom:none}
.tag{font-size:11px;font-family:ui-monospace,monospace;padding:1px 8px;border-radius:5px;flex:none}
.tag.org{background:#e0f2f1;color:#00695c}
.tag.trend{background:#ede7f6;color:#4527a0}
.tag.reddit{background:#fff3e0;color:#e65100}
.tag.nv{background:#e8f5e9;color:#1b5e20}
.item a{color:#1a4fa3;text-decoration:none;font-size:14px;word-break:break-all}
.item a:hover{text-decoration:underline}
.meta{color:#9ca3af;font-size:12px;font-family:ui-monospace,monospace}
section h2{font-size:14px;text-transform:uppercase;letter-spacing:.06em;color:#6b7280;margin:26px 0 10px}
.page-nav{font-size:13px;margin-bottom:20px}
.page-nav a{color:#1a4fa3;text-decoration:none}
footer{margin-top:40px;color:#9ca3af;font-size:12px}
table.assess{width:100%;background:#fff;border:1px solid #e5e7eb;border-radius:10px;border-collapse:collapse;margin-bottom:8px}
table.assess th,table.assess td{padding:8px 12px;border-bottom:1px solid #f0f1f3;font-size:13.5px;text-align:left}
table.assess th{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:#6b7280;background:#fafbfc}
table.assess td.num{font-family:ui-monospace,monospace;white-space:nowrap}
/* AI 总结 */
.picks{padding:10px 18px;border-bottom:1px solid #f0f1f3;background:#fffdf5;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.picks .lbl{font-size:12px;color:#92400e;font-weight:700;flex:none}
.chip{font-size:12.5px;padding:2px 10px;border-radius:20px;background:#fef3c7;border:1px solid #fde68a;color:#92400e;text-decoration:none;font-weight:600}
.chip:hover{background:#fde68a}
.ovo{padding:10px 18px;border-bottom:1px solid #f0f1f3;font-size:13.5px;color:#4b5563;background:#fffdf5}
.sum-ovo{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 18px;margin-bottom:14px}
.sum-ovo p{font-size:14px}
.pick-line{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.pick-line .why{font-size:13px;color:#374151;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:4px 10px}
.sum-model{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px 16px;margin-bottom:10px}
.sm-head{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:6px}
.sm-head a{color:#1a4fa3;text-decoration:none;font-weight:600;font-size:14px;word-break:break-all}
.sm-head a:hover{text-decoration:underline}
.sm-head .badge{margin-left:auto}
.badge{font-size:11px;padding:1px 8px;border-radius:5px;flex:none}
.badge.hot{background:#fee2e2;color:#b91c1c}
.badge.good{background:#dbeafe;color:#1d4ed8}
.badge.meh{background:#f3f4f6;color:#6b7280}
.badge.skip{background:#f3f4f6;color:#9ca3af;text-decoration:line-through}
.sum-model p{font-size:13.5px;margin:2px 0}
.sum-model p b{color:#374151;font-weight:600;margin-right:6px}
"""

def esc(s): return html.escape(str(s))

def anchor(repo): return "m-" + repo.replace("/", "--")

REC_BADGE = {"强烈推荐": ("hot", "★ 强烈推荐"), "值得关注": ("good", "值得关注"),
             "一般": ("meh", "一般"), "跳过": ("skip", "跳过")}


def item_html(it):
    src = it["source"]
    tag = {"hf-org": ("org", "官方"), "hf-trending": ("trend", "trending"),
           "reddit": ("reddit", "社区"), "nvidia-forum": ("nv", "NVIDIA")}.get(src, ("org", src))
    if src == "reddit":
        body = f'<a href="{esc(it["url"])}">{esc(it["title"])}</a>'
        m = re.search(r"reddit\.com/r/([^/]+)/", it.get("url", ""))
        sub = it.get("sub") or (m.group(1) if m else "")
        meta = (f"r/{sub} · " if sub else "") + it.get("updated", "")[:16]
    elif src == "nvidia-forum":
        body = f'<a href="{esc(it["url"])}">{esc(it["title"])}</a>'
        meta = (f"{it.get('sub', '')} 论坛 · " if it.get("sub") else "") + it.get("updated", "")[:16]
    else:
        body = f'<a href="{esc(it["url"])}">{esc(it["repo"])}</a>'
        meta = f"dl:{it.get('downloads',0):,} · ♥{it.get('likes',0)} · {it.get('pipeline') or '-'}"
    return (f'<div class="item"><span class="tag {tag[0]}">{tag[1]}</span>'
            f'{body}<span class="meta">{esc(meta)}</span></div>')


def summary_model_html(m):
    repo = m.get("repo", "")
    b = REC_BADGE.get(m.get("recommendation", ""), ("meh", esc(m.get("recommendation", "—"))))
    cat = f'<span class="tag trend">{esc(m["category"])}</span>' if m.get("category") else ""
    return (f'<div class="sum-model" id="{esc(anchor(repo))}">'
            f'<div class="sm-head"><a href="https://huggingface.co/{esc(repo)}">{esc(repo)}</a>{cat}'
            f'<span class="badge {b[0]}">{b[1]}</span></div>'
            f'<p><b>是什么</b>{esc(m.get("what", ""))}</p>'
            f'<p><b>优势</b>{esc(m.get("pros", ""))}</p>'
            f'<p><b>劣势</b>{esc(m.get("cons", ""))}</p></div>')


def summary_html(data):
    """单日页 AI 总结区: 整体一段话 + 推荐理由 + 每模型 是什么/优/劣"""
    s = data.get("summary")
    if not s:
        return ""
    picks = s.get("picks") or []
    pick_line = "".join(
        f'<span class="why"><b>{esc(p["repo"].split("/", 1)[1])}</b> — {esc(p.get("reason", ""))}</span>'
        for p in picks) or '<span class="meta">今日无特别推荐</span>'
    models_html = "".join(summary_model_html(m) for m in (s.get("models") or []))
    return (f'<section><h2>AI 总结 <span class="meta">{esc(s.get("model", ""))} 生成于 '
            f'{esc((s.get("generated_at") or "")[:16])} UTC · LLM 生成, 仅供参考</span></h2>'
            f'<div class="sum-ovo"><p>{esc(s.get("overview", ""))}</p>'
            f'<div class="pick-line">{pick_line}</div></div>'
            f'{models_html}</section>')


def assess_html(data, picks):
    """部署评估表(picks 里的模型加 ⭐)"""
    rows = data.get("assessments") or []
    if not rows:
        return ""
    seen, uniq = set(), []
    for a in rows:
        if a["repo"] not in seen:
            seen.add(a["repo"])
            uniq.append(a)
    trs = []
    for a in uniq:
        act = f'<span class="meta">激活 {a["active_b"]}B</span>' if a.get("active_b") else ""
        moe = ' <span class="tag trend">MoE</span>' if a.get("moe") else ""
        star = ' <span title="今日推荐">⭐</span>' if a["repo"] in picks else ""
        trs.append(
            f'<tr><td><a href="https://huggingface.co/{esc(a["repo"])}">{esc(a["repo"].split("/",1)[1])}</a>'
            f'<span class="meta">{esc(a["repo"].split("/",1)[0])}</span>{moe}{star}</td>'
            f'<td class="num">{a["params_b"]}B {act}</td>'
            f'<td class="num">{a["q4_gb"]}GB</td>'
            f'<td>{esc(a["mac"])}</td>'
            f'<td>{esc(a["spark"])}</td></tr>')
    return ('<section><h2>部署评估 <span class="meta">⭐=今日推荐 · '
            '估:带宽÷激活权重,±50% · '
            'Mac=M4 Air 24GB(120GB/s,16GB wired) · Spark=单台GB10(273GB/s,95GB)</span></h2>'
            '<table class="assess"><thead><tr><th>模型</th><th>参数</th>'
            f'<th>Q4 显存</th><th>Mac M4 Air</th><th>DGX Spark</th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table></section>')


def index_card(d, data):
    """首页单天卡片: 标题 + 条数 + 今日推荐 chips + 一句话总结"""
    n = sum(len(data.get(k) or []) for k in ("hf_org", "hf_trending", "reddit"))
    s = data.get("summary") or {}
    picks_html = ovo_html = ""
    if s.get("picks"):
        chips = "".join(
            f'<a class="chip" href="{d}.html#{esc(anchor(p["repo"]))}" '
            f'title="{esc(p["repo"])}">{esc(p["repo"].split("/", 1)[1])}</a>'
            for p in s["picks"])
        picks_html = f'<div class="picks"><span class="lbl">⭐ 今日推荐</span>{chips}</div>'
    if s.get("overview"):
        ovo_html = f'<div class="ovo">{esc(s["overview"])}</div>'
    return (f'<div class="day"><div class="day-head"><a href="{d}.html">{d}</a>'
            f'<span class="n">{n} 条</span></div>{picks_html}{ovo_html}</div>')


def page(title, body, footer_note):
    """footer_note 必须来自数据(采集时间/最新日期), 不能用构建时刻——
    否则每次重建所有旧页面都会被改一行, git 里每天全量 diff"""
    return (f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><style>{STYLE}</style></head>'
            f'<body><div class="wrap">{body}'
            f'<footer>model-daily · data: HF API + r/LocalLLaMA · {footer_note}</footer>'
            f'</div></body></html>')


def main():
    days = sorted(f[:-5] for f in os.listdir("data")
                  if f.endswith(".json") and f[0].isdigit() and not f.startswith("assess"))
    os.makedirs("docs", exist_ok=True)

    # 首页: 每天一张卡片(条目点进单日页看全; 有总结则展示推荐 chips + 一段话)
    cards = "".join(index_card(d, json.load(open(f"data/{d}.json"))) for d in reversed(days))
    idx_body = ('<h1>大模型日报</h1>'
                '<div class="sub">HF 官方组织 + trending + r/LocalLLaMA · 每天 09:30 (北京时间) 自动更新</div>'
                + cards)
    with open("docs/index.html", "w") as f:
        f.write(page("大模型日报", idx_body, f"更新至 {days[-1]}"))

    # 单日页
    for d in days:
        data = json.load(open(f"data/{d}.json"))
        picks = {p["repo"] for p in ((data.get("summary") or {}).get("picks") or [])}
        body = (f'<div class="page-nav"><a href="index.html">← 日报首页</a></div>'
                f'<h1>{d}</h1>'
                f'<div class="sub">窗口 {data["window_hours"]}h · 生成于 {data["generated_at"][:16]} UTC</div>'
                + summary_html(data)
                + assess_html(data, picks))
        for key, label in [("hf_org", "官方组织新仓"), ("hf_trending", "trending 新模型")]:
            if data[key]:
                body += f'<section><h2>{label}</h2>' + "".join(item_html(it) for it in data[key]) + '</section>'
        zones = {k: [] for k, _, _ in ZONES}
        for it in (data.get("reddit") or []) + (data.get("nvidia_forum") or []):
            zones[classify_item(it)].append(it)
        for zkey, label, hint in ZONES:
            if zones[zkey]:
                meta = f' <span class="meta">{esc(hint)}</span>' if hint else ""
                body += (f'<section><h2>{label}{meta}</h2>'
                         + "".join(item_html(it) for it in zones[zkey]) + '</section>')
        with open(f"docs/{d}.html", "w") as f:
            f.write(page(d, body, f'采集于 {data["generated_at"][:16]} UTC'))

    print(f"built: index + {len(days)} day pages -> docs/")


if __name__ == "__main__":
    main()
