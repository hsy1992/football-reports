"""SQLite 存取层。所有时间字段存 UTC ISO 字符串。"""
import sqlite3
from datetime import datetime, timezone

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    competition TEXT,
    kickoff_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'tracking',   -- tracking | finished
    sport_key TEXT,
    odds_api_event_id TEXT,
    home_team_en TEXT,
    away_team_en TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS odds_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    fetched_at TEXT NOT NULL,
    source TEXT NOT NULL,            -- odds_api | oddsportal
    bookmaker TEXT NOT NULL,
    market TEXT NOT NULL,            -- 1x2 | ah | ou
    line REAL,                       -- 让球线 / 大小球线；1x2 为 NULL
    home_odds REAL,
    draw_odds REAL,                  -- 仅 1x2 有；ou 时 home=大 away=小
    away_odds REAL
);
CREATE INDEX IF NOT EXISTS idx_snap_match ON odds_snapshots(match_id, fetched_at);
CREATE TABLE IF NOT EXISTS team_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source TEXT NOT NULL,
    recent_matches_json TEXT,
    injuries_json TEXT
);
CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT,                     -- ok | partial | error
    detail TEXT
);
CREATE TABLE IF NOT EXISTS paper_bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    placed_at TEXT NOT NULL,
    market TEXT NOT NULL,            -- ah | ou | cs
    pick TEXT NOT NULL,              -- 如 主让 -1.25 / 大 2.25 / 1-0
    bookmaker TEXT,
    line REAL,
    side TEXT,                       -- home/away/over/under；cs 为空
    odds REAL NOT NULL,              -- cs 记模型公平赔率（市价不可得）
    ev REAL,
    result TEXT,                     -- 赢/赢半/走/输半/输（未结算为 NULL）
    pnl REAL,                        -- 每注本金 1
    settled_at TEXT
);
-- ========== 球员/球队信息（API-Football 主数据源）==========
CREATE TABLE IF NOT EXISTS api_team_ids (
    team_name TEXT PRIMARY KEY,      -- 我库英文队名(The Odds API 口径)
    api_team_id INTEGER NOT NULL,
    canonical_name TEXT,             -- API-Football 返回的官方名
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS players (
    api_player_id INTEGER PRIMARY KEY,   -- 同球员全局唯一，INSERT OR REPLACE 覆盖更新
    name TEXT NOT NULL,
    firstname TEXT,
    lastname TEXT,
    age INTEGER,
    nationality TEXT,
    birth_date TEXT,
    height TEXT,
    weight TEXT,
    photo TEXT,
    injured INTEGER DEFAULT 0,           -- 0/1
    -- 最近一次抓取所在的国家队大名单上下文
    team_name TEXT,
    position TEXT,
    squad_number INTEGER,
    season INTEGER,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS player_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_player_id INTEGER NOT NULL REFERENCES players(api_player_id),
    season INTEGER NOT NULL,
    team_name TEXT,                      -- 该 stat block 所属队(国家队或俱乐部)
    league_name TEXT,
    league_country TEXT,
    position TEXT,
    appearances INTEGER,
    lineups INTEGER,
    minutes INTEGER,
    rating REAL,
    captain INTEGER DEFAULT 0,
    shots_total INTEGER,
    shots_on INTEGER,
    goals INTEGER,
    assists INTEGER,
    passes_total INTEGER,
    passes_key INTEGER,
    passes_accuracy TEXT,                -- API 返回字符串如 "82.3"
    tackles_total INTEGER,
    tackles_blocks INTEGER,
    tackles_interceptions INTEGER,
    duels_total INTEGER,
    duels_won INTEGER,
    dribbles_attempts INTEGER,
    dribbles_success INTEGER,
    dribbles_past INTEGER,
    fouls_drawn INTEGER,
    fouls_committed INTEGER,
    cards_yellow INTEGER,
    cards_yellowred INTEGER,
    cards_red INTEGER,
    penalty_won INTEGER,
    penalty_scored INTEGER,
    penalty_missed INTEGER,
    xg REAL,                             -- 预留：API-Football 不提供，待 FBref/SportMonks 补
    xag REAL,
    fetched_at TEXT NOT NULL,
    UNIQUE(api_player_id, season, league_name, team_name)
);
CREATE TABLE IF NOT EXISTS injuries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_player_id INTEGER,
    player_name TEXT,
    team_name TEXT,
    reason TEXT,
    type TEXT,
    status TEXT,
    injury_date TEXT,
    fetched_at TEXT NOT NULL,
    UNIQUE(api_player_id, injury_date, reason)
);
CREATE TABLE IF NOT EXISTS coaches (
    team_name TEXT PRIMARY KEY,
    api_coach_id INTEGER,
    name TEXT,
    age INTEGER,
    nationality TEXT,
    photo TEXT,
    fetched_at TEXT NOT NULL
);
"""


def utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    """老库平滑加列（赛果回填功能引入）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(matches)")}
    for col, ddl in [
        ("home_score", "ALTER TABLE matches ADD COLUMN home_score INTEGER"),
        ("away_score", "ALTER TABLE matches ADD COLUMN away_score INTEGER"),
        ("result_source", "ALTER TABLE matches ADD COLUMN result_source TEXT"),
        ("result_attempts",
         "ALTER TABLE matches ADD COLUMN result_attempts INTEGER NOT NULL DEFAULT 0"),
    ]:
        if col not in cols:
            conn.execute(ddl)
    pb_cols = {r["name"] for r in conn.execute("PRAGMA table_info(paper_bets)")}
    if pb_cols and "stake" not in pb_cols:
        # 注额列：波胆 0.1，其余 1（高赔率玩法小仓位，符合实际投注习惯）
        conn.execute("ALTER TABLE paper_bets ADD COLUMN stake REAL NOT NULL DEFAULT 1")
    if pb_cols and "strategy" not in pb_cols:
        # 策略列：ev=EV最优入口；flow=顺职业资金方向（平行实验组）
        conn.execute("ALTER TABLE paper_bets ADD COLUMN strategy TEXT NOT NULL"
                     " DEFAULT 'ev'")
    for col in ("venue_name", "venue_city"):  # 球场缓存（静态，抓一次即可）
        if col not in cols:
            conn.execute(f"ALTER TABLE matches ADD COLUMN {col} TEXT")
    conn.commit()

    # 一次性修正历史让球注单的术语 bug（旧标签如"客受让 -1.00"自相矛盾）
    bad = conn.execute(
        "SELECT COUNT(*) c FROM paper_bets WHERE market='ah'"
        " AND (pick LIKE '%受让 -%' OR pick LIKE '%让 +%' OR pick LIKE '%-0.00')"
    ).fetchone()
    if bad and bad["c"]:
        for b in conn.execute(
            "SELECT id, side, line FROM paper_bets WHERE market='ah'").fetchall():
            if b["line"] is None or b["side"] is None:
                continue
            team = "主" if b["side"] == "home" else "客"
            h = b["line"] if b["side"] == "home" else -b["line"]
            if abs(h) < 1e-9:
                pick = f"{team}平手"
            else:
                pick = f"{team}{'让' if h < 0 else '受让'} {abs(h):.2f}"
            conn.execute("UPDATE paper_bets SET pick=? WHERE id=?", (pick, b["id"]))
        conn.commit()


