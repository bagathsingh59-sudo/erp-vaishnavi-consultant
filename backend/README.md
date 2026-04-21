# Backend — Flask Server

All Python / Flask server-side code lives here. This is a single Flask application using the **application factory** pattern.

---

## 📂 Folder Structure

```
backend/
├── run.py              Production entry point (imported by gunicorn)
├── run_dev.py          Local development runner (python run_dev.py)
├── clear_data.py       Utility — wipes non-essential data (dev only)
│
└── app/                Main Flask application package
    ├── __init__.py         App factory — Flask() + blueprints + auto-migrations
    ├── auth.py             Clerk JWT validation + @login_required
    ├── user_context.py     Current user helpers, role scoping (admin vs user)
    ├── backup.py           PostgreSQL backup/restore utilities (pg_dump/psql)
    ├── db_utils.py         Database helper functions
    ├── swagger_config.py   Swagger/OpenAPI configuration
    │
    ├── models/             SQLAlchemy ORM models (database schema)
    │   ├── establishment.py
    │   ├── employee.py
    │   ├── payroll.py
    │   ├── accounts.py
    │   ├── daily_mis.py
    │   ├── bonus.py
    │   ├── enrollment.py
    │   ├── manual_reimbursement.py
    │   └── ...
    │
    └── routes/             Flask blueprints (HTTP endpoints)
        ├── establishment.py
        ├── employee.py
        ├── payroll.py
        ├── reports.py
        ├── accounts.py
        ├── backup.py
        ├── daily_mis.py
        ├── bonus.py
        ├── enrollment.py
        ├── manual_reimbursement.py
        └── ...
```

---

## 🏗️ Architectural Patterns

### Application Factory
`create_app()` in `app/__init__.py` builds the Flask app. This lets us:
- Register blueprints cleanly
- Run auto-migrations on startup
- Configure per-environment (dev/prod) without rewrites

### Template + Static Paths
Templates and static assets live OUTSIDE `backend/` — in `frontend/templates/` and `frontend/static/`. The Flask app factory wires them up:

```python
Flask(
    __name__,
    template_folder='../../frontend/templates',
    static_folder='../../frontend/static',
)
```

### Blueprint Organisation
Every feature is a blueprint in `app/routes/<feature>.py`. Each blueprint:
1. Imports its relevant models
2. Applies `@login_required` on routes
3. Uses `user_context.user_X()` helpers for role scoping
4. Renders templates from `frontend/templates/<feature>/`

### User Role Scoping
All data access goes through `user_context.py`:
- `is_admin()` → is current user admin?
- `current_user_id()` → Clerk user ID
- `user_establishments()` → filtered query scoped to user
- `user_vouchers()` → same for vouchers
- `verify_est_ownership()` → 403 if not owner

Admin sees ALL data; regular users see ONLY data they own (`owner_id == current_user_id`).

### Auto-Migrations
On every app startup, `_auto_migrate_columns(db)` runs:
- Checks `information_schema.columns` for each expected column
- Adds columns if missing (via `ALTER TABLE`)
- Lets us add new fields without writing migration files

---

## 🗄️ Models Overview

| Model | Purpose |
|-------|---------|
| `Establishment` | Client companies (300+) with PF/ESIC codes, fees, TDS settings |
| `Employee` | Workers deployed at establishments, with salary + nominee data |
| `PayrollConfig` | Per-establishment rules (how salary/EPF/ESIC is calculated) |
| `MonthlyPayroll` | Monthly payroll batches (status: draft → processing → finalized) |
| `PayrollEntry` | One row per employee per month — all compliance amounts stored |
| `SalaryHead` | Basic/DA/HRA/etc. — defines heads per establishment |
| `EmployeeSalary` | Employee's salary break-up across heads |
| `AccountGroup` + `AccountHead` + `Voucher` + `VoucherEntry` | Tally-style accounting |
| `DailyMISEntry` | Daily task log (payments, returns filed, customer queries) |
| `BonusRun` + `BonusEntry` | Annual bonus calculation (Form C + register) |
| `Enrollment` | UAN/ESIC IP tracker for new employees |
| `ManualReimbursement` | Manual reimbursement letters (no payroll dependency) |
| `AppUser` | Custom role table (admin/user flag, linked to Clerk user_id) |
| `ActivityLog` | Audit trail of user actions |

