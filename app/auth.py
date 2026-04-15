"""
Clerk Authentication Module for Vaishnavi Consultant ERP
=========================================================
Simplified: Let Clerk handle ALL token management.
Flask just reads __session cookie and verifies via Clerk JWKS.

How it works:
1. User logs in via Clerk JS widget on the frontend
2. Clerk sets a __session cookie in the browser
3. On every request, Flask reads this cookie and verifies the JWT
4. If valid → user info is stored in g.clerk_user
5. If invalid → redirect to /login
6. Logout → Clerk JS handles signOut (clears __session cookie)
"""

import os
import json
import time
import functools
import jwt
import requests
from flask import g, redirect, url_for, request, flash, session, current_app


# ─── JWKS Cache (Clerk's public keys) ────────────────────────────
_jwks_cache = {'keys': None, 'fetched_at': 0}
JWKS_CACHE_TTL = 3600  # Refresh every 1 hour


def _get_clerk_jwks():
    """Fetch Clerk's public keys (JWKS) for JWT verification"""
    now = time.time()
    if _jwks_cache['keys'] and (now - _jwks_cache['fetched_at']) < JWKS_CACHE_TTL:
        return _jwks_cache['keys']

    secret_key = os.getenv('CLERK_SECRET_KEY', '')
    if not secret_key:
        return None

    try:
        headers = {'Authorization': f'Bearer {secret_key}'}
        resp = requests.get('https://api.clerk.com/v1/jwks', headers=headers, timeout=3)
        if resp.status_code == 200:
            _jwks_cache['keys'] = resp.json().get('keys', [])
            _jwks_cache['fetched_at'] = now
            return _jwks_cache['keys']
    except Exception as e:
        print(f'[AUTH] JWKS fetch error: {e}')

    return _jwks_cache.get('keys')


def _get_signing_key(token):
    """Get the correct RSA public key to verify the JWT"""
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get('kid')
        jwks = _get_clerk_jwks()
        if not jwks:
            return None

        for key_data in jwks:
            if key_data.get('kid') == kid:
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
        return None
    except Exception:
        return None