# ---------- matches ----------

def add_match(conn, home, away, kickoff_utc, competition=None, sport_key=None):
    cur = conn.execute(
        "INSERT INTO matches (home_team, away_team, competition, kickoff_utc,"
        " sport_key, created_at) VALUES (?,?,?,?,?,?)",
        (home, away, competition, kickoff_utc, sport_key, utcnow_iso()),
    )
    conn.commit()
    return cur.lastrowid


def get_match(conn, match_id):
    return conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()


def get_match_by_event(conn, event_id):
    return conn.execute(
        "SELECT * FROM matches WHERE odds_api_event_id=?", (event_id,)
    ).fetchone()


def add_passive_match(conn, home_en, away_en, kickoff_utc, sport_key, event_id):
    """批量响应里顺带存档的比赛：不调度、不显示，只攒数据。"""
    cur = conn.execute(
        "INSERT INTO matches (home_team, away_team, kickoff_utc, status,"
        " sport_key, odds_api_event_id, home_team_en, away_team_en, created_at)"
        " VALUES (?,?,?,'passive',?,?,?,?,?)",
        (home_en, away_en, kickoff_utc, sport_key, event_id,
         home_en, away_en, utcnow_iso()),
    )
    conn.commit()
    return cur.lastrowid


def promote_match(conn, match_id, home, away, competition, kickoff_utc):
    """把被动存档的比赛升级为正式跟踪（历史快照自动保留）。"""
    conn.execute(
        "UPDATE matches SET home_team=?, away_team=?, competition=?,"
        " kickoff_utc=?, status='tracking' WHERE id=?",
        (home, away, competition, kickoff_utc, match_id),
    )
    conn.commit()


