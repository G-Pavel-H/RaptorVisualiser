import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiService, SerializedTree } from '../../services/api.service';
import { TVEdge, TVNode, TreeViewComponent } from '../../components/tree-view.component';

type Method = 'collapsed_tree' | 'tree_traversal';

@Component({
  selector: 'app-explore',
  standalone: true,
  imports: [TreeViewComponent, FormsModule, RouterLink],
  template: `
    <div class="explore-layout">
      <div class="canvas">
        <div class="query-bar">
          <input
            class="query-input"
            [(ngModel)]="query"
            placeholder="ask the tree a question…"
            (keydown.enter)="runQuery()"
          />
          <select [(ngModel)]="method">
            <option value="collapsed_tree">collapsed_tree</option>
            <option value="tree_traversal">tree_traversal</option>
          </select>
          <button class="primary" (click)="runQuery()" [disabled]="!query() || querying()">
            {{ querying() ? '…' : 'retrieve' }}
          </button>
        </div>
        <div class="tree-area">
          <app-tree-view
            [nodes]="annotatedNodes()"
            [edges]="edges()"
            [selectedId]="selectedId()"
            (nodeClick)="onNodeClick($event)"
          ></app-tree-view>
        </div>
      </div>

      <aside class="panel side">
        <a class="back muted small" routerLink="/">← new build</a>
        @if (selectedNode()) {
          <div>
            <div class="badge mono">node {{ selectedNode()!.id }} · layer {{ selectedNode()!.layer }}</div>
            <div class="node-text mono">{{ selectedNode()!.text }}</div>
          </div>
        } @else {
          <div class="muted small">click any node to see its full text.</div>
        }

        @if (lastContext()) {
          <div class="section">
            <div class="section-title">assembled context ({{ method() }})</div>
            <div class="ctx mono">{{ lastContext() }}</div>
            <div class="retrieved muted small">
              retrieved: {{ retrievedIds().length }} nodes
              ({{ retrievedIds().join(', ') }})
            </div>
          </div>
        }
      </aside>
    </div>
  `,
  styles: [`
    .explore-layout {
      display: grid;
      grid-template-columns: 1fr 420px;
      gap: 16px;
      padding: 16px;
      height: calc(100vh - 60px);
    }
    .canvas {
      display: flex;
      flex-direction: column;
      background: var(--bg-1);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
    }
    .query-bar {
      display: flex;
      gap: 8px;
      padding: 12px;
      border-bottom: 1px solid var(--border);
      background: var(--bg-2);
    }
    .query-input { flex: 1; }
    .tree-area { flex: 1; }
    .side { display: flex; flex-direction: column; gap: 16px; padding: 18px; overflow-y: auto; }
    .back { display: block; }
    .badge {
      display: inline-block;
      padding: 4px 10px;
      background: var(--accent-soft);
      color: var(--accent);
      border-radius: 999px;
      font-size: 11px;
      margin-bottom: 10px;
    }
    .node-text {
      font-size: 13px;
      line-height: 1.65;
      color: var(--text-0);
      background: var(--bg-1);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 12px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .section { border-top: 1px solid var(--border); padding-top: 14px; }
    .section-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-2); margin-bottom: 8px; }
    .ctx {
      font-size: 12px;
      line-height: 1.6;
      max-height: 280px;
      overflow-y: auto;
      background: var(--bg-1);
      padding: 10px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      color: var(--text-1);
      white-space: pre-wrap;
    }
    .retrieved { margin-top: 8px; }
    .small { font-size: 11px; }
  `],
})
export class ExploreComponent implements OnInit {
  private api = inject(ApiService);
  private route = inject(ActivatedRoute);

  buildId = signal('');
  nodes = signal<TVNode[]>([]);
  edges = signal<TVEdge[]>([]);
  selectedId = signal<number | null>(null);
  query = signal('');
  method = signal<Method>('collapsed_tree');
  querying = signal(false);
  retrievedIds = signal<number[]>([]);
  lastContext = signal<string | null>(null);

  selectedNode = computed(() => {
    const id = this.selectedId();
    return id === null ? null : this.nodes().find((n) => n.id === id) ?? null;
  });

  annotatedNodes = computed(() => {
    const retrieved = new Set(this.retrievedIds());
    return this.nodes().map((n) => ({ ...n, retrieved: retrieved.has(n.id) }));
  });

  ngOnInit() {
    const id = this.route.snapshot.paramMap.get('id') ?? '';
    this.buildId.set(id);
    this.api.getBuild(id).subscribe((b) => {
      if (b.tree) this.loadTree(b.tree);
    });
  }

  private loadTree(t: SerializedTree) {
    this.nodes.set(t.nodes.map((n) => ({ id: n.id, layer: n.layer, text: n.text, children: n.children })));
    this.edges.set(t.edges.map((e) => ({ parent: e.parent, child: e.child })));
  }

  onNodeClick(id: number) { this.selectedId.set(id); }

  runQuery() {
    if (!this.query().trim()) return;
    this.querying.set(true);
    this.api.query(this.buildId(), this.query(), this.method()).subscribe({
      next: (r) => {
        this.retrievedIds.set(r.retrieved_node_ids ?? []);
        this.lastContext.set(r.context ?? '');
        this.querying.set(false);
      },
      error: () => this.querying.set(false),
    });
  }
}
