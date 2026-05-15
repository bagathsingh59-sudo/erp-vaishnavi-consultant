from flask import Flask, session, flash, redirect, url_for, request
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
from datetime import timedelta
import os

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

db = SQLAlchemy()
csrf = CSRFProtect()


def create_app():
    # Templates + static live in the frontend/ folder at repo root.
    # From backend/app/ → go up 2 levels → into frontend/
    app = Flask(
        __name__,
        template_folder='../../frontend/templates',
        static_folder='../../frontend/static',
    )

    # Configuration
    base_dir = os.path.abspath(os.path.dirname(__file__))
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'vaishnavi-consultant-erp-secret-key-2026')

    # Database: PostgreSQL only — DATABASE_URL is required
    database_url = os.getenv('DATABASE_URL', '')
    if not database_url:
        raise RuntimeError(
            'DATABASE_URL environment variable is required. '
            'Set it in your .env file. Example: '
            'DATABASE_URL=postgresql://username:password@host:5432/dbname'
        )
    # Railway/Render sometimes provide postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['DB_TYPE'] = 'postgresql'

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    # PostgreSQL connection pooling — tuned to avoid stale connection hangs
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,         # Auto-reconnect dead connections (critical)
        'pool_recycle': 1800,          # Recycle connections every 30 min (not 5)
        'pool_size': 5,                # Keep 5 connections in pool
        'max_overflow': 10,            # Allow 10 extra connections
        'pool_timeout': 10,            # Wait max 10s for a connection (fail fast)
        'connect_args': {
            'connect_timeout': 10,     # PostgreSQL connect timeout (fail fast)
            'keepalives': 1,           # Enable TCP keepalives
            'keepalives_idle': 30,     # Send keepalive after 30s idle
            'keepalives_interval': 10, # Retry every 10s
            'keepalives_count': 5,     # Give up after 5 failed keepalives
        },
    }

    # ── Session & CSRF Lifetime — prevents form data loss during idle ──
    # Users may take 30-60 min to fill long forms (e.g., employee add).
    # Both the Flask session cookie and CSRF token must outlive that window.
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
    app.config['SESSION_PERMANENT'] = True
    app.config['SESSION_REFRESH_EACH_REQUEST'] = True  # Extend session on each request
    app.config['WTF_CSRF_TIME_LIMIT'] = 28800          # 8 hours (matches session)
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # Clerk Authentication Config (Clerk manages all token/session handling)
    app.config['CLERK_PUBLISHABLE_KEY'] = os.getenv('CLERK_PUBLISHABLE_KEY', '')
    app.config['CLERK_SECRET_KEY'] = os.getenv('CLERK_SECRET_KEY', '')

    # Initialize extensions
    db.init_app(app)
    csrf.init_app(app)

    # ── Error Handlers ──
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        """Handle CSRF token errors gracefully instead of showing raw 400 page.
        This commonly happens when:
        - User's session expires while filling a form
        - Browser cache serves a stale page with an old CSRF token
        - User navigates back to a form after their session changed
        """
        flash('Your form session expired. Please try again.', 'warning')
        # Redirect back to the page they were trying to submit
        referrer = request.referrer
        if referrer:
            return redirect(referrer)
        return redirect(url_for('establishment.dashboard'))

    @app.errorhandler(500)
    def handle_500_error(e):
        """Handle internal server errors gracefully"""
        import traceback
        error_msg = str(e)
        app.logger.error(f"500 error: {e}\n{traceback.format_exc()}")

        # Detect database / CRUD errors and show clear notification
        from sqlalchemy.exc import (OperationalError, IntegrityError,
                                     DatabaseError, DisconnectionError)
        original = getattr(e, 'original_exception', e)
        if isinstance(original, DisconnectionError):
            flash('Database connection lost. Please try again.', 'danger')
        elif isinstance(original, IntegrityError):
            flash('Data conflict: duplicate or invalid entry. Please check and try again.', 'danger')
        elif isinstance(original, OperationalError):
            flash('Database operation failed. Please try again or contact admin.', 'danger')
        elif isinstance(original, DatabaseError):
            flash('Database error occurred. Please try again.', 'danger')
        elif 'psycopg2' in error_msg or 'postgresql' in error_msg.lower():
            flash('PostgreSQL connection error. Please check database settings.', 'danger')
        else:
            flash('Something went wrong. Please try again.', 'danger')

        referrer = request.referrer
        if referrer:
            return redirect(referrer)
        return redirect(url_for('establishment.dashboard'))

    # ── Database CRUD Error Safety ──
    @app.after_request
    def handle_db_session_errors(response):
        """Rollback on error responses — do NOT auto-commit on every response.
        Committing on every request was causing stale connections to hang and
        doubling DB writes with the explicit commits in route handlers."""
        try:
            # Only rollback on 4xx/5xx responses — never auto-commit
            if response.status_code >= 400 and db.session.is_active:
                db.session.rollback()
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            app.logger.error(f"DB session auto-rollback: {e}")
        return response

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        """Clean up database session after each request"""
        if exception:
            db.session.rollback()
        db.session.remove()

    # Initialize Clerk Authentication
    from app.auth import init_auth
    init_auth(app)

    # Context processor: inject selected establishment into all templates
    @app.context_processor
    def inject_selected_establishment():
        from app.models.establishment import Establishment
        from app.user_context import is_admin, current_user_id
        selected_est = None
        est_id = session.get('selected_est_id')
        if est_id:
            selected_est = Establishment.query.get(est_id)
            if not selected_est:
                session.pop('selected_est_id', None)
            elif not is_admin():
                # Non-admin: verify they can access this establishment.
                # Access is allowed if they are EITHER:
                #   - the original creator (owner_id), OR
                #   - the currently-assigned handler (assigned_to_id)
                # This keeps the sidebar showing the selected establishment for
                # users working on clients that admin has assigned to them.
                uid = current_user_id()
                if uid and selected_est.owner_id != uid \
                        and getattr(selected_est, 'assigned_to_id', None) != uid:
                    selected_est = None
                    session.pop('selected_est_id', None)
        return dict(selected_est=selected_est)

    # ── MIS Action URL helper (task_type + est_id → target page) ──
    @app.context_processor
    def inject_mis_helpers():
        from flask import url_for as _url

        def mis_action_url(entry):
            """Return action URL for a MIS entry based on task_type + establishment.
            Maps each task to the actual working page where the task can be done."""
            task = entry.task_type
            est_id = entry.establishment_id

            try:
                # ── Payment & Accounts ──
                if task == 'Compliance Amount Received':
                    return _url('accounts.client_payment')
                elif task == 'Fee Received':
                    return _url('accounts.client_payment')
                elif task == 'Challan Payment Done':
                    return _url('accounts.payment_entry')
                elif task == 'Refund / Reversal':
                    return _url('accounts.accounts_home')

                # ── Return Filing → Payroll list (where ECR/ESIC reports are generated) ──
                elif task in ('EPF Return Filed', 'ESIC Return Filed', 'PT Return Filed',
                              'LWF Return Filed', 'Annual Return Filed',
                              'GST Return Filed', 'TDS Return Filed', 'Other Return Filed'):
                    if est_id:
                        return _url('payroll.payroll_list', establishment=est_id)
                    return _url('payroll.payroll_list')

                # ── Employee / Portal Work ──
                elif task == 'Employee Enrolment':
                    if est_id:
                        return _url('employee.employee_add', establishment_id=est_id)
                    return _url('employee.employee_add')
                elif task in ('Employee Exit Processed', 'KYC Update', 'UAN Activation',
                              'IP Generated', 'Transfer / Scheme Certificate',
                              'Claim Settlement', 'DSC Work'):
                    if est_id:
                        return _url('employee.employee_list', establishment=est_id)
                    return _url('employee.employee_list')

                # ── Records & Data ──
                elif task in ('Data Collection', 'Data Entry / Processing',
                              'Records Maintenance'):
                    if est_id:
                        return _url('employee.employee_list', establishment=est_id)
                    return _url('employee.employee_list')
                elif task == 'Document Dispatch' or task == 'Document Received':
                    if est_id:
                        return _url('establishment.establishment_view', id=est_id)
                    return None

                # ── Registration & License ──
                elif task == 'New Establishment Registration':
                    return _url('establishment.establishment_add')
                elif task in ('New PF Registration', 'New ESIC Registration',
                              'Shop Act / License Renewal', 'Amendment / Modification'):
                    if est_id:
                        return _url('establishment.establishment_edit', id=est_id)
                    return _url('establishment.establishment_list')

                # ── Inspection & Legal ──
                elif task in ('Notice Received', 'Notice Reply Submitted',
                              'Inspection Attended', 'Assessment / Hearing'):
                    if est_id:
                        return _url('establishment.establishment_view', id=est_id)
                    return None

                # ── Communication & Support ──
                elif task in ('Customer Query Resolved', 'Follow-up Done'):
                    if est_id:
                        return _url('establishment.establishment_view', id=est_id)
                    return None

                # ── Other ──
                elif task == 'Reconciliation':
                    return _url('accounts.accounts_home')
                elif task == 'Report Prepared':
                    if est_id:
                        return _url('payroll.payroll_list', establishment=est_id)
                    return _url('payroll.payroll_list')

            except Exception:
                pass

            # Fallback: if establishment exists, go to establishment view
            if est_id:
                try:
                    return _url('establishment.establishment_view', id=est_id)
                except Exception:
                    pass
            return None

        return dict(mis_action_url=mis_action_url)

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.backup import backup_bp
    from app.routes.establishment import establishment_bp
    from app.routes.credential import credential_bp
    from app.routes.bulk import bulk_bp
    from app.routes.employee import employee_bp
    from app.routes.employee_bulk import employee_bulk_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(establishment_bp)
    app.register_blueprint(credential_bp)
    app.register_blueprint(bulk_bp)
    app.register_blueprint(employee_bp)
    app.register_blueprint(employee_bulk_bp)

    # Register payroll blueprint
    from app.routes.payroll import payroll_bp
    app.register_blueprint(payroll_bp)

    # Register reports blueprint
    from app.routes.reports import reports_bp
    app.register_blueprint(reports_bp)

    # Register accounts blueprint
    from app.routes.accounts import accounts_bp
    app.register_blueprint(accounts_bp)

    # Register admin blueprint
    from app.routes.admin import admin_bp
    app.register_blueprint(admin_bp)

    # Register Enrollment (UAN & ESIC Tracker) blueprint
    from app.routes.enrollment import enrollment_bp
    app.register_blueprint(enrollment_bp)

    # Register Daily MIS blueprint
    from app.routes.daily_mis import daily_mis_bp
    app.register_blueprint(daily_mis_bp)

    # Register API docs blueprint
    from app.routes.api_docs import api_docs_bp
    app.register_blueprint(api_docs_bp)

    # Register Bonus blueprint
    from app.routes.bonus import bonus_bp
    app.register_blueprint(bonus_bp)

    # Register Manual Reimbursement blueprint
    from app.routes.manual_reimbursement import manual_reimb_bp
    app.register_blueprint(manual_reimb_bp)

    # Register Loan blueprint
    from app.routes.loan import loan_bp
    app.register_blueprint(loan_bp)

    # Register Non-Client Quick Returns blueprint
    from app.routes.non_client import non_client_bp
    app.register_blueprint(non_client_bp)

    # Register Vault blueprint — disabled for now, re-enable later
    # from app.routes.vault import vault_bp
    # app.register_blueprint(vault_bp)

    # ── Swagger API Documentation ──
    from flasgger import Swagger
    from app.swagger_config import SWAGGER_TEMPLATE, SWAGGER_CONFIG
    Swagger(app, template=SWAGGER_TEMPLATE, config=SWAGGER_CONFIG)

    # Exempt Swagger & API endpoints from CSRF
    csrf.exempt('flasgger.apispec_1')
    csrf.exempt('flasgger.apidocs')
    csrf.exempt('api_docs.test_db_connection')

    # Create database tables
    with app.app_context():
        from app.models.establishment import Establishment, PortalCredential
        from app.models.employee import Employee, Nominee, TransferHistory
        from app.models.payroll import (PayrollConfig, SalaryHead, EmployeeSalary,
                                         EmployeeSalaryHead, MonthlyPayroll, PayrollEntry,
                                         PayrollEntryHead)
        from app.models.accounts import AccountGroup, AccountHead, Voucher, VoucherEntry
        from app.models.activity_log import ActivityLog
        from app.models.app_user import AppUser
        from app.models.daily_mis import DailyMISEntry
        from app.models.bonus import BonusRun, BonusEntry
        from app.models.vault import VaultFile
        from app.models.enrollment import Enrollment
        from app.models.manual_reimbursement import ManualReimbursement
        from app.models.loan import LoanAccount, LoanPayment
        from app.models.assignment_log import EstablishmentAssignmentLog
        from app.models.backup_file import BackupFile   # persistent backup storage
        from app.models.non_client import NonClientReturn   # non-client quick returns
        db.create_all()

        # Auto-migrate: add new columns to existing tables (PostgreSQL won't add via create_all)
        _auto_migrate_columns(db)

        # Seed default account groups and heads (only once)
        _seed_default_accounts()

        # Seed any newly added account heads for existing DBs
        _seed_missing_account_heads()

    # ── Scheduled auto-backup every 15 days ───────────────────────────
    _start_backup_scheduler(app)

    return app