def list_matches(conn, status=None):
    if status:
        return conn.execute(
            "SELECT * FROM matches WHERE status=? ORDER BY kickoff_utc", (status,)
        ).fetchall()
    return conn.execute("SELECT * FROM matches ORDER BY kickoff_utc").fetchall()


def remove_match(conn, match_id):
    conn.execute("DELETE FROM odds_snapshots WHERE match_id=?", (match_id,))
    conn.execute("DELETE FROM matches WHERE id=?", (match_id,))
    conn.commit()


def set_event(conn, match_id, sport_key, event_id, home_en=None, away_en=None):
    conn.execute(
        "UPDATE matches SET sport_key=?, odds_api_event_id=?,"
        " home_team_en=COALESCE(?, home_team_en),"
        " away_team_en=COALESCE(?, away_team_en) WHERE id=?",
        (sport_key, event_id, home_en, away_en, match_id),
    )
    conn.commit()


def update_kickoff(conn, match_id, kickoff_utc):
    conn.execute("UPDATE matches SET kickoff_utc=? WHERE id=?",
                 (kickoff_utc, match_id))
    conn.commit()


def set_venue(conn, match_id, venue_name, venue_city):
    conn.execute("UPDATE matches SET venue_name=?, venue_city=? WHERE id=?",
                 (venue_name, venue_city, match_id))
    conn.commit()


def set_status(conn, match_id, status):
    conn.execute("UPDATE matches SET status=? WHERE id=?", (status, match_id))
    conn.commit()


# ---------- 赛果回填 ----------

def matches_needing_result(conn, kickoff_before_iso, limit=10):
    """已开赛但还没有比分的比赛（含被动存档），跟踪中的优先。"""
    return conn.execute(
        "SELECT * FROM matches WHERE home_score IS NULL AND kickoff_utc < ?"
        " AND result_attempts < 20"   # 提前到110min起每15min一问，点球赛需更多次
        " ORDER BY (status != 'passive') DESC, kickoff_utc DESC LIMIT ?",
        (kickoff_before_iso, limit),
    ).fetchall()


def set_result(conn, match_id, home_score, away_score, source):
    conn.execute(
        "UPDATE matches SET home_score=?, away_score=?, result_source=? WHERE id=?",
        (home_score, away_score, source, match_id),
    )
    conn.commit()


def bump_result_attempts(conn, match_id):
    conn.execute(
        "UPDATE matches SET result_attempts = result_attempts + 1 WHERE id=?",
        (match_id,),
    )
    conn.commit()


# ---------- 模拟下注 ----------

def get_paper_bets(conn, match_id):
    return conn.execute(
        "SELECT * FROM paper_bets WHERE match_id=? ORDER BY market", (match_id,)
    ).fetchall()


def insert_paper_bet(conn, match_id, market, pick, bookmaker, line, side,
                     odds, ev, stake=1.0, strategy="ev"):
    conn.execute(
        "INSERT INTO paper_bets (match_id, placed_at, market, pick, bookmaker,"
        " line, side, odds, ev, stake, strategy) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (match_id, utcnow_iso(), market, pick, bookmaker, line, side, odds, ev,
         stake, strategy),
    )
    conn.commit()


