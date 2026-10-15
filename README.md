# nebius-proofpatch (ProofPatch)

> **Nebius × NVIDIA Global AI Hackathon** &bull; Evidence-Driven Autonomous Code-Repair Agent

---

## 1. Project Overview

**ProofPatch** is an evidence-driven autonomous code-repair agent. Instead of speculative code patching, ProofPatch adheres to a strict scientific verification cycle:
1. **Reproduce:** Synthesize an isolated regression test proving the bug exists and fails on the base commit.
2. **Synthesize:** Query eligible **NVIDIA open-source models** (e.g., Nemotron) served via **Nebius AI Cloud / Token Factory** to propose targeted, minimal patches.
3. **Verify:** Execute the test suite and regression tests inside an isolated sandbox.
4. **Certify:** Deliver only patches with empirical proof of defect resolution and zero regressions.

---

## 2. Competition Requirements & Preserved Constraints

> [!IMPORTANT]
> **Implementation Status: Repository Setup Phase (Pre-Implementation)**  
> This repository is in the initial setup phase. In strict accordance with competition setup constraints, no cloud infrastructure has been provisioned, no models downloaded, and zero cloud credits consumed.

The following core hackathon requirements are preserved for future implementation:
- **Nebius Infrastructure:** The application pipeline must run on Nebius AI Cloud infrastructure or utilize Nebius Token Factory endpoints.
- **NVIDIA Open-Source Model:** Core code analysis and repair synthesis will utilize at least one eligible NVIDIA open-source model (such as NVIDIA Nemotron).
- **Comprehensive Documentation:** Full technical disclosure of models, infrastructure topology, setup workflows, and evaluation results.
- **Transparent Evaluation:** Systematic evaluation on bug benchmarks with honest reporting of successes, partial fixes, and failure modes.

---

## 3. Strict Engineering & Anti-Fabrication Principles

- **Zero Fabricated Results:** No simulated benchmarks, false repair rates, or unverified claims.
- **No Committed Secrets:** Nebius API tokens, NVIDIA NIM keys, and cloud credentials are strictly excluded via `.gitignore` and handled via secure environment variables.
- **Autonomous Repository:** Completely decoupled repository with independent versioning, tests, and configuration.

---

## 4. Repository Structure

```
nebius-proofpatch/
├── LICENSE                          # Apache-2.0 License
├── README.md                        # Project documentation & status
├── .gitignore                       # Environment, token, sandbox & build guards
├── docs/                            # Competition requirements & architecture
│   └── competition_requirements.md  # Preserved competition requirements
└── tests/                           # Reproduction & patch verification test harness (planned)
```

---

## 5. License

This project is licensed under the **Apache License 2.0** — see the [LICENSE](LICENSE) file for details.
