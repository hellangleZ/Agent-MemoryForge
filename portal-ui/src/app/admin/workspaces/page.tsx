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
  Shield,
  Search,
  Loader2,
  Trash2,
  Eye,
  RefreshCw,
  X
} from 'lucide-react';
import { addWorkspaceMember, deleteWorkspaceMember, getWorkspaceMembers, getWorkspaces, deleteWorkspace, getWorkspaceById, Workspace, WorkspaceDetail, WorkspaceMember } from '@/lib/api';

interface WorkspaceDetailModalProps {
  workspace: WorkspaceDetail | null;
  onClose: () => void;
  isDark: boolean;
  members: WorkspaceMember[];
  memberForm: { user_id: string; role: string };
  onMemberFormChange: (next: { user_id: string; role: string }) => void;
  onAddMember: () => void;
  onRemoveMember: (userId: string) => void;
}

function WorkspaceDetailModal({ workspace, onClose, isDark, members, memberForm, onMemberFormChange, onAddMember, onRemoveMember }: WorkspaceDetailModalProps) {
  if (!workspace) return null;

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
          )}>Workspace Details</h2>
          <button
            onClick={onClose}
            className={cn(
              "p-2 rounded-lg transition-colors",
              isDark ? "hover:bg-white/10" : "hover:bg-slate-100"
            )}
          >
            <X className={cn(
              "w-5 h-5",
              isDark ? "text-slate-400" : "text-slate-500"
            )} />
          </button>
        </div>
        <div className="p-6 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={cn(
                "text-sm transition-colors duration-300",
                isDark ? "text-slate-400" : "text-slate-500"
              )}>Workspace ID</label>
              <p className={cn(
                "font-mono text-sm transition-colors duration-300",
                isDark ? "text-white" : "text-slate-900"
              )}>{workspace.id}</p>
            </div>
            <div>
              <label className={cn(
                "text-sm transition-colors duration-300",
                isDark ? "text-slate-400" : "text-slate-500"
              )}>Name</label>
              <p className={cn(
                "transition-colors duration-300",
                isDark ? "text-white" : "text-slate-900"
              )}>{workspace.name}</p>
            </div>
            <div>
              <label className={cn(
                "text-sm transition-colors duration-300",
                isDark ? "text-slate-400" : "text-slate-500"
              )}>Owner</label>
              <p className={cn(
                "transition-colors duration-300",
                isDark ? "text-white" : "text-slate-900"
              )}>{workspace.owner}</p>
            </div>
            <div>
              <label className={cn(
                "text-sm transition-colors duration-300",
                isDark ? "text-slate-400" : "text-slate-500"
              )}>Status</label>
              <div className="mt-1">
                <Badge variant={workspace.status === 'active' ? 'success' : 'default'}>
                  {workspace.status}
                </Badge>
              </div>
            </div>
            <div>
              <label className={cn(
                "text-sm transition-colors duration-300",
                isDark ? "text-slate-400" : "text-slate-500"
              )}>Created At</label>
              <p className={cn(
                "transition-colors duration-300",
                isDark ? "text-white" : "text-slate-900"
              )}>{new Date(workspace.created_at).toLocaleString()}</p>
            </div>
          </div>

          {workspace.agents && workspace.agents.length > 0 && (
            <div>
              <label className={cn(
                "text-sm transition-colors duration-300",
                isDark ? "text-slate-400" : "text-slate-500"
              )}>Agents</label>
              <div className="flex flex-wrap gap-2 mt-1">
                {workspace.agents.map((agent) => (
                  <Badge key={agent} variant="info">{agent}</Badge>
                ))}
              </div>
            </div>
          )}

          {workspace.config && Object.keys(workspace.config).length > 0 && (
            <div>
              <label className={cn(
                "text-sm transition-colors duration-300",
                isDark ? "text-slate-400" : "text-slate-500"
              )}>Configuration</label>
              <pre className={cn(
                "mt-2 p-4 rounded-xl text-xs overflow-auto transition-colors duration-300",
                isDark ? "bg-white/5 text-slate-300" : "bg-slate-100 text-slate-700"
              )}>
                {JSON.stringify(workspace.config, null, 2)}
              </pre>
            </div>
          )}

          <div>
            <label className={cn(
              "text-sm transition-colors duration-300",
              isDark ? "text-slate-400" : "text-slate-500"
            )}>Members</label>
            <div className="mt-2 space-y-2">
              {members.length === 0 ? (
                <p className={cn(
                  "text-sm transition-colors duration-300",
                  isDark ? "text-slate-500" : "text-slate-600"
                )}>No members yet.</p>
              ) : (
                members.map((member) => (
                  <div key={member.user_id} className={cn(
                    "flex items-center justify-between p-2 rounded-lg border transition-colors duration-300",
                    isDark ? "border-white/10 bg-white/5" : "border-slate-200 bg-slate-50"
                  )}>
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        "font-mono text-xs transition-colors duration-300",
                        isDark ? "text-slate-300" : "text-slate-600"
                      )}>{member.user_id}</span>
                      <Badge variant="info">{member.role}</Badge>
                    </div>
                    <Button size="sm" variant="ghost" onClick={() => onRemoveMember(member.user_id)}>
                      Remove
                    </Button>
                  </div>
                ))
              )}
            </div>
            <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-2">
              <input
                type="text"
                placeholder="user_id"
                value={memberForm.user_id}
                onChange={(e) => onMemberFormChange({ ...memberForm, user_id: e.target.value })}
                className={cn(
                  "w-full px-3 py-2 rounded-lg border transition-all duration-300 focus:outline-none focus:ring-2",
                  isDark
                    ? "bg-slate-800/50 border-white/10 text-white placeholder:text-slate-500 focus:border-cyan-500/50 focus:ring-cyan-500/20"
                    : "bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-cyan-400/50 focus:ring-cyan-400/20"
                )}
              />
              <select
                value={memberForm.role}
                onChange={(e) => onMemberFormChange({ ...memberForm, role: e.target.value })}
                className={cn(
                  "w-full px-3 py-2 rounded-lg border transition-all duration-300 focus:outline-none focus:ring-2",
                  isDark
                    ? "bg-slate-800/50 border-white/10 text-white focus:border-cyan-500/50 focus:ring-cyan-500/20"
                    : "bg-white border-slate-200 text-slate-900 focus:border-cyan-400/50 focus:ring-cyan-400/20"
                )}
              >
                <option value="member">member</option>
                <option value="admin">admin</option>
                <option value="viewer">viewer</option>
              </select>
              <Button onClick={onAddMember}>Add Member</Button>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

