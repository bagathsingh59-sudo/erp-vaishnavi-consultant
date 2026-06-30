"""Dev mode runner — skips login for local preview (AUTH_DEV_OPEN)."""
import os
os.environ['AUTH_DEV_OPEN'] = '1'          # bypass auth locally
os.environ.setdefault('SECRET_KEY', 'dev-secret-key')
os.environ.setdefault('JWT_SECRET', 'dev-jwt-secret')

from app import create_app

# Ensure it stays on even if dotenv loaded other values.
os.environ['AUTH_DEV_OPEN'] = '1'

app = create_app()

if __name__ == '__main__':
    print("\n[DEV MODE] Running with AUTH_DEV_OPEN=1 (no login required)")
    app.run(debug=False, port=5000)
