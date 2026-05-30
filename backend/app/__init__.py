"""Backend package.

Two side-effects at import time:

1. Prepend the vendored RAPTOR submodule to sys.path so `import raptor`
   resolves to backend/vendor/raptor/raptor.

2. Stub heavy ML packages that RAPTOR imports at module-load but we never
   actually use. We provide our own OpenAI-based subclasses for embedding,
   summarization and QA — `SBertEmbeddingModel` and `UnifiedQAModel` are
   never instantiated. Skipping `torch`, `transformers`, `sentence-transformers`
   saves ~2 GB of disk + minutes of install time on Render.
"""
import sys
import types
from pathlib import Path

# 1) sys.path for the vendored submodule
_RAPTOR_VENDOR = Path(__file__).resolve().parent.parent / "vendor" / "raptor"
if _RAPTOR_VENDOR.is_dir() and str(_RAPTOR_VENDOR) not in sys.path:
    sys.path.insert(0, str(_RAPTOR_VENDOR))


# 2) Stubs. Only install them if the real package isn't available; this way a
#    dev machine that does have torch installed will still work normally.
class _StubbedOut:
    """Placeholder for unused upstream classes. Raises if instantiated, so a
    silent-bug-via-empty-class is impossible."""

    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            f"{type(self).__name__} is stubbed out in this deployment — "
            "RaptorVisualiser uses its own OpenAI-based model wrappers."
        )


def _ensure_stub(name: str, attrs: dict | None = None) -> None:
    if name in sys.modules:
        return
    try:
        __import__(name)
    except ImportError:
        mod = types.ModuleType(name)
        for key, value in (attrs or {}).items():
            setattr(mod, key, value)
        sys.modules[name] = mod


# scipy/sklearn probe `torch.Tensor` to decide whether an argument is a
# torch tensor (returning False for non-torch types). A bare stub without
# `Tensor` makes that probe raise. Give it a dummy class — no instance of
# anything we use will ever be a subclass of it, so the probe returns False
# correctly.
_ensure_stub("torch", {"Tensor": type("Tensor", (), {})})
_ensure_stub(
    "sentence_transformers",
    {"SentenceTransformer": type("SentenceTransformer", (_StubbedOut,), {})},
)
_ensure_stub(
    "transformers",
    {
        "T5ForConditionalGeneration": type("T5ForConditionalGeneration", (_StubbedOut,), {}),
        "T5Tokenizer": type("T5Tokenizer", (_StubbedOut,), {}),
    },
)
