from datetime import datetime, timedelta, timezone
from flask import Blueprint, g, jsonify, request

from .auth import login_required
from .db import get_db

bp = Blueprint("analytics", __name__, url_prefix="/api")


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")


def _days_arg() -> int:
    try:
        return min(max(int(request.args.get("days", 30)), 1), 365)
    except ValueError:
        return 30


def _top(db, column: str, link_ids: list[int], since: str, limit=8):
    marks = ",".join("?" * len(link_ids))
    rows = db.execute(
        f"SELECT {column} AS name, COUNT(*) AS clicks FROM clicks "
        f"WHERE link_id IN ({marks}) AND clicked_at >= ? GROUP BY {column} ORDER BY clicks DESC LIMIT ?",
        [*link_ids, since, limit]).fetchall()
    return [dict(r) for r in rows]


def build_report(db, link_ids: list[int], days: int) -> dict:
    since = _since(days)
    if not link_ids:
        return {"days": days, "total_clicks": 0, "unique_visitors": 0, "by_day": [], "countries": [],
                "devices": [], "browsers": [], "referrers": []}
    marks = ",".join("?" * len(link_ids))
    totals = db.execute(
        f"SELECT COUNT(*) AS total, COUNT(DISTINCT visitor_hash) AS uniq FROM clicks "
        f"WHERE link_id IN ({marks}) AND clicked_at >= ?", [*link_ids, since]).fetchone()
    per_day = {r["d"]: r["c"] for r in db.execute(
        f"SELECT date(clicked_at) AS d, COUNT(*) AS c FROM clicks WHERE link_id IN ({marks}) "
        f"AND clicked_at >= ? GROUP BY d", [*link_ids, since])}
    today = datetime.now(timezone.utc).date()
    by_day = []
    for i in range(days - 1, -1, -1):     # preenche dias sem clique com 0 (gráfico contínuo)
        d = (today - timedelta(days=i)).isoformat()
        by_day.append({"date": d, "clicks": per_day.get(d, 0)})
    return {"days": days, "total_clicks": totals["total"], "unique_visitors": totals["uniq"], "by_day": by_day,
            "countries": _top(db, "country", link_ids, since), "devices": _top(db, "device", link_ids, since),
            "browsers": _top(db, "browser", link_ids, since), "referrers": _top(db, "referrer", link_ids, since)}


@bp.get("/links/<int:link_id>/analytics")
@login_required
def link_analytics(link_id):
    db = get_db()
    link = db.execute("SELECT id, slug FROM links WHERE id = ? AND user_id = ?", (link_id, g.user_id)).fetchone()
    if not link:
        return jsonify(error="Link não encontrado"), 404
    return jsonify(build_report(db, [link["id"]], _days_arg()))


@bp.get("/analytics/overview")
@login_required
def overview():
    db = get_db()
    ids = [r[0] for r in db.execute("SELECT id FROM links WHERE user_id = ?", (g.user_id,))]
    report = build_report(db, ids, _days_arg())
    report["total_links"] = len(ids)
    report["top_links"] = [dict(r) for r in db.execute(
        "SELECT id, slug, title, click_count FROM links WHERE user_id = ? ORDER BY click_count DESC LIMIT 5", (g.user_id,))]
    return jsonify(report)
