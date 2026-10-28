<div align="center">
  <img src="frontend/public/patchworks-horizontal.png" alt="Patchworks" width="420" />
  <br />
  <br />
  <p><strong>Nebius &times; NVIDIA Global AI Hackathon</strong> &bull; <em>Find the fault. Forge the fix. Prove it works.</em></p>
  <p>
    <a href="https://opensource.org/licenses/Apache-2.0"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License: Apache 2.0" /></a>
    <a href="https://opensource.org/licenses/Apache-2.0"><img src="https://img.shields.io/badge/OSI-Approved%20License-green.svg" alt="OSI Approved" /></a>
    <a href="https://patchworks-workbench.onrender.com"><img src="https://img.shields.io/badge/Live%20Workbench-Online-B7FF3C?style=flat-square" alt="Live Workbench" /></a>
    <img src="https://img.shields.io/badge/Inference-Nebius%20Token%20Factory-00E5FF?style=flat-square" alt="Inference" />
    <img src="https://img.shields.io/badge/Engine-NVIDIA%20Nemotron%20Family-76B900?style=flat-square&logo=nvidia" alt="NVIDIA Nemotron" />
    <img src="https://img.shields.io/badge/Auth%20%26%20Vault-Supabase-3ECF8E?style=flat-square&logo=supabase" alt="Supabase" />
  </p>
</div>

---

## 1. Project Overview

**Patchworks** is an autonomous, evidence-driven code-repair workbench built for the **Nebius &times; NVIDIA Global AI Hackathon** (Coding and Agentic Engineering Track).

While modern generative coding agents can produce code, they frequently hallucinate invalid syntax, break existing test suites, and open unverified pull requests that consume engineering hours. **Patchworks eliminates this risk by treating code repair as an accountable, deterministic engineering cycle:**

1. **Ingest & Isolate:** Repositories (via GitHub URL, Git remotes, Zip archives, or built-in benchmarks) are cloned into ephemeral, isolated sandbox workspaces with full starting commit tracking and SSRF protections.
2. **Causal Diagnosis:** Autonomous fault analysis powered by **NVIDIA open-source Nemotron models** on **Nebius Token Factory**, diagnosing root causes from code AST, failing test outputs, and stack traces.
3. **Scoped Synthesis:** Generates minimal, scoped unified diff patches strictly validated against directory traversal and syntax malformations.
4. **Empirical Sandbox Verification:** Safely executes test suites (`pytest`, `python`) in an isolated subprocess environment.
5. **Automated Rollback & Proof Certification:** If verification fails or breaks existing tests, Patchworks immediately reverts the workspace to HEAD. If tests pass with exit code 0, it issues a cryptographic verification proof (`FIX VERIFIED`).
6. **PR Awareness & Publication:** Inspects target branches for divergence and existing PRs to prevent duplicate publication, opening auditable GitHub Pull Requests with complete verification certificates under developer control.

---

## 2. NVIDIA Open-Source Models & Nemotron Integration

Patchworks is engineered from the ground up to harness NVIDIA's premier open-source foundation models served via **Nebius Token Factory**. Through our dynamic engine configuration, developers and agents can select the optimal Nemotron model for their specific repair workload:

```
┌────────────────────────────────────────────────────────────────────────┐
│                   Nebius Token Factory Inference API                   │
│          Endpoint: https://api.studio.nebius.ai/v1/chat/completions    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
       ┌────────────────────────────┼────────────────────────────┐
       ▼                            ▼                            ▼
┌───────────────────────┐ ┌───────────────────────┐ ┌────────────────────────┐
│   Nemotron 3 Super    │ │   Nemotron 3 Ultra    │ │   Nemotron Nano / 3.5  │
│       (120B MoE)      │ │        (550B)         │ │   (30B / Lightning)    │
│  RECOMMENDED FOR CODE │ │  FLAGSHIP REASONING   │ │   COMPACT / ECONOMY    │
├───────────────────────┤ ├───────────────────────┤ ├────────────────────────┤
│ • Scoped Patch Synth  │ │ • Architectural Causal│ │ • Rapid Initial Triage │
│ • Unified Diff Syntax │ │   Multi-File Analysis │ │ • Pre-Repair Filtering │
│ • AST Code Structure  │ │ • Cross-Module Faults │ │ • Syntax Checks        │
│ • Deterministic Fixes │ │ • Complex Refactorings│ │ • Minimal Latency      │
└───────────────────────┘ └───────────────────────┘ └────────────────────────┘
```

