"""API-Football v3 (api-sports.io) —— 球员/大名单/伤停/裁判/教练/首发主数据源。

注册后在 app/.env 写入 API_FOOTBALL_KEY=xxx 即可。
API 是标准 JSON（无 Cloudflare），无 key 时返回 403 + {"errors":{"token":"..."}}。

接口计费：每次调用 = 1 个额度。免费档 100 次/天；/players 每 20 人分页。
当前赛季的 /players 可能需要付费档（免费档限历史赛季），key 无效或权限不足时
错误会从 errors 字段返回，本模块原样抛出便于排查。
"""
import logging
import time

import requests

from config import API_FOOTBALL_BASE, API_FOOTBALL_KEY, USER_AGENT

log = logging.getLogger("api_football")

# 国家队名差异：我库的英文名(The Odds API 口径) -> API-Football 搜索别名。
# find_team_id 会依次尝试原名与这些别名，挑 national=True 的命中。
TEAM_ALIASES = {
    "South Korea": ["Korea Republic"],
    "USA": ["United States"],
    "Bosnia & Herzegovina": ["Bosnia and Herzegovina"],
    "Ivory Coast": ["Cote d'Ivoire", "Ivory Coast"],
    "DR Congo": ["Congo DR", "Democratic Republic of the Congo"],
    "Cape Verde": ["Cabo Verde"],
    "UAE": ["United Arab Emirates"],
    "Curaçao": ["Curacao"],
}

# 请求间隔：免费档限速较严(按 plan，通常 10-60 req/min)，保守起见每请求间隔 1s。
_MIN_INTERVAL = 1.0
_last_request = 0.0

# 本次进程累计 API 调用次数（额度预算用，免费档 100/天）
_call_count = 0


def call_count():
    return _call_count


class ApiFootballError(Exception):
    """API 调用失败（网络、限流、权限不足、key 无效等）。errors 原文见 .errors。"""

    def __init__(self, msg, errors=None):
        super().__init__(msg)
        self.errors = errors or {}


def _headers():
    if not API_FOOTBALL_KEY:
        raise ApiFootballError("未配置 API_FOOTBALL_KEY，请在 app/.env 写入后重试")
    return {"x-apisports-key": API_FOOTBALL_KEY, "User-Agent": USER_AGENT}


def _throttle():
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request = time.monotonic()


def _get(path, params=None, retries=3):
    """核心请求。返回 response JSON；失败抛 ApiFootballError(含 errors 原文)。"""
    global _call_count
    params = params or {}
    last_err = None
    for attempt in range(1, retries + 1):
        _throttle()
        try:
            resp = requests.get(
                f"{API_FOOTBALL_BASE}{path}", params=params,
                headers=_headers(), timeout=30,
            )
            _call_count += 1
            # 限流头落盘观察（免费档尤其要盯）
            rem = resp.headers.get("x-ratelimit-remaining")
            if rem is not None:
                log.info("API-Football 限流剩余: %s (path=%s)", rem, path)
            data = resp.json()
            # API 即使 HTTP 200 也可能在 errors 里报错（如权限不足/参数错）
            errs = data.get("errors")
            if errs:
                # errors 可能是 {} (空=无错) 或 {field: msg} 或字符串
                if isinstance(errs, dict) and errs:
                    raise ApiFootballError(
                        f"API-Football 返回错误: {errs}", errs)
                if isinstance(errs, str) and errs.strip():
                    raise ApiFootballError(f"API-Football 返回错误: {errs}", {"_": errs})
            return data
        except ApiFootballError:
            raise
        except Exception as e:  # 网络/JSON 解析错，指数退避重试
            last_err = e
            wait = 2 ** attempt
            log.warning("API-Football 请求 %s 失败(第%d次): %s，%ds 后重试",
                        path, attempt, e, wait)
            time.sleep(wait)
    raise ApiFootballError(f"请求 {path} 重试 {retries} 次仍失败: {last_err}")


# ---------------- 连通性 / key 校验 ----------------

def test_key():
    """校验 key 并返回账号信息。返回 (ok, info_dict, message)。

    /status 返回当前账号的 plan、剩余额度、订阅到期时间。
    """
    try:
        data = _get("/status")
    except ApiFootballError as e:
        return False, {}, f"key 校验失败: {e}"
    resp = (data.get("response") or {}).get("subscription") or {}
    acct = (data.get("response") or {}).get("account") or {}
    requests_info = (data.get("response") or {}).get("requests") or {}
    info = {
        "account": acct.get("email") or acct.get("id"),
        "plan": resp.get("plan"),
        "end": resp.get("end"),
        "remaining": requests_info.get("current"),
        "limit_day": requests_info.get("limit_day"),
    }
    return True, info, "key 有效"


