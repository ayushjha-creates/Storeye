"""Authentication primitives: Argon2id password hashing and RBAC roles.

This module is the single source of truth for credential hashing and for the
canonical Storeye roles. It has no database dependency so it can be unit-tested
(`no_db`) and imported from seed scripts without an engine.

Hashing uses Argon2id (the current recommended default). Raw passwords are never
logged and never persisted; only the Argon2id encoded hash is stored.
"""

from __future__ import annotations

import re

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

# Canonical Storeye roles. Keep the set minimal and defensible.
ROLE_OWNER = "OWNER"
ROLE_MANAGER = "MANAGER"
ROLE_STAFF = "STAFF"

CANONICAL_ROLES = (ROLE_OWNER, ROLE_MANAGER, ROLE_STAFF)

# Role levels: higher number = more privilege. STAFF is the floor for every
# authenticated business operation.
_ROLE_LEVELS = {
    ROLE_OWNER: 3,
    ROLE_MANAGER: 2,
    ROLE_STAFF: 1,
}

# Legacy role strings that appear in seeded/historical data map onto the
# canonical roles. They are accepted for authorization but new writes should use
# a canonical role.
_LEGACY_ROLE_ALIASES = {
    "REGIONAL_ADMIN": ROLE_OWNER,
    "STORE_MANAGER": ROLE_MANAGER,
    "Store Manager": ROLE_MANAGER,
    "ASSOCIATE": ROLE_STAFF,
    "store manager": ROLE_MANAGER,
    "manager": ROLE_MANAGER,
    "staff": ROLE_STAFF,
    "associate": ROLE_STAFF,
    "owner": ROLE_OWNER,
}

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 8
_REDACTED = "***"


def hash_password(password: str) -> str:
    """Hash a password with Argon2id. Returns the encoded hash (never the raw value)."""
    password = _validate_password_input(password)
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time Argon2id verification. Returns False on any mismatch/error."""
    password = _validate_password_input(password)
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_is_valid(password: str) -> bool:
    """Practical password policy: non-empty, at least MIN_PASSWORD_LENGTH chars."""
    if not isinstance(password, str):
        return False
    password = password.strip()
    if len(password) < MIN_PASSWORD_LENGTH:
        return False
    # Reject whitespace-only / control-char-filled passwords.
    if re.fullmatch(r"\s*", password):
        return False
    return True


def redact(value: str | None) -> str:
    """Redact a secret for logging/tests (never log real passwords)."""
    if not value:
        return ""
    return _REDACTED


def role_level(role: str | None) -> int:
    """Return the privilege level for a role (canonical + legacy aliases)."""
    if role is None:
        return 0
    level = _ROLE_LEVELS.get(role)
    if level is not None:
        return level
    canonical = _LEGACY_ROLE_ALIASES.get(role)
    return _ROLE_LEVELS.get(canonical or "", 0)


def role_at_least(role: str | None, minimum: str) -> bool:
    """True when `role` has at least `minimum` privilege."""
    return role_level(role) >= role_level(minimum)


def canonical_role(role: str | None) -> str:
    """Map a stored role string onto a canonical role (falls back to STAFF)."""
    if role in CANONICAL_ROLES:
        return role
    canonical = _LEGACY_ROLE_ALIASES.get(role or "")
    return canonical or ROLE_STAFF


def _validate_password_input(password: str) -> str:
    if password is None:
        raise ValueError("Password must be a string")
    if not isinstance(password, str):
        raise ValueError("Password must be a string")
    return password