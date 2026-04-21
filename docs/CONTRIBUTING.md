# Contributing

Thanks for your interest in improving Vaishnavi Consultant ERP! 🙏

## 🎯 Before You Start

This is a **proprietary codebase** for Vaishnavi Consultant. External contributions are accepted on a case-by-case basis.

## 🌿 Workflow

1. **Create a feature branch** off `main`:
   ```bash
   git checkout -b feature/short-descriptive-name
   ```

2. **Make small, focused commits**:
   ```bash
   git add specific-file.py
   git commit -m "Verb-first commit message in present tense"
   ```

3. **Test locally** before pushing:
   ```bash
   cd backend && python run_dev.py
   # Try the feature in a browser
   ```

4. **Push and open a PR**:
   ```bash
   git push origin feature/short-descriptive-name
   ```

5. **Maintainer reviews** → merges → Railway auto-deploys in 2-3 min.

## ✍️ Commit Message Guidelines

### Good examples
- `Add Manual Reimbursement letter feature`
- `Fix CSRF token missing on form submission`
- `Compact payslip template to fit 2 per A4 page`
- `Refactor backup module for ZIP compression`

### Bad examples
- `fix bug` (too vague)
- `updated stuff` (meaningless)
- `WIP` (merge-blocking but uninformative)

### Format
- First line: imperative verb + what changed (under 70 chars)
- Blank line
- Body: WHY the change was made, any gotchas

Example:
```
Add weekly backup reminder banner

Users often forget to back up their data. This adds a yellow
reminder on the /backup page if the last backup is more than
7 days old, with a one-click "Backup Now" button.

Also adds a global floating reminder that appears on any page
until dismissed, powered by the /api/storage-info endpoint.
```

## 🎨 Coding Standards

### Python
- **PEP 8** — use `black` or your IDE's auto-format
- **Type hints** welcomed but not required
- **Docstrings** on all route handlers + public functions
- **No print statements** in production code (use Flask's logger)
- **No commented-out code** — delete or use git history

### Jinja2
- 4-space indentation
- Compute in Python, display in Jinja (keep templates dumb)
- Use `url_for()` — never hardcode URLs
- Include `{% set print_size = '...' %}{% include '_print_common.html' %}` in every new report

### SQL / Models
- Always include the column in `_auto_migrate_columns()` when adding to an existing table
- Never drop columns via migrations (mark deprecated instead)
- Always add `nullable=True` on new columns (for safe rollout)
- Use `nullable=True` initially, add NOT NULL constraint later if needed

### Security
- EVERY form must have `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">`
- Use `user_establishments()` etc. not raw `Establishment.query` (for data isolation)
- Never log secrets (API keys, passwords, PII)
- Validate all user input — don't trust request.form

## ✅ PR Checklist

Before submitting a PR:

- [ ] Feature tested in localhost
- [ ] No commented-out code
- [ ] No `print()` debug statements left in
- [ ] CSRF token on all forms
- [ ] User-scoped queries (not raw)
- [ ] Related README updated if structure changed
- [ ] Screenshots attached for UI changes

## 🧪 Testing Changes

There's no automated test suite yet. Manual testing required:

### Smoke test checklist for ANY change:
1. `cd backend && python run_dev.py` — does it start without errors?
2. Navigate to `/` — does base.html render?
3. Navigate to `/backup` — does storage gauge appear in top-right?
4. Click a few sidebar links — any 500 errors?
5. Create a test establishment → add employee → process payroll → finalize
6. Open a report → print preview — check margins and page size

### For backend-only changes:
```bash
cd backend
python -c "from app import create_app; app = create_app(); print('OK')"
```

### For print/report changes:
- Open report in browser
- Ctrl+P → Print preview
- Check page size and margins
- Verify no sidebar/navbar visible

## 🎁 What Makes a Good Contribution

1. **Small, focused** — one feature/fix per PR
2. **Well-tested** locally before pushing
3. **Documented** — if it's a new concept, add a note to README or DEVELOPER-GUIDE
4. **Reversible** — can be rolled back without data loss
5. **Respects conventions** — follows existing patterns in the codebase

## 🚫 What to Avoid

- Large refactors without discussion first
- Adding npm/node dependencies (frontend is server-rendered)
- Hard-coding business values (use env vars or config)
- Direct DB mutations without `create_restore_point()` safety
- Breaking existing print formats (they're used for government filings)

## 💬 Questions?

Open a GitHub issue with the "question" label, or contact the maintainer directly.

Happy coding! 🚀
