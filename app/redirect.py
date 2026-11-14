import hashlib
from datetime import datetime, timezone

from flask import Blueprint, abort, current_app, jsonify, redirect, request

from .db import get_db
from .rules import is_bot, parse_user_agent, referrer_host

bp = Blueprint("redirect", __name__)


@bp.get("/health")
def health():
    return jsonify(status="ok")


@bp.get("/<slug>")
def follow(slug):
    db = get_db()
    link = db.execute("SELECT * FROM links WHERE slug = ?", (slug,)).fetchone()
    if not link or not link["is_active"]:
        abort(404)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if link["expires_at"] and link["expires_at"] <= now:
        return jsonify(error="Este link expirou"), 410

    ua = request.headers.get("User-Agent", "")
    if is_bot(ua):                      # bots/prefetch não contam como clique e não consomem max_clicks
        return redirect(link["target_url"], 302)

    # Incremento atômico respeitando max_clicks: sem race condition entre requisições concorrentes
    cur = db.execute(
        "UPDATE links SET click_count = click_count + 1 WHERE id = ? AND (max_clicks IS NULL OR click_count < max_clicks)",
        (link["id"],))
    if cur.rowcount == 0:
        db.commit()
        return jsonify(error="Este link atingiu o limite de cliques"), 410

    device, browser = parse_user_agent(ua)
    country = (request.headers.get("CF-IPCountry") or request.headers.get("X-Country") or "").strip().upper()[:7] or "Unknown"
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0]).strip()
    visitor = hashlib.sha256(f"{current_app.config['SECRET_KEY']}|{ip}|{ua}".encode()).hexdigest()[:32]
    db.execute("INSERT INTO clicks(link_id, country, device, browser, referrer, visitor_hash) VALUES (?,?,?,?,?,?)",
               (link["id"], country, device, browser, referrer_host(request.referrer), visitor))
    db.commit()
    resp = redirect(link["target_url"], 302)   # 302 (não 301): 301 seria cacheado pelo browser e esconderia cliques
    resp.headers["Cache-Control"] = "no-store"
    return resp
