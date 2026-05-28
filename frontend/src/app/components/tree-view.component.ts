import {
  AfterViewInit,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
  ViewChild,
} from '@angular/core';
import * as d3 from 'd3';

export interface TVNode {
  id: number;
  layer: number;
  text: string;
  children: number[];
  pending?: boolean;          // cluster_formed but not yet summarized
  retrieved?: boolean;        // highlight as retrieved by a query
}
export interface TVEdge {
  parent: number;
  child: number;
  transient?: boolean;        // shown during cluster_formed, before summary lands
}

interface Laid {
  id: number;
  x: number;
  y: number;
  data: TVNode;
  r: number;
}

@Component({
  selector: 'app-tree-view',
  standalone: true,
  template: `<div #host class="host"></div>`,
  styles: [`
    :host { display: block; width: 100%; height: 100%; }
    .host { width: 100%; height: 100%; overflow: hidden; position: relative; }

    :host ::ng-deep svg { display: block; }

    /* Pulse traveling along edges of the retrieval path */
    :host ::ng-deep path.edge-pulse {
      fill: none;
      stroke: #b3ff5a;
      stroke-width: 2.4px;
      stroke-linecap: round;
      stroke-dasharray: 8 16;
      filter: url(#glow-lime);
      animation: edge-pulse-flow 1.1s linear infinite;
      pointer-events: none;
    }
    @keyframes edge-pulse-flow {
      from { stroke-dashoffset: 0; }
      to   { stroke-dashoffset: -24; }
    }

    /* Subtle ambient pulse on the selected node */
    :host ::ng-deep g.node.is-selected > circle.halo {
      animation: halo-pulse 1.6s ease-in-out infinite;
    }
    :host ::ng-deep g.node.is-retrieved > circle.halo {
      animation: halo-pulse 1.1s ease-in-out infinite;
    }
    @keyframes halo-pulse {
      0%, 100% { opacity: 0.18; transform: scale(1); }
      50%      { opacity: 0.55; transform: scale(1.25); }
    }

    /* Hover lift */
    :host ::ng-deep g.node {
      transition: filter 200ms ease;
      cursor: pointer;
    }
    :host ::ng-deep g.node:hover > circle.main {
      filter: url(#glow);
    }
  `],
})
export class TreeViewComponent implements AfterViewInit, OnChanges, OnDestroy {
  @Input({ required: true }) nodes: TVNode[] = [];
  @Input({ required: true }) edges: TVEdge[] = [];
  @Input() selectedId: number | null = null;
  @Output() nodeClick = new EventEmitter<number>();

  @ViewChild('host', { static: true }) hostRef!: ElementRef<HTMLDivElement>;

  private svg!: d3.Selection<SVGSVGElement, unknown, null, undefined>;
  private gEdges!: d3.Selection<SVGGElement, unknown, null, undefined>;
  private gPulse!: d3.Selection<SVGGElement, unknown, null, undefined>;
  private gNodes!: d3.Selection<SVGGElement, unknown, null, undefined>;
  private tooltip!: d3.Selection<HTMLDivElement, unknown, null, undefined>;
  private resizeObs?: ResizeObserver;

  ngAfterViewInit(): void {
    this.svg = d3
      .select(this.hostRef.nativeElement)
      .append('svg')
      .attr('width', '100%')
      .attr('height', '100%');

    const defs = this.svg.append('defs');

    // Soft cyan glow for hover / selected
    const glow = defs
      .append('filter')
      .attr('id', 'glow')
      .attr('x', '-80%')
      .attr('y', '-80%')
      .attr('width', '260%')
      .attr('height', '260%');
    glow.append('feGaussianBlur').attr('stdDeviation', '4').attr('result', 'b');
    const m1 = glow.append('feMerge');
    m1.append('feMergeNode').attr('in', 'b');
    m1.append('feMergeNode').attr('in', 'SourceGraphic');

    // Lime glow for retrieved nodes + pulse trail
    const limeGlow = defs
      .append('filter')
      .attr('id', 'glow-lime')
      .attr('x', '-80%')
      .attr('y', '-80%')
      .attr('width', '260%')
      .attr('height', '260%');
    limeGlow.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'b');
    const m2 = limeGlow.append('feMerge');
    m2.append('feMergeNode').attr('in', 'b');
    m2.append('feMergeNode').attr('in', 'SourceGraphic');

