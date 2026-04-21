# Vaishnavi Consultant ERP

> A cloud-based payroll and compliance management system serving **300+ client establishments** for EPF, ESIC, and payroll compliance. Built for [Vaishnavi Consultant](https://erp.srivenkateshwara.in).

[![Live](https://img.shields.io/badge/live-erp.srivenkateshwara.in-success)](https://erp.srivenkateshwara.in)
[![Deployed on Railway](https://img.shields.io/badge/deployed-Railway-blueviolet)](https://railway.app)
[![Stack](https://img.shields.io/badge/stack-Flask%20%2B%20PostgreSQL-blue)]()

---

## 📂 Repository Structure

This project is organised into three top-level folders for clear separation of concerns:

```
vaishnavi-consultant-erp/
├── backend/          ⭐ All Python / Flask server code
├── frontend/         ⭐ All UI templates and static assets
├── docs/             ⭐ Architecture, deployment, developer guides
├── data/             Runtime data (backups, uploads)
│
├── Procfile          Railway deployment entry point
├── requirements.txt  Python dependencies (Railway auto-detects)
├── runtime.txt       Python version pin
├── .env.example      Environment variable template
└── README.md         (this file)
```

### 🗂️ Folder Purpose

| Folder | Contents | Read More |
|--------|----------|-----------|
| [`backend/`](./backend/README.md) | Flask app, models, routes, services | [backend/README.md](./backend/README.md) |
| [`frontend/`](./frontend/README.md) | Jinja2 templates, CSS, JS, images | [frontend/README.md](./frontend/README.md) |
| [`docs/`](./docs/) | Architecture, deployment, API docs | [docs/](./docs/) |
| [`data/`](./data/) | Runtime data (backups, uploads) | — |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 14+
- `pg_dump` and `psql` binaries (for backup/restore)

### Local Development

```bash
# 1. Clone
git clone https://github.com/bagathsingh59-sudo/erp-vaishnavi-consultant.git
cd erp-vaishnavi-consultant

# 2. Set up Python environment
python -m venv venv
source venv/bin/activate      # macOS/Linux
venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env → set DATABASE_URL, CLERK_* keys, SECRET_KEY

# 5. Run
cd backend
python run_dev.py
# Opens → http://localhost:5000
```

### Production (Railway)
Railway auto-deploys from the `main` branch on every push.
- **Live URL:** https://erp.srivenkateshwara.in
- **Procfile** at root tells Railway how to start the server.
- **Auto-migrations** run on startup (see `backend/app/__init__.py`).

See [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md) for full deployment guide.

---

## ✨ Main Features

| Feature | Description |
|---------|-------------|
| **Establishment Management** | Multi-client support with parent-child (sub-unit) hierarchy |
| **Employee Management** | Bulk import, KYC tracking, nominee management, transfer history |
| **Payroll Processing** | Monthly payroll with EPF, ESIC, PT, TDS, OT calculations |
| **Statutory Reports** | EPF ECR, ESIC MC Template, Form B, Form D, Annual returns |
| **Accounts Module** | Tally-style vouchers, ledger, trial balance, P&L, balance sheet |
| **Daily MIS** | Task tracking for staff, filing status matrix (admin-only) |
| **Compliance Tracker** | EPF/ESIC filing status per client per month |
| **UAN / ESIC IP Tracker** | Track enrollment status of all employees |
| **Manual Reimbursement** | Generate letters without payroll dependency |
| **Database Backup** | One-click ZIP-compressed PostgreSQL backup + import |
| **Filing Status Matrix** | Strategic admin view — 300+ clients vs months grid |

---

## 🛠️ Tech Stack

### Backend
- **Python 3.11** + **Flask 3**
- **SQLAlchemy 2** ORM + **Flask-SQLAlchemy**
- **Flask-WTF** for CSRF protection
- **Gunicorn** WSGI server
- **xhtml2pdf**, **xlwt**, **openpyxl** for report generation

### Frontend
- **Jinja2** server-side templates
- **Bootstrap 5** + custom CSS
- **Bootstrap Icons** (SVG icon set)
- Vanilla JavaScript (no framework)

### Database
- **PostgreSQL 14** (hosted on Railway)
- Auto-migrations on startup

### Authentication
- **Clerk** (SaaS) — JWT-based, supports OAuth, magic links, 2FA

### Deployment
- **Railway** — auto-deploy from GitHub `main`
- **Custom domain:** erp.srivenkateshwara.in
- **SSL** via Let's Encrypt (auto)

---

## 📚 Documentation

All documentation lives in [`docs/`](./docs/):

| Document | Purpose |
|----------|---------|
| [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) | System design, data flow, module interactions |
| [`docs/DEVELOPER-GUIDE.md`](./docs/DEVELOPER-GUIDE.md) | Getting started for new contributors |
| [`docs/API-REFERENCE.md`](./docs/API-REFERENCE.md) | Route catalogue with input/output |
| [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md) | Railway deployment and operations |
| [`docs/CONTRIBUTING.md`](./docs/CONTRIBUTING.md) | How to contribute, coding standards |
| [`docs/MIND_MAP.md`](./docs/MIND_MAP.md) | Feature brainstorm and roadmap |
| [`docs/SCHEMA_LOG.md`](./docs/SCHEMA_LOG.md) | Database schema change history |

---

## 🔒 Security

- **CSRF protection** on every form via Flask-WTF
- **User-scoped data** — each user only sees own establishments/data
- **Admin vs User** role separation
- **Row-level security** via `owner_id` filtering
- **HTTPS** enforced in production
- **Database backups** — ZIP-compressed, user-segregated
- **7-day weekly backup reminder**

---

## 🤝 Contributing

See [`docs/CONTRIBUTING.md`](./docs/CONTRIBUTING.md) for full guidelines.

Quick summary:
1. Fork → branch → make changes
2. Keep changes small and focused
3. Update relevant README if structure changes
4. Test on localhost before pushing

---

## 📬 Support

- **Issues:** Use GitHub Issues
- **Live site:** https://erp.srivenkateshwara.in
- **Repo:** https://github.com/bagathsingh59-sudo/erp-vaishnavi-consultant

---

## 📄 License

Proprietary — Vaishnavi Consultant. All rights reserved.
