"""Thin Brevo (transactional email API) wrapper. Until BREVO_API_KEY is set in
the environment, send_email() logs the message to the console instead of
calling the API, so registration/login/invite flows keep working end-to-end in dev."""
import logging

import httpx

from app.config import settings

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """Brevo refused or couldn't be reached. Callers turn this into a clear
    error for the user instead of a 500, and roll back what the email was for."""


async def send_email(to: str, subject: str, html_content: str) -> None:
    if not settings.brevo_api_key:
        print(f"\n----- [dev email fallback] -----\nTo: {to}\nSubject: {subject}\n{html_content}\n---------------------------------\n")
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                BREVO_URL,
                headers={
                    "api-key": settings.brevo_api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "sender": {"email": settings.email_from, "name": settings.email_from_name},
                    "to": [{"email": to}],
                    "subject": subject,
                    "htmlContent": html_content,
                },
            )
    except httpx.HTTPError as e:
        logger.error("Brevo unreachable sending %r: %s", subject, e)
        raise EmailDeliveryError("Email service unreachable") from e
    if response.status_code >= 400:
        # Most common causes: EMAIL_FROM is not a verified sender in Brevo,
        # or the API key is wrong/revoked (401).
        logger.error("Brevo rejected %r from %s: HTTP %s %s",
                     subject, settings.email_from, response.status_code, response.text[:500])
        raise EmailDeliveryError(f"Brevo HTTP {response.status_code}")