    // Radial gradient for summary nodes (cyan) — kept saturated all the way out
    const gradCyan = defs
      .append('radialGradient')
      .attr('id', 'grad-cyan')
      .attr('cx', '50%').attr('cy', '38%').attr('r', '70%');
    gradCyan.append('stop').attr('offset', '0%').attr('stop-color', '#d0ffff');
    gradCyan.append('stop').attr('offset', '55%').attr('stop-color', '#22ecff');
    gradCyan.append('stop').attr('offset', '100%').attr('stop-color', '#00bcd9');

    // Gradient for leaf nodes (lifted slate → vivid blue)
    const gradLeaf = defs
      .append('radialGradient')
      .attr('id', 'grad-leaf')
      .attr('cx', '50%').attr('cy', '38%').attr('r', '70%');
    gradLeaf.append('stop').attr('offset', '0%').attr('stop-color', '#cfe0ff');
    gradLeaf.append('stop').attr('offset', '60%').attr('stop-color', '#7aa2ff');
    gradLeaf.append('stop').attr('offset', '100%').attr('stop-color', '#3d6bd6');

    // Gradient for retrieved nodes (lime) — bright outer too
    const gradLime = defs
      .append('radialGradient')
      .attr('id', 'grad-lime')
      .attr('cx', '50%').attr('cy', '38%').attr('r', '70%');
    gradLime.append('stop').attr('offset', '0%').attr('stop-color', '#f4ffd0');
    gradLime.append('stop').attr('offset', '55%').attr('stop-color', '#c6ff66');
    gradLime.append('stop').attr('offset', '100%').attr('stop-color', '#92db2c');

    this.gEdges = this.svg.append('g').attr('class', 'edges');
    this.gPulse = this.svg.append('g').attr('class', 'edge-pulses');
    this.gNodes = this.svg.append('g').attr('class', 'nodes');

    this.tooltip = d3
      .select(this.hostRef.nativeElement)
      .append('div')
      .attr('class', 'tv-tooltip')
      .style('position', 'absolute')
      .style('pointer-events', 'none')
      .style('opacity', '0')
      .style('max-width', '320px')
      .style('padding', '10px 12px')
      .style('font-family', '"JetBrains Mono", monospace')
      .style('font-size', '11.5px')
      .style('line-height', '1.55')
      .style('color', '#e7eaf3')
      .style('background', 'rgba(13, 17, 23, 0.95)')
      .style('border', '1px solid #00e5ff')
      .style('border-radius', '8px')
      .style('box-shadow', '0 0 18px rgba(0, 229, 255, 0.35)')
      .style('transition', 'opacity 140ms ease')
      .style('z-index', '20');