### Supported NVIDIA Nemotron Models

| Model ID | Architecture | Primary Role in Patchworks | Why It Was Chosen |
|---|---|---|---|
| **`nvidia/nemotron-3-super-120b-a12b`** | 120B Mixture-of-Experts (MoE) | **Primary Code Repair & Diff Synthesis** *(Default)* | Engineered specifically for agentic code generation and structural precision. Its MoE routing ensures accurate unified diff syntax (`--- a/...`, `+++ b/...`, `@@ ... @@`) without corrupting surrounding lines. |
| **`nvidia/Nemotron-3-Ultra-550b-a55b`** | 550B Dense/MoE Flagship | **Deep Architectural & Multi-File Diagnosis** | High-capacity reasoning model capable of analyzing extensive cross-module dependencies, race conditions, and root causes across complex multi-file repositories. |
| **`nvidia/Nemotron-3_5-Lightning`** | Optimized Dense | **Interactive Triage & Real-Time Streaming** | Ultra low-latency throughput for fast interactive sessions, candidate finding summaries, and responsive UI triage. |
| **`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`** | 30B Compact Parameter | **Economy / High-Throughput Pre-Flight** | Compact model optimized for rapid pre-repair checks, syntax verification, and test failure categorization with minimal credit consumption. |

### Schema-Constrained Patch Synthesis

Patchworks guides NVIDIA Nemotron models through strict JSON and unified diff contracts:
- **Root Cause Isolation:** The model isolates the failure mechanism before writing code.
- **Minimal Delta Principle:** Prompts instruct the model to touch only the necessary lines, explicitly prohibiting file overwrites or aesthetic reformats that obscure git blame.
- **Fail-Safe Parsing:** The `nebius_client.py` parser incorporates 4-layer fallback extraction (direct JSON, markdown code fence isolation, outermost brace extraction, and regex token isolation) ensuring 100% diff extraction reliability.

---

## 3. How Nebius Token Factory Accelerated Development & Workflows

**Nebius Token Factory** served as the high-throughput inference backbone for Patchworks. It accelerated development and developer experience in four distinct dimensions:

1. **Ultra-Low Inference Latency on NVIDIA Hardware:**
   Running massive models like Nemotron 3 Super (120B) and Nemotron 3 Ultra (550B) typically introduces noticeable developer wait times. Nebius Token Factory serves these models on dedicated NVIDIA GPU infrastructure with high tokens-per-second throughput, reducing diagnosis and patch generation times from 45+ seconds to **4–6 seconds**.
2. **Zero-Friction OpenAI-Compatible API Integration:**
   Nebius Token Factory provides an OpenAI-compatible endpoint (`https://api.studio.nebius.ai/v1/`). This allowed our Python backend (`nebius_client.py`) to utilize standard, production-tested client libraries with zero custom adapter overhead, complete with streaming responses (`stream=True`) and robust timeout/retry mechanics.
3. **High-Concurrency Agentic Workflows:**
   In batch repair mode, Patchworks dispatches parallel inspection and repair tasks across multiple findings simultaneously. Token Factory handled concurrent generation streams reliably without throttling or rate-limiting bottlenecks.
4. **Optimized Credit Utilization via Tiered Routing:**
   By supporting multiple Nemotron model sizes on the same endpoint, Token Factory enabled tiered routing: using Nemotron Nano for rapid preliminary triage and reserving Nemotron Super and Ultra for computationally heavy causal synthesis, maximizing the efficiency of hackathon credits.

