"""
Password Generator — internal Clerk → JWT credential migration.
================================================================

This is the in-app version of the one-time migration. It runs automatically on
boot when the env var PASSWORD_GENERATOR is truthy (true/1/yes), the same way a
seeder flag works. It is fully idempotent:

  1. If CLERK_SECRET_KEY is set, pull EVERY Clerk user and make sure each has a
     matching `app_users` row (keyed on the existing Clerk id → no data moves).
  2. For every user that has NO password yet, generate a TEMPORARY password,
     store its bcrypt hash, flag `must_change_password = True`, and keep the
     plaintext in `app_users.temp_password` so the admin can read and hand it
     out from Admin → Users. (The plaintext is wiped the moment the user sets
     their own password.)

Because it only touches users without a password, re-running it (every boot
while the flag is on) is safe — once everyone has a password it does nothing
except an idempotent Clerk sync. Turn the flag off afterwards to stop the
per-boot Clerk API calls.
"""
import os
import time
import secrets


def password_generator_enabled():
    return os.getenv('PASSWORD_GENERATOR', '').lower() in ('1', 'true', 'yes')


def _gen_temp_password():
    alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
    return 'Vp' + ''.join(secrets.choice(alphabet) for _ in range(8))


def _fetch_all_clerk_users():
    """Fetch every Clerk user (paginated). Returns [] if Clerk not configured
    or on any error — never raises, so it can't block app boot."""
    secret_key = os.getenv('CLERK_SECRET_KEY', '')
    if not secret_key or secret_key.startswith('sk_test_XXXX'):
        return []
    try:
        import requests
    except ImportError:
        return []

    out = []
    headers = {'Authorization': f'Bearer {secret_key}'}
    offset, limit = 0, 100
    try:
        while True:
            resp = requests.get(
                f'https://api.clerk.com/v1/users?limit={limit}&offset={offset}&order_by=-created_at',
                headers=headers, timeout=15,
            )
            if resp.status_code != 200:
                print(f'  [PWGEN] Clerk list error {resp.status_code}')
                break
            data = resp.json()
            users = data if isinstance(data, list) else data.get('data', [])
            if not users:
                break
            for u in users:
                first = (u.get('first_name') or '').strip()
                last = (u.get('last_name') or '').strip()
                name = (f'{first} {last}').strip() or u.get('username') or 'User'
                emails = u.get('email_addresses', [])
                email = emails[0]['email_address'] if emails else ''
                out.append({'user_id': u.get('id', ''), 'name': name, 'email': email})
            if len(users) < limit:
                break
            offset += limit
            time.sleep(0.15)
    except Exception as e:
        print(f'  [PWGEN] Clerk fetch error: {e}')
    return out


def run_password_generator(db):
    """Execute the migration. Safe + idempotent. Returns a small summary dict."""
    from app.models.app_user import AppUser

    created = 0
    assigned = 0
    no_email = 0

    # ── Step 1: ensure an app_users row exists for every Clerk user ──
    for cu in _fetch_all_clerk_users():
        cid = cu['user_id']
        if not cid:
            continue
        try:
            existing = AppUser.query.filter_by(clerk_user_id=cid).first()
            if existing:
                if cu['email'] and not existing.email:
                    existing.email = cu['email']
                if cu['name'] and not existing.name:
                    existing.name = cu['name']
                continue
            is_first = AppUser.query.count() == 0
            db.session.add(AppUser(
                clerk_user_id=cid,
                role='admin' if is_first else 'user',
                name=cu['name'],
                email=cu['email'],
                is_active=True,
            ))
            db.session.commit()
            created += 1
        except Exception:
            db.session.rollback()

    # ── Step 2: assign temp passwords to anyone without one ──
    for u in AppUser.query.filter(AppUser.password_hash.is_(None)).all():
        if not u.email:
            no_email += 1
            continue
        try:
            temp = _gen_temp_password()
            u.set_password(temp)
            u.must_change_password = True
            u.temp_password = temp        # visible to admin until first change
            db.session.commit()
            assigned += 1
        except Exception:
            db.session.rollback()

    print(f'  [PWGEN] Clerk users created: {created}, temp passwords assigned: '
          f'{assigned}, skipped (no email): {no_email}')
    return {'created': created, 'assigned': assigned, 'no_email': no_email}