def _start_backup_scheduler(app):
    """
    Start a background APScheduler that runs daily at 02:00 server time and
    creates a backup if the most-recent backup (any user) is ≥ 15 days old.

    Multi-worker safety: the job checks the DB before acting, so even if
    two gunicorn workers both start the scheduler, only one will actually
    create a backup (the other sees the fresh record and skips).
    """
    import os
    # Allow disabling via env var if needed (e.g. local dev with no pg_dump)
    if os.getenv('DISABLE_BACKUP_SCHEDULER', '').lower() in ('1', 'true', 'yes'):
        print('[SCHEDULER] Auto-backup scheduler disabled via DISABLE_BACKUP_SCHEDULER env var')
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        def _job():
            with app.app_context():
                from app.backup import auto_create_if_needed
                auto_create_if_needed()

        scheduler = BackgroundScheduler(daemon=True)
        # Run at 02:00 every day; add 0-300s jitter to stagger workers
        scheduler.add_job(
            _job,
            trigger=CronTrigger(hour=2, minute=0, jitter=300),
            id='auto_backup',
            name='Auto DB Backup (15-day)',
            replace_existing=True,
            misfire_grace_time=3600,   # Allow up to 1h delay (e.g. restart during window)
        )
        scheduler.start()
        print('[SCHEDULER] Auto-backup scheduler started (daily at 02:00, ±5 min jitter)')
    except Exception as e:
        # Never crash the app if scheduler fails to start
        print(f'[SCHEDULER] Failed to start: {e}')