Full schema history: [`../docs/SCHEMA_LOG.md`](../docs/SCHEMA_LOG.md)

---

## 🛣️ Routes Overview

| Blueprint | URL Prefix | Key Routes |
|-----------|------------|------------|
| `auth` | `/auth/*` | Login, logout, Clerk callback |
| `establishment` | `/establishments` | List, add, edit, select |
| `employee` | `/employees` | List, add, bulk import, salary config |
| `payroll` | `/payroll/*` | Create, process attendance, finalize |
| `reports` | `/payroll/<id>/report/*` | Payslips, Form B/D, ECR, MC template |
| `accounts` | `/accounts/*` | Vouchers, ledger, trial balance, P&L |
| `daily_mis` | `/daily-mis/*` | Task entry, compliance tracker, filing matrix |
| `bonus` | `/bonus/*` | Bonus runs, Form C, register |
| `enrollment` | `/enrollment/*` | UAN/ESIC IP tracker |
| `manual_reimb` | `/manual-reimbursement/*` | Manual letters + history |
| `backup` | `/backup/*` | Create, restore, download, import |
| `admin` | `/admin/*` | User management (admin-only) |

Full catalogue: [`../docs/API-REFERENCE.md`](../docs/API-REFERENCE.md)

---

## 🧪 Running Tests

No automated tests yet. Recommended setup:

```bash
pip install pytest pytest-flask
pytest backend/tests/
```

Tests should live in `backend/tests/` following the same module layout as `app/`.

---

## 🚀 Adding a New Feature

1. **Model:** Create `app/models/<feature>.py` with `db.Model` classes
2. **Routes:** Create `app/routes/<feature>.py` with a `Blueprint`
3. **Templates:** Create `frontend/templates/<feature>/` folder
4. **Register:** In `app/__init__.py`:
   - Import blueprint: `from app.routes.<feature> import <feature>_bp`
   - Register: `app.register_blueprint(<feature>_bp)`
   - Import model (for `create_all()` to pick it up): `from app.models.<feature> import <Model>`
5. **Sidebar link:** Add `<a href="{{ url_for('<feature>.<endpoint>') }}">` in `base.html`
6. **Migration:** If you add columns to existing tables, add to `_auto_migrate_columns()` list in `app/__init__.py`

---

## 📦 Environment Variables

| Variable | Required | Purpose |
|----------|:---:|---------|
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `SECRET_KEY` | ✅ | Flask session signing key |
| `CLERK_SECRET_KEY` | ✅ | Clerk API secret |
| `CLERK_PUBLISHABLE_KEY` | ✅ | Clerk frontend key |
| `ADMIN_EMAILS` | ✅ | Comma-separated admin emails |
| `DB_STORAGE_LIMIT_MB` | ⭕ | For the circular storage gauge (default 500) |

See `.env.example` at repo root for full list.

---

## 🐘 Database Operations

### Backup (via UI)
- Go to `/backup` → "Create Backup"
- Produces `.zip` file containing `pg_dump` SQL
- Saved to `data/backups/<user_id>/`

### Restore (via UI)
- Click "Restore" on any backup row
- Creates restore point first, then runs `psql -f backup.sql`

### Manual backup (command-line)
```bash
pg_dump --no-owner --no-acl -f backup.sql $DATABASE_URL
```

### Manual restore (command-line)
```bash
psql $DATABASE_URL -f backup.sql
```

---

## 🔐 Authentication Flow

1. User hits protected page → `@login_required` decorator kicks in
2. If no session: redirect to Clerk-hosted login page
3. User logs in at Clerk → redirected back with JWT
4. `auth.py` validates JWT, stores user info in Flask session
5. `user_context.current_app_user()` returns cached `AppUser` row
6. Every request can access user_id, name, is_admin

---

## 📖 Related Documentation

- [Architecture](../docs/ARCHITECTURE.md) — high-level system design
- [API Reference](../docs/API-REFERENCE.md) — endpoint catalogue
- [Deployment](../docs/DEPLOYMENT.md) — Railway + production notes
- [Developer Guide](../docs/DEVELOPER-GUIDE.md) — onboarding for new devs
- [Schema Log](../docs/SCHEMA_LOG.md) — database change history
