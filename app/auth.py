import hashlib, hmac, os, re, time
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import Blueprint, current_app, g, jsonify, request

from .db import get_db

bp = Blueprint("auth", __name__, url_prefix="/api/auth")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_attempts: dict[str, list[float]] = {}   # rate limit simples em memória (use Redis em produção)


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    salt_hex, h_hex = stored.split("$")
    h = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return hmac.compare_digest(h.hex(), h_hex)


def make_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=24)
    return jwt.encode({"sub": str(user_id), "exp": exp}, current_app.config["SECRET_KEY"], "HS256")


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify(error="Token ausente"), 401
        try:
            data = jwt.decode(header[7:], current_app.config["SECRET_KEY"], algorithms=["HS256"])
        except jwt.PyJWTError:
            return jsonify(error="Token inválido ou expirado"), 401
        g.user_id = int(data["sub"])
        return fn(*a, **kw)
    return wrapper


def _too_many_attempts(key: str) -> bool:
    now = time.time()
    window = [t for t in _attempts.get(key, []) if now - t < 300]
    _attempts[key] = window
    return len(window) >= current_app.config["LOGIN_MAX_ATTEMPTS"]


@bp.post("/register")
def register():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not EMAIL_RE.match(email):
        return jsonify(error="E-mail inválido"), 422
    if len(password) < 8:
        return jsonify(error="A senha precisa ter ao menos 8 caracteres"), 422
    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        return jsonify(error="E-mail já cadastrado"), 409
    cur = db.execute("INSERT INTO users(email, password_hash) VALUES (?, ?)", (email, hash_password(password)))
    db.commit()
    return jsonify(token=make_token(cur.lastrowid), email=email), 201


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    key = f"{request.remote_addr}:{email}"
    if _too_many_attempts(key):
        return jsonify(error="Muitas tentativas. Tente novamente em 5 minutos."), 429
    row = get_db().execute("SELECT id, password_hash FROM users WHERE email = ?", (email,)).fetchone()
    if not row or not verify_password(body.get("password") or "", row["password_hash"]):
        _attempts.setdefault(key, []).append(time.time())
        return jsonify(error="Credenciais inválidas"), 401   # mensagem única: não revela se o e-mail existe
    _attempts.pop(key, None)
    return jsonify(token=make_token(row["id"]), email=email)
