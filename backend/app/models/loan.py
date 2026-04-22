"""
Loan Account Model
====================
Tracks loans given (to staff/clients) and loans taken (from banks/others).
EMI auto-calculated. Each repayment stored in LoanPayment with principal/interest split.

Types:
  - 'staff_advance' — advance to staff (usually no interest, manual recovery)
  - 'client_loan'   — loan given to a client for compliance payments, refunded later
  - 'given_other'   — loan given to other parties
  - 'taken'         — loan taken by the business
"""

from app import db
from datetime import datetime, date


class LoanAccount(db.Model):
    """A loan account — represents a single loan relationship."""
    __tablename__ = 'loan_accounts'

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.String(100), nullable=True, index=True)

    # Type
    loan_type = db.Column(db.String(20), nullable=False, default='staff_advance')
    # 'staff_advance' | 'client_loan' | 'given_other' | 'taken'

    # Party (borrower or lender)
    party_name = db.Column(db.String(200), nullable=False)

    # Optional links to existing records
    # IMPORTANT: For "Staff Advance", use staff_user_id (Clerk user_id) — links to AppUser.
    #            For "Client Loan", use establishment_id — links to Establishment.
    #            employee_id is LEGACY (client worker) — not used for new loans.
    staff_user_id = db.Column(db.String(100), nullable=True, index=True)    # AppUser.clerk_user_id
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)   # LEGACY
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=True)
    party_phone = db.Column(db.String(15), nullable=True)

    # Loan details
    principal_amount = db.Column(db.Float, nullable=False, default=0)
    interest_rate_pa = db.Column(db.Float, nullable=True, default=0)   # Annual % — can be 0
    term_months = db.Column(db.Integer, nullable=True)                 # Total duration
    emi_amount = db.Column(db.Float, nullable=True, default=0)         # Auto-computed
    start_date = db.Column(db.Date, nullable=False, default=date.today)
    end_date = db.Column(db.Date, nullable=True)                       # Auto-computed

    # Tracking
    total_paid = db.Column(db.Float, default=0)                         # Cumulative
    total_principal_paid = db.Column(db.Float, default=0)
    total_interest_paid = db.Column(db.Float, default=0)
    outstanding_balance = db.Column(db.Float, default=0)                # Principal remaining

    # Status
    status = db.Column(db.String(15), nullable=False, default='active')
    # 'active' | 'closed' | 'defaulted'

    # Details
    purpose = db.Column(db.Text, nullable=True)
    remarks = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    employee = db.relationship('Employee', foreign_keys=[employee_id], lazy=True)   # LEGACY
    establishment = db.relationship('Establishment', foreign_keys=[establishment_id], lazy=True)
    payments = db.relationship('LoanPayment', backref='loan',
                                lazy='dynamic', cascade='all, delete-orphan',
                                order_by='LoanPayment.payment_date.desc()')

    @property
    def staff_user(self):
        """Look up the AppUser (firm staff member) for this loan, if staff_user_id is set."""
        if not self.staff_user_id:
            return None
        from app.models.app_user import AppUser
        return AppUser.query.filter_by(clerk_user_id=self.staff_user_id).first()

    @property
    def staff_name(self):
        """Human-readable staff name (or None)."""
        u = self.staff_user
        if u:
            return u.name or u.email or 'Staff'
        return None

    @property
    def loan_type_display(self):
        mapping = {
            'staff_advance': 'Staff Advance',
            'client_loan':   'Client Loan',
            'given_other':   'Loan Given (Other)',
            'taken':         'Loan Taken',
        }
        return mapping.get(self.loan_type, self.loan_type)

    @property
    def is_given(self):
        """True for loans GIVEN (money out now, comes back later)"""
        return self.loan_type in ('staff_advance', 'client_loan', 'given_other')

    @property
    def is_taken(self):
        """True for loans TAKEN (money in now, paid back later)"""
        return self.loan_type == 'taken'

    @property
    def progress_pct(self):
        """% of principal paid back."""
        if not self.principal_amount:
            return 0
        return round((self.total_principal_paid / self.principal_amount) * 100, 1)

    @property
    def status_badge_class(self):
        return {
            'active':     'success',
            'closed':     'secondary',
            'defaulted':  'danger',
        }.get(self.status, 'secondary')

    def recalculate(self):
        """Recompute outstanding + cumulative totals from payment history."""
        total_paid = 0
        total_principal = 0
        total_interest = 0
        for p in self.payments:
            total_paid += (p.amount_paid or 0)
            total_principal += (p.principal_portion or 0)
            total_interest += (p.interest_portion or 0)

        self.total_paid = total_paid
        self.total_principal_paid = total_principal
        self.total_interest_paid = total_interest
        self.outstanding_balance = max(0, (self.principal_amount or 0) - total_principal)

        # Auto-close when fully paid
        if self.outstanding_balance <= 0.5 and self.status == 'active':
            self.status = 'closed'

    def __repr__(self):
        return f'<LoanAccount {self.id} {self.loan_type} {self.party_name}>'


class LoanPayment(db.Model):
    """A single EMI / repayment on a loan."""
    __tablename__ = 'loan_payments'

    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loan_accounts.id'), nullable=False)

    payment_date = db.Column(db.Date, nullable=False, default=date.today)
    amount_paid = db.Column(db.Float, nullable=False, default=0)
    principal_portion = db.Column(db.Float, default=0)
    interest_portion = db.Column(db.Float, default=0)
    outstanding_after = db.Column(db.Float, default=0)

    # Payment method / narration
    payment_method = db.Column(db.String(30), nullable=True)   # 'cash', 'bank transfer', 'salary deduction'
    reference = db.Column(db.String(100), nullable=True)        # UTR/Cheque #
    narration = db.Column(db.Text, nullable=True)

    # Optional voucher link (if paid via accounts module)
    voucher_id = db.Column(db.Integer, db.ForeignKey('vouchers.id'), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<LoanPayment loan={self.loan_id} date={self.payment_date} amt={self.amount_paid}>'


def calculate_emi(principal, annual_rate_pct, term_months):
    """Compute standard reducing-balance EMI.
    Returns 0 if any input is invalid or interest is zero (in which case use principal/term)."""
    try:
        principal = float(principal or 0)
        rate = float(annual_rate_pct or 0)
        term = int(term_months or 0)
        if principal <= 0 or term <= 0:
            return 0
        if rate <= 0:
            # Zero-interest loan: flat split
            return round(principal / term, 2)
        monthly_rate = rate / 12 / 100
        factor = (1 + monthly_rate) ** term
        emi = principal * monthly_rate * factor / (factor - 1)
        return round(emi, 2)
    except (ValueError, ZeroDivisionError, TypeError):
        return 0