def unsettled_paper_bets(conn):
    """有赛果但未结算的注单。"""
    return conn.execute(
        "SELECT b.*, m.home_score AS hs, m.away_score AS aws FROM paper_bets b"
        " JOIN matches m ON m.id = b.match_id"
        " WHERE b.result IS NULL AND m.home_score IS NOT NULL",
    ).fetchall()


def settle_paper_bet(conn, bet_id, result, pnl):
    conn.execute(
        "UPDATE paper_bets SET result=?, pnl=?, settled_at=? WHERE id=?",
        (result, pnl, utcnow_iso(), bet_id),
    )
    conn.commit()


def finished_with_results(conn):
    """有比分且有赔率快照的比赛，校准验证用。"""
    return conn.execute(
        "SELECT m.* FROM matches m WHERE m.home_score IS NOT NULL"
        " AND EXISTS (SELECT 1 FROM odds_snapshots s WHERE s.match_id = m.id"
        "             AND s.market = '1x2')"
        " ORDER BY m.kickoff_utc",
    ).fetchall()


# ---------- odds_snapshots ----------

def insert_snapshots(conn, match_id, source, rows, fetched_at=None):
    """rows: [{bookmaker, market, line, home, draw, away}]，只追加不覆盖。"""
    ts = fetched_at or utcnow_iso()
    conn.executemany(
        "INSERT INTO odds_snapshots (match_id, fetched_at, source, bookmaker,"
        " market, line, home_odds, draw_odds, away_odds) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (match_id, ts, source, r["bookmaker"], r["market"], r.get("line"),
             r.get("home"), r.get("draw"), r.get("away"))
            for r in rows
        ],
    )
    conn.commit()
    return ts


def last_snapshot_time(conn, match_id):
    row = conn.execute(
        "SELECT MAX(fetched_at) AS t FROM odds_snapshots WHERE match_id=?",
        (match_id,),
    ).fetchone()
    return row["t"]


def get_snapshots(conn, match_id):
    return conn.execute(
        "SELECT * FROM odds_snapshots WHERE match_id=?"
        " ORDER BY market, bookmaker, fetched_at",
        (match_id,),
    ).fetchall()


# ---------- team_stats ----------

def insert_team_stats(conn, team, source, recent_json, injuries_json):
    conn.execute(
        "INSERT INTO team_stats (team, fetched_at, source, recent_matches_json,"
        " injuries_json) VALUES (?,?,?,?,?)",
        (team, utcnow_iso(), source, recent_json, injuries_json),
    )
    conn.commit()


def last_team_stats_time(conn, team):
    row = conn.execute(
        "SELECT MAX(fetched_at) AS t FROM team_stats WHERE team=?", (team,)
    ).fetchone()
    return row["t"]


# ---------- scrape_runs ----------

def start_run(conn):
    cur = conn.execute(
        "INSERT INTO scrape_runs (started_at) VALUES (?)", (utcnow_iso(),)
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id, status, detail=""):
    conn.execute(
        "UPDATE scrape_runs SET finished_at=?, status=?, detail=? WHERE id=?",
        (utcnow_iso(), status, detail, run_id),
    )
    conn.commit()


# ---------- 球员/球队信息（API-Football）----------

def list_team_names(conn):
    """matches 表里出现的所有队名(英中混合)，由调用方归一化为英文后去重。"""
    rows = conn.execute(
        "SELECT DISTINCT home_team AS t FROM matches"
        " UNION SELECT DISTINCT away_team AS t FROM matches"
    ).fetchall()
    return [r["t"] for r in rows if r["t"]]


def upsert_team_id(conn, team_name, api_team_id, canonical_name=None):
    conn.execute(
        "INSERT OR REPLACE INTO api_team_ids (team_name, api_team_id,"
        " canonical_name, fetched_at) VALUES (?,?,?,?)",
        (team_name, api_team_id, canonical_name, utcnow_iso()),
    )
    conn.commit()


