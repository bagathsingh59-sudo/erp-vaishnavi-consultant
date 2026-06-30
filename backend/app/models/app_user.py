from app import db
from datetime import datetime
import bcrypt


class AppUser(db.Model):
    __tablename__ = 'app_users'

    id = db.Column(db.Integer, primary_key=True)

    # Stable per-user identifier. Historically this held the Clerk user id
    # (e.g. "user_2abc…"); after the migration to self-hosted JWT auth it
    # simply holds the canonical user uid. We KEEP the column name so the
    # value — which is also stored in Establishment.owner_id / assigned_to_id,
    # Voucher.owner_id, ActivityLog.user_id, etc. — continues to link every
    # owned record to its user with ZERO data rewrite. New users get a freshly
    # generated "usr_…" uid here.
    clerk_user_id = db.Column(db.String(100), unique=True, nullable=False, index=True)

    role = db.Column(db.String(10), nullable=False, default='user')  # 'admin' or 'user'

    # Self-referential: NULL for admins, points to admin's id for managed users
    admin_id = db.Column(db.Integer, db.ForeignKey('app_users.id'), nullable=True)

    name = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(200), nullable=True, index=True)  # also the login id

    # ── Self-hosted credentials (replaces Clerk) ──────────────────────────────
    password_hash = db.Column(db.String(255), nullable=True)        # bcrypt
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    # Plaintext of the auto-generated TEMPORARY password, shown to the admin in
    # Admin → Users so they can hand it out. Cleared the moment the user sets
    # their own password. NULL means "no pending temp password".
    temp_password = db.Column(db.String(100), nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Self-referential relationship
    admin = db.relationship('AppUser', remote_side=[id], backref='managed_users')

    # ── Password helpers (bcrypt) ─────────────────────────────────────────────
    def set_password(self, raw_password):
        """Hash and store a new password. Clears the forced-reset flag is the
        caller's responsibility (we leave must_change_password untouched here)."""
        if not raw_password:
            raise ValueError('Password cannot be empty')
        self.password_hash = bcrypt.hashpw(
            raw_password.encode('utf-8'), bcrypt.gensalt()
        ).decode('utf-8')

    def check_password(self, raw_password):
        """Verify a plaintext password against the stored bcrypt hash."""
        if not self.password_hash or not raw_password:
            return False
        try:
            return bcrypt.checkpw(
                raw_password.encode('utf-8'),
                self.password_hash.encode('utf-8'),
            )
        except (ValueError, TypeError):
            return False

    @property
    def uid(self):
        """The canonical user identifier (alias for the legacy column name)."""
        return self.clerk_user_id

    def __repr__(self):
        return f'<AppUser {self.clerk_user_id} role={self.role}>'
