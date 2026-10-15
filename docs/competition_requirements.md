# Nebius × NVIDIA Global AI Hackathon: Requirements & Architectural Preservations

## 1. Competition Overview

- **Competition:** [Nebius × NVIDIA Global AI Hackathon](https://nebius.com/)
- **Project Name:** ProofPatch
- **Domain:** Autonomous, evidence-driven code-repair agent.

## 2. Mandatory Competition Requirements to Preserve

The following technical mandates must be preserved throughout development and final submission:

1. **Nebius Infrastructure / Token Factory:**
   - The solution must execute on **Nebius AI Cloud** infrastructure or utilize **Nebius Token Factory** for model serving and token inference.
   - *Current phase guard:* Do not provision cloud instances, spin up clusters, or consume Nebius cloud credits during repository setup.
2. **Eligible NVIDIA Open-Source Model:**
   - The agentic loop must incorporate and run at least one eligible **NVIDIA open-source model** (e.g., NVIDIA Nemotron family such as `nvidia/Llama-3.1-Nemotron-70B-Instruct`).
   - *Current phase guard:* Do not download weights, cache large model files, or initiate remote inference jobs during setup.
3. **Rigorous Technical Documentation & Setup:**
   - The submission requires complete technical documentation of the model family, architecture, infrastructure deployment steps, and environment configuration.
4. **Empirical Evaluation & Benchmarking:**
   - Transparent evaluation on real-world bug benchmarks (e.g., SWE-bench Lite subsets or curated testbeds).
   - Exact patch verification metrics: Reproduction rate, pass rate, minimal diff ratio, and regression prevention rate.
   - Full disclosure of failed repairs and edge cases.
5. **Open-Source Compliance:**
   - Open-source repository licensed under Apache-2.0.

## 3. ProofPatch Agentic Loop Architecture

ProofPatch implements a 4-stage evidence-driven repair cycle:
1. **Bug Reproduction:** Parse issue/trace, construct an isolated reproducing test case, and verify that the test fails on unpatched code (`Evidence of Bug`).
2. **Patch Synthesis:** Prompt the NVIDIA open-source model served on Nebius Token Factory with code context and reproduction evidence to draft a minimal, AST-preserving patch.
3. **Regression & Safety Verification:** Run both the reproduction test and the existing test suite in an isolated sandbox.
4. **Patch Certification:** Accept the patch only if the reproducing test passes and zero regressions occur.
