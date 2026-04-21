from app import db
from datetime import datetime


class Enrollment(db.Model):
    """UAN & ESIC IP Tracker — records new employee enrollments done by staff."""
    __tablename__ = 'enrollments'

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.String(100), nullable=True, index=True)  # Multi-user isolation

    # Establishment link
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=False)

    # Employee details (as provided by establishment owner)
    employee_name = db.Column(db.String(200), nullable=False)
    father_husband_name = db.Column(db.String(200), nullable=False)
    gender = db.Column(db.String(10), nullable=False)       # Male, Female, Other
    date_of_birth = db.Column(db.Date, nullable=False)
    date_of_joining = db.Column(db.Date, nullable=False)

    # Enrollment output — filled after portal process
    uan_number = db.Column(db.String(20), nullable=True)
    esic_ip_number = db.Column(db.String(20), nullable=True)

    # Optional helpful fields
    aadhaar_number = db.Column(db.String(12), nullable=True)
    mobile_number = db.Column(db.String(15), nullable=True)
    designation = db.Column(db.String(100), nullable=True)

    # Link tracking
    is_linked = db.Column(db.Boolean, default=False)         # Pushed to main employee list?
    linked_employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)

    # Metadata
    remarks = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    establishment = db.relationship('Establishment', backref='enrollments')
    linked_employee = db.relationship('Employee', foreign_keys=[linked_employee_id])

    @property
    def enrollment_status(self):
        """Quick status: Completed / Partial / Pending"""
        if self.uan_number and self.esic_ip_number:
            return 'completed'
        elif self.uan_number or self.esic_ip_number:
            return 'partial'
        return 'pending'

    @property
    def status_label(self):
        s = self.enrollment_status
        if s == 'completed':
            return 'Completed'
        elif s == 'partial':
            return 'Partial (UAN only)' if self.uan_number else 'Partial (ESIC only)'
        return 'Pending'
