"""Popula o banco com dados de demonstração: python seed.py  →  login demo@linkr.dev / demo12345"""
import hashlib, os, random
from datetime import datetime, timedelta, timezone

from app import create_app
from app.auth import hash_password
from app.db import get_db

app = create_app()
random.seed(7)
LINKS = [("promo-black", "https://loja.example.com/black-friday", "Black Friday"),
         ("blog-sql", "https://blog.example.com/otimizando-queries-sql", "Post: otimizando SQL"),
         ("portfolio", "https://github.com/exemplo/portfolio", "Meu portfólio"),
         ("newsletter", "https://news.example.com/assinar", "Newsletter")]
COUNTRIES = ["BR"] * 10 + ["PT"] * 3 + ["US"] * 4 + ["DE", "AR", "MX", "ES"]
DEVICES = ["mobile"] * 6 + ["desktop"] * 4 + ["tablet"]
BROWSERS = ["Chrome"] * 6 + ["Safari"] * 3 + ["Firefox", "Edge"]
REFS = ["direct"] * 4 + ["instagram.com"] * 4 + ["twitter.com"] * 2 + ["linkedin.com"] * 3 + ["google.com"] * 3 + ["whatsapp.com"]

with app.app_context():
    db = get_db()
    db.execute("DELETE FROM users WHERE email = 'demo@linkr.dev'")
    uid = db.execute("INSERT INTO users(email, password_hash) VALUES (?, ?)", ("demo@linkr.dev", hash_password("demo12345"))).lastrowid
    now = datetime.now(timezone.utc)
    for slug, url, title in LINKS:
        lid = db.execute("INSERT INTO links(user_id, slug, target_url, title) VALUES (?,?,?,?)", (uid, slug, url, title)).lastrowid
        rows = []
        for day in range(45):
            for _ in range(int(random.gauss(14, 6) * (1 + (45 - day) / 90)) if random.random() > .1 else 0):
                t = now - timedelta(days=day, minutes=random.randint(0, 1439))
                rows.append((lid, t.strftime("%Y-%m-%d %H:%M:%S"), random.choice(COUNTRIES), random.choice(DEVICES),
                             random.choice(BROWSERS), random.choice(REFS), hashlib.sha256(str(random.randint(1, 400)).encode()).hexdigest()[:32]))
        db.executemany("INSERT INTO clicks(link_id, clicked_at, country, device, browser, referrer, visitor_hash) VALUES (?,?,?,?,?,?,?)", rows)
        db.execute("UPDATE links SET click_count = ? WHERE id = ?", (len(rows), lid))
    db.commit()
    print("Seed ok → demo@linkr.dev / demo12345")