def _auto_migrate_columns(db):
    """Add new columns to existing tables if they don't exist yet.
    PostgreSQL's CREATE TABLE IF NOT EXISTS won't add columns to tables that already exist.
    This safely checks and adds any missing columns."""
    migrations = [
        # (table_name, column_name, column_definition)
        ('payroll_configs', 'include_ot_in_compliance', 'BOOLEAN DEFAULT FALSE'),
        ('payroll_configs', 'include_ot_in_epf', 'BOOLEAN DEFAULT FALSE'),
        ('payroll_configs', 'include_ot_in_esic', 'BOOLEAN DEFAULT FALSE'),
        ('payroll_configs', 'esic_contribution_type', "VARCHAR(10) DEFAULT 'ceiling'"),
        ('employee_salaries', 'no_absence_deduction', 'BOOLEAN DEFAULT FALSE'),
        ('payroll_entries', 'rate_overrides', 'TEXT'),
        ('establishments', 'bonus_min_wage', 'FLOAT'),
        ('establishments', 'assigned_to_id', 'VARCHAR(100)'),
        ('loan_accounts', 'staff_user_id', 'VARCHAR(100)'),
        # Multi-month client payment — tag each entry with its payroll period
        ('voucher_entries', 'period_year', 'INTEGER'),
        ('voucher_entries', 'period_month', 'INTEGER'),
        # Compliance payment mode — fee-only vs through-us
        ('establishments', 'compliance_payment_mode', "VARCHAR(15) DEFAULT 'through_us'"),
        # NIL filing support
        ('establishments', 'nil_filing_fee', 'FLOAT'),
        ('establishments', 'nil_epf_admin_charge', 'FLOAT'),
        ('monthly_payrolls', 'is_nil', 'BOOLEAN DEFAULT FALSE'),
        ('monthly_payrolls', 'nil_epf_admin', 'FLOAT DEFAULT 0'),
        ('monthly_payrolls', 'nil_fee_amount', 'FLOAT DEFAULT 0'),
        # OT base wage — 'gross' (default) or 'basic_only'
        ('payroll_configs', 'ot_base_wage', "VARCHAR(15) DEFAULT 'gross'"),
    ]
    for table, column, col_def in migrations:
        try:
            # Check if column exists
            result = db.session.execute(db.text(
                f"SELECT column_name FROM information_schema.columns "
                f"WHERE table_name='{table}' AND column_name='{column}'"
            )).fetchone()
            if not result:
                db.session.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
                db.session.commit()
                print(f"  [MIGRATE] Added column {table}.{column}")
        except Exception as e:
            db.session.rollback()
            print(f"  [MIGRATE] Skip {table}.{column}: {e}")

    # One-time data migration: copy old include_ot_in_compliance → new split fields
    try:
        db.session.execute(db.text(
            "UPDATE payroll_configs SET include_ot_in_epf = include_ot_in_compliance, "
            "include_ot_in_esic = include_ot_in_compliance "
            "WHERE include_ot_in_compliance = TRUE AND include_ot_in_epf = FALSE AND include_ot_in_esic = FALSE"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()

    # One-time data migration: backfill assigned_to_id with owner_id
    # So existing establishments stay visible to the user who created them.
    try:
        db.session.execute(db.text(
            "UPDATE establishments SET assigned_to_id = owner_id "
            "WHERE assigned_to_id IS NULL AND owner_id IS NOT NULL"
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _seed_default_accounts():
    """Create default Tally-style account groups and heads if not already present"""
    from app.models.accounts import AccountGroup, AccountHead

    # Check if already seeded
    if AccountGroup.query.first():
        return

    # ── Account Groups ──
    groups = {
        # Assets
        'Current Assets':      ('asset', None),
        'Bank Accounts':       ('asset', 'Current Assets'),
        'Cash-in-Hand':        ('asset', 'Current Assets'),
        'Sundry Debtors':      ('asset', 'Current Assets'),
        # Liabilities
        'Current Liabilities': ('liability', None),
        # Income
        'Indirect Income':     ('income', None),
        # Expenses
        'Indirect Expenses':   ('expense', None),
    }

    group_objs = {}
    # Create parent groups first, then children
    for name, (nature, parent_name) in groups.items():
        if parent_name is None:
            grp = AccountGroup(name=name, nature=nature, is_system=True)
            db.session.add(grp)
            db.session.flush()
            group_objs[name] = grp

    for name, (nature, parent_name) in groups.items():
        if parent_name is not None:
            grp = AccountGroup(name=name, nature=nature,
                               parent_id=group_objs[parent_name].id, is_system=True)
            db.session.add(grp)
            db.session.flush()
            group_objs[name] = grp

    # ── Default Account Heads ──
    heads = [
        ('SBI Current Account',     'Bank Accounts',       True),
        ('Cash Account',            'Cash-in-Hand',        True),
        ('EPF Payable',             'Current Liabilities', True),
        ('ESIC Payable',            'Current Liabilities', True),
        ('Excess Client Receipts',  'Current Liabilities', True),
        ('TDS Receivable',          'Current Assets',      True),
        ('Professional Fees',       'Indirect Income',     True),
        ('IP & UAN Charges',        'Indirect Income',     True),
        ('Other Income',            'Indirect Income',     True),
        ('Bank Charges',            'Indirect Expenses',   True),
        # Standard expense heads — pre-seeded for one-click expense entry
        ('Office Rent',             'Indirect Expenses',   True),
        ('Electricity Bill',        'Indirect Expenses',   True),
        ('Internet Bill',           'Indirect Expenses',   True),
        ('Telephone Bill',          'Indirect Expenses',   True),
        ('Water Charges',           'Indirect Expenses',   True),
        ('Staff Salaries',          'Indirect Expenses',   True),
        ('Staff Incentive',         'Indirect Expenses',   True),
        ('Office Maintenance',      'Indirect Expenses',   True),
        ('Transport / Fuel',        'Indirect Expenses',   True),
        ('Donation',                'Indirect Expenses',   True),
        ('Interest Paid',           'Indirect Expenses',   True),
        ('EMI Paid',                'Indirect Expenses',   True),
        ('Printing & Stationery',   'Indirect Expenses',   True),
        ('Professional Tax (Own)',  'Indirect Expenses',   True),
        ('Repair & Maintenance',    'Indirect Expenses',   True),
        ('Food / Refreshments',     'Indirect Expenses',   True),
        ('Travel & Conveyance',     'Indirect Expenses',   True),
        ('Hosting / Software',      'Indirect Expenses',   True),
        ('Miscellaneous Expenses',  'Indirect Expenses',   True),
        # Loan accounts — pre-seeded for loan module
        ('Loans Given (Staff)',     'Current Assets',      True),
        ('Loans Given (Client)',    'Current Assets',      True),
        ('Loans Taken',             'Current Liabilities', True),
    ]

    for head_name, group_name, is_sys in heads:
        h = AccountHead(name=head_name, group_id=group_objs[group_name].id,
                        is_system=is_sys)
        db.session.add(h)

    db.session.commit()


def _seed_missing_account_heads():
    """Add any newly introduced system accounts to existing databases.
    Safe to run repeatedly — only creates missing heads."""
    from app.models.accounts import AccountGroup, AccountHead

    # Only run if groups already exist (i.e., not a fresh DB)
    if not AccountGroup.query.first():
        return

    group_map = {g.name: g for g in AccountGroup.query.all()}

    new_heads = [
        ('Office Rent',             'Indirect Expenses'),
        ('Electricity Bill',        'Indirect Expenses'),
        ('Internet Bill',           'Indirect Expenses'),
        ('Telephone Bill',          'Indirect Expenses'),
        ('Water Charges',           'Indirect Expenses'),
        ('Staff Salaries',          'Indirect Expenses'),
        ('Staff Incentive',         'Indirect Expenses'),
        ('Office Maintenance',      'Indirect Expenses'),
        ('Transport / Fuel',        'Indirect Expenses'),
        ('Donation',                'Indirect Expenses'),
        ('Interest Paid',           'Indirect Expenses'),
        ('EMI Paid',                'Indirect Expenses'),
        ('Printing & Stationery',   'Indirect Expenses'),
        ('Professional Tax (Own)',  'Indirect Expenses'),
        ('Repair & Maintenance',    'Indirect Expenses'),
        ('Food / Refreshments',     'Indirect Expenses'),
        ('Travel & Conveyance',     'Indirect Expenses'),
        ('Hosting / Software',      'Indirect Expenses'),
        ('Miscellaneous Expenses',  'Indirect Expenses'),
        ('Loans Given (Staff)',     'Current Assets'),
        ('Loans Given (Client)',    'Current Assets'),
        ('Loans Taken',             'Current Liabilities'),
    ]

    for head_name, group_name in new_heads:
        group = group_map.get(group_name)
        if not group:
            continue
        existing = AccountHead.query.filter_by(name=head_name).first()
        if not existing:
            h = AccountHead(name=head_name, group_id=group.id, is_system=True)
            db.session.add(h)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
