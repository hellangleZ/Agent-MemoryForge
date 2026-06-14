// API Client for Agent-MemoryForge Portal
// 继承Python portal的所有API功能

// Prefer same-origin relative requests (Next rewrites proxy to the gateway).
const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '';
let refreshInFlight: Promise<boolean> | null = null;

// Token management
function getCookie(name: string): string {
  if (typeof document === 'undefined') return '';
  const target = `${encodeURIComponent(name)}=`;
  const parts = (document.cookie || '').split(';');
  for (const part of parts) {
    const trimmed = part.trim();
    if (trimmed.startsWith(target)) {
      return decodeURIComponent(trimmed.slice(target.length));
    }
  }
  return '';
}

export function getToken(): string {
  if (typeof window !== 'undefined') {
    // Deprecated: we avoid storing bearer tokens in the browser.
    // Kept for backwards-compat with a few call sites.
    return localStorage.getItem('portal_access_token') || getCookie('portal_access_token') || '';
  }
  return '';
}

export function setToken(token: string): void {
  if (typeof window !== 'undefined') {
    // Store only an auth marker; actual auth is via httponly cookies.
    localStorage.setItem('portal_auth', token ? '1' : '');
  }
}

export function hasToken(): boolean {
  if (typeof window === 'undefined') return false;
  return (localStorage.getItem('portal_auth') || '').trim() === '1';
}

export function clearToken(): void {
  if (typeof window !== 'undefined') {
    localStorage.removeItem('portal_access_token');
    localStorage.removeItem('portal_auth');
  }
}

export function apiErrorStatus(error: unknown): number | null {
  if (!(error instanceof Error)) return null;
  try {
    const parsed = JSON.parse(error.message) as { status?: number };
    return typeof parsed.status === 'number' ? parsed.status : null;
  } catch {
    return null;
  }
}

export function isAuthError(error: unknown): boolean {
  const status = apiErrorStatus(error);
  return status === 401;
}

// Workspace management
export function getWorkspace(): string {
  if (typeof window !== 'undefined') {
    return localStorage.getItem('portal_workspace_id') || 'ws_default';
  }
  return 'ws_default';
}

export function setWorkspace(workspaceId: string): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem('portal_workspace_id', workspaceId || '');
  }
}

// Headers helper
function getHeaders(extraHeaders: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...extraHeaders,
  };

  const workspaceId = getWorkspace();
  if (workspaceId) {
    headers['x-workspace-id'] = workspaceId;
  }
  
  return headers;
}

async function parseResponseBody<T>(response: Response): Promise<T | { raw: string }> {
  const text = await response.text();
  try {
    return JSON.parse(text) as T;
  } catch {
    return { raw: text };
  }
}

function canRefresh(endpoint: string, response: Response): boolean {
  if (response.status !== 401) return false;
  return !endpoint.includes('/portal/v1/login')
    && !endpoint.includes('/portal/v1/logout')
    && !endpoint.includes('/portal/v1/token/refresh');
}

async function refreshSessionFromCookie(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const response = await fetch(`${API_BASE}/portal/v1/token/refresh`, {
        method: 'POST',
        credentials: 'include',
      });
      if (!response.ok) {
        clearToken();
        return false;
      }
      setToken('1');
      return true;
    })().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

export async function authenticatedFetch(
  endpoint: string,
  init: RequestInit = {},
  extraHeaders: Record<string, string> = {},
  retryOnAuth = true
): Promise<Response> {
  const headers = new Headers(getHeaders(extraHeaders));
  if (init.headers) {
    new Headers(init.headers).forEach((value, key) => headers.set(key, value));
  }
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...init,
    headers,
    credentials: 'include',
  });
  if (retryOnAuth && canRefresh(endpoint, response)) {
    const refreshed = await refreshSessionFromCookie();
    if (refreshed) {
      return authenticatedFetch(endpoint, init, extraHeaders, false);
    }
  }
  return response;
}

async function requestJson<T>(
  method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
  endpoint: string,
  body?: Record<string, unknown>,
  extraHeaders: Record<string, string> = {}
): Promise<T> {
  const response = await authenticatedFetch(endpoint, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  }, extraHeaders);
  const json = await parseResponseBody<T>(response);
  if (!response.ok) {
    throw new Error(JSON.stringify({ status: response.status, body: json }));
  }
  return json as T;
}

// Generic API calls
export async function postJson<T>(
  endpoint: string,
  body: Record<string, unknown> = {},
  extraHeaders: Record<string, string> = {}
): Promise<T> {
  return requestJson<T>('POST', endpoint, body, extraHeaders);
}

