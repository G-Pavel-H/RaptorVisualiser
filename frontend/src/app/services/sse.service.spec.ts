import { SseService } from './sse.service';

class FakeEventSource {
  static lastInstance: FakeEventSource | null = null;
  url: string;
  readyState = 0;
  listeners: Record<string, EventListener[]> = {};
  onerror: ((this: EventSource, ev: Event) => any) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.lastInstance = this;
  }
  addEventListener(type: string, listener: EventListener) {
    (this.listeners[type] ||= []).push(listener);
  }
  removeEventListener(type: string, listener: EventListener) {
    this.listeners[type] = (this.listeners[type] ?? []).filter((l) => l !== listener);
  }
  close() { this.readyState = 2; }
  dispatch(type: string, data: string) {
    const event = new MessageEvent(type, { data });
    (this.listeners[type] ?? []).forEach((l) => l(event));
  }
}

describe('SseService', () => {
  let originalES: any;

  beforeEach(() => {
    originalES = (window as any).EventSource;
    (window as any).EventSource = FakeEventSource;
    (FakeEventSource as any).CLOSED = 2;
  });
  afterEach(() => { (window as any).EventSource = originalES; });

  it('emits parsed events for known stages', (done) => {
    const svc = new SseService();
    const received: any[] = [];
    const sub = svc.connect('/x').subscribe((ev) => {
      received.push(ev);
      if (received.length === 2) {
        expect(received[0].stage).toBe('chunked');
        expect(received[1].stage).toBe('done');
        sub.unsubscribe();
        done();
      }
    });
    const es = FakeEventSource.lastInstance!;
    es.dispatch('chunked', JSON.stringify({ stage: 'chunked', layer: 0, payload: {} }));
    es.dispatch('done', JSON.stringify({ stage: 'done', layer: 0, payload: {} }));
  });

  it('closes the EventSource on unsubscribe', () => {
    const svc = new SseService();
    const sub = svc.connect('/x').subscribe();
    const es = FakeEventSource.lastInstance!;
    sub.unsubscribe();
    expect(es.readyState).toBe(2);
  });
});
