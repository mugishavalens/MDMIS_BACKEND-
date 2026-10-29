"""Thin SendGrid wrapper. Until SENDGRID_API_KEY is set in the environment,
send_email() logs the message to the console instead of calling the API, so
registration/login/invite flows keep working end-to-end in dev."""
import logging

import httpx

from app.config import settings

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """SendGrid refused or couldn't be reached. Callers turn this into a clear
    error for the user instead of a 500, and roll back what the email was for."""


async def send_email(to: str, subject: str, html_content: str) -> None:
    if not settings.sendgrid_api_key:
        print(f"\n----- [dev email fallback] -----\nTo: {to}\nSubject: {subject}\n{html_content}\n---------------------------------\n")
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                SENDGRID_URL,
                headers={
                    "Authorization": f"Bearer {settings.sendgrid_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "personalizations": [{"to": [{"email": to}]}],
                    "from": {"email": settings.email_from, "name": settings.email_from_name},
                    "subject": subject,
                    "content": [{"type": "text/html", "value": html_content}],
                },
            )
    except httpx.HTTPError as e:
        logger.error("SendGrid unreachable sending %r: %s", subject, e)
        raise EmailDeliveryError("Email service unreachable") from e
    if response.status_code >= 400:
        # Most common cause: EMAIL_FROM is not a verified Sender Identity in SendGrid (403).
        logger.error("SendGrid rejected %r from %s: HTTP %s %s",
                     subject, settings.email_from, response.status_code, response.text[:500])
        raise EmailDeliveryError(f"SendGrid HTTP {response.status_code}")
