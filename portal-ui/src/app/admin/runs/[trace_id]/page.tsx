'use client';

import { useCallback, useEffect, useState } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { Card, CardHeader, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import { useTheme } from '@/lib/theme';
import { cn } from '@/lib/utils';
import { motion } from 'framer-motion';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowLeft, Clock, CheckCircle, XCircle, Loader2, RefreshCw, X } from 'lucide-react';
import { getRunByTraceId, RunDetail } from '@/lib/api';

type Span = Record<string, unknown>;
type TraceEvent = Record<string, unknown>;

function RunDetailContent() {
  const params = useParams();
  const traceId = params.trace_id as string;
  const { addToast } = useToast();
  const { isDark } = useTheme();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<RunDetail | null>(null);

  const fetchTrace = useCallback(async () => {
    if (!traceId) return;

    try {
      setError(null);
      const data = await getRunByTraceId(traceId);
      setTrace(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch trace details';
      setError(message);
      addToast(message, 'error');
    } finally {
      setLoading(false);
    }
  }, [addToast, traceId]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchTrace();
    setRefreshing(false);
  };

  useEffect(() => {
    fetchTrace();
  }, [fetchTrace]);

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
          )}>Loading trace...</p>
        </div>
      </div>
    );
  }

  const spans: Span[] = (trace?.trace?.spans as unknown as Span[]) || [];
  const events: TraceEvent[] = (trace?.trace?.events as unknown as TraceEvent[]) || [];
  const metadata = trace?.trace?.metadata || {};

  const formatTs = (value: unknown) => {
    if (!value) return '—';
    if (typeof value === 'number') {
      return new Date(value * 1000).toLocaleString();
    }
    const str = String(value);
    const parsed = Date.parse(str);
    if (!Number.isNaN(parsed)) {
      return new Date(parsed).toLocaleString();
    }
    return str;
  };

  const spanStatus = (span: Span) => {
    const ok = (span.attributes as Record<string, unknown> | undefined)?.ok;
    if (ok === false) return 'error';
    return 'success';
  };

  const spanDuration = (span: Span) => {
    const duration = span.duration_ms as number | undefined;
    if (duration !== undefined && duration !== null) return `${Math.round(duration)}ms`;
    return '—';
  };

  const spanStart = (span: Span) => formatTs(span.start_time);
  const spanEnd = (span: Span) => formatTs(span.end_time);

  const getSpanAttributes = (span: Span): Record<string, unknown> | null => {
    if (span.attributes && typeof span.attributes === 'object') {
      return span.attributes as Record<string, unknown>;
    }
    return null;
  };

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
              <Link href="/admin/runs">
                <Button variant="ghost" className="mb-4">
                  <ArrowLeft className="w-4 h-4" />
                  Back to Runs
                </Button>
              </Link>
              <Card className="p-6">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                  <div className="flex items-center gap-4">
                    <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-500 to-cyan-500 flex items-center justify-center shadow-lg shadow-purple-500/25">
                      <Clock className="w-7 h-7 text-white" />
                    </div>
                    <div>
                      <h1 className={cn(
                        "text-2xl font-bold transition-colors duration-300",
                        isDark ? "text-white" : "text-slate-900"
                      )}>Trace Details</h1>
                      <p className={cn(
                        "font-mono text-sm transition-colors duration-300",
                        isDark ? "text-slate-500" : "text-slate-500"
                      )}>{traceId}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="secondary" onClick={handleRefresh} disabled={refreshing}>
                      <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
                      Refresh
                    </Button>
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
                        )}>Error Loading Trace</h4>
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

            {/* Metadata Card */}
            {Object.keys(metadata).length > 0 && (
              <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.12 }}>
                <Card>
                  <CardHeader title="Metadata" description="Trace metadata information" />
                  <CardContent>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(metadata).map(([key, value]) => (
                        <Badge key={key} variant="info" className="text-xs">
                          {key}: {String(value)}
                        </Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            )}

            {/* Trace Timeline */}
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.15 }}>
              <Card>
                <CardHeader title="Trace Timeline" description={`${spans.length} execution spans`} />
                <CardContent>
                  {spans.length === 0 ? (
                    <div className={cn(
                      "text-center py-8 transition-colors duration-300",
                      isDark ? "text-slate-500" : "text-slate-500"
                    )}>
                      No spans found
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {spans.map((span, index) => (
                        <div key={String(span.id)} className="relative pl-8 pb-4 last:pb-0">
                          {index < (spans.length - 1) && (
                            <div className={cn(
                              "absolute left-3 top-8 w-0.5 h-full transition-colors duration-300",
                              isDark ? "bg-white/10" : "bg-slate-200"
                            )} />
                          )}
                          <div className={cn(
                            "absolute left-0 top-1 w-6 h-6 rounded-full flex items-center justify-center",
                            isDark ? "bg-purple-500/10" : "bg-purple-100"
                          )}>
                            {spanStatus(span) === 'success' ? (
                              <CheckCircle className="w-4 h-4 text-green-400" />
                            ) : (
                              <XCircle className="w-4 h-4 text-red-400" />
                            )}
                          </div>
                          <div className={cn(
                            "p-4 rounded-xl border transition-colors duration-300",
                            isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"
                          )}>
                            <div className="flex items-center justify-between mb-2">
                              <h4 className={cn(
                                "font-medium transition-colors duration-300",
                                isDark ? "text-white" : "text-slate-900"
                              )}>{String(span.name || 'Span')}</h4>
                              <span className={cn(
                                "text-sm transition-colors duration-300",
                                isDark ? "text-slate-500" : "text-slate-500"
                              )}>{spanDuration(span)}</span>
                            </div>
                            <div className={cn(
                              "flex items-center gap-4 text-xs transition-colors duration-300",
                              isDark ? "text-slate-500" : "text-slate-500"
                            )}>
                              <span className="flex items-center gap-1">
                                <Clock className="w-3 h-3" />
                                {spanStart(span)} - {spanEnd(span)}
                              </span>
                            </div>
                            {(() => {
                              const attrs = getSpanAttributes(span);
                              return attrs && Object.keys(attrs).length > 0 && (
                              <div className="mt-3 flex flex-wrap gap-2">
                                {Object.entries(attrs).map(([key, value]) => (
                                  <Badge key={key} variant="default" className="text-xs">
                                    {key}: {String(value)}
                                  </Badge>
                                ))}
                              </div>
                            );
                            })()}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </motion.div>

            {/* Events */}
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.2 }}>
              <Card>
                <CardHeader title="Events" description={`${events.length} trace events`} />
                <CardContent>
                  {events.length === 0 ? (
                    <div className={cn(
                      "text-center py-8 transition-colors duration-300",
                      isDark ? "text-slate-500" : "text-slate-500"
                    )}>
                      No events found
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {events.map((event, index) => {
                        const message = String((event as any).message || (event as any).name || 'event');
                        const eventType = String((event as any).type || (event as any).attributes?.event || 'info');
                        const timestamp = (event as any).timestamp || (event as any).ts_s;
                        return (
                        <div key={index} className={cn(
                          "flex items-center gap-3 p-3 rounded-xl border transition-colors duration-300",
                          isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"
                        )}>
                          <Clock className={cn(
                            "w-4 h-4 flex-shrink-0",
                            isDark ? "text-slate-500" : "text-slate-400"
                          )} />
                          <span className={cn(
                            "text-xs w-24 transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>{formatTs(timestamp)}</span>
                          <span className={cn(
                            "text-sm flex-1 transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>{message}</span>
                          <Badge
                            variant={
                              eventType === 'success' || eventType === 'ok'
                                ? 'success'
                                : eventType === 'error'
                                  ? 'danger'
                                  : 'info'
                            }
                            className="text-xs"
                          >
                            {eventType}
                          </Badge>
                        </div>
                      );
                      })}
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

export default function AdminRunDetailPage() {
  return (
    <ToastProvider>
      <RunDetailContent />
    </ToastProvider>
  );
}
