# Developer Guide

Welcome! This guide helps new developers get productive quickly on the Vaishnavi Consultant ERP codebase.

## 🎯 Who This Is For

- Python / Flask developers joining the project
- Folks maintaining or extending existing features
- Anyone doing a code review

---

## 🚀 Local Setup (15 minutes)

### 1. Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.11+ | `python --version` |
| PostgreSQL | 14+ | `psql --version` |
| git | any | `git --version` |
| pg_dump | 14+ | `pg_dump --version` |

### 2. Clone & Install

```bash
git clone https://github.com/bagathsingh59-sudo/erp-vaishnavi-consultant.git
cd erp-vaishnavi-consultant
python -m venv venv
source venv/bin/activate       # macOS/Linux
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

### 3. Configure .env

```bash
cp .env.example .env
```

Edit `.env`:
```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/vaishnavi_dev
SECRET_KEY=your-dev-secret
CLERK_SECRET_KEY=sk_test_xxx
CLERK_PUBLISHABLE_KEY=pk_test_xxx
ADMIN_EMAILS=your.email@example.com
DB_STORAGE_LIMIT_MB=500
```

### 4. Create Local Database

```bash
createdb vaishnavi_dev
```

Or via psql:
```sql
CREATE DATABASE vaishnavi_dev;
```

### 5. Run

```bash
cd backend
python run_dev.py
```

Visit → http://localhost:5000

On first run, `create_all()` creates all tables + `_auto_migrate_columns()` adds columns.

---

## 📂 Where Things Live

| I want to… | Look in… |
|------------|----------|
| Add a new URL route | `backend/app/routes/<feature>.py` |
| Add a DB table | `backend/app/models/<feature>.py` |
| Edit a page's HTML | `frontend/templates/<feature>/page.html` |
| Add CSS/JS | `frontend/static/` |
| Change print margins | `frontend/templates/_print_common.html` |
| Add a sidebar link | `frontend/templates/base.html` |
| Configure Flask | `backend/app/__init__.py` |
| Add a env variable | `.env.example` + use `os.getenv()` |

---

## 🧑‍🍳 Cooking Recipes (Common Tasks)

### Recipe 1: Add a new page

```python
# backend/app/routes/my_feature.py
from flask import Blueprint, render_template
from app.auth import login_required

my_bp = Blueprint('my_feature', __name__)

@my_bp.route('/hello')
@login_required
def hello():
    return render_template('my_feature/hello.html', name='World')
