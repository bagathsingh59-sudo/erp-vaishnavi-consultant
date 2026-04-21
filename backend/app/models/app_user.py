from app import db
from datetime import datetime


class AppUser(db.Model):
    __tablename__ = 'app_users'

    id = db.Column(db.Integer, primary_key=True)
    clerk_user_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False, default='user')  # 'admin' or 'user'

    # Self-referential: NULL for admins, points to admin's id for managed users
    admin_id = db.Column(db.Integer, db.ForeignKey('app_users.id'), nullable=True)

    name = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Self-referential relationship
    admin = db.relationship('AppUser', remote_side=[id], backref='managed_users')

    def __repr__(self):
        return f'<AppUser {self.clerk_user_id} role={self.role}>'
