# nebius-proofpatch (ProofPatch)

> **Nebius × NVIDIA Global AI Hackathon** &bull; Evidence-Driven Autonomous Code-Repair Agent

---

## 1. Project Overview

**ProofPatch** is an evidence-driven autonomous code-repair agent. Instead of speculative code patching, ProofPatch adheres to a strict scientific verification cycle:
1. **Reproduce:** Clone into an isolated workspace and verify failure reproduction (tests or output).
2. **Synthesize:** Query eligible **NVIDIA open-source models** (`nvidia/Llama-3.1-Nemotron-70B-Instruct`) served via **Nebius AI Cloud / Token Factory** to propose targeted, minimal patches.
3. **Verify:** Apply the patch using strict uni-diff formatting and run testing inside the sandboxed space.
4. **Certify:** Deliver only patches with empirical proof of defect resolution and zero regressions.

## 2. Running ProofPatch Locally

This MVP supports local evaluation and uses mock functionality if the Nebius API keys are unconfigured.

### Start Backend

1. Navigate to backend: `cd backend`
2. Install reqs: `pip install -r requirements.txt` (or via uv: `uv pip install -r requirements.txt`)
3. Configure environment variables (copy `.env.example` to `.env`).
4. Run server: `PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000`

### Start Frontend

1. Navigate to frontend: `cd frontend`
2. Install deps: `npm install`
3. Run dev server: `npm run dev` (Vite dev runner on port 5173).

### Automated Runner

You can also run both services simultaneously using the root launcher:
```bash
./run.sh
```

## 3. Supported Workflows and Sandbox

ProofPatch accepts public/local Git repository URLs. For benchmarking, use the provided `benchmark_fixtures/`.

**Security Sandbox Guarantees:**
- **No Path Traversal:** Validates patch target paths strictly prevent relative (`../`) and absolute breakout.
- **SSRF Protection:** Ingestion restricts clones to `http`, `https`, and (for local demo purposes only) `file`.
- **Subprocess Isolation:** `WorkspaceManager` limits test runs to explicit allowed test commands (`pytest`, `python`, `python3`) and utilizes secure argument parsing with `shlex` and `shell=False` to explicitly prevent command shell injections (RCE).
- **Stateless Workspaces:** Workspaces are cloned into randomized temp directories and scrubbed upon completion.

## 4. Evaluation and Benchmarking

Included in `benchmark_fixtures/`:
- `simple_bug`: Validates basic Python AST-level patching (`math_utils.py` logic error). Reproduces failure under `pytest test_math_utils.py`, patches cleanly, and transitions from failure to verified fix.
- `edge_case`: Validates model capability resolving boundary errors (`text_utils.py` off-by-one boundary truncation). Ensures proper status transition on unverified/failed repairs.

*In live testing with Nebius Token Factory, `nvidia/Llama-3.1-Nemotron-70B-Instruct` is configured as the primary code diagnosis and repair model, with fallback mock verification when unconfigured.*

## 5. Architectural Decisions

- **Frontend:** React 19 + TypeScript + Vite + Tailwind CSS.
- **Backend:** FastAPI + `gitpython` + `unidiff`.
- **Model Gateway:** Nebius's OpenAI-compatible completions mapping targeting `nvidia/Llama-3.1-Nemotron-70B-Instruct`.

---

## License

This project is licensed under the **Apache License 2.0**.
