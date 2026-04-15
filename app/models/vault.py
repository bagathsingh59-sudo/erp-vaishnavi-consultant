"""
Compliance Document Vault — stores metadata for uploaded files.
Physical files live under data/vault/ on disk.
"""
from app import db
from datetime import datetime

# Fixed category list (edit only here)
VAULT_CATEGORIES = [
    ('EPF', 'EPF — ECR / Challan / Receipt'),
    ('ESIC', 'ESIC — Contribution / Challan / Receipt'),
    ('PT', 'Professional Tax — Return / Challan / Receipt'),
    ('LWF', 'Labour Welfare Fund — Return / Challan / Receipt'),
    ('TDS', 'TDS — 24Q / Challan / TRACES'),
    ('LABOUR', 'Labour Dept — Form B / D / Annual Returns'),
    ('BONUS', 'Bonus — Form A / C / D / Payment Proof'),
    ('REGISTRATION', 'Registrations — Licenses / Certificates'),
    ('OTHER', 'Other — Notices, Letters, Misc.'),
]
VAULT_CATEGORY_KEYS = [k for k, _ in VAULT_CATEGORIES]
VAULT_CATEGORY_LABELS = dict(VAULT_CATEGORIES)


class VaultFile(db.Model):
    __tablename__ = 'vault_files'

    id = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer, db.ForeignKey('establishments.id'), nullable=False, index=True)

    category = db.Column(db.String(20), nullable=False, index=True)     # EPF / ESIC / ...
    fy_start_year = db.Column(db.Integer, nullable=False, index=True)   # e.g. 2024 for FY 2024-25
    # For monthly docs: month number 1–12. For registrations/yearly docs: nullable.
    month = db.Column(db.Integer, nullable=True)

    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)   # Possibly renamed to avoid duplicates
    relative_path = db.Column(db.String(500), nullable=False)     # Relative to data/vault/
    size_bytes = db.Column(db.Integer, default=0)
    mime_type = db.Column(db.String(100), nullable=True)

    description = db.Column(db.String(300), nullable=True)

    uploaded_by = db.Column(db.String(100), nullable=True)        # Clerk user id
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    establishment = db.relationship('Establishment', backref='vault_files')

    @property
    def fy_label(self):
        return f"FY {self.fy_start_year}-{str(self.fy_start_year + 1)[-2:]}"

    @property
    def month_label(self):
        if not self.month:
            return '—'
        import calendar
        return f"{calendar.month_name[self.month]} {self.fy_start_year if self.month >= 4 else self.fy_start_year + 1}"

    @property
    def category_label(self):
        return VAULT_CATEGORY_LABELS.get(self.category, self.category)

    @property
    def size_human(self):
        n = self.size_bytes or 0
        for unit in ['B', 'KB', 'MB', 'GB']:
            if n < 1024:
                return f"{n:.1f} {unit}" if unit != 'B' else f"{n} {unit}"
            n /= 1024
        return f"{n:.1f} TB"