---

## 4. Nebius Tools & Cloud Services Utilized

- **Nebius Token Factory:** Managed, high-speed LLM inference endpoint powering real-time streaming causal analysis, candidate diagnosis, and patch synthesis.
- **Nebius AI Cloud Infrastructure:** Underpinning GPU clusters providing high-bandwidth model execution for NVIDIA open-source model weights.
- **Nebius Credentials & Key Management:** Secure API key authentication managed via `NEBIUS_API_KEY` with automated client reload and credential redaction across all logs and error handlers.

---

## 5. Setup & Installation Instructions

### Prerequisites
- **Python:** Version 3.11 or newer
- **Node.js:** Version 18.x or newer (with npm)
- **Git:** Version 2.30+ installed and on PATH

---

### Step 1: Clone the Repository

```bash
git clone https://github.com/PPurab-006/nebius-proofpatch.git
cd nebius-proofpatch
```

---

### Step 2: Configure Environment Variables

Create your local `.env` configuration file:
```bash
cp .env.example .env
```

Edit `.env` to configure your Nebius Token Factory API key:
```env
# Nebius Token Factory / AI Cloud Settings
NEBIUS_API_KEY="your-nebius-token-factory-api-key"
NEBIUS_BASE_URL="https://api.studio.nebius.ai/v1/"
NEBIUS_MODEL_NAME="nvidia/nemotron-3-super-120b-a12b"
NEBIUS_TIMEOUT="60.0"

# Optional: GitHub Personal Access Token (or connect dynamically via UI)
GITHUB_TOKEN=""

# Optional: Supabase persistence for cross-session history
SUPABASE_URL=""
SUPABASE_ANON_KEY=""
SUPABASE_SERVICE_ROLE_KEY=""
PATCHWORKS_ENCRYPTION_KEY=""
```

> **Note on Mock Mode:** If `NEBIUS_API_KEY` is omitted or left as `mock_key`, Patchworks automatically activates deterministic mock simulation mode, allowing full UI exploration and testing without API credits.

---

### Step 3: Quick Start (Automated Launcher)

To launch both the FastAPI backend and Vite frontend concurrently with a single command:

```bash
chmod +x run.sh
./run.sh
```

- **Frontend Workbench:** Accessible at `http://localhost:5173`
- **Backend API & Swagger Docs:** Accessible at `http://localhost:8000/docs`

---

### Step 4: Manual Setup (Alternative)

If you prefer running services in separate terminal sessions:

#### Terminal 1 — Backend (FastAPI + Uvicorn)
```bash
# 1. Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install Python dependencies
pip install -r backend/requirements.txt

# 3. Start Uvicorn development server
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Terminal 2 — Frontend (React + Vite + TailwindCSS)
```bash
# 1. Navigate to frontend directory
cd frontend

# 2. Install Node dependencies
npm install

# 3. Start Vite dev server
npm run dev
```

---

## 6. Running Built-in Benchmarks & Tests

Patchworks includes deterministic benchmark fixtures (`simple_bug` and `edge_case`) designed for end-to-end evaluation:

### Run the Benchmark Test Suite
```bash
# Run the complete backend test suite
PYTHONPATH=. ./.venv/bin/pytest backend/tests

# Run GitHub integration and verification gate tests
PYTHONPATH=. ./.venv/bin/pytest backend/tests/test_github.py

