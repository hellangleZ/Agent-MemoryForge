'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { Card, CardHeader, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge, StatusDot } from '@/components/ui/Badge';
import { Input, Textarea } from '@/components/ui/Input';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import {
  applyWorkspaceConfig,
  getWorkspaceSecrets,
  getTools,
  getToolsPolicy,
  getToolsStatus,
  getWorkspaceConfig,
  saveWorkspaceSecrets,
  saveWorkspaceConfig,
  ToolPolicy,
  updateToolsPolicy,
  WorkspaceConfig,
  WorkspaceSecretsStatus,
} from '@/lib/api';
import {
  AlertCircle,
  CheckCircle2,
  Database,
  FileJson,
  ListChecks,
  Loader2,
  KeyRound,
  Plug,
  Power,
  PowerOff,
  RefreshCw,
  Save,
  Search,
  Server,
  Terminal,
  Wrench,
} from 'lucide-react';
import {
  WORKSPACE_SECRET_NAME_RE,
  extractInlineWorkspaceSecretsFromMcp,
  normalizeWorkspaceSecretName,
  normalizeWorkspaceSecretStatus,
  workspaceSecretRowsFromStatus,
  type WorkspaceSecretDraft,
} from '@/lib/workspaceSecrets';

interface Tool {
  name: string;
  category?: string;
  spec?: string;
  schema?: { description?: string; parameters?: Record<string, unknown> };
}

interface ToolsResponse {
  data: Record<string, Tool[]>;
  tools_by_namespace?: Record<string, Tool[]>;
  warning?: string | null;
  discovery?: {
    cached: boolean;
    updated_at?: string | null;
    stale: boolean;
    refresh_required: boolean;
  };
}

interface ToolStatus {
  name: string;
  enabled: boolean;
  status: string;
  config: Record<string, unknown>;
}

interface ToolsStatusResponse {
  status?: string;
  data?: {
    workspace_configured?: boolean;
    workspace_saved?: boolean;
    workspace_applied?: boolean;
    env_configured?: boolean;
    configured?: boolean;
    env?: Record<string, string | null>;
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

interface McpDraft {
  mcp_servers_json: string;
  mcp_stdio_json: string;
  mcp_http_url: string;
  mcp_http_namespace: string;
  mcp_http_headers_json: string;
}

const EMPTY_MCP: McpDraft = {
  mcp_servers_json: '',
  mcp_stdio_json: '',
  mcp_http_url: '',
  mcp_http_namespace: 'mcp',
  mcp_http_headers_json: '',
};

const NEON_SERVER = {
  name: 'neon-postgres',
  transport: 'http',
  namespace: 'neon',
  url: 'https://mcp.neon.tech/mcp',
  headers: {
    Authorization: 'Bearer ${NEON_API_KEY}',
  },
  required_env: ['NEON_API_KEY'],
};

const SUPABASE_SERVER = {
  name: 'supabase-postgres',
  transport: 'http',
  namespace: 'supabase',
  url: 'https://mcp.supabase.com/mcp',
  headers: {
    Authorization: 'Bearer ${SUPABASE_ACCESS_TOKEN}',
  },
  required_env: ['SUPABASE_ACCESS_TOKEN'],
};

const CONTEXT7_SERVER = {
  name: 'context7-docs',
  transport: 'http',
  namespace: 'context7',
  url: 'https://mcp.context7.com/mcp',
  headers: {
    CONTEXT7_API_KEY: '${CONTEXT7_API_KEY}',
  },
  required_env: ['CONTEXT7_API_KEY'],
};

const HTTPS_MCP_PRESET = JSON.stringify([CONTEXT7_SERVER], null, 2);

function normalizeMcp(mcp?: WorkspaceConfig['mcp']): McpDraft {
  return {
    mcp_servers_json: mcp?.mcp_servers_json || '',
    mcp_stdio_json: mcp?.mcp_stdio_json || '',
    mcp_http_url: mcp?.mcp_http_url || '',
    mcp_http_namespace: mcp?.mcp_http_namespace || 'mcp',
    mcp_http_headers_json: mcp?.mcp_http_headers_json || '',
  };
}

function hasMcpConnectionValue(mcp: McpDraft): boolean {
  const serversJson = mcp.mcp_servers_json.trim();
  if (serversJson) {
    try {
      const servers = JSON.parse(serversJson);
      if (!Array.isArray(servers)) return true;
      return servers.some((server) => {
        if (!server || typeof server !== 'object') return false;
        const entry = server as Record<string, unknown>;
        return Boolean(String(entry.command || entry.url || '').trim());
      });
    } catch {
      return true;
    }
  }

  const stdioJson = mcp.mcp_stdio_json.trim();
  if (stdioJson) {
    try {
      const stdio = JSON.parse(stdioJson);
      if (!stdio || typeof stdio !== 'object' || Array.isArray(stdio)) return true;
      return Boolean(String((stdio as Record<string, unknown>).command || '').trim());
    } catch {
      return true;
    }
  }

  return Boolean(mcp.mcp_http_url.trim());
}

function parseCommaList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function validateJson(value: string, label: string, expected: 'array' | 'object'): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  try {
    const parsed = JSON.parse(trimmed);
    if (expected === 'array' && !Array.isArray(parsed)) {
      return `${label} must be a JSON array`;
    }
    if (expected === 'object' && (Array.isArray(parsed) || typeof parsed !== 'object' || parsed === null)) {
      return `${label} must be a JSON object`;
    }
    return null;
  } catch {
    return `${label} is not valid JSON`;
  }
}

function upsertServerPreset(currentJson: string, preset: Record<string, unknown>): string {
  let servers: Record<string, unknown>[] = [];
  const trimmed = currentJson.trim();
  if (trimmed) {
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) {
        servers = parsed.filter(
          (server): server is Record<string, unknown> =>
            Boolean(server) && typeof server === 'object' && !Array.isArray(server)
        );
      }
    } catch {
      servers = [];
    }
  }

  const presetName = String(preset.name || '').trim();
  const presetNamespace = String(preset.namespace || '').trim();
  const next = servers.filter((server) => {
    const serverName = String(server.name || '').trim();
    const serverNamespace = String(server.namespace || '').trim();
    return serverName !== presetName && serverNamespace !== presetNamespace;
  });
  next.push(preset);
  return JSON.stringify(next, null, 2);
}

