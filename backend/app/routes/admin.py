"""
Admin User Management Routes
==============================
Allows admins to:
- View all registered users (synced from Clerk)
- Link users to their admin (assign admin_id)
- Promote user → admin or demote admin → user
- Activate / deactivate users
- Unlink users (remove admin_id)
- Force sync users from Clerk
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
from app import db
from app.models.app_user import AppUser
from app.auth import admin_required, fetch_all_clerk_users, sync_all_users_from_clerk
from app.user_context import current_user_id, is_admin, log_activity
from datetime import datetime

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.before_request
def require_admin():
    """All admin routes require admin role"""
    if not is_admin():
        flash('Admin access required.', 'danger')
        return redirect(url_for('establishment.dashboard'))


@admin_bp.route('/users')
def user_list():
    """
    List all users with their roles, admin linkage, and status.
    Auto-syncs from Clerk on every page load (cached 10 min).
    """
    # ── Sync from Clerk (cached — won't hit API if called within 10 min) ──
    updated, created, total_clerk = sync_all_users_from_clerk()
    if created > 0:
        flash(f'{created} new user(s) synced from Clerk.', 'info')

    # ── Fetch Clerk data for extra info (image, last sign-in) ──
    clerk_users = fetch_all_clerk_users()
    clerk_map = {cu['user_id']: cu for cu in clerk_users}

    users = AppUser.query.order_by(AppUser.role.desc(), AppUser.created_at).all()
    admins = AppUser.query.filter_by(role='admin', is_active=True).all()

    # Enrich users with Clerk data
    for user in users:
        cu = clerk_map.get(user.clerk_user_id, {})
        user._clerk_image = cu.get('image_url', '')
        user._clerk_last_sign_in = None
        if cu.get('last_sign_in_at'):
            try:
                # Clerk sends milliseconds timestamp
                user._clerk_last_sign_in = datetime.fromtimestamp(cu['last_sign_in_at'] / 1000)
            except (ValueError, TypeError, OSError):
                pass

    # Stats
    total_users = len(users)
    admin_count = sum(1 for u in users if u.role == 'admin')
    user_count = sum(1 for u in users if u.role == 'user')
    active_count = sum(1 for u in users if u.is_active)
    unlinked_count = sum(1 for u in users if u.role == 'user' and u.admin_id is None)

    return render_template('admin/users.html',
                           users=users,
                           admins=admins,
                           total_users=total_users,
                           admin_count=admin_count,
                           user_count=user_count,
                           active_count=active_count,
                           unlinked_count=unlinked_count,
                           total_clerk=total_clerk)


@admin_bp.route('/users/sync', methods=['POST'])
def force_sync():
    """Force re-sync all users from Clerk (clears cache)"""
    # Clear cache to force fresh API call
    fetch_all_clerk_users._cache = None
    fetch_all_clerk_users._cached_at = 0

    updated, created, total = sync_all_users_from_clerk()
    flash(f'Clerk sync complete: {total} Clerk users found, {updated} updated, {created} new.', 'success')
    return redirect(url_for('admin.user_list'))


@admin_bp.route('/users/<int:user_id>/link', methods=['POST'])
def link_user(user_id):
    """Link a user to an admin (set admin_id)."""
    user = AppUser.query.get_or_404(user_id)
    admin_id = request.form.get('admin_id', type=int)

    if user.role == 'admin':
        flash('Cannot link an admin to another admin.', 'warning')
        return redirect(url_for('admin.user_list'))

    if admin_id:
        admin_user = AppUser.query.get(admin_id)
        if not admin_user or admin_user.role != 'admin':
            flash('Invalid admin selected.', 'danger')
            return redirect(url_for('admin.user_list'))
        user.admin_id = admin_id
        db.session.commit()
        log_activity('link_user', 'AppUser', entity_id=user.id,
                     entity_name=user.name,
                     details=f'Linked to admin: {admin_user.name}')
        db.session.commit()
        flash(f'{user.name} linked to admin {admin_user.name}.', 'success')
    else:
        flash('Please select an admin.', 'warning')

    return redirect(url_for('admin.user_list'))


@admin_bp.route('/users/<int:user_id>/unlink', methods=['POST'])
def unlink_user(user_id):
    """Unlink a user from their admin (set admin_id = NULL)"""
    user = AppUser.query.get_or_404(user_id)

    if user.role == 'admin':
        flash('Admins do not have an admin link.', 'warning')
        return redirect(url_for('admin.user_list'))

    old_admin = user.admin
    user.admin_id = None
    db.session.commit()
    log_activity('unlink_user', 'AppUser', entity_id=user.id,
                 entity_name=user.name,
                 details=f'Unlinked from admin: {old_admin.name if old_admin else "N/A"}')
    db.session.commit()
    flash(f'{user.name} unlinked from admin.', 'success')
    return redirect(url_for('admin.user_list'))


@admin_bp.route('/users/<int:user_id>/promote', methods=['POST'])
def promote_user(user_id):
    """Promote a user to admin role"""
    user = AppUser.query.get_or_404(user_id)

    if user.role == 'admin':
        flash(f'{user.name} is already an admin.', 'info')
        return redirect(url_for('admin.user_list'))

    user.role = 'admin'
    user.admin_id = None
    db.session.commit()
    log_activity('promote_user', 'AppUser', entity_id=user.id,
                 entity_name=user.name,
                 details='Promoted to admin role')
    db.session.commit()
    flash(f'{user.name} promoted to Admin.', 'success')
    return redirect(url_for('admin.user_list'))


@admin_bp.route('/users/<int:user_id>/demote', methods=['POST'])
def demote_user(user_id):
    """Demote an admin to user role"""
    user = AppUser.query.get_or_404(user_id)

    if user.role == 'user':
        flash(f'{user.name} is already a user.', 'info')
        return redirect(url_for('admin.user_list'))

    admin_count = AppUser.query.filter_by(role='admin', is_active=True).count()
    current_uid = current_user_id()
    if user.clerk_user_id == current_uid and admin_count <= 1:
        flash('Cannot demote yourself — you are the only admin.', 'danger')
        return redirect(url_for('admin.user_list'))

    managed = AppUser.query.filter_by(admin_id=user.id).all()
    for m in managed:
        m.admin_id = None

    user.role = 'user'
    db.session.commit()
    log_activity('demote_user', 'AppUser', entity_id=user.id,
                 entity_name=user.name,
                 details=f'Demoted to user role. {len(managed)} managed users unlinked.')
    db.session.commit()
    flash(f'{user.name} demoted to User. {len(managed)} managed users unlinked.', 'success')
    return redirect(url_for('admin.user_list'))


@admin_bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
def toggle_active(user_id):
    """Activate or deactivate a user"""
    user = AppUser.query.get_or_404(user_id)

    current_uid = current_user_id()
    if user.clerk_user_id == current_uid:
        flash('You cannot deactivate your own account.', 'danger')
        return redirect(url_for('admin.user_list'))

    user.is_active = not user.is_active
    status = 'activated' if user.is_active else 'deactivated'
    db.session.commit()
    log_activity(f'{status}_user', 'AppUser', entity_id=user.id,
                 entity_name=user.name,
                 details=f'User {status}')
    db.session.commit()
    flash(f'{user.name} {status}.', 'success')
    return redirect(url_for('admin.user_list'))


@admin_bp.route('/users/<int:user_id>/details')
def user_details(user_id):
    """Get user details as JSON (for modals/AJAX) — enriched with Clerk data."""
    user = AppUser.query.get_or_404(user_id)

    # Get Clerk data for this user
    clerk_users = fetch_all_clerk_users()
    clerk_data = {}
    for cu in clerk_users:
        if cu['user_id'] == user.clerk_user_id:
            clerk_data = cu
            break

    # Count establishments and employees
    from app.models.establishment import Establishment
    est_count = Establishment.query.filter_by(owner_id=user.clerk_user_id).count()

    from app.models.employee import Employee
    est_ids = [e.id for e in Establishment.query.filter_by(owner_id=user.clerk_user_id).with_entities(Establishment.id).all()]
    emp_count = Employee.query.filter(Employee.establishment_id.in_(est_ids)).count() if est_ids else 0

    # Last sign-in from Clerk
    last_sign_in = ''
    if clerk_data.get('last_sign_in_at'):
        try:
            dt = datetime.fromtimestamp(clerk_data['last_sign_in_at'] / 1000)
            last_sign_in = dt.strftime('%d %b %Y, %I:%M %p')
        except (ValueError, TypeError, OSError):
            pass

    return jsonify({
        'id': user.id,
        'name': user.name,
        'email': user.email,
        'role': user.role,
        'is_active': user.is_active,
        'admin_id': user.admin_id,
        'admin_name': user.admin.name if user.admin else None,
        'clerk_user_id': user.clerk_user_id,
        'image_url': clerk_data.get('image_url', ''),
        'last_sign_in': last_sign_in,
        'created_at': user.created_at.strftime('%d %b %Y, %I:%M %p') if user.created_at else '',
        'updated_at': user.updated_at.strftime('%d %b %Y, %I:%M %p') if user.updated_at else '',
        'establishment_count': est_count,
        'employee_count': emp_count,
        'managed_users_count': len(user.managed_users) if user.role == 'admin' else 0,
    })


# ═════════════════════════════════════════════════════════════════
# STAFF PERFORMANCE DASHBOARD (admin-only)
# All-staff summary table with period-aware compliance % and fee data.
# Clicking a staff row navigates to the drill-down page.
# ═════════════════════════════════════════════════════════════════
@admin_bp.route('/staff-performance')
def staff_performance():
    """All-staff overview: period-aware compliance %, tasks, fee due/received."""
    from app.models.establishment import Establishment
    from app.models.payroll import MonthlyPayroll
    from app.models.accounts import Voucher, VoucherEntry, AccountHead
    from app.utils.date_helpers import current_wage_month, current_fy_start_year
    from datetime import date
    from calendar import monthrange
    from sqlalchemy import func

    today = date.today()
    fy_start_year = current_fy_start_year(today)
    wage_y, wage_m = current_wage_month(today)

    from_str = request.args.get('from', '')
    to_str   = request.args.get('to', '')

    default_from = date(fy_start_year, 4, 1)
    default_to   = date(wage_y, wage_m, 1)
    if default_to < default_from:
        default_to = default_from

    try:
        from_month = date(int(from_str.split('-')[0]), int(from_str.split('-')[1]), 1) if from_str else default_from
    except (ValueError, IndexError):
        from_month = default_from

    try:
        to_month = date(int(to_str.split('-')[0]), int(to_str.split('-')[1]), 1) if to_str else default_to
    except (ValueError, IndexError):
        to_month = default_to

    # Build list of wage months in the selected range
    wage_months = []
    cur = from_month
    while cur <= to_month:
        wage_months.append(cur)
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
    num_months = len(wage_months)

    # Period end date (last calendar day of the to_month)
    last_wm   = wage_months[-1] if wage_months else to_month
    last_day  = monthrange(last_wm.year, last_wm.month)[1]
    period_end = date(last_wm.year, last_wm.month, last_day)

    # All active establishments and users
    all_ests = Establishment.query.filter_by(is_active=True).order_by(Establishment.company_name).all()
    est_ids  = [e.id for e in all_ests]
    users    = AppUser.query.filter_by(is_active=True).order_by(AppUser.name).all()

    # Pre-fetch all finalized payrolls in range (one batch query)
    finalized_index = {}
    if wage_months and est_ids:
        min_year = min(wm.year for wm in wage_months)
        max_year = max(wm.year for wm in wage_months)
        for p in MonthlyPayroll.query.filter(
            MonthlyPayroll.status == 'finalized',
            MonthlyPayroll.year  >= min_year,
            MonthlyPayroll.year  <= max_year,
            MonthlyPayroll.establishment_id.in_(est_ids),
        ).all():
            finalized_index[(p.establishment_id, p.year, p.month)] = True

    # Pre-fetch fee received per establishment (credits to Sundry Debtor account)
    fee_received_by_est = {}
    voucher_est_ids     = set()
    if est_ids:
        ah_rows = AccountHead.query.filter(
            AccountHead.establishment_id.in_(est_ids)
        ).all()
        if ah_rows:
            rows = db.session.query(
                AccountHead.establishment_id,
                func.sum(VoucherEntry.amount)
            ).join(VoucherEntry, VoucherEntry.account_id == AccountHead.id)\
             .join(Voucher, VoucherEntry.voucher_id == Voucher.id)\
             .filter(
                 AccountHead.establishment_id.in_(est_ids),
                 VoucherEntry.entry_type == 'credit',
                 Voucher.voucher_date >= from_month,
                 Voucher.voucher_date <= period_end,
             ).group_by(AccountHead.establishment_id).all()
            for est_id, total in rows:
                fee_received_by_est[est_id] = float(total or 0)

        for (vid,) in Voucher.query.filter(
            Voucher.establishment_id.in_(est_ids),
            Voucher.voucher_date >= from_month,
            Voucher.voucher_date <= period_end,
        ).with_entities(Voucher.establishment_id).all():
            if vid:
                voucher_est_ids.add(vid)

    def _monthly_fee(est):
        """Normalise establishment fee to a per-month amount."""
        if not est.fee_amount:
            return 0.0
        if est.fee_type == 'Quarterly':
            return est.fee_amount / 3.0
        if est.fee_type == 'Yearly':
            return est.fee_amount / 12.0
        return float(est.fee_amount)  # Monthly (default)

    # Build per-staff metrics
    staff_metrics = []
    off_tasks = off_done = off_due = off_recv = 0

    for user in users:
        assigned = [e for e in all_ests if e.assigned_to_id == user.clerk_user_id]

        total_tasks = completed_tasks = 0
        fee_due = fee_recv = 0.0
        not_updated = 0

        for est in assigned:
            applicable = bool(est.pf_code) or bool(est.esic_code)
            if applicable:
                for wm in wage_months:
                    total_tasks += 1
                    if finalized_index.get((est.id, wm.year, wm.month)):
                        completed_tasks += 1

            mf = _monthly_fee(est)
            fee_due  += mf * num_months
            fee_recv += fee_received_by_est.get(est.id, 0.0)

            if mf > 0 and est.id not in voucher_est_ids:
                not_updated += 1

        perf_pct = round(completed_tasks / total_tasks * 100) if total_tasks else None
        short  = max(0.0, fee_due - fee_recv)
        excess = max(0.0, fee_recv - fee_due)

        if perf_pct is None:
            grade, grade_label, grade_color = 'new',       'No Data',          '#94a3b8'
        elif perf_pct >= 90:
            grade, grade_label, grade_color = 'excellent', 'Excellent',         '#16a34a'
        elif perf_pct >= 75:
            grade, grade_label, grade_color = 'good',      'Good',              '#65a30d'
        elif perf_pct >= 50:
            grade, grade_label, grade_color = 'average',   'Average',           '#f59e0b'
        else:
            grade, grade_label, grade_color = 'attention', 'Needs Attention',   '#dc2626'

        off_tasks += total_tasks
        off_done  += completed_tasks
        off_due   += fee_due
        off_recv  += fee_recv

        staff_metrics.append({
            'user':            user,
            'est_count':       len(assigned),
            'total_tasks':     total_tasks,
            'completed_tasks': completed_tasks,
            'pending_tasks':   total_tasks - completed_tasks,
            'perf_pct':        perf_pct,
            'grade':           grade,
            'grade_label':     grade_label,
            'grade_color':     grade_color,
            'fee_due':         round(fee_due),
            'fee_received':    round(fee_recv),
            'short':           round(short),
            'excess':          round(excess),
            'not_updated':     not_updated,
        })

    # Sort: lowest % first (worst performers at top — same logic as filing matrix)
    staff_metrics.sort(key=lambda m: m['perf_pct'] if m['perf_pct'] is not None else -1)

    unassigned_count = sum(1 for e in all_ests if not e.assigned_to_id)
    office_pct = round(off_done / off_tasks * 100) if off_tasks else 0

    return render_template(
        'admin/staff_performance.html',
        staff_metrics=staff_metrics,
        from_month=from_month,
        to_month=to_month,
        from_month_str=from_month.strftime('%Y-%m'),
        to_month_str=to_month.strftime('%Y-%m'),
        period_label=f"{from_month.strftime('%b %Y')} to {to_month.strftime('%b %Y')}",
        num_months=num_months,
        unassigned_count=unassigned_count,
        total_active_est=len(all_ests),
        total_staff=len(users),
        office_pct=office_pct,
        office_fee_due=round(off_due),
        office_fee_received=round(off_recv),
    )


# ═════════════════════════════════════════════════════════════════
# STAFF PERFORMANCE DRILL-DOWN (admin-only)
# Establishment-by-establishment breakdown for one staff member.
# Shows monthly filing cells + fee due / received / short / excess.
# ═════════════════════════════════════════════════════════════════
@admin_bp.route('/staff-performance/<clerk_user_id>')
def staff_performance_drill(clerk_user_id):
    """Per-staff drill-down: establishment table with monthly cells + fee columns."""
    from app.models.establishment import Establishment
    from app.models.payroll import MonthlyPayroll
    from app.models.accounts import Voucher, VoucherEntry, AccountHead
    from app.utils.date_helpers import current_wage_month, current_fy_start_year
    from datetime import date
    from calendar import monthrange
    from sqlalchemy import func

    staff_user = AppUser.query.filter_by(
        clerk_user_id=clerk_user_id, is_active=True
    ).first_or_404()

    today = date.today()
    fy_start_year = current_fy_start_year(today)
    wage_y, wage_m = current_wage_month(today)

    from_str = request.args.get('from', '')
    to_str   = request.args.get('to', '')

    default_from = date(fy_start_year, 4, 1)
    default_to   = date(wage_y, wage_m, 1)
    if default_to < default_from:
        default_to = default_from

    try:
        from_month = date(int(from_str.split('-')[0]), int(from_str.split('-')[1]), 1) if from_str else default_from
    except (ValueError, IndexError):
        from_month = default_from

    try:
        to_month = date(int(to_str.split('-')[0]), int(to_str.split('-')[1]), 1) if to_str else default_to
    except (ValueError, IndexError):
        to_month = default_to

    wage_months = []
    cur = from_month
    while cur <= to_month:
        wage_months.append(cur)
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
    num_months = len(wage_months)

    last_wm   = wage_months[-1] if wage_months else to_month
    last_day  = monthrange(last_wm.year, last_wm.month)[1]
    period_end = date(last_wm.year, last_wm.month, last_day)

    # This staff's active establishments
    assigned_ests = Establishment.query.filter(
        Establishment.is_active == True,
        Establishment.assigned_to_id == clerk_user_id,
    ).order_by(Establishment.company_name).all()
    est_ids = [e.id for e in assigned_ests]

    # Finalized payrolls (batch)
    finalized_index = {}
    if wage_months and est_ids:
        min_year = min(wm.year for wm in wage_months)
        max_year = max(wm.year for wm in wage_months)
        for p in MonthlyPayroll.query.filter(
            MonthlyPayroll.status == 'finalized',
            MonthlyPayroll.year  >= min_year,
            MonthlyPayroll.year  <= max_year,
            MonthlyPayroll.establishment_id.in_(est_ids),
        ).all():
            finalized_index[(p.establishment_id, p.year, p.month)] = True

    # Fee received per establishment (batch)
    fee_received_by_est = {}
    voucher_est_ids     = set()
    if est_ids:
        ah_rows = AccountHead.query.filter(
            AccountHead.establishment_id.in_(est_ids)
        ).all()
        if ah_rows:
            rows = db.session.query(
                AccountHead.establishment_id,
                func.sum(VoucherEntry.amount)
            ).join(VoucherEntry, VoucherEntry.account_id == AccountHead.id)\
             .join(Voucher, VoucherEntry.voucher_id == Voucher.id)\
             .filter(
                 AccountHead.establishment_id.in_(est_ids),
                 VoucherEntry.entry_type == 'credit',
                 Voucher.voucher_date >= from_month,
                 Voucher.voucher_date <= period_end,
             ).group_by(AccountHead.establishment_id).all()
            for est_id, total in rows:
                fee_received_by_est[est_id] = float(total or 0)

        for (vid,) in Voucher.query.filter(
            Voucher.establishment_id.in_(est_ids),
            Voucher.voucher_date >= from_month,
            Voucher.voucher_date <= period_end,
        ).with_entities(Voucher.establishment_id).all():
            if vid:
                voucher_est_ids.add(vid)

    def _monthly_fee(est):
        if not est.fee_amount:
            return 0.0
        if est.fee_type == 'Quarterly':
            return est.fee_amount / 3.0
        if est.fee_type == 'Yearly':
            return est.fee_amount / 12.0
        return float(est.fee_amount)

    # Build per-establishment rows
    est_rows = []
    total_tasks = completed_tasks = 0
    total_due = total_recv = 0.0

    for est in assigned_ests:
        has_pf   = bool(est.pf_code)
        has_esic = bool(est.esic_code)
        applicable = has_pf or has_esic

        cells = []
        est_done = est_total = 0
        for wm in wage_months:
            is_fin = finalized_index.get((est.id, wm.year, wm.month), False)
            if applicable:
                est_total += 1
                if is_fin:
                    est_done += 1
            cells.append({'wm': wm, 'finalized': is_fin, 'applicable': applicable})

        total_tasks    += est_total
        completed_tasks += est_done

        mf       = _monthly_fee(est)
        fee_due  = round(mf * num_months)
        fee_recv = round(fee_received_by_est.get(est.id, 0.0))
        short    = max(0, fee_due - fee_recv)
        excess   = max(0, fee_recv - fee_due)
        total_due  += fee_due
        total_recv += fee_recv

        # Accounts status
        has_any_voucher = est.id in voucher_est_ids
        if fee_recv > 0 and short == 0 and excess == 0:
            acct_status = 'settled'
        elif fee_recv > 0 and short > 0:
            acct_status = 'short'
        elif fee_recv > 0 and excess > 0:
            acct_status = 'excess'
        elif has_any_voucher:
            acct_status = 'updated'
        elif mf > 0:
            acct_status = 'not_updated'
        else:
            acct_status = 'no_fee'

        est_pct = round(est_done / est_total * 100) if est_total else None

        est_rows.append({
            'est':           est,
            'has_pf':        has_pf,
            'has_esic':      has_esic,
            'applicable':    applicable,
            'cells':         cells,
            'est_total':     est_total,
            'est_done':      est_done,
            'est_pending':   est_total - est_done,
            'est_pct':       est_pct,
            'fee_due':       fee_due,
            'fee_received':  fee_recv,
            'short':         short,
            'excess':        excess,
            'acct_status':   acct_status,
        })

    perf_pct = round(completed_tasks / total_tasks * 100) if total_tasks else None
    total_short  = max(0, round(total_due - total_recv))
    total_excess = max(0, round(total_recv - total_due))
    not_updated  = sum(1 for r in est_rows if r['acct_status'] == 'not_updated')

    if perf_pct is None:
        grade, grade_label, grade_color = 'new',       'No Data',          '#94a3b8'
    elif perf_pct >= 90:
        grade, grade_label, grade_color = 'excellent', 'Excellent',         '#16a34a'
    elif perf_pct >= 75:
        grade, grade_label, grade_color = 'good',      'Good',              '#65a30d'
    elif perf_pct >= 50:
        grade, grade_label, grade_color = 'average',   'Average',           '#f59e0b'
    else:
        grade, grade_label, grade_color = 'attention', 'Needs Attention',   '#dc2626'

    return render_template(
        'admin/staff_performance_drill.html',
        staff_user=staff_user,
        est_rows=est_rows,
        wage_months=wage_months,
        num_months=num_months,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=total_tasks - completed_tasks,
        perf_pct=perf_pct,
        grade=grade,
        grade_label=grade_label,
        grade_color=grade_color,
        total_fee_due=round(total_due),
        total_fee_received=round(total_recv),
        total_short=total_short,
        total_excess=total_excess,
        not_updated=not_updated,
        from_month=from_month,
        to_month=to_month,
        from_month_str=from_month.strftime('%Y-%m'),
        to_month_str=to_month.strftime('%Y-%m'),
        period_label=f"{from_month.strftime('%b %Y')} to {to_month.strftime('%b %Y')}",
    )


# ═════════════════════════════════════════════
# REASSIGN — single or bulk
# ═════════════════════════════════════════════
@admin_bp.route('/reassign/<clerk_user_id>', methods=['GET', 'POST'])
def reassign_staff_clients(clerk_user_id):
    """Shows clients handled by a staff; admin selects some to move elsewhere."""
    from app.models.establishment import Establishment
    from app.models.assignment_log import EstablishmentAssignmentLog

    from_user = AppUser.query.filter_by(clerk_user_id=clerk_user_id).first_or_404()

    if request.method == 'POST':
        # Process reassignment
        est_ids = request.form.getlist('est_ids')
        to_user_id = request.form.get('to_user_id')
        reason = (request.form.get('reason') or '').strip()

        if not est_ids:
            flash('Please select at least one establishment to reassign.', 'warning')
            return redirect(url_for('admin.reassign_staff_clients', clerk_user_id=clerk_user_id))

        to_user = AppUser.query.filter_by(clerk_user_id=to_user_id).first()
        if not to_user:
            flash('Invalid destination user.', 'danger')
            return redirect(url_for('admin.reassign_staff_clients', clerk_user_id=clerk_user_id))

        moved = 0
        for est_id in est_ids:
            try:
                est = Establishment.query.get(int(est_id))
            except (ValueError, TypeError):
                continue
            if not est:
                continue

            # Log the transfer
            log = EstablishmentAssignmentLog(
                establishment_id=est.id,
                from_user_id=est.assigned_to_id,
                from_user_name=from_user.name or from_user.email,
                to_user_id=to_user.clerk_user_id,
                to_user_name=to_user.name or to_user.email,
                performed_by_id=current_user_id(),
                performed_by_role='admin',
                reason=reason or None,
            )
            # Get admin's name from Clerk / AppUser
            admin_user = AppUser.query.filter_by(clerk_user_id=current_user_id()).first()
            if admin_user:
                log.performed_by_name = admin_user.name or admin_user.email

            db.session.add(log)

            # Transfer
            est.assigned_to_id = to_user.clerk_user_id
            moved += 1

        db.session.commit()
        flash(f'Successfully reassigned {moved} client(s) to {to_user.name or to_user.email}.', 'success')
        return redirect(url_for('admin.staff_performance'))

    # GET — show current assignments with checkboxes
    assigned_ests = Establishment.query.filter(
        Establishment.is_active == True,
        Establishment.assigned_to_id == clerk_user_id,
    ).order_by(Establishment.company_name).all()

    other_users = AppUser.query.filter(
        AppUser.is_active == True,
        AppUser.clerk_user_id != clerk_user_id,
    ).order_by(AppUser.name).all()

    return render_template('admin/reassign.html',
                           from_user=from_user,
                           assigned_ests=assigned_ests,
                           other_users=other_users)


# ═════════════════════════════════════════════
# SINGLE ESTABLISHMENT TRANSFER (staff-initiated or admin)
# ═════════════════════════════════════════════
@admin_bp.route('/transfer-establishment/<int:est_id>', methods=['POST'])
def transfer_establishment(est_id):
    """Transfer a single establishment to another user.
    Accessible to admin (from staff performance) and to current handler.
    """
    from app.models.establishment import Establishment
    from app.models.assignment_log import EstablishmentAssignmentLog

    est = Establishment.query.get_or_404(est_id)

    # Authorization: admin OR current handler
    if not is_admin() and est.assigned_to_id != current_user_id():
        flash('You can only transfer establishments assigned to you.', 'danger')
        return redirect(url_for('establishment.establishment_list'))

    to_user_id = request.form.get('to_user_id')
    reason = (request.form.get('reason') or '').strip()

    to_user = AppUser.query.filter_by(clerk_user_id=to_user_id).first()
    if not to_user or not to_user.is_active:
        flash('Invalid destination user.', 'danger')
        return redirect(request.referrer or url_for('establishment.establishment_list'))

    from_user = AppUser.query.filter_by(clerk_user_id=est.assigned_to_id).first()
    performed_by = AppUser.query.filter_by(clerk_user_id=current_user_id()).first()

    log = EstablishmentAssignmentLog(
        establishment_id=est.id,
        from_user_id=est.assigned_to_id,
        from_user_name=(from_user.name if from_user else None) or (from_user.email if from_user else '—'),
        to_user_id=to_user.clerk_user_id,
        to_user_name=to_user.name or to_user.email,
        performed_by_id=current_user_id(),
        performed_by_name=(performed_by.name if performed_by else None) or (performed_by.email if performed_by else '—'),
        performed_by_role='admin' if is_admin() else 'user',
        reason=reason or None,
    )
    db.session.add(log)

    est.assigned_to_id = to_user.clerk_user_id
    db.session.commit()

    flash(f'{est.display_name} transferred to {to_user.name or to_user.email}.', 'success')
    return redirect(request.referrer or url_for('establishment.establishment_list'))
