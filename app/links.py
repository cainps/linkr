import io
import segno
import sqlite3
from flask import Blueprint, g, jsonify, request, current_app, Response

from .auth import login_required
from .db import get_db
from .rules import (RuleError, generate_slug, parse_expiry, parse_max_clicks,
                    validate_slug, validate_target_url)

bp = Blueprint("links", __name__, url_prefix="/api/links")


def serialize(row) -> dict:
    base = current_app.config["BASE_URL"] or request.host_url.rstrip("/")
    d = dict(row)
    d["short_url"] = f"{base}/{row['slug']}"
    d["is_active"] = bool(row["is_active"])
    return d


def _owned(link_id):
    return get_db().execute("SELECT * FROM links WHERE id = ? AND user_id = ?", (link_id, g.user_id)).fetchone()


@bp.errorhandler(RuleError)
def handle_rule_error(e):
    return jsonify(error=e.message), e.status


@bp.post("")
@login_required
def create_link():
    body = request.get_json(silent=True) or {}
    db = get_db()
    target = validate_target_url(body.get("url"), request.host)
    expires_at = parse_expiry(body.get("expires_at"))
    max_clicks = parse_max_clicks(body.get("max_clicks"))
    title = (body.get("title") or "").strip()[:120] or None

    # Regra: limite de links ativos por usuário (plano "free")
    active = db.execute("SELECT COUNT(*) FROM links WHERE user_id = ? AND is_active = 1", (g.user_id,)).fetchone()[0]
    if active >= current_app.config["MAX_ACTIVE_LINKS"]:
        raise RuleError(f"Limite de {current_app.config['MAX_ACTIVE_LINKS']} links ativos atingido", 403)

    custom = (body.get("slug") or "").strip()
    attempts = 1 if custom else 5   # slug aleatório: tenta de novo em caso de colisão
    for _ in range(attempts):
        slug = validate_slug(custom) if custom else generate_slug()
        try:
            cur = db.execute(
                "INSERT INTO links(user_id, slug, target_url, title, expires_at, max_clicks) VALUES (?,?,?,?,?,?)",
                (g.user_id, slug, target, title, expires_at, max_clicks))
            db.commit()
            return jsonify(serialize(db.execute("SELECT * FROM links WHERE id = ?", (cur.lastrowid,)).fetchone())), 201
        except sqlite3.IntegrityError:
            db.rollback()
            if custom:
                raise RuleError("Esse slug já está em uso", 409)
    raise RuleError("Não foi possível gerar um slug único, tente novamente", 503)


@bp.get("")
@login_required
def list_links():
    page = max(int(request.args.get("page", 1) or 1), 1)
    per_page = min(max(int(request.args.get("per_page", 20) or 20), 1), 100)
    q = (request.args.get("q") or "").strip()
    where, params = "user_id = ?", [g.user_id]
    if q:
        where += " AND (slug LIKE ? OR target_url LIKE ? OR title LIKE ?)"
        params += [f"%{q}%"] * 3
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM links WHERE {where}", params).fetchone()[0]
    rows = db.execute(f"SELECT * FROM links WHERE {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                      params + [per_page, (page - 1) * per_page]).fetchall()
    return jsonify(items=[serialize(r) for r in rows], total=total, page=page, per_page=per_page)


@bp.get("/<int:link_id>")
@login_required
def get_link(link_id):
    row = _owned(link_id)
    return (jsonify(serialize(row)), 200) if row else (jsonify(error="Link não encontrado"), 404)


@bp.patch("/<int:link_id>")
@login_required
def update_link(link_id):
    row = _owned(link_id)
    if not row:
        return jsonify(error="Link não encontrado"), 404
    body = request.get_json(silent=True) or {}
    fields = {}
    if "url" in body: fields["target_url"] = validate_target_url(body["url"], request.host)
    if "title" in body: fields["title"] = (body["title"] or "").strip()[:120] or None
    if "expires_at" in body: fields["expires_at"] = parse_expiry(body["expires_at"])
    if "max_clicks" in body: fields["max_clicks"] = parse_max_clicks(body["max_clicks"])
    if "is_active" in body: fields["is_active"] = 1 if body["is_active"] else 0
    # slug é imutável: trocar quebraria links já divulgados
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        get_db().execute(f"UPDATE links SET {sets} WHERE id = ?", [*fields.values(), link_id])
        get_db().commit()
    return jsonify(serialize(_owned(link_id)))


@bp.delete("/<int:link_id>")
@login_required
def delete_link(link_id):
    if not _owned(link_id):
        return jsonify(error="Link não encontrado"), 404
    get_db().execute("DELETE FROM links WHERE id = ?", (link_id,))   # clicks removidos via ON DELETE CASCADE
    get_db().commit()
    return "", 204

@bp.get("/<int:link_id>/qr.svg")
@login_required
def link_qr(link_id):
    row = _owned(link_id)                      # só o dono vê o QR do seu link
    if not row:
        return jsonify(error="Link não encontrado"), 404
    buf = io.BytesIO()                          # "arquivo na memória" para não gravar nada no disco
    segno.make(serialize(row)["short_url"], error="m").save(
        buf, kind="svg", scale=8, border=2, dark="#000", light="#fff")
    return Response(buf.getvalue(), mimetype="image/svg+xml")