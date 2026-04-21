from dotenv import load_dotenv
load_dotenv()

from app import create_app

app = create_app()

if __name__ == '__main__':
    print("\n[OK] Vaishnavi Consultant ERP is running!")
    print(">>> Open your browser and go to: http://localhost:5000\n")
    app.run(debug=True, port=5000)
