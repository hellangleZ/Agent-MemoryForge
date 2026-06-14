'use client';

import { useEffect, useMemo, useState } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { Card, CardHeader, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Input, Textarea } from '@/components/ui/Input';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import {
  applyWorkspaceConfig,
  getTools,
  getWorkspace,
  getWorkspaceConfig,
  getWorkspaceSecrets,
  saveWorkspaceConfig,
  saveWorkspaceSecrets,
  type WorkspaceConfig,
  type WorkspaceSecretsStatus,
} from '@/lib/api';
import { useTheme } from '@/lib/theme';
import { logError } from '@/lib/errorTracking';
import {
  DEFAULT_WORKSPACE_SECRET_NAMES,
  WORKSPACE_SECRET_NAME_RE,
  extractInlineWorkspaceSecretsFromMcp,
  hasWorkspaceSecretDraftValues,
  normalizeWorkspaceSecretName,
  normalizeWorkspaceSecretStatus,
  referencedWorkspaceSecretNames,
  workspaceSecretRowsFromStatus,
  type WorkspaceSecretDraft,
} from '@/lib/workspaceSecrets';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import {
  AlertCircle,
  Brain,
  CheckCircle,
  FileJson,
  KeyRound,
  Loader2,
  Plug,
  RefreshCw,
  RotateCcw,
  Save,
  Settings,
  Terminal,
  Trash2,
  Zap,
} from 'lucide-react';

interface Tool {
  name: string;
  category?: string;
  spec?: string;
  schema?: {
    description?: string;
    parameters?: Record<string, unknown>;
  };
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

type McpConfig = NonNullable<WorkspaceConfig['mcp']>;

const CONTEXT7_HTTP_HEADERS = JSON.stringify(
  {
    CONTEXT7_API_KEY: '${CONTEXT7_API_KEY}',
  },
  null,
  2
);

const CONTEXT7_SERVER_JSON = JSON.stringify(
  [
    {
      name: 'context7-docs',
      transport: 'http',
      namespace: 'context7',
      url: 'https://mcp.context7.com/mcp',
      headers: {
        CONTEXT7_API_KEY: '${CONTEXT7_API_KEY}',
      },
      required_env: ['CONTEXT7_API_KEY'],
    },
  ],
  null,
  2
);

function getMcp(config: WorkspaceConfig): McpConfig {
  return {
    mcp_stdio_json: config.mcp?.mcp_stdio_json || '',
    mcp_servers_json: config.mcp?.mcp_servers_json || '',
    mcp_http_url: config.mcp?.mcp_http_url || '',
    mcp_http_namespace: config.mcp?.mcp_http_namespace || 'mcp',
    mcp_http_headers_json: config.mcp?.mcp_http_headers_json || '',
  };
}

function validateJson(value: string | undefined, label: string, expected: 'array' | 'object'): string | null {
  const trimmed = String(value || '').trim();
  if (!trimmed) return null;

  try {
    const parsed = JSON.parse(trimmed);
    if (expected === 'array' && !Array.isArray(parsed)) {
      return `${label} must be a JSON array`;
    }
    if (expected === 'object' && (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object')) {
      return `${label} must be a JSON object`;
    }
    return null;
  } catch {
    return `${label} is not valid JSON`;
  }
}

function validateMcpConfig(mcp: McpConfig): string | null {
  return (
    validateJson(mcp.mcp_servers_json, 'MCP servers config', 'array') ||
    validateJson(mcp.mcp_stdio_json, 'MCP STDIO config', 'object') ||
    validateJson(mcp.mcp_http_headers_json, 'MCP HTTP headers', 'object')
  );
}

function ConfigContent() {
  const { addToast } = useToast();
  const { isDark } = useTheme();
  const [config, setConfig] = useState<WorkspaceConfig>({});
  const [tools, setTools] = useState<ToolsResponse | null>(null);
  const [secretStatus, setSecretStatus] = useState<Record<string, boolean>>({});
  const [secretRows, setSecretRows] = useState<WorkspaceSecretDraft[]>(
    DEFAULT_WORKSPACE_SECRET_NAMES.map((name) => ({ name, value: '' }))
  );
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [refreshingTools, setRefreshingTools] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);
  const workspaceId = getWorkspace();

  const allTools = useMemo(() => Object.values(tools?.data || {}).flat(), [tools]);
  const configuredSecretsCount = Object.values(secretStatus).filter(Boolean).length;
  const hasPendingSecretValues = hasWorkspaceSecretDraftValues(secretRows);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [configData, toolsData, secretsData] = await Promise.all([
          getWorkspaceConfig().catch(() => ({ data: {} })),
          getTools().catch(() => null),
          getWorkspaceSecrets().catch(() => null),
        ]);

        const nextConfig = ((configData as { data?: WorkspaceConfig }).data || {}) as WorkspaceConfig;
        const nextSecrets =
          ((secretsData as { data?: WorkspaceSecretsStatus } | null)?.data?.configured) ||
          nextConfig.mcp_secrets ||
          {};
        const normalizedSecrets = normalizeWorkspaceSecretStatus(nextSecrets);

        setConfig(nextConfig);
        setTools(toolsData as ToolsResponse | null);
        setSecretStatus(normalizedSecrets);
        setSecretRows((prev) => workspaceSecretRowsFromStatus(normalizedSecrets, prev));
      } catch (err: unknown) {
        const error = err instanceof Error ? err : new Error('Failed to fetch config');
        logError(error, { component: 'ConfigPage', action: 'fetchData' });
        addToast('Failed to load configuration', 'error');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [addToast]);

