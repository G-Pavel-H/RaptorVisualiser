import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { BuildEvent } from './sse.service';
import { SseService } from './sse.service';

// Minimal stand-in for the browser's EventSource so the SSE parsing/cleanup
// logic can be exercised headlessly in Node (jsdom provides MessageEvent).
class FakeEventSource {
  static lastInstance: FakeEventSource | null = null;
  static CLOSED = 2;
  url: string;
  readyState = 0;
  listeners: Record<string, EventListener[]> = {};
  onerror: ((ev: Event) => unknown) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.lastInstance = this;
  }
  addEventListener(type: string, l: EventListener) {
    (this.listeners[type] ||= []).push(l);
  }
  removeEventListener(type: string, l: EventListener) {
    this.listeners[type] = (this.listeners[type] ?? []).filter((x) => x !== l);
  }
  close() {
    this.readyState = 2;
  }
  dispatch(type: string, data: string) {
    const ev = new MessageEvent(type, { data });
    (this.listeners[type] ?? []).forEach((l) => l(ev));
  }
}

describe('SseService', () => {
  let originalES: unknown;

  beforeEach(() => {
    originalES = (globalThis as any).EventSource;
    (globalThis as any).EventSource = FakeEventSource;
  });
  afterEach(() => {
    (globalThis as any).EventSource = originalES;
  });

  it('connects to the given url', () => {
    new SseService().connect('/stream/abc').subscribe();
    expect(FakeEventSource.lastInstance!.url).toBe('/stream/abc');
  });

  it('emits parsed events for known stages, in order', async () => {
    const svc = new SseService();
    const received: BuildEvent[] = [];
    await new Promise<void>((resolve) => {
      const sub = svc.connect('/x').subscribe((ev) => {
        received.push(ev);
        if (received.length === 2) {
          sub.unsubscribe();
          resolve();
        }
      });
      const es = FakeEventSource.lastInstance!;
      es.dispatch('chunked', JSON.stringify({ stage: 'chunked', layer: 0, payload: {} }));
      es.dispatch('done', JSON.stringify({ stage: 'done', layer: 1, payload: { ok: true } }));
    });
    expect(received[0].stage).toBe('chunked');
    expect(received[1].stage).toBe('done');
    expect(received[1].layer).toBe(1);
    expect(received[1].payload).toEqual({ ok: true });
  });

  it('ignores empty / "undefined" data without emitting', () => {
    const svc = new SseService();
    const seen: BuildEvent[] = [];
    svc.connect('/x').subscribe((e) => seen.push(e));
    const es = FakeEventSource.lastInstance!;
    es.dispatch('chunked', '');
    es.dispatch('chunked', 'undefined');
    expect(seen).toHaveLength(0);
  });

  it('does not throw and does not emit on malformed JSON', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const svc = new SseService();
    const seen: BuildEvent[] = [];
    svc.connect('/x').subscribe((e) => seen.push(e));
    const es = FakeEventSource.lastInstance!;
    expect(() => es.dispatch('embedded', '{not valid json')).not.toThrow();
    expect(seen).toHaveLength(0);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it('removes listeners and closes the EventSource on unsubscribe', () => {
    const svc = new SseService();
    const seen: BuildEvent[] = [];
    const sub = svc.connect('/x').subscribe((e) => seen.push(e));
    const es = FakeEventSource.lastInstance!;
    sub.unsubscribe();
    expect(es.readyState).toBe(2);
    // events after teardown must not reach the (now unsubscribed) consumer
    es.dispatch('done', JSON.stringify({ stage: 'done', layer: 0, payload: {} }));
    expect(seen).toHaveLength(0);
  });

  it('completes the stream when the source closes with an error', () => {
    const svc = new SseService();
    let completed = false;
    svc.connect('/x').subscribe({ complete: () => (completed = true) });
    const es = FakeEventSource.lastInstance!;
    es.readyState = 2; // CLOSED
    es.onerror?.(new Event('error'));
    expect(completed).toBe(true);
  });
});
