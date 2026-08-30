"""Email delivery over plain SMTP -- no third-party dependencies."""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid


class MailConfigError(RuntimeError):
    """Raised when the SMTP settings are missing or malformed."""


@dataclass(frozen=True)
class MailConfig:
    host: str
    port: int
    username: str | None
    password: str | None
    sender: str
    recipients: tuple[str, ...]
    sender_name: str = "Weekly Recipe Club"
    use_tls: bool = True   # STARTTLS on a submission port
    use_ssl: bool = False  # implicit TLS, usually port 465

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "MailConfig":
        env = dict(os.environ if env is None else env)

        def flag(name: str, default: bool) -> bool:
            raw = env.get(name)
            if raw is None or not raw.strip():
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        missing = [key for key in ("SMTP_HOST", "MAIL_FROM", "MAIL_TO") if not env.get(key, "").strip()]
        if missing:
            raise MailConfigError(
                "missing environment variable(s): " + ", ".join(missing)
                + ". See README.md for the full list."
            )

        raw_port = env.get("SMTP_PORT", "587").strip()
        try:
            port = int(raw_port)
        except ValueError:
            raise MailConfigError(f"SMTP_PORT must be a number, got {raw_port!r}") from None

        recipients = tuple(part.strip() for part in env["MAIL_TO"].replace(";", ",").split(",") if part.strip())
        if not recipients:
            raise MailConfigError("MAIL_TO did not contain any addresses")

        return cls(
            host=env["SMTP_HOST"].strip(),
            port=port,
            username=(env.get("SMTP_USERNAME") or "").strip() or None,
            password=env.get("SMTP_PASSWORD") or None,
            sender=env["MAIL_FROM"].strip(),
            recipients=recipients,
            sender_name=(env.get("MAIL_FROM_NAME") or "Weekly Recipe Club").strip(),
            use_ssl=flag("SMTP_SSL", port == 465),
            use_tls=flag("SMTP_STARTTLS", port != 465),
        )


def build_message(config: MailConfig, subject: str, text_body: str, html_body: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((config.sender_name, config.sender))
    message["To"] = ", ".join(config.recipients)
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=config.sender.rpartition("@")[2] or None)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    return message


def send_message(config: MailConfig, message: EmailMessage, *, timeout: int = 30) -> None:
    context = ssl.create_default_context()
    if config.use_ssl:
        server: smtplib.SMTP = smtplib.SMTP_SSL(config.host, config.port, timeout=timeout, context=context)
    else:
        server = smtplib.SMTP(config.host, config.port, timeout=timeout)
    with server:
        server.ehlo()
        if not config.use_ssl and config.use_tls:
            server.starttls(context=context)
            server.ehlo()
        if config.username and config.password:
            server.login(config.username, config.password)
        server.send_message(message, from_addr=config.sender, to_addrs=list(config.recipients))
