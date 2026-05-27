"""Per-build session: holds the event queue, runs the build in a thread."""
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from . import events
from .builder import EventEmittingBuilder
from .serialization import serialize_tree

logger = logging.getLogger(__name__)


@dataclass
class BuildSession:
    id: str
    text: str
    queue: "asyncio.Queue[events.BuildEvent]" = field(default_factory=asyncio.Queue)
    status: str = "pending"  # pending | running | done | error
    tree_json: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None

    def emit_threadsafe(self, event: events.BuildEvent) -> None:
        """Called from the worker thread — schedule put_nowait on the loop."""
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self.queue.put_nowait, event)

    async def run(self) -> None:
        """Kick off the build in a worker thread; emit events as it progresses."""
        self._loop = asyncio.get_running_loop()
        self.status = "running"
        try:
            await asyncio.to_thread(self._build_sync)
            self.status = "done"
            self.emit_threadsafe(events.done(self.tree_json or {}))
        except Exception as exc:  # build failures, OpenAI errors, etc.
            logger.exception("Build %s failed", self.id)
            self.status = "error"
            self.error = str(exc)
            self.emit_threadsafe(events.error(str(exc)))

    def _build_sync(self) -> None:
        # Local import keeps RAPTOR (and torch) off the import path until a
        # build actually happens — speeds up app startup and test collection.
        from raptor import RetrievalAugmentationConfig
        from raptor.cluster_tree_builder import ClusterTreeConfig

        cfg = RetrievalAugmentationConfig(tb_max_tokens=40, tb_num_layers=3)
        builder_cfg = cfg.tree_builder_config
        assert isinstance(builder_cfg, ClusterTreeConfig)
        # Default reduction_dimension=10 means RAPTOR refuses to cluster a layer
        # with <=11 nodes — too high for the short paragraphs typical of a demo.
        # Lower it so even ~6 chunks produce a real second layer.
        builder_cfg.reduction_dimension = 3

        builder = EventEmittingBuilder(builder_cfg)
        builder.emit_fn = self.emit_threadsafe

        tree = builder.build_from_text(self.text, use_multithreading=False)
        self.tree_json = serialize_tree(tree)
        # Keep the tree around so query mode can use it without rebuilding.
        self._tree = tree

    @property
    def tree(self):
        return getattr(self, "_tree", None)


class BuildRegistry:
    """Process-local map of build_id → BuildSession."""

    def __init__(self) -> None:
        self._sessions: Dict[str, BuildSession] = {}

    def create(self, text: str) -> BuildSession:
        session = BuildSession(id=uuid.uuid4().hex, text=text)
        self._sessions[session.id] = session
        return session

    def get(self, build_id: str) -> Optional[BuildSession]:
        return self._sessions.get(build_id)


registry = BuildRegistry()
