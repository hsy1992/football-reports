# 足球盘口情报站 · Football Odds Intelligence

一个面向 **2026 FIFA 世界杯**的全自动足球盘口分析系统：定时抓取多家博彩公司赔率 → 用纯数学模型反推公平概率与期望值（EV）→ 生成赛博朋克风 HTML 报告 → 自动模拟下注并用真实赛果复盘校准。全程通过 GitHub Actions 调度，报告发布到 GitHub Pages。

> ⚠️ **免责声明**：本系统为纯数据分析研究项目，**不构成投注建议**。模型以基准公司赔率为锚，EV 仅为相对锚点的偏差；伤停、阵容等场外信息未纳入模型。博彩有风险。

---

## 核心特性

- **纯数学，零主观输入**：模型 100% 由市场赔率反推，不引入人为判断。以 Pinnacle（职业盘）+ Betfair 交易所（真实撮合价）为双锚点。
- **幂法去水 + 泊松/Dixon-Coles 模型**：用幂法去除庄家抽水（修正 favourite-longshot bias），再以泊松分布 + Dixon-Coles 低比分修正拟合 (λ主, λ客, ρ)，同时满足 1X2 / 让球 / 大小球三组零期望约束。
- **自校准**：每日用已完赛比赛的真实赛果给模型对账，但仅在样本量过统计门槛（≥20 场）后才调整参数——单场偶然结果不会扭曲模型。
- **模拟下注复盘**：开赛前 1.5 小时自动按全场最优价落单三笔模拟注单（亚盘/大小球/波胆），赛果回填后自动结算，长期追踪 ROI。这是验证策略是否真正有效的"试金石"。
- **额度精打细算**：The Odds API 按调用计费，系统通过同赛事批量抓取（多场=一次调用）、批量响应顺带免费存档、收窄抓取窗口等手段，较旧方案省约 60% 额度。
- **全自动流水线**：3 个 GitHub Actions 工作流（抓取/赛果/校准）+ 自动提交发布，无需人工干预。

---

## 系统架构

```
                GitHub Actions (定时调度)
                 ┌─────────────────────┐
   每30min ─────▶│  scrape.yml          │──▶ scrape.py
   每15min ─────▶│  results.yml         │──▶ scrape.py --results-only
   每天09:00 ───▶│  calibrate.yml       │──▶ calibrate.py
                 └─────────────────────┘
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
   数据源抓取          SQLite 存储        分析与报告
  (odds_api.py       (db.py)           (analyze.py)
   espn/fbref/                            │
   dongqiudi/                             ▼
   oddsportal)                    reports/*.html  (赛博朋克仪表盘)
        │                                 │
        ▼                                 ▼
   quota.json                      rsync → docs/  → git push
   (额度监控)                       GitHub Pages 公网发布
```

### 数据流（单次抓取 `scrape.py`）

1. **筛选到期比赛**：按距开赛时间判断是否该抓（>8h 跳过；8h~1.5h 每 6h；≤1.5h 每 30min）。
2. **批量抓赔率**：同一赛事多场比赛合并为一次 API 调用（同价 3 额度）；批量响应里其他场次顺带免费存档（passive）。
3. **降级容错**：The Odds API 失败 → 自动切 OddsPortal（Playwright）；单场失败不影响其他场。
4. **模拟下注**：进入临场 1.5h 窗口的首轮，按当下最优价落单（幂等，一场一次）。
5. **球队数据**：仅重点场抓取 ESPN 近况（FBref 备用补 xG）+ 懂球帝伤停。
6. **生成报告**：开赛前 72h 起每轮刷新 HTML（零额度成本，仅渲染已有快照）。
7. **回填赛果**：开赛后 110min 起每轮查 ESPN 比分 → 结算注单 → 生成完赛定稿报告。
8. **发布**：rsync 到 docs/ → git commit & push 到 GitHub Pages。

---

## 数学模型（`analyze.py` 的核心）

这是整个系统的灵魂，全部为可复现的数学推导：

### 1. 去水（Demargin）
庄家赔率含抽水，直接取倒数求和 >1。系统用**幂法**解 `k` 使 `Σ(1/o)^k = 1`，相比等比例法对冷门（高赔率）方向去水更多，修正 favourite-longshot bias。

### 2. 锚点加权
取 Pinnacle + Betfair 交易所的平滑报价（近 3 帧加权平均，避免单帧调价噪声），分别去水后等权平均得公平 1X2 概率。

### 3. 模型拟合（`fit_model`）
网格搜索 (λ主, λ客, ρ)，约束同时匹配：
- 公平 1X2 三概率
- 让球盘零 EV（`fair_ah_home`）
- 大小球零 EV（`fair_over_odds`）

