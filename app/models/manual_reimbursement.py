"""
Manual Reimbursement Model
============================
Lets user create a Reimbursement Letter without going through payroll finalization.
User can pick an existing establishment OR type name+address manually.
Full history tracked with edit/delete support.
"""

from app import db
from datetime import datetime, date


class ManualReimbursement(db.Model):
    """Manual Reimbursement letter — user fills all details by hand"""
    __tablename__ = 'manual_reimbursements'

    id = db.Column(db.Integer, primary_key=True)

    # Owner (user-scoping)
    owner_id = db.Column(db.String(100), nullable=True, index=True)
    staff_name = db.Column(db.String(200), nullable=True)

    # Client — either linked to existing establishment OR manual entry
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=True)
    # Manual fields (used when no establishment selected)
    manual_name = db.Column(db.String(250), nullable=True)
    manual_address = db.Column(db.Text, nullable=True)
    manual_pf_code = db.Column(db.String(50), nullable=True)
    manual_esic_code = db.Column(db.String(50), nullable=True)

    # Letter meta
    letter_date = db.Column(db.Date, nullable=False, default=date.today)
    ref_no = db.Column(db.String(80), nullable=True)
    period_label = db.Column(db.String(60), nullable=True)   # e.g., "April 2025" or "Apr 2025 to Jun 2025"

    # EPF details
    epf_count = db.Column(db.Integer, default=0)
    epf_wages = db.Column(db.Float, default=0)
    epf_ac01 = db.Column(db.Float, default=0)    # 3.67%
    epf_eps = db.Column(db.Float, default=0)     # 8.33%
    epf_edli = db.Column(db.Float, default=0)    # 0.50%
    epf_admin = db.Column(db.Float, default=0)   # 0.50%

    # ESIC details
    esic_count = db.Column(db.Integer, default=0)
    esic_wages = db.Column(db.Float, default=0)
    esic_employer = db.Column(db.Float, default=0)  # 3.25%

    # Computed totals (stored for history/edit convenience)
    epf_employer_refund = db.Column(db.Float, default=0)
    esic_employer_refund = db.Column(db.Float, default=0)
    total_refund = db.Column(db.Float, default=0)

    # Remarks
    remarks = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    establishment = db.relationship('Establishment',
                                    backref=db.backref('manual_reimbursements', lazy='dynamic'))

    @property
    def client_name(self):
        """Return display name — establishment name or manual name"""
        if self.establishment:
            return self.establishment.display_name
        return self.manual_name or '—'

    @property
    def client_address(self):
        if self.establishment:
            return self.establishment.address or ''
        return self.manual_address or ''

    @property
    def pf_code_display(self):
        if self.establishment:
            return self.establishment.pf_code or ''
        return self.manual_pf_code or ''

    @property
    def esic_code_display(self):
        if self.establishment:
            return self.establishment.esic_code or ''
        return self.manual_esic_code or ''

    def recalculate_totals(self):
        """Auto-calculate derived totals from input fields"""
        self.epf_employer_refund = (self.epf_ac01 or 0) + (self.epf_eps or 0) \
                                    + (self.epf_edli or 0) + (self.epf_admin or 0)
        self.esic_employer_refund = self.esic_employer or 0
        self.total_refund = self.epf_employer_refund + self.esic_employer_refund

    def __repr__(self):
        return f'<ManualReimbursement {self.id} {self.client_name} {self.letter_date}>'
