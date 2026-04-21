# Frontend — Jinja2 Templates + Static Assets

All UI code lives here. The backend (`../backend/app/`) uses Flask's template engine (Jinja2) to render these templates with data.

---

## 📂 Folder Structure

```
frontend/
├── templates/              Jinja2 HTML templates
│   ├── base.html              Main layout (sidebar, navbar, storage gauge)
│   ├── _print_common.html     ⭐ Shared print styles (@page rules)
│   │
│   ├── accounts/              Ledger, vouchers, trial balance, P&L, etc.
│   ├── bonus/                 Bonus Form C, statement, register
│   ├── daily_mis/             Task entries, filing matrix, compliance tracker
│   ├── employees/             Employee list, add/edit, bulk import
│   ├── enrollment/            UAN/ESIC IP tracker
│   ├── establishment/         Client list, dashboard, add/edit
│   ├── manual_reimbursement/  Manual letters (home, form, letter)
│   ├── payroll/               Payroll list, config, process, salary heads
│   ├── reports/               Payslips, Form B/D, ECR, MC, reimbursement
│   └── backup.html            DB backup UI
│
└── static/                 Static assets served by Flask
    ├── css/                   Stylesheets (currently scattered inline mostly)
    ├── js/                    JavaScript files
    └── images/                Logos, icons, screenshots
```

---

## 🎨 Design System

### Colors (used throughout)

| Purpose | Color | Usage |
|---------|:---:|-------|
| Primary (Indigo) | `#4f46e5` | Action buttons, links |
| Secondary (Purple) | `#7c3aed` | Highlights, badges |
| Success (Green) | `#16a34a` | Received, compliant |
| Warning (Amber) | `#f59e0b` | Pending, reminders |
| Danger (Red) | `#dc2626` | Errors, dues, delete |
| Brand Navy | `#1e3a8a` | Letterheads, reports |
| Text Dark | `#1e293b` | Main headings |
| Text Medium | `#475569` | Body text |
| Text Light | `#94a3b8` | Meta/secondary text |
| Bg Light | `#f8fafc` | Card backgrounds |
| Border | `#e2e8f0` | Dividers |

### Typography
- **Primary font:** System default (Helvetica/Arial stack via Bootstrap)
- **Report/Letter font:** `Georgia, Times New Roman, serif` (letters only)
- **Monospace:** `Consolas, Courier New, monospace` (numbers in tables)

### Spacing
- Consistent **8mm print margin** via `_print_common.html` across ALL reports

---

## 🖨️ Print System

### Shared Partial: `_print_common.html`

⭐ **Key concept:** All 35+ reports use one shared partial for print styles. This means:
- One fix applies to **all reports** at once
- Page size (A4/Legal, portrait/landscape) is set via a variable

### Usage in any report template:
```jinja
{% set print_size = 'a4-landscape' %}
{% include '_print_common.html' %}
```

### Supported sizes
| Value | Paper | Orientation | Used by |
|-------|-------|-------------|---------|
| `a4-portrait` | A4 | Portrait | Payslips, letters |
| `a4-landscape` | A4 | Landscape | Accounts reports, MIS |
| `legal-portrait` | Legal | Portrait | (not used currently) |
| `legal-landscape` | Legal | Landscape | Form B, D, Bonus, Salary Register |

### What the partial does
1. Sets `@page { size: …; margin: 8mm; }` for the printer
2. Hides: `.sidebar`, `.top-navbar`, `.no-print`, `.print-bar`, `#globalBackupReminder`
3. Removes shadows, borders, rounded corners from `.page`, `.cs-page`, `.fm-page`, etc.
4. Resets `.main-content` margin/padding to zero for full-page printing
5. Applies table page-break rules (`thead` repeats on every page)

---

## 📄 Template Layout Inheritance

Most pages extend `base.html`:

```jinja
{% extends "base.html" %}
{% block title %}Page Title{% endblock %}
{% block page_header %}Page Header{% endblock %}

{% block content %}
{% set print_size = 'a4-landscape' %}
{% include '_print_common.html' %}

<style>
  /* page-specific styles */
</style>

<!-- page content -->
{% endblock %}
```

Some reports are **standalone HTML** (not extending base) — these are printable letters opened in a new tab:
- `reports/reimbursement.html`
- `reports/reimbursement_multi.html`
- `manual_reimbursement/letter.html`

Standalone templates include `_print_common.html` inside `<head>` instead of `{% block content %}`.

---

## 🧩 Future: Component Library (Planned)

A planned Level-2 enhancement is to extract repeated UI patterns into Jinja macros (Shadcn-style):

```
frontend/templates/components/    (future)
├── buttons.html          Primary/danger/icon buttons
├── cards.html            Stat cards, info cards
├── tables.html           Data table with sort/hover
├── forms.html            Form section, inputs, selects
├── modals.html           Confirm dialog, info modal
├── badges.html           ADMIN, USER, status badges
├── hero_summary.html     Gradient banner + stat cards
├── filter_bar.html       From/To + quick presets
└── print_bar.html        Blue print/close bar
```

Usage:
```jinja
{% from 'components/buttons.html' import primary_button %}
{{ primary_button('Save', url=url_for('item.save'), icon='save') }}
```

See [`../docs/DEVELOPER-GUIDE.md`](../docs/DEVELOPER-GUIDE.md) for the component plan.

---

## 🌐 Static Assets

Anything in `frontend/static/` is served by Flask at `/static/<filename>`.

Flask auto-wires this via `static_folder='../../frontend/static'` in the app factory.

Reference in templates:
```jinja
<link rel="stylesheet" href="{{ url_for('static', filename='css/report_print.css') }}">
<img src="{{ url_for('static', filename='images/logo.png') }}">
```

---

## 🔨 Adding a New Page

1. Create `frontend/templates/<feature>/my_page.html`:
   ```jinja
   {% extends "base.html" %}
   {% block title %}My Page{% endblock %}
   {% block content %}
   {% set print_size = 'a4-landscape' %}
   {% include '_print_common.html' %}
   <h1>Hello</h1>
   {% endblock %}
   ```
2. In `backend/app/routes/<feature>.py`:
   ```python
   @feature_bp.route('/my-page')
   def my_page():
       return render_template('<feature>/my_page.html')
   ```
3. Done — visit `/my-page` in browser.

---

## 🎯 Current UI Highlights

| Page | Key Features |
|------|-------------|
| `base.html` | Sidebar, storage gauge (SVG donut), floating backup reminder |
| `backup.html` | Reminder banner, import form, ZIP/SQL badges |
| `accounts/client_statement.html` | FY/Range toggle, summary hero, certification footer |
| `daily_mis/filing_matrix.html` | 300-client × 12-month grid, color-coded cells |
| `manual_reimbursement/letter.html` | Professional A4 letter, auto-calc totals |
| `reports/payslip_elegant.html` | Premium payslip format, amount in words |

---

## 📖 Related Documentation

- [Backend README](../backend/README.md) — how the server renders these templates
- [Architecture](../docs/ARCHITECTURE.md) — overall design
- [Developer Guide](../docs/DEVELOPER-GUIDE.md) — onboarding