其中 ρ（低比分相关系数）**由市场平局概率反推，不取经验值**，限制在 [-0.35, 0.10]。

### 4. 推导任意盘口公平赔率与 EV
由模型比分矩阵推导净胜球分布、总进球分布，进而算任意让球线/大小球线的公平赔率（二分法解 EV=0），与各家实盘对比得 EV。

### 5. 波胆（正确比分）
修正后比分矩阵的概率排名，取 top 8。

> **局限**：模型校准基于 Pinnacle，对 Pinnacle 自身盘 EV 必然接近 0；价值信号主要体现在其他公司偏离 Pinnacle 的地方。

---

## 目录结构

```
football-odds-reports/
├── app/                        # 主程序
│   ├── config.py               # 全局配置（调度规则、博彩公司、时区等）
│   ├── db.py                   # SQLite 存取层 + schema + 迁移
│   ├── scrape.py               # 抓取入口（GitHub Actions 每 30min 调用）
│   ├── analyze.py              # 盘口数学解析 + HTML 报告生成（~1500 行）
│   ├── calibrate.py            # 校准验证：赛果对账 + 教训回流
│   ├── odds_api.py             # The Odds API 封装（队名中英映射、额度监控）
│   ├── calibration.json        # 校准反馈（analyze.py 自动读取）
│   ├── quota.json              # API 额度余量（总览页展示）
│   ├── football.db             # SQLite 数据库
│   ├── requirements.txt        # requests / beautifulsoup4 / lxml
│   └── sources/                # 数据源模块
│       ├── odds_api.py         # 主源：The Odds API（赔率）
│       ├── oddsportal.py       # 降级源：Playwright 抓 OddsPortal（含 bet365）
│       ├── espn.py             # 主源：球队近况 / 赛果 / 球场（无 key）
│       ├── fbref.py            # 备用源：近况 + xG（遵守 robots.txt）
│       ├── dongqiudi.py        # 备用源：伤停（懂球帝，尽力而为）
│       └── venues.py           # 2026 世界杯球场静态库 + 免费天气
├── docs/                       # GitHub Pages 发布目录（累积制）
│   ├── index.html              # 总览主页（系统唯一入口）
│   └── match_<ID>_盘口解析.html  # 各场比赛报告（已积累 100+ 场）
├── .github/workflows/
│   ├── scrape.yml              # 每 30min：抓取 + 报告 + 回填 + 发布
│   ├── results.yml             # 每 15min：仅查赛果（零额度）
│   └── calibrate.yml           # 每天 09:00 (北京)：校准对账
└── .gitignore                  # 忽略 logs/ reports/ .env
```

> 注：`app/reports/` 与 `app/logs/` 在 .gitignore 中（运行时产物）；`docs/` 是已发布的累积报告，纳入版本库。

---

## 数据源

| 模块 | 数据 | 类型 | 说明 |
|------|------|------|------|
| `sources/odds_api.py` | 赔率（1X2/亚盘/大小球） | API | 主源，消耗额度；事件列表接口免费 |
| `sources/oddsportal.py` | 赔率（含 bet365） | Playwright | 降级源，主源不可用时启用 |
| `sources/api_football.py` | 球员/大名单/伤停/教练/裁判/首发 | API | 赔率之外的信息层主源（付费，免费档100/天）；见 `SETUP_API.md` |
| `sources/espn.py` | 球队近况 / 赛果 / 球场 | 公共 JSON | 主力源，无反爬、无需 key |
| `sources/fbref.py` | 近况 + xG/xGA | 网页抓取 | ESPN 备用；**注意 FBref 现挂 Cloudflare，requests 已被挡**（见下） |
| `sources/dongqiudi.py` | 伤停 | API | 懂球帝，尽力而为，失败返回 None（实际长期返回空，已由 API-Football 替代） |
| `sources/venues.py` | 球场属性 + 天气 | 静态库 + API | 球场固定；天气用 open-meteo（免费） |

### 队名映射
国家队中文/英文映射表在 `odds_api.py` 的 `ZH_EN` / `EN_ZH`；ESPN 另有 `_ALIASES` 处理各源写法差异（如 Czechia↔Czech Republic）。The Odds API 不提供 bet365，bet365 只能通过 OddsPortal 获得。API-Football 队名差异（South Korea↔Korea Republic 等）在 `sources/api_football.py` 的 `TEAM_ALIASES` 处理。

### 关于 FBref 与 xG
FBref 现已挂 Cloudflare 交互挑战，`requests`/`cloudscraper`/`curl_cffi`/headless Playwright 均无法通过，故 `team_stats` 实际长期回退到 ESPN（无球员级 xG）。球员级高阶数据改走 API-Football（覆盖射门/射正/抢断/拦截/传球/过人等，**唯一缺 xG/xA**，`player_stats` 表预留空列待日后补）。详见 `可行性技术方案-球小策对标.md`。

