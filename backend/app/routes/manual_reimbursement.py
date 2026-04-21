"""
Manual Reimbursement Routes
=============================
Create, edit, view, print, and delete manual reimbursement letters.
No dependency on finalized payroll — user can fill all fields manually.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import db
from app.models.manual_reimbursement import ManualReimbursement
from app.models.establishment import Establishment
from app.auth import login_required
from app.user_context import (current_user_id, current_user_name, is_admin,
                               user_establishments, set_owner)
from datetime import datetime, date


manual_reimb_bp = Blueprint('manual_reimb', __name__)


def _user_reimbs(query=None):
    """Filter manual reimbursements by user role."""
    if query is None:
        query = ManualReimbursement.query
    if is_admin():
        return query
    uid = current_user_id()
    if uid:
        return query.filter(ManualReimbursement.owner_id == uid)
    return query.filter(ManualReimbursement.owner_id == '__none__')


def _parse_float(val, default=0):
    try:
        return float(val) if val not in (None, '') else default
    except (ValueError, TypeError):
        return default


def _parse_int(val, default=0):
    try:
        return int(float(val)) if val not in (None, '') else default
    except (ValueError, TypeError):
        return default


# ═════════════════════════════════════════════
#  HOME — List all manual reimbursements (history)
# ═════════════════════════════════════════════
@manual_reimb_bp.route('/manual-reimbursement')
@login_required
def mr_home():
    entries = _user_reimbs().order_by(ManualReimbursement.letter_date.desc(),
                                       ManualReimbursement.id.desc()).all()

    # Summary stats
    total_count = len(entries)
    total_amount = sum(e.total_refund or 0 for e in entries)

    # Current FY entries
    today = date.today()
    fy_start_year = today.year if today.month >= 4 else today.year - 1
    fy_start = date(fy_start_year, 4, 1)
    fy_end = date(fy_start_year + 1, 3, 31)
    fy_entries = [e for e in entries if fy_start <= e.letter_date <= fy_end]
    fy_count = len(fy_entries)
    fy_amount = sum(e.total_refund or 0 for e in fy_entries)

    return render_template('manual_reimbursement/home.html',
                           entries=entries,
                           total_count=total_count,
                           total_amount=total_amount,
                           fy_count=fy_count,
                           fy_amount=fy_amount,
                           fy_label=f'{fy_start_year}-{fy_start_year + 1}')


# ═════════════════════════════════════════════
#  NEW — Create form
# ═════════════════════════════════════════════
@manual_reimb_bp.route('/manual-reimbursement/new', methods=['GET', 'POST'])
@login_required
def mr_new():
    if request.method == 'POST':
        return _save_entry()

    # Render form
    establishments = user_establishments().filter_by(is_active=True)\
        .order_by(Establishment.company_name).all()
    return render_template('manual_reimbursement/form.html',
                           entry=None,
                           establishments=establishments,
                           today=date.today())


# ═════════════════════════════════════════════
#  EDIT — Update existing entry
# ═════════════════════════════════════════════
@manual_reimb_bp.route('/manual-reimbursement/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required
def mr_edit(entry_id):
    entry = _user_reimbs().filter_by(id=entry_id).first_or_404()

    if request.method == 'POST':
        return _save_entry(entry)

    establishments = user_establishments().filter_by(is_active=True)\
        .order_by(Establishment.company_name).all()
    return render_template('manual_reimbursement/form.html',
                           entry=entry,
                           establishments=establishments,
                           today=date.today())


def _save_entry(entry=None):
    """Save or update a manual reimbursement entry."""
    is_new = entry is None
    if is_new:
        entry = ManualReimbursement()
        set_owner(entry)
        entry.staff_name = current_user_name()

    # Client source: existing establishment OR manual entry
    client_mode = request.form.get('client_mode', 'existing')
    if client_mode == 'existing':
        est_id = request.form.get('establishment_id')
        if not est_id:
            flash('Please select an establishment.', 'danger')
            return redirect(url_for('manual_reimb.mr_new') if is_new
                            else url_for('manual_reimb.mr_edit', entry_id=entry.id))
        entry.establishment_id = int(est_id)
        # Clear manual fields
        entry.manual_name = None
        entry.manual_address = None
        entry.manual_pf_code = None
        entry.manual_esic_code = None
    else:
        name = (request.form.get('manual_name') or '').strip()
        if not name:
            flash('Please enter the establishment name.', 'danger')
            return redirect(url_for('manual_reimb.mr_new') if is_new
                            else url_for('manual_reimb.mr_edit', entry_id=entry.id))
        entry.establishment_id = None
        entry.manual_name = name
        entry.manual_address = (request.form.get('manual_address') or '').strip()
        entry.manual_pf_code = (request.form.get('manual_pf_code') or '').strip()
        entry.manual_esic_code = (request.form.get('manual_esic_code') or '').strip()

    # Letter meta
    date_str = request.form.get('letter_date')
    try:
        entry.letter_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    except ValueError:
        entry.letter_date = date.today()
    entry.ref_no = (request.form.get('ref_no') or '').strip() or None
    entry.period_label = (request.form.get('period_label') or '').strip() or None

    # EPF
    entry.epf_count = _parse_int(request.form.get('epf_count'))
    entry.epf_wages = _parse_float(request.form.get('epf_wages'))
    entry.epf_ac01 = _parse_float(request.form.get('epf_ac01'))
    entry.epf_eps = _parse_float(request.form.get('epf_eps'))
    entry.epf_edli = _parse_float(request.form.get('epf_edli'))
    entry.epf_admin = _parse_float(request.form.get('epf_admin'))

    # ESIC
    entry.esic_count = _parse_int(request.form.get('esic_count'))
    entry.esic_wages = _parse_float(request.form.get('esic_wages'))
    entry.esic_employer = _parse_float(request.form.get('esic_employer'))

    entry.remarks = (request.form.get('remarks') or '').strip() or None

    # Auto-compute totals
    entry.recalculate_totals()

    if is_new:
        db.session.add(entry)
    db.session.commit()

    flash(f'Manual reimbursement letter {"created" if is_new else "updated"} successfully.', 'success')

    # After save, redirect based on user action
    action = request.form.get('action', 'save')
    if action == 'save_view':
        return redirect(url_for('manual_reimb.mr_view', entry_id=entry.id))
    return redirect(url_for('manual_reimb.mr_home'))


# ═════════════════════════════════════════════
#  VIEW — Professional letter (print/download)
# ═════════════════════════════════════════════
@manual_reimb_bp.route('/manual-reimbursement/<int:entry_id>/view')
@login_required
def mr_view(entry_id):
    entry = _user_reimbs().filter_by(id=entry_id).first_or_404()
    return render_template('manual_reimbursement/letter.html', entry=entry)


# ═════════════════════════════════════════════
#  DELETE
# ═════════════════════════════════════════════
@manual_reimb_bp.route('/manual-reimbursement/<int:entry_id>/delete', methods=['POST'])
@login_required
def mr_delete(entry_id):
    entry = _user_reimbs().filter_by(id=entry_id).first_or_404()
    db.session.delete(entry)
    db.session.commit()
    flash('Manual reimbursement letter deleted.', 'success')
    return redirect(url_for('manual_reimb.mr_home'))
