'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { Card, CardHeader, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import { apiErrorStatus, getTools, getToolsStatus, getToolsPolicy, updateToolsPolicy, ToolPolicy } from '@/lib/api';
import { logError } from '@/lib/errorTracking';
import { cn } from '@/lib/utils';
import { AlertCircle, Filter, Loader2, Power, PowerOff, RefreshCw, Search, Terminal, Wrench, Zap } from 'lucide-react';

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
    tool_inventory_cached?: boolean;
    tool_inventory_updated_at?: string | null;
    tool_inventory_stale?: boolean;
    tool_inventory_refresh_required?: boolean;
  };
  tools: ToolStatus[];
}

function namespaceOf(tool: Tool): string {
  const name = String(tool.name || '');
  if (name.includes('.')) return name.split('.')[0] || 'mcp';
  return tool.category || 'local';
}

function ToolsContent() {
  const { addToast } = useToast();
  const [tools, setTools] = useState<ToolsResponse | null>(null);
  const [toolsStatus, setToolsStatus] = useState<ToolsStatusResponse | null>(null);
  const [toolPolicy, setToolPolicy] = useState<ToolPolicy | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [toggling, setToggling] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterCategory, setFilterCategory] = useState<string>('all');

  const fetchData = useCallback(async (options?: { refresh?: boolean }) => {
    const refresh = Boolean(options?.refresh);
    if (refresh) setRefreshing(true);
    try {
      const [toolsData, statusData, policyRes] = await Promise.all([
        getTools({ refresh }).catch((err) => {
          if (refresh) throw err;
          return null;
        }),
        getToolsStatus().catch(() => null),
        getToolsPolicy().catch(() => null),
      ]);

      setTools((toolsData as ToolsResponse | null) || { data: {} });
      setToolsStatus((statusData as ToolsStatusResponse | null) || { tools: [] });
      setToolPolicy((policyRes as { data?: ToolPolicy } | null)?.data || null);

      const warning = (toolsData as ToolsResponse | null)?.warning;
      if (warning) addToast(warning, 'error');
      if (refresh && !warning) addToast('Tool inventory refreshed', 'success');
    } catch (err: unknown) {
      const error = err instanceof Error ? err : new Error('Failed to fetch tools');
      logError(error, { component: 'ToolsPage', action: 'fetchData', refresh });
      addToast(refresh ? 'Failed to refresh tool inventory' : 'Failed to load tools', 'error');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [addToast]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const handleToggleTool = async (toolName: string, enabled: boolean) => {
    const nextEnabled = !enabled;
    setToggling(toolName);
    try {
      const current: ToolPolicy = toolPolicy || { allowlist: [], denylist: [], overrides: {} };
      const overrides = { ...(current.overrides || {}), [toolName]: nextEnabled };
      const nextPolicy: ToolPolicy = { ...current, overrides };
      await updateToolsPolicy(nextPolicy);
      setToolPolicy(nextPolicy);
      await fetchData();
      addToast(`Tool ${nextEnabled ? 'enabled' : 'disabled'}`, 'success');
    } catch (err: unknown) {
      const error = err instanceof Error ? err : new Error('Failed to toggle tool');
      logError(error, { component: 'ToolsPage', action: 'toggleTool', toolName });
      const status = apiErrorStatus(error);
      addToast(status === 403 ? 'Workspace owner or admin permission required' : 'Failed to update tool policy', 'error');
    } finally {
      setToggling(null);
    }
  };

  const allTools = useMemo(() => Object.values(tools?.data || {}).flat(), [tools]);
  const categories = useMemo(() => ['all', ...Object.keys(tools?.data || {})], [tools]);
  const filteredTools = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return allTools.filter((tool) => {
      const haystack = [tool.name, tool.category, tool.spec, tool.schema?.description]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      const matchesSearch = !query || haystack.includes(query);
      const matchesCategory = filterCategory === 'all' || namespaceOf(tool) === filterCategory || tool.category === filterCategory;
      return matchesSearch && matchesCategory;
    });
  }, [allTools, filterCategory, searchQuery]);

  const enabledCount = toolsStatus?.tools.filter((tool) => tool.enabled).length || 0;
  const totalCount = toolsStatus?.tools.length || allTools.length;
  const namespaceCount = new Set(allTools.map(namespaceOf)).size;
  const discovery = tools?.discovery;
  const statusData = toolsStatus?.data;
  const discoveryRequired = Boolean(
    discovery?.refresh_required ?? statusData?.tool_inventory_refresh_required ?? allTools.length === 0
  );
  const workspaceConfigured = Boolean(statusData?.workspace_configured || statusData?.configured);
  const inventoryLabel = discoveryRequired ? 'Discovery needed' : discovery?.cached ? 'Inventory cached' : 'No inventory';

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4 text-text-muted">
          <Loader2 className="h-8 w-8 animate-spin" />
          <p className="text-sm">Loading tools</p>
        </div>
      </div>
    );
  }

  const statusCards = [
    { icon: Wrench, label: 'Discovered', value: totalCount },
    { icon: Power, label: 'Enabled', value: enabledCount },
    { icon: PowerOff, label: 'Disabled', value: Math.max(totalCount - enabledCount, 0) },
    { icon: Terminal, label: 'Namespaces', value: namespaceCount },
  ];

  return (
    <div className="min-h-screen bg-background">
      <div className="container mx-auto px-4 py-8">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
          <div className="lg:col-span-1">
            <Sidebar variant="customer" />
          </div>

          <div className="space-y-6 lg:col-span-3">
            <Card className="p-6">
              <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div className="flex items-center gap-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-md border bg-muted text-text-primary">
                    <Terminal className="h-6 w-6" />
                  </div>
                  <div>
                    <h1 className="text-2xl font-semibold text-text-primary">MCP Tools</h1>
                    <p className="text-sm text-text-muted">Workspace-scoped tools discovered from your active MCP configuration</p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={workspaceConfigured ? 'success' : 'warning'} dot>
                    {workspaceConfigured ? 'Configured' : 'Not configured'}
                  </Badge>
                  <Badge variant={discoveryRequired ? 'warning' : 'default'}>
                    {inventoryLabel}
                  </Badge>
                  <Button variant="secondary" size="sm" onClick={() => fetchData({ refresh: true })} loading={refreshing}>
                    <RefreshCw className="h-4 w-4" />
                    Refresh
                  </Button>
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

            <Card className="p-4">
              <div className="flex flex-col gap-4 md:flex-row">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                  <input
                    type="text"
                    placeholder="Search tools"
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                    className="h-10 w-full rounded-md border bg-card pl-9 pr-3 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ring/15"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <Filter className="h-4 w-4 text-text-muted" />
                  <select
                    value={filterCategory}
                    onChange={(event) => setFilterCategory(event.target.value)}
                    className="h-10 min-w-[160px] rounded-md border bg-card px-3 text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-ring/15"
                  >
                    {categories.map((cat) => (
                      <option key={cat} value={cat}>
                        {cat === 'all' ? 'All namespaces' : cat}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </Card>

            <Card>
              <CardHeader title="Available Tools" description={`Showing ${filteredTools.length} tools`} />
              <CardContent>
                {tools?.warning && (
                  <div className="mb-4 rounded-md border bg-muted/40 p-3 text-sm text-text-muted">
                    {tools.warning}
                  </div>
                )}
                {filteredTools.length > 0 ? (
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    {filteredTools.map((tool) => {
                      const status = toolsStatus?.tools.find((item) => item.name === tool.name);
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
                            <Button
                              size="sm"
                              variant={isEnabled ? 'secondary' : 'primary'}
                              onClick={() => handleToggleTool(tool.name, isEnabled)}
                              disabled={toggling === tool.name}
                            >
                              {toggling === tool.name ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              ) : isEnabled ? (
                                <PowerOff className="h-3 w-3" />
                              ) : (
                                <Power className="h-3 w-3" />
                              )}
                              {isEnabled ? 'Disable' : 'Enable'}
                            </Button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="flex min-h-[220px] flex-col items-center justify-center rounded-md border border-dashed p-6 text-center">
                    {discoveryRequired ? (
                      <AlertCircle className="h-8 w-8 text-text-muted" />
                    ) : (
                      <Terminal className="h-8 w-8 text-text-muted" />
                    )}
                    <h3 className="mt-3 text-sm font-medium text-text-primary">
                      {discoveryRequired ? 'Tool discovery is required' : 'No tools found'}
                    </h3>
                    <p className="mt-1 max-w-md text-sm text-text-muted">
                      {workspaceConfigured
                        ? 'Refresh the active workspace inventory after saving and applying MCP configuration.'
                        : 'Configure and apply an MCP server for this workspace before tools can appear here.'}
                    </p>
                    <Button className="mt-4" size="sm" onClick={() => fetchData({ refresh: true })} loading={refreshing}>
                      <Zap className="h-4 w-4" />
                      Discover tools
                    </Button>
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

export default function ToolsPage() {
  return (
    <ToastProvider>
      <ToolsContent />
    </ToastProvider>
  );
}
