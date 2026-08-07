# Sandbox image the Tester (and Coder-written-file execution) runs inside.
# python:3.11-slim alone has no test runner and the container has
# network_disabled=True at run time, so anything the toy demo repo needs
# must be baked in here at build time, not pip-installed on the fly.
#
# Build once:
#   docker build -t agent-swarm-sandbox:latest -f docker/sandbox.Dockerfile .
FROM python:3.11-slim

RUN pip install --no-cache-dir \
    pytest==8.2.2 \
    flask==3.0.3 \
    requests==2.32.3
