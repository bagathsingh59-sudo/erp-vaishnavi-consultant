"""
Authentication Routes (self-hosted JWT)
=======================================
Email + password sign-in, logout, silent refresh, and forced password change.
Tokens live in httpOnly cookies set/cleared here (see app/jwt_auth.py).
"""

from flask import (Blueprint, render_template, redirect, url_for, session, g,
                   jsonify, request, flash, make_response)
from datetime import datetime

from app import db
from app.models.app_user import AppUser
from app.jwt_auth import (
    REFRESH_COOKIE, create_access_token, issue_refresh_token,
    validate_refresh_token, revoke_refresh_token, set_auth_cookies,
    clear_auth_cookies,
)

auth_bp = Blueprint('auth', __name__)


def _safe_next(default_endpoint='establishment.dashboard'):
    """Return a safe local redirect target from ?next=, else the dashboard."""
    nxt = request.args.get('next') or request.form.get('next') or ''
    # Only allow same-site relative paths (no scheme/host) to avoid open redirect.
    if nxt.startswith('/') and not nxt.startswith('//'):
        return nxt
    return url_for(default_endpoint)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login_page():
    """Show the sign-in form (GET) and authenticate (POST)."""
    # Already signed in? Go to dashboard.
    if getattr(g, 'clerk_user', None) and g.clerk_user.get('user_id') not in (None, 'dev-user'):
        return redirect(url_for('establishment.dashboard'))

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''

        if not email or not password:
            flash('Please enter your email and password.', 'warning')
            return render_template('auth/login.html', email=email), 400

        user = AppUser.query.filter(
            db.func.lower(AppUser.email) == email
        ).first()

        if not user or not user.is_active or not user.check_password(password):
            flash('Invalid email or password.', 'danger')
            return render_template('auth/login.html', email=email), 401

        # ── Success — issue tokens and set cookies on a redirect ──
        user.last_login_at = datetime.utcnow()
        db.session.commit()

        access = create_access_token(user)
        refresh = issue_refresh_token(user)

        target = (url_for('auth.change_password')
                  if user.must_change_password else _safe_next())
        resp = make_response(redirect(target))
        set_auth_cookies(resp, access, refresh)
        return resp

    return render_template('auth/login.html', email='')


@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    """Revoke the refresh token, clear cookies, and return to login."""
    revoke_refresh_token(request.cookies.get(REFRESH_COOKIE, ''))
    session.clear()
    resp = make_response(redirect(url_for('auth.login_page')))
    clear_auth_cookies(resp)
    flash('You have been signed out.', 'info')
    return resp


@auth_bp.route('/refresh', methods=['POST'])
def refresh():
    """Renew the access token from a valid refresh cookie (the before_request
    hook also does this automatically). Returns JSON; useful for XHR callers."""
    uid = validate_refresh_token(request.cookies.get(REFRESH_COOKIE, ''))
    if not uid:
        resp = make_response(jsonify({'ok': False, 'error': 'invalid_refresh'}), 401)
        clear_auth_cookies(resp)
        return resp
    user = AppUser.query.filter_by(clerk_user_id=uid).first()
    if not user or not user.is_active:
        resp = make_response(jsonify({'ok': False, 'error': 'inactive'}), 401)
        clear_auth_cookies(resp)
        return resp
    access = create_access_token(user)
    resp = make_response(jsonify({'ok': True}))
    set_auth_cookies(resp, access)   # access only; refresh cookie unchanged
    return resp


@auth_bp.route('/change-password', methods=['GET', 'POST'])
def change_password():
    """Set a new password. Used both for the forced first-login reset and for
    voluntary changes from the profile menu."""
    user = getattr(g, 'clerk_user', None)
    if not user or user.get('user_id') in (None, 'dev-user', 'internal-portal'):
        return redirect(url_for('auth.login_page'))

    app_user = AppUser.query.filter_by(clerk_user_id=user['user_id']).first()
    if not app_user:
        return redirect(url_for('auth.login_page'))

    forced = app_user.must_change_password

    if request.method == 'POST':
        current = request.form.get('current_password') or ''
        new = request.form.get('new_password') or ''
        confirm = request.form.get('confirm_password') or ''

        # On a forced first-login reset we skip the current-password check only
        # if they were given a temp password they may not remember typing here;
        # but we still require it to be correct for safety.
        if not app_user.check_password(current):
            flash('Your current password is incorrect.', 'danger')
            return render_template('auth/change_password.html', forced=forced), 400
        if len(new) < 8:
            flash('New password must be at least 8 characters.', 'warning')
            return render_template('auth/change_password.html', forced=forced), 400
        if new != confirm:
            flash('New password and confirmation do not match.', 'warning')
            return render_template('auth/change_password.html', forced=forced), 400
        if new == current:
            flash('New password must be different from the current one.', 'warning')
            return render_template('auth/change_password.html', forced=forced), 400

        app_user.set_password(new)
        app_user.must_change_password = False
        app_user.temp_password = None      # wipe the visible temp password
        db.session.commit()

        flash('Your password has been updated.', 'success')
        return redirect(url_for('establishment.dashboard'))

    return render_template('auth/change_password.html', forced=forced)


@auth_bp.route('/debug-user')
def debug_user():
    """Debug endpoint — shows the current user context."""
    user = getattr(g, 'clerk_user', None)
    from app.user_context import current_user_id, is_admin, get_user_est_ids
    return jsonify({
        'current_user': user,
        'current_user_id': current_user_id(),
        'is_admin': is_admin(),
        'user_est_ids': get_user_est_ids(),
    })