export async function patchJson<T>(
  endpoint: string,
  body: Record<string, unknown> = {},
  extraHeaders: Record<string, string> = {}
): Promise<T> {
  return requestJson<T>('PATCH', endpoint, body, extraHeaders);
}

// Tool Policy Types and APIs
export interface ToolPolicy {
  allowlist: string[];
  denylist: string[];
  overrides: Record<string, boolean>;
}

export async function getToolsPolicy() {
  return getJson<{ data: ToolPolicy }>('/portal/v1/tools/policy');
}

export async function updateToolsPolicy(policy: ToolPolicy) {
  return postJson('/portal/v1/tools/policy', policy as unknown as Record<string, unknown>);
}

export async function getJson<T>(
  endpoint: string,
  extraHeaders: Record<string, string> = {}
): Promise<T> {
  return requestJson<T>('GET', endpoint, undefined, extraHeaders);
}

export async function deleteJson<T>(
  endpoint: string,
  extraHeaders: Record<string, string> = {}
): Promise<T> {
  return requestJson<T>('DELETE', endpoint, undefined, extraHeaders);
}

// Auth APIs
interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export async function login(username: string, password: string) {
  const result = await postJson<TokenResponse>('/portal/v1/login', {
    username,
    password,
  });
  // Mark session as authenticated; cookie is set by the backend.
  if (result.access_token) setToken('1');
  return result;
}

export async function adminLogin(username: string, password: string) {
  const result = await postJson<TokenResponse>('/portal/v1/login', {
    username,
    password,
  }, { 'X-Admin-Mode': 'true' });
  if (result.access_token) setToken('1');
  return result;
}

export async function refreshToken(refreshToken: string) {
  const result = await requestJson<TokenResponse>(
    'POST',
    '/portal/v1/token/refresh',
    { refresh_token: refreshToken }
  );
  if (result.access_token) setToken('1');
  return result;
}

export async function logout(refreshToken?: string) {
  const res = await postJson('/portal/v1/logout', refreshToken ? { refresh_token: refreshToken } : {});
  clearToken();
  return res;
}

export async function changePassword(currentPassword: string, newPassword: string) {
  return postJson('/portal/v1/password/change', {
    current_password: currentPassword,
    new_password: newPassword,
  });
}

export async function getMe() {
  return getJson<{ id: string; email: string; role: string; created_at: string }>('/portal/v1/me');
}

export async function signup(username: string, password: string) {
  return postJson('/portal/v1/signup', { username, password });
}

// Workspace APIs
export async function getWorkspaceConfig() {
  return getJson<{ data: WorkspaceConfig }>('/portal/v1/workspace/config');
}

export async function saveWorkspaceConfig(config: Partial<WorkspaceConfig>) {
  return postJson('/portal/v1/workspace/config', config);
}

export async function applyWorkspaceConfig() {
  return postJson('/portal/v1/workspace/apply', {});
}

export interface WorkspaceSecretsStatus {
  tenant_id?: string;
  workspace_id?: string;
  configured: Record<string, boolean>;
  names: string[];
}

export async function getWorkspaceSecrets() {
  return getJson<{ data: WorkspaceSecretsStatus }>('/portal/v1/workspace/secrets');
}

export async function saveWorkspaceSecrets(payload: {
  values?: Record<string, string>;
  clear?: string[];
}) {
  return postJson<{ data: WorkspaceSecretsStatus }>('/portal/v1/workspace/secrets', {
    values: payload.values || {},
    clear: payload.clear || [],
  });
}