---

## 数据库 Schema（SQLite，`db.py`）

所有时间字段存 UTC ISO 字符串，显示时转北京时间。

| 表 | 用途 |
|----|------|
| `matches` | 比赛主表：队名、开赛时间、状态（tracking/passive/finished）、sport_key、event_id、球场、比分 |
| `odds_snapshots` | 赔率快照（只追加不覆盖）：match_id、来源、公司、市场（1x2/ah/ou）、盘口线、三端赔率 |
| `team_stats` | 球队近况 + 伤停（JSON，ESPN 球队级） |
| `scrape_runs` | 抓取运行记录（ok/partial/error） |
| `paper_bets` | 模拟注单：玩法、选择、策略、注额、赔率、EV、结果、盈亏 |
| `api_team_ids` | 队名 -> API-Football team_id 缓存 |
| `players` | 球员档案（姓名/位置/年龄/国籍/号码/是否伤） |
| `player_stats` | 赛季统计（射门/射正/抢断/拦截/传球/过人/对抗/牌/分钟/评分；预留 xg/xag 空列） |
| `injuries` | 伤停清单（API-Football，替代懂球帝） |
| `coaches` | 主教练信息 |

### 比赛状态机
- **passive**：批量响应里顺带存档的场次，不调度、不显示，只攒数据。
- **tracking**：正式跟踪（手动添加，或涉及 FIFA Top10 强队自动升格，或属于 `AUTO_TRACK_SPORTS` 赛事）。
- **finished**：已开赛。

`db._migrate()` 实现老库平滑加列（赛果回填、注额、策略、球场缓存列）。

---

## 自动化调度（GitHub Actions）

| 工作流 | 频率 | 作用 | 额度消耗 |
|--------|------|------|----------|
| `scrape.yml` | 每 30min | 抓赔率 + 球队数据 + 生成报告 + 回填赛果 + 结算 + 发布 | 有 |
| `results.yml` | 每 15min | 仅查完赛结果 + 结算 + 刷新页面（`--results-only`） | 零 |
| `calibrate.yml` | 每天 01:00 UTC | 赛果对账 + 教训回流 + 模拟下注复盘 | 零 |

- 三个工作流共用 `concurrency.group: publish` 串行化，避免推送竞争。
- 发布用 `rsync -a`（不带 `--delete`）：CI 每次全新检出，`docs/` 已完赛比赛的历史报告必须累积保留。
- 推送带 rebase 重试（防与其它工作流竞争）。
- `ODDS_API_KEY` / `ODDS_API_KEY_FALLBACK` 存 GitHub Secrets。

---

## 配置说明（`app/config.py`）

| 配置项 | 值 | 说明 |
|--------|----|------|
| `TZ` | Asia/Shanghai | 所有输入/显示按北京时间，库内存 UTC |
| `BOOKMAKERS` | pinnacle 等 10 家 | 最多 10 家（10 家以内额度消耗相同） |
| `MARKETS` | h2h,spreads,totals | 欧赔 1X2 / 亚洲让球 / 大小球 |
| `WINDOW_FAR_HOURS` | 8 | 开赛前 8h 以外不抓 |
| `INTERVAL_FAR_MIN` | 360 | 8h~1.5h：每 6h 抓一次 |
| `WINDOW_NEAR_HOURS` | 1.5 | 临场密集窗口 |
| `INTERVAL_NEAR_MIN` | 30 | 1.5h 以内：每 30min（末帧≈收盘价） |
| `TEAM_STATS_INTERVAL_MIN` | 720 | 球队数据每 12h 刷新 |
| `REPORT_WINDOW_HOURS` | 72 | 开赛前 72h 起生成报告（零额度） |
| `AUTO_TRACK_SPORTS` | soccer_fifa_world_cup | 整赛事自动密集跟踪 |
| `TOP_TEAMS` | FIFA 前 10 | 涉及强队自动升格为重点 |
| `KNOCKOUT_START_ID` | 73 | 小组赛/淘汰赛分界（埋点观察用） |
| `QUOTA_WARN_THRESHOLD` | 150 | 额度低于此值弹通知（每 24h 最多一次） |

API key 放 `app/.env`（已在 .gitignore）：
```
ODDS_API_KEY=xxx
ODDS_API_KEY_FALLBACK=xxx   # 主 key 耗尽(401)时自动启用
```

---

## 本地运行

