'use client';

import { useState, useEffect, useCallback } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { Card, CardHeader, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import { useTheme } from '@/lib/theme';
import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';
import Link from 'next/link';
import {
  Terminal,
  Search,
  Eye,
  Loader2,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  X
} from 'lucide-react';
import { getRuns, RunRecord } from '@/lib/api';

const ITEMS_PER_PAGE = 10;

function RunsContent() {
  const { addToast } = useToast();
  const { isDark } = useTheme();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [agentFilter, setAgentFilter] = useState<string>('all');
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [agents, setAgents] = useState<string[]>([]);

  const fetchRuns = useCallback(async () => {
    try {
      setError(null);
      const params: {
        page: number;
        limit: number;
        agent?: string;
        status?: string;
      } = {
        page: currentPage,
        limit: ITEMS_PER_PAGE,
      };

      if (agentFilter !== 'all') {
        params.agent = agentFilter;
      }
      if (statusFilter !== 'all') {
        params.status = statusFilter;
      }

      const response = await getRuns(params);
      setRuns(response.runs);
      setTotal(response.total);

      // Extract unique agents from runs
      const uniqueAgents = Array.from(new Set(response.runs.map(r => r.agent)));
      setAgents(uniqueAgents);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch runs';
      setError(message);
      addToast(message, 'error');
    } finally {
      setLoading(false);
    }
  }, [addToast, currentPage, agentFilter, statusFilter]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchRuns();
    setRefreshing(false);
  };

  const handlePageChange = (newPage: number) => {
    setCurrentPage(newPage);
  };

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  const filteredRuns = runs.filter(run => {
    const matchesSearch = searchQuery === '' ||
      run.trace_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      run.agent.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesSearch;
  });

  const totalPages = Math.ceil(total / ITEMS_PER_PAGE);

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
          )}>Loading runs...</p>
        </div>
      </div>
    );
  }

  return (
    <div className={cn(
      "min-h-screen transition-colors duration-300",
      isDark ? "bg-[hsl(230_25%_7%)]" : "bg-[hsl(220_20%_97%)]"
    )}>
      {/* Background effects */}
      <div className="fixed inset-0 -z-10 overflow-hidden">
        <div className={cn(
          "absolute inset-0 transition-colors duration-300",
          isDark
            ? "bg-gradient-to-br from-purple-900/20 via-transparent to-cyan-900/20"
            : "bg-gradient-to-br from-purple-100/50 via-transparent to-cyan-100/50"
        )} />
        <div className={cn(
          "absolute top-0 right-1/4 w-96 h-96 rounded-full blur-3xl transition-colors duration-300",
          isDark ? "bg-purple-600/20" : "bg-purple-300/30"
        )} />
        {/* Grid pattern */}
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
          <div className="lg:col-span-1"><Sidebar variant="admin" /></div>
          <div className="lg:col-span-3 space-y-6">
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
              <Card className="p-6">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                  <div className="flex items-center gap-4">
                    <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-500 to-cyan-500 flex items-center justify-center shadow-lg shadow-purple-500/25">
                      <Terminal className="w-7 h-7 text-white" />
                    </div>
                    <div>
                      <h1 className={cn(
                        "text-2xl font-bold transition-colors duration-300",
                        isDark ? "text-white" : "text-slate-900"
                      )}>Run History</h1>
                      <p className={cn(
                        "transition-colors duration-300",
                        isDark ? "text-slate-400" : "text-slate-600"
                      )}>View all conversation and task runs</p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="secondary" onClick={handleRefresh} disabled={refreshing}>
                      <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
                      Refresh
                    </Button>
                    <Badge variant="info">{total} runs</Badge>
                  </div>
                </div>
              </Card>
            </motion.div>

            {/* Error Display */}
            {error && (
              <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.1 }}>
                <Card className={cn(
                  "border transition-colors duration-300",
                  isDark ? "border-red-500/20 bg-red-500/5" : "border-red-200 bg-red-50"
                )}>
                  <CardContent className="p-4">
                    <div className="flex items-start gap-3">
                      <div className={cn(
                        "w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0",
                        isDark ? "bg-red-500/10" : "bg-red-100"
                      )}>
                        <X className={cn("w-5 h-5", isDark ? "text-red-400" : "text-red-600")} />
                      </div>
                      <div>
                        <h4 className={cn(
                          "font-medium transition-colors duration-300",
                          isDark ? "text-white" : "text-slate-900"
                        )}>Error Loading Runs</h4>
                        <p className={cn(
                          "text-sm mt-1 transition-colors duration-300",
                          isDark ? "text-slate-400" : "text-slate-600"
                        )}>{error}</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            )}

            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.15 }}>
              <Card className="p-4">
                <div className="flex flex-col md:flex-row gap-4">
                  <div className="flex-1 relative">
                    <Search className={cn(
                      "absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4",
                      isDark ? "text-slate-500" : "text-slate-400"
                    )} />
                    <input
                      type="text"
                      placeholder="Search by trace_id or agent..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className={cn(
                        "w-full pl-10 px-4 py-3 rounded-xl border transition-all duration-300 focus:outline-none focus:ring-2",
                        isDark
                          ? "bg-slate-800/50 border-white/10 text-white placeholder:text-slate-500 focus:border-cyan-500/50 focus:ring-cyan-500/20"
                          : "bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-cyan-400/50 focus:ring-cyan-400/20"
                      )}
                    />
                  </div>
                  <select
                    value={agentFilter}
                    onChange={(e) => setAgentFilter(e.target.value)}
                    className={cn(
                      "min-w-[150px] px-4 py-3 rounded-xl border transition-all duration-300 focus:outline-none focus:ring-2",
                      isDark
                        ? "bg-slate-800/50 border-white/10 text-white focus:border-cyan-500/50 focus:ring-cyan-500/20"
                        : "bg-white border-slate-200 text-slate-900 focus:border-cyan-400/50 focus:ring-cyan-400/20"
                    )}
                  >
                    <option value="all">All Agents</option>
                    {agents.map((agent) => (
                      <option key={agent} value={agent}>{agent}</option>
                    ))}
                  </select>
                  <select
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    className={cn(
                      "min-w-[150px] px-4 py-3 rounded-xl border transition-all duration-300 focus:outline-none focus:ring-2",
                      isDark
                        ? "bg-slate-800/50 border-white/10 text-white focus:border-cyan-500/50 focus:ring-cyan-500/20"
                        : "bg-white border-slate-200 text-slate-900 focus:border-cyan-400/50 focus:ring-cyan-400/20"
                    )}
                  >
                    <option value="all">All Status</option>
                    <option value="success">Success</option>
                    <option value="error">Error</option>
                    <option value="running">Running</option>
                  </select>
                </div>
              </Card>
            </motion.div>

            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.2 }}>
              <Card>
                <CardHeader title="All Runs" description={`Showing ${filteredRuns.length} of ${total} runs`} />
                <CardContent>
                  {filteredRuns.length === 0 ? (
                    <div className={cn(
                      "text-center py-8 transition-colors duration-300",
                      isDark ? "text-slate-500" : "text-slate-500"
                    )}>
                      No runs found
                    </div>
                  ) : (
                    <>
                      <div className="overflow-x-auto">
                        <table className="w-full">
                          <thead>
                            <tr className={cn(
                              "text-left text-xs uppercase tracking-wider transition-colors duration-300",
                              isDark ? "text-slate-500" : "text-slate-500"
                            )}>
                              <th className="pb-3 pl-2">Trace ID</th>
                              <th className="pb-3">Agent</th>
                              <th className="pb-3">Status</th>
                              <th className="pb-3">Duration</th>
                              <th className="pb-3">Created</th>
                              <th className="pb-3 pr-2 text-right">Actions</th>
                            </tr>
                          </thead>
                          <tbody className={cn(
                            "divide-y transition-colors duration-300",
                            isDark ? "divide-white/5" : "divide-slate-100"
                          )}>
                            {filteredRuns.map((run) => (
                              <tr key={run.id} className={cn(
                                "transition-colors",
                                isDark ? "hover:bg-white/5" : "hover:bg-slate-50"
                              )}>
                                <td className="py-3 pl-2">
                                  <span className={cn(
                                    "font-mono text-sm transition-colors duration-300",
                                    isDark ? "text-white" : "text-slate-900"
                                  )}>{run.trace_id}</span>
                                </td>
                                <td className="py-3">
                                  <span className={cn(
                                    "text-sm transition-colors duration-300",
                                    isDark ? "text-slate-400" : "text-slate-600"
                                  )}>{run.agent}</span>
                                </td>
                                <td className="py-3">
                                  <Badge variant={run.status === 'success' ? 'success' : run.status === 'error' ? 'danger' : 'warning'}>
                                    {run.status === 'running' ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                                    {run.status}
                                  </Badge>
                                </td>
                                <td className="py-3">
                                  <span className={cn(
                                    "text-sm transition-colors duration-300",
                                    isDark ? "text-slate-500" : "text-slate-500"
                                  )}>{run.duration_ms}ms</span>
                                </td>
                                <td className="py-3">
                                  <span className={cn(
                                    "text-sm transition-colors duration-300",
                                    isDark ? "text-slate-500" : "text-slate-500"
                                  )}>{new Date(run.created_at).toLocaleString()}</span>
                                </td>
                                <td className="py-3 pr-2">
                                  <Link href={`/admin/runs/${run.trace_id}`}>
                                    <Button size="sm" variant="ghost"><Eye className="w-4 h-4" /></Button>
                                  </Link>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>

                      {/* Pagination */}
                      {totalPages > 1 && (
                        <div className={cn(
                          "flex items-center justify-between mt-4 pt-4 border-t transition-colors duration-300",
                          isDark ? "border-white/10" : "border-slate-200"
                        )}>
                          <div className={cn(
                            "text-sm transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>
                            Page {currentPage} of {totalPages}
                          </div>
                          <div className="flex gap-2">
                            <Button
                              variant="secondary"
                              size="sm"
                              disabled={currentPage === 1}
                              onClick={() => handlePageChange(currentPage - 1)}
                            >
                              <ChevronLeft className="w-4 h-4" />
                              Previous
                            </Button>
                            <Button
                              variant="secondary"
                              size="sm"
                              disabled={currentPage === totalPages}
                              onClick={() => handlePageChange(currentPage + 1)}
                            >
                              Next
                              <ChevronRight className="w-4 h-4" />
                            </Button>
                          </div>
                        </div>
                      )}
                    </>
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

export default function AdminRunsPage() {
  return (
    <ToastProvider>
      <RunsContent />
    </ToastProvider>
  );
}
