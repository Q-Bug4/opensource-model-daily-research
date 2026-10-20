#!/usr/bin/env python3
"""summarize.py — 用 OpenAI 兼容 API 为 data/<day>.json 生成 AI 总结。

输出写回 day JSON 的 "summary" 字段, build_site.py 负责渲染:
  overview : 一段话总结当天整体发布情况(单日页顶部)
  models[] : 每个模型 "是什么/优势/劣势/推荐度"(单日页 AI 总结区)
  picks[]  : 今日推荐模型 + 理由(首页直接展示)

配置(优先级: 环境变量 > .env > llm.json, 模板见 .env.example):
  LLM_BASE_URL / OPENAI_BASE_URL   任意 OpenAI 兼容网关, 如 https://api.openai.com/v1
  LLM_API_KEY  / OPENAI_API_KEY
  LLM_MODEL    / OPENAI_MODEL      如 gpt-4o-mini / deepseek-chat / ...

未配置 -> 提示后跳过(exit 0, 不影响构建); 调用失败 -> exit 1
(工作流里 continue-on-error, 不阻塞采集与建站)。已有 summary 跳过, --force 重新生成。
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

MAX_MODELS = 30   # 单日最多送多少个模型给 LLM(按热度截断)

SCHEMA_EXAMPLE = '''{
  "overview": "一段话(120-200字): 今天整体发布情况, 主线方向, 值得关注的点",
  "models": [
    {
      "repo": "与输入完全一致的 repo 名",
      "category": "LLM/VLM/图像/嵌入/音频/其他 之一",
      "what": "1-2 句: 这是什么模型、多大参数、谁发布的、定位是什么",
      "pros": "优势/亮点, 1-2 句",
      "cons": "劣势/局限/注意事项, 1-2 句",
      "recommendation": "强烈推荐|值得关注|一般|跳过 四选一"
    }
  ],
  "picks": [
    { "repo": "与 models 里完全一致的 repo 名", "reason": "为什么今天值得看它, 一句话" }
  ]
}'''


def load_dotenv(path=".env"):
    """KEY=VALUE 行, 支持 # 注释与引号值"""
    env = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k:
                env[k] = v
    return env


def load_config():
    """真实环境变量 > .env > llm.json"""
    dotenv = load_dotenv()
    f = json.load(open("llm.json")) if os.path.exists("llm.json") else {}

    def pick(env_names, file_key):
        for n in env_names:
            v = os.environ.get(n) or dotenv.get(n)
            if v:
                return v.strip()
        return f.get(file_key)

    return {
        "base_url": pick(("LLM_BASE_URL", "OPENAI_BASE_URL"), "base_url"),
        "api_key": pick(("LLM_API_KEY", "OPENAI_API_KEY"), "api_key"),
        "model": pick(("LLM_MODEL", "OPENAI_MODEL"), "model"),
    }


def collect_targets(data):
    """去重后的模型清单(合并 hf_org/hf_trending, 附部署评估), 官方仓优先再按热度, 截断"""
    items = {}
    for it in data.get("hf_org", []) + data.get("hf_trending", []):
        items.setdefault(it["repo"], it)
    assess = {a["repo"]: a for a in data.get("assessments", [])}

    out = []
    for repo, it in items.items():
        entry = {
            "repo": repo,
            "source": it["source"],
            "org": it.get("org"),
            "pipeline": it.get("pipeline"),
            "downloads": it.get("downloads", 0),
            "likes": it.get("likes", 0),
            "created": (it.get("created") or "")[:10],
        }
        a = assess.get(repo)
        if a and not a.get("skip"):
            entry["deploy"] = {
                "params_b": a.get("params_b"), "active_b": a.get("active_b"),
                "moe": a.get("moe"), "precision": a.get("precision"),
                "q4_gb": a.get("q4_gb"), "mac": a.get("mac"), "spark": a.get("spark"),
            }
        out.append(entry)
    out.sort(key=lambda e: (e["source"] != "hf-org", -(e["likes"] or 0)))
    return out[:MAX_MODELS]


