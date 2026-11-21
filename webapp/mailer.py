"""
Outgoing email for account links (RBAC Phase 4): invitations and password resets.

SMTP settings come from the environment / .env only (SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASSWORD), never from code. When they are missing, send() returns False and the
caller decides what to do (an admin is shown the link once; a forgot-password request
only logs that delivery is not configured - never the link, never to the requester).

Links are built from APP_BASE_URL when set (recommended in production, so a forged Host
header can't poison the link), otherwise from the request's own host.
"""
from __future__ import annotations

import html
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def configured() -> bool:
    return bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"))


def base_url(request_host_url: Optional[str] = None) -> str:
    url = (os.environ.get("APP_BASE_URL") or request_host_url or "http://localhost:5000/").strip()
    return url if url.endswith("/") else url + "/"


def _wrap(title: str, body_html: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#f1f5f9;margin:0;padding:24px;color:#0f172a;">
  <div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;padding:28px;">
    <div style="font-size:20px;font-weight:800;color:#2563eb;letter-spacing:1px;margin-bottom:4px;">W.A.R.L.O.G.</div>
    <div style="font-size:13px;color:#64748b;margin-bottom:20px;">{html.escape(title)}</div>
    {body_html}
    <div style="margin-top:24px;font-size:12px;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:12px;">
      This is an automated message from WARLOG. If you didn't expect it, you can ignore it.
    </div>
  </div>
</body></html>"""


def link_email(title: str, intro: str, link: str, button: str, expiry_note: str) -> Tuple[str, str]:
    """(plain text, html) for an email that carries one action link."""
    text = f"{intro}\n\n{button}: {link}\n\n{expiry_note}\n\n- WARLOG"
    body = (f'<p style="font-size:14px;line-height:1.5;">{html.escape(intro)}</p>'
            f'<p style="margin:24px 0;"><a href="{html.escape(link)}" style="background:#2563eb;color:#ffffff;'
            f'padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:700;">{html.escape(button)}</a></p>'
            f'<p style="font-size:12px;color:#64748b;">{html.escape(expiry_note)}</p>'
            f'<p style="font-size:11px;color:#94a3b8;word-break:break-all;">{html.escape(link)}</p>')
    return text, _wrap(title, body)


def send(to: str, subject: str, text: str, html_body: str) -> Tuple[bool, str]:
    """Sends one email. Returns (sent, message). Never raises."""
    if not configured():
        logger.warning("[MAIL] SMTP is not configured (SMTP_USER / SMTP_PASSWORD missing in .env); "
                       f"email '{subject}' to {to} was not sent")
        return False, "Email delivery is not configured on this server."
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        port = int(os.environ.get("SMTP_PORT", 465))
        user, password = os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"]
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"WARLOG <{user}>"
        msg["To"] = to
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as s:
                s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls()
                s.login(user, password)
                s.send_message(msg)
        logger.info(f"[MAIL] '{subject}' sent to {to}")
        return True, "Email sent."
    except Exception as e:
        logger.error(f"[MAIL] could not send '{subject}' to {to}: {e}")
        return False, "The email could not be sent."
