import os
import requests
import time

BASE_URL = "http://localhost:8000"

def wait_for_backend():
    print("Waiting for backend to start...")
    for _ in range(30):
        try:
            resp = requests.get(f"{BASE_URL}/api/health")
            if resp.status_code == 200:
                print("Backend is up!")
                return True
        except requests.ConnectionError:
            pass
        time.sleep(1)
    print("Backend failed to start")
    return False

def run_benchmark(fixture_name, issue_desc, test_cmd):
    print(f"\n{'='*50}\nRunning Benchmark: {fixture_name}\n{'='*50}")
    repo_url = f"file://{os.path.abspath(os.path.join(os.path.dirname(__file__), '../benchmark_fixtures', fixture_name))}"

    start_time = time.time()

    print("1. Diagnosing issue...")
    try:
        diag_resp = requests.post(f"{BASE_URL}/api/diagnose", json={
            "repo_url": repo_url,
            "issue_description": issue_desc,
            "test_command": test_cmd
        })
        diag_resp.raise_for_status()
        diag_data = diag_resp.json()
    except Exception as e:
        print(f"FAILED Diagnosis: {e}")
        return False

    print(f"  Diagnosis Workspace: {diag_data['workspace_id']}")
    print(f"  Diagnosis: {diag_data['diagnosis']['diagnosis']}")

    print("\n2. Requesting Repair...")
    try:
        rep_resp = requests.post(f"{BASE_URL}/api/repair", json={
            "workspace_id": diag_data['workspace_id'],
            "issue_description": issue_desc,
            "diagnosis_context": diag_data['diagnosis'],
            "test_command": test_cmd
        })
        rep_resp.raise_for_status()
        rep_data = rep_resp.json()
    except Exception as e:
        print(f"FAILED Repair: {e}")
        return False

    duration = time.time() - start_time

    print("\n--- Repair Result ---")
    print(f"Status: {rep_data['status']}")
    print(f"Verification: {rep_data.get('verification_status')}")
    print(f"Latency: {duration:.2f} seconds")

    # Cleanup
    requests.delete(f"{BASE_URL}/api/workspace/{diag_data['workspace_id']}")

    return True

if __name__ == "__main__":
    import subprocess
    import sys

    # Start backend
    server_process = subprocess.Popen(
        ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"],
        env=dict(os.environ, PYTHONPATH=os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    )

    try:
        if not wait_for_backend():
            sys.exit(1)

        run_benchmark(
            "simple_bug",
            "test_subtract fails because it adds instead of subtracting",
            "pytest test_math_utils.py"
        )

        run_benchmark(
            "edge_case",
            "truncate_text truncates at 9 chars instead of 10 when max_length is 10",
            "pytest test_text_utils.py"
        )
    finally:
        server_process.terminate()
        server_process.wait()
