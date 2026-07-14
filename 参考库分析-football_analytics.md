# 参考库分析：eddwebster/football_analytics

> 仓库地址：<https://github.com/eddwebster/football_analytics>
> License：MIT ｜ 语言：Python + R ｜ 性质：个人作品集 / 学习型仓库（非生产系统）
> 调研日期：2026-07-14

## 一、仓库定位

`football_analytics` 是足球分析师 Edd Webster 维护的一个 **"二合一" 仓库**：

1. **一份极其庞大的足球分析资源索引**（README 的主体）——收录数据源、库、论文、博客、教程、课程、会议、工作等，按主题分类，相当于足球分析领域的 "awesome list"。
2. **作者本人的一套分析项目代码**（`notebooks/` 下）——按"抓取 → 解析 → 工程化 → 统一 → 分析"五阶段工作流组织，用 Jupyter notebook 为主。

对本项目（football-odds-reports）而言，它的价值不在于架构（它没有调度、没有落库 pipeline，工程化程度低于本项目），而在于 **分析方法论与可复用的代码片段 / 库指引**——尤其是本项目当前缺失的 **xG 建模** 和 **FBref 抓取** 两块。

---

## 二、仓库结构

```
football_analytics/
├── README.md          # 资源索引主体（极长）
├── notebooks/         # 实际分析代码（核心）
│   ├── 1_data_scraping/        # 抓取
│   ├── 2_data_parsing/         # 解析
│   ├── 3_data_engineering/     # 工程化
│   ├── 4_data_unification/     # 数据统一
│   └── 5_data_analysis_and_projects/  # 分析项目
├── data/              # 各厂商原始 / 处理后数据样本
├── docs/              # 各厂商数据文档
├── research/          # 论文 / 文档 / 幻灯片
├── scripts/           # Python 脚本
├── dashboards/        # Tableau 仪表盘
├── img/               # 徽标 / 球员图 / 球场图等
├── fonts/             # 可视化字体
└── video/             # 分析用视频
```

`data/` 下覆盖的厂商：capology、fbref、fifa、elo、opta、sb(StatsBomb)、wyscout、understat、stratabet、metrica-sports、stats-perform、tm(TransferMarkt)、twenty-first-group 等——基本是公开足球数据的全谱系。

---

## 三、五阶段工作流详解

### ① 抓取 `1_data_scraping`

| Notebook | 数据源 | 内容 |
|---|---|---|
| FBref Player Stats Web Scraping | FBref | 球员赛季统计 |
| Capology Player Salary Web Scraping | Capology | 球员薪资 |
| TransferMarkt Player Bio and Status | TransferMarkt | 球员资料 / 状态 |
| Opta Event Data Scraping from WhoScored | WhoScored/Opta | 事件数据 |
| understat/ | Understat | 射手 / 射门数据 |

### ② 解析 `2_data_parsing`

- **ELO Team Ratings Data Parsing** — Club Elo 球队评级
- **StatsBomb Data Parsing** / **StatsBomb 360 Data Parsing** — StatsBomb 事件 + 360 帧
- **Wyscout Data Parsing** — Wyscout 事件数据

### ③ 工程化 `3_data_engineering`

17 个 notebook，把上述各源清洗、结构化。包括 FBref、Opta、StatsBomb、StatsBomb 360、Wyscout、StrataBet、Second Spectrum、Capology、TransferMarkt（身价/转会）、The Guardian（转会费）、体能数据 Part 1/2、Centre Circle CPL 等。

### ④ 统一 `4_data_unification`

- **Unification of Aggregated Seasonal Football Datasets** — 把多个聚合赛季数据集合并成一张统一表。

### ⑤ 分析项目 `5_data_analysis_and_projects`（核心）

| 子目录 | 分析主题 | 关键技术 |
|---|---|---|
| `xg_modeling/` | **预期进球 (xG) 建模** | Logistic Regression、Random Forest、**XGBoost**；分 `shots_dataset` 和 `opta_dataset` 两套 |
| `action_value_frameworks/vaep/` | **VAEP 动作价值框架** | SciSports 风格，给球员每个动作估值 |
| `player_similarity_and_clustering/` | **球员相似度 + 聚类** | PCA + K-Means，案例"找皮克式后卫" |
| `tracking_data/` | **Tracking 数据分析** | Metrica Sports / Second Spectrum / Signality 三套跟踪数据 |
| `england_euro_2020/` | **英格兰 Euro 2020 复盘** | StatsBomb 事件数据：工程化 + 分析 + 可视化 |

---

## 四、README 资源索引的关键专题

README 的 "Key Concepts" 一节对本项目有直接参考价值，重点专题：

- **Expected Goals (xG) Modeling** — xG 建模资源汇总
- **Dixon Coles Modeling** — 本项目泊松模型的核心，这里有扩展阅读
- **Possession Value (PV) Frameworks** — 控球价值框架：
  - xT（Expected Threat）
  - VAEP（Valuing Actions by Estimating Probabilities）
  - g+（Goals Added）
  - OBV（On-Ball Value）
- **Pitch Control Modeling** — 球场控制模型（Will Spearman 等）
- **Passing Networks** — 传球网络
- **Player Rating** — 球员评级
- **Game Win Probability Modelling** — 比赛胜率建模
- **Player Similarity and Style Analysis** — 球员相似度与风格
- **Quantifying Relative Club and League Strength** — 联赛 / 球队相对强度量化（跨联赛校准，对世界杯这种跨洲赛事尤其相关）
- **Reinforcement Learning for Football Simulation** — 强化学习足球仿真

