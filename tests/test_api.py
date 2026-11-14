import pytest
from datetime import datetime, timedelta, timezone

from app import create_app, auth

CHROME = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


@pytest.fixture
def client(tmp_path):
    auth._attempts.clear()
    app = create_app({"DATABASE": str(tmp_path / "t.db"), "SECRET_KEY": "test-secret-key-with-at-least-32-bytes!!", "TESTING": True, "MAX_ACTIVE_LINKS": 3})
    return app.test_client()


def register(client, email="a@x.com"):
    r = client.post("/api/auth/register", json={"email": email, "password": "12345678"})
    assert r.status_code == 201
    return {"Authorization": f"Bearer {r.json['token']}"}


def make(client, h, **kw):
    return client.post("/api/links", json={"url": "https://example.com/pagina", **kw}, headers=h)


# ---------- auth ----------
def test_register_validations_and_duplicate(client):
    assert client.post("/api/auth/register", json={"email": "ruim", "password": "12345678"}).status_code == 422
    assert client.post("/api/auth/register", json={"email": "a@x.com", "password": "curta"}).status_code == 422
    register(client)
    assert client.post("/api/auth/register", json={"email": "A@x.com", "password": "12345678"}).status_code == 409


def test_login_ok_wrong_password_and_rate_limit(client):
    register(client)
    assert client.post("/api/auth/login", json={"email": "a@x.com", "password": "12345678"}).status_code == 200
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "a@x.com", "password": "errada"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "a@x.com", "password": "12345678"}).status_code == 429


def test_protected_routes_need_token(client):
    assert client.get("/api/links").status_code == 401
    assert client.get("/api/links", headers={"Authorization": "Bearer lixo"}).status_code == 401


# ---------- regras de criação ----------
def test_create_random_and_custom_slug(client):
    h = register(client)
    r = make(client, h)
    assert r.status_code == 201 and len(r.json["slug"]) == 7
    r = make(client, h, slug="meu-link")
    assert r.status_code == 201 and r.json["short_url"].endswith("/meu-link")


def test_slug_rules(client):
    h = register(client)
    make(client, h, slug="promo")
    assert make(client, h, slug="promo").status_code == 409          # duplicado
    assert make(client, h, slug="api").status_code == 409            # reservado
    assert make(client, h, slug="a b").status_code == 422            # caracteres inválidos
    assert make(client, h, slug="ab").status_code == 422             # curto demais


@pytest.mark.parametrize("url", ["ftp://x.com", "javascript:alert(1)", "http://localhost/x",
                                 "http://127.0.0.1/x", "http://192.168.0.1", "http://localhost.local", "nada", "http://localhost"])
def test_rejects_dangerous_urls(client, url):
    h = register(client)
    assert client.post("/api/links", json={"url": url}, headers=h).status_code == 422


def test_rejects_redirect_loop(client):
    h = register(client)
    assert client.post("/api/links", json={"url": "http://localhost/abc"}, headers=h).status_code == 422


def test_expiry_must_be_future(client):
    h = register(client)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert make(client, h, expires_at=past).status_code == 422


def test_active_link_limit(client):
    h = register(client)
    for _ in range(3):
        assert make(client, h).status_code == 201
    assert make(client, h).status_code == 403


# ---------- redirect + analytics ----------
def test_redirect_counts_click_and_records_analytics(client):
    h = register(client)
    link = make(client, h, slug="gogo").json
    r = client.get("/gogo", headers={**CHROME, "Referer": "https://www.twitter.com/post", "CF-IPCountry": "br"})
    assert r.status_code == 302 and r.headers["Location"] == "https://example.com/pagina"
    a = client.get(f"/api/links/{link['id']}/analytics", headers=h).json
    assert a["total_clicks"] == 1 and a["unique_visitors"] == 1
    assert a["countries"][0]["name"] == "BR" and a["referrers"][0]["name"] == "twitter.com"
    assert a["browsers"][0]["name"] == "Chrome" and a["devices"][0]["name"] == "desktop"
    assert sum(d["clicks"] for d in a["by_day"]) == 1 and len(a["by_day"]) == 30


