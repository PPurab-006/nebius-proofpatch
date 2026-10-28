<div align="center">
  <img src="frontend/public/patchworks-horizontal.png" alt="Patchworks" width="380" />
  <br />
  <br />
  <p><strong>Nebius &times; NVIDIA Global AI Hackathon</strong> &bull; <em>Find the fault. Forge the fix. Prove it works.</em></p>
  <p>
    <a href="https://patchworks-workbench.onrender.com"><img src="https://img.shields.io/badge/Live%20Workbench-Online-B7FF3C?style=flat-square" alt="Live Workbench" /></a>
    <img src="https://img.shields.io/badge/Inference-Nebius%20Token%20Factory-00E5FF?style=flat-square" alt="Inference" />
    <img src="https://img.shields.io/badge/Model-NVIDIA%20Nemotron--70B-76B900?style=flat-square&logo=nvidia" alt="Model" />
    <img src="https://img.shields.io/badge/Auth%20%26%20Vault-Supabase-3ECF8E?style=flat-square&logo=supabase" alt="Supabase" />
  </p>
</div>

---

## 1. Project Overview

**Patchworks** is an evidence-driven autonomous code-repair workbench. Instead of speculative code patching, Patchworks adheres to a strict scientific verification cycle:
1. **Ingest & Isolate:** Clone repositories into an ephemeral, isolated sandbox workspace with starting commit tracking and SSRF protections.
2. **Diagnose:** Analyze software defects, stack traces, and code context using **NVIDIA open-source models** (`nvidia/Nemotron-3_5-Lightning`) served via **Nebius AI Cloud / Token Factory** (with deterministic fallback mock mode).
3. **Synthesize:** Generate minimal unified diff patches strictly validated against path traversal and syntax malformations.
4. **Empirically Verify:** Safely execute isolated test suites (`pytest`, `python`) in an isolated subprocess environment.
5. **Certify & Publish:** Strictly gate publication on empirical proof (`FIX VERIFIED` with exit code 0). With explicit user authorization, push fixes to dedicated branches (`patchworks/fix-<short-id>`) and open auditable GitHub Pull Requests with verification certificates.

---

## 2. GitHub Integration & Verified Pull Request Automation

Patchworks provides a native, secure GitHub integration supporting end-to-end repository repair and pull request publication:

```
[Connect GitHub] ──> [Browse & Select Repo/Branch] ──> [Clone to Isolated Sandbox]
                                                               │
                                                               ▼
[Audit Certificate & PR Link] <── [Open PR & Push Branch] <── [Empirical Verification Gate]
```

### Supported User Workflow:
1. **Connect GitHub Account:** Authenticate via Personal Access Token (PAT) or GitHub App. Tokens are held exclusively in backend session memory, never exposed in client bundles, and never written into git remotes.
2. **Repository & Branch Selection:** Search and browse accessible public or private repositories, inspect default branches, and select the target branch.
3. **Isolated Workspace:** Clones the target branch to an isolated temp directory, configuring a dedicated git identity (`Patchworks Agent`) and recording the starting commit SHA.
4. **Autonomous Diagnosis & Synthesis:** Generates root cause diagnosis, evidence snippets, and minimal diff patches.
5. **Sandbox Test Verification:** Executes reproduction test commands, capturing stdout, stderr, and exit codes.
6. **Publication Gate:**
   - **`FIX VERIFIED` (Exit Code 0):** Fix is certified. User can review diff, evidence, and custom notes, and approve opening a Pull Request.
   - **`FIX FAILED` / `VERIFICATION INCOMPLETE` / `UNVERIFIED`:** Pull request publication is strictly blocked by the backend API.
7. **Divergence Check:** Prior to publication, Patchworks checks if the remote branch has received new commits since the repair began. If diverged, publication is halted to prevent overwriting team changes.
8. **Branch Creation & PR Automation:** Creates a uniquely named branch (`patchworks/fix-<short-id>`), commits only modified tracked files, pushes via HTTP extraHeaders, and opens a Pull Request with structured evidence, exit codes, and truthful execution mode badges (Mock Mode vs Live Nebius).

---

## 3. Security Model and Safeguards

Patchworks enforces comprehensive defense-in-depth guarantees:

