import { Component } from '@angular/core';
import { RouterOutlet, RouterLink } from '@angular/router';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink],
  template: `
    <header class="topbar">
      <a routerLink="/" class="brand">
        <span class="logo-dot"></span>
        <span class="brand-text">RAPTOR<span class="brand-accent">.live</span></span>
      </a>
      <span class="muted mono small">a tree-building visualizer for retrieval-augmented research</span>
    </header>
    <main><router-outlet /></main>
  `,
  styles: [`
    .topbar {
      display: flex;
      align-items: baseline;
      gap: 24px;
      padding: 18px 32px;
      border-bottom: 1px solid var(--border);
      backdrop-filter: blur(6px);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 700;
      font-size: 18px;
      color: var(--text-0);
    }
    .brand-text { letter-spacing: 0.04em; }
    .brand-accent { color: var(--accent); }
    .logo-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 12px var(--accent-glow);
    }
    .small { font-size: 12px; }
    main {
      min-height: calc(100vh - 60px);
    }
  `],
})
export class AppComponent {}
