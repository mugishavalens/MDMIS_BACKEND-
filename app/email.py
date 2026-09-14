"""Thin SendGrid wrapper. Until SENDGRID_API_KEY is set in the environment,
send_email() logs the message to the console instead of calling the API, so
registration/login/invite flows keep working end-to-end in dev."""
import httpx

from app.config import settings

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"


async def send_email(to: str, subject: str, html_content: str) -> None:
    if not settings.sendgrid_api_key:
        print(f"\n----- [dev email fallback] -----\nTo: {to}\nSubject: {subject}\n{html_content}\n---------------------------------\n")
        return

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
        response.raise_for_status()
