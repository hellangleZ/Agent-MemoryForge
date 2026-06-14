'use client';

import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  BarChart3,
  Download,
  Gauge,
  Loader2,
  RefreshCw,
  Save,
  Search,
  ShieldAlert,
} from 'lucide-react';
import { Sidebar } from '@/components/Sidebar';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader } from '@/components/ui/Card';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import { cn } from '@/lib/utils';
import {
  AdminUsageItem,
  AuditEntry,
  MonitoringMetric,
  exportMonitoringAudit,
  exportMonitoringMetrics,
  getAdminUsage,
  getMonitoringAudit,
  getMonitoringMetrics,
  getWorkspace,
  setAdminQuota,
} from '@/lib/api';

type MetricType = 'cpu' | 'memory' | 'storage';
type TimeRange = '1h' | '24h' | '7d';

interface MetricsState {
  cpu: MonitoringMetric[];
  memory: MonitoringMetric[];
  storage: MonitoringMetric[];
}

function currentMonth(): string {
  return new Date().toISOString().slice(0, 7);
}

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  return new Intl.NumberFormat().format(value);
}

function averageMetric(items: MonitoringMetric[]): number {
  if (!items.length) return 0;
  return items.reduce((sum, item) => sum + item.value, 0) / items.length;
}

function usageBadge(row: AdminUsageItem) {
  if (!row.quota_enabled || row.monthly_token_quota === null) {
    return <Badge>Uncapped</Badge>;
  }
  if (row.blocked) {
    return <Badge variant="danger">Blocked</Badge>;
  }
  return <Badge variant="success">Active</Badge>;
}

