from app import db
from datetime import datetime, date


class PayrollConfig(db.Model):
    """Per-establishment payroll configuration — defines how salary is calculated"""
    __tablename__ = 'payroll_configs'

    id = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=False, unique=True)

    # --- Salary Type ---
    # 'monthly_fixed'  = Fixed monthly salary (most common)
    # 'daily_wages'    = Daily wage × days worked
    # 'monthly_package'= CTC-based package split into heads
    salary_type = db.Column(db.String(20), nullable=False, default='monthly_fixed')

    # --- Salary Structure ---
    # 'with_heads'  = Basic + DA + HRA + ... (multiple components)
    # 'gross_only'  = Single gross amount, no breakup
    salary_structure = db.Column(db.String(15), nullable=False, default='with_heads')

    # --- Working Days Basis ---
    # 'calendar'   = Use actual calendar days of the month (28/30/31)
    # 'fixed_26'   = Always 26 working days
    # 'fixed_30'   = Always 30 days
    # 'custom'     = Custom number of working days
    working_days_basis = db.Column(db.String(15), nullable=False, default='calendar')
    custom_working_days = db.Column(db.Integer, nullable=True)  # Only if working_days_basis = 'custom'

    # --- Compliance Calculation Basis ---
    # 'basic_da'  = EPF/ESIC calculated on Basic + DA only (most common)
    # 'gross'     = EPF/ESIC calculated on Gross salary
    compliance_basis = db.Column(db.String(10), nullable=False, default='basic_da')

    # Include OT amount in EPF/ESIC wage calculation?
    # True  = compliance_wages includes OT (earned_gross + OT)
    # False = compliance_wages excludes OT (earned_gross only) — default
    include_ot_in_compliance = db.Column(db.Boolean, default=False)  # Legacy — kept for backward compat

    # Separate OT toggles for EPF and ESIC (replaces single include_ot_in_compliance)
    include_ot_in_epf = db.Column(db.Boolean, default=False)
    include_ot_in_esic = db.Column(db.Boolean, default=False)

    # --- Absence / Deduction Rules ---
    # True  = Deduct salary for absent days
    # False = No deduction (pay full salary regardless)
    absence_deduction = db.Column(db.Boolean, default=True)

    # --- Overtime (OT) Settings ---
    ot_applicable = db.Column(db.Boolean, default=False)
    # 'single'  = 1× normal rate
    # 'double'  = 2× normal rate
    ot_rate_type = db.Column(db.String(10), nullable=True, default='double')
    # 'hours' = OT entered in hours
    # 'days'  = OT entered in days
    ot_unit = db.Column(db.String(10), nullable=True, default='hours')
    # 'gross'      = Use full gross salary as OT base (default — all components)
    # 'basic_only' = Use Basic wage only as OT base (excludes HRA and other allowances)
    ot_base_wage = db.Column(db.String(15), nullable=True, default='gross')

    # --- Rest Day / Weekly Off Settings ---
    # 'sunday'    = Fixed Sunday rest (default)
    # 'rotation'  = Rotation rest after 6 working days
    # 'fixed_day' = Fixed on a specific weekday (use rest_day_weekday)
    rest_day_type = db.Column(db.String(15), nullable=False, default='sunday')
    # 0=Monday, 1=Tuesday ... 6=Sunday (only used if rest_day_type='fixed_day')
    rest_day_weekday = db.Column(db.Integer, nullable=True, default=6)

    # --- Weekly Off (WO) Policy (applies to ALL salary types) ---
    # Is WO applicable?
    wo_applicable = db.Column(db.Boolean, default=True)
    # 'paid'   = WO day is paid (included in salary)
    # 'unpaid' = WO day is not paid (deducted / not counted)
    wo_type = db.Column(db.String(10), nullable=False, default='paid')
    # 'sunday' / 'monday' ... 'saturday' / 'rotational'
    wo_day = db.Column(db.String(12), nullable=False, default='sunday')
    # Sandwich rule: if absent on both sides of WO, treat WO as absent too
    wo_sandwich_rule = db.Column(db.Boolean, default=False)
    # Absence deduction divisor for monthly/CTC employees: '30' / '26' / 'calendar'
    absence_divisor = db.Column(db.String(10), nullable=False, default='30')
    # OT multiplier when employee works on WO day: 1.0 / 1.5 / 2.0
    wo_ot_rate = db.Column(db.Float, default=2.0)

    # DEPRECATED — kept for backward compatibility during migration
    weekly_off_policy = db.Column(db.String(10), nullable=True, default='paid')

    # --- Paid Holiday Settings ---
    # 'included'   = Paid holidays included in working days (no separate line)
    # 'separate'   = Show paid holidays as separate line item
    # 'not_applicable' = No paid holiday concept
    paid_holiday_type = db.Column(db.String(20), nullable=False, default='included')

    # --- Statutory Applicability ---
    epf_applicable = db.Column(db.Boolean, default=True)
    esic_applicable = db.Column(db.Boolean, default=False)
    pt_applicable = db.Column(db.Boolean, default=False)     # Professional Tax
    pt_state = db.Column(db.String(30), default='karnataka')   # State for PT slab
    bonus_applicable = db.Column(db.Boolean, default=False)    # Statutory Bonus
    gratuity_applicable = db.Column(db.Boolean, default=False) # Gratuity
    paid_leave_applicable = db.Column(db.Boolean, default=False)  # Paid Leave / Earned Leave
    tds_applicable = db.Column(db.Boolean, default=False)      # TDS on salary
    advance_applicable = db.Column(db.Boolean, default=False)  # Salary Advance
    lwf_applicable = db.Column(db.Boolean, default=False)      # Labour Welfare Fund

    # --- EPF Configuration ---
    # 'ceiling'  = EPF deducted on wages capped at epf_wage_ceiling (default, most common)
    # 'higher'   = EPF deducted on actual full wages (no ceiling — employer opts for higher contribution)
    epf_contribution_type = db.Column(db.String(10), nullable=False, default='ceiling')
    # EPF Employee contribution rate (default 12% — goes to A/c 01)
    epf_employee_rate = db.Column(db.Float, default=12.0)
    # EPF Employer breakdown:
    epf_ac01_rate = db.Column(db.Float, default=3.67)      # EPF A/c 01
    epf_eps_rate = db.Column(db.Float, default=8.33)        # EPS A/c 10
    epf_admin_rate = db.Column(db.Float, default=0.50)      # Admin Charge (min ₹500)
    epf_edli_rate = db.Column(db.Float, default=0.50)       # EDLI Contribution
    epf_admin_min = db.Column(db.Float, default=500.0)      # Minimum Admin Charge
    # EPF wage ceiling (default 15000 — statutory limit)
    epf_wage_ceiling = db.Column(db.Float, default=15000.0)
    # Include employer share in CTC? (some clients do)
    epf_employer_in_ctc = db.Column(db.Boolean, default=False)

    # --- ESIC Configuration ---
    # 'ceiling'  = ESIC deducted only if gross <= esic_wage_ceiling (default, most common)
    # 'higher'   = ESIC deducted on full wages regardless of ceiling (employer opts for higher coverage)
    esic_contribution_type = db.Column(db.String(10), nullable=False, default='ceiling')
    # ESIC employer rate (default 3.25%)
    esic_employer_rate = db.Column(db.Float, default=3.25)
    # ESIC employee rate (default 0.75%)
    esic_employee_rate = db.Column(db.Float, default=0.75)
    # ESIC wage ceiling (default 21000)
    esic_wage_ceiling = db.Column(db.Float, default=21000.0)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    establishment = db.relationship('Establishment', backref=db.backref('payroll_config', uselist=False))

    def __repr__(self):
        return f'<PayrollConfig est={self.establishment_id} type={self.salary_type}>'


