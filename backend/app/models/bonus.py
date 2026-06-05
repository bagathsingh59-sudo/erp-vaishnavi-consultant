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
    wage_ceiling = db.Column(db.Float, nullable=False, default=7000.0)     # Sec 12 (legacy / Statement Excel)
    min_wage_floor = db.Column(db.Float, nullable=True)                    # From establishment or manual
    eligibility_cap = db.Column(db.Float, nullable=False, default=21000.0) # Sec 2(13) (legacy)
    min_days_worked = db.Column(db.Integer, nullable=False, default=30)    # Sec 8

    # ──────────────────────────────────────────────────────────────────────
    # Vaishnavi engine settings — three sections of toggles the user picks
    # before generating the bonus sheet. All ignored by the legacy
    # Basic+DA Statement Excel exporter.
    # ──────────────────────────────────────────────────────────────────────

    # ── SECTION 1: Attendance composition ─────────────────────────────────
    # include_holiday_attendance: ON → paid_holidays added to attendance
    # att_include_ot_days       : ON → ot_hours/8 added to attendance
    # att_skip_zero             : ON → employees whose total FY attendance
    #                                  is 0 are skipped from the run entirely
    # If both include_holiday_attendance and att_include_ot_days are OFF
    # the engine uses "pure worked attendance only" (days_present).
    include_holiday_attendance = db.Column(db.Boolean, nullable=False, default=True)
    att_include_ot_days        = db.Column(db.Boolean, nullable=False, default=False)
    att_skip_zero              = db.Column(db.Boolean, nullable=False, default=True)

    # ── SECTION 2: Wage composition ───────────────────────────────────────
    # wage_use_full_gross       : ON → monthly_wage = entry.total_earnings
    #                                  (includes all earning heads + OT +
    #                                  arrears). Overrides every other
    #                                  wage_* flag below.
    # wage_add_nph_wages        : ON → paid_holidays × daily_rate is added
    #                                  to the base (only takes effect when
    #                                  include_holiday_attendance is OFF —
    #                                  otherwise NPH wage is already in the
    #                                  attendance × daily_rate base)
    # include_overtime_in_wage  : ON → ot_amount is added to the base
    # wage_add_other_allowance  : ON → max(0, earned_gross − base) added,
    #                                  i.e. anything earned beyond plain
    #                                  attendance × daily_rate
    wage_use_full_gross        = db.Column(db.Boolean, nullable=False, default=False)
    wage_add_nph_wages         = db.Column(db.Boolean, nullable=False, default=False)
    include_overtime_in_wage   = db.Column(db.Boolean, nullable=False, default=False)
    wage_add_other_allowance   = db.Column(db.Boolean, nullable=False, default=False)

    # ── SECTION 3: Ceiling and Cap (NULL = not applicable, default) ───────
    # wage_ceiling_per_month   : per-month maximum on the wage. If a month's
    #                            computed wage exceeds this, it's clamped
    #                            DOWN to the ceiling before bonus % is
    #                            applied. e.g. 7000 reproduces the Sec. 12
    #                            statutory cap.
    # bonus_cap_per_employee   : annual maximum on the total bonus per
    #                            employee. e.g. 20% × 12 × 7000 = 16,800
    #                            reproduces Sec. 11. NULL = no cap.
    wage_ceiling_per_month     = db.Column(db.Float, nullable=True)
    bonus_cap_per_employee     = db.Column(db.Float, nullable=True)

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
