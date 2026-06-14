'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowRight, Braces, Lock, User } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { clearToken, getMe, hasToken, isAuthError, login } from '@/lib/api';

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
    const detail = stringifyErrorDetail(parsed.body?.detail || parsed.body?.error || parsed.body?.raw) || 'Invalid credentials';
    return `Login failed: ${detail} (${parsed.status || 'unknown'})`;
  } catch {
    return `Login failed: ${error.message || 'unknown error'}`;
  }
}

export default function LoginPage() {
  const [formData, setFormData] = useState({ username: '', password: '' });
  const [alreadyLoggedIn, setAlreadyLoggedIn] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const router = useRouter();

  useEffect(() => {
    if (!hasToken()) {
      setAlreadyLoggedIn(false);
      return;
    }

    let cancelled = false;
    getMe()
      .then(() => {
        if (!cancelled) setAlreadyLoggedIn(true);
      })
      .catch((err) => {
        if (isAuthError(err)) clearToken();
        if (!cancelled) setAlreadyLoggedIn(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(formData.username.trim(), formData.password);
      router.push('/workspace');
    } catch (err) {
      setError(readableError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="console-page min-h-screen px-6 py-8">
      <div className="console-container grid min-h-[calc(100vh-4rem)] items-center gap-10 lg:grid-cols-[1.05fr_0.95fr]">
        <section className="max-w-2xl">
          <Badge variant="info">Developer workspace</Badge>
          <h1 className="mt-6 text-balance text-4xl font-semibold tracking-[-0.04em] text-text-primary sm:text-5xl">
            Sign in to a workspace-scoped session.
          </h1>
          <p className="mt-5 max-w-xl text-base leading-7 text-text-secondary">
            Normal sessions are scoped by tenant and workspace. Admin operations are separated under the protected control plane.
          </p>
          <div className="mt-8 rounded-xl border bg-card p-5 text-sm leading-6 text-text-secondary">
            Need the operator console? <Link href="/admin/login" className="font-medium text-text-primary underline underline-offset-4">Use admin login</Link>.
          </div>
        </section>

        <section className="console-shell rounded-2xl p-6 sm:p-8">
          <div className="mb-8">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg border bg-foreground text-background">
              <Braces className="h-5 w-5" />
            </div>
            <h2 className="mt-5 text-2xl font-semibold tracking-tight text-text-primary">Workspace login</h2>
            <p className="mt-2 text-sm text-text-secondary">Authenticate to call workspace-scoped APIs.</p>
          </div>

          {alreadyLoggedIn ? (
            <div className="rounded-lg border bg-muted/50 p-4">
              <h3 className="text-sm font-semibold text-text-primary">Already Logged In</h3>
              <p className="mt-2 text-sm leading-6 text-text-secondary">A portal session marker exists in this browser.</p>
              <div className="mt-4 flex flex-wrap gap-3">
                <Link href="/workspace"><Button>Open workspace</Button></Link>
                <Link href="/logout"><Button variant="secondary">Sign out</Button></Link>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}
              <label className="block">
                <span className="text-sm font-medium text-text-secondary">Username</span>
                <span className="relative mt-1.5 block">
                  <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-muted" />
                  <input
                    id="username"
                    type="text"
                    value={formData.username}
                    onChange={(event) => setFormData({ ...formData, username: event.target.value })}
                    className="h-10 w-full rounded-md border bg-card pl-9 pr-3 text-sm text-text-primary shadow-sm outline-none transition-colors placeholder:text-text-muted focus:ring-2 focus:ring-ring/15"
                    placeholder="username"
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
                    id="password"
                    type="password"
                    value={formData.password}
                    onChange={(event) => setFormData({ ...formData, password: event.target.value })}
                    className="h-10 w-full rounded-md border bg-card pl-9 pr-3 text-sm text-text-primary shadow-sm outline-none transition-colors placeholder:text-text-muted focus:ring-2 focus:ring-ring/15"
                    placeholder="password"
                    autoComplete="current-password"
                    required
                  />
                </span>
              </label>
              <Button type="submit" loading={loading} className="w-full">
                Sign in
                <ArrowRight className="h-4 w-4" />
              </Button>
            </form>
          )}
        </section>
      </div>
    </main>
  );
}
