"""
Admin User Management Routes
==============================
Allows admins to:
- View all staff/users with their roles, admin linkage, and status
- Create new user/staff accounts (email + temporary password)
- Reset a user's password
- Link users to their admin (assign admin_id)
- Promote user → admin or demote admin → user
- Activate / deactivate users
- Unlink users (remove admin_id)
"""

import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, jsonify
from app import db
from app.models.app_user import AppUser
from app.auth import admin_required
from app.jwt_auth import revoke_all_for_user
from app.user_context import current_user_id, is_admin, log_activity
from datetime import datetime


def _new_user_uid():
    """Generate a fresh canonical user uid for a brand-new account."""
    return f"usr_{secrets.token_hex(12)}"


def _generate_temp_password():
    """Human-typable temporary password (no ambiguous chars)."""
    alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
    return 'Vp' + ''.join(secrets.choice(alphabet) for _ in range(8))

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.before_request
def require_admin():
    """All admin routes require admin role"""
    if not is_admin():
        flash('Admin access required.', 'danger')
        return redirect(url_for('establishment.dashboard'))


@admin_bp.route('/users')
def user_list():
    """List all users with their roles, admin linkage, and status."""
    users = AppUser.query.order_by(AppUser.role.desc(), AppUser.created_at).all()
    admins = AppUser.query.filter_by(role='admin', is_active=True).all()

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
                           unlinked_count=unlinked_count)


