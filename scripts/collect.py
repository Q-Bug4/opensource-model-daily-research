#!/usr/bin/env python3
"""collect.py — 从各数据源采集'新发布的大模型',存 JSON。

源(全部免鉴权,2026-09-22 实测可用):
  1. HF 官方组织新仓: /api/models?author=<org>&sort=createdAt (48h 窗口)
  2. HF trending: sort=trendingScore + downloads/likes 质量门(滤掉微调/转换仓)
  3. Reddit r/LocalLLaMA RSS: 社区第一时间讨论的新模型情报
"""
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "Mozilla/5.0 model-daily-bot/0.1"}

# 官方组织名单(可扩充)
ORGS = [
    "Qwen", "deepseek-ai", "zai-org", "moonshotai", "minimaxi",
    "01-ai", "openai", "meta-llama", "mistralai", "google", "nvidia",
    "microsoft", "allenai", "THUDM", "internlm", "TeleAI",
]

# GGUF/MLX/转换仓关键词 — 这些不是"发布",是搬运
CONVERT_RE = re.compile(r"(gguf|mlx|awq|gptq|exl2|onnx|mlc|ncnn|\.bin$|-quant)", re.I)
# 微调/镜像仓特征
JUNK_RE = re.compile(r"(finetune|fine-tune|-ft|-rl|lora|uncensored|merge|merged|v[0-9.]+-finetune)", re.I)


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def get_text(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def collect_org_repos(since):
    """各官方组织 48h 内新建的仓"""
    out = []
    for org in ORGS:
        try:
            models = get_json(f"https://huggingface.co/api/models?author={org}"
                              f"&sort=createdAt&direction=-1&limit=20")
        except Exception as e:
            print(f"  ! {org}: {e}", file=sys.stderr)
            continue
        for m in models:
            created = datetime.fromisoformat(m["createdAt"].replace("Z", "+00:00"))
            if created < since:
                break
            out.append({
                "source": "hf-org",
                "org": org,
                "repo": m["id"],
                "created": m["createdAt"],
                "downloads": m.get("downloads", 0),
                "likes": m.get("likes", 0),
                "pipeline": m.get("pipeline_tag"),
                "url": f"https://huggingface.co/{m['id']}",
            })
    return out


def collect_trending(since):
    """trending 榜 + 质量门: 新(48h) + 真实采用(dl>300 或 likes>20),排除转换/微调仓"""
    out = []
    seen = set()
    try:
        models = get_json("https://huggingface.co/api/models?sort=trendingScore"
                          "&direction=-1&limit=200")
    except Exception as e:
        print(f"  ! trending: {e}", file=sys.stderr)
        return out
    for m in models:
        name = m["id"]
        if name in seen or "/" not in name:
            continue
        seen.add(name)
        created = datetime.fromisoformat(m["createdAt"].replace("Z", "+00:00"))
        if created < since:
            continue
        dl, likes = m.get("downloads", 0), m.get("likes", 0)
        if dl < 300 and likes < 20:
            continue
        if CONVERT_RE.search(name) or JUNK_RE.search(name):
            continue
        out.append({
            "source": "hf-trending",
            "org": name.split("/")[0],
            "repo": name,
            "created": m["createdAt"],
            "downloads": dl,
            "likes": likes,
            "pipeline": m.get("pipeline_tag"),
            "url": f"https://huggingface.co/{name}",
        })
    return out


def collect_reddit():
    """r/LocalLLaMA RSS — 社区新模型讨论(标题过滤 release 类)"""
    out = []
    try:
        xml = get_text("https://www.reddit.com/r/LocalLLaMA/new/.rss?limit=50")
    except Exception as e:
        print(f"  ! reddit: {e}", file=sys.stderr)
        return out
    entries = re.findall(r"<entry>(.*?)</entry>", xml, re.S)
    kw = re.compile(r"(release[sd]?|announce|launch|new model|open[- ]weight|"
                    r"weights|apex|qwen|deepseek|llama|glm|mimo|kimi|minimax|gpt-oss|"
                    r"gemma|mistral|phi|nemotron|ernie|intern)", re.I)
    noise = re.compile(r"(help|advice|question|how (do|to)|recommend|setup|issue|error|"
                       r"benchmark request|PSA|local setup|prompt)", re.I)
    for e in entries[:50]:
        t = re.search(r"<title>(.*?)</title>", e)
        l = re.search(r'href="([^"]+)"[^>]*/>', e.split("<updated>")[0])
        u = re.search(r'<link[^>]*href="([^"]+)"', e)
        d = re.search(r"<updated>(.*?)</updated>", e)
        if not (t and u and d):
            continue
        title = t.group(1)
        if kw.search(title) and not noise.search(title):
            out.append({
                "source": "reddit",
                "title": title,
                "url": u.group(1),
                "updated": d.group(1),
            })
    return out


def main():
    since = datetime.now(timezone.utc) - timedelta(hours=48)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    data = {
        "date": day,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": 48,
        "hf_org": collect_org_repos(since),
        "hf_trending": collect_trending(since),
        "reddit": collect_reddit(),
    }
    out_path = f"data/{day}.json"
    import os
    os.makedirs("data", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    print(f"org={len(data['hf_org'])} trending={len(data['hf_trending'])} "
          f"reddit={len(data['reddit'])} -> {out_path}")


if __name__ == "__main__":
    main()
