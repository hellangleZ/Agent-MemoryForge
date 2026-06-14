'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import {
  AdminQuotaItem,
  AdminUsageItem,
  AdminUser,
  createAdminUser,
  deleteAdminUser,
  getAdminQuotas,
  getAdminUsage,
  getAdminUsers,
  getWorkspace,
  resetAdminUserPassword,
  setAdminQuota,
  updateAdminUser,
} from '@/lib/api';
import {
  Gauge,
  Loader2,
  KeyRound,
  Plus,
  RefreshCw,
  Save,
  Settings2,
  Shield,
  Trash2,
  UserRound,
  Users,
  X,
} from 'lucide-react';

type Role = 'admin' | 'user';

function formatDate(value?: string | null): string {
  if (!value) return 'never';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatNumber(value?: number | null): string {
  return new Intl.NumberFormat().format(Number(value || 0));
}

function formatUnixSeconds(value?: number | null): string {
  if (!value) return 'never';
  return formatDate(new Date(value * 1000).toISOString());
}

function workspaceDefault(): string {
  return getWorkspace() || 'ws_default';
}

function quotaForWorkspace(items: AdminQuotaItem[], workspaceId: string): AdminQuotaItem | undefined {
  return items.find((item) => item.workspace_id === workspaceId) || items[0];
}

function usageForWorkspace(items: AdminUsageItem[], workspaceId: string): AdminUsageItem | undefined {
  return items.find((item) => item.workspace_id === workspaceId) || items[0];
}

function AdminUsersContent() {
  const { addToast } = useToast();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [selectedId, setSelectedId] = useState<string>('');
  const [selectedLoading, setSelectedLoading] = useState(false);
  const [savingUser, setSavingUser] = useState(false);
  const [savingPassword, setSavingPassword] = useState(false);
  const [savingQuota, setSavingQuota] = useState(false);
  const [deletingUserId, setDeletingUserId] = useState<string>('');
  const [usageItems, setUsageItems] = useState<AdminUsageItem[]>([]);
  const [quotaItems, setQuotaItems] = useState<AdminQuotaItem[]>([]);
  const [userEdit, setUserEdit] = useState({ role: 'user' as Role, tenant_id: '' });
  const [quotaForm, setQuotaForm] = useState({
    workspace_id: workspaceDefault(),
    monthly_token_quota: '',
    enabled: false,
  });
  const [passwordForm, setPasswordForm] = useState({
    new_password: '',
    confirm_password: '',
  });
  const [form, setForm] = useState({
    username: '',
    password: '',
    role: 'user' as Role,
    tenant_id: '',
  });

  const selectedUser = useMemo(
    () => users.find((user) => user.id === selectedId) || null,
    [selectedId, users]
  );

  const loadUsers = useCallback(async (quiet = false) => {
    if (quiet) setRefreshing(true);
    try {
      const res = await getAdminUsers();
      setUsers(res.users || []);
    } catch {
      addToast('Failed to load users', 'error');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [addToast]);

  const loadUserControls = useCallback(async (user: AdminUser) => {
    const tenantId = user.tenant_id || '';
    const workspaceId = quotaForm.workspace_id || workspaceDefault();
    setSelectedLoading(true);
    try {
      const [usageRes, quotaRes] = await Promise.all([
        getAdminUsage({ tenant_id: tenantId, user_id: user.id }),
        getAdminQuotas({ tenant_id: tenantId, user_id: user.id }),
      ]);
      const usage = usageRes.data.items || [];
      const quotas = quotaRes.data.items || [];
      const quota = quotaForWorkspace(quotas, workspaceId);
      setUsageItems(usage);
      setQuotaItems(quotas);
      setUserEdit({ role: user.role as Role, tenant_id: tenantId });
      setQuotaForm({
        workspace_id: quota?.workspace_id || workspaceId,
        monthly_token_quota: quota ? String(quota.monthly_token_quota) : '',
        enabled: quota ? quota.enabled : false,
      });
      setPasswordForm({ new_password: '', confirm_password: '' });
    } catch {
      setUsageItems([]);
      setQuotaItems([]);
      addToast('Failed to load user controls', 'error');
    } finally {
      setSelectedLoading(false);
    }
  }, [addToast, quotaForm.workspace_id]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    if (!selectedUser) {
      setUsageItems([]);
      setQuotaItems([]);
      return;
    }
    void loadUserControls(selectedUser);
  }, [loadUserControls, selectedUser]);

  const counts = useMemo(() => {
    const admins = users.filter((user) => user.role === 'admin').length;
    return { admins, users: users.length - admins, total: users.length };
  }, [users]);

  const selectedUsage = useMemo(
    () => usageForWorkspace(usageItems, quotaForm.workspace_id),
    [quotaForm.workspace_id, usageItems]
  );

  const submit = async () => {
    const username = form.username.trim();
    const password = form.password;
    if (!username) {
      addToast('Username is required', 'error');
      return;
    }
    if (password.length < 8) {
      addToast('Password must be at least 8 characters', 'error');
      return;
    }

    setCreating(true);
    try {
      const created = await createAdminUser({
        username,
        password,
        role: form.role,
        tenant_id: form.tenant_id.trim() || undefined,
      });
      setForm((prev) => ({ ...prev, username: '', password: '' }));
      await loadUsers();
      setSelectedId(created.data.id);
      addToast('User created', 'success');
    } catch {
      addToast('Failed to create user', 'error');
    } finally {
      setCreating(false);
    }
  };

  const saveSelectedUser = async () => {
    if (!selectedUser) return;
    const tenantId = userEdit.tenant_id.trim();
    if (!tenantId) {
      addToast('Tenant ID is required', 'error');
      return;
    }
    setSavingUser(true);
    try {
      const res = await updateAdminUser(selectedUser.id, {
        role: userEdit.role,
        tenant_id: tenantId,
      });
      setUsers((prev) => prev.map((user) => (user.id === res.data.id ? res.data : user)));
      addToast('User updated', 'success');
    } catch {
      addToast('Failed to update user', 'error');
    } finally {
      setSavingUser(false);
    }
  };

  const resetSelectedPassword = async () => {
    if (!selectedUser) return;
    const nextPassword = passwordForm.new_password;
    if (nextPassword.length < 8) {
      addToast('New password must be at least 8 characters', 'error');
      return;
    }
    if (nextPassword !== passwordForm.confirm_password) {
      addToast('Passwords do not match', 'error');
      return;
    }

    setSavingPassword(true);
    try {
      await resetAdminUserPassword(selectedUser.id, { new_password: nextPassword });
      setPasswordForm({ new_password: '', confirm_password: '' });
      addToast('Password reset', 'success');
    } catch {
      addToast('Failed to reset password', 'error');
    } finally {
      setSavingPassword(false);
    }
  };

  const saveSelectedQuota = async () => {
    if (!selectedUser) return;
    const workspaceId = quotaForm.workspace_id.trim();
    const rawQuota = quotaForm.monthly_token_quota.trim();
    const quotaValue = rawQuota === '' ? 0 : Number(rawQuota);
    if (!workspaceId) {
      addToast('Workspace ID is required', 'error');
      return;
    }
    if (quotaForm.enabled && rawQuota === '') {
      addToast('Enter a token quota before enabling enforcement', 'error');
      return;
    }
    if (!Number.isFinite(quotaValue) || quotaValue < 0) {
      addToast('Quota must be a non-negative number', 'error');
      return;
    }
    if (quotaForm.enabled && quotaValue <= 0) {
      addToast('Quota must be greater than 0 when enforcement is enabled', 'error');
      return;
    }
    const normalizedQuota = Math.floor(quotaValue);
    setSavingQuota(true);
    try {
      await setAdminQuota({
        tenant_id: selectedUser.tenant_id || undefined,
        workspace_id: workspaceId,
        user_id: selectedUser.id,
        monthly_token_quota: normalizedQuota,
        enabled: quotaForm.enabled,
      });
      await loadUserControls(selectedUser);
      addToast('Quota updated', 'success');
    } catch {
      addToast('Failed to update quota', 'error');
    } finally {
      setSavingQuota(false);
    }
  };

  const removeUser = async (user: AdminUser) => {
    if (!window.confirm(`Delete ${user.id}? This removes login access and active quotas.`)) {
      return;
    }
    setDeletingUserId(user.id);
    try {
      await deleteAdminUser(user.id);
      setUsers((prev) => prev.filter((item) => item.id !== user.id));
      if (selectedId === user.id) setSelectedId('');
      addToast('User deleted', 'success');
    } catch {
      addToast('Failed to delete user', 'error');
    } finally {
      setDeletingUserId('');
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3 text-text-muted">
          <Loader2 className="h-8 w-8 animate-spin" />
          <p className="text-sm">Loading users</p>
        </div>
      </div>
    );
  }

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
                <div className="flex items-center gap-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-md border bg-muted text-text-primary">
                    <Users className="h-6 w-6" />
                  </div>
                  <div>
                    <h1 className="text-2xl font-semibold text-text-primary">Users</h1>
                    <p className="text-sm text-text-muted">Tenant accounts, roles, quotas, and access</p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="info">{counts.total} total</Badge>
                  <Badge variant="success">{counts.admins} admin</Badge>
                  <Badge variant="default">{counts.users} user</Badge>
                </div>
              </div>
            </Card>

            <Card>
              <CardHeader title="Create User" description="Provision a tenant-scoped portal account" />
              <CardContent className="space-y-4">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  <Input
                    label="Username"
                    value={form.username}
                    onChange={(event) => setForm((prev) => ({ ...prev, username: event.target.value }))}
                    placeholder="employee@example.com"
                    autoComplete="off"
                  />
                  <Input
                    label="Password"
                    type="password"
                    value={form.password}
                    onChange={(event) => setForm((prev) => ({ ...prev, password: event.target.value }))}
                    placeholder="Minimum 8 characters"
                    autoComplete="new-password"
                  />
                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-text-primary">Role</label>
                    <select
                      value={form.role}
                      onChange={(event) => setForm((prev) => ({ ...prev, role: event.target.value as Role }))}
                      className="h-10 w-full rounded-md border bg-card px-3 text-sm text-text-primary shadow-sm focus:outline-none focus:ring-2 focus:ring-ring/15"
                    >
                      <option value="user">User</option>
                      <option value="admin">Admin</option>
                    </select>
                  </div>
                  <Input
                    label="Tenant ID"
                    value={form.tenant_id}
                    onChange={(event) => setForm((prev) => ({ ...prev, tenant_id: event.target.value }))}
                    placeholder="Current tenant"
                    autoComplete="off"
                  />
                </div>
                <div className="flex justify-end">
                  <Button onClick={submit} loading={creating}>
                    <Plus className="h-4 w-4" />
                    Create user
                  </Button>
                </div>
              </CardContent>
            </Card>

            {selectedUser && (
              <Card>
                <CardHeader
                  title="User Controls"
                  description={`${selectedUser.id} / ${selectedUser.tenant_id || 'unknown tenant'}`}
                  action={
                    <Button variant="ghost" size="sm" onClick={() => setSelectedId('')}>
                      <X className="h-4 w-4" />
                      Close
                    </Button>
                  }
                />
                <CardContent className="space-y-6">
                  {selectedLoading ? (
                    <div className="flex min-h-[120px] items-center justify-center text-text-muted">
                      <Loader2 className="h-5 w-5 animate-spin" />
                    </div>
                  ) : (
                    <>
                      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                        <div>
                          <label className="mb-1.5 block text-sm font-medium text-text-primary">Role</label>
                          <select
                            value={userEdit.role}
                            onChange={(event) => setUserEdit((prev) => ({ ...prev, role: event.target.value as Role }))}
                            className="h-10 w-full rounded-md border bg-card px-3 text-sm text-text-primary shadow-sm focus:outline-none focus:ring-2 focus:ring-ring/15"
                          >
                            <option value="user">User</option>
                            <option value="admin">Admin</option>
                          </select>
                        </div>
                        <Input
                          label="Tenant ID"
                          value={userEdit.tenant_id}
                          onChange={(event) => setUserEdit((prev) => ({ ...prev, tenant_id: event.target.value }))}
                        />
                        <div className="flex items-end">
                          <Button className="w-full" onClick={saveSelectedUser} loading={savingUser}>
                            <Save className="h-4 w-4" />
                            Save user
                          </Button>
                        </div>
                      </div>

                      <div className="grid grid-cols-1 gap-4 border-t pt-5 md:grid-cols-3">
                        <Input
                          label="New password"
                          type="password"
                          value={passwordForm.new_password}
                          onChange={(event) => setPasswordForm((prev) => ({ ...prev, new_password: event.target.value }))}
                          placeholder="Minimum 8 characters"
                          autoComplete="new-password"
                        />
                        <Input
                          label="Confirm password"
                          type="password"
                          value={passwordForm.confirm_password}
                          onChange={(event) => setPasswordForm((prev) => ({ ...prev, confirm_password: event.target.value }))}
                          placeholder="Repeat new password"
                          autoComplete="new-password"
                        />
                        <div className="flex items-end">
                          <Button className="w-full" variant="secondary" onClick={resetSelectedPassword} loading={savingPassword}>
                            <KeyRound className="h-4 w-4" />
                            Reset password
                          </Button>
                        </div>
                      </div>

                      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
                        <Input
                          label="Workspace ID"
                          value={quotaForm.workspace_id}
                          onChange={(event) => setQuotaForm((prev) => ({ ...prev, workspace_id: event.target.value }))}
                        />
                        <Input
                          label="Monthly token quota"
                          type="number"
                          min={0}
                          value={quotaForm.monthly_token_quota}
                          onChange={(event) => setQuotaForm((prev) => ({ ...prev, monthly_token_quota: event.target.value }))}
                          placeholder="Unlimited"
                        />
                        <label className="flex h-10 items-center gap-2 self-end rounded-md border bg-card px-3 text-sm text-text-primary">
                          <input
                            type="checkbox"
                            checked={quotaForm.enabled}
                            onChange={(event) => setQuotaForm((prev) => ({ ...prev, enabled: event.target.checked }))}
                          />
                          Enforce quota
                        </label>
                        <div className="flex items-end">
                          <Button className="w-full" onClick={saveSelectedQuota} loading={savingQuota}>
                            <Gauge className="h-4 w-4" />
                            Save quota
                          </Button>
                        </div>
                      </div>

                      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                        <div className="rounded-md border bg-muted/30 p-3">
                          <p className="text-xs uppercase text-text-muted">Requests</p>
                          <p className="mt-1 text-xl font-semibold text-text-primary">{formatNumber(selectedUsage?.request_count)}</p>
                        </div>
                        <div className="rounded-md border bg-muted/30 p-3">
                          <p className="text-xs uppercase text-text-muted">Tokens used</p>
                          <p className="mt-1 text-xl font-semibold text-text-primary">{formatNumber(selectedUsage?.total_tokens)}</p>
                        </div>
                        <div className="rounded-md border bg-muted/30 p-3">
                          <p className="text-xs uppercase text-text-muted">Remaining</p>
                          <p className="mt-1 text-xl font-semibold text-text-primary">
                            {selectedUsage?.remaining_tokens == null ? 'unlimited' : formatNumber(selectedUsage.remaining_tokens)}
                          </p>
                        </div>
                        <div className="rounded-md border bg-muted/30 p-3">
                          <p className="text-xs uppercase text-text-muted">Quota state</p>
                          <div className="mt-2">
                            <Badge variant={selectedUsage?.blocked ? 'danger' : selectedUsage?.quota_enabled ? 'success' : 'default'}>
                              {selectedUsage?.blocked ? 'blocked' : selectedUsage?.quota_enabled ? 'enforced' : 'off'}
                            </Badge>
                          </div>
                        </div>
                      </div>

                      {quotaItems.length > 0 && (
                        <div className="overflow-x-auto">
                          <table className="w-full min-w-[640px] text-sm">
                            <thead>
                              <tr className="border-b text-left text-xs uppercase text-text-muted">
                                <th className="py-2 pr-4 font-medium">Workspace</th>
                                <th className="py-2 pr-4 font-medium">Quota</th>
                                <th className="py-2 pr-4 font-medium">Enabled</th>
                                <th className="py-2 pr-4 font-medium">Updated</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y">
                              {quotaItems.map((quota) => (
                                <tr key={`${quota.workspace_id}:${quota.user_id}`}>
                                  <td className="py-2 pr-4 font-mono text-xs text-text-muted">{quota.workspace_id}</td>
                                  <td className="py-2 pr-4 text-text-primary">{formatNumber(quota.monthly_token_quota)}</td>
                                  <td className="py-2 pr-4">
                                    <Badge variant={quota.enabled ? 'success' : 'default'}>{quota.enabled ? 'yes' : 'no'}</Badge>
                                  </td>
                                  <td className="py-2 pr-4 text-text-muted">{formatUnixSeconds(quota.updated_at)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}

                      <div className="flex justify-end border-t pt-4">
                        <Button variant="danger" onClick={() => removeUser(selectedUser)} loading={deletingUserId === selectedUser.id}>
                          <Trash2 className="h-4 w-4" />
                          Delete user
                        </Button>
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>
            )}

            <Card>
              <CardHeader
                title="User Directory"
                description="Stored accounts in the portal auth database"
                action={
                  <Button variant="secondary" size="sm" onClick={() => loadUsers(true)} loading={refreshing}>
                    <RefreshCw className="h-4 w-4" />
                    Refresh
                  </Button>
                }
              />
              <CardContent>
                {users.length === 0 ? (
                  <div className="flex min-h-[180px] flex-col items-center justify-center rounded-md border border-dashed p-6 text-center">
                    <UserRound className="h-8 w-8 text-text-muted" />
                    <h3 className="mt-3 text-sm font-medium text-text-primary">No users</h3>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[840px] text-sm">
                      <thead>
                        <tr className="border-b text-left text-xs uppercase text-text-muted">
                          <th className="py-3 pr-4 font-medium">User</th>
                          <th className="py-3 pr-4 font-medium">Role</th>
                          <th className="py-3 pr-4 font-medium">Tenant</th>
                          <th className="py-3 pr-4 font-medium">Created</th>
                          <th className="py-3 pl-4 text-right font-medium">Actions</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y">
                        {users.map((user) => (
                          <tr key={user.id} className={selectedId === user.id ? 'bg-muted/40' : 'hover:bg-muted/30'}>
                            <td className="py-3 pr-4">
                              <div className="flex items-center gap-3">
                                <div className="flex h-8 w-8 items-center justify-center rounded-full border bg-muted text-text-primary">
                                  {user.role === 'admin' ? <Shield className="h-4 w-4" /> : <UserRound className="h-4 w-4" />}
                                </div>
                                <div>
                                  <p className="font-medium text-text-primary">{user.id}</p>
                                  <p className="text-xs text-text-muted">{user.email}</p>
                                </div>
                              </div>
                            </td>
                            <td className="py-3 pr-4">
                              <Badge variant={user.role === 'admin' ? 'success' : 'default'}>{user.role}</Badge>
                            </td>
                            <td className="py-3 pr-4 font-mono text-xs text-text-muted">{user.tenant_id || 'unknown'}</td>
                            <td className="py-3 pr-4 text-text-muted">{formatDate(user.created_at)}</td>
                            <td className="py-3 pl-4">
                              <div className="flex justify-end gap-2">
                                <Button variant="secondary" size="sm" onClick={() => setSelectedId(user.id)}>
                                  <Settings2 className="h-4 w-4" />
                                  Manage
                                </Button>
                                <Button variant="ghost" size="sm" onClick={() => removeUser(user)} loading={deletingUserId === user.id}>
                                  <Trash2 className="h-4 w-4" />
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
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AdminUsersPage() {
  return (
    <ToastProvider>
      <AdminUsersContent />
    </ToastProvider>
  );
}