  const handleConfigChange = (field: keyof WorkspaceConfig, value: string) => {
    setConfig((prev) => ({
      ...prev,
      [field]: value,
    }));
    setHasChanges(true);
  };

  const handleMcpChange = (field: keyof McpConfig, value: string) => {
    setConfig((prev) => ({
      ...prev,
      mcp: {
        ...getMcp(prev),
        [field]: value,
      },
    }));
    setHasChanges(true);
  };

  const applyContext7Preset = () => {
    setConfig((prev) => ({
      ...prev,
      mcp: {
        ...getMcp(prev),
        mcp_http_url: 'https://mcp.context7.com/mcp',
        mcp_http_namespace: 'context7',
        mcp_http_headers_json: CONTEXT7_HTTP_HEADERS,
      },
    }));
    setSecretRows((prev) =>
      workspaceSecretRowsFromStatus(
        {
          ...secretStatus,
          CONTEXT7_API_KEY: Boolean(secretStatus.CONTEXT7_API_KEY),
        },
        prev
      )
    );
    setHasChanges(true);
  };

  const refreshToolInventory = async () => {
    setRefreshingTools(true);
    try {
      const toolsData = await getTools({ refresh: true });
      setTools(toolsData as ToolsResponse);
      const warning = (toolsData as ToolsResponse).warning;
      if (warning) {
        addToast(warning, 'error');
      } else {
        addToast('Tool inventory refreshed', 'success');
      }
    } catch (err: unknown) {
      const error = err instanceof Error ? err : new Error('Failed to refresh tools');
      logError(error, { component: 'ConfigPage', action: 'refreshTools' });
      addToast('Failed to refresh tools', 'error');
    } finally {
      setRefreshingTools(false);
    }
  };

  const saveSecretValues = async (): Promise<void> => {
    const values: Record<string, string> = {};

    for (const row of secretRows) {
      const name = normalizeWorkspaceSecretName(row.name);
      const value = row.value.trim();
      if (!name && value) throw new Error('Secret name is required');
      if (name && !WORKSPACE_SECRET_NAME_RE.test(name)) throw new Error(`${name} is not a valid secret name`);
      if (name && value) values[name] = value;
    }

    if (!Object.keys(values).length) return;

    const saved = await saveWorkspaceSecrets({ values });
    const nextStatus = normalizeWorkspaceSecretStatus(saved.data.configured);
    setSecretStatus(nextStatus);
    setSecretRows((prev) => workspaceSecretRowsFromStatus(nextStatus, prev).map((row) => ({ ...row, value: '' })));
  };

