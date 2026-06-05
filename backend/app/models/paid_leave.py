"""
Paid Leave Module — Annual Earned Leave Statement
Karnataka Factories Act 1948, Sec. 79 (Leave with Wages)

A Paid Leave Run is annual, calendar year basis (January → December).
Each run computes per-employee earned leave + leave-encashment amount.
Statute: every adult worker who has worked for 240 days+ in a calendar
year is entitled to leave with wages on the basis of one day per
twenty days of work performed in the previous year.

Both thresholds are user-configurable per run so the same engine can
serve different establishment types (Factory / Shops & Commercial /
Beedi / etc.) without hard-coding statutory rules.
"""
from app import db
from datetime import datetime


class PaidLeaveRun(db.Model):
    """One paid-leave calculation batch for an establishment for one
    calendar year."""
    __tablename__ = 'paid_leave_runs'

    id = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer,
                                  db.ForeignKey('establishments.id'),
                                  nullable=False)

    # Calendar year: 2025 means Jan 2025 → Dec 2025
    year = db.Column(db.Integer, nullable=False)

    # ── Section 1: Attendance composition ────────────────────────────
    include_holiday_attendance = db.Column(db.Boolean, nullable=False, default=True)
    skip_zero_attendance       = db.Column(db.Boolean, nullable=False, default=True)

    # ── Section 2: Eligibility rule ───────────────────────────────────
    eligibility_threshold = db.Column(db.Integer, nullable=False, default=240)
    eligibility_divisor   = db.Column(db.Integer, nullable=False, default=20)

    # ── Section 3: Statement layout ───────────────────────────────────
    # 'mixed'           = single sheet, employees mixed
    # 'separate_sheets' = two sheets in the workbook: Eligible / Not Eligible
    # 'top_bottom'      = single sheet, Eligible block on top, Not Eligible below
    layout_mode = db.Column(db.String(20), nullable=False, default='top_bottom')

    # Status
    status = db.Column(db.String(15), nullable=False, default='draft')

    # Summary (computed at run-time, kept for fast UI display)
    total_employees    = db.Column(db.Integer, default=0)
    eligible_employees = db.Column(db.Integer, default=0)
    total_pl_amount    = db.Column(db.Float, default=0)

    # Dates
    payment_date = db.Column(db.Date, nullable=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    finalized_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    establishment = db.relationship('Establishment', backref='paid_leave_runs')
    entries = db.relationship('PaidLeaveEntry', backref='paid_leave_run',
                              cascade='all, delete-orphan', lazy='dynamic')

    @property
    def year_label(self):
        return f"Year {self.year}"


class PaidLeaveEntry(db.Model):
    """Per-employee paid-leave calculation for one run."""
    __tablename__ = 'paid_leave_entries'

    id = db.Column(db.Integer, primary_key=True)
    paid_leave_run_id = db.Column(db.Integer,
                                    db.ForeignKey('paid_leave_runs.id'),
                                    nullable=False)
    employee_id = db.Column(db.Integer,
                             db.ForeignKey('employees.id'),
                             nullable=False)

    # Month-wise attendance as JSON: {"2025-01": 22, "2025-02": 20, ...}
    monthly_data = db.Column(db.Text, nullable=True)

    # Aggregates (engine-computed)
    base_attendance     = db.Column(db.Float, default=0)   # Σ months as derived from payroll
    manual_addition     = db.Column(db.Float, default=0)   # Days the consultant manually
                                                            # adds to push the employee
                                                            # over the threshold
    total_attendance    = db.Column(db.Float, default=0)   # base + manual
    eligible_attendance = db.Column(db.Float, default=0)   # total / divisor

    # December rate snapshot (daily-rate equivalent at run time)
    december_rate = db.Column(db.Float, default=0)

    # Earned leave wage (eligible_attendance × december_rate)
    pl_amount = db.Column(db.Float, default=0)

    # Eligibility
    is_eligible          = db.Column(db.Boolean, default=False)
    ineligibility_reason = db.Column(db.String(200), nullable=True)

    # User-editable
    remarks = db.Column(db.String(200), nullable=True)

    employee = db.relationship('Employee')

    def __repr__(self):
        return (f'<PaidLeaveEntry run={self.paid_leave_run_id} '
                f'emp={self.employee_id} pl=₹{self.pl_amount}>')
