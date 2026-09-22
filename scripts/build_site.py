#!/usr/bin/env python3
"""build_site.py — 从 data/*.json 生成静态站(docs/): 首页时间线 + 单日页。纯手写 HTML,无依赖。"""
import json
import os
import html
from datetime import datetime

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
"""

def esc(s): return html.escape(str(s))


def item_html(it):
    src = it["source"]
    tag = {"hf-org": ("org", "官方"), "hf-trending": ("trend", "trending"),
           "reddit": ("reddit", "社区")}.get(src, ("org", src))
    if src == "reddit":
        body = f'<a href="{esc(it["url"])}">{esc(it["title"])}</a>'
        meta = it.get("updated", "")[:16]
    else:
        body = f'<a href="{esc(it["url"])}">{esc(it["repo"])}</a>'
        meta = f"dl:{it.get('downloads',0):,} · ♥{it.get('likes',0)} · {it.get('pipeline') or '-'}"
    return (f'<div class="item"><span class="tag {tag[0]}">{tag[1]}</span>'
            f'{body}<span class="meta">{esc(meta)}</span></div>')


def assess_html(data):
    """部署评估表"""
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
        trs.append(
            f'<tr><td><a href="https://huggingface.co/{esc(a["repo"])}">{esc(a["repo"].split("/",1)[1])}</a>'
            f'<span class="meta">{esc(a["repo"].split("/",1)[0])}</span>{moe}</td>'
            f'<td class="num">{a["params_b"]}B {act}</td>'
            f'<td class="num">{a["q4_gb"]}GB</td>'
            f'<td>{esc(a["mac"])}</td>'
            f'<td>{esc(a["spark"])}</td></tr>')
    return ('<section><h2>部署评估 <span class="meta">估:带宽÷激活权重,±50% · '
            'Mac=M4 Air 24GB(120GB/s,16GB wired) · Spark=单台GB10(273GB/s,95GB)</span></h2>'
            '<table class="assess"><thead><tr><th>模型</th><th>参数</th>'
            f'<th>Q4 显存</th><th>Mac M4 Air</th><th>DGX Spark</th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table></section>')


def day_card(day, data, link=True):
    n = len(data["hf_org"]) + len(data["hf_trending"]) + len(data["reddit"])
    title = f'<a href="{day}.html">{day}</a>' if link else esc(day)
    items = "".join(item_html(it) for it in
                    data["hf_org"] + data["hf_trending"] + data["reddit"])
    return (f'<div class="day"><div class="day-head">{title}'
            f'<span class="n">{n} 条</span></div>{items}</div>')


def page(title, body):
    return (f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><style>{STYLE}</style></head>'
            f'<body><div class="wrap">{body}'
            f'<footer>model-daily · data: HF API + r/LocalLLaMA · '
            f'built {datetime.utcnow():%Y-%m-%d %H:%M} UTC</footer>'
            f'</div></body></html>')


def main():
    days = sorted(f[:-5] for f in os.listdir("data")
                  if f.endswith(".json") and f[0].isdigit() and not f.startswith("assess"))
    os.makedirs("docs", exist_ok=True)

    # 首页: 每天一张卡片(条目折叠,点进单日页看全)
    cards = "".join(
        f'<div class="day"><div class="day-head"><a href="{d}.html">{d}</a>'
        f'<span class="n">{sum(len(json.load(open(f"data/{d}.json"))[k]) for k in ("hf_org","hf_trending","reddit"))} 条</span></div></div>'
        for d in reversed(days))
    idx_body = ('<h1>大模型日报</h1>'
                '<div class="sub">HF 官方组织 + trending + r/LocalLLaMA · 每天 09:30 (北京时间) 自动更新</div>'
                + cards)
    with open("docs/index.html", "w") as f:
        f.write(page("大模型日报", idx_body))

    # 单日页
    for d in days:
        data = json.load(open(f"data/{d}.json"))
        body = (f'<div class="page-nav"><a href="index.html">← 日报首页</a></div>'
                f'<h1>{d}</h1>'
                f'<div class="sub">窗口 {data["window_hours"]}h · 生成于 {data["generated_at"][:16]} UTC</div>'
                + assess_html(data))
        for key, label in [("hf_org", "官方组织新仓"), ("hf_trending", "trending 新模型"),
                           ("reddit", "社区讨论")]:
            if data[key]:
                body += f'<section><h2>{label}</h2>' + "".join(item_html(it) for it in data[key]) + '</section>'
        with open(f"docs/{d}.html", "w") as f:
            f.write(page(d, body))

    print(f"built: index + {len(days)} day pages -> docs/")


if __name__ == "__main__":
    main()