  const saveSecretsOnly = async () => {
    setSaving(true);
    try {
      await saveSecretValues();
      addToast('Workspace secrets saved', 'success');
    } catch (err: unknown) {
      const error = err instanceof Error ? err : new Error('Failed to save workspace secrets');
      logError(error, { component: 'ConfigPage', action: 'saveSecrets' });
      addToast(error.message || 'Failed to save workspace secrets', 'error');
    } finally {
      setSaving(false);
    }
  };

  const clearSecret = async (name: string) => {
    const secretName = normalizeWorkspaceSecretName(name);
    if (!secretName) return;

    setSaving(true);
    try {
      const saved = await saveWorkspaceSecrets({ clear: [secretName] });
      const nextStatus = normalizeWorkspaceSecretStatus(saved.data.configured);
      setSecretStatus(nextStatus);
      setSecretRows((prev) => workspaceSecretRowsFromStatus(nextStatus, prev));
      addToast('Workspace secret cleared', 'success');
    } catch (err: unknown) {
      const error = err instanceof Error ? err : new Error('Failed to clear workspace secret');
      logError(error, { component: 'ConfigPage', action: 'clearSecret', secretName });
      addToast('Failed to clear workspace secret', 'error');
    } finally {
      setSaving(false);
    }
  };

  const removeSecretRow = (index: number) => {
    setSecretRows((prev) => prev.filter((_, itemIndex) => itemIndex !== index));
  };

