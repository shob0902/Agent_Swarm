"""Docker sandbox wrapper.

Every Coder/Tester run happens in a fresh, ephemeral container -- generated
code never executes on the host. `network_disabled=True` is non-negotiable:
the Coder agent's output must not be able to phone home or fetch anything
from inside the sandbox. This is the only place in the project that is
allowed to run arbitrary code (Section 13: no arbitrary shell execution
outside the sandboxed container, ever).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import docker
import docker.errors
import requests.exceptions
from django.conf import settings

logger = logging.getLogger(__name__)


class SandboxError(Exception):
    """Raised for sandbox infrastructure failures (Docker unreachable, image pull failed, ...)."""


class SandboxTimeoutError(SandboxError):
    """Raised when the container did not finish within the timeout."""


@dataclass
class SandboxResult:
    exit_code: int
    logs: str
    timed_out: bool = False


def run_in_sandbox(
    repo_path: str,
    command: list[str],
    timeout: int | None = None,
    image: str | None = None,
) -> SandboxResult:
    """Run `command` inside a throwaway container with `repo_path` bind-mounted
    read/write at /workspace, then remove the container regardless of outcome.
    """
    timeout = timeout or settings.SANDBOX_TIMEOUT_SECONDS
    image = image or settings.SANDBOX_IMAGE

    try:
        client = docker.from_env()
    except docker.errors.DockerException as exc:
        raise SandboxError(f"Could not connect to Docker daemon: {exc}") from exc

    container = None
    try:
        container = client.containers.run(
            image,
            command,
            volumes={repo_path: {"bind": "/workspace", "mode": "rw"}},
            working_dir="/workspace",
            detach=True,
            mem_limit="512m",
            network_disabled=True,  # generated code gets zero network access
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


def _force_kill(container) -> None:
    try:
        container.kill()
    except docker.errors.APIError:
        pass  # already dead/exited -- fine, remove() below still runs


def _force_remove(container) -> None:
    try:
        container.remove(force=True)
    except docker.errors.APIError as exc:
        logger.warning("Failed to remove sandbox container %s: %s", getattr(container, "short_id", "?"), exc)