数据源专题里还专门列了 **Odds, Betting, and Predictions data** 一节——直接对标本项目的赔率方向。

---

## 五、推荐的现成 Python 库（README 点名，比手写抓取强）

README 在依赖说明里点名了几个关键库，对本项目**直接可用**：

| 库 | 作者 | 能抓什么 | 对本项目的意义 |
|---|---|---|---|
| **`soccerdata`** | Pieter Robberechts | Club Elo、ESPN、**FBref**、FiveThirtyEight、Football-Data.co.uk、SoFIFA、WhoScored | **解决 FBref Cloudflare 封锁的最优解**——封装好的抓取层，比自己硬刚 CF 强 |
| **`ScraperFC`** | Owen Seymour | FiveThirtyEight、**FBref**、Understat、Club Elo、Capology、TransferMarkt | 同上，FBref 的另一条现成路径 |
| `soccer_xg` | ML KU Leuven | xG 模型训练与分析 | **直接填补本项目 xG 缺口** |
| `socceraction` | ML KULeuven | VAEP 动作价值、xT 实现 | 球员动作级评级 |
| `mplsoccer` | Andrew Rowlinson | matplotlib 球场绘制 | 可视化 |
| `statsbombpy` / `statsbombapi` | StatsBomb / Francisco Goitia | StatsBomb 开放数据 | 事件数据 |
| `worldfootballR` (R) | Jason Zivkovic | FBref / TransferMarkt / Understat / fotmob | R 生态的 FBref 抓取 |

> ⚠️ 本项目此前用 requests / cloudscraper / curl_cffi / headless Playwright+stealth 硬刚 FBref 的 Cloudflare 全部失败（403，卡在 "Just a moment"）。`soccerdata` 和 `ScraperFC` 是**优先于自研抓取**的尝试方向——它们内部已处理 CF / 反爬，值得在补 xG 前先试。

---

## 六、对本项目（football-odds-reports）的参考价值

| 本项目现状 / 缺口 | football_analytics 提供的参考 |
|---|---|
| **xG/xA 缺失**（FBref CF 封锁，`player_stats` 的 xg/xag 为空列） | `xg_modeling/` 有 Logistic / XGBoost 完整 notebook；`soccer_xg` 库可直接用；或先用 Understat（射门级 xG，`1_data_scraping/understat`）作代理 |
| **FBref 抓取被 CF 卡死** | `1_data_scraping/FBref Player Stats Web Scraping.ipynb` 看作者绕法；优先试 `soccerdata` / `ScraperFC` 两个封装库 |
| **Dixon-Coles 模型**（本项目核心） | README "Dixon Coles Modeling" 专题有扩展资源；可对照验证本项目实现 |
| **跨联赛 / 跨洲强度校准**（世界杯 48 队来自不同大洲） | README "Quantifying Relative Club and League Strength" 专题；ELO 评级（`2_data_parsing/ELO`）是现成的跨赛事强度锚点 |
| **赔率 / 预测** | README "Odds, Betting, and Predictions data" 数据源专题 |
| **球员相似度 / 风格**（对标"球小策"球员画像层） | `player_similarity_and_clustering/` PCA + K-Means 完整案例 |

### 建议的复用优先级

1. **先试 `soccerdata` / `ScraperFC`** 补 FBref → 若通，xG/xA 直接落库，填上 `player_stats` 空列。这是当前最高 ROI 的一步。
2. **`soccer_xg` 或 `xg_modeling/` notebook** → 若 FBref 仍不通，用 Understat 射门数据 + 自己训 xG 模型作替代。
3. **ELO 跨联赛强度** → 世界杯跨洲校准的免费锚点，可与现有 Pinnacle/Betfair 双锚点互补。
4. **球员相似度** → 后续做"球小策"对标球员画像层时复用 PCA + K-Means 思路。

---

## 七、局限性

- **非生产系统**：Jupyter notebook 为主，无调度、无落库 pipeline、无自动化。工程化程度低于本项目（本项目有 GitHub Actions 三工作流 + SQLite + GitHub Pages）。
- **Python + R 混用**：部分分析是 R（`worldfootballR`、`StatsBombR`、`ggsoccer`），本项目纯 Python，复用需挑 Python 部分。
- **数据偏俱乐部赛事**：分析项目多围绕英超 / 欧洲联赛 / Euro，国家队 / 世界杯场景需自行迁移。
- **维护频率**：README 称 "semi-regularly" 更新，部分链接可能失效，需以实际访问为准。
- **版本较旧**：依赖写 Python 3.6.1+ / R 4.0.4+，部分库 API 可能已变。

---

## 八、一句话总结

`football_analytics` 是一座 **足球分析方法论的参考资料库**：README 当工具书查（xG / Dixon-Coles / PV 框架 / 联赛强度校准等专题），`notebooks/` 当代码片段抄（尤其 `xg_modeling/` 和 FBref 抓取）。它不能直接并入本项目，但能为本项目当前两大缺口（xG、FBref 抓取）提供现成的库（`soccerdata` / `ScraperFC` / `soccer_xg`）和实现范例，是补全球员数据后值得优先尝试的方向。
