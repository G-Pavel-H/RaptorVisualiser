import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

// In `ng serve` dev mode → call the local FastAPI on :8000.
// In production (Vercel) → call the deployed Render backend.
// Override either by setting `window.RAPTOR_API_BASE` in index.html.
const PROD_API = 'https://raptorvisualiser.onrender.com';
const isLocalDev =
  typeof window !== 'undefined' && window.location.hostname === 'localhost';
const API_BASE =
  (window as any).RAPTOR_API_BASE ??
  (isLocalDev ? 'http://localhost:8000' : PROD_API);

export interface SerializedNode {
  id: number;
  layer: number;
  text: string;
  children: number[];
}
export interface SerializedTree {
  num_layers: number;
  root_ids: number[];
  leaf_ids: number[];
  nodes: SerializedNode[];
  edges: { parent: number; child: number }[];
}
export type ErrorKind = 'generic' | 'out_of_funds' | 'site_cap' | 'ip_cap' | 'too_large' | 'mongo_down';

export interface BuildStatus {
  build_id: string;
  status: 'pending' | 'running' | 'done' | 'error';
  tree: SerializedTree | null;
  error: string | null;
  error_kind: ErrorKind | null;
}
export interface CreateBuildResponse {
  build_id: string;
}
export interface ApiErrorDetail {
  kind: ErrorKind;
  message: string;
  used_usd?: number;
  cap_usd?: number;
  resets_at?: string;
}
export interface QueryResponse {
  method: string;
  context: string;
  retrieved_node_ids: number[];
  layer_information: any;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);

  createBuild(text: string): Observable<CreateBuildResponse> {
    return this.http.post<CreateBuildResponse>(`${API_BASE}/api/builds`, { text });
  }

  getBuild(buildId: string): Observable<BuildStatus> {
    return this.http.get<BuildStatus>(`${API_BASE}/api/builds/${buildId}`);
  }

  query(buildId: string, query: string, method: 'collapsed_tree' | 'tree_traversal'): Observable<QueryResponse> {
    return this.http.post<QueryResponse>(`${API_BASE}/api/builds/${buildId}/query`, { query, method });
  }

  streamUrl(buildId: string): string {
    return `${API_BASE}/api/builds/${buildId}/stream`;
  }
}
