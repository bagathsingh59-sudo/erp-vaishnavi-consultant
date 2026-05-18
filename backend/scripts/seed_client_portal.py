#!/usr/bin/env python3
"""
seed_client_portal.py — create `client_users` and seed default logins.

Run this from the ERP repo once, before deploying the Client Portal.  It will:
  1. CREATE TABLE IF NOT EXISTS client_users (...)
  2. CREATE INDEXES on username/email/phone/establishment_id
  3. For every row in `establishments`, INSERT one client_users row with:
       - username = slug of "<company> (<branch>)"  e.g. micon-vulcanizer-wadi
       - email    = <username>@gmail.com
       - phone    = last 10 digits of establishments.contact_phone (if unique)
       - password = bcrypt("123456789", strength 10)
     Compatible with Spring Security's BCryptPasswordEncoder.

The Spring Boot Portal's own DataSeeder will pick up any later additions, but
running this script now lets you verify the data in PostgreSQL before the
Java app even starts.

Idempotent — safe to re-run, never overwrites an existing client_users row.

Usage:
    pip install psycopg2-binary bcrypt
    python backend/scripts/seed_client_portal.py
    python backend/scripts/seed_client_portal.py --password mySecret123
    python backend/scripts/seed_client_portal.py --dry-run
    python backend/scripts/seed_client_portal.py --database-url postgresql://...

Railway cost note:
    `postgres.railway.internal` is the free private endpoint — only reachable
    from inside Railway's network.  Running this script from your laptop with
    that hostname will fail (DNS won't resolve).  Three free / cheap options:

      1. Skip this script — the Spring Boot DataSeeder will do the same job
         when it boots inside Railway (uses the private URL, no egress fees).
      2. Run via the Railway CLI so it executes inside the project's network:
             railway run -- python backend/scripts/seed_client_portal.py
      3. From your laptop with the PUBLIC URL (one-time pennies of egress):
             $env:DATABASE_URL = "postgresql://...@<public-host>:<public-port>/railway"
             python backend/scripts/seed_client_portal.py
"""

import argparse
import os
import re
import sys
import unicodedata

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    sys.stderr.write("ERROR: psycopg2 not installed.\n        pip install psycopg2-binary\n")
    sys.exit(1)

try:
    import bcrypt
except ImportError:
    sys.stderr.write("ERROR: bcrypt not installed.\n        pip install bcrypt\n")
    sys.exit(1)


# ── DDL ──────────────────────────────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS client_users (
    id                SERIAL PRIMARY KEY,
    establishment_id  INTEGER NOT NULL REFERENCES establishments(id) ON DELETE CASCADE,
    username          VARCHAR(100) NOT NULL,
    email             VARCHAR(255) NOT NULL,
    phone             VARCHAR(20),
    password_hash     VARCHAR(255) NOT NULL,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at     TIMESTAMP,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_client_users_username UNIQUE (username),
    CONSTRAINT uq_client_users_email    UNIQUE (email),
    CONSTRAINT uq_client_users_phone    UNIQUE (phone)
);
"""

INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_client_users_establishment_id ON client_users(establishment_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_users_username_lower   ON client_users(LOWER(username))",
    "CREATE INDEX IF NOT EXISTS ix_client_users_email_lower      ON client_users(LOWER(email))",
]


# ── Helpers (must match Spring Boot's DataSeeder.slug()) ────────────────────
def slug(s):
    if not s:
        return "user"
    ascii_s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-z0-9]+", "-", ascii_s.lower()).strip("-")
    return cleaned or "user"


def display_name(company, branch):
    if branch and branch.strip():
        return f"{company} ({branch})"
    return company or "Unknown"


def normalize_phone(raw):
    if not raw:
        return None
    digits = re.sub(r"[^0-9]", "", str(raw))
    if len(digits) > 10:
        digits = digits[-10:]
    return digits if len(digits) == 10 else None


def find_unique_username(cur, base):
    candidate = base
    i = 2
    while True:
        cur.execute(
            "SELECT 1 FROM client_users "
            "WHERE LOWER(username) = LOWER(%s) OR LOWER(email) = LOWER(%s) LIMIT 1",
            (candidate, f"{candidate}@gmail.com"),
        )
        if not cur.fetchone():
            return candidate
        candidate = f"{base}-{i}"
        i += 1
        if i > 9999:
            raise RuntimeError(f"Cannot generate unique username for {base}")


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Seed client_users for Vaishnavi Client Portal")
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                   help="PostgreSQL URL (default: $DATABASE_URL)")
    p.add_argument("--password", default="123456789",
                   help="Default password for seeded logins (default: 123456789)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would happen without writing anything")
    args = p.parse_args()

    if not args.database_url:
        sys.stderr.write("ERROR: DATABASE_URL not set.  Pass --database-url or export DATABASE_URL.\n")
        sys.exit(1)

    safe_url = re.sub(r"://[^@]+@", "://***:***@", args.database_url)
    print(f"→ connecting to {safe_url}")

    conn = psycopg2.connect(args.database_url)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # 1 ── ensure schema -----------------------------------------------------
    print("→ ensuring client_users table + indexes…")
    cur.execute(SCHEMA_SQL)
    for sql in INDEX_SQL:
        cur.execute(sql)

    # 2 ── fetch all establishments -----------------------------------------
    cur.execute("""
        SELECT id, company_name, branch_name, contact_phone
          FROM establishments
         ORDER BY company_name, branch_name NULLS FIRST
    """)
    establishments = cur.fetchall()
    print(f"→ found {len(establishments)} establishments in the ERP")

    # 3 ── hash default password once (bcrypt is slow on purpose) -----------
    pwd_hash = bcrypt.hashpw(
        args.password.encode("utf-8"),
        bcrypt.gensalt(rounds=10),
    ).decode("utf-8")

    created  = 0
    skipped  = 0
    samples  = []

    for est in establishments:
        est_id   = est["id"]
        company  = est["company_name"]
        branch   = est.get("branch_name")
        contact  = est.get("contact_phone")

        cur.execute("SELECT 1 FROM client_users WHERE establishment_id = %s LIMIT 1", (est_id,))
        if cur.fetchone():
            skipped += 1
            continue

        name     = display_name(company, branch)
        base     = slug(name)
        username = find_unique_username(cur, base)
        email    = f"{username}@gmail.com"

        phone = normalize_phone(contact)
        if phone:
            cur.execute("SELECT 1 FROM client_users WHERE phone = %s LIMIT 1", (phone,))
            if cur.fetchone():
                phone = None

        if args.dry_run:
            print(f"  WOULD seed: est_id={est_id:<4}  username={username:<40}  phone={phone or '-'}")
        else:
            cur.execute("""
                INSERT INTO client_users (establishment_id, username, email, phone, password_hash)
                VALUES (%s, %s, %s, %s, %s)
            """, (est_id, username, email, phone, pwd_hash))
            print(f"  + seeded: est_id={est_id:<4}  username={username}")

        if len(samples) < 5:
            samples.append((name, username, email, phone))
        created += 1

    if args.dry_run:
        conn.rollback()
        print(f"\nDRY RUN — would create {created} new logins, skip {skipped} existing")
    else:
        conn.commit()
        print(f"\n✓ created {created} new logins, skipped {skipped} that already had one")
        if created > 0:
            print(f"  Default password for all NEW logins: {args.password}")
            print("\n  Sample logins (any one identifier + password works):")
            for name, u, e, ph in samples:
                print(f"    • {name}")
                print(f"        username = {u}")
                print(f"        email    = {e}")
                print(f"        phone    = {ph or '(none on file)'}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
