import os, secrets
from flask import Flask, jsonify, send_from_directory

from . import analytics, auth, db, links, redirect


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.update(
        DATABASE=os.environ.get("DATABASE", "linkr.db"),
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),  # defina SECRET_KEY em produção
        BASE_URL=os.environ.get("BASE_URL", ""),
        MAX_ACTIVE_LINKS=int(os.environ.get("MAX_ACTIVE_LINKS", 100)),
        LOGIN_MAX_ATTEMPTS=5,
    )
    if config:
        app.config.update(config)
    db.init_app(app)

    static_dir = os.path.join(os.path.dirname(__file__), "..", "static")

    @app.get("/")
    def index():
        return send_from_directory(static_dir, "index.html")

    @app.errorhandler(404)
    def not_found(_e):
        return jsonify(error="Não encontrado"), 404

    for bp in (auth.bp, links.bp, analytics.bp, redirect.bp):   # redirect por último: rota /<slug> é curinga
        app.register_blueprint(bp)
    return app