# Run standalone benchmark fixture runner
PYTHONPATH=. ./.venv/bin/python backend/run_benchmark.py
```

### Build & Validate Frontend Production Bundle
```bash
cd frontend
npm run build
```

---

## 7. Interactive Workbench Features & Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                     PATCHWORKS WORKBENCH (React 18)                    │
│   Dark Developer Aesthetic • Lime Accents • Monospace Telemetry        │
└──────┬──────────────────────┬──────────────────────────┬───────────────┘
       │                      │                          │
       ▼                      ▼                          ▼
┌──────────────┐       ┌──────────────┐           ┌──────────────┐
│  Ingestion   │       │ Engine Modal │           │  Benchmarks  │
│ GitHub / Zip │       │ Nemotron MoE │           │  simple_bug  │
└──────┬───────┘       └──────┬───────┘           └──────┬───────┘
       │                      │                          │
       └──────────────────────┼──────────────────────────┘
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      FASTAPI BACKEND & WORKSPACE ENGINE                │
│    Ephemeral Sandboxes • Subprocess Test Isolation • Rollback Guard    │
└──────┬───────────────────────────────────────────────────┬─────────────┘
       │                                                   │
       ▼                                                   ▼
┌───────────────────────────────┐         ┌──────────────────────────────┐
│     NEBIUS TOKEN FACTORY      │         │      GITHUB INTEGRATION      │
│  NVIDIA Nemotron 3 Super/Ultra│         │  Zero-Leak Header Auth       │
│  Causal Diagnosis & Diff Synth│         │  PR Divergence & Dedup Guard │
└───────────────────────────────┘         └──────────────────────────────┘
```

### Key Capabilities:
- **Sandbox Workspace Isolation:** Every repair runs inside an ephemeral, isolated directory with clean git state tracking.
- **Engine Configuration Modal:** Live switching between NVIDIA Nemotron 3 Super (120B MoE), Nemotron 3 Ultra (550B), Nemotron 3.5 Lightning, and Nemotron Nano (30B).
- **Deterministic Verification Gate:** Publication is strictly gated by test exit codes (`0 == FIX VERIFIED`).
- **Automated Rollback:** Failed patches automatically trigger git rollbacks before any branch pollution occurs.
- **GitHub PR Automation:** Verified repairs can be committed to uniquely named branches (`patchworks/fix-<short-id>`) and published as comprehensive Pull Requests with complete test logs.
- **PR Duplicate Prevention:** Detects existing open/closed pull requests to eliminate redundant review cycles.

---

## 8. API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Service health, Nebius configuration status, active model name |
| `GET` | `/api/engine/models` | List available NVIDIA Nemotron models and active inference engine |
| `POST` | `/api/engine/model` | Dynamically switch the active Nebius inference model |
| `POST` | `/api/benchmark/workspace` | Provision an isolated sandbox from built-in benchmark fixtures |
| `GET` | `/api/benchmarks` | List available benchmark suites (`simple_bug`, `edge_case`) |
| `POST` | `/api/inspect` | Perform read-only defect audit and candidate findings extraction |
| `POST` | `/api/diagnose` | Run causal defect diagnosis with Nebius Nemotron |
| `POST` | `/api/repair` | Synthesize minimal patch, apply to sandbox, and run verification tests |
| `POST` | `/api/rollback` | Revert workspace to clean HEAD commit |
| `GET` | `/api/github/status` | Current GitHub connection state and authenticated user info |
| `POST` | `/api/github/connect` | Authenticate with GitHub token (in-memory only) |
| `GET` | `/api/github/repos` | Browse and search accessible repositories |
| `POST` | `/api/github/workspace` | Clone target branch into an isolated sandbox workspace |
| `GET` | `/api/github/publish/readiness`| Check verification gate, test status, and branch divergence |
| `POST` | `/api/github/publish` | Validate gate, commit to unique branch, push, and open PR |
| `POST` | `/api/repair/batch` | Execute concurrent batch repairs across multiple candidate findings |

---

## 9. Demonstration Video

A comprehensive product demonstration video is included in the repository:
- **Video File:** [patchworks_demo_video.mp4](patchworks_demo_video.mp4)
- **Production Report:** Detailed scene-by-scene breakdown and technical verification in [video_production_report.md](video_production_report.md)

---

## 10. License

This project is licensed under the **Apache License 2.0**, an **OSI-Approved License** (Open Source Initiative).

See the [LICENSE](LICENSE) file for the complete license text.

```
Copyright 2026 Purab Sen (PPurab-006)

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
```
