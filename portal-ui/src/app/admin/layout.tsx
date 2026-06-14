'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { clearToken, getMe } from '@/lib/api';

const publicAdminPaths = new Set(['/admin/login', '/admin/signup']);

type GuardState = 'checking' | 'allowed' | 'denied';

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isPublic = useMemo(() => publicAdminPaths.has(pathname), [pathname]);
  const [state, setState] = useState<GuardState>(isPublic ? 'allowed' : 'checking');
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (isPublic) {
      setState('allowed');
      return;
    }

    let cancelled = false;
    setState('checking');
    setMessage('');

    getMe()
      .then((me) => {
        if (cancelled) return;
        if (me.role === 'admin') {
          setState('allowed');
          return;
        }
        setMessage(`Current role is "${me.role || 'unknown'}". Admin role is required.`);
        setState('denied');
      })
      .catch(() => {
        if (cancelled) return;
        clearToken();
        router.replace(`/admin/login?next=${encodeURIComponent(pathname)}`);
      });

    return () => {
      cancelled = true;
    };
  }, [isPublic, pathname, router]);

  if (isPublic || state === 'allowed') {
    return <>{children}</>;
  }

  if (state === 'denied') {
    return (
      <main className="console-page flex min-h-screen items-center justify-center px-6">
        <section className="console-shell w-full max-w-lg rounded-2xl p-8">
          <p className="console-kicker">403 / Admin only</p>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight text-text-primary">This portal is not a public workspace.</h1>
          <p className="mt-3 text-sm leading-6 text-text-secondary">
            {message || 'The current session is authenticated but is not allowed to access the admin control plane.'}
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link href="/admin/login">
              <Button variant="primary">Use admin account</Button>
            </Link>
            <Link href="/logout">
              <Button variant="secondary">Sign out</Button>
            </Link>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="console-page flex min-h-screen items-center justify-center px-6">
      <div className="text-center">
        <div className="mx-auto h-5 w-5 animate-spin rounded-full border-2 border-border border-t-foreground" />
        <p className="mt-3 text-sm text-text-muted">Checking admin session...</p>
      </div>
    </main>
  );
}