@admin_bp.route('/users/create', methods=['POST'])
def create_user():
    """Create a new staff/user account with a temporary password.
    The new user must change their password on first login."""
    name = (request.form.get('name') or '').strip()
    email = (request.form.get('email') or '').strip().lower()
    role = (request.form.get('role') or 'user').strip()
    password = (request.form.get('password') or '').strip()

    if role not in ('admin', 'user'):
        role = 'user'
    if not email or '@' not in email:
        flash('A valid email is required to create a user.', 'danger')
        return redirect(url_for('admin.user_list'))

    existing = AppUser.query.filter(db.func.lower(AppUser.email) == email).first()
    if existing:
        flash(f'A user with email {email} already exists.', 'warning')
        return redirect(url_for('admin.user_list'))

    temp_password = password or _generate_temp_password()
    user = AppUser(
        clerk_user_id=_new_user_uid(),
        role=role,
        name=name or email.split('@')[0],
        email=email,
        must_change_password=True,
        is_active=True,
    )
    user.set_password(temp_password)
    user.temp_password = temp_password   # visible to admin until first change
    db.session.add(user)
    db.session.commit()

    log_activity('create_user', 'AppUser', entity_id=user.id,
                 entity_name=user.name, details=f'Created {role} account')
    db.session.commit()
    flash(f'User "{user.name}" created. Login: {email} — Temporary password: '
          f'{temp_password} (they must change it on first login).', 'success')
    return redirect(url_for('admin.user_list'))


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
def reset_password(user_id):
    """Reset a user's password to a new temporary one (forces change on login)
    and revoke all their active sessions."""
    user = AppUser.query.get_or_404(user_id)
    new_password = (request.form.get('new_password') or '').strip() or _generate_temp_password()
    if len(new_password) < 8:
        flash('Password must be at least 8 characters.', 'danger')
        return redirect(url_for('admin.user_list'))

    user.set_password(new_password)
    user.must_change_password = True
    user.temp_password = new_password   # visible to admin until first change
    db.session.commit()
    revoke_all_for_user(user.clerk_user_id)   # log them out everywhere

    log_activity('reset_password', 'AppUser', entity_id=user.id,
                 entity_name=user.name, details='Password reset by admin')
    db.session.commit()
    flash(f'Password for "{user.name}" reset to: {new_password} '
          f'(they must change it on next login).', 'success')
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
    """Get user details as JSON (for modals/AJAX)."""
    user = AppUser.query.get_or_404(user_id)

    # Count establishments and employees owned by this user
    from app.models.establishment import Establishment
    est_count = Establishment.query.filter_by(owner_id=user.clerk_user_id).count()

    from app.models.employee import Employee
    est_ids = [e.id for e in Establishment.query.filter_by(owner_id=user.clerk_user_id).with_entities(Establishment.id).all()]
    emp_count = Employee.query.filter(Employee.establishment_id.in_(est_ids)).count() if est_ids else 0

    last_sign_in = ''
    if user.last_login_at:
        last_sign_in = user.last_login_at.strftime('%d %b %Y, %I:%M %p')

    return jsonify({
        'id': user.id,
        'name': user.name,
        'email': user.email,
        'role': user.role,
        'is_active': user.is_active,
        'admin_id': user.admin_id,
        'admin_name': user.admin.name if user.admin else None,
        'clerk_user_id': user.clerk_user_id,
        'image_url': '',
        'temp_password': user.temp_password or '',
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


# ═══════════════════════════════════════════════════════════════════════════
#  CLIENT PORTAL USER MANAGEMENT
#  Read/write `client_users` rows — the login table for the standalone
#  Spring Boot + Next.js portal at vaishnavi-client-portal.
# ═══════════════════════════════════════════════════════════════════════════
from app.models.client_user import ClientUser
from app.models.establishment import Establishment

try:
    import bcrypt as _bcrypt
except ImportError:
    _bcrypt = None  # We'll error politely if a save is attempted without it.


def _bcrypt_hash(plain):
    """Hash a password with bcrypt cost-10 — same scheme Spring Security validates."""
    if _bcrypt is None:
        raise RuntimeError(
            "bcrypt package not installed.  Run `pip install bcrypt>=4.1.0` "
            "in the ERP environment and restart the service."
        )
    return _bcrypt.hashpw(plain.encode('utf-8'),
                          _bcrypt.gensalt(rounds=10)).decode('utf-8')


@admin_bp.route('/portal-users')
def portal_user_list():
    """List all client portal logins with their establishment names."""
    search = (request.args.get('q') or '').strip().lower()

    q = ClientUser.query.join(Establishment,
                              Establishment.id == ClientUser.establishment_id)
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(
            db.func.lower(ClientUser.username).like(like),
            db.func.lower(ClientUser.email).like(like),
            ClientUser.phone.like(like),
            db.func.lower(Establishment.company_name).like(like),
            db.func.lower(db.func.coalesce(Establishment.branch_name, '')).like(like),
        ))

    users = q.order_by(Establishment.company_name,
                       Establishment.branch_name).all()
    return render_template('admin/portal_users.html',
                           users=users,
                           search=search)


@admin_bp.route('/portal-users/<int:user_id>/update', methods=['POST'])
def portal_user_update(user_id):
    """Update any of username/email/phone/password/active flag."""
    u = ClientUser.query.get_or_404(user_id)

    new_username = (request.form.get('username') or '').strip()
    new_email    = (request.form.get('email')    or '').strip()
    new_phone    = (request.form.get('phone')    or '').strip()
    new_password = request.form.get('password') or ''   # don't strip — preserve trailing spaces if intentional
    is_active    = request.form.get('is_active') == 'on'

    # Identifier uniqueness checks (skip if value didn't change)
    if new_username and new_username.lower() != u.username.lower():
        clash = ClientUser.query.filter(db.func.lower(ClientUser.username) == new_username.lower(),
                                        ClientUser.id != u.id).first()
        if clash:
            flash(f'Username "{new_username}" is already in use.', 'danger')
            return redirect(url_for('admin.portal_user_list'))
        u.username = new_username

    if new_email and new_email.lower() != (u.email or '').lower():
        clash = ClientUser.query.filter(db.func.lower(ClientUser.email) == new_email.lower(),
                                        ClientUser.id != u.id).first()
        if clash:
            flash(f'Email "{new_email}" is already in use.', 'danger')
            return redirect(url_for('admin.portal_user_list'))
        u.email = new_email

    if new_phone != (u.phone or ''):
        # Allow clearing the phone
        if new_phone == '':
            u.phone = None
        else:
            clash = ClientUser.query.filter(ClientUser.phone == new_phone,
                                            ClientUser.id != u.id).first()
            if clash:
                flash(f'Phone "{new_phone}" is already in use.', 'danger')
                return redirect(url_for('admin.portal_user_list'))
            u.phone = new_phone

    if new_password:
        if len(new_password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('admin.portal_user_list'))
        try:
            u.password_hash  = _bcrypt_hash(new_password)
        except RuntimeError as e:
            flash(str(e), 'danger')
            return redirect(url_for('admin.portal_user_list'))
        u.vault_password = new_password

    u.is_active = is_active
    db.session.commit()

    log_activity('portal_user_updated',
                 f'Updated portal login for establishment_id={u.establishment_id} (username={u.username})')
    flash(f'Updated portal login for "{u.username}".', 'success')
    return redirect(url_for('admin.portal_user_list'))


@admin_bp.route('/portal-users/<int:user_id>/reset-password', methods=['POST'])
def portal_user_reset_password(user_id):
    """Reset to the default password (or whatever's posted as ?new_password=)."""
    u = ClientUser.query.get_or_404(user_id)
    new_password = (request.form.get('new_password') or '123456789').strip()
    if len(new_password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin.portal_user_list'))
    try:
        u.password_hash  = _bcrypt_hash(new_password)
    except RuntimeError as e:
        flash(str(e), 'danger')
        return redirect(url_for('admin.portal_user_list'))
    u.vault_password = new_password
    db.session.commit()

    log_activity('portal_user_password_reset',
                 f'Reset portal password for username={u.username}')
    flash(f'Password for "{u.username}" reset to: {new_password}', 'success')
    return redirect(url_for('admin.portal_user_list'))


# ═══════════════════════════════════════════════════════════════════════════
#  BULK OPERATIONS on client_users
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route('/portal-users/bulk', methods=['POST'])
def portal_user_bulk():
    """
    Apply one of several bulk actions to a selected set (or all) of client_users.
      action = 'reset-password'   → reset to ?new_password=… (defaults to 123456789)
      action = 'deactivate'       → set is_active = False
      action = 'activate'         → set is_active = True
      action = 'sync-phones'      → pull last 10 digits of contact_phone from each
                                    establishment; skip rows where the resulting
                                    phone collides with another client_user

    Selection: form fields user_ids[] (list of integer IDs).  If empty AND
    `select_all=1` is present, applies to ALL client_users.
    """
    action       = (request.form.get('action') or '').strip()
    new_password = (request.form.get('new_password') or '123456789').strip()
    select_all   = request.form.get('select_all') == '1'
    raw_ids      = request.form.getlist('user_ids[]') or request.form.getlist('user_ids')

    q = ClientUser.query
    if not select_all:
        try:
            ids = [int(x) for x in raw_ids if x.strip()]
        except ValueError:
            flash('Invalid user ID in selection.', 'danger')
            return redirect(url_for('admin.portal_user_list'))
        if not ids:
            flash('No users selected.  Tick the rows you want to change, '
                  'or use "Apply to all" for a global action.', 'warning')
            return redirect(url_for('admin.portal_user_list'))
        q = q.filter(ClientUser.id.in_(ids))

    users = q.all()
    if not users:
        flash('No matching users found.', 'warning')
        return redirect(url_for('admin.portal_user_list'))

    n_changed = 0
    n_skipped = 0

    if action == 'reset-password':
        if len(new_password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('admin.portal_user_list'))
        try:
            pwd_hash = _bcrypt_hash(new_password)
        except RuntimeError as e:
            flash(str(e), 'danger')
            return redirect(url_for('admin.portal_user_list'))
        for u in users:
            u.password_hash = pwd_hash
            u.vault_password = new_password
            n_changed += 1
        log_activity('portal_user_bulk_reset_password',
                     f'Bulk-reset password for {n_changed} client_users')
        flash(f'Reset password for {n_changed} login(s) to: {new_password}', 'success')

    elif action in ('deactivate', 'activate'):
        target = (action == 'activate')
        for u in users:
            if u.is_active != target:
                u.is_active = target
                n_changed += 1
        verb = 'Activated' if target else 'Deactivated'
        log_activity(f'portal_user_bulk_{action}',
                     f'{verb} {n_changed} client_users')
        flash(f'{verb} {n_changed} login(s).', 'success')

    elif action == 'sync-phones':
        # Pull each establishment's contact_phone and stamp it onto the linked
        # client_user — skipping rows where the resulting number would collide
        # with another row.
        est_phones = dict(
            db.session.query(Establishment.id, Establishment.contact_phone).all()
        )
        for u in users:
            raw = est_phones.get(u.establishment_id) or ''
            digits = ''.join(ch for ch in raw if ch.isdigit())
            if len(digits) > 10:
                digits = digits[-10:]
            if len(digits) != 10:
                n_skipped += 1
                continue
            if digits == (u.phone or ''):
                continue  # already in sync
            clash = ClientUser.query.filter(
                ClientUser.phone == digits, ClientUser.id != u.id
            ).first()
            if clash:
                n_skipped += 1
                continue
            u.phone = digits
            n_changed += 1
        log_activity('portal_user_bulk_sync_phones',
                     f'Synced phones for {n_changed} client_users '
                     f'(skipped {n_skipped})')
        flash(f'Synced phones for {n_changed} login(s). '
              f'Skipped {n_skipped} (no clean 10-digit phone or duplicate).',
              'success' if n_changed else 'warning')

    else:
        flash(f'Unknown bulk action: "{action}"', 'danger')
        return redirect(url_for('admin.portal_user_list'))

    db.session.commit()
    return redirect(url_for('admin.portal_user_list'))


@admin_bp.route('/portal-users/<int:user_id>/toggle-active', methods=['POST'])
def portal_user_toggle_active(user_id):
    """
    Flip is_active in one click — used by the inline toggle switch in the
    portal users table.  Returns JSON for the inline JS handler.
    """
    u = ClientUser.query.get_or_404(user_id)
    u.is_active = not u.is_active
    db.session.commit()
    log_activity('portal_user_toggle_active',
                 ("Activated" if u.is_active else "Deactivated") +
                 f" portal login for username={u.username}")
    return jsonify({
        'ok':        True,
        'id':        u.id,
        'is_active': u.is_active,
    })


# ═══════════════════════════════════════════════════════════════════════════
#  ASSIGN CLIENTS  —  admin picks any establishments and gives them to any
#  staff in one shot.  Unlike /admin/reassign which is per-source-staff,
#  this page lists ALL establishments with their current assignee and lets
#  the admin filter by "Unassigned", a specific staff, or "All".
# ═══════════════════════════════════════════════════════════════════════════

from app.models.assignment_log import EstablishmentAssignmentLog  # safe re-import

@admin_bp.route('/assign-clients', methods=['GET'])
def assign_clients_list():
    """
    List every active establishment with its current assignee (or "Unassigned")
    plus controls for filtering and bulk-assigning.
    """
    flt = (request.args.get('filter') or 'all').strip()  # all | unassigned | <clerk_user_id>
    search = (request.args.get('q') or '').strip().lower()

    q = Establishment.query.filter(Establishment.is_active == True)

    if flt == 'unassigned':
        q = q.filter((Establishment.assigned_to_id == None) | (Establishment.assigned_to_id == ''))
    elif flt and flt != 'all':
        q = q.filter(Establishment.assigned_to_id == flt)

    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(
            db.func.lower(Establishment.company_name).like(like),
            db.func.lower(db.func.coalesce(Establishment.branch_name, '')).like(like),
            db.func.lower(db.func.coalesce(Establishment.pf_code, '')).like(like),
            db.func.lower(db.func.coalesce(Establishment.esic_code, '')).like(like),
        ))

    ests = q.order_by(Establishment.company_name, Establishment.branch_name).all()

    # Build clerk_user_id → AppUser map so we can show the current assignee name
    all_staff = AppUser.query.filter(AppUser.is_active == True).order_by(AppUser.name).all()
    staff_by_id = {s.clerk_user_id: s for s in all_staff}

    # Stats for the filter bar
    total = Establishment.query.filter(Establishment.is_active == True).count()
    unassigned_count = Establishment.query.filter(
        Establishment.is_active == True,
        ((Establishment.assigned_to_id == None) | (Establishment.assigned_to_id == ''))
    ).count()

    return render_template('admin/assign_clients.html',
                           ests=ests,
                           staff=all_staff,
                           staff_by_id=staff_by_id,
                           current_filter=flt,
                           search=search,
                           total=total,
                           unassigned_count=unassigned_count)


@admin_bp.route('/assign-clients', methods=['POST'])
def assign_clients_apply():
    """
    Apply the bulk-assign action.  Form fields:
      - est_ids[]     list of establishment IDs (or single est_ids)
      - to_user_id    destination clerk_user_id  (use empty/UNASSIGN to clear)
      - reason        optional free text
      - return_to     filter to redirect back to
    """
    raw_ids = request.form.getlist('est_ids[]') or request.form.getlist('est_ids')
    to_id   = (request.form.get('to_user_id') or '').strip()
    reason  = (request.form.get('reason') or '').strip()
    return_to = (request.form.get('return_to') or 'all').strip()

    try:
        ids = [int(x) for x in raw_ids if x.strip()]
    except ValueError:
        flash('Invalid establishment ID in selection.', 'danger')
        return redirect(url_for('admin.assign_clients_list', filter=return_to))

    if not ids:
        flash('No establishments selected.  Tick the rows you want to assign first.', 'warning')
        return redirect(url_for('admin.assign_clients_list', filter=return_to))

    # Destination — empty / "UNASSIGN" clears the assignment
    to_user = None
    clear_mode = (to_id == '' or to_id.lower() == 'unassign')
    if not clear_mode:
        to_user = AppUser.query.filter_by(clerk_user_id=to_id, is_active=True).first()
        if not to_user:
            flash('Destination staff not found or inactive.', 'danger')
            return redirect(url_for('admin.assign_clients_list', filter=return_to))

    # Admin who's performing the change — for the audit log
    performer = AppUser.query.filter_by(clerk_user_id=current_user_id()).first()
    performer_name = (performer.name or performer.email) if performer else None

    moved = 0
    unchanged = 0
    for est_id in ids:
        est = Establishment.query.get(est_id)
        if not est:
            continue

        new_assignee = None if clear_mode else to_user.clerk_user_id
        if (est.assigned_to_id or None) == new_assignee:
            unchanged += 1
            continue

        # Resolve the FROM name for the log
        from_name = '—'
        if est.assigned_to_id:
            from_user = AppUser.query.filter_by(clerk_user_id=est.assigned_to_id).first()
            if from_user:
                from_name = from_user.name or from_user.email

        log = EstablishmentAssignmentLog(
            establishment_id   = est.id,
            from_user_id       = est.assigned_to_id,
            from_user_name     = from_name if est.assigned_to_id else 'Unassigned',
            to_user_id         = new_assignee,
            to_user_name       = (to_user.name or to_user.email) if to_user else 'Unassigned',
            performed_by_id    = current_user_id(),
            performed_by_name  = performer_name,
            performed_by_role  = 'admin',
            reason             = reason or None,
        )
        db.session.add(log)

        est.assigned_to_id = new_assignee
        moved += 1

    db.session.commit()
    log_activity('admin_bulk_assign_clients',
                 f'Assigned {moved} establishment(s) to '
                 f'{(to_user.name or to_user.email) if to_user else "(Unassigned)"}'
                 f' [unchanged: {unchanged}]')

    if moved:
        target = (to_user.name or to_user.email) if to_user else 'Unassigned'
        flash(f'Successfully assigned {moved} establishment(s) to {target}.'
              + (f'  ({unchanged} already had this assignment.)' if unchanged else ''),
              'success')
    else:
        flash(f'No changes — {unchanged} establishment(s) already had this assignment.', 'info')

    return redirect(url_for('admin.assign_clients_list', filter=return_to))