    this.resizeObs = new ResizeObserver(() => this.render());
    this.resizeObs.observe(this.hostRef.nativeElement);
    this.render();
  }

  ngOnChanges(_: SimpleChanges): void {
    if (this.svg) this.render();
  }

  ngOnDestroy(): void {
    this.resizeObs?.disconnect();
  }

  // ----------------------------------------------------------- render

  private render(): void {
    const host = this.hostRef.nativeElement;
    const w = host.clientWidth || 800;
    const h = host.clientHeight || 600;

    const layout = this.layout(w, h);
    const byId = new Map(layout.map((n) => [n.id, n] as const));

    // ----- baseline edges -----
    const edgeKey = (e: TVEdge) => `${e.parent}->${e.child}`;
    const drawable = this.edges.filter((e) => byId.has(e.parent) && byId.has(e.child));

    const edgeSel = this.gEdges
      .selectAll<SVGPathElement, TVEdge>('path.edge')
      .data(drawable, edgeKey as any);

    edgeSel
      .enter()
      .append('path')
      .attr('class', 'edge')
      .attr('fill', 'none')
      .attr('stroke-opacity', 0)
      .attr('stroke-width', 1.4)
      .merge(edgeSel as any)
      .attr('stroke', (e) => (e.transient ? '#ff3df0' : '#3a4763'))
      .attr('stroke-dasharray', (e) => (e.transient ? '3 4' : null as any))
      .attr('d', (e) => this.edgePath(byId.get(e.parent)!, byId.get(e.child)!))
      .transition()
      .duration(450)
      .attr('stroke-opacity', (e) => (e.transient ? 0.85 : 0.5));

    edgeSel.exit().transition().duration(250).attr('stroke-opacity', 0).remove();

    // ----- pulse overlay along retrieval-path edges -----
    const retrievedIds = new Set(this.nodes.filter((n) => n.retrieved).map((n) => n.id));
    const pulseEdges = drawable.filter(
      (e) => retrievedIds.has(e.parent) && retrievedIds.has(e.child),
    );
    const pulseSel = this.gPulse
      .selectAll<SVGPathElement, TVEdge>('path.edge-pulse')
      .data(pulseEdges, edgeKey as any);

    pulseSel
      .enter()
      .append('path')
      .attr('class', 'edge-pulse')
      .merge(pulseSel as any)
      .attr('d', (e) => this.edgePath(byId.get(e.parent)!, byId.get(e.child)!));

    pulseSel.exit().remove();

    // ----- nodes -----
    const nodeSel = this.gNodes
      .selectAll<SVGGElement, Laid>('g.node')
      .data(layout, (d: any) => d.id);

    const ent = nodeSel
      .enter()
      .append('g')
      .attr('class', 'node')
      .attr('transform', (d) => `translate(${d.x},${d.y}) scale(0.2)`)
      .style('opacity', 0)
      .on('click', (_e, d) => this.nodeClick.emit(d.id))
      .on('mouseenter', (event, d) => this.onHover(event as MouseEvent, d, true))
      .on('mouseleave', (event, d) => this.onHover(event as MouseEvent, d, false));

    // Soft halo (under main circle) — pulses for selected/retrieved nodes via CSS.
    ent
      .append('circle')
      .attr('class', 'halo')
      .attr('r', (d) => d.r * 1.6)
      .attr('fill', '#00e5ff')
      .attr('opacity', 0)
      .style('transform-origin', 'center')
      .style('transform-box', 'fill-box');

    // Main circle (gradient fill).
    ent.append('circle').attr('class', 'main').attr('r', (d) => d.r);

    // Label.
    ent
      .append('text')
      .attr('class', 'label')
      .attr('text-anchor', 'middle')
      .attr('dy', '0.34em')
      .style('font-family', '"JetBrains Mono", monospace')
      .style('font-weight', '800')
      .style('pointer-events', 'none')
      .style('letter-spacing', '0.02em');

    ent
      .transition()
      .duration(600)
      .ease(d3.easeBackOut.overshoot(1.6))
      .attr('transform', (d) => `translate(${d.x},${d.y}) scale(1)`)
      .style('opacity', 1);

    // ----- update existing + new -----
    const merged = ent.merge(nodeSel as any);

    merged
      .classed('is-selected', (d) => d.id === this.selectedId)
      .classed('is-retrieved', (d) => !!d.data.retrieved);

    merged
      .transition()
      .duration(420)
      .ease(d3.easeCubicOut)
      .attr('transform', (d) => `translate(${d.x},${d.y}) scale(1)`);

    merged
      .select<SVGCircleElement>('circle.halo')
      .transition().duration(300)
      .attr('r', (d) => d.r * 1.7)
      .attr('fill', (d) =>
        d.data.retrieved ? '#b3ff5a' : d.id === this.selectedId ? '#00e5ff' : '#00e5ff',
      )
      .attr('opacity', (d) =>
        d.data.retrieved ? 0.4 : d.id === this.selectedId ? 0.35 : 0,
      );

    merged
      .select<SVGCircleElement>('circle.main')
      .transition().duration(300)
      .attr('r', (d) => d.r)
      .attr('fill', (d) => this.fill(d.data, d.id === this.selectedId))
      .attr('stroke', (d) => this.stroke(d.data, d.id === this.selectedId))
      .attr('stroke-width', (d) =>
        d.data.retrieved || d.id === this.selectedId ? 2.5 : 1.4,
      )
      .attr('filter', (d) =>
        d.data.retrieved
          ? 'url(#glow-lime)'
          : d.id === this.selectedId
            ? 'url(#glow)'
            : null,
      );

    merged
      .select<SVGTextElement>('text.label')
      .style('font-size', (d) => `${Math.max(10, Math.min(d.r * 0.72, 18))}px`)
      .style('fill', (d) =>
        d.data.retrieved ? '#1a2900' : d.data.pending ? '#e7eaf3' : '#04141a',
      )
      .text((d) => this.labelFor(d));

    nodeSel
      .exit()
      .transition().duration(220)
      .style('opacity', 0)
      .attr('transform', function () {
        const t = d3.select(this).attr('transform') || '';
        return t.replace(/scale\([^)]*\)/, 'scale(0.4)');
      })
      .remove();
  }

  // ------------------------------------------------------ interactions

  private onHover(event: MouseEvent, d: Laid, entering: boolean): void {
    const g = d3.select<SVGGElement, Laid>(event.currentTarget as SVGGElement);
    g.raise();

    g.select<SVGCircleElement>('circle.main')
      .transition().duration(180)
      .ease(d3.easeCubicOut)
      .attr('r', d.r * (entering ? 1.22 : 1))
      .attr('stroke-width', entering ? 3 : (d.data.retrieved || d.id === this.selectedId ? 2.5 : 1.4));

    g.select<SVGCircleElement>('circle.halo')
      .transition().duration(180)
      .attr('opacity', () => {
        if (entering) return d.data.retrieved ? 0.55 : 0.35;
        return d.data.retrieved ? 0.4 : d.id === this.selectedId ? 0.35 : 0;
      });

    if (entering) {
      const host = this.hostRef.nativeElement.getBoundingClientRect();
      const x = event.clientX - host.left + 14;
      const y = event.clientY - host.top + 14;
      this.tooltip
        .html(
          `<div style="color:#00e5ff;font-size:10px;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:4px;">
             layer ${d.data.layer} · node ${d.data.id}${d.data.retrieved ? ' · retrieved' : ''}
           </div>
           <div>${escapeHtml(truncate(d.data.text, 220))}</div>`,
        )
        .style('left', `${x}px`)
        .style('top', `${y}px`)
        .style('opacity', '1');
    } else {
      this.tooltip.style('opacity', '0');
    }
  }

  // ----------------------------------------------------------- layout

  private layout(w: number, h: number): Laid[] {
    if (this.nodes.length === 0) return [];
    // Reserve room so the largest possible circle (cap=60) plus its halo (×1.7)
    // can't ever clip the container edge.
    const padding = 110;
    const maxLayer = this.nodes.reduce((m, n) => Math.max(m, n.layer), 0);

    const byLayer = new Map<number, TVNode[]>();
    for (const n of this.nodes) {
      if (!byLayer.has(n.layer)) byLayer.set(n.layer, []);
      byLayer.get(n.layer)!.push(n);
    }
    for (const arr of byLayer.values()) arr.sort((a, b) => a.id - b.id);

    // Adaptive radius: shrink as the graph grows, but stay readable.
    // Tightest packing per layer drives the cap; overall density gives a soft floor.
    const widestRow = Math.max(...Array.from(byLayer.values(), (a) => a.length));
    const rowsCount = maxLayer + 1;
    const cellW = (w - padding * 2) / Math.max(1, widestRow);
    const cellH = (h - padding * 2) / Math.max(1, rowsCount);
    const fromCell = Math.min(cellW, cellH) * 0.42;
    const densityFloor = Math.sqrt((w * h) / Math.max(1, this.nodes.length)) * 0.32;
    const baseR = clamp(Math.min(fromCell, densityFloor), 16, 56);

    const out: Laid[] = [];
    const availH = h - padding * 2;
    for (let L = 0; L <= maxLayer; L++) {
      const arr = byLayer.get(L) ?? [];
      const y =
        maxLayer === 0
          ? h / 2
          : padding + availH - (availH * L) / Math.max(1, maxLayer);
      const stepX = (w - padding * 2) / Math.max(1, arr.length);
      // Higher layers a touch larger to emphasize summarization.
      const layerBoost = 1 + Math.min(L * 0.08, 0.32);
      arr.forEach((n, i) => {
        const r = clamp(baseR * layerBoost, 14, 60);
        out.push({
          id: n.id,
          x: padding + stepX * (i + 0.5),
          y,
          data: n,
          r: n.pending ? r * 0.7 : r,
        });
      });
    }
    return out;
  }

  // ----------------------------------------------------------- styling

  private edgePath(p: Laid, c: Laid): string {
    const mid = (p.y + c.y) / 2;
    return `M${p.x},${p.y} C${p.x},${mid} ${c.x},${mid} ${c.x},${c.y}`;
  }

  private labelFor(d: Laid): string {
    // Show a short word from the node text when it fits; fall back to id.
    if (d.r >= 22) {
      const word = (d.data.text || '').trim().split(/\s+/)[0] ?? '';
      const trimmed = word.replace(/[^\w]/g, '').slice(0, Math.max(3, Math.floor(d.r / 4)));
      if (trimmed.length >= 3) return trimmed;
    }
    return `${d.data.layer}·${d.data.id}`;
  }

  private fill(d: TVNode, _selected: boolean): string {
    if (d.retrieved) return 'url(#grad-lime)';
    if (d.pending) return '#1f2632';
    return d.layer === 0 ? 'url(#grad-leaf)' : 'url(#grad-cyan)';
  }

  private stroke(d: TVNode, selected: boolean): string {
    if (d.retrieved) return '#eaffce';
    if (selected) return '#ffffff';
    return d.pending ? '#ff3df0' : 'rgba(255, 255, 255, 0.18)';
  }
}

// ---- small helpers ----

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function truncate(s: string, n: number): string {
  if (!s) return '';
  return s.length <= n ? s : s.slice(0, n - 1) + '…';
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
