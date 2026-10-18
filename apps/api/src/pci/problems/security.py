import hashlib
import hmac
import secrets


def generate_edit_token() -> str:
    return secrets.token_urlsafe(32)


def digest_edit_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token: str, digest: str) -> bool:
    return hmac.compare_digest(digest_edit_token(token), digest)
