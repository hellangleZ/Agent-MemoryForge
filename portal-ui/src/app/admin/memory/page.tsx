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
import {
  Database,
  Search,
  Loader2,
  RefreshCw,
  Brain,
  Layers,
  FileText,
  Hash,
  Network,
  X
} from 'lucide-react';
import { getMemoryStats, memorySearch, memoryGet, rebuildMemoryIndex, MemorySearchResult, MemoryStats } from '@/lib/api';

function MemoryDetailModal({ memory, onClose, isDark }: { memory: MemorySearchResult | null; onClose: () => void; isDark: boolean }) {
  if (!memory) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        className={cn(
          "rounded-2xl border max-w-2xl w-full mx-4 max-h-[90vh] overflow-auto transition-colors duration-300",
          isDark ? "bg-slate-900 border-white/10" : "bg-white border-slate-200"
        )}
      >
        <div className={cn(
          "p-6 border-b flex items-center justify-between transition-colors duration-300",
          isDark ? "border-white/10" : "border-slate-200"
        )}>
          <h2 className={cn(
            "text-xl font-bold transition-colors duration-300",
            isDark ? "text-white" : "text-slate-900"
          )}>Memory Details</h2>
          <button
            onClick={onClose}
            className={cn(
              "p-2 rounded-lg transition-colors",
              isDark ? "hover:bg-white/10" : "hover:bg-slate-100"
            )}
          >
            <X className={cn("w-5 h-5", isDark ? "text-slate-400" : "text-slate-500")} />
          </button>
        </div>
        <div className="p-6 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={cn(
                "text-sm transition-colors duration-300",
                isDark ? "text-slate-400" : "text-slate-500"
              )}>Memory Type</label>
              <p className={cn(
                "transition-colors duration-300",
                isDark ? "text-white" : "text-slate-900"
              )}>{memory.memory_type || 'N/A'}</p>
            </div>
            <div>
              <label className={cn(
                "text-sm transition-colors duration-300",
                isDark ? "text-slate-400" : "text-slate-500"
              )}>Created At</label>
              <p className={cn(
                "transition-colors duration-300",
                isDark ? "text-white" : "text-slate-900"
              )}>{memory.created_at ? new Date(memory.created_at).toLocaleString() : 'N/A'}</p>
            </div>
          </div>
          {memory.content && (
            <div>
              <label className={cn(
                "text-sm transition-colors duration-300",
                isDark ? "text-slate-400" : "text-slate-500"
              )}>Content</label>
              <pre className={cn(
                "mt-2 p-4 rounded-xl text-sm overflow-auto transition-colors duration-300",
                isDark ? "bg-white/5 text-slate-300" : "bg-slate-100 text-slate-700"
              )}>
                {JSON.stringify(memory.content, null, 2)}
              </pre>
            </div>
          )}
          {memory.metadata && Object.keys(memory.metadata).length > 0 && (
            <div>
              <label className={cn(
                "text-sm transition-colors duration-300",
                isDark ? "text-slate-400" : "text-slate-500"
              )}>Metadata</label>
              <pre className={cn(
                "mt-2 p-4 rounded-xl text-xs overflow-auto transition-colors duration-300",
                isDark ? "bg-white/5 text-slate-300" : "bg-slate-100 text-slate-700"
              )}>
                {JSON.stringify(memory.metadata, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </motion.div>
    </div>
  );
}

function MemoryContent() {
  const { addToast } = useToast();
  const { isDark } = useTheme();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchType, setSearchType] = useState<string>('all');
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<MemorySearchResult[]>([]);
  const [selectedMemory, setSelectedMemory] = useState<MemorySearchResult | null>(null);
  const [selectedRawText, setSelectedRawText] = useState<string | null>(null);
  const [rebuildingIndex, setRebuildingIndex] = useState(false);

  const neutralStatTone = {
    bg: isDark ? 'bg-white/10' : 'bg-slate-100',
    icon: isDark ? 'text-slate-100' : 'text-slate-900',
  };

  const statColors: Record<string, { bg: string; icon: string }> = {
    blue: neutralStatTone,
    cyan: neutralStatTone,
    green: neutralStatTone,
    purple: neutralStatTone,
    pink: neutralStatTone,
    amber: neutralStatTone,
  };

  const fetchStats = useCallback(async () => {
    try {
      setError(null);
      const response = await getMemoryStats();
      if (response?.data) {
        setStats(response.data as MemoryStats);
      } else {
        setStats(null);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch memory stats';
      setError(message);
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchStats();
    setRefreshing(false);
  };

  const handleRebuildIndex = async () => {
    setRebuildingIndex(true);
    try {
      await rebuildMemoryIndex();
      addToast('Index rebuild started', 'success');
      await fetchStats();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Index rebuild failed';
      addToast(message, 'error');
    } finally {
      setRebuildingIndex(false);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) {
      addToast('Please enter a search query', 'warning');
      return;
    }

    setSearching(true);
    try {
      const tierMap: Record<string, string[] | undefined> = {
        all: undefined,
        stm: ['stm'],
        wm: ['wm'],
        ltm: ['semantic', 'preferences'],
        kg: ['graph'],
      };

      const tiers = tierMap[searchType] ?? undefined;

      const response = await memorySearch({
        query: searchQuery,
        top_k: 20,
        tiers,
      });

      const hits = (response as any)?.data?.hits || [];
      const results: MemorySearchResult[] = Array.isArray(hits)
        ? hits.map((h: any) => ({
            id: h.entry_id,
            memory_type: h.tier,
            content: { snippet: h.snippet, path: h.path, line: h.line },
            metadata: h.metadata,
            created_at: h.created_at,
            score: h.score,
          }))
        : [];

      setSearchResults(results);
      addToast(`Found ${results.length} results`, results.length ? 'success' : 'info');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Memory search failed';
      setSearchResults([]);
      setError(message);
      addToast(message, 'error');
    } finally {
      setSearching(false);
    }
  };

  const handleSelectMemory = async (memory: MemorySearchResult) => {
    setSelectedRawText(null);
    setSelectedMemory(memory);
    const content = memory.content as any;
    const path = (content?.path || '').trim();
    const line = Number(content?.line || 1);
    if (!path) return;
    try {
      const startLine = Math.max(1, (Number.isFinite(line) ? line : 1) - 3);
      const res = await memoryGet({ path, start_line: startLine, max_lines: 120 });
      setSelectedRawText((res as any)?.data?.content || null);
    } catch {
      // best-effort; modal can still show metadata + snippet.
    }
  };

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

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
          )}>Loading memory statistics...</p>
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
            ? "bg-gradient-to-br from-amber-900/20 via-transparent to-orange-900/20"
            : "bg-gradient-to-br from-amber-100/50 via-transparent to-orange-100/50"
        )} />
        <div className={cn(
          "absolute top-0 right-1/4 w-96 h-96 rounded-full blur-3xl transition-colors duration-300",
          isDark ? "bg-amber-600/20" : "bg-amber-300/30"
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
          <div className="lg:col-span-1">
            <Sidebar variant="admin" />
          </div>

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
                    <div className="w-14 h-14 rounded-xl border bg-muted flex items-center justify-center shadow-sm text-text-primary">
                      <Database className="w-7 h-7" />
                    </div>
                    <div>
                      <h1 className={cn(
                        "text-2xl font-bold transition-colors duration-300",
                        isDark ? "text-white" : "text-slate-900"
                      )}>Memory Management</h1>
                      <p className={cn(
                        "transition-colors duration-300",
                        isDark ? "text-slate-400" : "text-slate-600"
                      )}>Inspect and search memory storage</p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="secondary" onClick={handleRefresh} disabled={refreshing}>
                      <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
                      Refresh
                    </Button>
                  </div>
                </div>
              </Card>
            </motion.div>

            {/* Stats Cards */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
            >
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {/* STM */}
                <Card className="p-4">
                  <div className="flex items-center gap-3 mb-3">
                    <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", statColors.blue.bg)}>
                      <Brain className={cn("w-5 h-5", statColors.blue.icon)} />
                    </div>
                    <div>
                      <h3 className={cn(
                        "font-medium transition-colors duration-300",
                        isDark ? "text-white" : "text-slate-900"
                      )}>STM</h3>
                      <p className={cn(
                        "text-xs transition-colors duration-300",
                        isDark ? "text-slate-500" : "text-slate-500"
                      )}>Short-term Memory</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className={cn("transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>Items</span>
                      <span className={cn("font-mono transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>{stats?.stm?.count || 0}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className={cn("transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>Size</span>
                      <span className={cn("font-mono transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>{formatBytes(stats?.stm?.size_bytes || 0)}</span>
                    </div>
                    <div className={cn("w-full rounded-full h-2", isDark ? "bg-white/10" : "bg-slate-200")}>
                      <div className={cn("h-2 rounded-full", isDark ? "bg-slate-100" : "bg-slate-900")} style={{ width: '30%' }} />
                    </div>
                  </div>
                </Card>

                {/* WM */}
                <Card className="p-4">
                  <div className="flex items-center gap-3 mb-3">
                    <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", statColors.cyan.bg)}>
                      <Layers className={cn("w-5 h-5", statColors.cyan.icon)} />
                    </div>
                    <div>
                      <h3 className={cn("font-medium transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>WM</h3>
                      <p className={cn("text-xs transition-colors duration-300", isDark ? "text-slate-500" : "text-slate-500")}>Working Memory</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className={cn("transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>Items</span>
                      <span className={cn("font-mono transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>{stats?.wm?.count || 0}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className={cn("transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>Size</span>
                      <span className={cn("font-mono transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>{formatBytes(stats?.wm?.size_bytes || 0)}</span>
                    </div>
                    <div className={cn("w-full rounded-full h-2", isDark ? "bg-white/10" : "bg-slate-200")}>
                      <div className={cn("h-2 rounded-full", isDark ? "bg-slate-100" : "bg-slate-900")} style={{ width: '50%' }} />
                    </div>
                  </div>
                </Card>

                {/* LTM */}
                <Card className="p-4">
                  <div className="flex items-center gap-3 mb-3">
                    <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", statColors.green.bg)}>
                      <FileText className={cn("w-5 h-5", statColors.green.icon)} />
                    </div>
                    <div>
                      <h3 className={cn("font-medium transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>LTM</h3>
                      <p className={cn("text-xs transition-colors duration-300", isDark ? "text-slate-500" : "text-slate-500")}>Long-term Memory</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className={cn("transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>Items</span>
                      <span className={cn("font-mono transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>{stats?.ltm?.count || 0}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className={cn("transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>Size</span>
                      <span className={cn("font-mono transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>{formatBytes(stats?.ltm?.size_bytes || 0)}</span>
                    </div>
                    <div className={cn("w-full rounded-full h-2", isDark ? "bg-white/10" : "bg-slate-200")}>
                      <div className={cn("h-2 rounded-full", isDark ? "bg-slate-100" : "bg-slate-900")} style={{ width: '70%' }} />
                    </div>
                  </div>
                </Card>

                {/* Knowledge Graph */}
                <Card className="p-4">
                  <div className="flex items-center gap-3 mb-3">
                    <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", statColors.pink.bg)}>
                      <Network className={cn("w-5 h-5", statColors.pink.icon)} />
                    </div>
                    <div>
                      <h3 className={cn("font-medium transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>Knowledge Graph</h3>
                      <p className={cn("text-xs transition-colors duration-300", isDark ? "text-slate-500" : "text-slate-500")}>Graph Database</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className={cn("transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>Nodes</span>
                      <span className={cn("font-mono transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>{stats?.knowledge_graph?.nodes || 0}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className={cn("transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>Edges</span>
                      <span className={cn("font-mono transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>{stats?.knowledge_graph?.edges || 0}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className={cn("transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>Size</span>
                      <span className={cn("font-mono transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>{formatBytes(stats?.knowledge_graph?.size_bytes || 0)}</span>
                    </div>
                  </div>
                </Card>

                {/* File-first Index */}
                <Card className="p-4">
                  <div className="flex items-center gap-3 mb-3">
                    <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", statColors.amber.bg)}>
                      <Hash className={cn("w-5 h-5", statColors.amber.icon)} />
                    </div>
                    <div className="min-w-0">
                      <h3 className={cn("font-medium transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>Index</h3>
                      <p className={cn("text-xs transition-colors duration-300", isDark ? "text-slate-500" : "text-slate-500")}>SQLite FTS (derived)</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-sm gap-2">
                      <span className={cn("transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>Status</span>
                      {stats?.file_first?.index?.stale ? (
                        <Badge variant="warning">Stale</Badge>
                      ) : (
                        <Badge variant="success">Healthy</Badge>
                      )}
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className={cn("transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>Updated</span>
                      <span className={cn("font-mono transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>
                        {typeof stats?.file_first?.index?.mtime_s === 'number'
                          ? new Date(stats.file_first.index.mtime_s * 1000).toLocaleString()
                          : 'Unknown'}
                      </span>
                    </div>
                    <Button
                      variant="secondary"
                      onClick={() => void handleRebuildIndex()}
                      disabled={rebuildingIndex}
                      className="w-full"
                    >
                      <RefreshCw className={`w-4 h-4 ${rebuildingIndex ? 'animate-spin' : ''}`} />
                      Rebuild Index
                    </Button>
                  </div>
                </Card>

                {/* Total */}
                <Card className={cn(
                  "p-4 border transition-colors duration-300",
                  isDark
                    ? "bg-gradient-to-br from-purple-500/20 to-cyan-500/20 border-purple-500/30"
                    : "bg-gradient-to-br from-purple-100/50 to-cyan-100/50 border-purple-200"
                )}>
                  <div className="flex items-center gap-3 mb-3">
                    <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", statColors.purple.bg)}>
                      <Database className={cn("w-5 h-5", statColors.purple.icon)} />
                    </div>
                    <div>
                      <h3 className={cn("font-medium transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>Total Storage</h3>
                      <p className={cn("text-xs transition-colors duration-300", isDark ? "text-slate-500" : "text-slate-500")}>All Memory Types</p>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className={cn("transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>Total Items</span>
                      <span className={cn("font-mono font-bold transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>
                        {(stats?.stm?.count || 0) + (stats?.wm?.count || 0) + (stats?.ltm?.count || 0)}
                      </span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className={cn("transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>Total Size</span>
                      <span className={cn("font-mono font-bold", isDark ? "text-purple-400" : "text-purple-600")}>
                        {formatBytes(
                          (stats?.stm?.size_bytes || 0) +
                          (stats?.wm?.size_bytes || 0) +
                          (stats?.ltm?.size_bytes || 0) +
                          (stats?.knowledge_graph?.size_bytes || 0)
                        )}
                      </span>
                    </div>
                  </div>
                </Card>
              </div>
            </motion.div>

            {/* Search Section */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.2 }}
            >
              <Card className="p-6">
                <CardHeader
                  title="Memory Search"
                  description="Search across all memory stores"
                />
                <div className="space-y-4">
                  <div className="flex flex-col md:flex-row gap-4">
                    <div className="flex-1 relative">
                      <Search className={cn(
                        "absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4",
                        isDark ? "text-slate-500" : "text-slate-400"
                      )} />
                      <input
                        type="text"
                        placeholder="Search memories..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                        className={cn(
                          "w-full pl-10 px-4 py-3 rounded-xl border transition-all duration-300 focus:outline-none focus:ring-2",
                          isDark
                            ? "bg-slate-800/50 border-white/10 text-white placeholder:text-slate-500 focus:border-cyan-500/50 focus:ring-cyan-500/20"
                            : "bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-cyan-400/50 focus:ring-cyan-400/20"
                        )}
                      />
                    </div>
                    <select
                      aria-label="Memory tier"
                      value={searchType}
                      onChange={(e) => setSearchType(e.target.value)}
                      className={cn(
                        "md:w-40 px-4 py-3 rounded-xl border transition-all duration-300 focus:outline-none focus:ring-2",
                        isDark
                          ? "bg-slate-800/50 border-white/10 text-white focus:border-cyan-500/50 focus:ring-cyan-500/20"
                          : "bg-white border-slate-200 text-slate-900 focus:border-cyan-400/50 focus:ring-cyan-400/20"
                      )}
                    >
                      <option value="all">All Types</option>
                      <option value="stm">STM</option>
                      <option value="wm">WM</option>
                      <option value="ltm">LTM</option>
                      <option value="kg">Knowledge Graph</option>
                    </select>
                    <Button onClick={handleSearch} disabled={searching}>
                      {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
                      Search
                    </Button>
                  </div>
                </div>
              </Card>
            </motion.div>

            {/* Search Results */}
            {searchResults.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.3 }}
              >
                <Card>
                  <CardHeader
                    title="Search Results"
                    description={`Found ${searchResults.length} results`}
                  />
                  <CardContent>
                    <div className="space-y-3">
                      {searchResults.map((result, index) => (
                        <div
                          key={index}
                          className={cn(
                            "p-4 rounded-xl border cursor-pointer transition-colors duration-300",
                            isDark
                              ? "bg-white/5 border-white/10 hover:bg-white/10"
                              : "bg-slate-50 border-slate-200 hover:bg-white"
                          )}
                          onClick={() => void handleSelectMemory(result)}
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-2">
                                <Badge variant="info">{result.memory_type || 'Unknown'}</Badge>
                                <span className={cn(
                                  "text-xs transition-colors duration-300",
                                  isDark ? "text-slate-500" : "text-slate-500"
                                )}>
                                  {result.created_at ? new Date(result.created_at).toLocaleDateString() : 'Unknown date'}
                                </span>
                              </div>
                              <p className={cn(
                                "text-sm line-clamp-2 transition-colors duration-300",
                                isDark ? "text-slate-400" : "text-slate-600"
                              )}>
                                {typeof (result as any)?.content?.snippet === 'string'
                                  ? (result as any).content.snippet
                                  : JSON.stringify(result.content || result)}
                              </p>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            )}

            {error && <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.4 }}
            >
              <Card className="border bg-card">
                <CardContent className="p-4">
                  <div className="flex items-start gap-3">
                    <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0", statColors.amber.bg)}>
                      <Database className={cn("w-5 h-5", statColors.amber.icon)} />
                    </div>
                    <div>
                      <h4 className={cn("font-medium transition-colors duration-300", isDark ? "text-white" : "text-slate-900")}>Memory service unavailable</h4>
                      <p className={cn("text-sm mt-1 transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>
                        The portal did not show placeholder memory data. Fix the service connection and refresh this page.
                      </p>
                      <ul className={cn("text-sm mt-2 list-disc list-inside transition-colors duration-300", isDark ? "text-slate-400" : "text-slate-600")}>
                        <li>Ensure the memory service is running</li>
                        <li>Ensure the gateway is running and auth cookies are present</li>
                        <li className="break-all">Last error: {error}</li>
                      </ul>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </motion.div>}
          </div>
        </div>
      </div>

      {/* Memory Detail Modal */}
      {selectedMemory && (
        <MemoryDetailModal
          memory={
            selectedRawText
              ? ({
                  ...selectedMemory,
                  content: { ...(selectedMemory.content as any), raw_text: selectedRawText },
                } as MemorySearchResult)
              : selectedMemory
          }
          onClose={() => {
            setSelectedMemory(null);
            setSelectedRawText(null);
          }}
          isDark={isDark}
        />
      )}
    </div>
  );
}

// Helper functions
function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

export default function AdminMemoryPage() {
  return (
    <ToastProvider>
      <MemoryContent />
    </ToastProvider>
  );
}
