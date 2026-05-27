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
}

@Component({
  selector: 'app-tree-view',
  standalone: true,
  template: `<div #host class="host"></div>`,
  styles: [`
    .host { width: 100%; height: 100%; overflow: hidden; position: relative; }
    :host { display: block; width: 100%; height: 100%; }
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
  private gNodes!: d3.Selection<SVGGElement, unknown, null, undefined>;
  private resizeObs?: ResizeObserver;

  ngAfterViewInit(): void {
    this.svg = d3
      .select(this.hostRef.nativeElement)
      .append('svg')
      .attr('width', '100%')
      .attr('height', '100%')
      .style('display', 'block');
    // soft cyan glow filter
    const defs = this.svg.append('defs');
    const filter = defs.append('filter').attr('id', 'glow').attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%');
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur');
    const merge = filter.append('feMerge');
    merge.append('feMergeNode').attr('in', 'coloredBlur');
    merge.append('feMergeNode').attr('in', 'SourceGraphic');

    this.gEdges = this.svg.append('g').attr('class', 'edges');
    this.gNodes = this.svg.append('g').attr('class', 'nodes');

    this.resizeObs = new ResizeObserver(() => this.render());
    this.resizeObs.observe(this.hostRef.nativeElement);
    this.render();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (this.svg) this.render();
  }

  ngOnDestroy(): void {
    this.resizeObs?.disconnect();
  }

  private render(): void {
    const host = this.hostRef.nativeElement;
    const w = host.clientWidth || 800;
    const h = host.clientHeight || 600;

    const layout = this.layout(w, h);
    const byId = new Map(layout.map((n) => [n.id, n] as const));

    // ----- edges -----
    const edgeKey = (e: TVEdge) => `${e.parent}->${e.child}`;
    const drawableEdges = this.edges.filter((e) => byId.has(e.parent) && byId.has(e.child));
    const edgeSel = this.gEdges
      .selectAll<SVGPathElement, TVEdge>('path.edge')
      .data(drawableEdges, edgeKey as any);

    edgeSel
      .enter()
      .append('path')
      .attr('class', 'edge')
      .attr('fill', 'none')
      .attr('stroke-opacity', 0)
      .attr('stroke-width', 1.2)
      .merge(edgeSel as any)
      .attr('stroke', (e) => (e.transient ? '#ff3df0' : '#283042'))
      .attr('stroke-dasharray', (e) => (e.transient ? '3 4' : null))
      .attr('d', (e) => {
        const p = byId.get(e.parent)!;
        const c = byId.get(e.child)!;
        const mid = (p.y + c.y) / 2;
        return `M${p.x},${p.y} C${p.x},${mid} ${c.x},${mid} ${c.x},${c.y}`;
      })
      .transition()
      .duration(450)
      .attr('stroke-opacity', (e) => (e.transient ? 0.8 : 0.45));

    edgeSel.exit().transition().duration(250).attr('stroke-opacity', 0).remove();

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
      .style('cursor', 'pointer')
      .on('click', (_e, d) => this.nodeClick.emit(d.id));

    ent.append('circle').attr('r', (d) => this.radius(d.data));
    ent
      .append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '0.32em')
      .style('font-family', '"JetBrains Mono", monospace')
      .style('font-size', '10px')
      .style('fill', '#07090d')
      .style('font-weight', '600')
      .style('pointer-events', 'none')
      .text((d) => `${d.data.layer}·${d.data.id}`);

    ent
      .transition()
      .duration(550)
      .ease(d3.easeBackOut.overshoot(1.4))
      .attr('transform', (d) => `translate(${d.x},${d.y}) scale(1)`)
      .style('opacity', 1);

    const merged = ent.merge(nodeSel as any);
    merged
      .transition()
      .duration(400)
      .attr('transform', (d) => `translate(${d.x},${d.y}) scale(1)`);
    merged
      .select('circle')
      .attr('r', (d) => this.radius(d.data))
      .attr('fill', (d) => this.fill(d.data, d.id === this.selectedId))
      .attr('stroke', (d) => this.stroke(d.data, d.id === this.selectedId))
      .attr('stroke-width', (d) => (d.data.retrieved || d.id === this.selectedId ? 2.5 : 1.2))
      .attr('filter', (d) => (d.data.retrieved || d.id === this.selectedId ? 'url(#glow)' : null));

    nodeSel.exit().transition().duration(250).style('opacity', 0).remove();
  }

  private layout(w: number, h: number): Laid[] {
    if (this.nodes.length === 0) return [];
    const padding = 60;
    const maxLayer = this.nodes.reduce((m, n) => Math.max(m, n.layer), 0);
    const byLayer = new Map<number, TVNode[]>();
    for (const n of this.nodes) {
      if (!byLayer.has(n.layer)) byLayer.set(n.layer, []);
      byLayer.get(n.layer)!.push(n);
    }
    for (const arr of byLayer.values()) arr.sort((a, b) => a.id - b.id);

    const out: Laid[] = [];
    const availH = h - padding * 2;
    for (let L = 0; L <= maxLayer; L++) {
      const arr = byLayer.get(L) ?? [];
      const y =
        maxLayer === 0
          ? h / 2
          : padding + availH - (availH * L) / Math.max(1, maxLayer);
      const stepX = (w - padding * 2) / Math.max(1, arr.length);
      arr.forEach((n, i) => {
        out.push({
          id: n.id,
          x: padding + stepX * (i + 0.5),
          y,
          data: n,
        });
      });
    }
    return out;
  }

  private radius(d: TVNode): number {
    if (d.pending) return 8;
    return d.layer === 0 ? 11 : 14 + Math.min(d.layer * 2, 8);
  }

  private fill(d: TVNode, selected: boolean): string {
    if (d.retrieved) return '#b3ff5a';
    if (selected) return '#00e5ff';
    if (d.pending) return '#1f2632';
    return d.layer === 0 ? '#3a4a64' : '#00b9d1';
  }

  private stroke(d: TVNode, selected: boolean): string {
    if (d.retrieved || selected) return '#ffffff';
    return d.pending ? '#ff3df0' : '#0d1117';
  }
}