def test_bots_are_redirected_but_not_counted(client):
    h = register(client)
    link = make(client, h, slug="gogo").json
    r = client.get("/gogo", headers={"User-Agent": "Googlebot/2.1"})
    assert r.status_code == 302
    assert client.get(f"/api/links/{link['id']}", headers=h).json["click_count"] == 0


def test_max_clicks_enforced(client):
    h = register(client)
    make(client, h, slug="once", max_clicks=2)
    assert client.get("/once", headers=CHROME).status_code == 302
    assert client.get("/once", headers=CHROME).status_code == 302
    assert client.get("/once", headers=CHROME).status_code == 410


def test_expired_and_inactive_links(client):
    h = register(client)
    link = make(client, h, slug="exp").json
    with client.application.app_context():
        from app.db import get_db
        get_db().execute("UPDATE links SET expires_at = '2000-01-01 00:00:00' WHERE id = ?", (link["id"],))
        get_db().commit()
    assert client.get("/exp", headers=CHROME).status_code == 410
    link2 = make(client, h, slug="off").json
    client.patch(f"/api/links/{link2['id']}", json={"is_active": False}, headers=h)
    assert client.get("/off", headers=CHROME).status_code == 404
    assert client.get("/naoexiste", headers=CHROME).status_code == 404


# ---------- isolamento entre usuários ----------
def test_users_cannot_access_each_others_links(client):
    h1, h2 = register(client, "a@x.com"), register(client, "b@x.com")
    link = make(client, h1, slug="priv").json
    assert client.get(f"/api/links/{link['id']}", headers=h2).status_code == 404
    assert client.get(f"/api/links/{link['id']}/analytics", headers=h2).status_code == 404
    assert client.patch(f"/api/links/{link['id']}", json={"title": "x"}, headers=h2).status_code == 404
    assert client.delete(f"/api/links/{link['id']}", headers=h2).status_code == 404
    assert client.get("/api/links", headers=h2).json["total"] == 0


def test_update_delete_and_cascade(client):
    h = register(client)
    link = make(client, h, slug="xone").json
    client.get("/xone", headers=CHROME)
    r = client.patch(f"/api/links/{link['id']}", json={"url": "https://novo.com", "slug": "hack"}, headers=h)
    assert r.json["target_url"] == "https://novo.com" and r.json["slug"] == "xone"   # slug imutável
    assert client.delete(f"/api/links/{link['id']}", headers=h).status_code == 204
    with client.application.app_context():
        from app.db import get_db
        assert get_db().execute("SELECT COUNT(*) FROM clicks").fetchone()[0] == 0


def test_list_pagination_and_search(client):
    h = register(client)
    for s in ("alpha", "beta", "gamma"):
        make(client, h, slug=s)
    assert client.get("/api/links?per_page=2", headers=h).json["total"] == 3
    assert len(client.get("/api/links?per_page=2", headers=h).json["items"]) == 2
    assert client.get("/api/links?q=bet", headers=h).json["total"] == 1


def test_overview(client):
    h = register(client)
    make(client, h, slug="ovw")
    client.get("/ovw", headers=CHROME)
    o = client.get("/api/analytics/overview?days=7", headers=h).json
    assert o["total_links"] == 1 and o["total_clicks"] == 1 and o["top_links"][0]["slug"] == "ovw" and len(o["by_day"]) == 7


def test_qr_code(client):
    pytest.importorskip("segno")
    h = register(client)
    link = make(client, h, slug="qrtest").json
    r = client.get(f"/api/links/{link['id']}/qr.svg", headers=h)
    assert r.status_code == 200 and r.mimetype == "image/svg+xml" and b"<svg" in r.data
    h2 = register(client, "b@x.com")
    assert client.get(f"/api/links/{link['id']}/qr.svg", headers=h2).status_code == 404   # outro usuário não acessa