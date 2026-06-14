import Link from 'next/link';
import { ArrowLeft, LockKeyhole, ServerCog, ShieldCheck } from 'lucide-react';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';

export default function AdminSignupPage() {
  return (
    <main className="console-page min-h-screen px-6 py-8">
      <div className="console-container flex min-h-[calc(100vh-4rem)] items-center justify-center">
        <section className="console-shell w-full max-w-2xl rounded-2xl p-8">
          <Link href="/admin/login" className="mb-8 inline-flex items-center gap-2 text-sm text-text-secondary hover:text-text-primary">
            <ArrowLeft className="h-4 w-4" />
            Back to admin login
          </Link>

          <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="console-kicker">Bootstrap policy</p>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-text-primary">Admin signup is closed.</h1>
              <p className="mt-4 max-w-xl text-sm leading-6 text-text-secondary">
                The portal is an operator control plane, not a public application. Browser-based signup is disabled unless deployment explicitly sets <span className="font-mono text-text-primary">PORTAL_SIGNUP_ENABLED=1</span> for a controlled bootstrap window.
              </p>
            </div>
            <Badge variant="warning" dot>Default closed</Badge>
          </div>

          <div className="mt-8 grid gap-4 sm:grid-cols-3">
            <div className="rounded-xl border bg-card p-4">
              <ShieldCheck className="h-5 w-5 text-text-primary" />
              <p className="mt-3 text-sm font-medium text-text-primary">RBAC first</p>
              <p className="mt-2 text-xs leading-5 text-text-muted">Admin routes verify the authenticated role before showing data.</p>
            </div>
            <div className="rounded-xl border bg-card p-4">
              <LockKeyhole className="h-5 w-5 text-text-primary" />
              <p className="mt-3 text-sm font-medium text-text-primary">No public self-serve</p>
              <p className="mt-2 text-xs leading-5 text-text-muted">Normal accounts cannot browse the admin console.</p>
            </div>
            <div className="rounded-xl border bg-card p-4">
              <ServerCog className="h-5 w-5 text-text-primary" />
              <p className="mt-3 text-sm font-medium text-text-primary">Provisioned ops</p>
              <p className="mt-2 text-xs leading-5 text-text-muted">Create admin users from deployment scripts or a protected bootstrap process.</p>
            </div>
          </div>

          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/admin/login">
              <Button>Use existing admin account</Button>
            </Link>
            <Link href="/">
              <Button variant="secondary">View product model</Button>
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
