# 龙头战法 → 飞书群定时推送

参考 [ZhuLinsen/daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) 的 **GitHub Actions 定时 + 飞书 Webhook** 模式，做两件独立任务：

| 任务 | 默认时间（北京时间） | 脚本 |
|------|----------------------|------|
| **收盘复盘 + 次日观察名单** | 工作日 **15:10** | `run_close.py` |
| **竞价快报 + 观察名单裁决** | 工作日 **9:25** | `run_auction.py` |

行情默认走 **akshare（东财/新浪）**；环境摘要另从 **[连板网 lianban.net](https://lianban.net/)** 拉公开复盘（日复盘页 + RSS）：情绪温度、封板率、主线、当日结论。收盘报告对照当日，竞价报告引用 **上一交易日** 作环境锚。

**收盘推送模板**（飞书 Markdown）：环境→名单前提表 + **次日观察名单表**（含硬条件备注）+ 触发止损 + 执行顺序 + 一句话。

**观察名单默认每天变**：`WATCHLIST_MODE=auto` 时由 **当日涨停池**（连板≥2、硬条件、主线 `MAINLINE_KEYWORD`）自动生成 4 只，**不必**每天改 GitHub Variables。仅当你要强行指定时用 `manual` / `merge` + `WATCHLIST`。

**体温计也每天变**：在 `MAINLINE_KEYWORD` 对应票里取 **空间龙**（会在行业/涨停原因/概念里搜关键字；搜不到时 **去掉消费支线**，避免把上海九百这类全市场 5 板误当机器人体温计）。只有某天要钉死一只时才填 `THERMOMETER`。

## 1. 飞书群机器人（推荐，与 DSA 相同）

1. 飞书群 → **设置** → **群机器人** → **添加机器人** → **自定义机器人**
2. 复制 **Webhook 地址**，可选开启 **签名校验**
3. **长图表格推送（推荐）**：在 [飞书开放平台](https://open.feishu.cn/) 建企业自建应用，开通 **发送消息 / 上传图片** 权限，把 `App ID`、`App Secret` 配到 Secrets（`FEISHU_APP_ID`、`FEISHU_APP_SECRET`）。**收盘复盘、竞价快报** 均会 **先发长图（含表格）**，再发 Markdown 文本。
4. 写入 `.env` 或 GitHub Secrets：

```bash
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxx
FEISHU_WEBHOOK_SECRET=   # 可选
FEISHU_APP_ID=           # 长图上传（可选）
FEISHU_APP_SECRET=
WATCHLIST_MODE=auto
MAINLINE_KEYWORD=机器人
# THERMOMETER=   # 可选，不填则每日自动选主线空间龙
# WATCHLIST=   # 仅 merge/manual 时需要
```

## 2. 本地试跑

```bash
cd dragon-head-lark-bot
cp .env.example .env   # 编辑 Webhook
pip install -r requirements.txt
python run_close.py
python run_auction.py
```

## 3. GitHub Actions（零服务器，参考 DSA）

1. 把本目录推到 **你的** GitHub 仓库（可 fork 后只保留本 bot 目录，或单独建 repo）
2. `Settings` → `Secrets`：`FEISHU_WEBHOOK_URL`、（可选）`FEISHU_WEBHOOK_SECRET`、`OPENAI_API_KEY`
3. `Settings` → `Variables`：`WATCHLIST_MODE`、`MAINLINE_KEYWORD`；（可选）`WATCHLIST`、`THERMOMETER` 钉住某天
4. `Settings` → **Actions** → **General**：允许 Actions
5. Workflow：**龙头战法·竞价推送**（9:25）、**龙头战法·收盘推送**（15:10）；手动二合一用 **龙头战法飞书推送**

### 为什么之前 `schedule` 从不触发？

| 仓库 | 可见性 | `event=schedule` |
|------|--------|------------------|
| `daily_stock_analysis` | **public** | ✅ 每天有 run |
| 本仓库（改之前） | **private** | ❌ 始终为 0 |

在 **GitHub Free 个人账号** 下，**私有仓库的 `on.schedule` 不会进调度队列**（官方文档几乎不写，但和 DSA 公开库对比可复现）；`workflow_dispatch` 不受影响。改 cron、开 Actions 开关都无效。

**已处理：** 本仓库已改为 **public**（与 DSA 一致；Webhook/App Secret 仍在 GitHub Secrets，不会进代码）。

Cron（`Asia/Shanghai`）：竞价 **9:25**、收盘 **15:10**（可能比整点晚几分钟）。

若必须私有：升级 **GitHub Pro**，或保留下面 launchd / 外部 cron 调 `workflow_dispatch`。

## 4. Mac 定时触发（私有库或备份）

与 GitHub 定时**二选一**，同时开可能 **重复推送**。

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.dragon-head-lark-bot.auction.plist 2>/dev/null
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.dragon-head-lark-bot.close.plist 2>/dev/null
```

需要本机备份时再 `cp com.dragon-head-lark-bot.*.plist ~/Library/LaunchAgents/` 并 `launchctl bootstrap`；见 `scripts/trigger-*.sh`。

## 5. 与 daily_stock_analysis 的关系

| 能力 | DSA | 本项目 |
|------|-----|--------|
| 定时 | Actions `00-daily-analysis.yml` 18:00 | 9:25 + 15:10 双任务 |
| 飞书 | `FEISHU_WEBHOOK_URL` | 相同 |
| 内容 | 自选股 AI 决策仪表盘 | **龙头战法** 涨停池 + 观察名单 + 自动体温计 |
| LLM | 必选其一 API Key | **可选** `OPENAI_*` 润色 |

若要 **完全用 DSA 跑**：Fork DSA，在 `STOCK_LIST` 填观察代码，另加一条 workflow 在 9:25 跑自定义脚本；或把本仓库 `src/` 拷入 DSA 作为 `scripts/dragon_head/` 调用。

## 6. 用 lark-cli 发群（可选）

Webhook 足够推送 Markdown。若要用 **应用机器人 + chat_id**：

```bash
lark-cli im +chat-search --query "你的群名" --as bot
lark-cli im +messages-send --chat-id oc_xxx --markdown --content "..." --as bot
```

需机器人在群内；发送前需用户确认（见 lark-im skill）。

## 7. 自定义战法

编辑 `config/methodology_snippet.md` 与 `src/report_*.py` 中的规则函数；完整四步/否决线可逐步迁入 `pick_watchlist()`。

**不构成投资建议。**
