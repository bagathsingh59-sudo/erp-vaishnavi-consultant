"""
Bonus Module — Payment of Bonus Act, 1965

Stores Bonus Runs (one per establishment per financial year) and per-employee
bonus entries with month-wise detail.
"""
from app import db
from datetime import datetime


class BonusRun(db.Model):
    """One bonus calculation batch for an establishment for one financial year."""
    __tablename__ = 'bonus_runs'

    id = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=False)

    # Financial Year: start_year=2024 means FY 2024-25 (Apr 2024 to Mar 2025)
    start_year = db.Column(db.Integer, nullable=False)
    end_year = db.Column(db.Integer, nullable=False)

    # Bonus configuration (editable per run, stored as snapshot)
    bonus_percentage = db.Column(db.Float, nullable=False, default=8.33)   # 8.33 to 20
    wage_ceiling = db.Column(db.Float, nullable=False, default=7000.0)     # Sec 12
    min_wage_floor = db.Column(db.Float, nullable=True)                    # From establishment or manual
    eligibility_cap = db.Column(db.Float, nullable=False, default=21000.0) # Sec 2(13)
    min_days_worked = db.Column(db.Integer, nullable=False, default=30)    # Sec 8

    # Status: draft | finalized
    status = db.Column(db.String(15), nullable=False, default='draft')

    # Summary (computed, stored for quick display)
    total_employees = db.Column(db.Integer, default=0)
    eligible_employees = db.Column(db.Integer, default=0)
    total_bonus_ceiling = db.Column(db.Float, default=0)   # Using ₹7,000 ceiling
    total_bonus_actual = db.Column(db.Float, default=0)    # Using actual Basic+DA (no ceiling)

    # Dates
    payment_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    finalized_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    establishment = db.relationship('Establishment', backref='bonus_runs')
    entries = db.relationship('BonusEntry', backref='bonus_run',
                              cascade='all, delete-orphan', lazy='dynamic')

    @property
    def fy_label(self):
        return f"FY {self.start_year}-{str(self.end_year)[-2:]}"

    @property
    def effective_ceiling(self):
        """Actual ceiling used: max(wage_ceiling, min_wage_floor)"""
        if self.min_wage_floor and self.min_wage_floor > self.wage_ceiling:
            return self.min_wage_floor
        return self.wage_ceiling


class BonusEntry(db.Model):
    """Per-employee bonus calculation for one run."""
    __tablename__ = 'bonus_entries'

    id = db.Column(db.Integer, primary_key=True)
    bonus_run_id = db.Column(db.Integer, db.ForeignKey('bonus_runs.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)

    # Month-wise detail as JSON string, keyed by month key "YYYY-MM"
    # Each entry: {basic_da: float, capped: float, days: float, eligible: bool}
    monthly_data = db.Column(db.Text, nullable=True)

    # Aggregates
    months_eligible = db.Column(db.Integer, default=0)
    total_days_worked = db.Column(db.Float, default=0)
    total_basic_da = db.Column(db.Float, default=0)      # Sum of actual Basic+DA across eligible months
    total_capped_wage = db.Column(db.Float, default=0)   # Sum of min(actual, ceiling) across eligible months

    # Calculated bonuses (both shown for transparency)
    bonus_at_ceiling = db.Column(db.Float, default=0)    # total_capped_wage * pct
    bonus_at_actual = db.Column(db.Float, default=0)     # total_basic_da * pct

    # Manual overrides (set by user in preview screen)
    override_amount = db.Column(db.Float, nullable=True)  # Final amount if overridden
    remarks = db.Column(db.String(200), nullable=True)

    # Eligibility
    is_eligible = db.Column(db.Boolean, default=True)
    ineligibility_reason = db.Column(db.String(200), nullable=True)

    # Relationships
    employee = db.relationship('Employee')

    @property
    def final_bonus_ceiling(self):
        """Final bonus amount at ceiling (override if set)."""
        if self.override_amount is not None:
            return self.override_amount
        return self.bonus_at_ceiling

    @property
    def final_bonus_actual(self):
        """Final bonus amount at actual (override if set, same override applies)."""
        if self.override_amount is not None:
            return self.override_amount
        return self.bonus_at_actual