def build_prompt(day, models, community_titles):
    payload = json.dumps({"models": models, "community_titles": community_titles},
                         ensure_ascii=False, indent=1)
    return (
        "你是一名大模型领域的资深分析师, 为中文「开源大模型发布日报」撰写 "
        f"{day} 的总结。\n\n"
        "输入 JSON 里: models 是当天抓到的新模型(repo/发布方/pipeline/downloads/likes 热度, "
        "deploy 为部署评估: mac=Mac M4 Air 24GB, spark=DGX Spark 95GB, "
        "✅可跑/⚠️勉强/❌装不下 + 估算 tok/s); community_titles 是当日社区/论坛帖子标题, "
        "方括号为来源(r/LocalLLaMA = Reddit, NVIDIA 论坛·xx = NVIDIA 官方论坛, "
        "其中 DGX Spark 是读者最关心的部署目标), 仅供了解热度。\n"
        "你无法联网, 只能依据这些元数据和既有知识判断。\n\n"
        "输出严格遵循以下 JSON 结构:\n" + SCHEMA_EXAMPLE + "\n\n要求:\n"
        f"1. models 逐个覆盖输入的全部 {len(models)} 个模型, repo 字段与输入逐字一致\n"
        "2. 不认识的模型按名字/发布方/pipeline 谨慎推断, 并在 cons 注明「新发布, 暂无实测」; "
        "严禁编造 benchmark 数字\n"
        "3. picks 挑 1-4 个对本地部署/开源社区最值得关注的, 确实没有就给空数组\n"
        "4. 全文简体中文(repo 名除外); 只输出 JSON, 不要 markdown 代码块\n\n"
        f"输入:\n{payload}"
    )


def parse_json(text):
    """容忍 markdown 代码块/前后杂讯, 抠出 JSON"""
    t = re.sub(r"^```(?:json)?\s*|```\s*$", "", text.strip(), flags=re.M).strip()
    a, b = t.find("{"), t.rfind("}")
    if a >= 0 and b > a:
        t = t[a:b + 1]
    return json.loads(t)


def ask(client, model, prompt):
    try:
        r = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}],
            temperature=0.3, response_format={"type": "json_object"})
    except Exception:
        # 部分兼容网关不支持 response_format, 退回普通调用重试一次
        r = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}],
            temperature=0.3)
    return r.choices[0].message.content


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    day = args[0] if args else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    force = "--force" in sys.argv

    path = f"data/{day}.json"
    if not os.path.exists(path):
        sys.exit(f"no {path}; run collect.py first")
    data = json.load(open(path))
    if data.get("summary") and not force:
        print(f"{day}: summary 已存在(model={data['summary'].get('model')}), 跳过; --force 可重新生成")
        return

    cfg = load_config()
    if not all(cfg.values()):
        missing = [k for k, v in cfg.items() if not v]
        print(f"!! 未配置 LLM(缺 {','.join(missing)}): 设环境变量 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL "
              f"或拷 .env.example 为 .env 填好; 本次跳过总结", file=sys.stderr)
        return

    models = collect_targets(data)
    if not models:
        print(f"{day}: 今天没有抓到模型, 跳过总结")
        return
    community = ([f"[r/{it.get('sub') or 'LocalLLaMA'}] {it['title']}"
                  for it in (data.get("reddit") or [])][:20]
                 + [f"[NVIDIA 论坛·{it.get('sub', '')}] {it['title']}"
                    for it in (data.get("nvidia_forum") or [])][:15])
    prompt = build_prompt(day, models, community)

    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("!! 需要 openai 库: pip install openai")

    try:
        client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"],
                        timeout=180, max_retries=2)
        parsed = parse_json(ask(client, cfg["model"], prompt))
    except Exception as e:
        sys.exit(f"!! summarize 失败: {e}")

    # 校验: models 只留 repo 能对上的; picks 必须指向 models 里存在的 repo
    known = {m["repo"] for m in models}
    out_models = [{"repo": m["repo"], "category": str(m.get("category", "")),
                   "what": str(m.get("what", "")), "pros": str(m.get("pros", "")),
                   "cons": str(m.get("cons", "")),
                   "recommendation": str(m.get("recommendation", "值得关注"))}
                  for m in parsed.get("models", []) if m.get("repo") in known]
    if not out_models:
        sys.exit("!! LLM 返回的 models 里没有任何能对上输入 repo 的条目, 丢弃本次总结")
    picks = [{"repo": p["repo"], "reason": str(p.get("reason", ""))}
             for p in parsed.get("picks", []) if p.get("repo") in known]

    data["summary"] = {
        "model": cfg["model"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overview": str(parsed.get("overview", "")),
        "models": out_models,
        "picks": picks,
    }
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"summary -> {path} (model={cfg['model']}, models={len(out_models)}/{len(models)}, "
          f"picks={len(picks)})")


if __name__ == "__main__":
    main()
