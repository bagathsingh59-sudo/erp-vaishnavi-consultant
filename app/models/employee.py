from app import db
from datetime import datetime


class Employee(db.Model):
    __tablename__ = 'employees'

    id = db.Column(db.Integer, primary_key=True)
    emp_code = db.Column(db.String(20), unique=True, nullable=False)  # Auto: EMP0001, EMP0002...

    # Current Establishment (foreign key — can change via transfer)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=False)

    # Mandatory Fields
    name = db.Column(db.String(200), nullable=False)            # As per Aadhaar
    father_husband_name = db.Column(db.String(200), nullable=False)
    gender = db.Column(db.String(10), nullable=False)           # Male, Female, Other
    date_of_birth = db.Column(db.Date, nullable=False)
    date_of_joining = db.Column(db.Date, nullable=False)
    uan_number = db.Column(db.String(20), nullable=True)        # Primary ID — at least one of UAN/ESIC required
    esic_ip_number = db.Column(db.String(20), nullable=True)    # ESIC IP Number
    internal_emp_code = db.Column(db.String(50), nullable=True)  # Client's own employee code
    use_internal_code = db.Column(db.Boolean, default=False)     # Show internal code in reports

    # EPFO Registered Data (from EPF Active Member Download)
    epfo_name = db.Column(db.String(200), nullable=True)       # Exact name in EPFO records (golden source)
    member_id = db.Column(db.String(50), nullable=True)        # EPF Member ID (e.g., GBGLB00210660000020881)
    relation = db.Column(db.String(20), nullable=True)         # FATHER / HUSBAND
    nomination_filed = db.Column(db.Boolean, nullable=True)    # From EPFO
    aadhaar_verified = db.Column(db.Boolean, nullable=True)    # From EPFO
    face_auth_status = db.Column(db.Boolean, nullable=True)    # From EPFO
    name_mismatch_accepted = db.Column(db.Boolean, default=False)  # User accepted name mismatch

    # Personal Details (update later)
    aadhaar_number = db.Column(db.String(12), nullable=True)
    pan_number = db.Column(db.String(10), nullable=True)
    mobile_number = db.Column(db.String(15), nullable=True)
    email = db.Column(db.String(100), nullable=True)
    address = db.Column(db.Text, nullable=True)
    marital_status = db.Column(db.String(15), nullable=True)    # Single, Married, Widowed, Divorced

    # Bank Details (update later)
    bank_name = db.Column(db.String(100), nullable=True)
    bank_account_number = db.Column(db.String(30), nullable=True)
    bank_ifsc_code = db.Column(db.String(11), nullable=True)

    # Statutory Applicability (per-employee overrides)
    esic_exempt = db.Column(db.Boolean, default=False)            # True = skip ESIC for this employee
    esic_exemption_reason = db.Column(db.String(200), nullable=True)  # Why exempted (client request, wages above ceiling, etc.)

    # Employment Details (update later)
    designation = db.Column(db.String(100), nullable=True)
    department = db.Column(db.String(100), nullable=True)

    # Exit Details
    date_of_exit = db.Column(db.Date, nullable=True)
    exit_reason = db.Column(db.String(50), nullable=True)       # Resigned, Terminated, Absconded, Retired, Deceased

    # Status
    is_active = db.Column(db.Boolean, default=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    establishment = db.relationship('Establishment', backref=db.backref('employees', lazy=True))
    nominees = db.relationship('Nominee', backref='employee', lazy=True,
                               cascade='all, delete-orphan', order_by='Nominee.id')
    transfer_history = db.relationship('TransferHistory', backref='employee', lazy=True,
                                       cascade='all, delete-orphan',
                                       order_by='TransferHistory.transfer_date.desc()')

    @property
    def has_name_mismatch(self):
        """Check if ERP name differs from EPFO registered name"""
        if not self.epfo_name:
            return False
        return self.name.strip().upper() != self.epfo_name.strip().upper()

    @property
    def name_status(self):
        """Return name validation status: 'match', 'mismatch', 'accepted', 'no_epfo'"""
        if not self.epfo_name:
            return 'no_epfo'
        if not self.has_name_mismatch:
            return 'match'
        if self.name_mismatch_accepted:
            return 'accepted'
        return 'mismatch'

    @property
    def primary_id(self):
        """Primary visible identifier: UAN > ESIC IP > emp_code fallback.
        If establishment has EPF → UAN is primary.
        If only ESIC → ESIC IP is primary.
        Falls back to emp_code if neither is available.
        """
        if self.uan_number:
            return self.uan_number
        if self.esic_ip_number:
            return self.esic_ip_number
        return self.emp_code

    @property
    def primary_id_label(self):
        """Label for the primary identifier (UAN / ESIC IP / Code)"""
        if self.uan_number:
            return 'UAN'
        if self.esic_ip_number:
            return 'ESIC IP'
        return 'Code'

    def __repr__(self):
        return f'<Employee {self.emp_code} - {self.name}>'

    @staticmethod
    def generate_emp_code():
        """Generate next employee code like EMP0001, EMP0002..."""
        last = Employee.query.order_by(Employee.id.desc()).first()
        if last:
            num = int(last.emp_code.replace('EMP', '')) + 1
        else:
            num = 1
        return f'EMP{num:04d}'


class Nominee(db.Model):
    __tablename__ = 'nominees'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)

    name = db.Column(db.String(200), nullable=False)
    relation = db.Column(db.String(50), nullable=False)         # Wife, Husband, Son, Daughter, Father, Mother, etc.
    date_of_birth = db.Column(db.Date, nullable=True)
    aadhaar_number = db.Column(db.String(12), nullable=True)
    share_percentage = db.Column(db.Float, nullable=True)       # e.g., 50.0 for 50%

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Nominee {self.name} ({self.relation})>'


class TransferHistory(db.Model):
    __tablename__ = 'transfer_history'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)

    from_establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=False)
    to_establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=False)
    transfer_date = db.Column(db.Date, nullable=False)
    remarks = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    from_establishment = db.relationship('Establishment', foreign_keys=[from_establishment_id])
    to_establishment = db.relationship('Establishment', foreign_keys=[to_establishment_id])

    def __repr__(self):
        return f'<Transfer {self.employee_id} on {self.transfer_date}>'
