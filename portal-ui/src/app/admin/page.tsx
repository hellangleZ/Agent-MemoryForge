'use client';

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import {
  AdminUsageItem,
  getAdminQuotas,
  getAdminUsage,
  getAdminUsers,
  getWorkspaces,
} from '@/lib/api';
import {
  Activity,
  ArrowRight,
  Folder,
  Gauge,
  KeyRound,
  Loader2,
  Users,
  Wrench,
} from 'lucide-react';

interface OverviewState {
  users: number;
  admins: number;
  workspaces: number;
  quotaRules: number;
  usageRows: AdminUsageItem[];
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(value);
}

function AdminOverviewContent() {
  const { addToast } = useToast();
  const [loading, setLoading] = useState(true);
  const [state, setState] = useState<OverviewState>({
    users: 0,
    admins: 0,
    workspaces: 0,
    quotaRules: 0,
    usageRows: [],
  });

  const loadOverview = useCallback(async () => {
    setLoading(true);
    try {
      const [usersRes, workspacesRes, usageRes, quotaRes] = await Promise.all([
        getAdminUsers(),
        getWorkspaces(),
        getAdminUsage(),
        getAdminQuotas(),
      ]);
      const users = usersRes.users || [];
      setState({
        users: users.length,
        admins: users.filter((user) => user.role === 'admin').length,
        workspaces: workspacesRes.total || workspacesRes.workspaces?.length || 0,
        quotaRules: quotaRes.data?.total || quotaRes.data?.items?.length || 0,
        usageRows: usageRes.data?.items || [],
      });
    } catch {
      addToast('Failed to load admin overview', 'error');
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  const totals = useMemo(() => {
    return state.usageRows.reduce(
      (acc, row) => {
        acc.requests += row.request_count || 0;
        acc.tokens += row.total_tokens || 0;
        if (row.blocked) acc.blocked += 1;
        return acc;
      },
      { requests: 0, tokens: 0, blocked: 0 }
    );
  }, [state.usageRows]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3 text-text-muted">
          <Loader2 className="h-8 w-8 animate-spin" />
          <p className="text-sm">Loading overview</p>
        </div>
      </div>
    );
  }

  const stats = [
    { label: 'Users', value: state.users, detail: `${state.admins} admin`, icon: Users },
    { label: 'Workspaces', value: state.workspaces, detail: 'tenant scoped', icon: Folder },
    { label: 'Requests', value: totals.requests, detail: `${formatNumber(totals.tokens)} tokens`, icon: Activity },
    { label: 'Quota rules', value: state.quotaRules, detail: `${totals.blocked} blocked rows`, icon: Gauge },
  ];

  const links = [
    { href: '/admin/users', label: 'Manage users', icon: Users },
    { href: '/admin/tools', label: 'Configure tools', icon: Wrench },
    { href: '/admin/workspaces', label: 'Review workspaces', icon: Folder },
    { href: '/admin/monitoring', label: 'Usage and quota', icon: KeyRound },
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
                <div>
                  <h1 className="text-2xl font-semibold text-text-primary">Admin Overview</h1>
                  <p className="text-sm text-text-muted">Tenant operations, accounts, and usage controls</p>
                </div>
                <Button variant="secondary" onClick={loadOverview}>
                  Refresh
                </Button>
              </div>
            </Card>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
              {stats.map((stat) => (
                <Card key={stat.label} className="p-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-md bg-muted text-text-primary">
                      <stat.icon className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="text-2xl font-semibold text-text-primary">{formatNumber(stat.value)}</p>
                      <p className="text-xs text-text-muted">{stat.label}</p>
                    </div>
                  </div>
                  <p className="mt-3 text-xs text-text-muted">{stat.detail}</p>
                </Card>
              ))}
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {links.map((link) => (
                <Link key={link.href} href={link.href}>
                  <Card className="p-4 transition-colors hover:bg-muted/40">
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex items-center gap-3">
                        <div className="flex h-10 w-10 items-center justify-center rounded-md bg-muted text-text-primary">
                          <link.icon className="h-5 w-5" />
                        </div>
                        <p className="font-medium text-text-primary">{link.label}</p>
                      </div>
                      <ArrowRight className="h-4 w-4 text-text-muted" />
                    </div>
                  </Card>
                </Link>
              ))}
            </div>

            <Card>
              <div className="border-b p-5">
                <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                  <div>
                    <h2 className="text-lg font-semibold text-text-primary">Current Usage</h2>
                    <p className="text-sm text-text-muted">Rows returned by the admin usage API</p>
                  </div>
                  <Badge variant={totals.blocked ? 'warning' : 'default'}>{totals.blocked} blocked</Badge>
                </div>
              </div>
              <CardContent>
                {state.usageRows.length === 0 ? (
                  <div className="flex min-h-[160px] items-center justify-center rounded-md border border-dashed text-sm text-text-muted">
                    No usage recorded
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[720px] text-sm">
                      <thead>
                        <tr className="border-b text-left text-xs uppercase text-text-muted">
                          <th className="py-3 pr-4 font-medium">Workspace</th>
                          <th className="py-3 pr-4 font-medium">User</th>
                          <th className="py-3 pr-4 font-medium">Requests</th>
                          <th className="py-3 pr-4 font-medium">Tokens</th>
                          <th className="py-3 pr-4 font-medium">Quota</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y">
                        {state.usageRows.slice(0, 8).map((row) => (
                          <tr key={`${row.workspace_id}:${row.user_id}:${row.month}`} className="hover:bg-muted/30">
                            <td className="py-3 pr-4 font-mono text-xs text-text-muted">{row.workspace_id}</td>
                            <td className="py-3 pr-4 text-text-primary">{row.user_id}</td>
                            <td className="py-3 pr-4 text-text-muted">{formatNumber(row.request_count)}</td>
                            <td className="py-3 pr-4 text-text-muted">{formatNumber(row.total_tokens)}</td>
                            <td className="py-3 pr-4">
                              <Badge variant={row.blocked ? 'warning' : 'default'}>
                                {row.monthly_token_quota == null ? 'none' : formatNumber(row.monthly_token_quota)}
                              </Badge>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
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

export default function AdminOverviewPage() {
  return (
    <ToastProvider>
      <AdminOverviewContent />
    </ToastProvider>
  );
}