function namespaceOf(tool: Tool): string {
  const name = String(tool.name || '');
  if (name.includes('.')) return name.split('.')[0] || 'mcp';
  return tool.category || 'local';
}

function AdminToolsContent() {
  const { addToast } = useToast();
  const [tools, setTools] = useState<ToolsResponse | null>(null);
  const [toolsStatus, setToolsStatus] = useState<ToolsStatusResponse | null>(null);
  const [workspaceConfig, setWorkspaceConfig] = useState<WorkspaceConfig>({});
  const [mcpDraft, setMcpDraft] = useState<McpDraft>(EMPTY_MCP);
  const [secretStatus, setSecretStatus] = useState<Record<string, boolean>>({});
  const [secretRows, setSecretRows] = useState<WorkspaceSecretDraft[]>(
    workspaceSecretRowsFromStatus({})
  );
  const [policy, setPolicy] = useState<ToolPolicy>({ allowlist: [], denylist: [], overrides: {} });
  const [policyDraft, setPolicyDraft] = useState({ allowlist: '', denylist: '' });
  const [loading, setLoading] = useState(true);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [savingSecrets, setSavingSecrets] = useState(false);
  const [applyingConfig, setApplyingConfig] = useState(false);
  const [savingPolicy, setSavingPolicy] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const refreshData = useCallback(async () => {
    const [statusData, policyData, workspaceData, secretsData] = await Promise.all([
      getToolsStatus().catch(() => null),
      getToolsPolicy().catch(() => null),
      getWorkspaceConfig().catch(() => null),
      getWorkspaceSecrets().catch(() => null),
    ]);

    const nextStatus = (statusData as ToolsStatusResponse | null) || { tools: [] };
    setToolsStatus(nextStatus);

    const nextPolicy = (policyData as { data?: ToolPolicy } | null)?.data || nextStatus.data?.policy;
    if (nextPolicy) {
      setPolicy(nextPolicy);
      setPolicyDraft({
        allowlist: (nextPolicy.allowlist || []).join(', '),
        denylist: (nextPolicy.denylist || []).join(', '),
      });
    }

    const nextWorkspace = (workspaceData as { data?: WorkspaceConfig } | null)?.data || {};
    setWorkspaceConfig(nextWorkspace);
    setMcpDraft(normalizeMcp(nextWorkspace.mcp));
    const nextSecretStatus =
      (secretsData as { data?: WorkspaceSecretsStatus } | null)?.data?.configured ||
      nextWorkspace.mcp_secrets ||
      nextStatus.data?.workspace_secrets ||
      {};
    const normalizedSecretStatus = normalizeWorkspaceSecretStatus(nextSecretStatus);
    setSecretStatus(normalizedSecretStatus);
    setSecretRows((prev) => workspaceSecretRowsFromStatus(normalizedSecretStatus, prev));
  }, []);

  const loadToolInventory = useCallback(async (refresh = false) => {
    setToolsLoading(true);
    try {
      const toolsData = await getTools({ refresh });
      setTools((toolsData as ToolsResponse | null) || { data: {} });
      if (refresh && (toolsData as ToolsResponse).warning) {
        addToast((toolsData as ToolsResponse).warning || 'Tool discovery returned a warning', 'error');
      }
    } catch {
      if (refresh) addToast('Failed to refresh tool inventory', 'error');
      setTools((prev) => prev || { data: {} });
    } finally {
      setToolsLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    refreshData()
      .catch(() => addToast('Failed to load tool configuration', 'error'))
      .finally(() => setLoading(false));
    void loadToolInventory(false);
  }, [addToast, loadToolInventory, refreshData]);

  const allTools = useMemo(() => Object.values(tools?.data || {}).flat(), [tools]);
  const statusByName = useMemo(() => {
    const map = new Map<string, ToolStatus>();
    for (const item of toolsStatus?.tools || []) map.set(item.name, item);
    return map;
  }, [toolsStatus]);
  const filteredTools = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return allTools;
    return allTools.filter((tool) => {
      const haystack = [tool.name, tool.category, tool.spec, tool.schema?.description]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [allTools, searchQuery]);

  const enabledCount = (toolsStatus?.tools || []).filter((tool) => tool.enabled).length;
  const totalCount = toolsStatus?.tools.length || allTools.length;
  const namespaceCount = new Set(allTools.map(namespaceOf)).size;
  const statusData = toolsStatus?.data;
  const savedMcpConfigured = hasMcpConnectionValue(normalizeMcp(workspaceConfig.mcp));
  const workspaceSaved = Boolean(statusData?.workspace_saved ?? savedMcpConfigured);
  const workspaceApplied = Boolean(statusData?.workspace_applied);
  const envConfigured = Boolean(statusData?.env_configured);
  const workspaceSecretsConfigured = Boolean(
    statusData?.workspace_secrets_configured ||
      Object.values(secretStatus).some(Boolean)
  );
  const configured = workspaceSaved || workspaceApplied || envConfigured;
  const inventoryUpdatedAt = tools?.discovery?.updated_at || statusData?.tool_inventory_updated_at || null;
  const inventoryRefreshRequired = Boolean(
    tools?.discovery?.refresh_required ?? statusData?.tool_inventory_refresh_required ?? true
  );
  const scopeLabel = `${workspaceConfig.tenant_id || 'tenant'} / ${workspaceConfig.workspace_id || 'workspace'}`;

  const updateMcpDraft = (key: keyof McpDraft, value: string) => {
    setMcpDraft((prev) => ({ ...prev, [key]: value }));
  };

  const addServerPreset = (preset: Record<string, unknown>) => {
    setMcpDraft((prev) => ({
      ...prev,
      mcp_servers_json: upsertServerPreset(prev.mcp_servers_json, preset),
    }));
    const required = Array.isArray(preset.required_env)
      ? preset.required_env.map((name) => normalizeWorkspaceSecretName(String(name))).filter(Boolean)
      : [];
    if (required.length) {
      const requiredStatus = Object.fromEntries(
        required.map((name) => [name, Boolean(secretStatus[name])])
      );
      setSecretRows((prev) => workspaceSecretRowsFromStatus(requiredStatus, prev));
    }
  };

  const validateMcpDraft = (): string | null => {
    return (
      validateJson(mcpDraft.mcp_servers_json, 'MCP servers JSON', 'array') ||
      validateJson(mcpDraft.mcp_stdio_json, 'STDIO JSON', 'object') ||
      validateJson(mcpDraft.mcp_http_headers_json, 'HTTP headers JSON', 'object')
    );
  };

  const saveMcpConfig = async () => {
    const error = validateMcpDraft();
    if (error) {
      addToast(error, 'error');
      return false;
    }

    setSavingConfig(true);
    try {
      const { mcp: sanitizedMcp, values: inlineSecretValues, names: inlineSecretNames } =
        extractInlineWorkspaceSecretsFromMcp(mcpDraft);
      if (inlineSecretNames.length) {
        await saveWorkspaceSecrets({ values: inlineSecretValues });
      }
      const nextConfig: WorkspaceConfig = {
        system_prompt: workspaceConfig.system_prompt,
        mcp: { ...sanitizedMcp },
      };
      await saveWorkspaceConfig(nextConfig);
      setWorkspaceConfig(nextConfig);
      setMcpDraft(sanitizedMcp);
      addToast('MCP configuration saved', 'success');
      await refreshData();
      return true;
    } catch {
      addToast('Failed to save MCP configuration', 'error');
      return false;
    } finally {
      setSavingConfig(false);
    }
  };

  const applyMcpConfig = async () => {
    setApplyingConfig(true);
    try {
      const saved = await saveMcpConfig();
      if (!saved) return;
      await applyWorkspaceConfig();
      await loadToolInventory(true);
      await refreshData();
      addToast('MCP configuration applied', 'success');
    } catch {
      addToast('Failed to apply MCP configuration', 'error');
    } finally {
      setApplyingConfig(false);
    }
  };

  const updateSecretRow = (index: number, key: keyof WorkspaceSecretDraft, value: string) => {
    const nextValue = key === 'name' ? value.toUpperCase() : value;
    setSecretRows((prev) =>
      prev.map((row, rowIndex) =>
        rowIndex === index ? { ...row, [key]: nextValue } : row
      )
    );
  };

  const saveSecretRows = async () => {
    const values: Record<string, string> = {};
    for (const row of secretRows) {
      const name = normalizeWorkspaceSecretName(row.name);
      const value = row.value;
      if (!name && !value.trim()) continue;
      if (!WORKSPACE_SECRET_NAME_RE.test(name)) {
        addToast(`${name || 'Secret name'} is not valid`, 'error');
        return;
      }
      if (value) values[name] = value;
    }
    if (Object.keys(values).length === 0) {
      addToast('No secret values to save', 'error');
      return;
    }

    setSavingSecrets(true);
    try {
      await saveWorkspaceSecrets({ values });
      setSecretRows((prev) => prev.map((row) => ({ ...row, value: '' })));
      await refreshData();
      addToast('Workspace secrets saved', 'success');
    } catch {
      addToast('Failed to save workspace secrets', 'error');
    } finally {
      setSavingSecrets(false);
    }
  };

  const clearSecret = async (name: string) => {
    const secretName = normalizeWorkspaceSecretName(name);
    if (!secretName) return;
    setSavingSecrets(true);
    try {
      await saveWorkspaceSecrets({ clear: [secretName] });
      setSecretStatus((prev) => {
        const next = { ...prev };
        delete next[secretName];
        return next;
      });
      await refreshData();
      addToast('Workspace secret cleared', 'success');
    } catch {
      addToast('Failed to clear workspace secret', 'error');
    } finally {
      setSavingSecrets(false);
    }
  };

  const removeSecretRow = (index: number) => {
    setSecretRows((prev) => prev.filter((_, rowIndex) => rowIndex !== index));
  };

  const refreshTools = async () => {
    try {
      await loadToolInventory(true);
      await refreshData();
      addToast('Tool inventory refreshed', 'success');
    } catch {
      addToast('Failed to refresh tools', 'error');
    }
  };

  const handleToggleTool = async (toolName: string, enabled: boolean) => {
    try {
      const overrides = { ...(policy.overrides || {}) };
      overrides[toolName] = !enabled;
      const payload: ToolPolicy = {
        allowlist: policy.allowlist || [],
        denylist: policy.denylist || [],
        overrides,
      };
      await updateToolsPolicy(payload);
      setPolicy(payload);
      setToolsStatus((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          tools: prev.tools.map((tool) =>
            tool.name === toolName ? { ...tool, enabled: !enabled } : tool
          ),
        };
      });
      addToast(`Tool ${enabled ? 'disabled' : 'enabled'}`, 'success');
    } catch {
      addToast('Failed to update tool policy', 'error');
    }
  };

  const handleSavePolicy = async () => {
    setSavingPolicy(true);
    try {
      const payload: ToolPolicy = {
        allowlist: parseCommaList(policyDraft.allowlist),
        denylist: parseCommaList(policyDraft.denylist),
        overrides: policy.overrides || {},
      };
      await updateToolsPolicy(payload);
      setPolicy(payload);
      await refreshData();
      addToast('Tool policy saved', 'success');
    } catch {
      addToast('Failed to save tool policy', 'error');
    } finally {
      setSavingPolicy(false);
    }
  };

  if (loading && !toolsStatus) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3 text-text-muted">
          <Loader2 className="h-8 w-8 animate-spin" />
          <p className="text-sm">Loading tools</p>
        </div>
      </div>
    );
  }

  const statusCards = [
    { label: 'Discovered', value: totalCount, icon: Wrench },
    { label: 'Enabled', value: enabledCount, icon: Power },
    { label: 'Namespaces', value: namespaceCount, icon: Server },
    { label: 'Secrets', value: Object.values(secretStatus).filter(Boolean).length, icon: KeyRound },
  ];

  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto px-4 py-8">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
          <div className="lg:col-span-1">
            <Sidebar variant="admin" />
          </div>
          <div className="space-y-6 lg:col-span-3">
            <Card className="p-6">
              <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div className="flex items-center gap-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-md border bg-muted text-text-primary">
                    <Terminal className="h-6 w-6" />
                  </div>
                  <div>
                    <h1 className="text-2xl font-semibold text-text-primary">Tool Management</h1>
                    <p className="text-sm text-text-muted">Workspace MCP configuration and tool policy</p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={configured ? 'success' : 'warning'} dot>
                    {configured ? 'Configured' : 'Not configured'}
                  </Badge>
                  <Badge variant={workspaceApplied ? 'success' : 'default'}>
                    {workspaceApplied ? 'Applied' : 'Not applied'}
                  </Badge>
                  <Badge variant={inventoryRefreshRequired ? 'warning' : 'default'}>
                    {inventoryRefreshRequired ? 'Discovery needed' : 'Inventory cached'}
                  </Badge>
                  <Badge variant="info">{enabledCount}/{totalCount} enabled</Badge>
                </div>
              </div>
            </Card>

            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              {statusCards.map((stat) => (
                <Card key={stat.label} className="p-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-md bg-muted text-text-primary">
                      <stat.icon className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="text-2xl font-semibold text-text-primary">{stat.value}</p>
                      <p className="text-xs text-text-muted">{stat.label}</p>
                    </div>
                  </div>
                </Card>
              ))}
            </div>

            <Card>
              <CardHeader
                title="MCP Connection"
                description="Current workspace server settings"
                action={
                  <div className="flex flex-wrap gap-2">
                    <Button variant="secondary" size="sm" onClick={() => addServerPreset(NEON_SERVER)}>
                      <Database className="h-4 w-4" />
                      Neon
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => addServerPreset(SUPABASE_SERVER)}>
                      <Database className="h-4 w-4" />
                      Supabase
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => addServerPreset(CONTEXT7_SERVER)}>
                      <FileJson className="h-4 w-4" />
                      Context7
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setMcpDraft(EMPTY_MCP)}>
                      Clear
                    </Button>
                  </div>
                }
              />
              <CardContent className="space-y-5">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
                  <div className="rounded-md border bg-muted/30 p-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
                      <Server className="h-4 w-4 text-text-muted" />
                      Scope
                    </div>
                    <p className="mt-1 truncate font-mono text-xs text-text-muted">{scopeLabel}</p>
                  </div>
                  <div className="rounded-md border bg-muted/30 p-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
                      <StatusDot status={workspaceSaved ? 'online' : 'offline'} />
                      Saved config
                    </div>
                    <p className="mt-1 text-xs text-text-muted">{workspaceSaved ? 'Present' : 'Empty'}</p>
                  </div>
                  <div className="rounded-md border bg-muted/30 p-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
                      <StatusDot status={workspaceApplied ? 'online' : 'warning'} />
                      Runtime state
                    </div>
                    <p className="mt-1 text-xs text-text-muted">{workspaceApplied ? 'Applied in gateway' : 'Apply required'}</p>
                  </div>
                  <div className="rounded-md border bg-muted/30 p-3">
                    <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
                      <StatusDot status={workspaceSecretsConfigured ? 'online' : 'offline'} />
                      Workspace secrets
                    </div>
                    <p className="mt-1 text-xs text-text-muted">{workspaceSecretsConfigured ? 'Configured' : 'Empty'}</p>
                  </div>
                </div>

                <div className="rounded-md border bg-muted/20 p-4">
                  <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div className="flex items-center gap-2">
                      <KeyRound className="h-4 w-4 text-text-muted" />
                      <h3 className="text-sm font-medium text-text-primary">Workspace secrets</h3>
                      <Badge variant={workspaceSecretsConfigured ? 'success' : 'default'}>
                        {Object.values(secretStatus).filter(Boolean).length} configured
                      </Badge>
                    </div>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setSecretRows((prev) => [...prev, { name: '', value: '' }])}
                      disabled={savingSecrets}
                    >
                      Add secret
                    </Button>
                  </div>
                  <p className="mb-4 text-xs text-text-muted">Scope: {scopeLabel}. Saved values stay redacted.</p>

                  <div className="space-y-3">
                    {secretRows.map((row, index) => {
                      const name = normalizeWorkspaceSecretName(row.name);
                      const configured = Boolean(name && secretStatus[name]);
                      return (
                        <div key={`${row.name}-${index}`} className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(180px,1fr)_minmax(220px,2fr)_auto] md:items-end">
                          <Input
                            label="Name"
                            value={row.name}
                            onChange={(event) => updateSecretRow(index, 'name', event.target.value)}
                            placeholder="NEON_API_KEY"
                            className="font-mono text-xs uppercase"
                          />
                          <Input
                            label={configured ? 'Value configured' : 'Value'}
                            type="password"
                            value={row.value}
                            onChange={(event) => updateSecretRow(index, 'value', event.target.value)}
                            placeholder={configured ? 'Leave blank to keep existing value' : 'Paste workspace token'}
                            autoComplete="off"
                          />
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => (configured ? clearSecret(name) : removeSecretRow(index))}
                            disabled={savingSecrets}
                          >
                            {configured ? 'Clear' : 'Remove'}
                          </Button>
                        </div>
                      );
                    })}
                  </div>

                  <div className="mt-4 flex justify-end">
                    <Button variant="secondary" onClick={saveSecretRows} loading={savingSecrets} disabled={savingConfig || applyingConfig}>
                      <Save className="h-4 w-4" />
                      Save secrets
                    </Button>
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                  <Textarea
                    label="MCP servers JSON"
                    value={mcpDraft.mcp_servers_json}
                    onChange={(event) => updateMcpDraft('mcp_servers_json', event.target.value)}
                    placeholder={HTTPS_MCP_PRESET}
                    className="min-h-[190px] font-mono text-xs"
                  />
                  <Input
                    label="Single HTTP MCP URL"
                    value={mcpDraft.mcp_http_url}
                    onChange={(event) => updateMcpDraft('mcp_http_url', event.target.value)}
                    placeholder="https://mcp.example.com/mcp"
                  />
                  <Input
                    label="HTTP namespace"
                    value={mcpDraft.mcp_http_namespace}
                    onChange={(event) => updateMcpDraft('mcp_http_namespace', event.target.value)}
                    placeholder="mcp"
                  />
                  <div className="xl:col-span-2">
                    <Textarea
                      label="HTTP headers JSON"
                      value={mcpDraft.mcp_http_headers_json}
                      onChange={(event) => updateMcpDraft('mcp_http_headers_json', event.target.value)}
                      placeholder='{"Authorization":"Bearer ..."}'
                      className="min-h-[90px] font-mono text-xs"
                    />
                  </div>
                </div>

                <div className="flex flex-col gap-3 border-t pt-4 md:flex-row md:items-center md:justify-between">
                  <div className="flex items-center gap-2 text-sm text-text-muted">
                    {workspaceApplied ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
                    <span>{workspaceApplied ? 'Active tools are using the applied workspace configuration.' : 'Save and apply to activate this workspace configuration.'}</span>
                  </div>
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button variant="secondary" onClick={saveMcpConfig} loading={savingConfig} disabled={applyingConfig}>
                      <Save className="h-4 w-4" />
                      Save config
                    </Button>
                    <Button onClick={applyMcpConfig} loading={applyingConfig} disabled={savingConfig || toolsLoading}>
                      <Plug className="h-4 w-4" />
                      Apply & discover
                    </Button>
                    <Button variant="ghost" onClick={refreshTools} loading={toolsLoading} disabled={savingConfig || applyingConfig}>
                      <RefreshCw className="h-4 w-4" />
                      Refresh
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader title="Tool Policy" description="Allowlist, denylist, and per-tool overrides" />
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <Textarea
                    label="Allowlist"
                    value={policyDraft.allowlist}
                    onChange={(event) => setPolicyDraft((prev) => ({ ...prev, allowlist: event.target.value }))}
                    rows={2}
                    placeholder="memory.calculate_budget, memory.project_gantt"
                  />
                  <Textarea
                    label="Denylist"
                    value={policyDraft.denylist}
                    onChange={(event) => setPolicyDraft((prev) => ({ ...prev, denylist: event.target.value }))}
                    rows={2}
                    placeholder="memory.delete, external.write"
                  />
                </div>
                <div className="flex justify-end">
                  <Button variant="secondary" onClick={handleSavePolicy} loading={savingPolicy}>
                    <ListChecks className="h-4 w-4" />
                    Save policy
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader
                title="Discovered Tools"
                description={inventoryUpdatedAt ? `Cached inventory from ${inventoryUpdatedAt}` : 'Cached inventory'}
                action={
                  <div className="relative w-full min-w-[240px] sm:w-80">
                    <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                    <input
                      type="text"
                      placeholder="Search tools"
                      value={searchQuery}
                      onChange={(event) => setSearchQuery(event.target.value)}
                      className="h-9 w-full rounded-md border bg-card pl-9 pr-3 text-sm text-text-primary shadow-sm placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ring/15"
                    />
                  </div>
                }
              />
              <CardContent>
                {tools?.warning && (
                  <div className="mb-4 rounded-md border bg-muted/40 p-3 text-sm text-text-muted">
                    {tools.warning}
                  </div>
                )}
                {toolsLoading ? (
                  <div className="flex min-h-[180px] flex-col items-center justify-center rounded-md border border-dashed p-6 text-center">
                    <Loader2 className="h-8 w-8 animate-spin text-text-muted" />
                    <h3 className="mt-3 text-sm font-medium text-text-primary">Discovering tools</h3>
                    <p className="mt-1 max-w-md text-sm text-text-muted">Waiting for MCP server responses.</p>
                  </div>
                ) : filteredTools.length === 0 ? (
                  <div className="flex min-h-[180px] flex-col items-center justify-center rounded-md border border-dashed p-6 text-center">
                    <Wrench className="h-8 w-8 text-text-muted" />
                    <h3 className="mt-3 text-sm font-medium text-text-primary">No tools discovered</h3>
                    <p className="mt-1 max-w-md text-sm text-text-muted">
                      Apply an MCP configuration or refresh the active workspace inventory.
                    </p>
                    <div className="mt-4 flex gap-2">
                      <Button size="sm" onClick={applyMcpConfig} loading={applyingConfig} disabled={toolsLoading}>
                        <Plug className="h-4 w-4" />
                        Apply & discover
                      </Button>
                      <Button size="sm" variant="secondary" onClick={refreshTools} loading={toolsLoading}>
                        <RefreshCw className="h-4 w-4" />
                        Refresh
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    {filteredTools.map((tool) => {
                      const status = statusByName.get(tool.name);
                      const isEnabled = status?.enabled ?? true;
                      return (
                        <div key={`${namespaceOf(tool)}:${tool.name}`} className="rounded-md border bg-muted/20 p-4 transition-colors hover:bg-muted/40">
                          <div className="flex items-start justify-between gap-4">
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <h4 className="truncate text-sm font-medium text-text-primary">{tool.name}</h4>
                                <Badge variant={isEnabled ? 'success' : 'default'}>{isEnabled ? 'Enabled' : 'Disabled'}</Badge>
                                <Badge variant="info">{namespaceOf(tool)}</Badge>
                              </div>
                              {tool.schema?.description && (
                                <p className="mt-2 line-clamp-2 text-sm text-text-muted">{tool.schema.description}</p>
                              )}
                              {tool.spec && <p className="mt-2 truncate font-mono text-xs text-text-muted">{tool.spec}</p>}
                            </div>
                            <Button size="sm" variant={isEnabled ? 'secondary' : 'primary'} onClick={() => handleToggleTool(tool.name, isEnabled)}>
                              {isEnabled ? <PowerOff className="h-3 w-3" /> : <Power className="h-3 w-3" />}
                              {isEnabled ? 'Disable' : 'Enable'}
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AdminToolsPage() {
  return (
    <ToastProvider>
      <AdminToolsContent />
    </ToastProvider>
  );
}
