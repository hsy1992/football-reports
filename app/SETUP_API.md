# 球员/球队数据接入指南（API-Football）

本项目用 [API-Football](https://www.api-football.com/)（api-sports.io v3）作为球员/大名单/伤停/裁判/教练/首发的**主数据源**，补齐赔率模型之外的信息层（见 `可行性技术方案-球小策对标.md` Phase 1）。

## 1. 注册拿 key

1. 到 https://www.api-football.com/ 注册账号（免费档即可，100 次/天）。
2. Dashboard 里复制你的 API key。
3. 在 `app/.env` 写入一行（该文件已在 `.gitignore`，不会提交）：

```
API_FOOTBALL_KEY=你的key
```

如需指定赛季（默认 2026），可再加：
```
API_FOOTBALL_SEASON=2026
```

## 2. 校验 key

```bash
cd app
python fetch_players.py --test
```

成功会显示：账号、plan、订阅到期、今日剩余额度。

## 3. 抓取入库

```bash
# 单队测试（推荐先跑一队确认数据形状）
python fetch_players.py --team Argentina

# 按 API team_id 直抓（跳过队名解析）
python fetch_players.py --team-id 26

# 全量（遍历 DB 全部 48 支国家队）
python fetch_players.py

# 只抓大名单、不抓球员统计（省额度，每队仅 ~3 次调用）
python fetch_players.py --skip-stats

# 指定历史赛季（若当年赛季需付费档，用历史年绕过）
python fetch_players.py --season 2024
```

## 4. 额度预算（重要）

| 模式 | 每队调用数 | 免费档 100/天可跑 |
|------|-----------|-------------------|
| 全量（名单+统计+伤停+教练） | ~5 | ~18 队 |
| `--skip-stats`（仅名单+伤停+教练） | ~3 | ~30 队 |

**全量 48 队在免费档需分 3 天**，用 `--max-calls` 分批：

```bash
python fetch_players.py --max-calls 90    # 跑到 90 次就停，明日再跑
```

Starter 档（3000/天）一次跑完全量无压力。队名->team_id 解析结果缓存在 `api_team_ids` 表，重跑不重复消耗。

## 5. 已知限制

- **xG/xA 不提供**：API-Football 的 `/players` 没有 expected goals。`player_stats` 表预留了 `xg`/`xag` 空列，待日后接 SportMonks 或 FBref 补。MVP 阶段用 goals/shots/shots_on 作进攻代理（可行性方案已论证可行）。
- **当前赛季 `/players` 可能需付费档**：免费档对当年赛季的球员统计接口可能受限（返回 errors 里会说明）。若 2026 赛季报权限错，用 `--season 2024` 抓历史赛季数据先跑通，或升级档位。
- **未上场球员**：`/players` 只返回有出场记录的球员；`/squads` 返回完整注册大名单（含未出场新人）。脚本两者都抓并合并，未上场球员的统计列为 NULL。

## 6. 数据落库位置

| 表 | 内容 |
|----|------|
| `api_team_ids` | 队名 -> API team_id 缓存 |
| `players` | 球员档案（姓名/位置/年龄/国籍/身高体重/号码/是否伤） |
| `player_stats` | 赛季统计（射门/射正/进球/助攻/传球/关键传球/抢断/拦截/封堵/过人/对抗/犯规/牌/点球/分钟/评分，每球员每联赛每队一行） |
| `injuries` | 伤停清单（替换一直返回空的懂球帝） |
| `coaches` | 主教练信息 |

所有时间存 UTC ISO，队名用我库英文口径（The Odds API 口径，与 `matches.home_team_en` 一致）。

## 7. 文件清单

- `sources/api_football.py` — API 客户端（test/find_team_id/get_squad/get_team_players/get_team_injuries/get_team_coach/get_referees/get_fixture_lineups）
- `db.py` — 新增 5 张表 + 存取函数（`upsert_player` 等）
- `fetch_players.py` — 全量抓取编排入口
- `config.py` — `API_FOOTBALL_KEY` / `API_FOOTBALL_BASE` / `API_FOOTBALL_SEASON`
