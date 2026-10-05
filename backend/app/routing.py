"""Task-based model routing for Groq — send cheap tasks to a smaller model.

Why this exists
---------------
The pipeline makes 4-6 LLM calls per question. Only GENERATE needs the
120B model for answer quality. UNDERSTAND, EVALUATE, VERIFY, REFINE,
suggest, and overview are all structured-output tasks that the 20B model
handles just as well — at ~half the per-token cost.

Groq pricing (as of writing):
  - openai/gpt-oss-20b:  $0.075 / $0.30 per 1M tokens (in/out)
  - openai/gpt-oss-120b: $0.15  / $0.60 per 1M tokens (in/out)

Routing the 4 non-generation calls to the 20B model roughly halves the
per-query token bill.
"""

from __future__ import annotations

# Groq model ids
MODEL_SMALL = "openai/gpt-oss-20b"      # cheap, fast, structured-output safe
MODEL_LARGE = "openai/gpt-oss-120b"     # expensive, used only for generation


# Pipeline stage → model.
#
# Rules of thumb:
#   - Tasks that return JSON we parse: use SMALL
#   - Tasks that produce the user-visible answer: use LARGE
#   - Anything ambiguous: default to LARGE (safer)
TASK_ROUTING: dict[str, str] = {
    "understand": MODEL_SMALL,   # rewrite + classify → JSON out
    "evaluate":   MODEL_SMALL,   # is_sufficient → JSON out
    "verify":     MODEL_SMALL,   # citation verdict → JSON out
    "refine":     MODEL_SMALL,   # rewrite query → JSON out
    "suggest":    MODEL_SMALL,   # generate starter questions → JSON array
    "overview":   MODEL_SMALL,   # per-document 2-3 sentence summary
    "generate":   MODEL_LARGE,   # the actual answer — keep the good model
}


def model_for_task(task: str, *, force_large: bool = False) -> str:
    """Return the Groq model id for a given pipeline stage."""
    if force_large:
        return MODEL_LARGE
    return TASK_ROUTING.get(task, MODEL_LARGE)


__all__ = ["MODEL_SMALL", "MODEL_LARGE", "TASK_ROUTING", "model_for_task"]