function WorkspacesContent() {
  const { addToast } = useToast();
  const { isDark } = useTheme();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<WorkspaceDetail | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [memberForm, setMemberForm] = useState({ user_id: '', role: 'member' });

  const fetchWorkspaces = useCallback(async () => {
    try {
      setError(null);
      const response = await getWorkspaces();
      setWorkspaces(response.workspaces);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch workspaces';
      setError(message);
      addToast(message, 'error');
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await fetchWorkspaces();
    setRefreshing(false);
  };

  const handleDelete = async (workspaceId: string) => {
    if (!confirm(`Are you sure you want to delete workspace ${workspaceId}?`)) {
      return;
    }

    try {
      setDeletingId(workspaceId);
      await deleteWorkspace(workspaceId);
      addToast(`Workspace ${workspaceId} deleted successfully`, 'success');
      await fetchWorkspaces();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to delete workspace';
      addToast(message, 'error');
    } finally {
      setDeletingId(null);
    }
  };

  const handleViewDetail = async (workspaceId: string) => {
    try {
      const detail = await getWorkspaceById(workspaceId);
      setSelectedWorkspace(detail);
      const membersResp = await getWorkspaceMembers(workspaceId).catch(() => null);
      setMembers(membersResp?.members || []);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch workspace details';
      addToast(message, 'error');
    }
  };

  const handleAddMember = async () => {
    if (!selectedWorkspace) return;
    if (!memberForm.user_id.trim()) {
      addToast('User ID required', 'warning');
      return;
    }
    try {
      await addWorkspaceMember(selectedWorkspace.id, { user_id: memberForm.user_id.trim(), role: memberForm.role });
      const membersResp = await getWorkspaceMembers(selectedWorkspace.id).catch(() => null);
      setMembers(membersResp?.members || []);
      setMemberForm({ user_id: '', role: memberForm.role });
      addToast('Member added', 'success');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to add member';
      addToast(message, 'error');
    }
  };

  const handleRemoveMember = async (userId: string) => {
    if (!selectedWorkspace) return;
    try {
      await deleteWorkspaceMember(selectedWorkspace.id, userId);
      const membersResp = await getWorkspaceMembers(selectedWorkspace.id).catch(() => null);
      setMembers(membersResp?.members || []);
      addToast('Member removed', 'success');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to remove member';
      addToast(message, 'error');
    }
  };

  useEffect(() => {
    fetchWorkspaces();
  }, [fetchWorkspaces]);

  const filteredWorkspaces = workspaces.filter(ws =>
    ws.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
    ws.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    ws.owner.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (loading) {
    return (
      <div className={cn(
        "min-h-screen flex items-center justify-center transition-colors duration-300",
        isDark ? "bg-[hsl(230_25%_7%)]" : "bg-[hsl(220_20%_97%)]"
      )}>
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-text-muted" />
          <p className={cn(
            "transition-colors duration-300",
            isDark ? "text-slate-500" : "text-slate-500"
          )}>Loading workspaces...</p>
        </div>
      </div>
    );
  }

  return (
    <div className={cn(
      "min-h-screen bg-background transition-colors duration-300"
    )}>
      <div className="container mx-auto px-4 py-8 relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          <div className="lg:col-span-1">
            <Sidebar variant="admin" />
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
                    <div className="flex h-12 w-12 items-center justify-center rounded-md border bg-muted text-text-primary">
                      <Shield className="w-7 h-7" />
                    </div>
                    <div>
                      <h1 className={cn(
                        "text-2xl font-bold transition-colors duration-300",
                        isDark ? "text-white" : "text-slate-900"
                      )}>Workspace Management</h1>
                      <p className={cn(
                        "transition-colors duration-300",
                        isDark ? "text-slate-400" : "text-slate-600"
                      )}>Manage all workspaces in the system</p>
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

            {/* Search and Filter */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
            >
              <Card className="p-4">
                <div className="flex flex-col md:flex-row gap-4">
                  <div className="flex-1 relative">
                    <Search className={cn(
                      "absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4",
                      isDark ? "text-slate-500" : "text-slate-400"
                    )} />
                    <input
                      type="text"
                      placeholder="Search workspaces..."
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
                  <Badge variant="info">{filteredWorkspaces.length} workspaces</Badge>
                </div>
              </Card>
            </motion.div>

            {/* Error Display */}
            {error && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.15 }}
              >
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
                        <X className={cn(
                          "w-5 h-5",
                          isDark ? "text-red-400" : "text-red-600"
                        )} />
                      </div>
                      <div>
                        <h4 className={cn(
                          "font-medium transition-colors duration-300",
                          isDark ? "text-white" : "text-slate-900"
                        )}>Error Loading Workspaces</h4>
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

            {/* Workspaces Table */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.2 }}
            >
              <Card>
                <CardHeader title="All Workspaces" description={`Showing ${filteredWorkspaces.length} workspaces`} />
                <CardContent>
                  {filteredWorkspaces.length === 0 ? (
                    <div className={cn(
                      "text-center py-8 transition-colors duration-300",
                      isDark ? "text-slate-500" : "text-slate-500"
                    )}>
                      No workspaces found
                    </div>
                  ) : (
                    <div className="overflow-x-auto">
                      <table className="w-full">
                        <thead>
                          <tr className={cn(
                            "text-left text-xs uppercase tracking-wider transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>
                            <th className="pb-3 pl-2">Workspace ID</th>
                            <th className="pb-3">Name</th>
                            <th className="pb-3">Owner</th>
                            <th className="pb-3">Status</th>
                            <th className="pb-3">Created</th>
                            <th className="pb-3 pr-2 text-right">Actions</th>
                          </tr>
                        </thead>
                        <tbody className={cn(
                          "divide-y transition-colors duration-300",
                          isDark ? "divide-white/5" : "divide-slate-100"
                        )}>
                          {filteredWorkspaces.map((workspace) => (
                            <tr key={workspace.id} className={cn(
                              "transition-colors",
                              isDark ? "hover:bg-white/5" : "hover:bg-slate-50"
                            )}>
                              <td className="py-3 pl-2">
                                <span className={cn(
                                  "font-mono text-sm transition-colors duration-300",
                                  isDark ? "text-white" : "text-slate-900"
                                )}>{workspace.id}</span>
                              </td>
                              <td className="py-3">
                                <span className={cn(
                                  "text-sm transition-colors duration-300",
                                  isDark ? "text-white" : "text-slate-900"
                                )}>{workspace.name}</span>
                              </td>
                              <td className="py-3">
                                <span className={cn(
                                  "text-sm transition-colors duration-300",
                                  isDark ? "text-slate-400" : "text-slate-600"
                                )}>{workspace.owner}</span>
                              </td>
                              <td className="py-3">
                                <Badge variant={workspace.status === 'active' ? 'success' : 'default'}>
                                  {workspace.status}
                                </Badge>
                              </td>
                              <td className="py-3">
                                <span className={cn(
                                  "text-sm transition-colors duration-300",
                                  isDark ? "text-slate-500" : "text-slate-500"
                                )}>{new Date(workspace.created_at).toLocaleDateString()}</span>
                              </td>
                              <td className="py-3 pr-2">
                                <div className="flex items-center justify-end gap-2">
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => handleViewDetail(workspace.id)}
                                    title="View Details"
                                  >
                                    <Eye className="w-4 h-4" />
                                  </Button>
                                  <Button
                                    size="sm"
                                    variant="danger"
                                    onClick={() => handleDelete(workspace.id)}
                                    disabled={deletingId === workspace.id}
                                    title="Delete"
                                  >
                                    {deletingId === workspace.id ? (
                                      <Loader2 className="w-4 h-4 animate-spin" />
                                    ) : (
                                      <Trash2 className="w-4 h-4" />
                                    )}
                                  </Button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </CardContent>
              </Card>
            </motion.div>
          </div>
        </div>
      </div>

      {/* Workspace Detail Modal */}
      {selectedWorkspace && (
        <WorkspaceDetailModal
          workspace={selectedWorkspace}
          onClose={() => setSelectedWorkspace(null)}
          isDark={isDark}
          members={members}
          memberForm={memberForm}
          onMemberFormChange={setMemberForm}
          onAddMember={handleAddMember}
          onRemoveMember={handleRemoveMember}
        />
      )}
    </div>
  );
}

export default function AdminWorkspacesPage() {
  return (
    <ToastProvider>
      <WorkspacesContent />
    </ToastProvider>
  );
}
