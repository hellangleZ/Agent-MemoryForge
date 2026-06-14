'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Sidebar } from '@/components/Sidebar';
import { Card, CardHeader, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input, Textarea } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import { useTheme } from '@/lib/theme';
import { cn } from '@/lib/utils';
import { createAgent, deleteAgent, getAgents } from '@/lib/api';
import { motion } from 'framer-motion';
import { Bot, Loader2, MessageSquare, FileCode, GitBranch, Trash2 } from 'lucide-react';

interface Agent {
  name?: string;
  description?: string;
  capabilities?: string[];
  config?: Record<string, unknown>;
  custom?: boolean;
  system_prompt?: string;
  tools?: string[];
}
interface AgentsResponse { agents: Record<string, Agent>; }

function AgentsContent() {
  const { addToast } = useToast();
  const { isDark } = useTheme();
  const [agents, setAgents] = useState<Record<string, Agent> | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    id: '',
    name: '',
    description: '',
    system_prompt: '',
    tools: '',
  });

  useEffect(() => {
    const fetchAgents = async () => {
      try {
        const data = await getAgents().catch(() => null);
        setAgents((data as AgentsResponse)?.agents || {});
      } catch (err: any) {
        addToast('Failed to load agents', 'error');
      } finally { setLoading(false); }
    };
    fetchAgents();
  }, [addToast]);

  const agentIcons: Record<string, React.ComponentType<{ className?: string }>> = {
    'code-assistant': FileCode, 'project-manager': GitBranch, 'default': Bot,
  };

  const displayAgents = agents || {};

  const handleCreate = async () => {
    if (!form.id.trim()) {
      addToast('Agent ID is required', 'error');
      return;
    }
    setSaving(true);
    try {
      const tools = form.tools
        .split(',')
        .map((tool) => tool.trim())
        .filter(Boolean);
      await createAgent({
        id: form.id.trim(),
        name: form.name.trim() || undefined,
        description: form.description.trim() || undefined,
        system_prompt: form.system_prompt.trim() || undefined,
        tools,
      });
      addToast('Custom agent saved', 'success');
      setForm({ id: '', name: '', description: '', system_prompt: '', tools: '' });
      const data = await getAgents().catch(() => null);
      setAgents((data as AgentsResponse)?.agents || {});
    } catch (err: any) {
      addToast('Failed to save agent', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (agentId: string) => {
    if (!confirm(`Delete agent ${agentId}?`)) {
      return;
    }
    try {
      await deleteAgent(agentId);
      addToast('Agent deleted', 'success');
      const data = await getAgents().catch(() => null);
      setAgents((data as AgentsResponse)?.agents || {});
    } catch {
      addToast('Failed to delete agent', 'error');
    }
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
          )}>Loading agents...</p>
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
                    <div className="w-14 h-14 rounded-xl border bg-muted flex items-center justify-center shadow-sm text-text-primary">
                      <Bot className="w-7 h-7" />
                    </div>
                    <div>
                      <h1 className={cn(
                        "text-2xl font-bold transition-colors duration-300",
                        isDark ? "text-white" : "text-slate-900"
                      )}>Agent Management</h1>
                      <p className={cn(
                        "transition-colors duration-300",
                        isDark ? "text-slate-400" : "text-slate-600"
                      )}>View and configure available agents</p>
                    </div>
                  </div>
                  <Badge variant="info">{Object.keys(displayAgents).length} agents</Badge>
                </div>
              </Card>
            </motion.div>

            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.08 }}>
              <Card>
                <CardHeader title="Create Custom Agent" description="Define a new agent with a system prompt and tool allowlist." />
                <CardContent>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <Input
                      label="Agent ID"
                      placeholder="customer-support"
                      value={form.id}
                      onChange={(e) => setForm((prev) => ({ ...prev, id: e.target.value }))}
                    />
                    <Input
                      label="Display Name"
                      placeholder="Customer Support"
                      value={form.name}
                      onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
                    />
                    <Input
                      label="Description"
                      placeholder="Handles support workflows"
                      value={form.description}
                      onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
                    />
                    <Input
                      label="Tools (comma-separated)"
                      placeholder="mcp.search, mcp.ticket.create"
                      value={form.tools}
                      onChange={(e) => setForm((prev) => ({ ...prev, tools: e.target.value }))}
                    />
                    <div className="md:col-span-2">
                      <Textarea
                        label="System Prompt"
                        rows={4}
                        placeholder="You are a helpful support agent..."
                        value={form.system_prompt}
                        onChange={(e) => setForm((prev) => ({ ...prev, system_prompt: e.target.value }))}
                      />
                    </div>
                  </div>
                  <div className="flex justify-end mt-4">
                    <Button onClick={handleCreate} disabled={saving}>
                      {saving ? 'Saving...' : 'Save Agent'}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </motion.div>

            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.1 }}>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {Object.entries(displayAgents).map(([id, agent]) => {
                  const Icon = agentIcons[id] || Bot;
                  return (
                    <Card key={id} hover className="p-4">
                      <div className="flex items-start gap-4">
                        <div className="w-12 h-12 rounded-xl border bg-muted flex items-center justify-center text-text-primary">
                          <Icon className="w-6 h-6" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <h3 className={cn(
                            "font-semibold truncate transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>{agent.name || id}</h3>
                          <p className={cn(
                            "text-sm mt-1 line-clamp-2 transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>{agent.description || 'No description available'}</p>
                          {agent.custom && (
                            <Badge variant="info" className="mt-2">Custom</Badge>
                          )}
                          {agent.tools && agent.tools.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-3">
                              {agent.tools.slice(0, 3).map((tool) => (
                                <Badge key={tool} variant="default" className="text-xs">{tool}</Badge>
                              ))}
                              {agent.tools.length > 3 && (
                                <Badge variant="default" className="text-xs">+{agent.tools.length - 3}</Badge>
                              )}
                            </div>
                          )}
                          {agent.capabilities && (
                            <div className="flex flex-wrap gap-1 mt-3">
                              {agent.capabilities.slice(0, 3).map((cap: string) => <Badge key={cap} variant="default" className="text-xs">{cap}</Badge>)}
                              {agent.capabilities.length > 3 && <Badge variant="default" className="text-xs">+{agent.capabilities.length - 3}</Badge>}
                            </div>
                          )}
                        </div>
                      </div>
                      <div className="flex gap-2 mt-4">
                        <Link
                          href={`/admin/chat/${encodeURIComponent(id)}`}
                          className="inline-flex h-8 flex-1 items-center justify-center gap-2 rounded-md border bg-card px-3 text-xs font-medium text-text-primary transition-colors hover:bg-muted focus:outline-none focus:ring-2 focus:ring-ring/20"
                        >
                          <MessageSquare className="w-4 h-4" />
                          Chat
                        </Link>
                        {agent.custom && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleDelete(id)}
                            aria-label={`Delete ${id}`}
                            title={`Delete ${id}`}
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        )}
                      </div>
                    </Card>
                  );
                })}
              </div>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AdminAgentsPage() {
  return (<ToastProvider><AgentsContent /></ToastProvider>);
}
