"""
Non-Client Return Model
========================
Lightweight record for one-time / ad-hoc EPF+ESIC return processing
for establishments that are NOT registered as regular clients in the system.

No employees or establishments are written to the main DB — everything
lives in this single JSON-backed record.
"""

from app import db
from datetime import datetime


class NonClientReturn(db.Model):
    """
    One record per non-client monthly filing.
    Stores the processed result as JSON blobs so no separate employee rows needed.
    """
    __tablename__ = 'non_client_returns'

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.String(100), nullable=False, index=True)  # clerk_user_id of creator

    # Establishment identity (manually entered — NOT a DB foreign key)
    est_name    = db.Column(db.String(300), nullable=False)
    pf_code     = db.Column(db.String(50),  nullable=True)
    esic_code   = db.Column(db.String(50),  nullable=True)

    # Period
    month       = db.Column(db.Integer,  nullable=False)   # 1–12
    year        = db.Column(db.Integer,  nullable=False)   # e.g. 2025

    # Fee and notes
    fee_charged = db.Column(db.Float,    nullable=True, default=0)
    notes       = db.Column(db.Text,     nullable=True)

    # Processing status: 'pending' | 'processed' | 'error'
    status      = db.Column(db.String(20), nullable=False, default='pending')

    # ── Result data (stored as JSON text) ──────────────────────────────
    # List of employee dicts: [{name, uan, ip_no, days, gross, epf_wages, ...}, ...]
    employees_json  = db.Column(db.Text, nullable=True)

    # Pre-built ECR text (ready for EPFO portal upload)
    ecr_text        = db.Column(db.Text, nullable=True)

    # ESIC rows as JSON: [{ip_number, ip_name, no_of_days, total_wages, ...}, ...]
    esic_json       = db.Column(db.Text, nullable=True)

    # Summary totals JSON: {epf_ee_total, eps_total, epf_er_total, esic_ee_total, esic_er_total, ...}
    totals_json     = db.Column(db.Text, nullable=True)

    # Original filename that was uploaded
    source_filename = db.Column(db.String(500), nullable=True)

    # Timestamps
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # ── Convenience properties ──────────────────────────────────────────

    @property
    def month_name(self):
        """Full month name e.g. 'April'."""
        from calendar import month_name
        return month_name[self.month]

    @property
    def period_label(self):
        """Human-readable label e.g. 'April 2025'."""
        return f'{self.month_name} {self.year}'

    def get_employees(self):
        """Deserialise employees_json → list of dicts."""
        import json
        if not self.employees_json:
            return []
        try:
            return json.loads(self.employees_json)
        except Exception:
            return []

    def get_totals(self):
        """Deserialise totals_json → dict."""
        import json
        if not self.totals_json:
            return {}
        try:
            return json.loads(self.totals_json)
        except Exception:
            return {}

    def get_esic_rows(self):
        """Deserialise esic_json → list of dicts."""
        import json
        if not self.esic_json:
            return []
        try:
            return json.loads(self.esic_json)
        except Exception:
            return []

    def __repr__(self):
        return f'<NonClientReturn id={self.id} est={self.est_name!r} {self.period_label}>'
