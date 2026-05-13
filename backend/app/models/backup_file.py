"""
BackupFile model — persistent backup storage in PostgreSQL.

Stores each backup ZIP as binary data (LargeBinary / BYTEA) directly in
the database so that backups survive Railway container restarts and
redeploys (the filesystem is ephemeral; the PostgreSQL DB is persistent).

Table: app_backup_files
"""

from datetime import datetime
from app import db


class BackupFile(db.Model):
    __tablename__ = 'app_backup_files'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.String(100), nullable=False, index=True)
    filename   = db.Column(db.String(255), nullable=False)
    label      = db.Column(db.String(500), default='')
    file_data  = db.Column(db.LargeBinary, nullable=False)   # ZIP bytes
    file_size  = db.Column(db.Integer, default=0)            # bytes
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_auto    = db.Column(db.Boolean, default=False)        # True = created by scheduler

    def __repr__(self):
        return f'<BackupFile {self.filename} user={self.user_id}>'
