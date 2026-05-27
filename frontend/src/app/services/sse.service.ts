import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

export type BuildStage =
  | 'chunked'
  | 'embedded'
  | 'cluster_formed'
  | 'node_summarized'
  | 'layer_complete'
  | 'done'
  | 'error';

export interface BuildEvent {
  stage: BuildStage;
  layer: number;
  payload: any;
}

@Injectable({ providedIn: 'root' })
export class SseService {
  connect(url: string): Observable<BuildEvent> {
    return new Observable<BuildEvent>((subscriber) => {
      const source = new EventSource(url);
      const stages: BuildStage[] = [
        'chunked',
        'embedded',
        'cluster_formed',
        'node_summarized',
        'layer_complete',
        'done',
        'error',
      ];
      const onStage = (ev: Event) => {
        // EventSource's native 'error' event fires alongside our custom 'error'
        // stage — only the latter is a MessageEvent carrying data.
        if (!(ev instanceof MessageEvent)) return;
        const data = ev.data;
        if (data == null || data === '' || data === 'undefined') return;
        try {
          subscriber.next(JSON.parse(data) as BuildEvent);
        } catch (err) {
          console.warn('[sse] failed to parse', ev.type, JSON.stringify(data).slice(0, 200), err);
        }
      };
      stages.forEach((s) => source.addEventListener(s, onStage as EventListener));
      source.onerror = () => {
        // EventSource auto-reconnects; surface a single failure if we get one.
        if (source.readyState === EventSource.CLOSED) subscriber.complete();
      };
      return () => {
        stages.forEach((s) => source.removeEventListener(s, onStage as EventListener));
        source.close();
      };
    });
  }
}