def verify_clerk_session(token):
    """
    Verify the __session cookie JWT from Clerk.
    Returns decoded payload if valid, None if invalid/expired.
    Clerk manages all token refresh — we just verify.
    """
    if not token:
        return None

    try:
        signing_key = _get_signing_key(token)
        if not signing_key:
            return None

        payload = jwt.decode(
            token,
            signing_key,
            algorithms=['RS256'],
            options={
                'verify_exp': True,
                'verify_iat': True,
                'verify_nbf': True,
            }
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception:
        return None


def get_user_from_clerk_api(user_id):
    """
    Fetch full user details from Clerk Backend API.
    Returns dict with: user_id, role, name, email, image_url, is_admin
    """
    secret_key = os.getenv('CLERK_SECRET_KEY', '')
    if not secret_key or not user_id:
        return None

    try:
        headers = {'Authorization': f'Bearer {secret_key}'}
        resp = requests.get(
            f'https://api.clerk.com/v1/users/{user_id}',
            headers=headers,
            timeout=3
        )
        if resp.status_code == 200:
            data = resp.json()
            first = data.get('first_name', '') or ''
            last = data.get('last_name', '') or ''
            name = f'{first} {last}'.strip() or data.get('username', '') or 'User'
            email_list = data.get('email_addresses', [])
            email = email_list[0]['email_address'] if email_list else ''

            return {
                'user_id': user_id,
                'name': name,
                'email': email,
                'image_url': data.get('image_url', ''),
            }
    except Exception as e:
        print(f'[AUTH] User fetch error: {e}')

    return None


# ─── User Details Cache & Rate Limiter ────────────────────────────
# Prevents excessive Clerk API calls and infinite loops.
# Clerk free tier allows ~100 API calls/min.
_user_cache = {}
_user_cache_ttl = 1800  # 30 minutes — cache user info to avoid repeated calls during idle

# Rate limiter: max N Clerk API calls per minute
_api_call_log = []  # list of timestamps
_API_RATE_LIMIT = 30  # Max 30 calls per minute (well under Clerk's 100/min limit)
_API_RATE_WINDOW = 60  # seconds


def _check_rate_limit():
    """Check if we're within Clerk API rate limits. Returns True if OK to call."""
    now = time.time()
    # Remove old entries outside the window
    _api_call_log[:] = [t for t in _api_call_log if (now - t) < _API_RATE_WINDOW]
    if len(_api_call_log) >= _API_RATE_LIMIT:
        print(f'[AUTH] Rate limit reached ({_API_RATE_LIMIT} calls/min). Using cache.')
        return False
    return True


def _log_api_call():
    """Record an API call timestamp"""
    _api_call_log.append(time.time())


def _get_cached_user(user_id):
    """
    Get user details with caching + rate limiting.
    - Serves from cache if within TTL (5 min)
    - Respects Clerk API rate limits (30/min)
    - Returns stale cache if API fails or rate limited
    - Never creates infinite loops (single API call, no recursion)
    """
    now = time.time()
    cached = _user_cache.get(user_id)

    # Return cached if fresh
    if cached and (now - cached['_fetched_at']) < _user_cache_ttl:
        return cached

    # Check rate limit before making API call
    if not _check_rate_limit():
        return cached  # Return stale cache if rate limited

    # Make single API call (no recursion, no loop)
    _log_api_call()
    user = get_user_from_clerk_api(user_id)
    if user:
        user['_fetched_at'] = now
        _user_cache[user_id] = user
        return user

    return cached  # Return stale cache if API fails


def _sync_app_user(user_dict):
    """
    Sync AppUser record from Clerk user data.
    - First user ever = admin
    - Subsequent new users = user (unlinked, admin_id=NULL)
    - Updates name/email from Clerk data
    - Adds role info to g.clerk_user
    """
    from app import db
    from app.models.app_user import AppUser

    clerk_user_id = user_dict.get('user_id')
    if not clerk_user_id:
        return

    try:
        app_user = AppUser.query.filter_by(clerk_user_id=clerk_user_id).first()

        if not app_user:
            # New user — check if this is the first user (becomes admin)
            existing_count = AppUser.query.count()
            if existing_count == 0:
                app_user = AppUser(
                    clerk_user_id=clerk_user_id,
                    role='admin',
                    admin_id=None,
                    name=user_dict.get('name', 'Admin'),
                    email=user_dict.get('email', ''),
                )
            else:
                app_user = AppUser(
                    clerk_user_id=clerk_user_id,
                    role='user',
                    admin_id=None,  # unlinked until admin assigns
                    name=user_dict.get('name', 'User'),
                    email=user_dict.get('email', ''),
                )
            db.session.add(app_user)
            db.session.commit()
        else:
            # Sync name/email from Clerk
            changed = False
            clerk_name = user_dict.get('name', '')
            clerk_email = user_dict.get('email', '')
            if clerk_name and app_user.name != clerk_name:
                app_user.name = clerk_name
                changed = True
            if clerk_email and app_user.email != clerk_email:
                app_user.email = clerk_email
                changed = True
            if changed:
                db.session.commit()

        # Add role info to g.clerk_user
        g.clerk_user['role'] = app_user.role
        g.clerk_user['is_admin'] = (app_user.role == 'admin')

    except Exception as e:
        print(f'[AUTH] AppUser sync error: {e}')
        # Don't block auth if sync fails
        g.clerk_user.setdefault('role', 'user')
        g.clerk_user.setdefault('is_admin', False)


def fetch_all_clerk_users():
    """
    Fetch ALL users from Clerk Backend API.
    Used by User Management page to sync all user data.
    Returns list of user dicts, cached for 10 minutes.
    """
    now = time.time()

    # Check cache first (10 min TTL)
    cached = getattr(fetch_all_clerk_users, '_cache', None)
    cached_at = getattr(fetch_all_clerk_users, '_cached_at', 0)
    if cached and (now - cached_at) < 600:
        return cached

    secret_key = os.getenv('CLERK_SECRET_KEY', '')
    if not secret_key or secret_key.startswith('sk_test_XXXX'):
        return []

    all_users = []
    try:
        headers = {'Authorization': f'Bearer {secret_key}'}
        # Clerk API supports pagination — fetch all pages
        offset = 0
        limit = 100
        while True:
            resp = requests.get(
                f'https://api.clerk.com/v1/users?limit={limit}&offset={offset}&order_by=-created_at',
                headers=headers,
                timeout=15
            )
            if resp.status_code != 200:
                print(f'[AUTH] Clerk users list error: {resp.status_code}')
                break

            data = resp.json()
            # Clerk v5 API returns array directly
            users_data = data if isinstance(data, list) else data.get('data', data)
            if not users_data or not isinstance(users_data, list):
                break

            for u in users_data:
                first = u.get('first_name', '') or ''
                last = u.get('last_name', '') or ''
                name = f'{first} {last}'.strip() or u.get('username', '') or 'User'
                email_list = u.get('email_addresses', [])
                email = email_list[0]['email_address'] if email_list else ''

                # Convert Clerk timestamps (milliseconds) to datetime
                last_sign_in = u.get('last_sign_in_at')
                created_at_clerk = u.get('created_at')

                all_users.append({
                    'user_id': u.get('id', ''),
                    'name': name,
                    'email': email,
                    'image_url': u.get('image_url', ''),
                    'last_sign_in_at': last_sign_in,   # ms timestamp or None
                    'created_at_clerk': created_at_clerk,  # ms timestamp
                })

            # If we got fewer than limit, we've reached the end
            if len(users_data) < limit:
                break
            offset += limit

    except Exception as e:
        print(f'[AUTH] Clerk users list error: {e}')
        # Return stale cache if API fails
        if cached:
            return cached
        return []

    # Update cache
    fetch_all_clerk_users._cache = all_users
    fetch_all_clerk_users._cached_at = now
    return all_users


def sync_all_users_from_clerk():
    """
    Sync ALL Clerk users to AppUser table.
    - Updates name/email for existing users
    - Creates AppUser records for Clerk users who haven't logged in yet
    Returns count of (updated, created, total)
    """
    from app import db
    from app.models.app_user import AppUser
    from datetime import datetime

    clerk_users = fetch_all_clerk_users()
    if not clerk_users:
        return 0, 0, 0

    updated = 0
    created = 0

    for cu in clerk_users:
        clerk_id = cu['user_id']
        if not clerk_id:
            continue

        app_user = AppUser.query.filter_by(clerk_user_id=clerk_id).first()

        if app_user:
            # Update name/email if changed
            changed = False
            if cu['name'] and app_user.name != cu['name']:
                app_user.name = cu['name']
                changed = True
            if cu['email'] and app_user.email != cu['email']:
                app_user.email = cu['email']
                changed = True
            if changed:
                updated += 1
        else:
            # New Clerk user not in AppUser table yet — create as 'user'
            existing_count = AppUser.query.count()
            app_user = AppUser(
                clerk_user_id=clerk_id,
                role='admin' if existing_count == 0 else 'user',
                name=cu['name'],
                email=cu['email'],
            )
            db.session.add(app_user)
            created += 1

    db.session.commit()
    return updated, created, len(clerk_users)


def init_auth(app):
    """
    Initialize authentication for the Flask app.
    Adds before_request hook and context processor.

    KEY FIX: Uses Flask session as a fallback cache for authenticated users.
    Clerk JWTs expire every ~60 seconds. If a user takes longer than that
    to fill a form, the JWT in the __session cookie may expire. Without
    the Flask session fallback, the form POST would redirect to /login
    and the user's form data would be lost.

    Flow:
    1. Try to verify Clerk JWT (__session cookie)
    2. If valid → set g.clerk_user AND cache in Flask session
    3. If JWT expired but Flask session has cached user → use cache (grace period)
    4. If neither → redirect to login
    """

    # How long to trust the Flask session cache after last JWT verification.
    # 8 hours — matches PERMANENT_SESSION_LIFETIME. This prevents forms from
    # breaking / data being wiped when users are idle for longer periods.
    SESSION_GRACE_PERIOD = 28800
    # How often to re-sync AppUser role info from DB (avoid querying on every request)
    APPUSER_SYNC_INTERVAL = 600  # 10 minutes

    @app.before_request
    def check_auth():
        """Check Clerk authentication on every request"""
        g.clerk_user = None
        # Make Flask session permanent so PERMANENT_SESSION_LIFETIME (8h) applies
        session.permanent = True

        # Skip auth for: static files, login page, logout page, debug, public APIs
        if request.endpoint and (
            request.endpoint == 'static' or
            request.endpoint in ('auth.login_page', 'auth.logout_page', 'auth.debug_user',
                                 'api_docs.test_db_connection', 'api_docs.api_route_list') or
            request.path.startswith('/static/') or
            request.endpoint.startswith('flasgger.')
        ):
            return

        # Check if Clerk is configured
        clerk_key = os.getenv('CLERK_SECRET_KEY', '')
        if not clerk_key or clerk_key.startswith('sk_test_XXXX'):
            # Clerk NOT configured — run in open dev mode (no login required)
            g.clerk_user = {
                'user_id': 'dev-user',
                'name': 'Dev User',
                'email': 'dev@local',
                'image_url': '',
                'role': 'admin',
                'is_admin': True,
            }
            return

        # ── Clerk IS configured — verify __session cookie ──
        token = request.cookies.get('__session', '')
        payload = None
        user = None

        if token:
            payload = verify_clerk_session(token)

        if payload:
            # ✅ JWT is valid — extract user and cache in Flask session
            user_id = payload.get('sub', '')
            if not user_id:
                return redirect(url_for('auth.login_page'))

            user = _get_cached_user(user_id)
            if not user:
                user = {
                    'user_id': user_id,
                    'name': 'User',
                    'email': '',
                    'image_url': '',
                }

            g.clerk_user = user

            # ── Sync AppUser record (only periodically, not every request) ──
            last_sync = session.get('_appuser_synced_at', 0)
            if (time.time() - last_sync) > APPUSER_SYNC_INTERVAL:
                _sync_app_user(user)
                session['_appuser_synced_at'] = time.time()
            else:
                # Re-use role info from cached session to avoid DB query
                g.clerk_user['role'] = session.get('_clerk_user', {}).get('role', 'user')
                g.clerk_user['is_admin'] = session.get('_clerk_user', {}).get('is_admin', False)

            # Cache minimal user info in Flask session for grace period
            # (full dict can bloat cookie past 4KB browser limit)
            session['_clerk_user'] = {
                'user_id': g.clerk_user.get('user_id'),
                'name': g.clerk_user.get('name'),
                'email': g.clerk_user.get('email'),
                'image_url': g.clerk_user.get('image_url', ''),
                'role': g.clerk_user.get('role', 'user'),
                'is_admin': g.clerk_user.get('is_admin', False),
            }
            session['_clerk_verified_at'] = time.time()
            return

        # ── JWT missing or expired — try Flask session fallback ──
        cached_user = session.get('_clerk_user')
        verified_at = session.get('_clerk_verified_at', 0)

        if cached_user and (time.time() - verified_at) < SESSION_GRACE_PERIOD:
            # Still within grace period — trust the cached session, NO DB query.
            # This is what prevents hangs when Clerk API is slow or unreachable.
            g.clerk_user = cached_user
            return

        # ── No valid auth at all — clear stale session and redirect to login ──
        session.pop('_clerk_user', None)
        session.pop('_clerk_verified_at', None)

        if request.endpoint and request.endpoint != 'auth.login_page':
            if request.method == 'POST':
                # For POST requests, flash a message so user knows what happened
                flash('Your session expired. Please try again.', 'warning')
            return redirect(url_for('auth.login_page'))
        return

    @app.context_processor
    def inject_clerk_user():
        """Make clerk_user available in all Jinja2 templates"""
        return dict(clerk_user=getattr(g, 'clerk_user', None))


# ─── Route Protection Decorators ─────────────────────────────────

def login_required(f):
    """Decorator: Route requires any authenticated user (admin or user)"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not getattr(g, 'clerk_user', None):
            flash('Please login to continue.', 'warning')
            return redirect(url_for('auth.login_page'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Decorator: Route requires admin role"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not getattr(g, 'clerk_user', None):
            flash('Please login to continue.', 'warning')
            return redirect(url_for('auth.login_page'))
        from app.user_context import is_admin
        if not is_admin():
            flash('Admin access required.', 'danger')
            return redirect(url_for('establishment.dashboard'))
        return f(*args, **kwargs)
    return decorated
