from app import db
from datetime import datetime, date


class Establishment(db.Model):
    __tablename__ = 'establishments'

    id = db.Column(db.Integer, primary_key=True)

    # Owner — Clerk user_id who owns this establishment
    # Used for multi-user data isolation (each user sees only their own data)
    owner_id = db.Column(db.String(100), nullable=True, index=True)

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

    # TDS
    tds_applicable = db.Column(db.Boolean, default=False)     # Does this client deduct TDS?
    tds_rate = db.Column(db.Float, nullable=True)             # TDS rate %, default 10 (194J)

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
