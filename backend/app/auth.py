"""
Self-hosted JWT Authentication for Vaishnavi Consultant ERP
============================================================
Replaces the previous Clerk integration. The ERP now issues and verifies its
own tokens (see app/jwt_auth.py):

  1. User signs in at /login with email + password → we set two httpOnly
     cookies: a short-lived access JWT and a long-lived rotating refresh token.
  2. On every request we verify the access cookie. If it has expired we
     transparently rotate the refresh cookie and mint a fresh access token —
     so users are never bounced to /login mid-form while their refresh token
     is still valid.
  3. The authenticated user is exposed as g.clerk_user (name kept for template
     compatibility) — a plain dict: {user_id, name, email, role, is_admin}.
  4. Logout revokes the refresh token and clears both cookies.
"""

import os
import time
import functools

from flask import g, redirect, url_for, request, flash, session

from app.jwt_auth import (
    ACCESS_COOKIE, REFRESH_COOKIE,
    decode_access_token, validate_refresh_token,
    create_access_token, set_auth_cookies,
)


def _build_user_dict(app_user):
    """Shape an AppUser into the g.clerk_user dict the templates expect."""
    return {
        'user_id': app_user.clerk_user_id,
        'name': app_user.name or app_user.email or 'User',
        'email': app_user.email or '',
        'image_url': '',
        'role': app_user.role,
        'is_admin': (app_user.role == 'admin'),
    }


def _load_active_user(uid):
    """Fetch an active AppUser by uid, or None."""
    if not uid:
        return None
    from app.models.app_user import AppUser
    app_user = AppUser.query.filter_by(clerk_user_id=uid).first()
    if not app_user or not app_user.is_active:
        return None
    return app_user


def init_auth(app):
    """Wire authentication into the Flask app (before/after request hooks)."""

    # Endpoints reachable WITHOUT authentication.
    PUBLIC_ENDPOINTS = {
        'auth.login_page', 'auth.logout', 'auth.refresh', 'auth.debug_user',
        'api_docs.test_db_connection', 'api_docs.api_route_list',
        'seo.robots_txt', 'seo.sitemap_xml',
        'marketing.home', 'marketing.landing', 'marketing.about',
        '_healthz', 'static',
    }
    PUBLIC_PATHS = {'/', '/landing', '/about', '/healthz'}

    @app.before_request
    def check_auth():
        g.clerk_user = None          # legacy name kept for templates
        g.is_internal = False
        g._auth_new_access = None    # set when we auto-refresh (after_request reads it)
        session.permanent = True

        # ── Internal service-to-service bypass (Client Portal) ──
        internal_key = os.getenv('INTERNAL_API_KEY', '')
        header_key = request.headers.get('X-Internal-Api-Key', '')
        if internal_key and header_key and header_key == internal_key:
            g.clerk_user = {
                'user_id': 'internal-portal',
                'name': 'Client Portal (Internal)',
                'email': 'portal@internal',
                'image_url': '',
                'role': 'admin',
                'is_admin': True,
            }
            g.is_internal = True
            return

        # ── Skip auth for public surface, static, health, SEO, docs ──
        ep = request.endpoint or ''
        if (ep in PUBLIC_ENDPOINTS or
                request.path in PUBLIC_PATHS or
                request.path.startswith('/static/') or
                ep.startswith('flasgger.')):
            return

        # ── Optional local-dev open mode (never on in production) ──
        if os.getenv('AUTH_DEV_OPEN', '').lower() in ('1', 'true', 'yes'):
            g.clerk_user = {
                'user_id': 'dev-user', 'name': 'Dev User', 'email': 'dev@local',
                'image_url': '', 'role': 'admin', 'is_admin': True,
            }
            return

        # ── Verify the access cookie ──
        app_user = None
        payload = decode_access_token(request.cookies.get(ACCESS_COOKIE, ''))
        if payload:
            app_user = _load_active_user(payload.get('sub'))

        # ── Access expired/missing → renew from the refresh cookie ──
        # We validate (and slide) the refresh token WITHOUT rotating it, then
        # mint a fresh access token. Not rotating keeps concurrent requests
        # right after expiry from tripping false re-use detection.
        if not app_user:
            uid = validate_refresh_token(request.cookies.get(REFRESH_COOKIE, ''))
            if uid:
                app_user = _load_active_user(uid)
                if app_user:
                    g._auth_new_access = create_access_token(app_user)

        # ── Still no user → redirect to login ──
        if not app_user:
            if request.method == 'POST':
                flash('Your session expired. Please sign in again.', 'warning')
            return redirect(url_for('auth.login_page', next=request.path))

        g.clerk_user = _build_user_dict(app_user)
        g._app_user = app_user  # prime user_context cache

        # ── Force a password change before anything else if flagged ──
        if app_user.must_change_password and ep not in (
                'auth.change_password', 'auth.logout'):
            return redirect(url_for('auth.change_password'))

    @app.after_request
    def _apply_refreshed_cookies(resp):
        """If we renewed the access token this request, push the new cookie."""
        new_access = getattr(g, '_auth_new_access', None)
        if new_access:
            set_auth_cookies(resp, new_access)   # access only; refresh unchanged
        return resp

    @app.context_processor
    def inject_clerk_user():
        # `clerk_user` template var kept for compatibility across all templates.
        return dict(clerk_user=getattr(g, 'clerk_user', None))


# ─── Route Protection Decorators ─────────────────────────────────
def login_required(f):
    """Route requires any authenticated user (admin or user)."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not getattr(g, 'clerk_user', None):
            flash('Please sign in to continue.', 'warning')
            return redirect(url_for('auth.login_page'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Route requires admin role."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not getattr(g, 'clerk_user', None):
            flash('Please sign in to continue.', 'warning')
            return redirect(url_for('auth.login_page'))
        from app.user_context import is_admin
        if not is_admin():
            flash('Admin access required.', 'danger')
            return redirect(url_for('establishment.dashboard'))
        return f(*args, **kwargs)
    return decorated
