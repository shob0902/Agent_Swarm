# Sandbox image the Tester runs every install/build/test/lint command inside.
#
# Tests, builds and lint run with network_disabled=True, so the toolchains
# themselves (Python + Node, test runners, linters) are baked in here at build
# time. The repo's own dependencies are installed per run, in a separate
# network-enabled step that receives no secrets (see agents/services/tester.py).
#
# Build once (locally, and automatically in .github/workflows/agent-swarm.yml):
#   docker build -t agent-swarm-sandbox:latest -f docker/sandbox.Dockerfile .
FROM node:20-bookworm-slim AS node

FROM python:3.11-slim

# Node 20 (with npm, npx and corepack for yarn/pnpm) copied from the official image.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && ln -s ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack \
 && node --version && npm --version

# Python test runner and linters, plus the packages the original demo repo relies on.
RUN pip install --no-cache-dir \
    pytest==8.2.2 \
    ruff==0.6.9 \
    flake8==7.1.1 \
    flask==3.0.3 \
    requests==2.32.3

WORKDIR /workspace
