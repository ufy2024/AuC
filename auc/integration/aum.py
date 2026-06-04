from __future__ import annotations

from dataclasses import dataclass

from auc.integration.dispatcher import MetaDispatcher, SpecialistRegistry
from auc.integration.nuggets import NuggetsMemoryPort, NuggetsStore
from auc.integration.slicer import SemanticSlicer
from auc.ports.approval import ApprovalPort
from auc.ports.memory import ContextComposer, DefaultComposer, MemoryPort
from auc.ports.package import SlicerPolicy
from auc.ports.rules import FileRulesPort, ProjectRulesPort


@dataclass
class AuMStack:
    """Wire AuC reference implementations matching AuM integration docs."""

    slicer: SemanticSlicer
    rules: ProjectRulesPort
    memory: MemoryPort
    composer: ContextComposer
    approval: ApprovalPort
    dispatcher: MetaDispatcher
    nuggets_store: NuggetsStore | None = None

    @classmethod
    def create(
        cls,
        *,
        registry: SpecialistRegistry,
        approval: ApprovalPort,
        nuggets_path: str | None = None,
        base_memory: MemoryPort | None = None,
        require_package: bool = True,
    ) -> AuMStack:
        store = NuggetsStore.from_yaml(nuggets_path) if nuggets_path else None
        memory: MemoryPort = (
            NuggetsMemoryPort(base=base_memory, store=store)
            if store
            else (base_memory or NuggetsMemoryPort())
        )
        slicer = SemanticSlicer()
        rules = FileRulesPort()
        composer = DefaultComposer()
        dispatcher = MetaDispatcher(
            registry=registry,
            slicer=slicer,
            rules_port=rules,
            memory=memory,
            composer=composer,
            approval=approval,
            slicer_policy=SlicerPolicy(require_package=require_package),
        )
        return cls(
            slicer=slicer,
            rules=rules,
            memory=memory,
            composer=composer,
            approval=approval,
            dispatcher=dispatcher,
            nuggets_store=store,
        )
