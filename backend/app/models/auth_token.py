"""
Refresh-token store for the self-hosted JWT auth.

Access tokens are short-lived signed JWTs (stateless). Refresh tokens are
long-lived OPAQUE random strings — we store only their SHA-256 hash here so a
DB leak never exposes a usable token. Each refresh rotates: the old row is
revoked and a new one issued, which lets us detect re-use of a stolen token
and lets an admin revoke a user's sessions by deleting their rows.
"""
from app import db
from datetime import datetime


class RefreshToken(db.Model):
    __tablename__ = 'auth_refresh_tokens'

    id = db.Column(db.Integer, primary_key=True)

    # The user uid (== AppUser.clerk_user_id value).
    user_uid = db.Column(db.String(100), nullable=False, index=True)

    # SHA-256 hex of the raw refresh token (never store the raw value).
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)

    issued_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked = db.Column(db.Boolean, default=False, nullable=False)

    # When rotated, points at the token_hash that replaced this one (audit).
    replaced_by = db.Column(db.String(64), nullable=True)

    user_agent = db.Column(db.String(255), nullable=True)
    ip = db.Column(db.String(64), nullable=True)

    def is_valid(self):
        return (not self.revoked) and self.expires_at > datetime.utcnow()

    def __repr__(self):
        return f'<RefreshToken uid={self.user_uid} revoked={self.revoked}>'