class SalaryHead(db.Model):
    """Configurable salary components per establishment (Basic, DA, HRA, etc.)"""
    __tablename__ = 'salary_heads'

    id = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=False)

    name = db.Column(db.String(100), nullable=False)           # e.g., Basic, DA, HRA, Conveyance, Wash Allowance
    short_code = db.Column(db.String(20), nullable=False)      # e.g., BASIC, DA, HRA

    # 'earning'    = Added to salary (Basic, DA, HRA, etc.)
    # 'deduction'  = Subtracted (Advance, Loan recovery, etc.)
    head_type = db.Column(db.String(15), nullable=False, default='earning')

    # How the amount is determined:
    # 'fixed'      = Fixed amount per employee
    # 'percent'    = Percentage of another head (usually Basic)
    calc_type = db.Column(db.String(10), nullable=False, default='fixed')

    # If calc_type = 'percent', this stores the percentage value
    percent_value = db.Column(db.Float, nullable=True)

    # If calc_type = 'percent', which head is it based on? (usually Basic's id)
    percent_of_head_id = db.Column(db.Integer, db.ForeignKey('salary_heads.id'), nullable=True)

    # Is this head included in compliance calculation (EPF/ESIC)?
    is_for_compliance = db.Column(db.Boolean, default=False)   # True for Basic, DA

    # Exclude from ESIC wages? (e.g., Wash Allowance)
    exclude_from_esic = db.Column(db.Boolean, default=False)

    # Is this head included in gross calculation?
    is_in_gross = db.Column(db.Boolean, default=True)

    # Display order in salary slip
    display_order = db.Column(db.Integer, default=0)

    # Is this head active?
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    establishment = db.relationship('Establishment', backref=db.backref('salary_heads', lazy=True))
    percent_of_head = db.relationship('SalaryHead', remote_side=[id])

    def __repr__(self):
        return f'<SalaryHead {self.short_code} ({self.head_type})>'


