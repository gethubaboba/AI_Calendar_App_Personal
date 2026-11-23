"""TLS-only SMTP delivery in a subprocess with a hard wall-clock timeout."""
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from email.message import EmailMessage
from urllib.parse import urlsplit

from fastapi import HTTPException

DELIVERY_TIMEOUT = 20
SOCKET_TIMEOUT = 5
DEFAULT_RESET_URL = "https://gethubaboba.github.io/AI_Calendar_App_Personal/reset-password/"


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    sender: str
    tls_mode: str
    reset_url: str


def configuration():
    try:
        host = os.environ.get("SMTP_HOST", "").strip()
        port = int(os.environ.get("SMTP_PORT", "465"))
        username = os.environ.get("SMTP_USERNAME", "").strip()
        password = os.environ.get("SMTP_PASSWORD", "")
        sender = os.environ.get("SMTP_FROM", "").strip()
        mode = os.environ.get("SMTP_TLS_MODE", "ssl").strip().lower()
        reset_url = os.environ.get("PASSWORD_RESET_URL", DEFAULT_RESET_URL).strip()
        url = urlsplit(reset_url)
        url.port  # Validate an optional configured port.
        if (not host or any(c.isspace() for c in host) or not 1 <= port <= 65535
                or not username or not password or mode not in ("ssl", "starttls")
                or not re.fullmatch(r"[^\s@<>]+@[^\s@<>]+", sender)
                or url.scheme != "https" or not url.hostname or url.username or url.password
                or url.query or url.fragment or any(c.isspace() for c in reset_url)
                or any(c in username + host + sender + reset_url for c in "\r\n\x00")):
            raise ValueError
        return MailConfig(host, port, username, password, sender, mode, reset_url)
    except (ValueError, TypeError):
        raise HTTPException(503, "Восстановление пароля временно недоступно") from None


def send_reset_mail(config, recipient, token):
    # Secrets travel through stdin, never command arguments or child output.
    payload = json.dumps({"config": asdict(config), "recipient": recipient, "token": token})
    try:
        result = subprocess.run(
            [sys.executable, "-m", "services.reset_mail"],
            input=payload.encode("utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=DELIVERY_TIMEOUT, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def send_smtp(config, recipient, token):
    message = EmailMessage()
    message["From"] = config.sender
    message["To"] = recipient
    message["Subject"] = "Smart Calendar — восстановление пароля"
    message.set_content(
        "Для изменения пароля Smart Calendar откройте ссылку в течение 15 минут:\n\n"
        + config.reset_url + "#token=" + token
        + "\n\nЕсли вы не запрашивали изменение пароля, проигнорируйте это письмо. "
        "Ваш текущий пароль продолжает действовать.\n"
    )
    context = ssl.create_default_context()
    if config.tls_mode == "ssl":
        smtp = smtplib.SMTP_SSL(config.host, config.port, timeout=SOCKET_TIMEOUT,
                                context=context, local_hostname="smart-calendar")
    elif config.tls_mode == "starttls":
        smtp = smtplib.SMTP(config.host, config.port, timeout=SOCKET_TIMEOUT, local_hostname="smart-calendar")
    else:
        raise ValueError("TLS is required")
    try:
        smtp.ehlo()
        if config.tls_mode == "starttls":
            smtp.starttls(context=context)
            smtp.ehlo()
        smtp.login(config.username, config.password)
        refused = smtp.send_message(message, from_addr=config.sender, to_addrs=[recipient])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    finally:
        smtp.close()


if __name__ == "__main__":
    try:
        data = json.load(sys.stdin)
        send_smtp(MailConfig(**data["config"]), data["recipient"], data["token"])
    except Exception:
        # SMTP exceptions may contain addresses, credentials or message content.
        sys.exit(1)
