from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import re
import secrets
import time
import unicodedata
from collections import defaultdict, deque
from dataclasses import dataclass, field


_UNSAFE_PUBLIC_TEXT = re.compile(
    r"(?:"
    r"https?://|www\."
    r"|\b(?:\d{1,3}\.){3}\d{1,3}\b"
    r"|\b[A-Za-z]:\\"
    r"|(?:^|\s)/(?:home|opt|etc|var|tmp|run|root|mnt|srv)/"
    r"|@[A-Za-z0-9_.-]{2,}"
    r"|\b\d{8,}\b"
    r"|\b[0-9a-fA-F]{24,}\b"
    r"|\b(?:password|passwd|token|api[_ -]?key|private[_ -]?key|oauth|credential|bearer)\b"
    r"|\b[\w.-]+\.(?:env|key|pem|p12|db|sqlite|log|py|js|ts|json|ya?ml)\b"
    r"|\b(?:sudo|docker\s+exec|curl\s+|ssh\s+|rm\s+-rf|powershell)\b"
    r")",
    re.IGNORECASE,
)


def validate_public_text(value: object, maximum: int) -> str:
    """Return normalized fictional text or reject the entire unsafe field."""
    text = unicodedata.normalize("NFC", str(value)).replace("\x00", " ")
    if any(unicodedata.category(char) == "Cc" and char not in "\t\n\r" for char in text):
        raise ValueError("public text contains control characters")
    text = " ".join(text.split())
    if not text or len(text.encode("utf-8")) > maximum:
        raise ValueError("public text is empty or too long")
    if _UNSAFE_PUBLIC_TEXT.search(text):
        raise ValueError("public text contains operational data")
    return text


def _digest(secret: str, value: str) -> str:
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(slots=True)
class VoteSecurity:
    secret: str
    limits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))

    def new_voter_cookie(self) -> str:
        voter_id = secrets.token_urlsafe(18)
        return f"{voter_id}.{_digest(self.secret, voter_id)}"

    def voter_key(self, cookie: str | None) -> str | None:
        if not cookie or "." not in cookie:
            return None
        voter_id, signature = cookie.rsplit(".", 1)
        if not hmac.compare_digest(signature, _digest(self.secret, voter_id)):
            return None
        return _digest(self.secret, f"voter:{voter_id}")

    def network_key(self, address: str) -> str:
        day = dt.datetime.now(dt.timezone.utc).date().isoformat()
        return _digest(self.secret, f"network:{day}:{address}")

    def check_rate(self, network_key: str, *, limit: int = 10, window: int = 60) -> bool:
        now = time.monotonic()
        bucket = self.limits[network_key]
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


def new_csrf() -> str:
    return secrets.token_urlsafe(24)
