'use client';

import { useCallback, useEffect, useState } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { Card, CardHeader, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge, StatusDot } from '@/components/ui/Badge';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import { clearToken, getWorkspace, getWorkspaceConfig, getMe, hasToken, isAuthError, getMemoryStats, getToolsStatus, getAgents, MemoryStats, ToolsStatusResponse } from '@/lib/api';
import { useTheme } from '@/lib/theme';
import { logError } from '@/lib/errorTracking';
import { motion } from 'framer-motion';
import Link from 'next/link';
import { cn } from '@/lib/utils';
import {
  Shield,
  Settings,
  Activity,
  Clock,
  ArrowRight,
  Loader2,
  Zap,
  Database,
  Brain,
  RotateCcw
} from 'lucide-react';

interface WorkspaceInfo {
  workspace_id?: string;
  name?: string;
  created_at?: string;
  system_prompt?: string;
  mcp?: Record<string, unknown>;
  mcp_secrets?: Record<string, boolean>;
}

interface UserInfo {
  id: string;
  email: string;
  role: string;
  created_at: string;
}

interface ActivityItem {
  action: string;
  time: string;
  type: 'success' | 'info' | 'default' | 'warning';
}

const DEFAULT_WORKSPACE_ID = 'ws_default';

function WorkspaceContent() {
  const { addToast } = useToast();
  const { isDark } = useTheme();
  const [workspace, setWorkspace] = useState<WorkspaceInfo | null>(null);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null);
  const [toolsStatus, setToolsStatus] = useState<ToolsStatusResponse | null>(null);
  const [workspaceAgentsCount, setWorkspaceAgentsCount] = useState<number | null>(null);
  const [systemAgentsCount, setSystemAgentsCount] = useState<number | null>(null);
  const [recentActivity, setRecentActivity] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [workspaceId, setWorkspaceId] = useState(DEFAULT_WORKSPACE_ID);
  const [authenticated, setAuthenticated] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const currentWorkspaceId = getWorkspace();
      const markerPresent = hasToken();
      let sessionValid = false;
      let sessionExpired = false;
      let userData: UserInfo | null = null;

      setWorkspaceId(currentWorkspaceId);

      if (markerPresent) {
        try {
          userData = await getMe() as UserInfo;
          sessionValid = true;
        } catch (err) {
          if (isAuthError(err)) {
            clearToken();
            sessionExpired = true;
          } else {
            const error = err instanceof Error ? err : new Error('Failed to verify session');
            logError(error, { component: 'WorkspacePage', action: 'verifySession' });
          }
        }
      }

      setAuthenticated(sessionValid);
      setUser(userData);

      let configData: any = { data: { id: currentWorkspaceId } };
      let memStats: any = null;
      let toolStatus: ToolsStatusResponse | null = null;
      let agents: any = null;

      if (sessionValid) {
        [configData, memStats, toolStatus, agents] = await Promise.all([
          getWorkspaceConfig().catch(() => ({ data: { id: currentWorkspaceId } })),
          getMemoryStats().catch(() => null),
          getToolsStatus().catch(() => null),
          getAgents().catch(() => null),
        ]);
      }

      setWorkspace(configData.data as WorkspaceInfo);

      const statsData = (memStats as any)?.data || null;
      setMemoryStats(statsData as MemoryStats);
      setToolsStatus(toolStatus as ToolsStatusResponse);

      const agentsMap = (agents as any)?.agents;
      if (agentsMap && typeof agentsMap === 'object') {
        const entries = Object.values(agentsMap) as any[];
        const systemCount = entries.filter((a) => a && a.custom === false).length;
        const wsCount = entries.filter((a) => {
          if (!a || a.custom !== true) return false;
          const ws = (a.workspace_id || '').trim();
          return !ws || ws === currentWorkspaceId;
        }).length;
        setSystemAgentsCount(systemCount);
        setWorkspaceAgentsCount(wsCount);
      } else {
        setSystemAgentsCount(null);
        setWorkspaceAgentsCount(null);
      }

      const now = new Date();
      const activity: ActivityItem[] = [];
      activity.push({ action: sessionValid ? 'Workspace config loaded' : 'Workspace selected', time: now.toLocaleTimeString(), type: 'info' });
      if (sessionValid) activity.push({ action: 'Authenticated session', time: now.toLocaleTimeString(), type: 'success' });
      if (!sessionValid && sessionExpired) activity.push({ action: 'Session expired', time: now.toLocaleTimeString(), type: 'warning' });
      if (!sessionValid && !sessionExpired) activity.push({ action: 'Sign in required', time: now.toLocaleTimeString(), type: 'warning' });
      if (statsData) activity.push({ action: 'Memory stats loaded', time: now.toLocaleTimeString(), type: 'success' });
      if (toolStatus) activity.push({ action: 'Tools status loaded', time: now.toLocaleTimeString(), type: 'success' });
      if (agentsMap) activity.push({ action: 'Agents list loaded', time: now.toLocaleTimeString(), type: 'success' });
      setRecentActivity(activity.slice(0, 6));
    } catch (err: unknown) {
      const error = err instanceof Error ? err : new Error('Failed to fetch workspace data');
      logError(error, { component: 'WorkspacePage', action: 'fetchData' });
      addToast('Failed to fetch workspace data', 'error');
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const enabledTools = toolsStatus?.tools?.filter(t => t.enabled)?.length ?? null;
  const totalMemoryItems = memoryStats
    ? (memoryStats.stm?.count || 0) +
      (memoryStats.wm?.count || 0) +
      (memoryStats.ltm?.count || 0)
    : null;
  const indexStatus = memoryStats?.file_first?.index
    ? memoryStats.file_first.index.stale
      ? 'Stale'
      : 'Fresh'
    : '—';

  const stats = [
    { label: 'Memory Items', value: totalMemoryItems === null ? '—' : String(totalMemoryItems), icon: Database, color: 'neutral' },
    { label: 'Active Tools', value: enabledTools === null ? '—' : String(enabledTools), icon: Zap, color: 'neutral' },
    {
      label: 'Agents (WS/System)',
      value:
        workspaceAgentsCount === null || systemAgentsCount === null
          ? '—'
          : `${workspaceAgentsCount}/${systemAgentsCount}`,
      icon: Brain,
      color: 'neutral',
    },
    { label: 'Index Status', value: indexStatus, icon: Activity, color: 'neutral' },
  ];

  const statColors: Record<string, { bg: string; icon: string }> = {
    neutral: {
      bg: 'bg-muted',
      icon: 'text-text-primary',
    },
  };

  return (
    <div className={cn(
      "min-h-screen bg-background transition-colors duration-300"
    )}>
      <div className="container mx-auto px-4 py-8 relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Sidebar */}
          <div className="lg:col-span-1">
            <Sidebar variant="customer" />
          </div>

          {/* Main Content */}
          <div className="lg:col-span-3 space-y-6">
            {/* Header */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
            >
              <Card className="p-6">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                  <div className="flex items-center gap-4">
                    <div className="flex h-12 w-12 items-center justify-center rounded-md border bg-muted text-text-primary">
                      <Shield className="w-7 h-7" />
                    </div>
                    <div>
                      <h1 className={cn(
                        "text-2xl font-bold transition-colors duration-300",
                        isDark ? "text-white" : "text-slate-900"
                      )}>
                        Workspace: <span>{workspace?.workspace_id || workspaceId}</span>
                      </h1>
                      <p className={cn(
                        "transition-colors duration-300",
                        isDark ? "text-slate-400" : "text-slate-600"
                      )}>
                        Your personal AI workspace configuration
                      </p>
                    </div>
	                  </div>
	                  <div className="flex items-center gap-3">
	                    <div className={cn(
	                      "flex items-center gap-3 px-4 py-2 rounded-xl border transition-colors duration-300",
	                      isDark ? "bg-white/5 border-white/10" : "bg-white/80 border-slate-200"
	                    )}>
	                      <StatusDot status={authenticated ? 'online' : 'offline'} />
	                      <span className={cn(
	                        "text-sm transition-colors duration-300",
	                        isDark ? "text-slate-400" : "text-slate-600"
	                      )}>
	                        {authenticated ? 'Authenticated' : 'Not authenticated'}
	                      </span>
	                    </div>
	                    <Button
	                      size="sm"
	                      variant="secondary"
	                      onClick={async () => {
	                        setRefreshing(true);
	                        await fetchData();
	                        setRefreshing(false);
	                      }}
	                      disabled={refreshing}
	                    >
	                      {refreshing ? <Loader2 className="w-4 h-4 animate-spin" /> : <RotateCcw className="w-4 h-4" />}
	                      Refresh
	                    </Button>
	                  </div>
	                </div>
	              </Card>
	            </motion.div>

            {/* Stats Grid */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
            >
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {stats.map((stat) => {
                  const colors = statColors[stat.color];
                  return (
                    <Card key={stat.label} className="p-4">
                      <div className="flex items-center gap-3">
                        <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", colors.bg)}>
                          <stat.icon className={cn("w-5 h-5", colors.icon)} />
                        </div>
                        <div>
                          <p className={cn(
                            "text-2xl font-bold transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>{stat.value}</p>
                          <p className={cn(
                            "text-xs transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>{stat.label}</p>
                        </div>
                      </div>
                    </Card>
                  );
                })}
              </div>
            </motion.div>

            {/* Main Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Workspace Config */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.2 }}
              >
                <Card className="h-full">
                  <CardHeader
                    title="Workspace Configuration"
                    description="Current workspace settings"
                    action={
                      <Link href="/config">
                        <Button size="sm" variant="ghost">
                          <Settings className="w-4 h-4" />
                          Edit
                        </Button>
                      </Link>
                    }
                  />
                  <CardContent>
                    {loading ? (
                      <div className="flex items-center justify-center py-8">
                        <Loader2 className={cn(
                          "w-6 h-6 animate-spin",
                          isDark ? "text-slate-500" : "text-slate-400"
                        )} />
                      </div>
                    ) : (
                      <div className="space-y-4">
                        <div className={cn(
                          "p-4 rounded-xl border transition-colors duration-300",
                          isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"
                        )}>
                          <p className={cn(
                            "text-xs mb-1 transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>Workspace ID</p>
                          <p className={cn(
                            "font-mono text-sm transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>{workspace?.workspace_id || workspaceId}</p>
                        </div>
                        <div className={cn(
                          "p-4 rounded-xl border transition-colors duration-300",
                          isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"
                        )}>
                          <p className={cn(
                            "text-xs mb-1 transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>System Prompt</p>
                          <p className={cn(
                            "text-sm line-clamp-2 transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>
                            {workspace?.system_prompt || 'Not configured'}
                          </p>
                        </div>
                        <div className={cn(
                          "p-4 rounded-xl border transition-colors duration-300",
                          isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"
                        )}>
                          <p className={cn(
                            "text-xs mb-1 transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>MCP Configuration</p>
                          <p className={cn(
                            "text-sm transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>
                            {workspace?.mcp && Object.keys(workspace.mcp).length > 0 ? 'Configured' : 'Not configured'}
                          </p>
                        </div>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </motion.div>

              {/* Recent Activity */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.3 }}
              >
                <Card className="h-full">
                  <CardHeader
                    title="Recent Activity"
                    description="Latest page checks"
                  />
                  <CardContent>
                    <div className="space-y-3">
                      {recentActivity.map((activity, index) => (
                        <div
                          key={index}
                          className={cn(
                            "flex items-center gap-3 p-3 rounded-xl border transition-colors duration-300",
                            isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"
                          )}
                        >
                          <div className={cn(
                            "w-2 h-2 rounded-full",
                            activity.type === 'success' ? 'bg-slate-700' :
                            activity.type === 'info' ? 'bg-slate-500' :
                            activity.type === 'warning' ? 'bg-slate-600' :
                            isDark ? 'bg-slate-500' : 'bg-slate-400'
                          )} />
                          <div className="flex-1 min-w-0">
                            <p className={cn(
                              "text-sm truncate transition-colors duration-300",
                              isDark ? "text-white" : "text-slate-900"
                            )}>{activity.action}</p>
                          </div>
                          <div className={cn(
                            "flex items-center gap-1 text-xs transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>
                            <Clock className="w-3 h-3" />
                            {activity.time}
                          </div>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            </div>

            {/* Quick Actions */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.4 }}
            >
              <Card>
                <CardHeader
                  title="Quick Actions"
                  description="Common workspace tasks"
                />
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <Link href="/config">
                    <div className={cn(
                      "group p-4 rounded-xl border transition-all duration-300 cursor-pointer",
                      isDark
                        ? "bg-white/5 border-white/10 hover:bg-white/10 hover:border-white/20"
                        : "bg-white/80 border-slate-200 hover:bg-white hover:border-slate-300"
                    )}>
                      <div className="flex items-center gap-3">
                        <div className={cn(
                          "w-10 h-10 rounded-xl flex items-center justify-center group-hover:scale-110 transition-transform",
                          "bg-muted text-text-primary"
                        )}>
                          <Settings className="w-5 h-5" />
                        </div>
                        <div>
                          <h3 className={cn(
                            "font-medium transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>Configure</h3>
                          <p className={cn(
                            "text-xs transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>Edit workspace settings</p>
                        </div>
                        <ArrowRight className={cn(
                          "w-4 h-4 ml-auto transition-colors",
                          isDark ? "text-slate-500 group-hover:text-white" : "text-slate-400 group-hover:text-slate-900"
                        )} />
                      </div>
                    </div>
                  </Link>
                  <Link href="/tools">
                    <div className={cn(
                      "group p-4 rounded-xl border transition-all duration-300 cursor-pointer",
                      isDark
                        ? "bg-white/5 border-white/10 hover:bg-white/10 hover:border-white/20"
                        : "bg-white/80 border-slate-200 hover:bg-white hover:border-slate-300"
                    )}>
                      <div className="flex items-center gap-3">
                        <div className={cn(
                          "w-10 h-10 rounded-xl flex items-center justify-center group-hover:scale-110 transition-transform",
                          "bg-muted text-text-primary"
                        )}>
                          <Zap className="w-5 h-5" />
                        </div>
                        <div>
                          <h3 className={cn(
                            "font-medium transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>Tools</h3>
                          <p className={cn(
                            "text-xs transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>Manage MCP tools</p>
                        </div>
                        <ArrowRight className={cn(
                          "w-4 h-4 ml-auto transition-colors",
                          isDark ? "text-slate-500 group-hover:text-white" : "text-slate-400 group-hover:text-slate-900"
                        )} />
                      </div>
                    </div>
                  </Link>
                  <Link href="/chat/code-assistant">
                    <div className={cn(
                      "group p-4 rounded-xl border transition-all duration-300 cursor-pointer",
                      isDark
                        ? "bg-white/5 border-white/10 hover:bg-white/10 hover:border-white/20"
                        : "bg-white/80 border-slate-200 hover:bg-white hover:border-slate-300"
                    )}>
                      <div className="flex items-center gap-3">
                        <div className={cn(
                          "w-10 h-10 rounded-xl flex items-center justify-center group-hover:scale-110 transition-transform",
                          "bg-muted text-text-primary"
                        )}>
                          <Brain className="w-5 h-5" />
                        </div>
                        <div>
                          <h3 className={cn(
                            "font-medium transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>Chat</h3>
                          <p className={cn(
                            "text-xs transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>Start a conversation</p>
                        </div>
                        <ArrowRight className={cn(
                          "w-4 h-4 ml-auto transition-colors",
                          isDark ? "text-slate-500 group-hover:text-white" : "text-slate-400 group-hover:text-slate-900"
                        )} />
                      </div>
                    </div>
                  </Link>
                </div>
              </Card>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function WorkspacePage() {
  return (
    <ToastProvider>
      <WorkspaceContent />
    </ToastProvider>
  );
}
