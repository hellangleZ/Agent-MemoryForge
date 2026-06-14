'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowRight, Braces, Database, KeyRound, ServerCog, ShieldCheck, Terminal } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { clearToken, getMe, isAuthError, setToken } from '@/lib/api';

export default function HomePage() {
  const router = useRouter();
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    let cancelled = false;

    getMe()
      .then((me) => {
        if (cancelled) return;
        setToken('1');
        router.replace(me.role === 'admin' ? '/admin' : '/workspace');
      })
      .catch((error) => {
        if (isAuthError(error)) clearToken();
        if (!cancelled) setCheckingSession(false);
      });

    return () => {
      cancelled = true;
    };
  }, [router]);

  if (checkingSession) {
    return (
      <main className="console-page flex min-h-screen items-center justify-center px-6">
        <div className="text-center">
          <div className="mx-auto h-5 w-5 animate-spin rounded-full border-2 border-border border-t-foreground" />
          <p className="mt-3 text-sm text-text-muted">Checking portal session...</p>
        </div>
      </main>
    );
  }

  return (
    <main className="console-page min-h-screen px-6 py-8">
      <div className="console-container">
        <header className="flex items-center justify-between border-b py-5">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg border bg-foreground text-background">
              <Braces className="h-4 w-4" />
            </div>
            <div>
              <p className="text-sm font-semibold text-text-primary">Agent-MemoryForge</p>
              <p className="text-xs text-text-muted">SDK + Memory Service</p>
            </div>
          </div>
          <Link href="/admin/login">
            <Button size="sm">Admin login</Button>
          </Link>
        </header>

        <section className="grid min-h-[calc(100vh-8rem)] items-center gap-12 py-16 lg:grid-cols-[1.05fr_0.95fr]">
          <div>
            <Badge variant="info">Product definition</Badge>
            <h1 className="mt-6 text-balance text-5xl font-semibold tracking-[-0.055em] text-text-primary sm:text-6xl">
              SDK first. Portal second.
            </h1>
            <p className="mt-6 max-w-2xl text-base leading-7 text-text-secondary">
              Agent-MemoryForge is a developer SDK backed by a Memory Service. The portal is not a self-serve app surface; it is an admin/developer control plane for operating and debugging that runtime.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/admin/login">
                <Button>
                  Open control plane
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
              <Link href="/admin/signup">
                <Button variant="secondary">Admin provisioning policy</Button>
              </Link>
            </div>
          </div>

          <div className="console-shell rounded-2xl p-5">
            <div className="grid gap-3">
              {[
                { icon: Braces, title: 'SDK', body: 'Primary integration surface for application developers.' },
                { icon: Database, title: 'Memory Service', body: 'Runtime storage, retrieval, indexing, and context assembly.' },
                { icon: ShieldCheck, title: 'Portal', body: 'Protected console for admins, operators, and debugging workflows.' },
              ].map((item) => (
                <div key={item.title} className="rounded-xl border bg-card p-5">
                  <item.icon className="h-5 w-5 text-text-primary" />
                  <h2 className="mt-4 text-sm font-semibold text-text-primary">{item.title}</h2>
                  <p className="mt-2 text-sm leading-6 text-text-secondary">{item.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="grid gap-4 border-t py-8 md:grid-cols-3">
          <div className="rounded-xl border bg-card p-5">
            <ServerCog className="h-5 w-5 text-text-primary" />
            <p className="mt-4 text-sm font-medium text-text-primary">Workspace policy</p>
            <p className="mt-2 text-sm leading-6 text-text-muted">Tenant and workspace settings are admin-controlled.</p>
          </div>
          <div className="rounded-xl border bg-card p-5">
            <Terminal className="h-5 w-5 text-text-primary" />
            <p className="mt-4 text-sm font-medium text-text-primary">Run traces</p>
            <p className="mt-2 text-sm leading-6 text-text-muted">Trace IDs connect SDK requests to backend execution.</p>
          </div>
          <div className="rounded-xl border bg-card p-5">
            <KeyRound className="h-5 w-5 text-text-primary" />
            <p className="mt-4 text-sm font-medium text-text-primary">No public signup</p>
            <p className="mt-2 text-sm leading-6 text-text-muted">Admin accounts are provisioned through deployment/bootstrap.</p>
          </div>
        </section>
      </div>
    </main>
  );
}
