"""Dev mode runner — skips Clerk auth for local preview"""
import os
os.environ['CLERK_SECRET_KEY'] = ''
os.environ['CLERK_PUBLISHABLE_KEY'] = ''
os.environ['SECRET_KEY'] = 'dev-secret-key'

from app import create_app

# Force clear again after dotenv may have loaded
os.environ['CLERK_SECRET_KEY'] = ''
os.environ['CLERK_PUBLISHABLE_KEY'] = ''

app = create_app()

# Override app config too
app.config['CLERK_SECRET_KEY'] = ''
app.config['CLERK_PUBLISHABLE_KEY'] = ''

print(f"[CHECK] CLERK_SECRET_KEY = '{os.environ.get('CLERK_SECRET_KEY')}'")
print(f"[CHECK] app.config CLERK = '{app.config.get('CLERK_SECRET_KEY')}'")

if __name__ == '__main__':
    print("\n[DEV MODE] Running WITHOUT Clerk auth")
    app.run(debug=False, port=5000)
