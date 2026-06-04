from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from auc.agent import AgentConfig, DefaultAgent
from auc.integration.slicer import SemanticSlicer
from auc.messages import RunRequest, RunResult
from auc.ports.approval import ApprovalPort
from auc.ports.memory import ContextComposer, MemoryPort
from auc.ports.package import ContextPackage, SlicerPolicy
from auc.ports.rules import ProjectRulesPort


@dataclass
class SpecialistSpec:
    agent_id: str
    tags: list[str]
    description: str = ""
    config_builder: Callable[[], AgentConfig] | None = None


@dataclass
class SpecialistRegistry:
    _specs: dict[str, SpecialistSpec] = field(default_factory=dict)
    _default_id: str | None = None

    def register(self, spec: SpecialistSpec, *, default: bool = False) -> None:
        self._specs[spec.agent_id] = spec
        if default:
            self._default_id = spec.agent_id

    def get(self, agent_id: str) -> SpecialistSpec:
        if agent_id not in self._specs:
            raise KeyError(f"unknown specialist: {agent_id}")
        return self._specs[agent_id]

    def list_ids(self) -> list[str]:
        return list(self._specs.keys())

    def resolve_for_intent(self, intent: str) -> SpecialistSpec:
        low = intent.lower()
        best: SpecialistSpec | None = None
        best_score = 0
        for spec in self._specs.values():
            score = sum(1 for tag in spec.tags if tag.lower() in low)
            if score > best_score:
                best_score = score
                best = spec
        if best is not None:
            return best
        if self._default_id:
            return self._specs[self._default_id]
        raise RuntimeError("no specialist registered")


@dataclass
class MetaDispatcher:
    """AuM-style task dispatch: slice → rules → run Specialist (OpenClaw pattern)."""

    registry: SpecialistRegistry
    slicer: SemanticSlicer | None = None
    rules_port: ProjectRulesPort | None = None
    memory: MemoryPort | None = None
    composer: ContextComposer | None = None
    approval: ApprovalPort | None = None
    slicer_policy: SlicerPolicy = field(default_factory=SlicerPolicy)

    async def dispatch(
        self,
        intent: str,
        message: str,
        *,
        repo_root: str,
        specialist_id: str | None = None,
    ) -> RunResult:
        spec = (
            self.registry.get(specialist_id)
            if specialist_id
            else self.registry.resolve_for_intent(intent)
        )
        if spec.config_builder is None:
            raise ValueError(f"specialist {spec.agent_id} has no config_builder")

        package: ContextPackage | None = None
        if self.slicer is not None:
            package = await self.slicer.slice(intent, repo_root)
        elif self.slicer_policy.require_package:
            raise ValueError("SemanticSlicer required but not configured")

        config = spec.config_builder()
        config.memory = config.memory or self.memory
        config.composer = config.composer or self.composer
        config.rules = config.rules or self.rules_port
        config.approval = config.approval or self.approval
        config.slicer_policy = self.slicer_policy

        agent = DefaultAgent(config)
        return await agent.run(
            RunRequest(
                input=message,
                context_package=package,
                metadata={"repo_root": repo_root, "intent": intent},
            )
        )
