#!/usr/bin/env bash
# Exit on error
set -o errexit

echo "=== Patchworks Production Build ==="

# Configure fallback git author identity for headless containers
git config --global user.email "bot@proofpatch.test" || true
git config --global user.name "ProofPatch Bot" || true

# 1. Ensure Node.js & npm are available for frontend build
if ! command -v node > /dev/null 2>&1 || ! command -v npm > /dev/null 2>&1; then
    echo "Node.js/npm not found in Python runtime. Bootstrapping portable Node.js LTS..."
    NODE_VERSION="20.18.0"
    mkdir -p /tmp/node_runtime
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" -o /tmp/node.tar.xz
    tar -xf /tmp/node.tar.xz -C /tmp/node_runtime --strip-components=1
    export PATH="/tmp/node_runtime/bin:$PATH"
fi

echo "Using Node: $(node -v) | npm: $(npm -v)"

# 2. Build React/Vite Frontend
echo "--- Building frontend ---"
cd frontend
npm install
npm run build
cd ..

# 3. Install Python Dependencies
echo "--- Installing backend dependencies ---"
if command -v pip > /dev/null 2>&1; then
    pip install -r backend/requirements.txt
elif command -v pip3 > /dev/null 2>&1; then
    pip3 install -r backend/requirements.txt
elif [ -x "./.venv/bin/python" ]; then
    ./.venv/bin/python -m pip install -r backend/requirements.txt
else
    python3 -m pip install -r backend/requirements.txt
fi

echo "=== Build Complete ==="
