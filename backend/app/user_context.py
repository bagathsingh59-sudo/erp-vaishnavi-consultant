"""
User Context & Data Isolation Module
======================================
Provides helper functions for multi-user data isolation with admin/user roles.

Rules:
- Admin users see ALL data (no owner_id filter)
- Regular users see ONLY their own data (filtered by owner_id)
- Dev mode (no Clerk): Runs with owner_id='dev-user' as admin

All data traces through Establishment.owner_id:
  Establishment (owner_id) -> Employee, Payroll, PayrollEntry, Voucher, etc.

Usage in routes:
  from app.user_context import current_user_id, is_admin, user_establishments, verify_est_ownership
"""

from flask import g, abort


def current_user_id():
    """Get the current authenticated user's Clerk user_id"""
    user = getattr(g, 'clerk_user', None)
    if not user:
        return None
    return user.get('user_id', None)


def current_user_name():
    """Get the current user's display name"""
    user = getattr(g, 'clerk_user', None)
    if not user:
        return 'System'
    return user.get('name', user.get('email', 'User'))


def current_app_user():
    """Look up the AppUser record for the current clerk user, cached on g."""
    cached = getattr(g, '_app_user', None)
    if cached is not None:
        return cached

    uid = current_user_id()
    if not uid:
        return None

    from app.models.app_user import AppUser
    app_user = AppUser.query.filter_by(clerk_user_id=uid).first()
    g._app_user = app_user
    return app_user


def is_admin():
    """Check if the current user has admin role.
    Falls back to g.clerk_user['is_admin'] for dev-user compatibility.
    """
    app_user = current_app_user()
    if app_user:
        return app_user.role == 'admin'

    # Fallback for dev-user or cases where AppUser doesn't exist yet
    user = getattr(g, 'clerk_user', None)
    if user:
        return user.get('is_admin', False)
    return False


def user_establishments(query=None):
    """
    Filter Establishment query based on role.
    Admin: return ALL establishments (no filter).
    User: return establishments where they are the CREATOR or the current HANDLER.

    A user sees an establishment if:
      - they created it (owner_id = uid), OR
      - admin has assigned it to them (assigned_to_id = uid)
    """
    from app.models.establishment import Establishment
    from sqlalchemy import or_
    if query is None:
        query = Establishment.query

    if is_admin():
        return query  # Admin sees everything

    uid = current_user_id()
    if uid:
        # Users see establishments they created OR that have been assigned to them
        return query.filter(or_(
            Establishment.owner_id == uid,
            Establishment.assigned_to_id == uid,
        ))
    else:
        return query.filter(Establishment.owner_id == '__none__')  # No data


def user_vouchers(query=None):
    """
    Filter Voucher query based on role.
    Admin: return ALL vouchers.
    User: return only owned vouchers.
    """
    from app.models.accounts import Voucher
    if query is None:
        query = Voucher.query

    if is_admin():
        return query  # Admin sees everything

    uid = current_user_id()
    if uid:
        return query.filter(Voucher.owner_id == uid)
    else:
        return query.filter(Voucher.owner_id == '__none__')


def verify_est_ownership(establishment):
    """
    Verify that the current user can access the given establishment.
    Admin: always True.
    User: access allowed if they CREATED it (owner_id) OR admin assigned it to them (assigned_to_id).
    """
    if is_admin():
        return True

    uid = current_user_id()
    if not uid:
        abort(403)

    # User is allowed if they are the creator OR the current handler
    if establishment.owner_id == uid:
        return True
    if getattr(establishment, 'assigned_to_id', None) == uid:
        return True

    abort(403)


def verify_voucher_ownership(voucher):
    """
    Verify that the current user can access the given voucher.
    Admin: always True.
    User: checks owner_id match.
    """
    if is_admin():
        return True

    uid = current_user_id()
    if not uid or voucher.owner_id != uid:
        abort(403)
    return True


def get_user_est_ids():
    """
    Get list of establishment IDs accessible to the current user.
    Admin: return ALL establishment IDs.
    User: return those they CREATED or that are currently ASSIGNED to them.

    This is used to scope Employees, Payrolls, Vouchers, etc. — anything
    that has an establishment_id foreign key. Including assigned_to_id
    here means staff members can work on clients transferred to them.
    """
    from app.models.establishment import Establishment
    from sqlalchemy import or_

    if is_admin():
        return [e.id for e in Establishment.query.with_entities(Establishment.id).all()]

    uid = current_user_id()
    if uid:
        rows = Establishment.query.filter(or_(
            Establishment.owner_id == uid,
            Establishment.assigned_to_id == uid,
        )).with_entities(Establishment.id).all()
        return [e.id for e in rows]
    return []


def set_owner(obj):
    """
    Set owner_id on a new object (Establishment or Voucher).
    Call this before db.session.add().
    """
    uid = current_user_id()
    if uid:
        obj.owner_id = uid
    return obj


def ensure_est_selected_for_user():
    """
    Enforce establishment selection for NON-ADMIN users on client-scoped pages.

    Behavior:
      - Admin: always returns None (no-op; admin uses session OR global views).
      - User WITH session['selected_est_id']: returns None (pass through).
      - User WITHOUT session but URL has ?establishment=X: sets session, pass through.
      - User WITHOUT session AND only 1 accessible establishment: auto-select.
      - User WITHOUT session AND multiple establishments: redirect to selection.
      - User WITHOUT session AND zero establishments: redirect with warning.

    Use as a Flask blueprint before_request handler:
      @some_bp.before_request
      def _require_est():
          return ensure_est_selected_for_user()
    """
    from flask import session, request, flash, redirect, url_for

    # Admin is never constrained
    if is_admin():
        return None

    # Already have a selected establishment — pass through
    if session.get('selected_est_id'):
        return None

    # Fallback: URL query param carries the establishment id
    url_est = request.args.get('establishment') or request.form.get('establishment')
    if url_est and str(url_est).isdigit():
        session['selected_est_id'] = int(url_est)
        return None

    # Session missing and no URL hint — check accessible count
    user_ids = get_user_est_ids()
    if len(user_ids) == 0:
        flash('No establishments are assigned to you yet. Please contact admin.', 'warning')
        return redirect(url_for('establishment.establishment_list'))
    elif len(user_ids) == 1:
        # Only 1 establishment — auto-select it silently
        session['selected_est_id'] = user_ids[0]
        return None
    else:
        # Multiple — user must explicitly pick one
        flash('Please click on an establishment first to work on it.', 'info')
        return redirect(url_for('establishment.establishment_list'))


def log_activity(action, entity_type, entity_id=None, entity_name=None,
                 details=None, establishment_id=None):
    """
    Log an activity to the audit trail.
    """
    try:
        from app import db
        from app.models.activity_log import ActivityLog

        uid = current_user_id()
        uname = current_user_name()

        log = ActivityLog(
            user_id=uid,
            user_name=uname,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            details=details,
            establishment_id=establishment_id
        )
        db.session.add(log)
        # Don't commit here -- caller's commit will include this
    except Exception:
        pass  # Never let logging break the main operation