```bash
cd app
pip install -r requirements.txt

# 单场分析（生成 reports/match_<ID>_盘口解析.html）
python analyze.py <比赛ID>

# 手动抓取
python scrape.py --force            # 忽略频率限制立即抓全部
python scrape.py --match-id 1       # 只抓某场
python scrape.py --odds-only        # 只抓赔率
python scrape.py --results-only     # 只回填赛果（零额度）

# 校准对账
python calibrate.py

# 抓取球员/球队信息（API-Football，需先在 app/.env 配 API_FOOTBALL_KEY）
python fetch_players.py --test            # 校验 key + 显示额度
python fetch_players.py --team Argentina  # 单队
python fetch_players.py                   # 全量 48 支国家队
python fetch_players.py --skip-stats      # 仅大名单（省额度）
python fetch_players.py --max-calls 90    # 免费档分批，跑到 90 次停
```

> 球员数据接入详见 `app/SETUP_API.md`。OddsPortal 降级源需额外安装：`pip install playwright && playwright install chromium`

---

## 关键设计决策与"教训回流"

本项目最突出的特质是**诚实地用数据否定自己的假设**——代码注释和 `calibration.json` 里沉淀了大量经回测验证后的修正，这些不是缺陷而是设计原则：

1. **"顺资金"策略已下线（2026-06）**：24 场回测中该策略 0/3 命中、ROI -100%，且资金流向/让球线移动与赛果统计上不可区分于噪声。资金方向现仅作低置信度解读文字保留，不再据此加注。

2. **正 EV 不再标"推荐"**：74 场回测显示 EV≥5% 的让球盘注单胜率仅 46%、ROI -18.7%。模型≈市场时，大正 EV 多是某家滞后/错盘的烂价而非真机会。错盘护栏阈值从 15% 收紧到 8%，"正 EV"统一降为"信息参考，非买入信号"。

3. **校准切换有统计门槛**：去水方法/锚点权重的切换需样本≥20 场且差异显著（logloss 差≥0.02）。不足门槛的发现只记录在 notes，不影响模型——"单场比赛说明不了任何问题"。

4. **抓取窗口大幅收窄（2026-06）**：预测=开赛前最后一帧收盘价，远端盘口对预测无意义只烧额度。每场约 1+3 帧较旧 13 帧省 ~60% 额度，喂给模型的收盘价一帧不少。

5. **报告生成与抓取解耦**：生成报告不耗额度（仅渲染快照），靠被动存档通常也有快照，故放宽到开赛前 72h，让未来 3 天比赛都能看到报告。

6. **开赛后快照过滤**：`latest_odds` 只保留开赛前快照——本系统做赛前预测，开赛后滚球价不能用作"收盘价"，否则污染校准/回测/定稿展示。

7. **波胆小仓位**：波胆注额 0.1（其他玩法 1），符合高赔率玩法小仓位的现实投注习惯；按模型公平赔率记账（市价不可采集），复盘指标为命中率校准。

### 当前校准状态（`calibration.json`，2026-07-14）
- 样本：98 场
- 去水方法：幂法（维持）
- 亚盘 97 注 ROI +11.4%、大小球 97 注 ROI +1.2%——均视作方差，不当作可盈利策略
- 淘汰赛 28 场：平局 14% / 场均 2.75 球 / 大胜 14%

---

## 报告内容（`match_<ID>_盘口解析.html`）

赛博朋克风横版仪表盘（FWC-18/AQ 暗夜霓虹美学，纯 SVG 图表无 JS 依赖）：

- **模型参数**：市场公平概率 vs 模型拟合概率、λ主/λ客、总进球期望、ρ
- **盘口走势曲线**：Pinnacle/Betfair 主胜赔率、亚盘水位时序
- **基本面对比**（助读，不进模型）：球场/海拔/顶棚、赛日天气、主场优势、近况攻防
- **亚洲让球盘**：各家盘口/赔率/公平赔率/EV 表 + 全场最优推荐
- **大小球盘**：同上
- **波胆**：比分概率排名 top 8 + 公平赔率
- **对冲/保险参考**：让球方平局会输时，给出配平局保本的比例（降波动不增 EV）
- **模拟下注**：落单记录与结算盈亏
- **依据链**（按权重分层）：①市场锚点（主依据）②盘口走势 ③纸面近况 ④资金流向与盘口行为

总览主页 `docs/index.html` 列出全部比赛、API 额度、模拟盈亏、推荐成功率（每 5min 自动刷新）。

---

## 技术栈

- **Python 3.12** / SQLite（标准库，零外部数据库）
- **requests** + **BeautifulSoup/lxml**（网页抓取）/ **Playwright**（OddsPortal 降级）
- **GitHub Actions**（调度）+ **GitHub Pages**（发布）
- 数学：纯标准库 `math`（幂法去水、泊松、Dixon-Coles、二分法）——无 numpy/scipy 依赖
- 报告：纯 HTML/CSS/内嵌 SVG（无前端框架、无 JS）
