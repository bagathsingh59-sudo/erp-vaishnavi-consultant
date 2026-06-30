# Clerk → Self-hosted JWT Auth — Migration & Go-Live Runbook

The ERP no longer uses Clerk. It now issues and verifies its own tokens:

- **Access token** — short-lived signed JWT (HS256), httpOnly cookie `access_token`.
- **Refresh token** — long-lived opaque value (stored hashed), httpOnly cookie
  `refresh_token`. Sliding expiry; renewed silently when the access token expires.
- Login is **email + password** (bcrypt). New users are **created by an admin**;
  there is no public sign-up.

Every user's identity is still the **same id value** that Clerk used (stored in
`app_users.clerk_user_id` and in `owner_id` / `assigned_to_id` across the DB), so
**no ownership data has to move** — only passwords are new.

## ⚠️ Important: do NOT just deploy

Until the migration script has run, existing users have **no password**, so nobody
can log in. Follow the order below.

## Go-live steps (env-gated — no manual script needed)

1. **Set env vars** on the server (Railway / Dokploy):
   - `JWT_SECRET` = a long random string
     (`python -c "import secrets;print(secrets.token_urlsafe(48))"`)
   - optional: `JWT_ACCESS_TTL_MIN` (default 30), `JWT_REFRESH_TTL_DAYS` (default 14)
   - Keep `CLERK_SECRET_KEY` (used to import the user list).
   - `INTERNAL_API_KEY` unchanged (the Client Portal still uses it).

2. **Deploy** the new code. On boot it auto-adds the `password_hash`,
   `must_change_password`, `last_login_at`, `temp_password` columns and the
   `auth_refresh_tokens` table.

3. **Flip the Password Generator on:** set `PASSWORD_GENERATOR=true` and restart /
   redeploy. On boot the app pulls every Clerk user, gives anyone without a
   password a **temporary** one, and forces a change on first login. The temp
   passwords are visible to the admin in **Admin → Users** (each row shows
   `Temp: …` until that user changes it). It is idempotent — only users without
   a password are touched.

4. **Hand out the temp passwords** from Admin → Users, then set
   `PASSWORD_GENERATOR=false` again (stops the per-boot Clerk API calls).
   You may keep or remove `CLERK_SECRET_KEY` afterwards — it's only used while
   the generator is on.

> Prefer a manual run instead of the flag? `python backend/migrate_clerk_to_jwt.py`
> does exactly the same thing once.

## Day-to-day

- **Sign in:** `/login` with email + password. First login forces a password change.
- **Create users:** Admin → Users → **New User** (email, role, optional temp password).
- **Reset a password:** Admin → Users → key icon (shows a new temp password and
  signs that user out everywhere).
- **Change your own password:** key icon in the top bar → `/change-password`.
- **Local dev without login:** set `AUTH_DEV_OPEN=1` (NEVER in production).

## Notes

- The internal template variable is still named `clerk_user` purely for template
  compatibility; it is just the current-user dict and has nothing to do with Clerk.
- `requests` and the temporary `CLERK_SECRET_KEY` are only needed for the one-time
  migration script; both can be dropped afterwards.
