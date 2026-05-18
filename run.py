import subprocess
import sys
import os

def main():
    backend_script = os.path.join("app", "main.py")
    frontend_script = "streamlit_app.py"

    print("🤖 Starting Friendly FastAPI Backend...")
    # Run FastAPI
    backend_process = subprocess.Popen([sys.executable, backend_script])

    print("🤖 Starting Friendly Streamlit Frontend...")
    # Run Streamlit on port 8501
    frontend_process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", frontend_script, "--server.port", "8501"])

    try:
        # Keep the main process running while both sub-processes run
        backend_process.wait()
        frontend_process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down both services...")
        backend_process.terminate()
        frontend_process.terminate()
        backend_process.wait()
        frontend_process.wait()
        print("✅ Shutdown complete.")

if __name__ == "__main__":
    main()
