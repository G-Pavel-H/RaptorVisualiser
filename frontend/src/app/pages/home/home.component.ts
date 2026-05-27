import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../../services/api.service';

const SAMPLE = `The Apollo program was a series of human spaceflight missions undertaken by NASA between 1961 and 1972. Its goal was to land humans on the Moon and bring them safely back to Earth. Apollo 11, in July 1969, achieved that goal when Neil Armstrong and Buzz Aldrin walked on the lunar surface while Michael Collins orbited above. Five more crewed landings followed through Apollo 17. The program produced lasting advances in rocketry, computing, and materials science. It also returned 382 kilograms of lunar samples that continue to inform planetary geology today. Public interest waned after the initial landing, and budget pressure led to the cancellation of Apollos 18 through 20.`;

@Component({
  selector: 'app-home',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="layout">
      <section class="hero">
        <h1>Watch a RAPTOR tree<br /><span class="accent">build itself</span>, in real time.</h1>
        <p class="dim">
          Paste text. We chunk, embed, cluster, summarize — layer by layer — and stream every step
          to your browser. Click any node when it's done. Ask questions and see exactly which nodes
          get retrieved.
        </p>
      </section>

      <section class="panel input-card">
        <label class="label">Your text</label>
        <textarea
          [(ngModel)]="text"
          rows="12"
          spellcheck="false"
          placeholder="Paste an essay, an article, a transcript… (~40 KB max)"
        ></textarea>

        <div class="meta">
          <span class="mono small">{{ text().length }} chars · {{ MAX }} limit</span>
          <button type="button" (click)="text.set(SAMPLE)" class="ghost">use sample</button>
        </div>

        @if (error()) {
          <div class="error mono small">{{ error() }}</div>
        }

        <div class="actions">
          <button class="primary" (click)="start()" [disabled]="!canStart() || submitting()">
            {{ submitting() ? 'starting…' : 'build the tree →' }}
          </button>
        </div>
      </section>
    </div>
  `,
  styles: [`
    .layout {
      max-width: 880px;
      margin: 0 auto;
      padding: 56px 24px 80px;
    }
    .hero h1 {
      font-size: 44px;
      line-height: 1.1;
      margin: 0 0 16px;
      letter-spacing: -0.01em;
    }
    .accent {
      color: var(--accent);
      text-shadow: 0 0 24px var(--accent-glow);
    }
    .hero p { font-size: 16px; line-height: 1.65; margin: 0 0 40px; max-width: 640px; }
    .input-card { padding: 24px; }
    .label { display: block; font-size: 12px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-2); margin-bottom: 8px; }
    textarea {
      width: 100%;
      resize: vertical;
      font-family: "JetBrains Mono", monospace;
      font-size: 13px;
      line-height: 1.6;
    }
    .meta { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; }
    .small { font-size: 12px; }
    .ghost { background: transparent; border-color: var(--border); }
    .actions { margin-top: 20px; }
    .error {
      margin-top: 12px;
      color: var(--danger);
      background: rgba(255, 89, 112, 0.08);
      border: 1px solid rgba(255, 89, 112, 0.35);
      border-radius: var(--radius);
      padding: 10px 14px;
    }
  `],
})
export class HomeComponent {
  private api = inject(ApiService);
  private router = inject(Router);
  readonly MAX = 40000;
  readonly SAMPLE = SAMPLE;
  text = signal('');
  submitting = signal(false);
  error = signal<string | null>(null);

  canStart() {
    const len = this.text().length;
    return len > 30 && len <= this.MAX;
  }

  start() {
    this.error.set(null);
    this.submitting.set(true);
    this.api.createBuild(this.text()).subscribe({
      next: (r) => this.router.navigate(['/builds', r.build_id]),
      error: (err) => {
        this.submitting.set(false);
        this.error.set(err?.error?.detail?.message ?? err?.error?.detail ?? 'Failed to start build');
      },
    });
  }
}
