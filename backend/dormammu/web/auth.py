from __future__ import annotations

import hashlib
import ipaddress
import secrets
from typing import Mapping


PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 390_000


def host_requires_token(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized in {"0.0.0.0", "::", ""}:
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return normalized not in {"localhost"}
    return not ip.is_loopback


def validate_server_auth_config(
    *,
    host: str,
    token: str | None,
    password_hash: str | None = None,
    allow_initial_setup: bool = True,
) -> None:
    has_token = bool((token or "").strip())
    has_password = bool((password_hash or "").strip())
    if host_requires_token(host) and not has_token and not has_password and not allow_initial_setup:
        raise ValueError(
            "Refusing to bind the web terminal to an external address without "
            "authentication. Set a web password or pass --token."
        )


def request_token(headers: Mapping[str, str], query_token: str | None = None) -> str | None:
    auth = headers.get("authorization") or headers.get("Authorization")
    if auth:
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    explicit = headers.get("x-dormammu-token") or headers.get("X-Dormammu-Token")
    if explicit:
        return explicit.strip()
    return query_token.strip() if query_token else None


def token_matches(*, expected: str | None, supplied: str | None) -> bool:
    if not expected:
        return True
    return supplied == expected


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return f"{PASSWORD_HASH_ALGORITHM}${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


def password_matches(*, password_hash: str | None, supplied: str | None) -> bool:
    if not password_hash or supplied is None:
        return False
    try:
        algorithm, iterations_raw, salt, expected = password_hash.split("$", 3)
        iterations = int(iterations_raw)
    except ValueError:
        return False
    if algorithm != PASSWORD_HASH_ALGORITHM or iterations <= 0:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        supplied.encode("utf-8"),
        salt.encode("ascii"),
        iterations,
    ).hex()
    return secrets.compare_digest(digest, expected)


def credential_matches(
    *,
    token: str | None,
    password_hash: str | None,
    supplied: str | None,
) -> bool:
    if token and supplied == token:
        return True
    return password_matches(password_hash=password_hash, supplied=supplied)
