from __future__ import annotations

from flask import Flask
from presto_pay import PrestoPay

from flask_store import extensions
from flask_store.config import Settings, configure_logging, load_settings, log_startup
from flask_store.routes import checkout, payments, webhooks


def create_app(settings: Settings | None = None, presto: PrestoPay | None = None) -> Flask:
    configure_logging()
    settings = settings or load_settings()

    app = Flask(__name__)
    extensions.init_app(app, settings, presto or PrestoPay.from_env(settings.presto_env))
    app.register_blueprint(checkout.bp)
    app.register_blueprint(payments.bp)
    app.register_blueprint(webhooks.bp)

    log_startup(settings, "Flask")
    return app
