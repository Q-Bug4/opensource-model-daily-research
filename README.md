# model-daily — 大模型发布日报

每天自动采集业界新发布的大模型,生成静态页面。

- 数据源(全部免鉴权):
  - HF 官方组织新仓(Qwen/deepseek/zai/moonshot/minimax/01-ai/openai/meta/mistral/google/nvidia/microsoft/allenai/THUDM/internlm/TeleAI,48h 窗口)
  - HF trending 榜 + 质量门(下载>300 或 点赞>20,排除 GGUF/MLX/微调/镜像仓)
  - Reddit r/LocalLLaMA RSS(社区第一手讨论,标题关键词过滤)
  - NVIDIA 开发者论坛 DGX Spark/GB10 板块 RSS(官方一手部署实测,最高优先级)
- **部署评估**(assess.py): 每个新模型给出 参数量/MoE激活/Q4显存 + 两台目标机器的结论:
  - Mac M4 Air 24GB (120GB/s, 16GB wired) — 能否装下、预期 tok/s
  - DGX Spark GB10 (273GB/s, 95GB) — 单台或多台 TP 结论
  - 速率公式: tok/s ≈ 带宽 ÷ 激活权重量(±50% 估算,Q4 超内存自动降档 Q3 建议)
- **AI 总结**(summarize.py): 用任意 OpenAI 兼容 API 生成
  - 单日页: 当天一段话总结 + 每个模型「是什么 / 优势 / 劣势 / 推荐度」
  - 今日推荐(picks): **首页直接展示**推荐模型 chips + 推荐理由
  - 未配置 API key 时自动跳过, 不影响采集与建站
- GitHub Actions 每天 UTC 01:30(北京 09:30)跑 collect → assess → summarize → build:
  bot 只把 `data/` 当天新文件提交回 main;站点由 workflow 构建后以 **Pages artifact** 直接部署
- GitHub Pages: 需在 Settings → Pages 把 Source 设为 **GitHub Actions**(docs/ 已不入库)
- 站点: 首页按天索引(含每天推荐),单日页含 AI 总结 + 部署评估表 +
  情报分区(DGX Spark → 部署实践 → NVIDIA 动态 → 社区讨论)

## 分支与同步(避免和 daily-bot 冲突)

- `main` 上只有两类提交: bot 的 `daily: <date>`(纯新增 data 文件) + 人工的功能合并
- 日常开发在 `dev` 分支;**生成物一律不提交**(docs/、当天 data/*.json、assess-cache 均已 gitignore)
- 同步基线永远无冲突, 因为 bot 只新增 data 文件、dev 只改源码, 路径不相交:

```bash
git switch dev
# ...改代码, 本地随便跑 pipeline 预览...
git fetch origin && git rebase origin/main   # 零冲突
git push -u origin dev                        # 然后 PR 或 ff 合进 main
```

## AI 总结配置

优先级: 环境变量 > `.env`(已 gitignore) > `llm.json`:

```bash
cp .env.example .env    # 填 base_url / api_key / model, 任何 OpenAI 兼容网关都行
pip install openai
python3 scripts/summarize.py            # 今天; 也可 python3 scripts/summarize.py 2026-09-22
python3 scripts/summarize.py --force    # 已有总结时强制重新生成
```

GitHub Actions: 在仓库 Settings → Secrets 配 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`(不配则当天无总结, 不阻塞构建)。

## 本地跑

```bash
python3 scripts/collect.py && python3 scripts/assess.py && python3 scripts/build_site.py
# 打开 docs/index.html (总结为可选步骤: 中间加 python3 scripts/summarize.py)
```

## 调整

- 加组织: `scripts/collect.py` 的 `ORGS` 列表
- 调质量门/过滤词: `collect_trending()` 和 `CONVERT_RE`/`JUNK_RE`
- 调社区分区(DGX Spark/部署实践/NVIDIA/一般): `build_site.py` 的 `SPARK_RE`/`DEPLOY_RE`/`NVIDIA_RE`
- 加 NVIDIA 论坛板块: `collect.py` 的 `NV_CATS`(Discourse RSS 路径)
- 调总结提示词/推荐个数: `scripts/summarize.py` 的 `build_prompt()` 和 `MAX_MODELS`
- 首页显示条数/样式: `scripts/build_site.py`

## 目录

```
scripts/collect.py      # 采集(HF API + Reddit RSS)
scripts/assess.py       # 部署评估(参数量/显存/两台机器结论)
scripts/summarize.py    # AI 总结(OpenAI 兼容 API, 写回 day JSON 的 summary 字段)
scripts/build_site.py   # 生成 docs/ 静态页
data/YYYY-MM-DD.json    # 每日原始数据(含 summary)
.env.example           # LLM 配置模板(拷为 .env 填好; .env 不入库)
docs/                   # 静态站(Pages 发布源)
```
