"""Per-build session: holds the event queue, runs the build in a thread."""
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from . import cost_tracker, events
from .builder import EventEmittingBuilder
from .raptor_models import (
    TrackingEmbeddingModel,
    TrackingQAModel,
    TrackingSummarizationModel,
)
from .serialization import serialize_tree

logger = logging.getLogger(__name__)


OUT_OF_FUNDS_COPY = (
    "🪙 The AI piggy bank ran dry. The maintainer's been pinged to feed "
    "the meter — usually just a minute or two. Try again shortly."
)


@dataclass
class BuildSession:
    id: str
    text: str
    ip: str = "unknown"
    queue: "asyncio.Queue[events.BuildEvent]" = field(default_factory=asyncio.Queue)
    status: str = "pending"
    tree_json: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_kind: Optional[str] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None

    def emit_threadsafe(self, event: events.BuildEvent) -> None:
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self.queue.put_nowait, event)

    def _recorder(self, model: str, in_toks: int, out_toks: int) -> None:
        cost_tracker.record_usage_threadsafe(model, in_toks, out_toks, self.ip)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        cost_tracker.bind_loop(self._loop)
        self.status = "running"
        try:
            await asyncio.to_thread(self._build_sync)
            self.status = "done"
            self.emit_threadsafe(events.done(self.tree_json or {}))
        except Exception as exc:
            # Out-of-funds gets dedicated, friendly UX. We *keep* whatever
            # tree got built so the user sees the partial result.
            if cost_tracker.is_insufficient_quota_error(exc):
                logger.warning("Build %s halted: insufficient_quota", self.id)
                self.status = "error"
                self.error = OUT_OF_FUNDS_COPY
                self.error_kind = "out_of_funds"
                # Serialize whatever leaves/summaries managed to land.
                try:
                    partial = getattr(self, "_partial_tree", None)
                    if partial is not None:
                        self.tree_json = serialize_tree(partial)
                except Exception:
                    logger.exception("Could not serialize partial tree.")
                self.emit_threadsafe(
                    events.error(OUT_OF_FUNDS_COPY, kind="out_of_funds")
                )
            else:
                logger.exception("Build %s failed", self.id)
                self.status = "error"
                self.error = str(exc)
                self.error_kind = "generic"
                self.emit_threadsafe(events.error(str(exc), kind="generic"))

    def _build_sync(self) -> None:
        from raptor import RetrievalAugmentationConfig
        from raptor.cluster_tree_builder import ClusterTreeConfig

        embedding_model = TrackingEmbeddingModel(self._recorder)
        summarization_model = TrackingSummarizationModel(self._recorder)
        qa_model = TrackingQAModel(self._recorder)
        # When `embedding_model` is supplied, RAPTOR keys node embeddings
        # under "EMB" instead of "OpenAI". Stash both so the query endpoint
        # can rebuild a TreeRetrieverConfig pointed at the right key.
        self._embedding_model = embedding_model
        self._embedding_key = "EMB"

        cfg = RetrievalAugmentationConfig(
            tb_max_tokens=40,
            tb_num_layers=3,
            embedding_model=embedding_model,
            summarization_model=summarization_model,
            qa_model=qa_model,
        )
        builder_cfg = cfg.tree_builder_config
        assert isinstance(builder_cfg, ClusterTreeConfig)
        builder_cfg.reduction_dimension = 3

        builder = EventEmittingBuilder(builder_cfg)
        builder.emit_fn = self.emit_threadsafe

        # Stash the in-progress all_nodes ref so we can serialize a partial
        # tree if the build dies mid-flight (e.g. OpenAI runs out of funds).
        self._install_partial_tree_hook(builder)

        self._qa_model = qa_model
        tree = builder.build_from_text(self.text, use_multithreading=False)
        self.tree_json = serialize_tree(tree)
        self._tree = tree

    # --- partial tree capture --------------------------------------------

    def _install_partial_tree_hook(self, builder: EventEmittingBuilder) -> None:
        """Wrap construct_tree to keep a snapshot of nodes/edges-so-far."""
        from raptor.tree_structures import Tree

        original = builder.construct_tree
        session = self

        def wrapped(current_level_nodes, all_tree_nodes, layer_to_nodes, **kw):
            # Take a baseline snapshot before any clustering kicks off.
            session._refresh_partial(all_tree_nodes, layer_to_nodes)
            try:
                return original(current_level_nodes, all_tree_nodes, layer_to_nodes, **kw)
            finally:
                # And again on the way out (success or failure).
                session._refresh_partial(all_tree_nodes, layer_to_nodes)

        builder.construct_tree = wrapped  # type: ignore[method-assign]

        # Also snapshot after leaves are created.
        original_leaves = builder.multithreaded_create_leaf_nodes

        def wrapped_leaves(chunks):
            leaves = original_leaves(chunks)
            session._refresh_partial(dict(leaves), {0: list(leaves.values())})
            return leaves

        builder.multithreaded_create_leaf_nodes = wrapped_leaves  # type: ignore[method-assign]

    def _refresh_partial(self, all_nodes: Dict[int, Any], layer_to_nodes: Dict[int, Any]) -> None:
        from raptor.tree_structures import Tree

        if not all_nodes:
            return
        # root_nodes = top layer's nodes; leaf_nodes = layer 0
        max_layer = max(layer_to_nodes) if layer_to_nodes else 0
        roots = layer_to_nodes.get(max_layer, [])
        leaves = layer_to_nodes.get(0, [])
        self._partial_tree = Tree(dict(all_nodes), roots, leaves, max_layer, dict(layer_to_nodes))

    @property
    def tree(self):
        return getattr(self, "_tree", None) or getattr(self, "_partial_tree", None)

    @property
    def qa_model(self):
        return getattr(self, "_qa_model", None)

    @property
    def embedding_model(self):
        return getattr(self, "_embedding_model", None)

    @property
    def embedding_key(self) -> str:
        return getattr(self, "_embedding_key", "OpenAI")


class BuildRegistry:
    def __init__(self) -> None:
        self._sessions: Dict[str, BuildSession] = {}

    def create(self, text: str, ip: str = "unknown") -> BuildSession:
        session = BuildSession(id=uuid.uuid4().hex, text=text, ip=ip)
        self._sessions[session.id] = session
        return session

    def get(self, build_id: str) -> Optional[BuildSession]:
        return self._sessions.get(build_id)


registry = BuildRegistry()