class EmployeeSalary(db.Model):
    """Salary assignment for each employee — the monthly salary details"""
    __tablename__ = 'employee_salaries'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)

    # Effective date — when this salary takes effect
    effective_from = db.Column(db.Date, nullable=False)

    # Which template was used to create this salary (NULL if manual entry)
    salary_template_id = db.Column(db.Integer, db.ForeignKey('salary_templates.id'), nullable=True)

    # Gross salary (auto-calculated from heads, or manually entered for gross_only)
    gross_salary = db.Column(db.Float, nullable=False, default=0)

    # For daily_wages: rate per day
    daily_rate = db.Column(db.Float, nullable=True)

    # --- Per-Employee Salary Type (allows mixed types in one establishment) ---
    # If NULL, falls back to establishment's PayrollConfig.salary_type
    # 'monthly_fixed'  = Fixed monthly salary
    # 'daily_wages'    = Daily wage × days worked
    # 'monthly_package'= CTC-based package
    salary_type = db.Column(db.String(20), nullable=True)

    # --- Per-Employee WO Override (NULL = use establishment default) ---
    wo_applicable = db.Column(db.Boolean, nullable=True)       # NULL = use config default
    wo_type = db.Column(db.String(10), nullable=True)          # 'paid' / 'unpaid'
    wo_day = db.Column(db.String(12), nullable=True)           # Override WO day
    wo_sandwich_rule = db.Column(db.Boolean, nullable=True)    # Override sandwich rule
    absence_divisor = db.Column(db.String(10), nullable=True)  # Override divisor
    wo_ot_rate = db.Column(db.Float, nullable=True)            # Override OT rate

    # --- Per-Employee Absence Override ---
    # True  = No deduction for absence — full salary paid every month regardless of attendance
    # False/NULL = Use establishment config (deduct for absent days)
    no_absence_deduction = db.Column(db.Boolean, nullable=True, default=False)

    # DEPRECATED
    weekly_off_policy = db.Column(db.String(10), nullable=True)

    # Is this the current active salary? (latest effective)
    is_current = db.Column(db.Boolean, default=True)

    # Revision tracking
    revision_reason = db.Column(db.String(200), nullable=True)  # e.g., "Annual Increment", "Promotion"

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    salary_template = db.relationship('SalaryTemplate', backref=db.backref('employee_salaries', lazy=True))
    employee = db.relationship('Employee', backref=db.backref('salaries', lazy=True,
                               order_by='EmployeeSalary.effective_from.desc()'))
    head_values = db.relationship('EmployeeSalaryHead', backref='employee_salary', lazy=True,
                                  cascade='all, delete-orphan')

    def __repr__(self):
        return f'<EmployeeSalary emp={self.employee_id} gross={self.gross_salary}>'


class EmployeeSalaryHead(db.Model):
    """Individual head amounts for each employee's salary"""
    __tablename__ = 'employee_salary_heads'

    id = db.Column(db.Integer, primary_key=True)
    employee_salary_id = db.Column(db.Integer, db.ForeignKey('employee_salaries.id'), nullable=False)
    salary_head_id = db.Column(db.Integer, db.ForeignKey('salary_heads.id'), nullable=False)

    # The actual amount for this head
    amount = db.Column(db.Float, nullable=False, default=0)

    # Relationship
    salary_head = db.relationship('SalaryHead')

    def __repr__(self):
        return f'<EmployeeSalaryHead head={self.salary_head_id} amt={self.amount}>'


