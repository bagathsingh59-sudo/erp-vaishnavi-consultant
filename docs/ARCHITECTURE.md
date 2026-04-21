# Architecture Overview

## 🏗️ High-Level System Design

```
                     ┌─────────────────────┐
                     │    USER / BROWSER   │
                     └──────────┬──────────┘
                                │ HTTPS
                                ▼
                     ┌─────────────────────┐
                     │   RAILWAY EDGE      │
                     │  erp.srivenkates…   │
                     └──────────┬──────────┘
                                │
                                ▼
                     ┌─────────────────────┐
                     │   GUNICORN (WSGI)   │
                     │   2 workers         │
                     └──────────┬──────────┘
                                │
                                ▼
     ┌──────────────────────────────────────────────┐
     │              FLASK APP (backend/app)          │
     │                                               │
     │  ┌─────────┐   ┌─────────┐   ┌──────────┐    │
     │  │ Routes  │──▶│ Models  │──▶│ Database │    │
     │  │ (HTTP)  │   │ (ORM)   │   │ Postgres │    │
     │  └────┬────┘   └─────────┘   └──────────┘    │
     │       │                                       │
     │       ▼                                       │
     │  ┌─────────────┐                              │
     │  │   Jinja2    │──▶ frontend/templates/       │
     │  │  renderer   │                              │
     │  └─────────────┘                              │
     └──────────────────────────────────────────────┘
                                │
                                ▼
                     ┌─────────────────────┐
                     │   CLERK (SaaS Auth) │
                     │   JWT validation    │
                     └─────────────────────┘
```

## 🔁 Request Lifecycle

1. Browser sends HTTPS request to `erp.srivenkateshwara.in/...`
2. Railway edge routes it to the running container
3. Gunicorn hands it to a Flask worker
4. Flask's `before_request` → Clerk JWT validation via `auth.py`
5. If authenticated → route handler executes
6. Handler queries DB via SQLAlchemy models
7. Scoped data via `user_context.user_X()` helpers (admin sees all, user sees own)
8. Handler calls `render_template('path.html', **data)`
9. Jinja looks up template in `../../frontend/templates/` (relative to Flask app)
10. Rendered HTML returned to browser

## 📦 Module Map

```
backend/app/
├── __init__.py             App factory
├── auth.py                 Clerk integration + @login_required
├── user_context.py         Role scoping (admin vs user)
├── backup.py               pg_dump / psql wrappers
│
├── models/                 ORM (SQLAlchemy)
│   ├── establishment.py    300+ client companies
│   ├── employee.py         Workers + nominees + transfer history
│   ├── payroll.py          PayrollConfig, MonthlyPayroll, Entry, Heads
│   ├── accounts.py         Voucher + Entry + AccountHead/Group
│   ├── daily_mis.py        Task log
│   ├── bonus.py            BonusRun + BonusEntry
│   ├── enrollment.py       UAN/ESIC IP tracker
│   ├── manual_reimbursement.py
│   ├── app_user.py         Role table
│   └── activity_log.py     Audit trail
│
└── routes/                 HTTP endpoints (Blueprints)
    ├── auth.py
    ├── establishment.py
    ├── employee.py + employee_bulk.py
    ├── payroll.py
    ├── reports.py          ⚡ Heavy: generates reports
    ├── accounts.py         ⚡ Heavy: ledger, trial balance
    ├── daily_mis.py        Includes filing_matrix (admin-only)
    ├── bonus.py
    ├── enrollment.py
    ├── manual_reimbursement.py
    ├── backup.py
    ├── admin.py            User management
    └── api_docs.py         Swagger
```

## 🔒 Authentication & Authorization

### Authentication (Clerk)
- External SaaS — Clerk hosts login page
- Returns signed JWT
- Backend validates JWT on every request
- Session caches validated user info

### Authorization (in-house)
Two roles: **admin** and **user**

Admin-only features:
- Accounts module (vouchers, ledgers)
- Filing Status Matrix
- All backups (user sees only own)
- User management

Data scoping:
- Every query filters by `owner_id = current_user_id()` for non-admins
- Admin queries have no such filter
- `verify_est_ownership()` throws 403 if user tries to access another user's establishment

## 🗄️ Database Strategy

### Connection Pool
- `pool_size=5, max_overflow=10` (total 15 simultaneous connections)
- `pool_pre_ping=True` → auto-reconnect dead connections
- `pool_recycle=1800` → recycle every 30 minutes (prevent stale)
- `keepalives_idle=30` → TCP keepalive for Railway's network

### Auto-migrations
On every startup, `_auto_migrate_columns(db)` runs:
- Queries `information_schema.columns` for each (table, column) pair in its list
- If missing → runs `ALTER TABLE ADD COLUMN`
- This lets us add new columns without writing Alembic migrations

### Backup Strategy
- User triggers via UI → `pg_dump --no-owner --no-acl` → ZIP-compressed
- Stored in `data/backups/<user_id>/erp_backup_YYYY-MM-DD_HH-MM-SS.zip`
- Max 20 kept per user (auto-cleanup)
- Restore creates "restore point" first (safety net)
- Users can import ZIP from local disk for disaster recovery

## 🚀 Deployment

- **Railway** — auto-deploys from GitHub `main` on every push
- **Procfile** at root: `web: gunicorn --chdir backend run:app ...`
- **requirements.txt** at root (Railway auto-detects Python)
- **runtime.txt** at root (pins Python version)
- **Custom domain** via CNAME → `erp.srivenkateshwara.in`
- **SSL** auto-provisioned by Railway (Let's Encrypt)

See [DEPLOYMENT.md](./DEPLOYMENT.md) for details.

## 🌐 Frontend Strategy

- **Server-side rendered** Jinja2 templates (no SPA)
- **Bootstrap 5** + custom inline styles
- **Pattern:** Every page extends `base.html`, includes `_print_common.html` for print styles
- **Print:** All 35+ reports use the shared partial for uniform 8mm margins + page size

## 📊 Data Flow Examples

### Payroll Processing
```
User creates MonthlyPayroll (status: draft)
       ↓
Process attendance → PayrollEntry per employee
       ↓
System calculates EPF, ESIC, PT, TDS, OT
       ↓
Admin clicks Finalize → status: 'finalized'
       ↓
Now can download: ECR, MC Template, Form B, payslips, reimbursement letter
```

### Filing Status Matrix
```
Admin opens /daily-mis/filing-matrix
       ↓
Load all active Establishments
       ↓
Load all finalized MonthlyPayrolls in date range
       ↓
Build matrix[est_id][month] = 'full' | 'partial' | 'none' | 'na'
       ↓
Render color-coded grid (green/yellow/red/grey)
```

## 🔮 Future Architecture Considerations

### If scaling beyond 10,000 users (currently 300):
- Add Redis for session caching
- Move Clerk → in-house auth (removes SaaS dep)
- Consider migrating Flask → Spring Boot (Java) for 3-4x performance
- Split into microservices (auth / payroll / reports)

### If adding mobile app:
- Refactor routes into `/api/v1/...` JSON endpoints
- Frontend becomes a separate React/Vue SPA
- Auth becomes API-key or OAuth-based

These are **deferred** decisions — current monolith handles 300 clients comfortably.
