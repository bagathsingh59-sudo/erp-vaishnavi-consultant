"""
ClientUser — login credential for the standalone client portal (Spring Boot
+ Next.js app at vaishnavi-client-portal).  This table is created and
maintained by the Spring Boot server's DataSeeder; the ERP reads + writes
it to give the admin a place to view/edit portal credentials.

Schema must stay in sync with:
  vaishnavi-client-portal/server/src/main/java/com/vaishnavi/portal/user/ClientUser.java
"""
from app import db
from datetime import datetime


class ClientUser(db.Model):
    __tablename__ = 'client_users'

    id               = db.Column(db.Integer, primary_key=True)
    establishment_id = db.Column(db.Integer,
                                 db.ForeignKey('establishments.id', ondelete='CASCADE'),
                                 nullable=False, index=True)
    username         = db.Column(db.String(100), unique=True, nullable=False)
    email            = db.Column(db.String(255), unique=True, nullable=False)
    phone            = db.Column(db.String(20),  unique=True, nullable=True)
    password_hash    = db.Column(db.String(255), nullable=False)
    # Plaintext mirror written every time the password is set/changed (by
    # either side).  Admin-only visibility — never returned to portal users.
    vault_password   = db.Column(db.String(255), nullable=True)
    is_active        = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at    = db.Column(db.DateTime, nullable=True)
    created_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, nullable=False,
                                 default=datetime.utcnow, onupdate=datetime.utcnow)

    establishment = db.relationship('Establishment', backref=db.backref('portal_user', uselist=False))

    def __repr__(self):
        return f'<ClientUser id={self.id} username={self.username}>'