  const handleSave = async () => {
    const { mcp, values: inlineSecretValues, names: inlineSecretNames } =
      extractInlineWorkspaceSecretsFromMcp(getMcp(config));
    const validationError = validateMcpConfig(mcp);
    if (validationError) {
      addToast(validationError, 'error');
      return;
    }

    const draftSecretNames = new Set(
      secretRows
        .filter((row) => row.value.trim())
        .map((row) => normalizeWorkspaceSecretName(row.name))
        .filter(Boolean)
    );
    const inlineSecretNameSet = new Set(inlineSecretNames);
    const missingSecrets = referencedWorkspaceSecretNames(mcp).filter(
      (name) => !secretStatus[name] && !draftSecretNames.has(name) && !inlineSecretNameSet.has(name)
    );
    if (missingSecrets.length) {
      addToast(`Missing workspace secret: ${missingSecrets.join(', ')}`, 'error');
      return;
    }

    setSaving(true);
    try {
      await saveSecretValues();
      if (inlineSecretNames.length) {
        const saved = await saveWorkspaceSecrets({ values: inlineSecretValues });
        const nextStatus = normalizeWorkspaceSecretStatus(saved.data.configured);
        setSecretStatus(nextStatus);
        setSecretRows((prev) => workspaceSecretRowsFromStatus(nextStatus, prev).map((row) => ({ ...row, value: '' })));
        setConfig((prev) => ({ ...prev, mcp }));
      }
      await saveWorkspaceConfig({
        system_prompt: config.system_prompt,
        mcp,
      });
      await applyWorkspaceConfig();
      const toolsData = await getTools({ refresh: true });
      setTools(toolsData as ToolsResponse);
      const warning = (toolsData as ToolsResponse).warning;
      if (warning) {
        addToast(warning, 'error');
      } else {
        addToast('Configuration saved and tools discovered', 'success');
      }
      setHasChanges(false);
    } catch (err: unknown) {
      const error = err instanceof Error ? err : new Error('Failed to save config');
      logError(error, { component: 'ConfigPage', action: 'saveApplyConfig' });
      addToast(error.message || 'Failed to save configuration', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setConfig({});
    setHasChanges(true);
    addToast('Configuration reset to defaults', 'info');
  };

  if (loading) {
    return (
      <div className={cn(
        "min-h-screen flex items-center justify-center transition-colors duration-300",
        isDark ? "bg-[hsl(230_25%_7%)]" : "bg-[hsl(220_20%_97%)]"
      )}>
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-cyan-500" />
          <p className={cn(
            "transition-colors duration-300",
            isDark ? "text-slate-500" : "text-slate-500"
          )}>Loading configuration...</p>
        </div>
      </div>
    );
  }

  const mcp = getMcp(config);

  return (
    <div className={cn(
      "min-h-screen transition-colors duration-300",
      isDark ? "bg-[hsl(230_25%_7%)]" : "bg-[hsl(220_20%_97%)]"
    )}>
      <div className="fixed inset-0 -z-10 overflow-hidden">
        <div className={cn(
          "absolute inset-0 transition-colors duration-300",
          isDark
            ? "bg-gradient-to-br from-purple-900/20 via-transparent to-cyan-900/20"
            : "bg-gradient-to-br from-purple-100/50 via-transparent to-cyan-100/50"
        )} />
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage: isDark
              ? 'linear-gradient(hsl(185 100% 50% / 0.02) 1px, transparent 1px), linear-gradient(90deg, hsl(185 100% 50% / 0.02) 1px, transparent 1px)'
              : 'linear-gradient(hsl(185 85% 40% / 0.03) 1px, transparent 1px), linear-gradient(90deg, hsl(185 85% 40% / 0.03) 1px, transparent 1px)',
            backgroundSize: '50px 50px',
          }}
        />
      </div>

      <div className="container mx-auto px-4 py-8 relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          <div className="lg:col-span-1">
            <Sidebar variant="customer" />
          </div>

          <div className="lg:col-span-3 space-y-6">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
            >
              <Card className="p-6">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                  <div className="flex items-center gap-4">
                    <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-500 to-cyan-500 flex items-center justify-center shadow-lg shadow-purple-500/25">
                      <Settings className="w-7 h-7 text-white" />
                    </div>
                    <div>
                      <h1 className={cn(
                        "text-2xl font-bold transition-colors duration-300",
                        isDark ? "text-white" : "text-slate-900"
                      )}>
                        Configuration
                      </h1>
                      <p className={cn(
                        "transition-colors duration-300",
                        isDark ? "text-slate-400" : "text-slate-600"
                      )}>
                        Workspace: <span className="gradient-text">{workspaceId}</span>
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    {(hasChanges || hasPendingSecretValues) && (
                      <span className={cn(
                        "text-sm",
                        isDark ? "text-amber-400" : "text-amber-600"
                      )}>Unsaved changes</span>
                    )}
                    <Button
                      variant="secondary"
                      onClick={handleReset}
                      disabled={saving}
                    >
                      <RotateCcw className="w-4 h-4" />
                      Reset
                    </Button>
                    <Button
                      onClick={handleSave}
                      loading={saving}
                      disabled={refreshingTools}
                    >
                      <Plug className="w-4 h-4" />
                      Save & apply
                    </Button>
                  </div>
                </div>
              </Card>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
            >
              <Card>
                <CardHeader
                  title="LLM Configuration"
                  description="System prompt and language model settings"
                  action={
                    <div className="flex items-center gap-2">
                      <Brain className={cn(
                        "w-4 h-4",
                        isDark ? "text-purple-400" : "text-purple-600"
                      )} />
                      <span className={cn(
                        "text-xs transition-colors duration-300",
                        isDark ? "text-slate-500" : "text-slate-500"
                      )}>AI Model</span>
                    </div>
                  }
                />
                <CardContent>
                  <Textarea
                    id="system_prompt"
                    label="System Prompt"
                    placeholder="You are a helpful AI assistant..."
                    value={config.system_prompt || ''}
                    onChange={(e) => handleConfigChange('system_prompt', e.target.value)}
                    className="min-h-[150px]"
                  />
                </CardContent>
              </Card>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.2 }}
            >
              <Card>
                <CardHeader
                  title="MCP Tools Configuration"
                  description="Model Context Protocol tool settings"
                  action={
                    <div className="flex flex-wrap items-center gap-2">
                      <Button variant="secondary" size="sm" onClick={applyContext7Preset} disabled={saving}>
                        <FileJson className="w-4 h-4" />
                        Context7
                      </Button>
                      <Button variant="ghost" size="sm" onClick={refreshToolInventory} loading={refreshingTools} disabled={saving}>
                        <RefreshCw className="w-4 h-4" />
                        Refresh
                      </Button>
                    </div>
                  }
                />
                <CardContent className="space-y-5">
                  <div className="rounded-md border bg-muted/20 p-4">
                    <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                      <div className="flex flex-wrap items-center gap-2">
                        <KeyRound className="w-4 h-4 text-text-muted" />
                        <h3 className="text-sm font-medium text-text-primary">Workspace secrets</h3>
                        <Badge variant={configuredSecretsCount ? 'success' : 'default'}>
                          {configuredSecretsCount} configured
                        </Badge>
                      </div>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => setSecretRows((prev) => [...prev, { name: '', value: '' }])}
                        disabled={saving}
                      >
                        Add secret
                      </Button>
                    </div>

                    <div className="space-y-3">
                      {secretRows.map((row, index) => {
                        const name = normalizeWorkspaceSecretName(row.name);
                        const configured = Boolean(name && secretStatus[name]);
                        return (
                          <div key={`${row.name}-${index}`} className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(180px,1fr)_minmax(220px,2fr)_auto] md:items-end">
                            <Input
                              label="Name"
                              value={row.name}
                              onChange={(event) =>
                                setSecretRows((prev) =>
                                  prev.map((item, itemIndex) =>
                                    itemIndex === index ? { ...item, name: normalizeWorkspaceSecretName(event.target.value) } : item
                                  )
                                )
                              }
                              placeholder="CONTEXT7_API_KEY"
                              className="font-mono text-xs uppercase"
                            />
                            <Input
                              label={configured ? 'Value configured' : 'Value'}
                              type="password"
                              value={row.value}
                              onChange={(event) =>
                                setSecretRows((prev) =>
                                  prev.map((item, itemIndex) =>
                                    itemIndex === index ? { ...item, value: event.target.value } : item
                                  )
                                )
                              }
                              placeholder={configured ? 'Leave blank to keep existing value' : 'Paste workspace token'}
                              autoComplete="off"
                            />
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => (configured ? clearSecret(name) : removeSecretRow(index))}
                              disabled={saving}
                            >
                              <Trash2 className="w-4 h-4" />
                              {configured ? 'Clear' : 'Remove'}
                            </Button>
                          </div>
                        );
                      })}
                    </div>

                    <div className="mt-4 flex justify-end">
                      <Button variant="secondary" onClick={saveSecretsOnly} loading={saving} disabled={!hasPendingSecretValues}>
                        <Save className="w-4 h-4" />
                        Save secrets
                      </Button>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <Textarea
                      id="mcp_stdio_json"
                      label="MCP STDIO Config (JSON object)"
                      placeholder='{"command":"python","args":["-m","agent_memory_mcp_server"]}'
                      value={mcp.mcp_stdio_json || ''}
                      onChange={(e) => handleMcpChange('mcp_stdio_json', e.target.value)}
                      className="min-h-[120px] font-mono text-xs"
                    />
                    <Textarea
                      id="mcp_servers_json"
                      label="MCP Servers Config (JSON array)"
                      placeholder={CONTEXT7_SERVER_JSON}
                      value={mcp.mcp_servers_json || ''}
                      onChange={(e) => handleMcpChange('mcp_servers_json', e.target.value)}
                      className="min-h-[120px] font-mono text-xs"
                    />
                    <Input
                      id="mcp_http_url"
                      label="MCP HTTP URL"
                      placeholder="https://mcp.context7.com/mcp"
                      value={mcp.mcp_http_url || ''}
                      onChange={(e) => handleMcpChange('mcp_http_url', e.target.value)}
                    />
                    <Input
                      id="mcp_http_namespace"
                      label="MCP HTTP Namespace"
                      placeholder="context7"
                      value={mcp.mcp_http_namespace || ''}
                      onChange={(e) => handleMcpChange('mcp_http_namespace', e.target.value)}
                    />
                  </div>
                  <Textarea
                    id="mcp_http_headers_json"
                    label="MCP HTTP Headers (JSON object)"
                    placeholder={CONTEXT7_HTTP_HEADERS}
                    value={mcp.mcp_http_headers_json || ''}
                    onChange={(e) => handleMcpChange('mcp_http_headers_json', e.target.value)}
                    className="min-h-[90px] font-mono text-xs"
                  />
                </CardContent>
              </Card>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.3 }}
            >
              <Card>
                <CardHeader
                  title="Available Tools"
                  description="Tools available in this workspace"
                  action={
                    <div className="flex items-center gap-2">
                      <Zap className={cn(
                        "w-4 h-4",
                        isDark ? "text-amber-400" : "text-amber-600"
                      )} />
                      <span className={cn(
                        "text-xs transition-colors duration-300",
                        isDark ? "text-slate-500" : "text-slate-500"
                      )}>
                        {allTools.length} tools
                      </span>
                    </div>
                  }
                />
                <CardContent>
                  {tools?.warning && (
                    <div className="mb-4 flex items-start gap-2 rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-text-secondary">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>{tools.warning}</span>
                    </div>
                  )}

                  {allTools.length > 0 ? (
                    <div className="space-y-4">
                      {Object.entries(tools?.data || {}).map(([category, categoryTools]) => (
                        <div key={category}>
                          <h4 className={cn(
                            "text-sm font-medium mb-2 capitalize transition-colors duration-300",
                            isDark ? "text-slate-400" : "text-slate-600"
                          )}>
                            {category}
                          </h4>
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                            {(categoryTools as Tool[]).map((tool) => (
                              <div
                                key={tool.name}
                                className={cn(
                                  "flex items-center gap-3 p-3 rounded-xl border transition-colors duration-300",
                                  isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"
                                )}
                              >
                                <CheckCircle className={cn(
                                  "w-4 h-4",
                                  isDark ? "text-green-400" : "text-green-600"
                                )} />
                                <div className="flex-1 min-w-0">
                                  <p className={cn(
                                    "text-sm font-medium truncate transition-colors duration-300",
                                    isDark ? "text-white" : "text-slate-900"
                                  )}>
                                    {tool.name}
                                  </p>
                                  {tool.schema?.description && (
                                    <p className={cn(
                                      "text-xs truncate transition-colors duration-300",
                                      isDark ? "text-slate-500" : "text-slate-500"
                                    )}>
                                      {tool.schema.description}
                                    </p>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center py-8">
                      <Terminal className={cn(
                        "w-10 h-10 mx-auto mb-3",
                        isDark ? "text-slate-500" : "text-slate-400"
                      )} />
                      <p className={cn(
                        "text-sm transition-colors duration-300",
                        isDark ? "text-slate-500" : "text-slate-500"
                      )}>
                        No tools discovered for this workspace.
                      </p>
                    </div>
                  )}
                </CardContent>
              </Card>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ConfigPage() {
  return (
    <ToastProvider>
      <ConfigContent />
    </ToastProvider>
  );
}
