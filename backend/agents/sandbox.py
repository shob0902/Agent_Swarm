# Runs untrusted generated code inside a throwaway Docker container with no network access.
from __future__ import annotations
import logging
import os
from dataclasses import dataclass
import docker
import docker.errors
import requests.exceptions
from django.conf import settings
logger = logging.getLogger(__name__)
class SandboxError(Exception):
    # Raised when the sandbox infrastructure itself fails, e.g. Docker is unreachable.
    pass
class SandboxTimeoutError(SandboxError):
    # Raised when the container did not finish inside the allowed time.
    pass
@dataclass
class SandboxResult:
    # Outcome of one sandbox run: exit code, captured logs and whether it timed out.
    exit_code: int
    logs: str
    timed_out: bool = False
# Never pass host environment through; only these fixed values (plus the caller's explicit extras) reach the container.
BASE_ENVIRONMENT = {
    "HOME": "/tmp",
    "CI": "true",
    "npm_config_cache": "/tmp/.npm",
    "npm_config_update_notifier": "false",
    "COREPACK_HOME": "/tmp/.corepack",
    "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
    "PIP_CACHE_DIR": "/tmp/.pip",
    "PYTHONDONTWRITEBYTECODE": "1",
}
def run_in_sandbox(
    repo_path: str,
    command: list[str],
    timeout: int | None = None,
    image: str | None = None,
    environment: dict[str, str] | None = None,
    allow_network: bool = False,
) -> SandboxResult:
    # Runs the command against the repo mounted at /workspace and always tears the container down after.
    # allow_network is only ever set for dependency installation; tests, builds and lint run offline.
    timeout = timeout or settings.SANDBOX_TIMEOUT_SECONDS
    image = image or settings.SANDBOX_IMAGE
    client = _docker_client()
    container = None
    try:
        container = client.containers.run(
            image,
            command,
            volumes={repo_path: {"bind": "/workspace", "mode": "rw"}},
            working_dir="/workspace",
            detach=True,
            mem_limit=settings.SANDBOX_MEMORY_LIMIT,
            network_disabled=not allow_network,
            environment={**BASE_ENVIRONMENT, **(environment or {})},
            user=_host_user(),
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            pids_limit=512,
        )
    except docker.errors.ImageNotFound as exc:
        raise SandboxError(f"Sandbox image {image!r} not found and could not be pulled: {exc}") from exc
    except docker.errors.APIError as exc:
        raise SandboxError(f"Docker API error starting sandbox container: {exc}") from exc
    try:
        try:
            wait_result = container.wait(timeout=timeout)
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as exc:
            logger.warning("Sandbox container %s timed out after %ss", container.short_id, timeout)
            _force_kill(container)
            return SandboxResult(exit_code=-1, logs=f"Sandbox execution timed out after {timeout}s", timed_out=True)
        logs = container.logs().decode("utf-8", errors="replace")
        return SandboxResult(exit_code=wait_result.get("StatusCode", -1), logs=logs)
    finally:
        _force_remove(container)
_CLIENT = None
def _docker_client():
    # One Docker client per process: every check reuses it instead of re-reading the environment and
    # opening a new connection to the daemon. A failed connection isn't cached, so the next call retries.
    global _CLIENT
    if _CLIENT is None:
        try:
            _CLIENT = docker.from_env()
        except docker.errors.DockerException as exc:
            raise SandboxError(f"Could not connect to Docker daemon: {exc}") from exc
    return _CLIENT
def _host_user() -> str | None:
    # On Linux (e.g. the GitHub Actions runner) run as the host user so files written into the clone stay ours.
    if hasattr(os, "getuid"):
        return f"{os.getuid()}:{os.getgid()}"
    return None
def _force_kill(container) -> None:
    # Kills a container that overran its timeout, ignoring the case where it already exited.
    try:
        container.kill()
    except docker.errors.APIError:
        pass
def _force_remove(container) -> None:
    # Deletes the container and just logs a warning if Docker refuses.
    try:
        container.remove(force=True)
    except docker.errors.APIError as exc:
        logger.warning("Failed to remove sandbox container %s: %s", getattr(container, "short_id", "?"), exc)
