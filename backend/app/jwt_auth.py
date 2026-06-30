"""
Self-hosted JWT authentication service (replaces Clerk).
=========================================================

Two-token model, all configurable via environment variables:

  • ACCESS token  — short-lived signed JWT (HS256). Stateless; carries the
    user's uid/role/name/email. Sent in the httpOnly `access_token` cookie.
  • REFRESH token — long-lived OPAQUE random string. Only its SHA-256 hash is
    stored (auth_refresh_tokens). Sent in the httpOnly `refresh_token` cookie
    and ROTATED on every use. Lets us revoke sessions and detect re-use.

Environment variables (all optional except JWT_SECRET in production):
  JWT_SECRET             signing secret for access tokens (REQUIRED in prod)
  JWT_ACCESS_TTL_MIN     access token lifetime, minutes      (default 30)
  JWT_REFRESH_TTL_DAYS   refresh token lifetime, days        (default 14)
  JWT_ISSUER             token `iss` claim                   (default vaishnavi-erp)
  JWT_COOKIE_SECURE      "1"/"true" → Secure cookies (HTTPS) (default: auto)
  JWT_COOKIE_SAMESITE    SameSite policy                     (default Lax)
"""
import os
import time
import hashlib
import secrets
from datetime import datetime, timedelta

import jwt as pyjwt
from flask import request


# ─── Config helpers (read fresh so .env / platform env always wins) ──────────
def _secret():
    # Fall back to Flask SECRET_KEY so the app still boots in dev, but a
    # dedicated JWT_SECRET should always be set in production.
    return os.getenv('JWT_SECRET') or os.getenv('SECRET_KEY', 'change-me-jwt-secret')


def _access_ttl():
    try:
        return int(os.getenv('JWT_ACCESS_TTL_MIN', '30'))
    except ValueError:
        return 30


def _refresh_ttl_days():
    try:
        return int(os.getenv('JWT_REFRESH_TTL_DAYS', '14'))
    except ValueError:
        return 14


def _issuer():
    return os.getenv('JWT_ISSUER', 'vaishnavi-erp')


ACCESS_COOKIE = 'access_token'
REFRESH_COOKIE = 'refresh_token'


# ─── Access tokens (stateless JWT) ───────────────────────────────────────────
def create_access_token(user):
    """Mint a signed access JWT for an AppUser."""
    now = int(time.time())
    payload = {
        'sub': user.clerk_user_id,            # canonical user uid
        'role': user.role,
        'name': user.name or '',
        'email': user.email or '',
        'type': 'access',
        'iss': _issuer(),
        'iat': now,
        'exp': now + _access_ttl() * 60,
    }
    return pyjwt.encode(payload, _secret(), algorithm='HS256')


def decode_access_token(token):
    """Return the decoded payload if valid+unexpired, else None."""
    if not token:
        return None
    try:
        payload = pyjwt.decode(
            token, _secret(), algorithms=['HS256'],
            options={'require': ['exp', 'sub']},
            issuer=_issuer(),
        )
        if payload.get('type') != 'access':
            return None
        return payload
    except pyjwt.InvalidTokenError:
        return None
    except Exception:
        return None


# ─── Refresh tokens (opaque + rotated, stored hashed) ────────────────────────
def _hash(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def issue_refresh_token(user):
    """Create and persist a new refresh token; return the RAW value (the only
    time it is ever visible)."""
    from app import db
    from app.models.auth_token import RefreshToken

    raw = secrets.token_urlsafe(48)
    rec = RefreshToken(
        user_uid=user.clerk_user_id,
        token_hash=_hash(raw),
        expires_at=datetime.utcnow() + timedelta(days=_refresh_ttl_days()),
        user_agent=(request.headers.get('User-Agent', '') or '')[:255],
        ip=(request.headers.get('X-Forwarded-For', request.remote_addr or '') or '')[:64],
    )
    db.session.add(rec)
    db.session.commit()
    return raw


def validate_refresh_token(raw, slide=True):
    """Validate a raw refresh token WITHOUT rotating it.

    Returns the user_uid on success, or None if missing/revoked/expired.

    We deliberately do NOT rotate on every access-token renewal: a single page
    load can fire several near-simultaneous requests (e.g. the page + an XHR),
    and rotating each time would make the later requests present a token that
    was just replaced — falsely tripping re-use detection and logging the user
    out. Instead the refresh token is stable for its lifetime; `slide=True`
    extends its expiry on use so active users stay signed in (a sliding
    session). Rotation happens only at login; revocation happens at
    logout / password-reset.
    """
    from app import db
    from app.models.auth_token import RefreshToken

    if not raw:
        return None

    rec = RefreshToken.query.filter_by(token_hash=_hash(raw)).first()
    if not rec or not rec.is_valid():
        return None

    if slide:
        # Extend expiry, but at most once per ~minute to avoid a write storm.
        new_exp = datetime.utcnow() + timedelta(days=_refresh_ttl_days())
        if (new_exp - rec.expires_at) > timedelta(minutes=1):
            rec.expires_at = new_exp
            db.session.commit()

    return rec.user_uid


def revoke_refresh_token(raw):
    """Revoke a single refresh token (used on logout)."""
    from app import db
    from app.models.auth_token import RefreshToken
    if not raw:
        return
    rec = RefreshToken.query.filter_by(token_hash=_hash(raw)).first()
    if rec and not rec.revoked:
        rec.revoked = True
        db.session.commit()


def revoke_all_for_user(user_uid):
    """Revoke every active refresh token for a user (force logout everywhere)."""
    from app import db
    from app.models.auth_token import RefreshToken
    if not user_uid:
        return
    RefreshToken.query.filter_by(user_uid=user_uid, revoked=False)\
        .update({'revoked': True})
    db.session.commit()


# ─── Cookie helpers ──────────────────────────────────────────────────────────
def _cookie_secure():
    env = os.getenv('JWT_COOKIE_SECURE', '')
    if env != '':
        return env.lower() in ('1', 'true', 'yes')
    # Auto: secure when the request is HTTPS (works behind Railway/Dokploy proxy
    # which set X-Forwarded-Proto).
    proto = request.headers.get('X-Forwarded-Proto', request.scheme)
    return proto == 'https'


def _samesite():
    return os.getenv('JWT_COOKIE_SAMESITE', 'Lax')


def set_auth_cookies(resp, access_token, refresh_token=None):
    """Attach the access (and optionally refresh) cookies to a response."""
    secure = _cookie_secure()
    samesite = _samesite()
    resp.set_cookie(
        ACCESS_COOKIE, access_token,
        max_age=_access_ttl() * 60,
        httponly=True, secure=secure, samesite=samesite, path='/',
    )
    if refresh_token is not None:
        resp.set_cookie(
            REFRESH_COOKIE, refresh_token,
            max_age=_refresh_ttl_days() * 86400,
            httponly=True, secure=secure, samesite=samesite, path='/',
        )
    return resp


def clear_auth_cookies(resp):
    resp.delete_cookie(ACCESS_COOKIE, path='/')
    resp.delete_cookie(REFRESH_COOKIE, path='/')
    return resp
