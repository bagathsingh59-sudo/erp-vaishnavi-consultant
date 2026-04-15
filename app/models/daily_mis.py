"""
Daily MIS (Management Information System) Model
=================================================
Tracks all daily tasks performed by staff across 8 categories and 42 task types.
Payment-related tasks auto-link to the Accounts module via voucher_id.

Admin Features:
- Task assignment (admin assigns tasks to staff)
- Admin remarks (notes visible to staff)
- Priority marking (normal, urgent, critical)
- Due date tracking with overdue detection
"""

from app import db
from datetime import datetime, date


# ── 8 CATEGORIES with 42 TASK TYPES ──
MIS_TASK_CATEGORIES = {
    'Payment & Accounts': [
        'Compliance Amount Received',
        'Fee Received',
        'Challan Payment Done',
        'Refund / Reversal',
    ],
    'Return Filing': [
        'EPF Return Filed',
        'ESIC Return Filed',
        'PT Return Filed',
        'LWF Return Filed',
        'Annual Return Filed',
        'GST Return Filed',
        'TDS Return Filed',
        'Other Return Filed',
    ],
    'Employee / Portal Work': [
        'Employee Enrolment',
        'Employee Exit Processed',
        'KYC Update',
        'UAN Activation',
        'IP Generated',
        'Transfer / Scheme Certificate',
        'Claim Settlement',
        'DSC Work',
    ],
    'Records & Data Management': [
        'Data Collection',
        'Data Entry / Processing',
        'Records Maintenance',
        'Document Dispatch',
        'Document Received',
    ],
    'Registration & License': [
        'New PF Registration',
        'New ESIC Registration',
        'Shop Act / License Renewal',
        'New Establishment Registration',
        'Amendment / Modification',
    ],
    'Inspection & Legal': [
        'Notice Received',
        'Notice Reply Submitted',
        'Inspection Attended',
        'Assessment / Hearing',
    ],
    'Communication & Support': [
        'Customer Query Resolved',
        'Visitor Attended',
        'Follow-up Done',
        'Internal Discussion',
    ],
    'Other': [
        'Portal Issue Resolution',
        'Reconciliation',
        'Report Prepared',
        'Other',
    ],
}

# Flat list for validation
ALL_TASK_TYPES = []
for _tasks in MIS_TASK_CATEGORIES.values():
    ALL_TASK_TYPES.extend(_tasks)

# Tasks that trigger auto-voucher creation in Accounts
PAYMENT_TASK_TYPES = [
    'Compliance Amount Received',
    'Fee Received',
    'Challan Payment Done',
    'Refund / Reversal',
]


class DailyMISEntry(db.Model):
    """Daily MIS task entry logged by staff or assigned by admin"""
    __tablename__ = 'daily_mis_entries'

    id = db.Column(db.Integer, primary_key=True)

    # Who logged this (creator)
    owner_id = db.Column(db.String(100), nullable=True, index=True)
    staff_name = db.Column(db.String(200), nullable=True)

    # ── Admin Assignment Fields ──
    # If admin creates/assigns a task TO a staff member
    assigned_to_id = db.Column(db.String(100), nullable=True, index=True)
    assigned_to_name = db.Column(db.String(200), nullable=True)
    assigned_by_name = db.Column(db.String(200), nullable=True)
    is_assigned = db.Column(db.Boolean, default=False)  # True if admin-assigned task

    # ── Admin Remarks ──
    admin_remarks = db.Column(db.Text, nullable=True)
    admin_remarks_by = db.Column(db.String(200), nullable=True)
    admin_remarks_at = db.Column(db.DateTime, nullable=True)

    # ── Priority & Due Date ──
    priority = db.Column(db.String(10), nullable=False, default='normal')
    # priority options: normal, urgent, critical
    due_date = db.Column(db.Date, nullable=True)

    # What was done
    task_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    category = db.Column(db.String(50), nullable=False)
    task_type = db.Column(db.String(100), nullable=False)

    # For which establishment (optional — internal tasks may not have one)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=True)

    # Task details
    description = db.Column(db.Text, nullable=True)
    amount = db.Column(db.Float, nullable=True)
    reference = db.Column(db.String(100), nullable=True)  # UTR / TRRN / Challan No.
    status = db.Column(db.String(20), nullable=False, default='completed')
    # status options: completed, pending, in_progress

    # Auto-linked voucher (if payment task)
    voucher_id = db.Column(db.Integer, db.ForeignKey('vouchers.id'), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    establishment = db.relationship('Establishment',
                                    backref=db.backref('mis_entries', lazy='dynamic'))
    voucher = db.relationship('Voucher',
                              backref=db.backref('mis_entry', uselist=False, lazy=True))

    def __repr__(self):
        return f'<DailyMISEntry {self.task_type} {self.task_date}>'

    @property
    def establishment_name(self):
        if self.establishment:
            return self.establishment.display_name
        return '—'

    @property
    def is_overdue(self):
        """Check if task is overdue (has due_date, not completed, past due)"""
        if self.due_date and self.status != 'completed' and self.due_date < date.today():
            return True
        return False

    @property
    def days_overdue(self):
        """How many days overdue (0 if not overdue)"""
        if self.is_overdue:
            return (date.today() - self.due_date).days
        return 0

    @property
    def status_badge(self):
        if self.is_overdue:
            days = self.days_overdue
            return f'<span class="badge bg-danger" style="font-size:0.68rem;">OVERDUE ({days}d)</span>'
        badges = {
            'completed': ('success', 'Completed'),
            'pending': ('danger', 'Pending'),
            'in_progress': ('warning', 'In Progress'),
        }
        cls, label = badges.get(self.status, ('secondary', self.status))
        return f'<span class="badge bg-{cls}" style="font-size:0.68rem;">{label}</span>'

    @property
    def priority_badge(self):
        if self.priority == 'critical':
            return '<span class="badge bg-danger" style="font-size:0.62rem;">CRITICAL</span>'
        elif self.priority == 'urgent':
            return '<span class="badge bg-warning text-dark" style="font-size:0.62rem;">URGENT</span>'
        return ''
