from os import environ as env, path
from pathlib import Path

assert env.get("SECRET_KEY"), "Secret key not found"
assert env.get("BLOCKONOMICS_API_KEY"), "Blockonomics API not found"

config = {
    "secret_key": env.get("SECRET_KEY"),
    "blockonomics_api_key": env.get("BLOCKONOMICS_API_KEY"),
    "base_dir": Path(__file__).resolve().parent.parent,
    "static_root": path.join(Path(__file__).resolve().parent.parent, "static/"),
    "debug": True,
    "allowed_hosts": ['*'],
    "language_code": "en-us",
    "time_zone": "UTC",
    "use_i18n": True,
    "use_l10n": True,
    "use_tz": True,
    "static_url": "/static/",
    "email_use_tls": True,
    "smtp_host": env.get("SMTP_HOST"),
    "smtp_user": env.get("SMTP_USER"),
    "smtp_password": env.get("SMTP_PASSWORD"),
    "smtp_port": env.get("SMTP_PORT")
}

