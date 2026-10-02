from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

PROJECT_DIR = Path(__file__).resolve().parents[2]

log = logging.getLogger("flask_store")


@dataclass(frozen=True, slots=True)
class Settings:
    public_base_url: str
    currency: str
    presto_mrn: str
    presto_env: Mapping[str, str]

    @property
    def environment(self) -> str:
        return self.presto_env.get("PRESTOPAY_BASE_URL") or self.presto_env.get("PRESTOPAY_ENV", "")

    @property
    def merchant_id(self) -> str:
        return self.presto_env.get("PRESTOPAY_MID", "")

    @property
    def notify_url(self) -> str:
        return f"{self.public_base_url}/presto/notify"

    @property
    def redirect_url(self) -> str:
        return f"{self.public_base_url}/return"

    def return_url_for(self, txn_ref_num: str) -> str:
        return f"{self.redirect_url}/{txn_ref_num}"


def load_settings(environ: Mapping[str, str] | None = None, env_file: Path | None = PROJECT_DIR / ".env") -> Settings:
    values: dict[str, str] = {}
    if env_file is not None and env_file.exists():
        values.update({key: value for key, value in dotenv_values(env_file).items() if value is not None})
    values.update(os.environ if environ is None else environ)

    presto_mrn = values.get("PRESTOPAY_MRN", "")
    if not presto_mrn:
        raise RuntimeError("PRESTOPAY_MRN is not set; add it to .env or export it")

    return Settings(
        public_base_url=values.get("APP_PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/"),
        currency=values.get("APP_DEFAULT_CURRENCY", "MYR"),
        presto_mrn=presto_mrn,
        presto_env=values,
    )


def log_startup(settings: Settings, framework: str) -> None:
    log.info("Presto Pay demo (%s) ready", framework)
    log.info("Checkout: http://localhost:8080/")
    log.info("Gateway: env=%s mid=%s prestoMrn=%s", settings.environment, settings.merchant_id, settings.presto_mrn)
    log.info(
        "Callbacks (must be reachable by Presto): notifyUrl=%s redirectUrl=%s",
        settings.notify_url,
        settings.redirect_url,
    )


def configure_logging() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.setLevel(logging.INFO)
