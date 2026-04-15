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
