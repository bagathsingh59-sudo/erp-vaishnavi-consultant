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
# Shows each staff's client load, filing compliance %, fees collected
# ═════════════════════════════════════════════════════════════════
@admin_bp.route('/staff-performance')
def staff_performance():
    """Performance dashboard for all staff — admin's primary monitoring tool."""
    from app.models.establishment import Establishment
    from app.models.payroll import MonthlyPayroll
    from app.models.accounts import Voucher, VoucherEntry, AccountHead
    from datetime import date

    # All active users (both admin + regular, so admin also sees own load)
    users = AppUser.query.filter_by(is_active=True).order_by(AppUser.name).all()

    # Current FY for performance window
    today = date.today()
    fy_start_year = today.year if today.month >= 4 else today.year - 1
    fy_start = date(fy_start_year, 4, 1)
    fy_end = date(fy_start_year + 1, 3, 31)
    fy_label = f'{fy_start_year}-{fy_start_year + 1}'

    # For fees collected — we compute per staff
    fee_heads = AccountHead.query.filter(
        AccountHead.name.in_(['Professional Fees', 'IP & UAN Charges', 'Other Income'])
    ).all()
    fee_head_ids = [h.id for h in fee_heads]

    staff_metrics = []
    unassigned_count = Establishment.query.filter(
        Establishment.is_active == True,
        Establishment.assigned_to_id.is_(None)
    ).count()

    total_active_est = Establishment.query.filter_by(is_active=True).count()

    for user in users:
        # Establishments assigned to this user
        assigned_ests = Establishment.query.filter(
            Establishment.is_active == True,
            Establishment.assigned_to_id == user.clerk_user_id,
        ).all()
        est_count = len(assigned_ests)

        # Filing compliance — count finalized monthly payrolls in FY
        fully_filed = 0
        partial_filed = 0
        not_filed = 0

        for est in assigned_ests:
            # Has any finalized payroll in this FY?
            finalized_count = MonthlyPayroll.query.filter(
                MonthlyPayroll.establishment_id == est.id,
                MonthlyPayroll.status == 'finalized',
                MonthlyPayroll.year == fy_start_year,
            ).count() + MonthlyPayroll.query.filter(
                MonthlyPayroll.establishment_id == est.id,
                MonthlyPayroll.status == 'finalized',
                MonthlyPayroll.year == fy_start_year + 1,
                MonthlyPayroll.month <= 3,
            ).count()

            # Rough classification
            if finalized_count >= 9:
                fully_filed += 1
            elif finalized_count >= 3:
                partial_filed += 1
            else:
                not_filed += 1

        # Compliance %
        if est_count > 0:
            compliance_pct = round((fully_filed / est_count) * 100)
        else:
            compliance_pct = None

        # Fees collected by this staff (vouchers created by them, fee account credits)
        fees_collected = 0
        if fee_head_ids:
            q = db.session.query(db.func.sum(VoucherEntry.amount))\
                .join(Voucher, VoucherEntry.voucher_id == Voucher.id)\
                .filter(
                    VoucherEntry.account_id.in_(fee_head_ids),
                    VoucherEntry.entry_type == 'credit',
                    Voucher.voucher_date >= fy_start,
                    Voucher.voucher_date <= fy_end,
                    Voucher.owner_id == user.clerk_user_id,
                )
            fees_collected = q.scalar() or 0

        # Grade
        if compliance_pct is None:
            grade = 'new'
            grade_label = 'No Assignment'
            grade_color = '#94a3b8'
        elif compliance_pct >= 90:
            grade = 'excellent'
            grade_label = 'Excellent'
            grade_color = '#16a34a'
        elif compliance_pct >= 70:
            grade = 'moderate'
            grade_label = 'Moderate'
            grade_color = '#f59e0b'
        else:
            grade = 'attention'
            grade_label = 'Needs Attention'
            grade_color = '#dc2626'

        staff_metrics.append({
            'user': user,
            'est_count': est_count,
            'fully_filed': fully_filed,
            'partial_filed': partial_filed,
            'not_filed': not_filed,
            'compliance_pct': compliance_pct,
            'fees_collected': fees_collected,
            'grade': grade,
            'grade_label': grade_label,
            'grade_color': grade_color,
            'avg_per_client': round(fees_collected / est_count) if est_count > 0 else 0,
        })

    # Sort by compliance % descending (best performer first)
    staff_metrics.sort(key=lambda m: m['compliance_pct'] if m['compliance_pct'] is not None else -1,
                       reverse=True)

    return render_template('admin/staff_performance.html',
                           staff_metrics=staff_metrics,
                           fy_label=fy_label,
                           unassigned_count=unassigned_count,
                           total_active_est=total_active_est,
                           total_staff=len(users))


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
