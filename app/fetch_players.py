#!/usr/bin/env python3
"""全量抓取球队/球员信息入库（API-Football 主数据源）。

用法:
    python fetch_players.py --test            # 校验 key + 显示账号额度/plan
    python fetch_players.py                   # 遍历 DB 全部球队
    python fetch_players.py --team Argentina  # 单队(按我库英文名)
    python fetch_players.py --team-id 26      # 单队(按 API team_id，跳过解析)
    python fetch_players.py --skip-stats      # 只抓大名单不抓球员统计(省额度)
    python fetch_players.py --season 2025     # 指定赛季(默认 2026)
    python fetch_players.py --max-calls 90    # 额度预算：累计调用到上限就停(免费档)

额度预估(每队)：大名单 1 + 球员统计 ~2(分页) + 伤停 1 + 教练 1 ≈ 5 次。
免费档 100/天约够 18 队；全量 54 队需 Starter 档或分多日运行(--max-calls 分批)。
"""
import argparse
import logging
from logging.handlers import RotatingFileHandler

import db
from config import API_FOOTBALL_SEASON, LOG_DIR
from sources import api_football
from sources.odds_api import to_english

log = logging.getLogger("fetch_players")


def setup_logging():
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(LOG_DIR / "fetch_players.log", maxBytes=5 * 1024 * 1024,
                             backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    root.addHandler(sh)


# ---------------- 解析：API 响应 -> 扁平 dict ----------------

def _flt(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _int(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _get(d, *keys):
    """取嵌套字段，兼容 API 字段拼写差异(如 committed/commited)。"""
    for k in keys:
        v = (d or {}).get(k)
        if v is not None:
            return v
    return None


def flatten_stat(api_player_id, season, st):
    """一个 statistics block -> player_stats 扁平 dict。"""
    g = st.get("games") or {}
    shots = st.get("shots") or {}
    goals = st.get("goals") or {}
    passes = st.get("passes") or {}
    tackles = st.get("tackles") or {}
    duels = st.get("duels") or {}
    dribbles = st.get("dribbles") or {}
    fouls = st.get("fouls") or {}
    cards = st.get("cards") or {}
    penalty = st.get("penalty") or {}
    return {
        "api_player_id": api_player_id, "season": season,
        "team_name": (st.get("team") or {}).get("name"),
        "league_name": (st.get("league") or {}).get("name"),
        "league_country": (st.get("league") or {}).get("country"),
        "position": g.get("position"),
        "appearances": _int(g.get("appearences")),     # API 拼写
        "lineups": _int(g.get("lineups")),
        "minutes": _int(g.get("minutes")),
        "rating": _flt(g.get("rating")),
        "captain": g.get("captain"),
        "shots_total": _int(shots.get("total")),
        "shots_on": _int(shots.get("on")),
        "goals": _int(goals.get("total")),
        "assists": _int(goals.get("assists")),
        "passes_total": _int(passes.get("total")),
        "passes_key": _int(passes.get("key")),
        "passes_accuracy": passes.get("accuracy"),       # 字符串如 "82.3"
        "tackles_total": _int(tackles.get("total")),
        "tackles_blocks": _int(tackles.get("blocks")),
        "tackles_interceptions": _int(tackles.get("interceptions")),
        "duels_total": _int(duels.get("total")),
        "duels_won": _int(duels.get("won")),
        "dribbles_attempts": _int(dribbles.get("attempts")),
        "dribbles_success": _int(dribbles.get("success")),
        "dribbles_past": _int(dribbles.get("past")),
        "fouls_drawn": _int(fouls.get("drawn")),
        "fouls_committed": _int(_get(fouls, "committed", "commited")),
        "cards_yellow": _int(cards.get("yellow")),
        "cards_yellowred": _int(cards.get("yellowred")),
        "cards_red": _int(cards.get("red")),
        "penalty_won": _int(_get(penalty, "won")),
        "penalty_scored": _int(_get(penalty, "scored")),
        "penalty_missed": _int(_get(penalty, "missed")),
        # xg/xag 预留，API-Football 不提供
    }


# ---------------- 单队抓取 ----------------

def fetch_team(conn, team_name, team_id, season, skip_stats, max_calls):
    """抓单队：大名单(/squads) + 球员统计(/players) + 伤停 + 教练，入库。"""
    label = f"{team_name}(#{team_id})"

    # 1) 大名单（权威注册名单，含未上场球员）
    squad = []
    try:
        squad = api_football.get_squad(team_id)
    except api_football.ApiFootballError as e:
        log.warning("%s 大名单抓取失败: %s（继续用 /players 补）", label, e)

    # 2) 球员统计（含每人多段 statistics；分页）
    players_resp = []
    if not skip_stats:
        try:
            players_resp = api_football.get_team_players(team_id, season)
        except api_football.ApiFootballError as e:
            log.error("%s 球员统计抓取失败: %s（可能当赛季需付费档，用 --season 选历史年）",
                      label, e)

    # 3) 合并：squad 提供名单/号码/位置，/players 覆盖完整 bio + 标记有统计
    merged = {}   # api_player_id -> dict
    for sp in squad:
        pid = sp.get("id")
        if pid is None:
            continue
        merged[pid] = {
            "api_player_id": pid, "name": sp.get("name"),
            "age": sp.get("age"), "squad_number": sp.get("number"),
            "position": sp.get("position"), "photo": sp.get("photo"),
            "team_name": team_name, "season": season,
        }
    for item in players_resp:
        p = item.get("player") or {}
        pid = p.get("id")
        if pid is None:
            continue
        if pid not in merged:
            merged[pid] = {"api_player_id": pid, "name": p.get("name"),
                           "team_name": team_name, "season": season}
        m = merged[pid]
        m["firstname"] = p.get("firstname")
        m["lastname"] = p.get("lastname")
        m["age"] = p.get("age") or m.get("age")
        m["nationality"] = p.get("nationality")
        m["birth_date"] = (p.get("birth") or {}).get("date")
        m["height"] = p.get("height")
        m["weight"] = p.get("weight")
        m["injured"] = p.get("injured")
        if p.get("photo"):
            m["photo"] = p["photo"]
        # /players 的 games.position 补齐 squad 没给的位置
        if not m.get("position"):
            for st in item.get("statistics") or []:
                pos = (st.get("games") or {}).get("position")
                if pos:
                    m["position"] = pos
                    break

    # 入库球员
    for m in merged.values():
        db.upsert_player(conn, m)
    log.info("%s 入库球员 %d 名（大名单 %d + 有统计 %d）",
             label, len(merged), len(squad), len(players_resp))

    # 入库球员统计（每人每段 statistics 一行）
    n_stats = 0
    for item in players_resp:
        p = item.get("player") or {}
        pid = p.get("id")
        for st in item.get("statistics") or []:
            try:
                db.upsert_player_stats(conn, flatten_stat(pid, season, st))
                n_stats += 1
            except Exception as e:
                log.warning("%s 球员#%s 一段统计入库失败: %s", label, pid, e)

    # 4) 伤停
    try:
        inj = api_football.get_team_injuries(team_id)
        for r in inj:
            pl = r.get("player") or {}
            db.upsert_injury(conn, {
                "api_player_id": pl.get("id"),
                "player_name": pl.get("name"),
                "team_name": team_name,
                "reason": r.get("reason"),
                "type": r.get("type"),
                "status": r.get("status"),
                "injury_date": r.get("date"),
            })
        log.info("%s 伤停 %d 条", label, len(inj))
    except api_football.ApiFootballError as e:
        log.warning("%s 伤停抓取失败: %s", label, e)

    # 5) 教练
    try:
        c = api_football.get_team_coach(team_id)
        if c:
            db.upsert_coach(conn, team_name, {
                "api_coach_id": c.get("id"), "name": c.get("name"),
                "age": c.get("age"), "nationality": c.get("nationality"),
                "photo": c.get("photo"),
            })
            log.info("%s 教练: %s", label, c.get("name"))
    except api_football.ApiFootballError as e:
        log.warning("%s 教练抓取失败: %s", label, e)

    return len(merged), n_stats


# ---------------- 队名归一化 ----------------

def normalize_team_names(conn):
    """matches 表的队名(英中混合) -> 去重英文列表，过滤待定。"""
    seen, out = set(), []
    for raw in db.list_team_names(conn):
        if not raw or raw == "待定":
            continue
        en = to_english(raw).strip()
        if not en or en == "待定" or en in seen:
            continue
        seen.add(en)
        out.append(en)
    return sorted(out)


def resolve_team_id(conn, team_name):
    """DB 缓存优先，否则查 API 并缓存。返回 api_team_id 或 None。"""
    cached = db.get_team_id(conn, team_name)
    if cached:
        return cached
    found = api_football.find_team_id(team_name)
    if not found:
        return None
    tid, cname = found
    db.upsert_team_id(conn, team_name, tid, cname)
    return tid


# ---------------- 主流程 ----------------

def main():
    parser = argparse.ArgumentParser(description="抓取球队/球员信息入库")
    parser.add_argument("--test", action="store_true", help="只校验 key 与额度")
    parser.add_argument("--team", help="只抓单队(我库英文名)")
    parser.add_argument("--team-id", type=int, help="只抓单队(按 API team_id，跳过解析)")
    parser.add_argument("--skip-stats", action="store_true", help="只抓大名单不抓球员统计")
    parser.add_argument("--season", type=int, default=API_FOOTBALL_SEASON)
    parser.add_argument("--max-calls", type=int, default=0,
                        help="额度预算：累计 API 调用到此值就停(0=不限)")
    args = parser.parse_args()

    setup_logging()
    conn = db.connect()

    if args.test:
        ok, info, msg = api_football.test_key()
        if ok:
            log.info("✓ %s", msg)
            log.info("  账号: %s | plan: %s | 到期: %s | 今日剩余: %s/%s",
                     info.get("account"), info.get("plan"), info.get("end"),
                     info.get("remaining"), info.get("limit_day"))
        else:
            log.error("✗ %s", msg)
        return

    if not api_football.API_FOOTBALL_KEY:
        log.error("未配置 API_FOOTBALL_KEY：请在 app/.env 写入 API_FOOTBALL_KEY=xxx "
                  "（注册 api-football.com 免费档即可），再用 --test 校验。")
        return

    # 确定要处理的球队
    if args.team_id:
        targets = [(f"team#{args.team_id}", args.team_id)]
    elif args.team:
        targets = [(args.team, None)]
    else:
        names = normalize_team_names(conn)
        log.info("待处理球队 %d 支（已归一化为英文）", len(names))
        targets = [(n, None) for n in names]

    ok, fail, total_players, total_stats = 0, 0, 0, 0
    for team_name, tid_hint in targets:
        if args.max_calls and api_football.call_count() >= args.max_calls:
            log.warning("已达额度预算 %d 次，剩余球队改日再跑。已完成 %d 队。",
                        args.max_calls, ok)
            break
        tid = tid_hint or resolve_team_id(conn, team_name)
        if not tid:
            log.error("%s: 无法解析 team_id，跳过", team_name)
            fail += 1
            continue
        try:
            np, ns = fetch_team(conn, team_name, tid, args.season,
                                args.skip_stats, args.max_calls)
            ok += 1
            total_players += np
            total_stats += ns
        except Exception as e:
            log.error("%s 抓取异常: %s", team_name, e)
            fail += 1

    log.info("完成：成功 %d 队 / 失败 %d 队 | 球员 %d 名 | 统计 %d 段 | API 调用 %d 次",
             ok, fail, total_players, total_stats, api_football.call_count())


if __name__ == "__main__":
    main()