def get_team_id(conn, team_name):
    row = conn.execute(
        "SELECT api_team_id FROM api_team_ids WHERE team_name=?", (team_name,)
    ).fetchone()
    return row["api_team_id"] if row else None


def upsert_player(conn, p):
    """p: dict(api_player_id, name, firstname, lastname, age, nationality,
    birth_date, height, weight, photo, injured, team_name, position,
    squad_number, season)。INSERT OR REPLACE 覆盖同球员旧记录。"""
    conn.execute(
        "INSERT OR REPLACE INTO players (api_player_id, name, firstname,"
        " lastname, age, nationality, birth_date, height, weight, photo,"
        " injured, team_name, position, squad_number, season, fetched_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (p["api_player_id"], p["name"], p.get("firstname"), p.get("lastname"),
         p.get("age"), p.get("nationality"), p.get("birth_date"),
         p.get("height"), p.get("weight"), p.get("photo"),
         int(bool(p.get("injured"))), p.get("team_name"), p.get("position"),
         p.get("squad_number"), p.get("season"), utcnow_iso()),
    )
    conn.commit()


def upsert_player_stats(conn, s):
    """s: dict，stat block 各字段。同一(球员,赛季,联赛,队)覆盖更新。"""
    conn.execute(
        "INSERT OR REPLACE INTO player_stats (api_player_id, season, team_name,"
        " league_name, league_country, position, appearances, lineups, minutes,"
        " rating, captain, shots_total, shots_on, goals, assists, passes_total,"
        " passes_key, passes_accuracy, tackles_total, tackles_blocks,"
        " tackles_interceptions, duels_total, duels_won, dribbles_attempts,"
        " dribbles_success, dribbles_past, fouls_drawn, fouls_committed,"
        " cards_yellow, cards_yellowred, cards_red, penalty_won, penalty_scored,"
        " penalty_missed, xg, xag, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,"
        "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (s["api_player_id"], s["season"], s.get("team_name"),
         s.get("league_name"), s.get("league_country"), s.get("position"),
         s.get("appearances"), s.get("lineups"), s.get("minutes"),
         s.get("rating"), int(bool(s.get("captain"))),
         s.get("shots_total"), s.get("shots_on"), s.get("goals"),
         s.get("assists"), s.get("passes_total"), s.get("passes_key"),
         s.get("passes_accuracy"), s.get("tackles_total"),
         s.get("tackles_blocks"), s.get("tackles_interceptions"),
         s.get("duels_total"), s.get("duels_won"), s.get("dribbles_attempts"),
         s.get("dribbles_success"), s.get("dribbles_past"),
         s.get("fouls_drawn"), s.get("fouls_committed"),
         s.get("cards_yellow"), s.get("cards_yellowred"), s.get("cards_red"),
         s.get("penalty_won"), s.get("penalty_scored"), s.get("penalty_missed"),
         s.get("xg"), s.get("xag"), utcnow_iso()),
    )
    conn.commit()


def upsert_injury(conn, i):
    """i: dict(api_player_id, player_name, team_name, reason, type, status,
    injury_date)。同(球员,日期,原因)覆盖。"""
    conn.execute(
        "INSERT OR REPLACE INTO injuries (api_player_id, player_name, team_name,"
        " reason, type, status, injury_date, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
        (i.get("api_player_id"), i.get("player_name"), i.get("team_name"),
         i.get("reason"), i.get("type"), i.get("status"),
         i.get("injury_date"), utcnow_iso()),
    )
    conn.commit()


def upsert_coach(conn, team_name, c):
    """c: dict(api_coach_id, name, age, nationality, photo)。每队一教练覆盖。"""
    conn.execute(
        "INSERT OR REPLACE INTO coaches (team_name, api_coach_id, name, age,"
        " nationality, photo, fetched_at) VALUES (?,?,?,?,?,?,?)",
        (team_name, c.get("api_coach_id"), c.get("name"), c.get("age"),
         c.get("nationality"), c.get("photo"), utcnow_iso()),
    )
    conn.commit()
