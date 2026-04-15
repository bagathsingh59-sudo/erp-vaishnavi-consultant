from app import db
from datetime import datetime, date


class AccountGroup(db.Model):
    """Account groups — like Tally's predefined groups"""
    __tablename__ = 'account_groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    # nature: asset, liability, income, expense
    nature = db.Column(db.String(20), nullable=False)
    # parent_id for sub-groups (e.g., Bank Accounts under Current Assets)
    parent_id = db.Column(db.Integer, db.ForeignKey('account_groups.id'), nullable=True)
    is_system = db.Column(db.Boolean, default=False)  # System groups can't be deleted

    parent = db.relationship('AccountGroup', remote_side=[id],
                             backref=db.backref('sub_groups', lazy=True))

    def __repr__(self):
        return f'<AccountGroup {self.name}>'


class AccountHead(db.Model):
    """Individual account heads — like Tally ledgers"""
    __tablename__ = 'account_heads'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('account_groups.id'), nullable=False)

    # If this account is linked to an establishment (Sundry Debtor)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=True)

    opening_balance = db.Column(db.Float, default=0)  # Opening balance for FY
    # opening_balance_type: 'Dr' or 'Cr'
    opening_balance_type = db.Column(db.String(2), default='Dr')

    is_system = db.Column(db.Boolean, default=False)  # System accounts can't be deleted
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    group = db.relationship('AccountGroup', backref=db.backref('accounts', lazy=True))
    establishment = db.relationship('Establishment', backref=db.backref('account_head', uselist=False, lazy=True))

    def __repr__(self):
        return f'<AccountHead {self.name}>'

    @property
    def nature(self):
        return self.group.nature if self.group else 'asset'


class Voucher(db.Model):
    """Transaction voucher — Receipt, Payment, Journal"""
    __tablename__ = 'vouchers'

    id = db.Column(db.Integer, primary_key=True)

    # Owner — Clerk user_id who created this voucher (for multi-user data isolation)
    owner_id = db.Column(db.String(100), nullable=True, index=True)

    # Voucher type: receipt, payment, journal
    voucher_type = db.Column(db.String(20), nullable=False)
    voucher_number = db.Column(db.String(30), nullable=False)  # Auto-generated: RV-001, PV-001, JV-001
    voucher_date = db.Column(db.Date, nullable=False)

    # For client payment entries — link to establishment
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=True)
    # For payroll-linked entries
    payroll_id = db.Column(db.Integer, db.ForeignKey('monthly_payrolls.id'), nullable=True)

    # Reference / UTR / TRRN
    reference = db.Column(db.String(100), nullable=True)
    narration = db.Column(db.Text, nullable=True)

    # Total amount (sum of debit side = sum of credit side)
    total_amount = db.Column(db.Float, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    establishment = db.relationship('Establishment', backref=db.backref('vouchers', lazy=True))
    entries = db.relationship('VoucherEntry', backref='voucher', lazy=True,
                              cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Voucher {self.voucher_type} {self.voucher_number}>'


class VoucherEntry(db.Model):
    """Individual debit/credit line in a voucher — double entry"""
    __tablename__ = 'voucher_entries'

    id = db.Column(db.Integer, primary_key=True)
    voucher_id = db.Column(db.Integer, db.ForeignKey('vouchers.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account_heads.id'), nullable=False)

    # debit or credit
    entry_type = db.Column(db.String(6), nullable=False)  # 'debit' or 'credit'
    amount = db.Column(db.Float, nullable=False, default=0)

    # Optional: description for this line
    particulars = db.Column(db.String(300), nullable=True)

    # Relationships
    account = db.relationship('AccountHead', backref=db.backref('entries', lazy=True))

    def __repr__(self):
        return f'<VoucherEntry {self.entry_type} {self.amount} → {self.account.name if self.account else "?"}>'