class SalaryTemplate(db.Model):
    """Reusable salary preset per establishment — apply to multiple employees in one click"""
    __tablename__ = 'salary_templates'

    id = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=False)

    name = db.Column(db.String(100), nullable=False)  # e.g., "Unskilled Worker", "Supervisor"

    # Salary type for this template
    # 'monthly_fixed' / 'daily_wages' / 'monthly_package'
    salary_type = db.Column(db.String(20), nullable=False, default='monthly_fixed')

    # Gross salary (for monthly_fixed / monthly_package)
    gross_salary = db.Column(db.Float, default=0)

    # Daily rate (for daily_wages)
    daily_rate = db.Column(db.Float, default=0)

    # Weekly off policy override (NULL = use establishment default)
    weekly_off_policy = db.Column(db.String(10), nullable=True)

    # How many employees currently use this template (for display)
    # Not enforced — just informational
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    establishment = db.relationship('Establishment', backref=db.backref('salary_templates', lazy=True))
    head_values = db.relationship('SalaryTemplateHead', backref='template', lazy=True,
                                  cascade='all, delete-orphan')

    def __repr__(self):
        return f'<SalaryTemplate {self.name} est={self.establishment_id}>'


class SalaryTemplateHead(db.Model):
    """Head-wise amounts stored in a salary template"""
    __tablename__ = 'salary_template_heads'

    id = db.Column(db.Integer, primary_key=True)
    salary_template_id = db.Column(db.Integer, db.ForeignKey('salary_templates.id'), nullable=False)
    salary_head_id = db.Column(db.Integer, db.ForeignKey('salary_heads.id'), nullable=False)

    # The preset amount for this head
    amount = db.Column(db.Float, nullable=False, default=0)

    # Relationship
    salary_head = db.relationship('SalaryHead')

    def __repr__(self):
        return f'<SalaryTemplateHead tmpl={self.salary_template_id} head={self.salary_head_id} amt={self.amount}>'


class MonthlyPayroll(db.Model):
    """Monthly payroll batch per establishment"""
    __tablename__ = 'monthly_payrolls'

    id = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=False)

    # Month and Year
    month = db.Column(db.Integer, nullable=False)    # 1-12
    year = db.Column(db.Integer, nullable=False)      # e.g., 2026

    # Status: 'draft', 'processing', 'finalized'
    status = db.Column(db.String(15), nullable=False, default='draft')

    # ── NIL FILING SUPPORT ──
    # is_nil: True if this is a NIL-return month (no employees worked)
    #         When True: no attendance processed, no ECR generated,
    #         only EPF admin charge + consultant fee recorded.
    is_nil = db.Column(db.Boolean, default=False, index=True)
    # nil_epf_admin: Admin charge for this nil month (usually ₹75 or ₹500)
    nil_epf_admin = db.Column(db.Float, default=0)
    # nil_fee_amount: Consultant fee charged for this nil month
    nil_fee_amount = db.Column(db.Float, default=0)

    # Summary totals (auto-calculated)
    total_gross = db.Column(db.Float, default=0)
    total_epf_employee = db.Column(db.Float, default=0)
    # EPF Employer breakdown totals
    total_epf_ac01 = db.Column(db.Float, default=0)       # EPF A/c 01 (3.67%)
    total_epf_eps = db.Column(db.Float, default=0)         # EPS A/c 10 (8.33%)
    total_epf_admin = db.Column(db.Float, default=0)       # Admin Charge (0.5% min ₹500)
    total_epf_edli = db.Column(db.Float, default=0)        # EDLI (0.5%)
    total_epf_employer = db.Column(db.Float, default=0)    # Total employer (13%)
    total_esic_employee = db.Column(db.Float, default=0)
    total_esic_employer = db.Column(db.Float, default=0)
    total_pt = db.Column(db.Float, default=0)
    total_net_pay = db.Column(db.Float, default=0)
    total_employees = db.Column(db.Integer, default=0)

    # Working days for this month
    working_days = db.Column(db.Integer, nullable=True)

    # Holiday dates — comma-separated day numbers (e.g., "2,15,26")
    # These are National Paid Holidays for this month
    holiday_dates = db.Column(db.String(100), nullable=True)

    # Other Charges — additional billable charges for this month (recorded as Other Income)
    other_charges_description = db.Column(db.String(300), nullable=True)   # e.g., "Annual Return Filing"
    other_charges_amount = db.Column(db.Float, default=0)                   # Amount in ₹

    # EPF Late Payment — Interest (7Q) & Damages (14B)
    # Due date is always 15th of the next month (auto-calculated)
    epf_payment_date = db.Column(db.Date, nullable=True)        # Actual date EPF was paid
    epf_delay_days = db.Column(db.Integer, default=0)           # Days delayed after due date
    epf_interest_14b = db.Column(db.Float, default=0)           # Interest u/s 7Q @ 12% p.a. (field name kept for DB compat)
    epf_damages_7q = db.Column(db.Float, default=0)             # Damages u/s 14B @ 1% per month (field name kept for DB compat)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    establishment = db.relationship('Establishment', backref=db.backref('monthly_payrolls', lazy=True))
    entries = db.relationship('PayrollEntry', backref='monthly_payroll', lazy=True,
                              cascade='all, delete-orphan')

    # Unique constraint: one payroll per establishment per month
    __table_args__ = (
        db.UniqueConstraint('establishment_id', 'month', 'year', name='uq_payroll_est_month_year'),
    )

    def __repr__(self):
        return f'<MonthlyPayroll est={self.establishment_id} {self.month}/{self.year}>'

    @property
    def month_name(self):
        import calendar
        return calendar.month_name[self.month]

    @property
    def period_display(self):
        return f'{self.month_name} {self.year}'

    @property
    def epf_due_date(self):
        """EPF due date = 15th of the next month after payroll month"""
        if self.month == 12:
            return date(self.year + 1, 1, 15)
        else:
            return date(self.year, self.month + 1, 15)


