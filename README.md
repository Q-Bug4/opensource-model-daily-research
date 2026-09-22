# model-daily — 大模型发布日报

每天自动采集业界新发布的大模型,生成静态页面。

- 数据源(全部免鉴权):
  - HF 官方组织新仓(Qwen/deepseek/zai/moonshot/minimax/01-ai/openai/meta/mistral/google/nvidia/microsoft/allenai/THUDM/internlm/TeleAI,48h 窗口)
  - HF trending 榜 + 质量门(下载>300 或 点赞>20,排除 GGUF/MLX/微调/镜像仓)
  - Reddit r/LocalLLaMA RSS(社区第一手讨论,标题关键词过滤)
- GitHub Actions 每天 UTC 01:30(北京 09:30)跑 `scripts/collect.py` + `scripts/build_site.py`,结果提交回本仓
- GitHub Pages 从 `docs/` 出静态站: 首页按天索引,单日页分三区(官方/trending/社区)

## 本地跑

```bash
python3 scripts/collect.py && python3 scripts/build_site.py
# 打开 docs/index.html
```

## 调整

- 加组织: `scripts/collect.py` 的 `ORGS` 列表
- 调质量门/过滤词: `collect_trending()` 和 `CONVERT_RE`/`JUNK_RE`
- 首页显示条数/样式: `scripts/build_site.py`

## 目录

```
scripts/collect.py      # 采集(HF API + Reddit RSS)
scripts/build_site.py   # 生成 docs/ 静态页
data/YYYY-MM-DD.json    # 每日原始数据
docs/                   # 静态站(Pages 发布源)
```
