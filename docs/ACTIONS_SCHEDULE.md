# GitHub Actions 定时排查备忘

## 现象（截至 2026-11-02）

| Workflow | `event=schedule` 次数 | 说明 |
|----------|----------------------|------|
| 龙头战法·竞价推送 | **0** | 从未自动跑过 |
| 龙头战法·收盘推送 | **1** | 仅 10-30 22:00 北京（应为 15:10） |
| daily_stock_analysis | 多次 | 同账号公开库 schedule 正常 |

## 2026-11-02（周一）9:25 北京

- UTC 窗口 `00:00–04:00` 内 **无任何** dragon-head-lark-bot run。
- 本机 **launchd 未加载**（`com.dragon-head-lark-bot.auction` 不存在）。
- 非周末：cron `1-5` 应包含周一。

## 当前方案

1. **`dragon-head-scheduler.yml`**：极简 cron，用 `GITHUB_TOKEN` `gh workflow run` 触发竞价/收盘（避免在重 workflow 上挂 schedule）。
2. **（推荐备份）** 在 `daily_stock_analysis` 增加 `dragon-head-auction-dispatch.yml`，用 PAT 跨库 dispatch（见该 workflow 注释）。
3. **Mac launchd**：`scripts/trigger-auction.sh` / `trigger-close.sh`。
