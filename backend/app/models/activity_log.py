from app import db
from datetime import datetime


class ActivityLog(db.Model):
    """Audit trail — logs all key actions across the system"""
    __tablename__ = 'activity_logs'

    id = db.Column(db.Integer, primary_key=True)

    # Who performed the action
    user_id = db.Column(db.String(100), nullable=True, index=True)
    user_name = db.Column(db.String(100), nullable=True)  # Cached display name

    # What action was performed
    action = db.Column(db.String(30), nullable=False)  # created, updated, deleted, finalized, etc.
    entity_type = db.Column(db.String(50), nullable=False)  # establishment, employee, payroll, voucher, etc.
    entity_id = db.Column(db.Integer, nullable=True)
    entity_name = db.Column(db.String(200), nullable=True)  # Human-readable name/title

    # Optional details (what changed)
    details = db.Column(db.Text, nullable=True)  # e.g., "Gross changed from 15000 to 18000"

    # Linked establishment (for scoping)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=True)

    # Timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Relationships
    establishment = db.relationship('Establishment', backref=db.backref('activity_logs', lazy=True))

    def __repr__(self):
        return f'<ActivityLog {self.action} {self.entity_type} #{self.entity_id}>'
