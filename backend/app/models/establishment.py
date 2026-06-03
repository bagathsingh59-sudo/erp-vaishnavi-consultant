from app import db
from datetime import datetime, date


class Establishment(db.Model):
    __tablename__ = 'establishments'

    id = db.Column(db.Integer, primary_key=True)

    # Owner — Clerk user_id of the creator (historical, does not change)
    owner_id = db.Column(db.String(100), nullable=True, index=True)

    # Handler — Clerk user_id of the currently-assigned staff (admin can re-assign)
    # If null, falls back to owner_id for visibility.
    assigned_to_id = db.Column(db.String(100), nullable=True, index=True)

    # Parent–Child (Sub-Unit / Branch) hierarchy
    # If parent_id is NULL → this is a main/parent establishment
    # If parent_id points to another establishment → this is a sub-unit/branch
    parent_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=True)

    # Basic Information
    company_name = db.Column(db.String(200), nullable=False)
    branch_name = db.Column(db.String(200), nullable=True)   # e.g., "Unit 2", "Bangalore Branch"
    type_of_industry = db.Column(db.String(100), nullable=True)
    date_of_registration = db.Column(db.Date, nullable=True)
    address = db.Column(db.Text, nullable=True)

    # Contact
    contact_person = db.Column(db.String(100), nullable=True)
    contact_phone = db.Column(db.String(15), nullable=True)
    contact_email = db.Column(db.String(100), nullable=True)

    # Registration Numbers
    pf_code = db.Column(db.String(50), nullable=True)
    esic_code = db.Column(db.String(50), nullable=True)
    pan_number = db.Column(db.String(10), nullable=True)
    gst_number = db.Column(db.String(15), nullable=True)

    # Service & Fee
    fee_type = db.Column(db.String(20), nullable=True)       # Monthly, Quarterly, Yearly
    fee_amount = db.Column(db.Float, nullable=True)
    service_type = db.Column(db.String(30), nullable=True)    # With Records, Only Returns

    # Fee billing cycle anchor (used only when fee_type is Quarterly or Yearly).
    # Quarterly: the first billing month of the cycle (e.g. 6 = June).
    #   System derives the other 3 billing months as anchor + 3, + 6, + 9.
    # Yearly: the single year-close billing month (e.g. 3 = March).
    # NULL for Monthly establishments (every month bills, no anchor needed).
    fee_cycle_anchor_month = db.Column(db.Integer, nullable=True)

    # TDS
    tds_applicable = db.Column(db.Boolean, default=False)     # Does this client deduct TDS?
    tds_rate = db.Column(db.Float, nullable=True)             # TDS rate %, default 10 (194J)

    # Compliance Payment Mode — how does this client pay EPF/ESIC?
    #   'through_us'    = Client pays EPF+ESIC+Fee to us, we remit to govt (default)
    #   'client_direct' = Client pays EPF/ESIC directly from their account to govt;
    #                     only Fee comes to us. Accounts only records Fee income.
    compliance_payment_mode = db.Column(db.String(15), nullable=False, default='through_us')

    # ── NIL FILING SETTINGS (for months with no work / no employees) ──
    # nil_filing_fee: Consultant fee charged for nil months (usually lower than regular)
    #                 If blank, user will be asked to enter at payroll creation time.
    nil_filing_fee = db.Column(db.Float, nullable=True)
    # nil_epf_admin_charge: EPF admin charge applicable for nil months
    #                       Usually ₹75 (old rule) or ₹500 (newer rule) — per-client manual entry
    nil_epf_admin_charge = db.Column(db.Float, nullable=True)

    @property
    def opening_balance(self):
        """Read opening balance from the linked Sundry Debtor AccountHead."""
        from app.models.accounts import AccountHead
        debtor = AccountHead.query.filter_by(establishment_id=self.id).first()
        return debtor.opening_balance if debtor else 0

    @property
    def opening_balance_type(self):
        from app.models.accounts import AccountHead
        debtor = AccountHead.query.filter_by(establishment_id=self.id).first()
        return (debtor.opening_balance_type if debtor else 'Dr') or 'Dr'

    # Bonus — Minimum Wage for this establishment's scheduled employment
    # Used as floor for bonus wage ceiling: max(₹7,000, min_wage)
    # Per Payment of Bonus Act Sec. 12. Leave blank if not applicable.
    bonus_min_wage = db.Column(db.Float, nullable=True)

    # License / Registration Expiry Dates
    labour_license_expiry = db.Column(db.Date, nullable=True)
    factory_license_expiry = db.Column(db.Date, nullable=True)
    trade_license_expiry = db.Column(db.Date, nullable=True)
    shop_act_expiry = db.Column(db.Date, nullable=True)
    contract_license_expiry = db.Column(db.Date, nullable=True)
    other_license_name = db.Column(db.String(100), nullable=True)
    other_license_expiry = db.Column(db.Date, nullable=True)

    # Status
    is_active = db.Column(db.Boolean, default=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    credentials = db.relationship('PortalCredential', backref='establishment',
                                  lazy=True, cascade='all, delete-orphan',
                                  order_by='PortalCredential.portal_name')

    # Parent–Child relationship for sub-units/branches
    parent = db.relationship('Establishment', remote_side=[id], backref=db.backref('sub_units', lazy=True))

    @property
    def display_name(self):
        """Show branch name if it's a sub-unit, else company name"""
        if self.parent_id and self.branch_name:
            return f"{self.company_name} — {self.branch_name}"
        return self.company_name

    @property
    def is_sub_unit(self):
        return self.parent_id is not None

    # ── Fee billing-cycle helpers ────────────────────────────────────────────
    # These replace the hard-coded (1, 4, 7, 10) / April-only checks that
    # used to live inline in the dashboard / bulk / admin routes, so the
    # whole codebase agrees on one definition of "is this a billing month".

    @property
    def effective_fee_cycle_anchor(self):
        """Anchor month with safe defaults if none set on the row.
        Quarterly → June (6), Yearly → March (3). These match the backfill
        applied by the auto-migrate on first boot.
        """
        if self.fee_cycle_anchor_month and 1 <= self.fee_cycle_anchor_month <= 12:
            return self.fee_cycle_anchor_month
        ft = (self.fee_type or '').strip()
        if ft == 'Quarterly':
            return 6   # April-June cycle, billed in June
        if ft == 'Yearly':
            return 3   # Indian FY year-close
        return None

    def is_billing_month(self, filing_month):
        """Should this establishment's fee be added in the given filing month?
        Monthly → always. Quarterly → every 3 months from the anchor.
        Yearly → only the anchor month.
        """
        ft = (self.fee_type or 'Monthly').strip()
        if ft == 'Monthly':
            return True
        anchor = self.effective_fee_cycle_anchor
        if anchor is None:
            return False
        if ft == 'Yearly':
            return filing_month == anchor
        if ft == 'Quarterly':
            return (filing_month - anchor) % 3 == 0
        return False

    def billing_months(self):
        """List of months (1..12) this establishment bills in. Used to show
        the user a preview on the establishment form, and on dashboards."""
        ft = (self.fee_type or 'Monthly').strip()
        if ft == 'Monthly':
            return list(range(1, 13))
        anchor = self.effective_fee_cycle_anchor
        if anchor is None:
            return []
        if ft == 'Yearly':
            return [anchor]
        if ft == 'Quarterly':
            return sorted(((anchor - 1 + 3 * i) % 12) + 1 for i in range(4))
        return []

    def next_billing_month(self, from_month, from_year):
        """(month, year) of the NEXT billing month at or after the given
        month. Used to render the "next bill in …" hint on the Slab column."""
        ft = (self.fee_type or 'Monthly').strip()
        if ft == 'Monthly':
            return from_month, from_year
        months = self.billing_months()
        if not months:
            return None, None
        # Find the next month in the current year, else wrap to next year
        future = [m for m in months if m >= from_month]
        if future:
            return future[0], from_year
        return months[0], from_year + 1

    def fee_for_filing_month(self, filing_month):
        """Amount actually charged in the given filing month — zero if it's
        not a billing month for this establishment, full amount otherwise."""
        if not self.fee_amount or not self.is_billing_month(filing_month):
            return 0
        return self.fee_amount

    @property
    def expiring_licenses(self):
        """Return list of licenses expiring within 60 days or already expired"""
        from datetime import date, timedelta
        today = date.today()
        alert_date = today + timedelta(days=60)
        alerts = []
        license_fields = [
            ('labour_license_expiry', 'Labour License'),
            ('factory_license_expiry', 'Factory License'),
            ('trade_license_expiry', 'Trade License'),
            ('shop_act_expiry', 'Shop & Establishment Act'),
            ('contract_license_expiry', 'Contract Labour License'),
            ('other_license_expiry', self.other_license_name or 'Other License'),
        ]
        for field, label in license_fields:
            exp_date = getattr(self, field, None)
            if exp_date:
                days_left = (exp_date - today).days
                if days_left <= 60:
                    alerts.append({
                        'license': label,
                        'expiry': exp_date,
                        'days_left': days_left,
                        'status': 'expired' if days_left < 0 else ('critical' if days_left <= 15 else 'warning')
                    })
        return alerts

    def __repr__(self):
        return f'<Establishment {self.company_name}>'


class PortalCredential(db.Model):
    __tablename__ = 'portal_credentials'

    id = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=False)

    portal_name = db.Column(db.String(100), nullable=False)   # EPF, ESIC, Shram Suvidha, TRACES, GST, IT Portal, etc.
    username = db.Column(db.String(200), nullable=False)
    password = db.Column(db.String(200), nullable=False)
    remarks = db.Column(db.Text, nullable=True)                # Any extra notes like DSC details, authorized signatory, etc.

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<PortalCredential {self.portal_name} - {self.establishment.company_name}>'


class LicenseExpiry(db.Model):
    """Dynamic licence/registration expiry tracking per establishment"""
    __tablename__ = 'license_expiries'

    id = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=False)

    license_name = db.Column(db.String(200), nullable=False)   # e.g., Labour License, Factory License, etc.
    expiry_date = db.Column(db.Date, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    establishment = db.relationship('Establishment', backref=db.backref('license_expiries', lazy=True,
                                    cascade='all, delete-orphan', order_by='LicenseExpiry.expiry_date'))

    def __repr__(self):
        return f'<LicenseExpiry {self.license_name} - {self.expiry_date}>'
