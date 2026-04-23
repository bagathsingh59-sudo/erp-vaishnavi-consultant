"""
Daily MIS Routes
=================
Tracks all daily tasks performed by staff. Payment-related tasks
auto-create vouchers in the Accounts module.

Access: Both Admin and Regular Users (staff)

Admin Features:
- Admin Dashboard with pending overview, staff performance
- Task assignment (create & assign tasks to staff)
- Admin remarks on any entry
- Quick status update from dashboard
- Compliance tracker view
- Staff-wise pending view
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models.daily_mis import (DailyMISEntry, MIS_TASK_CATEGORIES,
                                   ALL_TASK_TYPES, PAYMENT_TASK_TYPES)
from app.models.accounts import AccountGroup, AccountHead, Voucher, VoucherEntry
from app.models.establishment import Establishment
from app.models.app_user import AppUser
from app.auth import login_required
from app.user_context import (current_user_id, current_user_name, is_admin,
                               user_establishments, set_owner, log_activity,
                               verify_est_ownership)
from datetime import datetime, date
from sqlalchemy import func, or_, and_

daily_mis_bp = Blueprint('daily_mis', __name__)


# ─────────────────────────────────────────────
# Helper: Filter MIS entries by user role
# ─────────────────────────────────────────────
def _user_mis_entries(query=None):
    """Admin sees all MIS entries.
    Staff sees: own entries + entries assigned to them.
    """
    if query is None:
        query = DailyMISEntry.query
    if is_admin():
        return query
    uid = current_user_id()
    if uid:
        # Staff sees their own entries AND tasks assigned to them
        return query.filter(
            or_(DailyMISEntry.owner_id == uid,
                DailyMISEntry.assigned_to_id == uid)
        )
    return query.filter(DailyMISEntry.owner_id == '__none__')


def _get_staff_list():
    """Get list of active staff (non-admin users) for assignment dropdown."""
    users = AppUser.query.filter_by(is_active=True).order_by(AppUser.name).all()
    return users


# ─────────────────────────────────────────────
# Helper: Financial year (same logic as accounts)
# ─────────────────────────────────────────────
def _get_fy():
    today = date.today()
    start_year = today.year if today.month >= 4 else today.year - 1
    start = date(start_year, 4, 1)
    end = date(start_year + 1, 3, 31)
    label = f'{start_year}-{start_year + 1}'
    return start, end, label


def _next_voucher_number(voucher_type, fy_start, fy_end):
    """Generate next voucher number: RV-001, PV-001, JV-001"""
    prefix_map = {'receipt': 'RV', 'payment': 'PV', 'journal': 'JV'}
    prefix = prefix_map.get(voucher_type, 'V')
    count = Voucher.query.filter(
        Voucher.voucher_type == voucher_type,
        Voucher.voucher_date >= fy_start,
        Voucher.voucher_date <= fy_end
    ).count()
    return f'{prefix}-{count + 1:03d}'


def _get_or_create_debtor(est):
    """Get or create Sundry Debtor account for an establishment"""
    existing = AccountHead.query.filter_by(establishment_id=est.id).first()
    if existing:
        return existing
    debtor_group = AccountGroup.query.filter_by(name='Sundry Debtors').first()
    if not debtor_group:
        return None
    acct = AccountHead(
        name=est.display_name,
        group_id=debtor_group.id,
        establishment_id=est.id,
        is_system=False
    )
    db.session.add(acct)
    db.session.flush()
    return acct


# ─────────────────────────────────────────────
# Voucher auto-creation for payment tasks
# ─────────────────────────────────────────────
def _create_receipt_voucher(entry, est, bank_account_id, task_type):
    """Create a Receipt Voucher when compliance amount or fee is received."""
    fy_start, fy_end, _ = _get_fy()
    if entry.task_date < fy_start or entry.task_date > fy_end:
        return None
    v_num = _next_voucher_number('receipt', fy_start, fy_end)
    debtor_acct = _get_or_create_debtor(est)
    if not debtor_acct:
        return None
    bank_acct = AccountHead.query.get(bank_account_id)
    if not bank_acct:
        return None

    client_name = est.display_name
    if task_type == 'Fee Received':
        narration = f'MIS: Professional Fee from {client_name}'
        income_acct = AccountHead.query.filter_by(name='Professional Fees').first()
    else:
        narration = f'MIS: Compliance payment from {client_name}'
        income_acct = None

    voucher = Voucher(
        voucher_type='receipt', voucher_number=v_num,
        voucher_date=entry.task_date, establishment_id=est.id,
        reference=entry.reference, narration=narration,
        total_amount=entry.amount, owner_id=current_user_id()
    )
    db.session.add(voucher)
    db.session.flush()

    db.session.add(VoucherEntry(
        voucher_id=voucher.id, account_id=bank_acct.id,
        entry_type='debit', amount=entry.amount,
        particulars=f'Received from {client_name}'
    ))

    if task_type == 'Fee Received' and income_acct:
        db.session.add(VoucherEntry(
            voucher_id=voucher.id, account_id=income_acct.id,
            entry_type='credit', amount=entry.amount,
            particulars=f'{client_name} — Professional Fee'
        ))
    else:
        db.session.add(VoucherEntry(
            voucher_id=voucher.id, account_id=debtor_acct.id,
            entry_type='credit', amount=entry.amount,
            particulars=f'{client_name} — Compliance Amount Received'
        ))

    log_activity('created', 'voucher', entity_id=voucher.id,
                 entity_name=f'{v_num} — {client_name} (MIS)',
                 details=f'Receipt Rs.{entry.amount:,.0f} via Daily MIS',
                 establishment_id=est.id)
    return voucher


def _create_payment_voucher(entry, est, bank_account_id):
    """Create a Payment Voucher when EPF/ESIC challan is paid."""
    fy_start, fy_end, _ = _get_fy()
    if entry.task_date < fy_start or entry.task_date > fy_end:
        return None
    v_num = _next_voucher_number('payment', fy_start, fy_end)
    bank_acct = AccountHead.query.get(bank_account_id)
    if not bank_acct:
        return None

    client_name = est.display_name if est else 'Unknown'
    epf_acct = AccountHead.query.filter_by(name='EPF Payable').first()
    esic_acct = AccountHead.query.filter_by(name='ESIC Payable').first()

    desc_lower = (entry.description or '').lower()
    if 'esic' in desc_lower and esic_acct:
        payable_acct = esic_acct
        label = 'ESIC Challan'
    elif epf_acct:
        payable_acct = epf_acct
        label = 'EPF Challan'
    else:
        return None

    voucher = Voucher(
        voucher_type='payment', voucher_number=v_num,
        voucher_date=entry.task_date,
        establishment_id=est.id if est else None,
        reference=entry.reference,
        narration=f'MIS: {label} Payment — {client_name}',
        total_amount=entry.amount, owner_id=current_user_id()
    )
    db.session.add(voucher)
    db.session.flush()

    db.session.add(VoucherEntry(
        voucher_id=voucher.id, account_id=payable_acct.id,
        entry_type='debit', amount=entry.amount,
        particulars=f'{client_name} — {label} Payment'
    ))
    db.session.add(VoucherEntry(
        voucher_id=voucher.id, account_id=bank_acct.id,
        entry_type='credit', amount=entry.amount,
        particulars=f'{label} Payment — {client_name}'
    ))

    log_activity('created', 'voucher', entity_id=voucher.id,
                 entity_name=f'{v_num} — {client_name} (MIS)',
                 details=f'Payment Rs.{entry.amount:,.0f} via Daily MIS',
                 establishment_id=est.id if est else None)
    return voucher


def _create_journal_voucher(entry, est, bank_account_id):
    """Create a Journal Voucher for refund/reversal."""
    fy_start, fy_end, _ = _get_fy()
    if entry.task_date < fy_start or entry.task_date > fy_end:
        return None
    v_num = _next_voucher_number('journal', fy_start, fy_end)
    bank_acct = AccountHead.query.get(bank_account_id)
    if not bank_acct:
        return None

    client_name = est.display_name if est else 'Unknown'
    debtor_acct = _get_or_create_debtor(est) if est else None
    if not debtor_acct:
        return None

    voucher = Voucher(
        voucher_type='journal', voucher_number=v_num,
        voucher_date=entry.task_date,
        establishment_id=est.id if est else None,
        reference=entry.reference,
        narration=f'MIS: Refund/Reversal — {client_name}',
        total_amount=entry.amount, owner_id=current_user_id()
    )
    db.session.add(voucher)
    db.session.flush()

    db.session.add(VoucherEntry(
        voucher_id=voucher.id, account_id=debtor_acct.id,
        entry_type='debit', amount=entry.amount,
        particulars=f'{client_name} — Refund/Reversal'
    ))
    db.session.add(VoucherEntry(
        voucher_id=voucher.id, account_id=bank_acct.id,
        entry_type='credit', amount=entry.amount,
        particulars=f'Refund to {client_name}'
    ))

    log_activity('created', 'voucher', entity_id=voucher.id,
                 entity_name=f'{v_num} — {client_name} (MIS)',
                 details=f'Journal Rs.{entry.amount:,.0f} via Daily MIS',
                 establishment_id=est.id if est else None)
    return voucher


# ═════════════════════════════════════════════
#  HOME — Smart Dashboard (Admin vs Staff view)
# ═════════════════════════════════════════════
@daily_mis_bp.route('/daily-mis')
@login_required
def mis_home():
    date_str = request.args.get('date', '')
    if date_str:
        try:
            view_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            view_date = date.today()
    else:
        view_date = date.today()

    today = date.today()
    admin_mode = is_admin()

    # Get entries for the selected date
    query = _user_mis_entries().filter(DailyMISEntry.task_date == view_date)
    entries = query.order_by(DailyMISEntry.created_at.desc()).all()

    # Summary stats
    total_tasks = len(entries)
    completed = sum(1 for e in entries if e.status == 'completed')
    pending = sum(1 for e in entries if e.status == 'pending')
    in_progress = sum(1 for e in entries if e.status == 'in_progress')

    # Category-wise breakdown
    category_counts = {}
    for e in entries:
        category_counts[e.category] = category_counts.get(e.category, 0) + 1

    # Payment summary
    payment_entries = [e for e in entries if e.category == 'Payment & Accounts' and e.amount]
    total_amount = sum(e.amount for e in payment_entries)

    # ── ADMIN-ONLY data ──
    staff_counts = {}
    overdue_entries = []
    all_pending = []
    assigned_pending = []

    if admin_mode:
        # Staff-wise breakdown for this date
        for e in entries:
            name = e.staff_name or 'Unknown'
            if name not in staff_counts:
                staff_counts[name] = {'total': 0, 'completed': 0, 'pending': 0, 'in_progress': 0}
            staff_counts[name]['total'] += 1
            staff_counts[name][e.status] = staff_counts[name].get(e.status, 0) + 1

        # ALL overdue tasks (across all dates, not just today)
        overdue_entries = DailyMISEntry.query.filter(
            DailyMISEntry.due_date < today,
            DailyMISEntry.status != 'completed'
        ).order_by(DailyMISEntry.due_date.asc()).all()

        # ALL pending tasks (across all dates)
        all_pending = DailyMISEntry.query.filter(
            DailyMISEntry.status.in_(['pending', 'in_progress'])
        ).order_by(DailyMISEntry.task_date.desc()).limit(50).all()

        # Admin-assigned tasks that are still pending
        assigned_pending = DailyMISEntry.query.filter(
            DailyMISEntry.is_assigned == True,
            DailyMISEntry.status != 'completed'
        ).order_by(DailyMISEntry.due_date.asc().nulls_last(),
                    DailyMISEntry.task_date.desc()).all()
    else:
        # STAFF: show tasks assigned to them
        uid = current_user_id()
        if uid:
            assigned_pending = DailyMISEntry.query.filter(
                DailyMISEntry.assigned_to_id == uid,
                DailyMISEntry.status != 'completed'
            ).order_by(DailyMISEntry.due_date.asc().nulls_last()).all()

    return render_template('daily_mis/home.html',
                           entries=entries,
                           view_date=view_date,
                           today=today,
                           total_tasks=total_tasks,
                           completed=completed,
                           pending=pending,
                           in_progress=in_progress,
                           category_counts=category_counts,
                           staff_counts=staff_counts,
                           payment_entries=payment_entries,
                           total_amount=total_amount,
                           overdue_entries=overdue_entries,
                           all_pending=all_pending,
                           assigned_pending=assigned_pending,
                           is_admin=admin_mode)


# ═════════════════════════════════════════════
#  ADD — New MIS Entry (self or assign to staff)
# ═════════════════════════════════════════════
@daily_mis_bp.route('/daily-mis/add', methods=['GET', 'POST'])
@login_required
def mis_add():
    if request.method == 'POST':
        return _save_mis_entry()

    establishments = user_establishments().filter_by(is_active=True) \
        .order_by(Establishment.company_name).all()
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    bank_accounts = bank_group.accounts if bank_group else []

    # Staff list for task assignment (admin only)
    staff_list = _get_staff_list() if is_admin() else []

    return render_template('daily_mis/entry_form.html',
                           entry=None,
                           categories=MIS_TASK_CATEGORIES,
                           establishments=establishments,
                           bank_accounts=bank_accounts,
                           staff_list=staff_list,
                           today=date.today(),
                           is_admin=is_admin())


# ═════════════════════════════════════════════
#  EDIT — Existing MIS Entry
# ═════════════════════════════════════════════
@daily_mis_bp.route('/daily-mis/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required
def mis_edit(entry_id):
    entry = DailyMISEntry.query.get_or_404(entry_id)

    # Ownership check: admin can edit all, staff can edit own + assigned
    uid = current_user_id()
    if not is_admin() and entry.owner_id != uid and entry.assigned_to_id != uid:
        flash('You can only edit your own entries or tasks assigned to you.', 'warning')
        return redirect(url_for('daily_mis.mis_home'))

    if request.method == 'POST':
        return _save_mis_entry(entry)

    establishments = user_establishments().filter_by(is_active=True) \
        .order_by(Establishment.company_name).all()
    bank_group = AccountGroup.query.filter_by(name='Bank Accounts').first()
    bank_accounts = bank_group.accounts if bank_group else []
    staff_list = _get_staff_list() if is_admin() else []

    return render_template('daily_mis/entry_form.html',
                           entry=entry,
                           categories=MIS_TASK_CATEGORIES,
                           establishments=establishments,
                           bank_accounts=bank_accounts,
                           staff_list=staff_list,
                           today=date.today(),
                           is_admin=is_admin())


# ═════════════════════════════════════════════
#  DELETE — Remove MIS Entry (Admin only)
# ═════════════════════════════════════════════
@daily_mis_bp.route('/daily-mis/<int:entry_id>/delete', methods=['POST'])
@login_required
def mis_delete(entry_id):
    entry = DailyMISEntry.query.get_or_404(entry_id)
    if not is_admin():
        flash('Only Admin can delete MIS entries.', 'warning')
        return redirect(url_for('daily_mis.mis_home'))

    if entry.voucher_id:
        voucher = Voucher.query.get(entry.voucher_id)
        if voucher:
            VoucherEntry.query.filter_by(voucher_id=voucher.id).delete()
            db.session.delete(voucher)

    task_info = f'{entry.task_type} — {entry.establishment_name}'
    log_activity('deleted', 'mis_entry', entity_id=entry.id,
                 entity_name=task_info,
                 details=f'Deleted MIS entry dated {entry.task_date}',
                 establishment_id=entry.establishment_id)
    db.session.delete(entry)
    db.session.commit()
    flash(f'MIS entry deleted: {task_info}', 'success')
    return redirect(url_for('daily_mis.mis_home'))


# ═════════════════════════════════════════════
#  QUICK STATUS UPDATE (AJAX — Admin + assigned staff)
# ═════════════════════════════════════════════
@daily_mis_bp.route('/daily-mis/<int:entry_id>/status', methods=['POST'])
@login_required
def mis_update_status(entry_id):
    entry = DailyMISEntry.query.get_or_404(entry_id)
    uid = current_user_id()

    # Admin can update any; staff can update own + assigned
    if not is_admin() and entry.owner_id != uid and entry.assigned_to_id != uid:
        return jsonify({'error': 'Not authorized'}), 403

    new_status = request.form.get('status', '').strip()
    if new_status not in ('completed', 'pending', 'in_progress'):
        return jsonify({'error': 'Invalid status'}), 400

    old_status = entry.status
    entry.status = new_status

    log_activity('updated', 'mis_entry', entity_id=entry.id,
                 entity_name=f'{entry.task_type} — {entry.establishment_name}',
                 details=f'Status: {old_status} → {new_status}',
                 establishment_id=entry.establishment_id)
    db.session.commit()

    # Return for AJAX or redirect
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'status': new_status,
                        'badge': entry.status_badge})
    flash(f'Status updated to {new_status}.', 'success')
    return redirect(request.referrer or url_for('daily_mis.mis_home'))


# ═════════════════════════════════════════════
#  ADMIN REMARKS (AJAX — Admin only)
# ═════════════════════════════════════════════
@daily_mis_bp.route('/daily-mis/<int:entry_id>/remark', methods=['POST'])
@login_required
def mis_add_remark(entry_id):
    if not is_admin():
        flash('Only Admin can add remarks.', 'warning')
        return redirect(url_for('daily_mis.mis_home'))

    entry = DailyMISEntry.query.get_or_404(entry_id)
    remark = request.form.get('admin_remarks', '').strip()

    entry.admin_remarks = remark
    entry.admin_remarks_by = current_user_name()
    entry.admin_remarks_at = datetime.utcnow()

    log_activity('updated', 'mis_entry', entity_id=entry.id,
                 entity_name=f'{entry.task_type} — {entry.establishment_name}',
                 details=f'Admin remark added: {remark[:100]}',
                 establishment_id=entry.establishment_id)
    db.session.commit()

    flash('Admin remark saved.', 'success')
    return redirect(request.referrer or url_for('daily_mis.mis_home'))


# ═════════════════════════════════════════════
#  REASSIGN TASK (Admin only)
# ═════════════════════════════════════════════
@daily_mis_bp.route('/daily-mis/<int:entry_id>/reassign', methods=['POST'])
@login_required
def mis_reassign(entry_id):
    if not is_admin():
        flash('Only Admin can reassign tasks.', 'warning')
        return redirect(url_for('daily_mis.mis_home'))

    entry = DailyMISEntry.query.get_or_404(entry_id)
    new_user_id = request.form.get('assign_to_id', '').strip()

    if new_user_id:
        user = AppUser.query.filter_by(clerk_user_id=new_user_id).first()
        if user:
            old_assignee = entry.assigned_to_name or entry.staff_name or 'Unassigned'
            entry.assigned_to_id = user.clerk_user_id
            entry.assigned_to_name = user.name or user.email
            entry.is_assigned = True

            log_activity('updated', 'mis_entry', entity_id=entry.id,
                         entity_name=f'{entry.task_type} — {entry.establishment_name}',
                         details=f'Reassigned: {old_assignee} → {user.name or user.email}',
                         establishment_id=entry.establishment_id)
            db.session.commit()
            flash(f'Task reassigned to {user.name or user.email}.', 'success')
    else:
        flash('Please select a staff member.', 'warning')

    return redirect(request.referrer or url_for('daily_mis.mis_home'))


# ═════════════════════════════════════════════
#  COMPLIANCE TRACKER (Admin view)
# ═════════════════════════════════════════════
@daily_mis_bp.route('/daily-mis/compliance')
@login_required
def mis_compliance():
    """Shows compliance amount received vs returns filed per establishment.
    This replaces the physical book tracking.
    """
    from_str = request.args.get('from_date', '')
    to_str = request.args.get('to_date', '')

    today = date.today()
    if not from_str:
        from_date = date(today.year, today.month, 1)
    else:
        try:
            from_date = datetime.strptime(from_str, '%Y-%m-%d').date()
        except ValueError:
            from_date = date(today.year, today.month, 1)
    if not to_str:
        to_date = today
    else:
        try:
            to_date = datetime.strptime(to_str, '%Y-%m-%d').date()
        except ValueError:
            to_date = today

    # Get all "Compliance Amount Received" entries in date range
    compliance_entries = _user_mis_entries().filter(
        DailyMISEntry.task_type == 'Compliance Amount Received',
        DailyMISEntry.task_date >= from_date,
        DailyMISEntry.task_date <= to_date
    ).order_by(DailyMISEntry.task_date.desc()).all()

    # For each compliance entry, check if returns are filed for that establishment
    tracker_data = []
    for ce in compliance_entries:
        est_id = ce.establishment_id
        if not est_id:
            continue

        # Check if EPF return filed for this est in the date range
        epf_filed = _user_mis_entries().filter(
            DailyMISEntry.task_type == 'EPF Return Filed',
            DailyMISEntry.establishment_id == est_id,
            DailyMISEntry.task_date >= from_date,
            DailyMISEntry.task_date <= to_date,
            DailyMISEntry.status == 'completed'
        ).first()

        esic_filed = _user_mis_entries().filter(
            DailyMISEntry.task_type == 'ESIC Return Filed',
            DailyMISEntry.establishment_id == est_id,
            DailyMISEntry.task_date >= from_date,
            DailyMISEntry.task_date <= to_date,
            DailyMISEntry.status == 'completed'
        ).first()

        challan_paid = _user_mis_entries().filter(
            DailyMISEntry.task_type == 'Challan Payment Done',
            DailyMISEntry.establishment_id == est_id,
            DailyMISEntry.task_date >= from_date,
            DailyMISEntry.task_date <= to_date,
            DailyMISEntry.status == 'completed'
        ).first()

        tracker_data.append({
            'entry': ce,
            'epf_filed': bool(epf_filed),
            'esic_filed': bool(esic_filed),
            'challan_paid': bool(challan_paid),
            'all_done': bool(epf_filed and esic_filed and challan_paid),
        })

    total_received = len(tracker_data)
    all_done = sum(1 for t in tracker_data if t['all_done'])
    pending_action = total_received - all_done

    return render_template('daily_mis/compliance.html',
                           tracker_data=tracker_data,
                           from_date=from_date,
                           to_date=to_date,
                           total_received=total_received,
                           all_done=all_done,
                           pending_action=pending_action,
                           is_admin=is_admin())


# ═════════════════════════════════════════════
#  FILING STATUS MATRIX — Client × Month Grid (ADMIN ONLY)
# ═════════════════════════════════════════════
@daily_mis_bp.route('/daily-mis/filing-matrix')
@login_required
def filing_matrix():
    """Filing Status Matrix — ADMIN-ONLY strategic view.
    Shows all establishments vs all wage months in selected range.
    Data source: MonthlyPayroll.status == 'finalized' (i.e., when admin
    finalizes payroll for a client-month, that month is considered filed).
    Each cell shows EPF and ESIC filing status (Full / Partial / None / N/A).
    """
    # ── ADMIN-ONLY access ──
    if not is_admin():
        flash('This report is available only to Admin users.', 'warning')
        return redirect(url_for('daily_mis.mis_home'))

    from app.models.establishment import Establishment
    from app.models.payroll import MonthlyPayroll
    from app.models.accounts import Voucher, VoucherEntry, AccountHead

    from app.utils.date_helpers import current_wage_month

    # ── Parse date range (month-level, YYYY-MM format) ──
    from_str = request.args.get('from', '')
    to_str = request.args.get('to', '')
    today = date.today()

    # Default range: start of current FY (Apr YYYY) → current WAGE month.
    # Rationale: contributions for the running calendar month can't be paid
    # yet, so the matrix should NOT include future / current-uncompleted
    # months. The last meaningful wage month is the previous calendar month.
    current_fy_start = today.year if today.month >= 4 else today.year - 1
    wage_y, wage_m = current_wage_month(today)
    default_from = date(current_fy_start, 4, 1)
    default_to = date(wage_y, wage_m, 1)

    # Safety: if wage month is before FY start (e.g., today is exactly Apr 1),
    # clamp "to" to match "from" so the range is at least 1 month.
    if default_to < default_from:
        default_to = default_from

    try:
        if from_str:
            parts = from_str.split('-')
            from_month = date(int(parts[0]), int(parts[1]), 1)
        else:
            from_month = default_from
    except (ValueError, IndexError):
        from_month = default_from

    try:
        if to_str:
            parts = to_str.split('-')
            to_month = date(int(parts[0]), int(parts[1]), 1)
        else:
            to_month = default_to
    except (ValueError, IndexError):
        to_month = default_to

    # Generate list of wage months from 'from' to 'to' inclusive
    wage_months = []
    cur = from_month
    while cur <= to_month:
        wage_months.append(cur)
        # Move to next month
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)

    # ── Get ALL active establishments (admin sees everything) ──
    establishments = Establishment.query.filter_by(is_active=True)\
        .order_by(Establishment.company_name).all()

    # ── Pre-fetch ALL finalized payrolls within the wage-month range ──
    if wage_months:
        year_month_pairs = [(wm.year, wm.month) for wm in wage_months]
        min_year = min(wm.year for wm in wage_months)
        max_year = max(wm.year for wm in wage_months)
    else:
        min_year = today.year
        max_year = today.year

    all_finalized = MonthlyPayroll.query.filter(
        MonthlyPayroll.status == 'finalized',
        MonthlyPayroll.year >= min_year,
        MonthlyPayroll.year <= max_year
    ).all()

    # Index finalized payrolls by (est_id, year, month)
    # Store tuple: (is_filed, is_nil) — NIL months still count as filed but shown distinctly
    finalized_index = {}
    for p in all_finalized:
        finalized_index[(p.establishment_id, p.year, p.month)] = (True, bool(p.is_nil))

    # ── Build matrix ──
    matrix = []
    summary_counts = {'full': 0, 'partial': 0, 'none': 0, 'na': 0}
    month_totals = {i: {'full': 0, 'partial': 0, 'none': 0, 'na': 0} for i in range(len(wage_months))}

    for est in establishments:
        has_pf = bool(est.pf_code)
        has_esic = bool(est.esic_code)

        row_cells = []
        row_full = 0
        row_partial = 0
        row_none = 0
        row_na = 0

        for idx, wm in enumerate(wage_months):
            # Payroll finalized for this (est, year, month)?
            fn_info = finalized_index.get((est.id, wm.year, wm.month), (False, False))
            is_finalized, is_nil = fn_info

            # When payroll is finalized, both EPF and ESIC are considered filed
            # for whichever codes the establishment has.
            epf_filed = is_finalized if has_pf else None
            esic_filed = is_finalized if has_esic else None

            # Determine cell status
            if not has_pf and not has_esic:
                status = 'na'
            else:
                applicable = []
                if has_pf:
                    applicable.append(epf_filed)
                if has_esic:
                    applicable.append(esic_filed)
                if all(applicable):
                    status = 'full'
                elif any(applicable):
                    status = 'partial'
                else:
                    status = 'none'

            row_cells.append({
                'status': status,
                'epf': epf_filed,
                'esic': esic_filed,
                'wage_month': wm,
                'has_pf': has_pf,
                'has_esic': has_esic,
                'finalized': is_finalized,
                'is_nil': is_nil,           # NIL filings count as filed but shown with 'N' label
            })

            month_totals[idx][status] += 1
            if status == 'full': row_full += 1
            elif status == 'partial': row_partial += 1
            elif status == 'none': row_none += 1
            else: row_na += 1

        # Classify row for summary
        applicable_cells = row_full + row_partial + row_none
        if applicable_cells == 0:
            row_classification = 'na'
        elif row_full == applicable_cells:
            row_classification = 'full'
        elif row_none == applicable_cells:
            row_classification = 'none'
        else:
            row_classification = 'partial'

        summary_counts[row_classification] += 1

        # Compliance % for this establishment
        if applicable_cells > 0:
            compliance_pct = round((row_full / applicable_cells) * 100)
        else:
            compliance_pct = None

        matrix.append({
            'est': est,
            'cells': row_cells,
            'full': row_full,
            'partial': row_partial,
            'none': row_none,
            'na': row_na,
            'classification': row_classification,
            'compliance_pct': compliance_pct,
            'has_pf': has_pf,
            'has_esic': has_esic,
        })

    # ── Fees collected in the period (admin sees all — voucher data) ──
    # Total = sum of all "Professional Fees" + "IP & UAN Charges" + "Other Income" credits
    # Date range: from 1st of from_month to last day of to_month
    from calendar import monthrange
    if wage_months:
        last_wm = wage_months[-1]
        last_day = monthrange(last_wm.year, last_wm.month)[1]
        period_end = date(last_wm.year, last_wm.month, last_day)
    else:
        period_end = to_month

    total_fees_collected = 0
    try:
        fee_accounts = AccountHead.query.filter(
            AccountHead.name.in_(['Professional Fees', 'IP & UAN Charges', 'Other Income'])
        ).all()
        fee_account_ids = [a.id for a in fee_accounts]
        if fee_account_ids:
            # Admin sees ALL fees collected (no owner_id filter)
            entries_q = db.session.query(db.func.sum(VoucherEntry.amount))\
                .join(Voucher, VoucherEntry.voucher_id == Voucher.id)\
                .filter(
                    VoucherEntry.account_id.in_(fee_account_ids),
                    VoucherEntry.entry_type == 'credit',
                    Voucher.voucher_date >= from_month,
                    Voucher.voucher_date <= period_end
                )
            total_fees_collected = entries_q.scalar() or 0
    except Exception:
        total_fees_collected = 0

    # ── Overall compliance stats ──
    total_applicable_cells = sum(m['full'] + m['partial'] + m['none'] for m in matrix)
    total_full_cells = sum(m['full'] for m in matrix)
    overall_compliance_pct = round((total_full_cells / total_applicable_cells) * 100) if total_applicable_cells else 0

    total_est = len(establishments)
    total_pending_cells = sum(m['none'] + m['partial'] for m in matrix)

    # Sort matrix: worst compliance first (to highlight priority follow-ups)
    matrix_sorted = sorted(matrix, key=lambda m: (m['compliance_pct'] if m['compliance_pct'] is not None else 200))

    return render_template('daily_mis/filing_matrix.html',
                           matrix=matrix_sorted,
                           wage_months=wage_months,
                           month_totals=month_totals,
                           summary_counts=summary_counts,
                           total_est=total_est,
                           total_fees_collected=total_fees_collected,
                           total_applicable_cells=total_applicable_cells,
                           total_full_cells=total_full_cells,
                           total_pending_cells=total_pending_cells,
                           overall_compliance_pct=overall_compliance_pct,
                           from_month=from_month,
                           to_month=to_month,
                           from_month_str=from_month.strftime('%Y-%m'),
                           to_month_str=to_month.strftime('%Y-%m'),
                           period_label=f"{from_month.strftime('%b %Y')} to {to_month.strftime('%b %Y')}",
                           is_admin=is_admin())


# ═════════════════════════════════════════════
#  STAFF PENDING VIEW (Admin clicks on staff name)
# ═════════════════════════════════════════════
@daily_mis_bp.route('/daily-mis/staff/<staff_name>')
@login_required
def mis_staff_view(staff_name):
    if not is_admin():
        flash('Admin only.', 'warning')
        return redirect(url_for('daily_mis.mis_home'))

    # All pending entries for this staff
    pending_entries = DailyMISEntry.query.filter(
        or_(DailyMISEntry.staff_name == staff_name,
            DailyMISEntry.assigned_to_name == staff_name),
        DailyMISEntry.status.in_(['pending', 'in_progress'])
    ).order_by(DailyMISEntry.due_date.asc().nulls_last(),
               DailyMISEntry.task_date.desc()).all()

    # Today's entries for this staff
    today = date.today()
    today_entries = DailyMISEntry.query.filter(
        or_(DailyMISEntry.staff_name == staff_name,
            DailyMISEntry.assigned_to_name == staff_name),
        DailyMISEntry.task_date == today
    ).order_by(DailyMISEntry.created_at.desc()).all()

    # This month's stats
    month_start = date(today.year, today.month, 1)
    month_entries = DailyMISEntry.query.filter(
        or_(DailyMISEntry.staff_name == staff_name,
            DailyMISEntry.assigned_to_name == staff_name),
        DailyMISEntry.task_date >= month_start,
        DailyMISEntry.task_date <= today
    ).all()

    month_total = len(month_entries)
    month_completed = sum(1 for e in month_entries if e.status == 'completed')
    month_pending = sum(1 for e in month_entries if e.status == 'pending')

    staff_list = _get_staff_list()

    return render_template('daily_mis/staff_view.html',
                           staff_name=staff_name,
                           pending_entries=pending_entries,
                           today_entries=today_entries,
                           month_total=month_total,
                           month_completed=month_completed,
                           month_pending=month_pending,
                           staff_list=staff_list,
                           is_admin=True)


# ═════════════════════════════════════════════
#  REPORT — Date-range report with filters
# ═════════════════════════════════════════════
@daily_mis_bp.route('/daily-mis/report')
@login_required
def mis_report():
    from_str = request.args.get('from_date', '')
    to_str = request.args.get('to_date', '')
    category_filter = request.args.get('category', '')
    status_filter = request.args.get('status', '')
    staff_filter = request.args.get('staff', '')
    est_filter = request.args.get('establishment_id', '', type=str)

    today = date.today()
    if not from_str:
        from_date = date(today.year, today.month, 1)
    else:
        try:
            from_date = datetime.strptime(from_str, '%Y-%m-%d').date()
        except ValueError:
            from_date = date(today.year, today.month, 1)
    if not to_str:
        to_date = today
    else:
        try:
            to_date = datetime.strptime(to_str, '%Y-%m-%d').date()
        except ValueError:
            to_date = today

    query = _user_mis_entries().filter(
        DailyMISEntry.task_date >= from_date,
        DailyMISEntry.task_date <= to_date
    )
    if category_filter:
        query = query.filter(DailyMISEntry.category == category_filter)
    if status_filter:
        query = query.filter(DailyMISEntry.status == status_filter)
    if staff_filter:
        query = query.filter(DailyMISEntry.staff_name == staff_filter)
    if est_filter:
        try:
            query = query.filter(DailyMISEntry.establishment_id == int(est_filter))
        except ValueError:
            pass

    entries = query.order_by(DailyMISEntry.task_date.desc(),
                             DailyMISEntry.created_at.desc()).all()

    total_tasks = len(entries)
    completed = sum(1 for e in entries if e.status == 'completed')
    pending = sum(1 for e in entries if e.status == 'pending')
    in_progress = sum(1 for e in entries if e.status == 'in_progress')
    total_amount = sum(e.amount for e in entries if e.amount)

    category_counts = {}
    for e in entries:
        category_counts[e.category] = category_counts.get(e.category, 0) + 1

    staff_list = []
    if is_admin():
        staff_list = db.session.query(DailyMISEntry.staff_name).distinct() \
            .filter(DailyMISEntry.staff_name.isnot(None)).all()
        staff_list = sorted([s[0] for s in staff_list])

    establishments = user_establishments().filter_by(is_active=True) \
        .order_by(Establishment.company_name).all()

    return render_template('daily_mis/report.html',
                           entries=entries,
                           from_date=from_date, to_date=to_date,
                           category_filter=category_filter,
                           status_filter=status_filter,
                           staff_filter=staff_filter,
                           est_filter=est_filter,
                           total_tasks=total_tasks,
                           completed=completed, pending=pending,
                           in_progress=in_progress,
                           total_amount=total_amount,
                           category_counts=category_counts,
                           categories=MIS_TASK_CATEGORIES,
                           staff_list=staff_list,
                           establishments=establishments,
                           is_admin=is_admin())


# ═════════════════════════════════════════════
#  API — Get task types for a category (AJAX)
# ═════════════════════════════════════════════
@daily_mis_bp.route('/daily-mis/api/tasks')
@login_required
def api_task_types():
    category = request.args.get('category', '')
    tasks = MIS_TASK_CATEGORIES.get(category, [])
    return jsonify({'tasks': tasks})


# ═════════════════════════════════════════════
#  SAVE — Create or update MIS entry
# ═════════════════════════════════════════════
def _save_mis_entry(existing_entry=None):
    """Save a new or existing MIS entry. Auto-creates voucher for payment tasks."""
    try:
        task_date_str = request.form.get('task_date', '')
        task_date = datetime.strptime(task_date_str, '%Y-%m-%d').date() if task_date_str else date.today()
        category = request.form.get('category', '').strip()
        task_type = request.form.get('task_type', '').strip()
        est_id = request.form.get('establishment_id', type=int)
        description = request.form.get('description', '').strip()
        amount = request.form.get('amount', '')
        amount = round(float(amount)) if amount else None
        reference = request.form.get('reference', '').strip()
        status = request.form.get('status', 'completed')
        bank_account_id = request.form.get('bank_account_id', type=int)
        priority = request.form.get('priority', 'normal')
        due_date_str = request.form.get('due_date', '')
        due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date() if due_date_str else None
        assign_to_id = request.form.get('assign_to_id', '').strip()

    except (ValueError, TypeError) as e:
        flash(f'Invalid input: {e}', 'danger')
        return redirect(url_for('daily_mis.mis_add'))

    if not category or not task_type:
        flash('Category and Task Type are required.', 'danger')
        return redirect(url_for('daily_mis.mis_add'))

    if task_type in PAYMENT_TASK_TYPES:
        if not amount or amount <= 0:
            flash('Amount is required for payment tasks.', 'danger')
            return redirect(url_for('daily_mis.mis_add'))
        if not est_id:
            flash('Establishment is required for payment tasks.', 'danger')
            return redirect(url_for('daily_mis.mis_add'))
        if not bank_account_id:
            flash('Bank Account is required for payment tasks.', 'danger')
            return redirect(url_for('daily_mis.mis_add'))

    est = None
    if est_id:
        est = Establishment.query.get(est_id)
        if est:
            verify_est_ownership(est)

    is_new = existing_entry is None

    if is_new:
        entry = DailyMISEntry()
        entry.owner_id = current_user_id()
        entry.staff_name = current_user_name()
    else:
        entry = existing_entry
        if entry.voucher_id:
            old_voucher = Voucher.query.get(entry.voucher_id)
            if old_voucher:
                VoucherEntry.query.filter_by(voucher_id=old_voucher.id).delete()
                db.session.delete(old_voucher)
                db.session.flush()
            entry.voucher_id = None

    entry.task_date = task_date
    entry.category = category
    entry.task_type = task_type
    entry.establishment_id = est_id
    entry.description = description
    entry.amount = amount
    entry.reference = reference
    entry.status = status
    entry.priority = priority
    entry.due_date = due_date

    # ── Task Assignment (Admin only) ──
    if is_admin() and assign_to_id:
        user = AppUser.query.filter_by(clerk_user_id=assign_to_id).first()
        if user:
            entry.assigned_to_id = user.clerk_user_id
            entry.assigned_to_name = user.name or user.email
            entry.assigned_by_name = current_user_name()
            entry.is_assigned = True

    if is_new:
        db.session.add(entry)
    db.session.flush()

    # ── Auto-create voucher for payment tasks ──
    voucher = None
    if task_type in PAYMENT_TASK_TYPES and amount and amount > 0 and est and bank_account_id:
        if task_type in ('Compliance Amount Received', 'Fee Received'):
            voucher = _create_receipt_voucher(entry, est, bank_account_id, task_type)
        elif task_type == 'Challan Payment Done':
            voucher = _create_payment_voucher(entry, est, bank_account_id)
        elif task_type == 'Refund / Reversal':
            voucher = _create_journal_voucher(entry, est, bank_account_id)

        if voucher:
            entry.voucher_id = voucher.id

    action = 'created' if is_new else 'updated'
    log_activity(action, 'mis_entry', entity_id=entry.id,
                 entity_name=f'{task_type} — {entry.establishment_name}',
                 details=f'{category}: {description or task_type}',
                 establishment_id=est_id)
    db.session.commit()

    if voucher:
        flash(f'MIS entry saved + Voucher {voucher.voucher_number} created in Accounts!', 'success')
    elif entry.is_assigned and is_new:
        flash(f'Task assigned to {entry.assigned_to_name}!', 'success')
    else:
        flash(f'MIS entry {"added" if is_new else "updated"} successfully!', 'success')

    return redirect(url_for('daily_mis.mis_home', date=task_date.strftime('%Y-%m-%d')))