```

```jinja
{# frontend/templates/my_feature/hello.html #}
{% extends "base.html" %}
{% block content %}
<h1>Hello, {{ name }}!</h1>
{% endblock %}
```

Register in `backend/app/__init__.py`:
```python
from app.routes.my_feature import my_bp
app.register_blueprint(my_bp)
```

---

### Recipe 2: Add a new DB column

```python
# backend/app/models/payroll.py
class PayrollConfig(db.Model):
    ...
    new_field = db.Column(db.String(50), nullable=True)
```

```python
# backend/app/__init__.py → _auto_migrate_columns list
migrations = [
    ...
    ('payroll_configs', 'new_field', 'VARCHAR(50)'),
]
```

Next restart → column auto-added to DB. No Alembic needed.

---

### Recipe 3: Add an admin-only feature

```python
from app.user_context import is_admin

@my_bp.route('/admin-only')
@login_required
def admin_only():
    if not is_admin():
        flash('Admins only', 'warning')
        return redirect(url_for('home'))
    # ... admin logic
```

Also hide the sidebar link for non-admins:
```jinja
{% if clerk_user and clerk_user.is_admin %}
<a href="{{ url_for('my_bp.admin_only') }}">Admin Page</a>
{% endif %}
```

---

### Recipe 4: Scope data by user

```python
from app.user_context import user_establishments, current_user_id

@my_bp.route('/my-data')
@login_required
def my_data():
    # Admin sees all; user sees only their own
    items = user_establishments(Establishment.query).all()
    return render_template('my_feature/list.html', items=items)
```

---

### Recipe 5: Add a report with print support

```jinja
{# frontend/templates/reports/my_report.html #}
{% extends "base.html" %}
{% block content %}
{% set print_size = 'a4-landscape' %}
{% include '_print_common.html' %}

<style>
  /* page-specific CSS */
</style>

<div class="no-print">
    <button onclick="window.print()">Print</button>
</div>

<div class="report-content">
    ...
</div>
{% endblock %}
```

The `_print_common.html` handles page size, margins, and hides sidebar on print automatically.

---

### Recipe 6: Add CSRF to a form

```jinja
<form method="POST" action="{{ url_for('my_bp.save') }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <!-- your fields -->
    <button type="submit">Save</button>
</form>
```

Missing `csrf_token` → form submission fails with "Your form session expired".

---

## 🧪 Testing Strategy

Currently no automated tests. For new features, we recommend:

```bash
pip install pytest pytest-flask pytest-mock
```

Create tests in `backend/tests/`:
```python
# backend/tests/test_payroll.py
def test_epf_calculation():
    assert calculate_epf(15000) == 1800
```

Run: `pytest backend/tests/`

---

## 🐛 Debugging Tips

### "Template not found"
→ Check the path. Templates live in `frontend/templates/` now, not `app/templates/`.
→ Flask is configured with `template_folder='../../frontend/templates'` in `backend/app/__init__.py`.

### "Your form session expired"
→ Missing `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` in your form.

### "No module named xlwt/openpyxl/xhtml2pdf"
→ Missing from `requirements.txt` or virtual env not activated. Run `pip install -r requirements.txt`.

### "DATABASE_URL environment variable is required"
→ `.env` not loaded. Check `.env` file exists at repo root with `DATABASE_URL=...`.

### Tables missing columns after adding new field
→ Did you add to `_auto_migrate_columns` list in `app/__init__.py`?

---

## 🎨 Coding Standards

### Python
- Follow PEP 8
- Use descriptive function names (`calculate_epf_wage` not `calc`)
- Docstrings on routes explaining what they do
- Type hints welcome but not enforced
- Use `f-strings` not `.format()` or `%`

### Jinja2
- 4-space indentation
- Prefer `{% set x = value %}` over inline expressions
- Keep template logic minimal — compute in Python, display in Jinja
- Use `url_for()` not hardcoded URLs

### CSS
- Prefer inline `<style>` within templates for page-specific styles (current pattern)
- Shared styles → `_print_common.html` or future `components/`
- Use CSS variables for brand colors (`#4f46e5`, `#1e3a8a`, etc.)

### Git
- Descriptive commit messages
- Keep commits small and focused
- Don't commit `.env`, `__pycache__/`, `data/backups/`

---

## 🏗️ Architecture Patterns

### Application Factory
Flask app is built via `create_app()` function. This allows:
- Multiple configurations (dev/prod/test)
- Clean blueprint registration
- Testing with different app instances

### Blueprint per Feature
Every major feature gets its own blueprint in `app/routes/`. Don't add routes to existing blueprints unless they truly belong together.

### Role-Scoped Queries
Always use `user_establishments()`, `user_vouchers()` etc. from `user_context.py` instead of raw queries. This ensures data isolation automatically.

### No ORM in Routes
Keep complex business logic OUT of route handlers. Put it in:
- Model methods (if specific to a model)
- Separate service modules (if shared across routes)
- Future: `app/services/` folder

---

## 📚 Further Reading

- [Flask docs](https://flask.palletsprojects.com/)
- [SQLAlchemy ORM tutorial](https://docs.sqlalchemy.org/en/20/orm/quickstart.html)
- [Jinja2 templates](https://jinja.palletsprojects.com/)
- [Bootstrap 5 docs](https://getbootstrap.com/docs/5.0/getting-started/introduction/)
- [Our architecture](./ARCHITECTURE.md)
- [Our API reference](./API-REFERENCE.md)
- [Our deployment guide](./DEPLOYMENT.md)

---

## 🆘 Getting Help

- **Bug?** Open a GitHub issue
- **Question?** Check existing docs first, then ask the maintainer
- **Want to contribute?** See [CONTRIBUTING.md](./CONTRIBUTING.md)
