"""
Establishment Assignment Log
==============================
Audit trail of every establishment re-assignment between staff members.
"""

from app import db
from datetime import datetime


class EstablishmentAssignmentLog(db.Model):
    """One row per transfer of an establishment from one staff to another."""
    __tablename__ = 'establishment_assignment_logs'

    id = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=False)

    # Clerk user_ids
    from_user_id = db.Column(db.String(100), nullable=True)
    from_user_name = db.Column(db.String(200), nullable=True)
    to_user_id = db.Column(db.String(100), nullable=True)
    to_user_name = db.Column(db.String(200), nullable=True)

    # Who performed the transfer
    performed_by_id = db.Column(db.String(100), nullable=True)
    performed_by_name = db.Column(db.String(200), nullable=True)
    performed_by_role = db.Column(db.String(10), nullable=True)   # 'admin' or 'user'

    reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship
    establishment = db.relationship('Establishment',
                                    backref=db.backref('assignment_logs', lazy='dynamic',
                                                        order_by='EstablishmentAssignmentLog.created_at.desc()'))

    def __repr__(self):
        return f'<AssignmentLog est={self.establishment_id} from={self.from_user_id} to={self.to_user_id}>'