class PayrollEntry(db.Model):
    """Individual employee payroll entry for a given month"""
    __tablename__ = 'payroll_entries'

    id = db.Column(db.Integer, primary_key=True)
    monthly_payroll_id = db.Column(db.Integer, db.ForeignKey('monthly_payrolls.id'), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)

    # Attendance
    days_present = db.Column(db.Float, default=0)
    days_absent = db.Column(db.Float, default=0)
    paid_holidays = db.Column(db.Float, default=0)
    ot_hours = db.Column(db.Float, default=0)         # OT in hours or days depending on config
    total_payable_days = db.Column(db.Float, default=0)

    # Earnings
    gross_salary = db.Column(db.Float, default=0)      # Full month gross
    earned_gross = db.Column(db.Float, default=0)       # Proportionate to days worked
    ot_amount = db.Column(db.Float, default=0)
    total_earnings = db.Column(db.Float, default=0)

    # Statutory Deductions — EPF
    epf_employee = db.Column(db.Float, default=0)       # Employee 12% (A/c 01)
    epf_ac01 = db.Column(db.Float, default=0)            # Employer EPF A/c 01 (3.67%)
    epf_eps = db.Column(db.Float, default=0)             # Employer EPS A/c 10 (8.33%)
    epf_admin = db.Column(db.Float, default=0)           # Admin Charge (0.5% min ₹500)
    epf_edli = db.Column(db.Float, default=0)            # EDLI (0.5%)
    epf_employer = db.Column(db.Float, default=0)        # Total employer (13%)
    # ESIC
    esic_employee = db.Column(db.Float, default=0)
    esic_employer = db.Column(db.Float, default=0)
    professional_tax = db.Column(db.Float, default=0)

    # Arrear Salary
    arrear_amount = db.Column(db.Float, default=0)
    arrear_remark = db.Column(db.String(200), nullable=True)  # e.g., "Arrear for Apr-Jun 2026"

    # Other Deductions
    other_deduction = db.Column(db.Float, default=0)
    other_deduction_remark = db.Column(db.String(200), nullable=True)

    # Net Pay
    total_deductions = db.Column(db.Float, default=0)
    net_pay = db.Column(db.Float, default=0)

    # Compliance wages (for EPF/ESIC calculation basis)
    epf_wages = db.Column(db.Float, default=0)
    esic_wages = db.Column(db.Float, default=0)

    # Rate overrides from universal template upload (JSON)
    # Format: {"daily_rate": 600} or {"gross": 20000} or {"heads": {"BASIC": 10000, "DA": 5000}}
    rate_overrides = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    employee = db.relationship('Employee', backref=db.backref('payroll_entries', lazy=True))

    def __repr__(self):
        return f'<PayrollEntry emp={self.employee_id} net={self.net_pay}>'


class PayrollEntryHead(db.Model):
    """Individual head-wise breakup for each payroll entry"""
    __tablename__ = 'payroll_entry_heads'

    id = db.Column(db.Integer, primary_key=True)
    payroll_entry_id = db.Column(db.Integer, db.ForeignKey('payroll_entries.id'), nullable=False)
    salary_head_id = db.Column(db.Integer, db.ForeignKey('salary_heads.id'), nullable=False)

    # Full month amount and earned (proportionate) amount
    full_amount = db.Column(db.Float, default=0)
    earned_amount = db.Column(db.Float, default=0)

    # Relationships
    payroll_entry = db.relationship('PayrollEntry', backref=db.backref('head_breakup', lazy=True, cascade='all, delete-orphan'))
    salary_head = db.relationship('SalaryHead')

    def __repr__(self):
        return f'<PayrollEntryHead head={self.salary_head_id} earned={self.earned_amount}>'
