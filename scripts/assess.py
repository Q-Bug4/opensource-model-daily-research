#!/usr/bin/env python3
"""assess.py — 对 data/<day>.json 里的 HF 模型做部署评估: 显存/速率/机器结论。

硬件基线(实测口径, 见 ~/ai-infra/docs/hardware-gb10.md 与 research/2026-09-21 报告):
  Mac M4 Air 24GB: 带宽 ~120 GB/s, GPU 可锁内存默认 ~16GB (可调至 18)
  DGX Spark GB10:  带宽 ~273 GB/s, 单台可用 ~95GB; N 台 TP 有效带宽 ~ N*273

速率估算: tok/s ≈ 有效带宽 ÷ 每 token 激活权重 GB (±50%, 长上下文会降)
  dense: 每 token 读全部权重; MoE: 只读激活部分(名字里的 A3B / 架构判断)
缓存: data/assess-cache.json (repo -> 评估结果), 避免重复拉 API。
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 model-daily-bot/0.1"}

BYTES_PER_PARAM = {"fp8": 1.05, "bf16": 2.05, "float8": 1.05, "bfloat16": 2.05,
                   "mxfp4": 0.56, "nvfp4": 0.56, "int4": 0.58}
Q4_BPB = 0.58   # Q4/NVFP4 bytes-per-param
Q8_BPB = 1.10

MAC = {"name": "Mac M4 Air 24GB", "bw": 120, "mem": 16}
SPARK = {"name": "DGX Spark GB10", "bw": 273, "mem": 95}

AOE_RE = re.compile(r"(\d+\.?\d*)B\s*[-‑]?\s*A\s*(\d+\.?\d*)B", re.I)   # 30B-A3B
SIZE_RE = re.compile(r"(\d+\.?\d*)B", re.I)
MOE_ARCH_RE = re.compile(r"(moe|mixtral|deepseek_v\d|glm|nemotron|granite.*moe|"
                         r"qwen3.*moe|minicpm|hunyuan|ernie)", re.I)
MOE_NAME_RE = re.compile(r"(a\d+b|-a\d|deepseek|glm-|kimi|minimax|hunyuan|ernie|"
                         r"nemotron|gpt-oss|nllb)", re.I)
IMAGE_PIPE = {"text-to-image", "image-to-image", "unconditional-image-generation",
              "image-to-video", "text-to-video"}


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def fetch_model_info(repo):
    try:
        m = get_json(f"https://huggingface.co/api/models/{repo}")
    except Exception as e:
        return {"error": str(e)}
    saf = m.get("safetensors") or {}
    total_bytes = saf.get("total") or 0
    cfg = m.get("config") or {}
    quants = (m.get("cardData") or {}).get("quantized_from")  # rarely present
    applied = []
    # config.quantizations 字段: 应用过的量化
    for q in (m.get("quantization") or {}).get("bits", []) if isinstance(m.get("quantization"), dict) else []:
        applied.append(q)
    prec = "bf16"
    name_l = repo.lower()
    if "fp8" in name_l or "float8" in name_l:
        prec = "fp8"
    if "mxfp4" in name_l or "nvfp4" in name_l or "fp4" in name_l:
        prec = "nvfp4"
    arch = ""
    try:
        arch = (cfg.get("architectures") or [""])[0]
    except Exception:
        pass
    return {"bytes": total_bytes, "prec": prec, "arch": arch,
            "pipeline": m.get("pipeline_tag") or cfg.get("pipeline_tag")}


def estimate(repo, info):
    if info.get("error") or not info.get("bytes"):
        return None
    bpb = BYTES_PER_PARAM.get(info["prec"], 2.05)
    params_b = info["bytes"] / (bpb * 1e9)          # 总参数, B
    if params_b <= 0.01:
        return None

    # 名字里的总参数量优先于字节反推(仓库可能是 fp8 混精/部分分片, 反推偏低)
    nm = SIZE_RE.search(repo)
    if nm and 0.35 < float(nm.group(1)) / max(params_b, 0.01) < 2.5:
        params_b = float(nm.group(1))

    # 激活参数
    m = AOE_RE.search(repo)
    if m:
        active_b = float(m.group(2))
        moe = True
    elif MOE_ARCH_RE.search(info["arch"] or "") or MOE_NAME_RE.search(repo):
        moe = True
        active_b = params_b * 0.08          # DeepSeek/Qwen MoE 激活比通常 5-12%
    else:
        active_b = params_b
        moe = False

    q4_gb = params_b * Q4_BPB
    fp8_gb = params_b * BYTES_PER_PARAM["fp8"]
    act_q4_gb = max(active_b * Q4_BPB, 0.3)
    is_image = (info.get("pipeline") or "") in IMAGE_PIPE
    is_embed = (info.get("pipeline") or "") in ("embedding", "feature-extraction",
                                                "sentence-similarity")

    def verdict(machine, size_gb):
        """返回 (状态, tok/s 或 None, 说明)"""
        if is_image or is_embed:
            if size_gb > machine["mem"]:
                return "❌", None, "装不下"
            return "✅", None, "图像/嵌入模型" if is_image else "嵌入模型, 秒级"
        overhead = 1.5 + min(0.05 * size_gb, 6)     # KV+运行时粗估
        if size_gb + overhead > machine["mem"] * 1.12:
            # Q4 装不下 → 试 Q3 降档
            q3_gb = params_b * 0.44
            if q3_gb + overhead <= machine["mem"] * 1.12:
                tps = machine["bw"] / (active_b * 0.44 + 0.5)
                return "⚠️", tps, f"Q4({size_gb:.0f}GB)超内存,需Q3({q3_gb:.0f}GB)"
            return "❌", None, f"需 {size_gb:.0f}GB > {machine['mem']}GB"
        tps = machine["bw"] / (act_q4_gb + 0.5)
        ok = "✅" if tps >= 15 else ("⚠️" if tps >= 8 else "❌")
        return ok, tps, ""

    mac_ok, mac_tps, mac_note = verdict(MAC, q4_gb)
    # Spark: 先试 NVFP4(原生) 单台, 不行算 N 台
    if q4_gb + 3 <= SPARK["mem"]:
        spark_desc, spark_tps, nodes = "1 台", SPARK["bw"] / (act_q4_gb + 0.5), 1
        spark_ok = "✅" if spark_tps >= 15 else ("⚠️" if spark_tps >= 8 else "❌")
    else:
        nodes = max(2, -(-q4_gb // (SPARK["mem"] - 8)))
        spark_tps = (SPARK["bw"] * nodes) / (act_q4_gb + 0.5)
        spark_desc = f"{int(nodes)} 台 TP"
        spark_ok = "✅" if spark_tps >= 15 else ("⚠️" if spark_tps >= 8 else "❌")

    def fmt_tps(t):
        return f"~{t:.0f} tok/s" if t else ""

    return {
        "repo": repo,
        "params_b": round(params_b, 1),
        "active_b": round(active_b, 1) if moe else None,
        "moe": moe,
        "precision": info["prec"],
        "q4_gb": round(q4_gb, 1),
        "fp8_gb": round(fp8_gb, 1),
        "pipeline": info.get("pipeline"),
        "mac": f"{mac_ok} {fmt_tps(mac_tps)} {mac_note}".strip(),
        "spark": f"{spark_ok} {spark_desc} {fmt_tps(spark_tps) if not is_image else ''}".strip(),
    }


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else \
        datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"data/{day}.json"
    if not os.path.exists(path):
        sys.exit(f"no {path}; run collect.py first")

    cache_path = "data/assess-cache.json"
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}

    data = json.load(open(path))
    targets = [it["repo"] for it in data.get("hf_org", [])] + \
              [it["repo"] for it in data.get("hf_trending", [])]

    results = []
    for repo in targets:
        if repo not in cache:
            info = fetch_model_info(repo)
            cache[repo] = {"info": info,
                           "assessed": estimate(repo, info) or {"repo": repo, "skip": True},
                           "at": datetime.now(timezone.utc).isoformat()}
            time.sleep(0.3)
        a = cache[repo].get("assessed")
        if a and not a.get("skip"):
            results.append(a)

    data["assessments"] = results
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    with open(cache_path, "w") as f:
        json.dump(cache, f, ensure_ascii=False)

    print(f"assessed {len(results)}/{len(targets)} models -> {path}")
    for a in results:
        act = f"/{a['active_b']}B" if a.get("active_b") else ""
        print(f"  {a['repo']}: {a['params_b']}B{act} q4={a['q4_gb']}GB "
              f"mac[{a['mac']}] spark[{a['spark']}]")


if __name__ == "__main__":
    main()
