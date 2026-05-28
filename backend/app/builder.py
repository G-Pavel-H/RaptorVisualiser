"""Event-emitting RAPTOR builder.

Subclasses ClusterTreeBuilder and overrides two methods to push BuildEvents
to a callback at the right moments. The callback is sync and thread-safe —
the BuildSession owner wraps it with loop.call_soon_threadsafe.

Honesty note: the upstream construct_tree is reimplemented here (copy +
instrumentation) rather than monkey-patched, because the upstream loop
doesn't expose hook points for clustering / per-cluster summarization.
This means future RAPTOR upstream changes to construct_tree won't be
picked up automatically — keep this in sync if the submodule is bumped.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Callable, Dict, List

from raptor.cluster_tree_builder import ClusterTreeBuilder
from raptor.tree_structures import Node
from raptor.utils import get_node_list, get_text

from . import events

# Max concurrent summary calls per layer. OpenAI's chat-completion endpoint
# tolerates this easily; raise if your tier allows more.
SUMMARY_CONCURRENCY = 6

EmitFn = Callable[[events.BuildEvent], None]


class EventEmittingBuilder(ClusterTreeBuilder):
    """ClusterTreeBuilder that pushes BuildEvents to an emit callback.

    Set `emit_fn` before calling build_from_text.
    """

    emit_fn: EmitFn = staticmethod(lambda _e: None)

    # ----- leaf chunking + embedding -----

    def multithreaded_create_leaf_nodes(self, chunks: List[str]) -> Dict[int, Node]:
        # Emit one 'chunked' event before any embedding work, with the chunk ids
        # pre-allocated. The UI shows N pending placeholders immediately.
        self.emit_fn(events.chunked(chunks))

        leaf_nodes: Dict[int, Node] = {}
        lock = Lock()

        def one(index: int, text: str) -> None:
            _, node = self.create_node(index, text)
            with lock:
                leaf_nodes[index] = node
            self.emit_fn(events.embedded(index, text))

        with ThreadPoolExecutor(max_workers=SUMMARY_CONCURRENCY) as ex:
            futures = [ex.submit(one, i, t) for i, t in enumerate(chunks)]
            for f in as_completed(futures):
                f.result()

        self.emit_fn(events.layer_complete(0, len(leaf_nodes)))
        return leaf_nodes

    # ----- cluster / summarize / layer -----

    def construct_tree(
        self,
        current_level_nodes: Dict[int, Node],
        all_tree_nodes: Dict[int, Node],
        layer_to_nodes: Dict[int, List[Node]],
        use_multithreading: bool = False,
    ) -> Dict[int, Node]:
        next_node_index = len(all_tree_nodes)

        for layer in range(self.num_layers):
            new_level_nodes: Dict[int, Node] = {}
            node_list_current_layer = get_node_list(current_level_nodes)

            if len(node_list_current_layer) <= self.reduction_dimension + 1:
                self.num_layers = layer
                break

            clusters = self.clustering_algorithm.perform_clustering(
                node_list_current_layer,
                self.cluster_embedding_model,
                reduction_dimension=self.reduction_dimension,
                **self.clustering_params,
            )

            # Pre-allocate node ids deterministically so the UI's notion of
            # "node 17" matches the final tree regardless of completion order.
            cluster_jobs = []
            for cluster_idx, cluster in enumerate(clusters):
                child_ids = [n.index for n in cluster]
                self.emit_fn(events.cluster_formed(layer + 1, cluster_idx, child_ids))
                cluster_jobs.append((next_node_index, cluster, child_ids))
                next_node_index += 1

            lock = Lock()

            def process_one(job):
                node_id, cluster, child_ids = job
                node_texts = get_text(cluster)
                summarized_text = self.summarize(
                    context=node_texts, max_tokens=self.summarization_length
                )
                _, new_parent_node = self.create_node(
                    node_id, summarized_text, {n.index for n in cluster}
                )
                with lock:
                    new_level_nodes[node_id] = new_parent_node
                self.emit_fn(
                    events.node_summarized(
                        layer + 1, node_id, summarized_text, child_ids
                    )
                )

            with ThreadPoolExecutor(max_workers=SUMMARY_CONCURRENCY) as ex:
                futures = [ex.submit(process_one, j) for j in cluster_jobs]
                for f in as_completed(futures):
                    f.result()  # surface exceptions

            layer_to_nodes[layer + 1] = list(new_level_nodes.values())
            current_level_nodes = new_level_nodes
            all_tree_nodes.update(new_level_nodes)
            self.emit_fn(events.layer_complete(layer + 1, len(new_level_nodes)))

        return current_level_nodes
