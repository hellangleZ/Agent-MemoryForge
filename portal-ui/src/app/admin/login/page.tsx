'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { ArrowRight, Braces, Lock, ShieldCheck, User } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { adminLogin, clearToken, getMe, logout } from '@/lib/api';

function stringifyErrorDetail(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === 'string') return item;
        if (item && typeof item === 'object' && 'msg' in item) return String(item.msg);
        return JSON.stringify(item);
      })
      .join('; ');
  }
  if (value && typeof value === 'object' && 'msg' in value) return String(value.msg);
  if (value && typeof value === 'object') return JSON.stringify(value);
  return 'Login failed';
}

function readableError(error: unknown) {
  if (!(error instanceof Error)) return 'Login failed';
  try {
    const parsed = JSON.parse(error.message) as { status?: number; body?: { detail?: string; error?: string; raw?: string } };
    return stringifyErrorDetail(parsed.body?.detail || parsed.body?.error || parsed.body?.raw) || `Login failed (${parsed.status || 'unknown'})`;
  } catch {
    return error.message || 'Login failed';
  }
}

function AdminLoginContent() {
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextParam = searchParams.get('next');
  const target = nextParam?.startsWith('/admin') && !nextParam.startsWith('/admin/login') && !nextParam.startsWith('/admin/signup') ? nextParam : '/admin';

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    setLoading(true);

    try {
      await adminLogin(formData.username.trim(), formData.password);
      const me = await getMe();
      if (me.role !== 'admin') {
        await logout().catch(() => null);
        clearToken();
        setError('This account is authenticated, but it is not an admin account.');
        return;
      }
      router.replace(target);
    } catch (err) {
      clearToken();
      setError(readableError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="console-page min-h-screen px-6 py-8">
      <div className="console-container grid min-h-[calc(100vh-4rem)] items-center gap-10 lg:grid-cols-[1.05fr_0.95fr]">
        <section className="max-w-2xl">
          <div className="mb-8 inline-flex items-center gap-2 rounded-full border bg-card px-3 py-1 text-xs text-text-secondary shadow-sm">
            <ShieldCheck className="h-3.5 w-3.5" />
            Admin-only control plane
          </div>
          <p className="console-kicker">Agent-MemoryForge</p>
          <h1 className="mt-4 text-balance text-4xl font-semibold tracking-[-0.04em] text-text-primary sm:text-5xl">
            Operate the memory layer behind the API.
          </h1>
          <p className="mt-5 max-w-xl text-base leading-7 text-text-secondary">
            The Gateway API and official Python SDK are the developer integration surfaces. This portal is the control plane for workspace scope, memory inspection, run traces, MCP policy, quotas, and account operations.
          </p>
          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            {['Tenant/workspace/user isolation', 'Trace debugging', 'Tool policy'].map((item) => (
              <div key={item} className="rounded-xl border bg-card p-4 shadow-sm">
                <p className="text-sm font-medium text-text-primary">{item}</p>
                <p className="mt-2 text-xs leading-5 text-text-muted">Admin session required. Backend RBAC enforced.</p>
              </div>
            ))}
          </div>
        </section>

        <section className="console-shell rounded-2xl p-6 sm:p-8">
          <div className="mb-8 flex items-start justify-between gap-4">
            <div>
              <div className="flex h-10 w-10 items-center justify-center rounded-lg border bg-foreground text-background">
                <Braces className="h-5 w-5" />
              </div>
              <h2 className="mt-5 text-2xl font-semibold tracking-tight text-text-primary">Admin sign in</h2>
              <p className="mt-2 text-sm text-text-secondary">Use a provisioned administrator account.</p>
            </div>
            <Badge variant="success" dot>Gated</Badge>
          </div>

          {error && (
            <div className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/25 dark:bg-red-500/10 dark:text-red-300">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <label className="block">
              <span className="text-sm font-medium text-text-secondary">Username</span>
              <span className="relative mt-1.5 block">
                <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                <input
                  type="text"
                  value={formData.username}
                  onChange={(event) => setFormData({ ...formData, username: event.target.value })}
                  className="h-10 w-full rounded-md border bg-card pl-9 pr-3 text-sm text-text-primary shadow-sm outline-none transition-colors placeholder:text-text-muted focus:ring-2 focus:ring-ring/15"
                  placeholder="portal_admin"
                  autoComplete="username"
                  required
                />
              </span>
            </label>

            <label className="block">
              <span className="text-sm font-medium text-text-secondary">Password</span>
              <span className="relative mt-1.5 block">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                <input
                  type="password"
                  value={formData.password}
                  onChange={(event) => setFormData({ ...formData, password: event.target.value })}
                  className="h-10 w-full rounded-md border bg-card pl-9 pr-3 text-sm text-text-primary shadow-sm outline-none transition-colors placeholder:text-text-muted focus:ring-2 focus:ring-ring/15"
                  placeholder="Admin password"
                  autoComplete="current-password"
                  required
                />
              </span>
            </label>

            <Button type="submit" loading={loading} className="w-full">
              Continue to console
              <ArrowRight className="h-4 w-4" />
            </Button>
          </form>

          <p className="mt-4 text-center text-sm text-text-secondary">
            Employee account? <Link href="/login" className="font-medium text-text-primary underline underline-offset-4">Use workspace login</Link>.
          </p>

          <div className="mt-6 rounded-lg border bg-muted/50 p-4 text-sm leading-6 text-text-secondary">
            Public signup is disabled by default. Admin accounts should be created during deployment/bootstrap, not self-served from the browser.
            <Link href="/admin/signup" className="ml-1 font-medium text-text-primary underline underline-offset-4">Why?</Link>
          </div>
        </section>
      </div>
    </main>
  );
}

export default function AdminLoginPage() {
  return (
    <Suspense fallback={null}>
      <AdminLoginContent />
    </Suspense>
  );
}
