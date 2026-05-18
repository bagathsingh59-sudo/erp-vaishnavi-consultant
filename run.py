"""Root-level entry shim — delegates to backend/run.py so tooling that expects
`python run.py` at the project root works without changes.  Identical behaviour
to `python backend/run.py` from the repo root.
"""
import os
import sys

# Make `app` package importable.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

from app import create_app

app = create_app()

if __name__ == '__main__':
    print("\n[OK] Vaishnavi Consultant ERP is running!")
    port = int(os.environ.get('PORT', 5000))
    print(f">>> Open your browser and go to: http://localhost:{port}\n")
    app.run(debug=True, host='0.0.0.0', port=port)
