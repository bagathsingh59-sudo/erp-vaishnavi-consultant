"""
One-time Clerk → JWT migration (manual trigger).

This is the SAME logic the app runs automatically on boot when the
PASSWORD_GENERATOR env var is truthy (see app/password_generator.py). You only
need this script if you'd rather run the migration once by hand instead of via
the env flag.

Usage (from backend/, with CLERK_SECRET_KEY available):
    python migrate_clerk_to_jwt.py

Afterwards the temporary passwords are visible to the admin in Admin → Users
(each user's row shows "Temp: …" until they set their own password).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db                                  # noqa: E402
from app.password_generator import run_password_generator       # noqa: E402


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        summary = run_password_generator(db)
        print(f"Done. {summary}")
        print("Temporary passwords are now shown in Admin → Users.")
