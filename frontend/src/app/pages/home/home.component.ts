import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiErrorDetail, ApiService, ErrorKind } from '../../services/api.service';

const SAMPLE = `Tigranes II, known as Tigranes the Great, ruled the Kingdom of Armenia from 95 to 55 BC and presided over the most expansive period in Armenian history. Born around 140 BC into the Artaxiad dynasty, he spent much of his youth as a hostage at the court of the Parthian Empire, a common diplomatic practice of the era. He secured his release and ascended the Armenian throne in 95 BC by ceding seventy valleys to Parthia, a price he would later reclaim many times over.

Tigranes quickly set about consolidating power. He allied with Mithridates VI of Pontus, sealing the partnership by marrying Mithridates' daughter Cleopatra.`;

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
        <div class="meta-links">
          <a class="meta-link" href="https://arxiv.org/html/2401.18059v1" target="_blank" rel="noopener">
            <span class="meta-icon">📄</span>
            <span>What is RAPTOR? <span class="dim">— read the paper</span></span>
          </a>
          <a class="meta-link" href="https://www.linkedin.com/in/pavel-ghazaryan/" target="_blank" rel="noopener">
            <span class="meta-icon">in</span>
            <span>Built by <span class="accent">Pavel Ghazaryan</span> <span class="dim">— say hi on LinkedIn</span></span>
          </a>
        </div>
      </section>

      <section class="panel input-card">
        <label class="label">Your text</label>
        <textarea
          [(ngModel)]="text"
          rows="12"
          spellcheck="false"
          placeholder="Paste an essay, an article, a transcript… (20,000 chars max)"
        ></textarea>

        <div class="meta">
          <span class="mono small">{{ text().length.toLocaleString() }} / {{ MAX.toLocaleString() }} chars</span>
          <button type="button" (click)="text.set(SAMPLE)" class="ghost">use sample</button>
        </div>

        @if (errorKind() === 'out_of_funds') {
          <div class="error funds">
            <div class="title">🪙 The AI piggy bank ran dry</div>
            <div class="body">
              The maintainer's been pinged to feed the meter — usually just a minute or two.
              Refresh in a bit.
            </div>
          </div>
        } @else if (errorKind() === 'site_cap') {
          <div class="error cap">
            <div class="title">🌙 Site-wide daily budget reached</div>
            <div class="body">
              The whole site has hit today's spend cap. Resets at midnight UTC.
            </div>
          </div>
        } @else if (errorKind() === 'ip_cap') {
          <div class="error cap">
            <div class="title">⏳ You've hit your personal daily limit</div>
            <div class="body">
              Each visitor gets a small slice of the daily budget so everyone can play.
              Your cap resets at midnight UTC.
            </div>
          </div>
        } @else if (errorKind() === 'mongo_down') {
          <div class="error">
            <div class="title">Service temporarily unavailable</div>
            <div class="body">The spend tracker is offline. Try again in a moment.</div>
          </div>
        } @else if (error()) {
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
    .hero p { font-size: 16px; line-height: 1.65; margin: 0 0 22px; max-width: 640px; }
    .meta-links { display: flex; flex-direction: column; gap: 8px; margin: 0 0 40px; }
    .meta-link {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: rgba(15, 19, 28, 0.5);
      color: var(--text-1);
      font-size: 13.5px;
      width: fit-content;
      transition: border-color 180ms var(--easing), color 180ms var(--easing), box-shadow 180ms var(--easing);
    }
    .meta-link:hover {
      border-color: var(--accent);
      color: var(--text-0);
      box-shadow: 0 0 14px rgba(0, 229, 255, 0.25);
    }
    .meta-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 22px;
      height: 22px;
      border-radius: 5px;
      background: var(--accent-soft);
      color: var(--accent);
      font-family: "JetBrains Mono", monospace;
      font-size: 11px;
      font-weight: 700;
    }
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
      margin-top: 14px;
      color: var(--danger);
      background: rgba(255, 89, 112, 0.08);
      border: 1px solid rgba(255, 89, 112, 0.35);
      border-radius: var(--radius);
      padding: 14px 16px;
    }
    .error .title {
      font-weight: 700;
      font-size: 15px;
      margin-bottom: 4px;
      color: var(--text-0);
    }
    .error .body {
      font-size: 13px;
      color: var(--text-1);
      line-height: 1.55;
    }
    .error.funds {
      background: linear-gradient(180deg, rgba(255, 213, 47, 0.10), rgba(255, 213, 47, 0.03));
      border-color: rgba(255, 213, 47, 0.5);
    }
    .error.funds .title { color: #ffd54f; }
    .error.cap {
      background: rgba(0, 229, 255, 0.06);
      border-color: rgba(0, 229, 255, 0.45);
    }
    .error.cap .title { color: var(--accent); }
  `],
})
export class HomeComponent {
  private api = inject(ApiService);
  private router = inject(Router);
  readonly MAX = 20000;
  readonly SAMPLE = SAMPLE;
  text = signal('');
  submitting = signal(false);
  error = signal<string | null>(null);
  errorKind = signal<ErrorKind | null>(null);

  canStart() {
    const len = this.text().length;
    return len > 30 && len <= this.MAX;
  }

  start() {
    this.error.set(null);
    this.errorKind.set(null);
    this.submitting.set(true);
    this.api.createBuild(this.text()).subscribe({
      next: (r) => this.router.navigate(['/builds', r.build_id]),
      error: (err) => {
        this.submitting.set(false);
        const detail: ApiErrorDetail | string | undefined = err?.error?.detail;
        if (detail && typeof detail === 'object') {
          this.errorKind.set(detail.kind);
          this.error.set(detail.message);
        } else {
          this.error.set(
            typeof detail === 'string' ? detail : 'Failed to start build',
          );
        }
      },
    });
  }
}
