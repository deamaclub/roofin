"""Send through your own mailbox (free with Gmail/Outlook) and read replies back.

Gmail: turn on 2-step verification, create an App Password, and set
    ROOFIN_SMTP_USER=you@gmail.com  ROOFIN_SMTP_PASSWORD=<16-char app password>
Defaults point at Gmail; override ROOFIN_SMTP_HOST / ROOFIN_IMAP_HOST for other providers.
"""
from __future__ import annotations

import email
import imaplib
import os
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr

OPT_OUT = re.compile(r"\b(stop|unsubscribe|remove me|take me off|do not contact|don'?t contact|not interested)\b", re.I)


@dataclass
class MailConfig:
    user: str
    password: str
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    imap_host: str = "imap.gmail.com"

    @classmethod
    def from_env(cls) -> "MailConfig | None":
        user, pw = os.environ.get("ROOFIN_SMTP_USER"), os.environ.get("ROOFIN_SMTP_PASSWORD")
        if not user or not pw:
            return None
        return cls(user, pw, os.environ.get("ROOFIN_SMTP_HOST", "smtp.gmail.com"),
                   int(os.environ.get("ROOFIN_SMTP_PORT", "587")), os.environ.get("ROOFIN_IMAP_HOST", "imap.gmail.com"))


def build_message(from_name: str, from_addr: str, to: list[str], subject: str, body: str,
                  in_reply_to: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=from_addr.rsplit("@", 1)[-1])
    msg["List-Unsubscribe"] = f"<mailto:{from_addr}?subject=unsubscribe>"
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    return msg


class Mailer:
    """Thin wrapper so tests can swap in a fake."""

    def __init__(self, cfg: MailConfig):
        self.cfg = cfg

    def send(self, msg: EmailMessage) -> None:
        with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=60) as s:
            s.starttls()
            s.login(self.cfg.user, self.cfg.password)
            s.send_message(msg)

    def fetch_recent(self, days: int = 21) -> list[email.message.Message]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
        out = []
        with imaplib.IMAP4_SSL(self.cfg.imap_host) as m:
            m.login(self.cfg.user, self.cfg.password)
            m.select("INBOX", readonly=True)
            _, data = m.search(None, f'(SINCE "{since}")')
            for num in (data[0] or b"").split():
                _, parts = m.fetch(num, "(BODY.PEEK[])")
                if parts and isinstance(parts[0], tuple):
                    out.append(email.message_from_bytes(parts[0][1]))
        return out


def plain_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                return (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "replace")
        return ""
    return (msg.get_payload(decode=True) or b"").decode(msg.get_content_charset() or "utf-8", "replace")


def new_text(body: str) -> str:
    """The reply itself, without the quoted original underneath."""
    lines = []
    for line in body.splitlines():
        if line.startswith(">") or re.match(r"^On .+wrote:$", line.strip()):
            break
        lines.append(line)
    return "\n".join(lines).strip()


@dataclass
class Reply:
    sender: str
    subject: str
    text: str
    refs: str  # In-Reply-To + References
    opt_out: bool


def parse_reply(msg: email.message.Message) -> Reply:
    sender = parseaddr(msg.get("From", ""))[1].lower()
    text = new_text(plain_text(msg))
    refs = " ".join(filter(None, [msg.get("In-Reply-To"), msg.get("References")]))
    subject = msg.get("Subject", "")
    return Reply(sender, subject, text, refs, bool(OPT_OUT.search(text) or OPT_OUT.search(subject)))