function downloadCsv(content: string, filename: string) {
  const blob = new Blob([content], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function MonitoringContent() {
  const { addToast } = useToast();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRange>('24h');
  const [workspaceFilter, setWorkspaceFilter] = useState(getWorkspace());
  const [userFilter, setUserFilter] = useState('');
  const [month, setMonth] = useState(currentMonth());
  const [usage, setUsage] = useState<AdminUsageItem[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditEntry[]>([]);
  const [metrics, setMetrics] = useState<MetricsState>({
    cpu: [],
    memory: [],
    storage: [],
  });
  const [quotaForm, setQuotaForm] = useState({
    workspace_id: getWorkspace(),
    user_id: '',
    monthly_token_quota: '100000',
    enabled: true,
  });

  const loadData = useCallback(async () => {
    setError(null);
    const results = await Promise.allSettled([
      getMonitoringMetrics('cpu', timeRange),
      getMonitoringMetrics('memory', timeRange),
      getMonitoringMetrics('storage', timeRange),
      getMonitoringAudit(1, 20),
      getAdminUsage({
        workspace_id: workspaceFilter || undefined,
        user_id: userFilter || undefined,
        month,
      }),
    ]);

    const nextErrors: string[] = [];
    const [cpuRes, memoryRes, storageRes, auditRes, usageRes] = results;

    if (cpuRes.status === 'fulfilled') {
      setMetrics(prev => ({ ...prev, cpu: cpuRes.value.metrics || [] }));
    } else {
      nextErrors.push('CPU metrics unavailable');
      setMetrics(prev => ({ ...prev, cpu: [] }));
    }

    if (memoryRes.status === 'fulfilled') {
      setMetrics(prev => ({ ...prev, memory: memoryRes.value.metrics || [] }));
    } else {
      nextErrors.push('Memory metrics unavailable');
      setMetrics(prev => ({ ...prev, memory: [] }));
    }

    if (storageRes.status === 'fulfilled') {
      setMetrics(prev => ({ ...prev, storage: storageRes.value.metrics || [] }));
    } else {
      nextErrors.push('Storage metrics unavailable');
      setMetrics(prev => ({ ...prev, storage: [] }));
    }

    if (auditRes.status === 'fulfilled') {
      setAuditLogs(auditRes.value.audits || []);
    } else {
      nextErrors.push('Audit logs unavailable');
      setAuditLogs([]);
    }

    if (usageRes.status === 'fulfilled') {
      setUsage(usageRes.value.data.items || []);
    } else {
      nextErrors.push('Usage ledger unavailable');
      setUsage([]);
    }

    setError(nextErrors.length ? nextErrors.join('. ') : null);
  }, [month, timeRange, userFilter, workspaceFilter]);

  useEffect(() => {
    let cancelled = false;
    async function init() {
      setLoading(true);
      await loadData();
      if (!cancelled) setLoading(false);
    }
    init();
    return () => {
      cancelled = true;
    };
  }, [loadData]);

  const totals = useMemo(() => {
    return usage.reduce(
      (acc, row) => {
        acc.requests += row.request_count;
        acc.tokens += row.total_tokens;
        acc.blocked += row.blocked ? 1 : 0;
        acc.capped += row.quota_enabled ? 1 : 0;
        return acc;
      },
      { requests: 0, tokens: 0, blocked: 0, capped: 0 }
    );
  }, [usage]);

  const refresh = async () => {
    setRefreshing(true);
    await loadData();
    setRefreshing(false);
    addToast('Operations data refreshed', 'success');
  };

  const submitQuota = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const quota = Number(quotaForm.monthly_token_quota);
    if (!quotaForm.workspace_id.trim() || !quotaForm.user_id.trim() || !Number.isFinite(quota) || quota < 0) {
      addToast('Quota form is incomplete', 'error');
      return;
    }

    await setAdminQuota({
      workspace_id: quotaForm.workspace_id.trim(),
      user_id: quotaForm.user_id.trim(),
      monthly_token_quota: Math.floor(quota),
      enabled: quotaForm.enabled,
    });
    addToast('Quota saved', 'success');
    await loadData();
  };

  const exportMetrics = async () => {
    const types: MetricType[] = ['cpu', 'memory', 'storage'];
    for (const type of types) {
      const csv = await exportMonitoringMetrics(type, timeRange);
      downloadCsv(csv, `metrics_${type}_${timeRange}.csv`);
    }
    addToast('Metrics export ready', 'success');
  };

  const exportAudit = async () => {
    const csv = await exportMonitoringAudit();
    downloadCsv(csv, `audit_${timeRange}.csv`);
    addToast('Audit export ready', 'success');
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex items-center gap-3 text-text-muted">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span className="text-sm">Loading operations data...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background text-text-primary">
      <div className="container mx-auto px-4 py-8">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
          <div className="lg:col-span-1">
            <Sidebar variant="admin" />
          </div>

          <main className="space-y-6 lg:col-span-3">
            <Card>
              <CardContent className="p-5">
                <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-11 w-11 items-center justify-center rounded-lg border bg-muted text-text-primary">
                      <Gauge className="h-5 w-5" />
                    </div>
                    <div>
                      <h1 className="text-xl font-semibold">Operations Control</h1>
                      <p className="mt-1 text-sm text-text-muted">
                        Tenant usage, employee quota, system metrics, and audit events.
                      </p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {(['1h', '24h', '7d'] as TimeRange[]).map(range => (
                      <button
                        key={range}
                        onClick={() => setTimeRange(range)}
                        className={cn(
                          'h-9 rounded-md border px-3 text-sm transition-colors',
                          timeRange === range
                            ? 'bg-foreground text-background'
                            : 'bg-card text-text-secondary hover:bg-muted hover:text-text-primary'
                        )}
                      >
                        {range}
                      </button>
                    ))}
                    <Button variant="secondary" onClick={refresh} disabled={refreshing}>
                      <RefreshCw className={cn('h-4 w-4', refreshing && 'animate-spin')} />
                      Refresh
                    </Button>
                    <Button variant="ghost" onClick={exportMetrics}>
                      <Download className="h-4 w-4" />
                      Metrics
                    </Button>
                    <Button variant="ghost" onClick={exportAudit}>
                      <Download className="h-4 w-4" />
                      Audit
                    </Button>
                  </div>
                </div>
                {error && (
                  <div className="mt-4 flex items-start gap-2 rounded-md border bg-muted/40 p-3 text-sm text-text-secondary">
                    <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                )}
              </CardContent>
            </Card>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-text-muted">Requests</span>
                    <Activity className="h-4 w-4 text-text-muted" />
                  </div>
                  <p className="mt-3 text-2xl font-semibold">{formatNumber(totals.requests)}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-text-muted">Tokens</span>
                    <BarChart3 className="h-4 w-4 text-text-muted" />
                  </div>
                  <p className="mt-3 text-2xl font-semibold">{formatNumber(totals.tokens)}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-text-muted">Blocked Users</span>
                    <ShieldAlert className="h-4 w-4 text-text-muted" />
                  </div>
                  <p className="mt-3 text-2xl font-semibold">{formatNumber(totals.blocked)}</p>
                </CardContent>
              </Card>
              <Card>
                <CardContent className="p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-text-muted">Quota Rules</span>
                    <Gauge className="h-4 w-4 text-text-muted" />
                  </div>
                  <p className="mt-3 text-2xl font-semibold">{formatNumber(totals.capped)}</p>
                </CardContent>
              </Card>
            </div>

            <Card>
              <CardHeader title="Usage & Quotas" description={`Monthly ledger for ${month}`} />
              <CardContent>
                <div className="mb-5 grid grid-cols-1 gap-3 md:grid-cols-4">
                  <label className="space-y-1.5">
                    <span className="text-xs font-medium text-text-muted">Workspace</span>
                    <input
                      value={workspaceFilter}
                      onChange={event => setWorkspaceFilter(event.target.value)}
                      className="h-9 w-full rounded-md border bg-card px-3 text-sm"
                    />
                  </label>
                  <label className="space-y-1.5">
                    <span className="text-xs font-medium text-text-muted">User</span>
                    <input
                      value={userFilter}
                      onChange={event => setUserFilter(event.target.value)}
                      placeholder="optional"
                      className="h-9 w-full rounded-md border bg-card px-3 text-sm"
                    />
                  </label>
                  <label className="space-y-1.5">
                    <span className="text-xs font-medium text-text-muted">Month</span>
                    <input
                      type="month"
                      value={month}
                      onChange={event => setMonth(event.target.value)}
                      className="h-9 w-full rounded-md border bg-card px-3 text-sm"
                    />
                  </label>
                  <div className="flex items-end">
                    <Button variant="secondary" onClick={refresh} className="w-full">
                      <Search className="h-4 w-4" />
                      Apply
                    </Button>
                  </div>
                </div>

                <div className="overflow-x-auto rounded-lg border">
                  <table className="w-full min-w-[820px] text-sm">
                    <thead className="bg-muted/50 text-left text-xs uppercase text-text-muted">
                      <tr>
                        <th className="px-3 py-2">User</th>
                        <th className="px-3 py-2">Workspace</th>
                        <th className="px-3 py-2 text-right">Requests</th>
                        <th className="px-3 py-2 text-right">Input</th>
                        <th className="px-3 py-2 text-right">Output</th>
                        <th className="px-3 py-2 text-right">Total</th>
                        <th className="px-3 py-2 text-right">Quota</th>
                        <th className="px-3 py-2 text-right">Remaining</th>
                        <th className="px-3 py-2">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {usage.length === 0 ? (
                        <tr>
                          <td className="px-3 py-8 text-center text-text-muted" colSpan={9}>
                            No usage events or quota rules found.
                          </td>
                        </tr>
                      ) : (
                        usage.map(row => (
                          <tr
                            key={`${row.workspace_id}:${row.user_id}`}
                            className="hover:bg-muted/30"
                            onClick={() =>
                              setQuotaForm({
                                workspace_id: row.workspace_id,
                                user_id: row.user_id,
                                monthly_token_quota: String(row.monthly_token_quota ?? 100000),
                                enabled: row.quota_enabled,
                              })
                            }
                          >
                            <td className="px-3 py-3 font-medium">{row.user_id}</td>
                            <td className="px-3 py-3 font-mono text-xs text-text-secondary">{row.workspace_id}</td>
                            <td className="px-3 py-3 text-right">{formatNumber(row.request_count)}</td>
                            <td className="px-3 py-3 text-right">{formatNumber(row.input_tokens)}</td>
                            <td className="px-3 py-3 text-right">{formatNumber(row.output_tokens)}</td>
                            <td className="px-3 py-3 text-right font-medium">{formatNumber(row.total_tokens)}</td>
                            <td className="px-3 py-3 text-right">{formatNumber(row.monthly_token_quota)}</td>
                            <td className="px-3 py-3 text-right">{formatNumber(row.remaining_tokens)}</td>
                            <td className="px-3 py-3">{usageBadge(row)}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader title="Set User Quota" description="Quota applies to one user in one workspace for the current tenant." />
              <CardContent>
                <form onSubmit={submitQuota} className="grid grid-cols-1 gap-3 md:grid-cols-5">
                  <label className="space-y-1.5">
                    <span className="text-xs font-medium text-text-muted">Workspace</span>
                    <input
                      value={quotaForm.workspace_id}
                      onChange={event => setQuotaForm(prev => ({ ...prev, workspace_id: event.target.value }))}
                      className="h-9 w-full rounded-md border bg-card px-3 text-sm"
                    />
                  </label>
                  <label className="space-y-1.5">
                    <span className="text-xs font-medium text-text-muted">User</span>
                    <input
                      value={quotaForm.user_id}
                      onChange={event => setQuotaForm(prev => ({ ...prev, user_id: event.target.value }))}
                      className="h-9 w-full rounded-md border bg-card px-3 text-sm"
                    />
                  </label>
                  <label className="space-y-1.5">
                    <span className="text-xs font-medium text-text-muted">Monthly Tokens</span>
                    <input
                      type="number"
                      min="0"
                      value={quotaForm.monthly_token_quota}
                      onChange={event => setQuotaForm(prev => ({ ...prev, monthly_token_quota: event.target.value }))}
                      className="h-9 w-full rounded-md border bg-card px-3 text-sm"
                    />
                  </label>
                  <label className="flex items-end gap-2 pb-2 text-sm text-text-secondary">
                    <input
                      type="checkbox"
                      checked={quotaForm.enabled}
                      onChange={event => setQuotaForm(prev => ({ ...prev, enabled: event.target.checked }))}
                      className="h-4 w-4"
                    />
                    Enabled
                  </label>
                  <div className="flex items-end">
                    <Button type="submit" className="w-full">
                      <Save className="h-4 w-4" />
                      Save
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              {(['cpu', 'memory', 'storage'] as MetricType[]).map(type => (
                <Card key={type}>
                  <CardContent className="p-4">
                    <div className="flex items-center justify-between">
                      <span className="capitalize text-sm text-text-muted">{type}</span>
                      <Badge>{metrics[type].length} points</Badge>
                    </div>
                    <p className="mt-3 text-2xl font-semibold">
                      {averageMetric(metrics[type]).toFixed(1)}
                      <span className="ml-1 text-sm font-normal text-text-muted">
                        {type === 'memory' ? 'MB avg' : '% avg'}
                      </span>
                    </p>
                    <div className="mt-4 flex h-16 items-end gap-1">
                      {metrics[type].slice(-24).map((item, index) => (
                        <div
                          key={`${item.timestamp}:${index}`}
                          className="flex-1 rounded-t bg-foreground/70"
                          style={{ height: `${Math.max(4, Math.min(100, item.value))}%` }}
                          title={`${item.value.toFixed(1)} at ${item.timestamp}`}
                        />
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>

            <Card>
              <CardHeader title="Audit Logs" description={`${auditLogs.length} recent entries`} />
              <CardContent>
                <div className="overflow-x-auto rounded-lg border">
                  <table className="w-full min-w-[760px] text-sm">
                    <thead className="bg-muted/50 text-left text-xs uppercase text-text-muted">
                      <tr>
                        <th className="px-3 py-2">Time</th>
                        <th className="px-3 py-2">User</th>
                        <th className="px-3 py-2">Action</th>
                        <th className="px-3 py-2">Resource</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y">
                      {auditLogs.length === 0 ? (
                        <tr>
                          <td className="px-3 py-8 text-center text-text-muted" colSpan={4}>
                            No audit logs found.
                          </td>
                        </tr>
                      ) : (
                        auditLogs.map(entry => (
                          <tr key={entry.id} className="hover:bg-muted/30">
                            <td className="px-3 py-3 text-text-secondary">{new Date(entry.timestamp).toLocaleString()}</td>
                            <td className="px-3 py-3 font-mono text-xs">{entry.user_id}</td>
                            <td className="px-3 py-3"><Badge>{entry.action}</Badge></td>
                            <td className="px-3 py-3 font-mono text-xs text-text-secondary">{entry.resource}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          </main>
        </div>
      </div>
    </div>
  );
}

export default function AdminMonitoringPage() {
  return (
    <ToastProvider>
      <MonitoringContent />
    </ToastProvider>
  );
}