# ---------------- 队名 -> team_id 解析 ----------------

def _norm(name):
    return "".join(c for c in (name or "").lower() if c.isalnum())


def find_team_id(name):
    """搜索国家队，返回 (team_id, canonical_name) 或 None。

    /teams?name= 做部分匹配，可能返回多个(含同名俱乐部)。挑 national=True 且
    名字最相似的。原名搜不到时依次尝试 TEAM_ALIASES 里的别名。
    """
    candidates = [name] + TEAM_ALIASES.get(name, [])
    tried = []
    for q in candidates:
        try:
            data = _get("/teams", {"name": q})
        except ApiFootballError as e:
            log.warning("搜索球队 '%s' 失败: %s", q, e)
            tried.append(q)
            continue
        teams = data.get("response", [])
        # 只保留国家队
        nationals = [t for t in teams if (t.get("team") or {}).get("national")]
        if not nationals:
            continue
        # 取名字相似度最高的
        best = max(
            nationals,
            key=lambda t: _sim(name, (t.get("team") or {}).get("name", "")),
        )
        tid = best["team"]["id"]
        cname = best["team"]["name"]
        log.info("队名解析: %s -> #%s %s", name, tid, cname)
        return tid, cname
    log.error("未找到国家队 '%s'（尝试过 %s）。可用 fetch_players.py --team 手动指定 id",
              name, tried)
    return None


def _sim(a, b):
    import difflib
    a, b = _norm(a), _norm(b)
    if a == b or a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------- 球员/大名单 ----------------

def get_team_players(team_id, season):
    """拉某队某赛季全部球员(含每人的多段 statistics)。

    /players 每 20 人分页，自动翻页直到 paging.total。返回 [{player, statistics}]。
    单页失败抛 ApiFootballError；调用方应 try/except 单队。
    """
    out = []
    page = 1
    while True:
        data = _get("/players", {"team": team_id, "season": season, "page": page})
        out.extend(data.get("response", []))
        paging = data.get("paging", {})
        total = int(paging.get("total", 1))
        if page >= total:
            break
        page += 1
    log.info("球队 #%s season=%s 拉取 %d 名球员", team_id, season, len(out))
    return out


def get_squad(team_id):
    """某队当前注册大名单(含未上场球员)。/squads 不分赛季、不消耗分页。

    返回 [{id, name, age, number, position, photo}] 或 []。
    比 /players 更全(覆盖未出场的新人)，但没有统计数据。
    """
    data = _get("/squads", {"team": team_id})
    rows = data.get("response", [])
    if not rows:
        return []
    players = (rows[0].get("players") or [])
    log.info("球队 #%s 注册大名单 %d 人", team_id, len(players))
    return players


# ---------------- 伤停 ----------------

def get_team_injuries(team_id):
    """某队当前伤停清单。返回 [{player, reason, type, status, date}] 或 []。"""
    data = _get("/injuries", {"team": team_id})
    rows = data.get("response", [])
    log.info("球队 #%s 伤停 %d 条", team_id, len(rows))
    return rows


# ---------------- 教练 ----------------

def get_team_coach(team_id):
    """某队主教练。返回 {id, name, age, nationality, photo} 或 None。"""
    data = _get("/coachs", {"team": team_id})
    rows = data.get("response", [])
    if not rows:
        return None
    c = rows[0]
    info = {
        "id": c.get("id"), "name": c.get("name"),
        "age": c.get("age"), "nationality": c.get("nationality"),
        "photo": c.get("photo"),
    }
    log.info("球队 #%s 主教练: %s", team_id, info.get("name"))
    return info


# ---------------- 裁判（Phase 3 用，低频缓存） ----------------

def get_referees(league_id=None, season=None):
    """裁判列表。世界杯裁判按赛事+赛季查。返回 [{id, name, nationality, ...}]。"""
    params = {}
    if league_id:
        params["league"] = league_id
    if season:
        params["season"] = season
    data = _get("/referees", params)
    return data.get("response", [])


# ---------------- 首发阵容（Phase 3 用，赛前约1h可得） ----------------

def get_fixture_lineups(fixture_id):
    """某场比赛的实际首发(含阵型)。赛前约 1 小时才有数据。返回两队阵容或 []。"""
    data = _get("/fixtures/lineups", {"fixture": fixture_id})
    return data.get("response", [])
