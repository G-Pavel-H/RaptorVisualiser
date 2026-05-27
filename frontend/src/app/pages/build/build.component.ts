import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';
import { ApiService } from '../../services/api.service';
import { BuildEvent, SseService } from '../../services/sse.service';
import { TVEdge, TVNode, TreeViewComponent } from '../../components/tree-view.component';

@Component({
  selector: 'app-build',
  standalone: true,
  imports: [TreeViewComponent, RouterLink],
  template: `
    <div class="build-layout">
      <div class="canvas">
        <app-tree-view [nodes]="nodes()" [edges]="edges()"></app-tree-view>
      </div>
      <aside class="panel side">
        <div class="header">
          <div class="status-dot" [class.done]="status() === 'done'" [class.error]="status() === 'error'"></div>
          <div>
            <div class="stage mono">{{ stage() ?? 'connecting…' }}</div>
            <div class="muted small">build {{ buildId().slice(0, 8) }}</div>
          </div>
        </div>

        <div class="counters">
          <div class="counter">
            <div class="counter-value">{{ chunkCount() }}</div>
            <div class="counter-label">chunks</div>
          </div>
          <div class="counter">
            <div class="counter-value">{{ clusterCount() }}</div>
            <div class="counter-label">clusters</div>
          </div>
          <div class="counter">
            <div class="counter-value">{{ layerProgress() }}</div>
            <div class="counter-label">layer</div>
          </div>
        </div>

        <div class="log mono">
          @for (line of log(); track $index) {
            <div class="log-line {{ line.stage }}">
              <span class="muted">·</span> {{ line.text }}
            </div>
          }
        </div>

        @if (status() === 'done') {
          <a class="explore-btn" [routerLink]="['/builds', buildId(), 'explore']">explore tree →</a>
        }
        @if (status() === 'error') {
          <div class="error mono small">{{ errorMsg() }}</div>
        }
      </aside>
    </div>
  `,
  styles: [`
    .build-layout {
      display: grid;
      grid-template-columns: 1fr 360px;
      gap: 16px;
      padding: 16px;
      height: calc(100vh - 60px);
    }
    .canvas {
      background: var(--bg-1);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      position: relative;
      overflow: hidden;
    }
    .side {
      display: flex;
      flex-direction: column;
      padding: 18px;
      gap: 16px;
    }
    .header { display: flex; align-items: center; gap: 12px; }
    .status-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 12px var(--accent-glow);
      animation: shimmer 1.4s var(--easing) infinite;
    }
    .status-dot.done { background: var(--lime); animation: none; box-shadow: 0 0 12px rgba(179, 255, 90, 0.5); }
    .status-dot.error { background: var(--danger); animation: none; }
    .stage { font-size: 14px; font-weight: 600; }
    .small { font-size: 11px; }
    .counters { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
    .counter {
      background: var(--bg-2);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 12px;
      text-align: center;
    }
    .counter-value {
      font-family: "JetBrains Mono", monospace;
      font-size: 22px;
      color: var(--accent);
    }
    .counter-label { font-size: 10px; text-transform: uppercase; color: var(--text-2); letter-spacing: 0.1em; }
    .log {
      flex: 1;
      overflow-y: auto;
      font-size: 11px;
      line-height: 1.6;
      color: var(--text-1);
      background: var(--bg-1);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 10px;
      max-height: 320px;
    }
    .log-line.embedded { color: var(--text-1); }
    .log-line.cluster_formed { color: var(--magenta); }
    .log-line.node_summarized { color: var(--accent); }
    .log-line.layer_complete { color: var(--lime); }
    .log-line.error { color: var(--danger); }
    .explore-btn {
      display: block;
      text-align: center;
      padding: 12px;
      border-radius: var(--radius);
      background: linear-gradient(180deg, #00e5ff 0%, #0090aa 100%);
      color: #061417;
      font-weight: 600;
    }
    .error {
      color: var(--danger);
      background: rgba(255, 89, 112, 0.08);
      border: 1px solid rgba(255, 89, 112, 0.35);
      padding: 10px;
      border-radius: var(--radius);
    }
  `],
})
export class BuildComponent implements OnInit, OnDestroy {
  private api = inject(ApiService);
  private sse = inject(SseService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  buildId = signal('');
  status = signal<'pending' | 'running' | 'done' | 'error'>('pending');
  stage = signal<string | null>(null);
  errorMsg = signal<string | null>(null);
  chunkCount = signal(0);
  clusterCount = signal(0);
  layerProgress = signal('0/0');
  nodes = signal<TVNode[]>([]);
  edges = signal<TVEdge[]>([]);
  log = signal<{ stage: string; text: string }[]>([]);

  private sub?: Subscription;

  ngOnInit() {
    const id = this.route.snapshot.paramMap.get('id') ?? '';
    this.buildId.set(id);
    if (!id) return this.router.navigate(['/']) as any;
    this.sub = this.sse.connect(this.api.streamUrl(id)).subscribe({
      next: (e) => this.handle(e),
      error: (err) => {
        this.status.set('error');
        this.errorMsg.set(String(err));
      },
    });
  }

  ngOnDestroy() { this.sub?.unsubscribe(); }

  private handle(e: BuildEvent) {
    this.stage.set(e.stage);
    const append = (text: string) => this.log.update((v) => [...v.slice(-200), { stage: e.stage, text }]);

    switch (e.stage) {
      case 'chunked': {
        const chunks: { id: number; preview: string }[] = e.payload.chunks;
        this.chunkCount.set(chunks.length);
        // pre-create leaf placeholders so the user sees structure forming
        const newNodes: TVNode[] = chunks.map((c) => ({
          id: c.id, layer: 0, text: c.preview, children: [], pending: true,
        }));
        this.nodes.set(newNodes);
        append(`chunked into ${chunks.length}`);
        break;
      }
      case 'embedded': {
        const id: number = e.payload.node_id;
        this.nodes.update((arr) => arr.map((n) => n.id === id ? { ...n, pending: false, text: e.payload.preview } : n));
        append(`embed #${id}`);
        break;
      }
      case 'cluster_formed': {
        this.clusterCount.update((v) => v + 1);
        // Transient magenta edges from each child up to "?" — drawn after the summary lands.
        // To avoid orphans, we just log here and let node_summarized add the real edges.
        append(`cluster L${e.layer} ← {${e.payload.child_ids.join(',')}}`);
        break;
      }
      case 'node_summarized': {
        const newNode: TVNode = {
          id: e.payload.node_id,
          layer: e.layer,
          text: e.payload.preview,
          children: e.payload.children,
        };
        this.nodes.update((arr) => [...arr, newNode]);
        const newEdges: TVEdge[] = e.payload.children.map((c: number) => ({ parent: newNode.id, child: c }));
        this.edges.update((es) => [...es, ...newEdges]);
        append(`summary #${newNode.id} (L${e.layer})`);
        break;
      }
      case 'layer_complete': {
        this.layerProgress.set(`L${e.layer} · ${e.payload.node_count}`);
        append(`layer ${e.layer} complete (${e.payload.node_count})`);
        break;
      }
      case 'done': {
        this.status.set('done');
        append('done');
        break;
      }
      case 'error': {
        this.status.set('error');
        this.errorMsg.set(e.payload.message);
        append(`error: ${e.payload.message}`);
        break;
      }
    }
    return;
  }
}
