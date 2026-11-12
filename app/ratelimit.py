"""Sliding-window rate limits for the unauthenticated auth endpoints:
password guessing, verification-code guessing, and email bombing (every
code request sends a real email through the paid provider).

In memory, per process: right for the single Render instance this runs
on. Several instances would each count separately (limits multiply by
the instance count), and would need a shared store such as Redis.

Per-email limits are the real protection (an attacker can't fake whose
account they're targeting). Per-IP limits are deliberately generous: the
IP comes from X-Forwarded-For, which a client can set itself, and on
Render many users can share one proxy address.
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class RateLimiter:
    def __init__(self, name: str, limit: int, window_seconds: int):
        self.name = name
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque:
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        return hits

    def check(self, key: str) -> None:
        """Refuse (429) if `key` has used up its allowance; doesn't count."""
        now = time.monotonic()
        hits = self._prune(key, now)
        if len(hits) >= self.limit:
            retry = int(hits[0] + self.window - now) + 1
            minutes = max(1, round(retry / 60))
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Too many attempts. Please try again in {minutes} minute{'s' if minutes != 1 else ''}.",
                headers={"Retry-After": str(retry)},
            )

    def hit(self, key: str) -> None:
        """Count one use, refusing first if the allowance is used up."""
        self.check(key)
        self._hits[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def clear(self) -> None:
        self._hits.clear()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


_15_MIN, _HOUR = 15 * 60, 60 * 60

# Failed sign-ins per account: 5 wrong passwords, then a 15-minute pause.
login_failures = RateLimiter("login_failures", 5, _15_MIN)
login_per_ip = RateLimiter("login_per_ip", 100, _15_MIN)
# Every request that emails a code (register, sign-in of an unverified
# account, resend, password reset): per address and per IP.
code_emails = RateLimiter("code_emails", 3, _15_MIN)
code_emails_per_ip = RateLimiter("code_emails_per_ip", 30, _HOUR)
# Code guesses per account, on top of the 5-per-code limit.
code_checks = RateLimiter("code_checks", 10, _15_MIN)
registrations_per_ip = RateLimiter("registrations_per_ip", 20, _HOUR)
invite_lookups_per_ip = RateLimiter("invite_lookups_per_ip", 60, _HOUR)

ALL = (login_failures, login_per_ip, code_emails, code_emails_per_ip, code_checks,
       registrations_per_ip, invite_lookups_per_ip)
