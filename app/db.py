import sqlite3
from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS links (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slug        TEXT NOT NULL UNIQUE,            -- índice único = lookup O(log n) no redirect
    target_url  TEXT NOT NULL,
    title       TEXT,
    expires_at  TEXT,                            -- NULL = nunca expira
    max_clicks  INTEGER,                         -- NULL = ilimitado
    click_count INTEGER NOT NULL DEFAULT 0,      -- contador desnormalizado (evita COUNT(*) na listagem)
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_links_user ON links(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS clicks (
    id           INTEGER PRIMARY KEY,
    link_id      INTEGER NOT NULL REFERENCES links(id) ON DELETE CASCADE,
    clicked_at   TEXT NOT NULL DEFAULT (datetime('now')),
    country      TEXT NOT NULL DEFAULT 'Unknown',
    device       TEXT NOT NULL DEFAULT 'desktop',
    browser      TEXT NOT NULL DEFAULT 'Other',
    referrer     TEXT NOT NULL DEFAULT 'direct',
    visitor_hash TEXT NOT NULL                   -- sha256(salt+ip+ua): conta únicos sem guardar IP
);
-- Índice composto: todas as queries de analytics filtram por link e janela de tempo
CREATE INDEX IF NOT EXISTS idx_clicks_link_time ON clicks(link_id, clicked_at);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