- **Token Safety & Redaction:** Tokens are never passed in query parameters, never stored in browser `localStorage`, and never written to `.git/config` on disk. Git subprocesses authenticate using ephemeral in-memory `-c http.extraHeader="AUTHORIZATION: basic <base64>"`. Any errors or logs automatically redact authorization secrets.
- **Backend Gate Enforcement:** The frontend never decides whether a patch can be published. The backend revalidates `verification_status == "FIX VERIFIED"` on every `/api/github/publish` request.
- **SSRF & URL Validation:** Prevents DNS rebinding and internal IP addresses (RFC 1918, link-local, loopback, and cloud metadata `169.254.169.254`).
- **Path Traversal Protection:** Repository names, branch names, and unidiff patch headers reject directory traversal (`..`), flag injection (`-flag`), and command chaining (`;&|`).
- **No Force-Pushes & No Auto-Merges:** Patchworks never force-pushes, never pushes to protected default branches, and never automatically merges pull requests. The human maintainer retains full merging control.

---

## 4. Running Patchworks Locally

### Quick Start with Launcher

Run both backend and frontend concurrently:
```bash
./run.sh
```

### Manual Setup

#### Backend
1. `cd backend`
2. Activate or create virtual environment: `python3 -m venv .venv && source .venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` (optional: add `NEBIUS_API_KEY` for live model inference, or `GITHUB_TOKEN` for server default token).
5. Start API server:
   ```bash
   PYTHONPATH=. uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
   ```

#### Frontend
1. `cd frontend`
2. Install dependencies: `npm install`
3. Start Vite dev server: `npm run dev` (runs at `http://localhost:5173`)
4. Verify production bundle: `npm run build`

---

## 5. API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Service health, Nebius configuration status, active model name |
| `GET` | `/api/github/status` | Current GitHub connection state and authenticated user info |
| `POST` | `/api/github/connect` | Authenticate with GitHub token (PAT) |
| `POST` | `/api/github/disconnect` | Clear active GitHub session |
| `GET` | `/api/github/repos` | Browse and search accessible repositories |
| `GET` | `/api/github/repos/{owner}/{repo}/branches` | List branches for a repository |
| `POST` | `/api/github/workspace` | Clone target branch into an isolated sandbox workspace |
| `POST` | `/api/diagnose` | Run autonomous defect diagnosis with Nebius or deterministic mock |
| `POST` | `/api/repair` | Synthesize minimal patch, apply safely, and run sandbox tests |
| `GET` | `/api/github/publish/readiness` | Check verification gate, test status, and branch divergence |
| `POST` | `/api/github/publish` | Validate gate, commit to unique branch, push, and open PR |
| `POST` | `/api/rollback` | Revert workspace to HEAD |
| `DELETE` | `/api/workspace/{id}` | Clean up temporary workspace directory |

---

## 6. Testing Instructions

Run the complete backend test suite:
```bash
PYTHONPATH=. ./.venv/bin/pytest backend/tests
```

Run GitHub-specific integration and gate tests:
```bash
PYTHONPATH=. ./.venv/bin/pytest backend/tests/test_github.py
```

Run deterministic benchmark fixtures:
```bash
PYTHONPATH=. ./.venv/bin/python backend/run_benchmark.py
```

Verify frontend build:
```bash
cd frontend && npm run build
```

---

## 7. Known Limitations & Troubleshooting

- **GitHub Rate Limits:** Unauthenticated GitHub API calls are limited to 60 req/hour. Connecting a valid Personal Access Token raises the limit to 5,000 req/hour.
- **Token Scopes:** For public repositories, fine-grained tokens need `Contents (read/write)` and `Pull requests (read/write)`. For private repositories, ensure the token has access to the target organization or repository.
- **Branch Divergence:** If another developer commits to the target branch while Patchworks is running tests, Patchworks detects the conflict and halts publication. Re-fetch the repository to test against the latest commit.
- **Mock Mode vs Live Inference:** If `NEBIUS_API_KEY` is omitted or set to `mock_key`, Patchworks operates in honest simulated mock mode with deterministic benchmarks (`simple_bug` and `edge_case`). PR descriptions and UI badges clearly indicate mock mode.

---

## License

This project is licensed under the **Apache License 2.0**.

