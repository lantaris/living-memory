"""Living-memory: layered persistent memory for Hermes (MemoryProvider plugin).

Discovery contract: this file must mention ``register_memory_provider`` /
``MemoryProvider`` (text scan) and ``register(ctx)`` must hand the provider to
``ctx.register_memory_provider``. Activation is ``memory.provider: living-memory``
in config.yaml - not ``plugins.enabled``.
"""

from __future__ import annotations

from pathlib import Path

from .hermes_provider import LivingMemoryProvider

_SKILL_PATH = Path(__file__).resolve().parent / "skills" / "living-memory" / "SKILL.md"


def register(ctx) -> None:
    """Plugin entry point: auxiliary LLM task + the memory provider."""
    try:
        ctx.register_auxiliary_task(
            "living_memory_compress",
            display_name="Living memory compression",
            description=(
                "Compress a conversation tail into the living-memory store "
                "(core facts, session tasks, loss log)."
            ),
            inherit_from="compression",
        )
    except Exception:
        # The task registration is an optimisation (model inheritance); the
        # provider still works without it.
        pass
    try:
        ctx.register_skill(
            "living-memory",
            _SKILL_PATH,
            description=(
                "Layered living memory: when to use memory_search and memory_pending, "
                "and how the memory block reaches your context."
            ),
        )
    except Exception:
        # Skills are read-only guidance; losing them must not cost the provider.
        pass
    ctx.register_memory_provider(LivingMemoryProvider(ctx=ctx))
