"""
Authentication Routes
=====================
Login page with Clerk JS widget.
Logout is handled by Clerk JS on the frontend (clears __session cookie).
"""

from flask import Blueprint, render_template, redirect, url_for, session, g, jsonify
import os

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/debug-user')
def debug_user():
    """Debug endpoint — shows current user context"""
    user = getattr(g, 'clerk_user', None)
    from app.user_context import current_user_id, is_admin, get_user_est_ids
    from app.models.establishment import Establishment
    all_est = Establishment.query.all()
    return jsonify({
        'clerk_user': user,
        'current_user_id': current_user_id(),
        'is_admin': is_admin(),
        'user_est_ids': get_user_est_ids(),
        'all_establishments_in_db': [
            {'id': e.id, 'name': e.company_name, 'owner_id': e.owner_id}
            for e in all_est
        ]
    })


@auth_bp.route('/login')
def login_page():
    """
    Show login page with Clerk SignIn widget.
    If already logged in, redirect to dashboard.
    """
    # If already authenticated, go to dashboard
    user = getattr(g, 'clerk_user', None)
    if user and user.get('user_id') and user['user_id'] != 'dev-user':
        return redirect(url_for('establishment.dashboard'))

    clerk_pub_key = os.getenv('CLERK_PUBLISHABLE_KEY', '')
    return render_template('auth/login.html', clerk_pub_key=clerk_pub_key)


@auth_bp.route('/logout')
def logout_page():
    """
    Logout page — shows a simple page that calls Clerk.signOut()
    to properly clear the __session cookie and sign out.
    """
    # Clear Flask session
    session.clear()

    clerk_pub_key = os.getenv('CLERK_PUBLISHABLE_KEY', '')
    return render_template('auth/logout.html', clerk_pub_key=clerk_pub_key)
