# Deployment Guide

## 🚀 Current Deployment

| Aspect | Value |
|--------|-------|
| **Provider** | [Railway](https://railway.app) |
| **Live URL** | https://erp.srivenkateshwara.in |
| **Auto-deploy from** | GitHub `main` branch |
| **Python version** | 3.11 (pinned in `runtime.txt`) |
| **WSGI server** | Gunicorn (2 workers, 120s timeout) |
| **Database** | PostgreSQL (Railway managed) |

---

## 🔁 Deployment Flow

```
Developer pushes to main
         ↓
GitHub webhook → Railway
         ↓
Railway reads Procfile at repo root
         ↓
Railway installs from requirements.txt
         ↓
Railway runs: gunicorn --chdir backend run:app ...
         ↓
Gunicorn changes dir to backend/
         ↓
Imports run:app → creates Flask app
         ↓
Flask app factory runs:
  - db.create_all()
  - _auto_migrate_columns()
  - Register all blueprints
         ↓
App is live at erp.srivenkateshwara.in
```

## 📂 Files That Matter for Deployment

| File | Location | Purpose |
|------|:---:|---------|
| `Procfile` | root | Tells Railway how to start: `web: gunicorn --chdir backend run:app ...` |
| `requirements.txt` | root | Python packages — Railway auto-detects and installs |
| `runtime.txt` | root | Pins Python version (`python-3.11.x`) |
| `.env` (local only) | root | Secrets, NOT committed to git |
| `run.py` | `backend/` | Entry point — `from app import create_app; app = create_app()` |
| `app/__init__.py` | `backend/app/` | Flask factory + auto-migrations |

## 🌍 Environment Variables

Set these in **Railway → Service → Variables** tab:

| Variable | Required | Example |
|----------|:---:|---------|
| `DATABASE_URL` | ✅ | `postgresql://...` (Railway auto-provides when Postgres plugin is added) |
| `SECRET_KEY` | ✅ | Random 32+ char string |
| `CLERK_SECRET_KEY` | ✅ | `sk_live_...` from Clerk dashboard |
| `CLERK_PUBLISHABLE_KEY` | ✅ | `pk_live_...` from Clerk dashboard |
| `ADMIN_EMAILS` | ✅ | `owner@vaishnavi.com,admin@...` (comma-sep) |
| `DB_STORAGE_LIMIT_MB` | ⭕ | `500` (for storage gauge) |

## 🌐 Custom Domain

- Configured in Railway: `erp.srivenkateshwara.in` → CNAME to Railway default URL
- SSL auto-provisioned by Railway (Let's Encrypt)
- No manual cert renewal needed

---

## 🆕 Deploying a Change

### For most changes:
```bash
git add .
git commit -m "Descriptive message"
git push origin main
```

That's it. Railway detects the push and redeploys in **2-3 minutes**.

### Watch deployment:
1. Go to [railway.app](https://railway.app) → your project → Deployments tab
2. Click latest deployment → View logs
3. Look for "Listening at: http://0.0.0.0:..." → deploy succeeded
4. Look for errors during pip install or app startup → investigate

---

## 🔄 Database Migrations

Your app uses **auto-migrations** — no Alembic/Flyway needed.

### Adding a new column (safe, automatic)

1. In model file (e.g. `backend/app/models/payroll.py`):
   ```python
   class PayrollConfig(db.Model):
       ...
       new_field = db.Column(db.String(50), nullable=True)
   ```

2. In `backend/app/__init__.py` (`_auto_migrate_columns` list):
   ```python
   migrations = [
       ...
       ('payroll_configs', 'new_field', 'VARCHAR(50)'),
   ]
   ```

3. Push → Railway redeploys → auto-migration runs on startup → column added.

### For complex migrations (data reshape, column renames):
- Write one-time SQL migration script
- Run manually via Railway's PostgreSQL shell:
  ```bash
  railway connect postgres
  \i migration.sql
  ```

---

## 🗄️ Backup & Restore

### Automatic Backup (UI)
- Users trigger from `/backup` page
- Uses `pg_dump --no-owner --no-acl`
- ZIP-compressed
- Stored in `data/backups/<user_id>/`

⚠️ **Important:** Railway's default filesystem is **ephemeral**. Backups are lost on redeploy unless you attach a **Volume**.

### Persistent Backup Storage (Recommended)
Add a Railway Volume:
1. Railway → Service → Volumes → Add Volume
2. Mount at `/app/data` (or your preferred path)
3. Volume persists across deploys

### Manual Backup (Safer)
Download via UI → keep on your local computer.

Or via Railway CLI:
```bash
railway run pg_dump $DATABASE_URL > local_backup.sql
```

### Restore
- Via UI: Click Restore on any backup
- Creates restore point first (safety net)
- Replaces entire DB

### Disaster Recovery
- Download ZIP backup from /backup page
- Keep copies on local machine / cloud storage
- If Railway data is lost: Import ZIP back via /backup → click Restore

---

## 🔍 Monitoring & Logs

### Railway Logs
- Real-time: Deployments tab → select deployment → View logs
- Historical: Same place, previous deployments

### What to look for
- `pg_dump` errors → backup problems
- `5xx` errors → app bugs
- Slow queries → DB tuning needed
- OOM kills → upgrade plan

### Flask-level logging
Logs go to stdout via `print()` or Flask's logger. Railway captures all stdout.

---

## 🛠️ Troubleshooting Production

### "Application Error" / 500 page
1. Check Railway logs
2. Most common: env variable missing (`DATABASE_URL`, `SECRET_KEY`, etc.)
3. Second most common: newly added Python package not in `requirements.txt`

### Site extremely slow
1. Check DB connections (should be ≤15)
2. Check a specific slow endpoint
3. Railway metrics → CPU/memory

### Storage gauge shows 90%+
1. Large backups in `data/backups/` (auto-cleanup should handle)
2. Big database → consider archiving old payrolls
3. Upgrade Railway plan for more storage

### Deploy fails
1. Check requirements.txt syntax (UTF-8, no BOM, no spaces between letters)
2. Check Procfile syntax
3. Python version in runtime.txt available on Railway?

---

## 🔐 Security Notes

- `.env` NEVER committed to git (`.gitignore` protects it)
- All secrets live in Railway Variables
- HTTPS enforced by Railway (no http → https redirect needed in app)
- Clerk handles auth — no passwords stored locally
- CSRF protection on every form (Flask-WTF)
- Admin/user role enforced at both route and template level

---

## 📦 Alternative: Dockerfile Deployment

If Railway's nixpacks doesn't work for some dependency, add a Dockerfile at repo root:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080
CMD ["gunicorn", "--chdir", "backend", "run:app", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120"]
```

Railway will auto-detect and use the Dockerfile.

---

## 🚧 Scaling

Current setup handles ~300 concurrent users comfortably. If you exceed this:

### Vertical scale
- Railway → upgrade plan (more CPU/RAM)
- Increase gunicorn workers in Procfile: `--workers 4`

### Horizontal scale
- Run multiple Railway services behind Railway's load balancer
- Requires: session cookies use secret-key signing (already done)
- May need: move uploads to object storage (S3) — currently filesystem-based

### Database
- Currently PostgreSQL single-node on Railway
- For 10k+ users: read replicas, connection pooler (PgBouncer)

See [ARCHITECTURE.md](./ARCHITECTURE.md) for long-term scaling considerations.
