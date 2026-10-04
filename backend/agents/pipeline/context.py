# The per-run object handed to every agent in place of the old Celery-side Task instance.
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
if TYPE_CHECKING:
    from .reporting import Reporter
@dataclass
class PipelineContext:
    # What the agents need to know about the task, plus the reporter they log runs through.
    task_id: int
    description: str
    github_url: str
    reporter: "Reporter"
    local_path: str = ""
    base_branch: str = ""
    base_sha: str = ""
    profile: Any = None
    run_url: str = ""
    checkpoint: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    @property
    def id(self) -> int:
        # Alias so log lines written against the old Task model (task.id) keep working.
        return self.task_id
