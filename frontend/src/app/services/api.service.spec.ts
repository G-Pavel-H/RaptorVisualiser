import { describe, it, expect, vi, beforeEach } from 'vitest';
import { of } from 'rxjs';
import { ApiService } from './api.service';

// A hand-rolled HttpClient double — we only assert the URL + body ApiService
// builds, so the service can be constructed directly without Angular's DI.
function makeHttp() {
  return {
    post: vi.fn().mockReturnValue(of({})),
    get: vi.fn().mockReturnValue(of({})),
  };
}

// jsdom serves pages from http://localhost, so ApiService resolves its dev API base.
const BASE = 'http://localhost:8000';

describe('ApiService', () => {
  let http: ReturnType<typeof makeHttp>;
  let api: ApiService;

  beforeEach(() => {
    http = makeHttp();
    api = new ApiService(http as any);
  });

  it('createBuild POSTs the text to /api/builds', () => {
    api.createBuild('hello world');
    expect(http.post).toHaveBeenCalledWith(`${BASE}/api/builds`, { text: 'hello world' });
  });

  it('getBuild GETs /api/builds/:id', () => {
    api.getBuild('build-123');
    expect(http.get).toHaveBeenCalledWith(`${BASE}/api/builds/build-123`);
  });

  it('query POSTs the query + method to the build query endpoint', () => {
    api.query('b1', 'what is x?', 'collapsed_tree');
    expect(http.post).toHaveBeenCalledWith(`${BASE}/api/builds/b1/query`, {
      query: 'what is x?',
      method: 'collapsed_tree',
    });
  });

  it('streamUrl builds the SSE stream url for a build', () => {
    expect(api.streamUrl('xyz')).toBe(`${BASE}/api/builds/xyz/stream`);
  });

  it('maps distinct build ids to distinct stream urls', () => {
    expect(api.streamUrl('a')).not.toBe(api.streamUrl('b'));
  });
});
