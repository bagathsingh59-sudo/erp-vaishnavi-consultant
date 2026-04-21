"""
Clear all backend data (preserving account_groups and account_heads seed data).
Creates the app_users table via db.create_all().
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import create_app, db

app = create_app()

with app.app_context():
    # Tables to clear, in order respecting foreign key constraints
    tables_to_clear = [
        'activity_logs',
        'voucher_entries',
        'vouchers',
        'payroll_entry_heads',
        'payroll_entries',
        'monthly_payrolls',
        'employee_salary_heads',
        'employee_salaries',
        'salary_heads',
        'payroll_configs',
        'transfer_history',
        'nominees',
        'employees',
        'portal_credentials',
        'establishments',
        'app_users',
    ]

    for table_name in tables_to_clear:
        try:
            db.session.execute(db.text(f'DELETE FROM {table_name}'))
            count = db.session.execute(db.text(f'SELECT COUNT(*) FROM {table_name}')).scalar()
            print(f'  Cleared {table_name} (rows remaining: {count})')
        except Exception as e:
            print(f'  Skipped {table_name}: {e}')

    db.session.commit()

    # Verify preserved tables
    for table in ['account_groups', 'account_heads']:
        count = db.session.execute(db.text(f'SELECT COUNT(*) FROM {table}')).scalar()
        print(f'  Preserved {table}: {count} rows')

    # Ensure app_users table exists
    db.create_all()
    print('\nAll data cleared. app_users table ready.')
    print('account_groups and account_heads preserved.')