// Chat APIs
export async function sendChatMessage(body: ChatRequest): Promise<Response> {
  const response = await authenticatedFetch('/v1/chat/stream', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  
  if (!response.ok) {
    const text = await response.text();
    let json: { error?: string; detail?: string };
    try {
      json = JSON.parse(text);
    } catch {
      json = { error: text };
    }
    throw new Error(json.error || json.detail || 'Chat request failed');
  }
  
  return response;
}

// File-first memory APIs (proxied via gateway)
export async function memorySearch(params: {
  query: string;
  top_k?: number;
  tiers?: string[];
  scopes?: string[];
  memory_url?: string;
}) {
  return postJson<{ status: string; data: { hits: unknown[] } }>('/v1/memory/search', {
    query: params.query,
    top_k: params.top_k ?? 20,
    tiers: params.tiers,
    scopes: params.scopes,
    memory_url: params.memory_url,
  });
}

export async function memoryGet(params: {
  path: string;
  start_line?: number;
  max_lines?: number;
  memory_url?: string;
}) {
  return postJson<{ status: string; data: { path: string; content: string } }>('/v1/memory/get', {
    path: params.path,
    start_line: params.start_line,
    max_lines: params.max_lines,
    memory_url: params.memory_url,
  });
}

// Memory APIs
export async function getMemory(type: string, params: Record<string, unknown>) {
  return postJson('/v1/memory/retrieve', { memory_type: type, params });
}

export async function getMemoryStats() {
  return postJson<{ data: MemoryStats }>('/portal/v1/memory/stats', {});
}

export async function rebuildMemoryIndex(params?: { memory_url?: string }) {
  return postJson<{ status: string; data?: unknown }>('/portal/v1/memory/index/rebuild', {
    memory_url: params?.memory_url,
  });
}

export async function storeMemory(type: string, params: Record<string, unknown>) {
  return postJson('/v1/memory/store', { memory_type: type, params });
}

// Tool & Agent Discovery
export async function getTools(options?: { refresh?: boolean }) {
  const suffix = options?.refresh ? '?refresh=1' : '';
  return getJson<{
    data: Record<string, Tool[]>;
    tools_by_namespace?: Record<string, Tool[]>;
    warning?: string | null;
    discovery?: {
      cached: boolean;
      updated_at?: string | null;
      stale: boolean;
      refresh_required: boolean;
    };
  }>(`/portal/v1/tools${suffix}`);
}

export async function getToolsStatus() {
  return getJson<ToolsStatusResponse>('/portal/v1/tools/status');
}

export async function getAgents() {
  return getJson<{ agents: Record<string, Agent> }>('/portal/v1/agents');
}

export async function createAgent(agent: {
  id: string;
  name?: string;
  description?: string;
  system_prompt?: string;
  tools?: string[];
  workspace_id?: string;
}) {
  return postJson('/portal/v1/agents', agent);
}

export async function deleteAgent(agentId: string) {
  return deleteJson(`/portal/v1/agents/${agentId}`);
}

// ============ Admin Workspace Management APIs ============

// GET /portal/v1/workspaces - 列出所有工作区
export async function getWorkspaces(): Promise<WorkspacesResponse> {
  return getJson<WorkspacesResponse>('/portal/v1/workspaces', getHeaders());
}

// GET /portal/v1/workspaces/{id} - 获取工作区详情
export async function getWorkspaceById(workspaceId: string): Promise<WorkspaceDetail> {
  return getJson<WorkspaceDetail>(`/portal/v1/workspaces/${workspaceId}`, getHeaders());
}

// DELETE /portal/v1/workspaces/{id} - 删除工作区
export async function deleteWorkspace(workspaceId: string): Promise<{ success: boolean }> {
  return deleteJson<{ success: boolean }>(`/portal/v1/workspaces/${workspaceId}`, getHeaders());
}

export async function getWorkspaceMembers(workspaceId: string): Promise<{ members: WorkspaceMember[] }> {
  return getJson<{ members: WorkspaceMember[] }>(`/portal/v1/workspaces/${workspaceId}/members`, getHeaders());
}

export async function addWorkspaceMember(workspaceId: string, member: { user_id: string; role: string }) {
  return postJson(`/portal/v1/workspaces/${workspaceId}/members`, member);
}

export async function deleteWorkspaceMember(workspaceId: string, userId: string) {
  return deleteJson(`/portal/v1/workspaces/${workspaceId}/members/${userId}`, getHeaders());
}

// ============ Admin Runs APIs ============

// GET /v1/runs - 列出所有运行记录
export async function getRuns(params?: {
  page?: number;
  limit?: number;
  agent?: string;
  status?: string;
}): Promise<RunsResponse> {
  const query = params ? '?' + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString() : '';
  return getJson<RunsResponse>(`/v1/runs${query}`, getHeaders());
}

// GET /v1/runs/{trace_id} - 获取运行详情
export async function getRunByTraceId(traceId: string): Promise<RunDetail> {
  return getJson<RunDetail>(`/v1/runs/${traceId}`, getHeaders());
}

// ============ Admin User Management APIs ============

// GET /portal/v1/admin/users - 列出所有用户
export async function getAdminUsers(): Promise<AdminUsersResponse> {
  return getJson<AdminUsersResponse>('/portal/v1/admin/users', getHeaders());
}

export async function createAdminUser(payload: {
  username: string;
  password: string;
  role: 'admin' | 'user';
  tenant_id?: string;
}): Promise<AdminUserCreateResponse> {
  return postJson<AdminUserCreateResponse>('/portal/v1/admin/users', payload);
}

export async function updateAdminUser(username: string, payload: {
  role?: 'admin' | 'user';
  tenant_id?: string;
}): Promise<AdminUserUpdateResponse> {
  return patchJson<AdminUserUpdateResponse>(`/portal/v1/admin/users/${encodeURIComponent(username)}`, payload);
}

export async function resetAdminUserPassword(username: string, payload: {
  new_password: string;
}): Promise<AdminUserPasswordResetResponse> {
  return postJson<AdminUserPasswordResetResponse>(`/portal/v1/admin/users/${encodeURIComponent(username)}/password`, payload);
}

export async function deleteAdminUser(username: string): Promise<AdminUserDeleteResponse> {
  return deleteJson<AdminUserDeleteResponse>(`/portal/v1/admin/users/${encodeURIComponent(username)}`, getHeaders());
}

export async function getAdminUsage(params?: {
  tenant_id?: string;
  workspace_id?: string;
  user_id?: string;
  month?: string;
}): Promise<AdminUsageResponse> {
  const query = new URLSearchParams();
  if (params?.tenant_id) query.set('tenant_id', params.tenant_id);
  if (params?.workspace_id) query.set('workspace_id', params.workspace_id);
  if (params?.user_id) query.set('user_id', params.user_id);
  if (params?.month) query.set('month', params.month);
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return getJson<AdminUsageResponse>(`/portal/v1/admin/usage${suffix}`, getHeaders());
}

export async function getAdminQuotas(params?: {
  tenant_id?: string;
  workspace_id?: string;
  user_id?: string;
}): Promise<AdminQuotaListResponse> {
  const query = new URLSearchParams();
  if (params?.tenant_id) query.set('tenant_id', params.tenant_id);
  if (params?.workspace_id) query.set('workspace_id', params.workspace_id);
  if (params?.user_id) query.set('user_id', params.user_id);
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return getJson<AdminQuotaListResponse>(`/portal/v1/admin/quotas${suffix}`, getHeaders());
}

export async function setAdminQuota(payload: {
  tenant_id?: string;
  workspace_id: string;
  user_id: string;
  monthly_token_quota: number;
  enabled: boolean;
}): Promise<AdminQuotaSetResponse> {
  return postJson<AdminQuotaSetResponse>('/portal/v1/admin/quotas', payload);
}

// Monitoring APIs
export async function getMonitoringMetrics(
  metricType: 'cpu' | 'memory' | 'storage',
  timeRange: '1h' | '24h' | '7d'
) {
  return getJson<MonitoringMetricsResponse>(`/portal/v1/monitoring/metrics?metric_type=${metricType}&time_range=${timeRange}`);
}

export async function getMonitoringAudit(page: number = 1, limit: number = 50, action?: string, userId?: string) {
  const params = new URLSearchParams({
    page: page.toString(),
    limit: limit.toString(),
  });
  if (action) params.set('action', action);
  if (userId) params.set('user_id', userId);
  return getJson<MonitoringAuditResponse>(`/portal/v1/monitoring/audit?${params.toString()}`);
}

export async function exportMonitoringMetrics(metricType: 'cpu' | 'memory' | 'storage', timeRange: '1h' | '24h' | '7d') {
  const params = new URLSearchParams({
    metric_type: metricType,
    time_range: timeRange,
  });
  const response = await authenticatedFetch(`/portal/v1/monitoring/metrics/export?${params.toString()}`, {
    method: 'GET',
  });
  if (!response.ok) {
    throw new Error(`Export failed: ${response.status}`);
  }
  return response.text();
}

export async function exportMonitoringAudit(action?: string, userId?: string) {
  const params = new URLSearchParams();
  if (action) params.set('action', action);
  if (userId) params.set('user_id', userId);
  const response = await authenticatedFetch(`/portal/v1/monitoring/audit/export?${params.toString()}`, {
    method: 'GET',
  });
  if (!response.ok) {
    throw new Error(`Export failed: ${response.status}`);
  }
  return response.text();
}

// Types
export interface WorkspaceConfig {
  tenant_id?: string;
  workspace_id?: string;
  system_prompt?: string;
  mcp_secrets?: Record<string, boolean>;
  mcp?: {
    mcp_stdio_json?: string;
    mcp_servers_json?: string;
    mcp_http_url?: string;
    mcp_http_namespace?: string;
    mcp_http_headers_json?: string;
  };
}

export interface ChatRequest {
  agent: string;
  user_id: string;
  conversation_id?: string;
  messages: Array<{ role: string; content: string }>;
}

export interface ChatResponse {
  // Stream response handling is done separately
  status?: string | number;
  [key: string]: unknown;
}

export interface Tool {
  name: string;
  category?: string;
  spec?: string;
  schema?: {
    description?: string;
    parameters?: Record<string, unknown>;
  };
}

export interface Agent {
  // Agent metadata
}

export interface ApiResponse {
  status: string | number;
  [key: string]: unknown;
}

// Tool Status Types
export interface ToolStatus {
  name: string;
  enabled: boolean;
  status: string;
  config: Record<string, unknown>;
}

export interface ToolsStatusResponse {
  status?: string;
  data?: {
    workspace_configured?: boolean;
    workspace_saved?: boolean;
    workspace_applied?: boolean;
    env_configured?: boolean;
    configured?: boolean;
    workspace_secrets_configured?: boolean;
    workspace_secrets?: Record<string, boolean>;
    policy?: ToolPolicy;
    tool_inventory_cached?: boolean;
    tool_inventory_updated_at?: string | null;
    tool_inventory_stale?: boolean;
    tool_inventory_refresh_required?: boolean;
  };
  tools: ToolStatus[];
}

// Monitoring Types
export interface MonitoringMetric {
  timestamp: string;
  value: number;
  unit: string;
}

export interface MonitoringMetricsResponse {
  metrics: MonitoringMetric[];
  total?: number;
}

export interface AuditEntry {
  id: string;
  user_id: string;
  action: string;
  resource: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
}

export interface MonitoringAuditResponse {
  audits: AuditEntry[];
  total: number;
}

// Memory Types
export interface MemorySearchResult {
  id: string;
  memory_type: string;
  content: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  created_at?: string;
  score?: number;
}

export interface MemoryStats {
  stm: { count: number; size_bytes: number };
  wm: { count: number; size_bytes: number };
  ltm: { count: number; size_bytes: number };
  knowledge_graph: { nodes: number; edges: number; size_bytes: number };
  file_first?: {
    index?: {
      mtime_s?: number;
      stale?: boolean;
    };
  };
}

// ============ Admin Workspace Types ============

export interface Workspace {
  id: string;
  name: string;
  owner: string;
  created_at: string;
  status: string;
}

export interface WorkspacesResponse {
  workspaces: Workspace[];
  total: number;
}

export interface WorkspaceDetail extends Workspace {
  config: Record<string, unknown>;
  agents: string[];
}

export interface WorkspaceMember {
  user_id: string;
  role: string;
  added_at?: string;
  updated_at?: string;
}

// ============ Admin Runs Types ============

export interface RunRecord {
  id: string;
  trace_id: string;
  agent: string;
  status: string;
  created_at: string;
  duration_ms: number;
}

export interface RunsResponse {
  runs: RunRecord[];
  total: number;
}

export interface RunDetail {
  trace: {
    id: string;
    trace_id: string;
    spans: Record<string, unknown>[];
    events: Record<string, unknown>[];
    metadata: Record<string, unknown>;
  };
}

// ============ Admin User Types ============

export interface AdminUser {
  id: string;
  email: string;
  role: string;
  created_at: string;
  last_login?: string | null;
  tenant_id?: string | null;
}

export interface AdminUsersResponse {
  users: AdminUser[];
  total: number;
}

export interface AdminUserCreateResponse {
  status: string;
  data: AdminUser;
}

export interface AdminUserUpdateResponse {
  status: string;
  data: AdminUser;
}

export interface AdminUserPasswordResetResponse {
  status: string;
  data: {
    id: string;
    revoked_refresh_tokens: number;
  };
}

export interface AdminUserDeleteResponse {
  status: string;
  data: {
    id: string;
    tenant_id: string;
    removed_quotas: number;
    removed_members: number;
  };
}

export interface AdminUsageItem {
  tenant_id: string;
  workspace_id: string;
  user_id: string;
  month: string;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  monthly_token_quota: number | null;
  quota_enabled: boolean;
  remaining_tokens: number | null;
  blocked: boolean;
  updated_at?: number | null;
}

export interface AdminUsageResponse {
  status: string;
  data: {
    tenant_id: string;
    workspace_id?: string | null;
    user_id?: string | null;
    month: string;
    items: AdminUsageItem[];
    total: number;
  };
}

export interface AdminQuotaItem {
  tenant_id: string;
  workspace_id: string;
  user_id: string;
  monthly_token_quota: number;
  enabled: boolean;
  updated_at: number;
}

export interface AdminQuotaListResponse {
  status: string;
  data: {
    tenant_id: string;
    workspace_id?: string | null;
    user_id?: string | null;
    items: AdminQuotaItem[];
    total: number;
  };
}

export interface AdminQuotaSetResponse {
  status: string;
  data: {
    quota: AdminQuotaItem;
  };
}
