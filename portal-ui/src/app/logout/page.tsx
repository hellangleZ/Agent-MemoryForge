'use client';

import { useCallback, useEffect, useState } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { Card, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import { logout, clearToken, getMe, isAuthError, setToken } from '@/lib/api';
import { logError } from '@/lib/errorTracking';
import Link from 'next/link';
import { LogOut, CheckCircle, ArrowRight } from 'lucide-react';

type LogoutState = 'checking' | 'authenticated' | 'unauthenticated';
type PortalVariant = 'admin' | 'customer';

function LogoutShell({ children, variant }: { children: React.ReactNode; variant: PortalVariant }) {
  return (
    <main className="console-page min-h-screen px-6 py-8">
      <div className="console-container grid gap-6 lg:grid-cols-[280px_1fr]">
        <Sidebar variant={variant} />
        <section className="flex min-h-[calc(100vh-4rem)] items-center justify-center">
          {children}
        </section>
      </div>
    </main>
  );
}

function LogoutContent() {
  const { addToast } = useToast();
  const [state, setState] = useState<LogoutState>('checking');
  const [returnHref, setReturnHref] = useState('/workspace');
  const [portalVariant, setPortalVariant] = useState<PortalVariant>('customer');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;

    getMe()
      .then((me) => {
        if (cancelled) return;
        const nextVariant = me.role === 'admin' ? 'admin' : 'customer';
        setToken('1');
        setPortalVariant(nextVariant);
        setReturnHref(nextVariant === 'admin' ? '/admin' : '/workspace');
        setState('authenticated');
      })
      .catch((error) => {
        if (isAuthError(error)) clearToken();
        if (!cancelled) setState('unauthenticated');
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogout = useCallback(async () => {
    setSubmitting(true);
    try {
      await logout().catch(() => {});
    } catch (err: unknown) {
      const error = err instanceof Error ? err : new Error('Logout error');
      logError(error, { component: 'LogoutPage', action: 'handleLogout' });
    } finally {
      clearToken();
      setState('unauthenticated');
      addToast('Successfully logged out', 'success');
      window.location.assign('/login');
      setSubmitting(false);
    }
  }, [addToast]);

  if (state === 'checking') {
    return (
      <main className="console-page flex min-h-screen items-center justify-center px-6">
        <div className="text-center">
          <div className="mx-auto h-5 w-5 animate-spin rounded-full border-2 border-border border-t-foreground" />
          <p className="mt-3 text-sm text-text-muted">Checking portal session...</p>
        </div>
      </main>
    );
  }

  if (state === 'unauthenticated') {
    return (
      <LogoutShell variant={portalVariant}>
        <Card className="w-full max-w-md">
          <CardContent className="p-8 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-lg border bg-muted text-text-primary">
              <CheckCircle className="h-5 w-5" />
            </div>
            <h2 className="mt-5 text-2xl font-semibold tracking-tight text-text-primary">Already logged out</h2>
            <p className="mt-2 text-sm leading-6 text-text-secondary">There is no active portal session in this browser.</p>
            <div className="mt-6 flex flex-col gap-3">
              <Link href="/login">
                <Button className="w-full">Sign in <ArrowRight className="h-4 w-4" /></Button>
              </Link>
              <Link href="/">
                <Button variant="secondary" className="w-full">Open portal home</Button>
              </Link>
            </div>
          </CardContent>
        </Card>
      </LogoutShell>
    );
  }

  return (
    <LogoutShell variant={portalVariant}>
      <Card className="w-full max-w-md">
        <CardContent className="p-8">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-lg border bg-foreground text-background">
            <LogOut className="h-5 w-5" />
          </div>
          <div className="text-center">
            <h2 className="mt-5 text-2xl font-semibold tracking-tight text-text-primary">Confirm logout</h2>
            <p className="mt-2 text-sm leading-6 text-text-secondary">
              Sign out only when you explicitly confirm. Visiting the portal home will keep this session.
            </p>
          </div>
          <div className="mt-6 rounded-lg border bg-muted/50 p-4">
            <h4 className="text-sm font-medium text-text-primary">What happens when you log out:</h4>
            <ul className="mt-3 space-y-2 text-sm text-text-secondary">
              <li className="flex items-center gap-2"><CheckCircle className="h-4 w-4 text-text-primary" />Your session token will be cleared.</li>
              <li className="flex items-center gap-2"><CheckCircle className="h-4 w-4 text-text-primary" />You will be redirected to the login page.</li>
              <li className="flex items-center gap-2"><CheckCircle className="h-4 w-4 text-text-primary" />Your workspace configuration stays saved.</li>
            </ul>
          </div>
          <div className="mt-6 flex flex-col gap-3">
            <Button variant="danger" onClick={handleLogout} loading={submitting} className="w-full"><LogOut className="h-4 w-4" />Sign out</Button>
            <Link href={returnHref} className="w-full">
              <Button variant="secondary" className="w-full">Stay signed in</Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    </LogoutShell>
  );
}

export default function LogoutPage() {
  return (<ToastProvider><LogoutContent /></ToastProvider>);
}
