import Link from 'next/link';
import { ArrowLeft, LockKeyhole } from 'lucide-react';
import { Button } from '@/components/ui/Button';

export default function SignupPage() {
  return (
    <main className="console-page flex min-h-screen items-center justify-center px-6 py-8">
      <section className="console-shell w-full max-w-xl rounded-2xl p-8">
        <Link href="/" className="mb-8 inline-flex items-center gap-2 text-sm text-text-secondary hover:text-text-primary">
          <ArrowLeft className="h-4 w-4" />
          Back
        </Link>
        <LockKeyhole className="h-7 w-7 text-text-primary" />
        <h1 className="mt-5 text-3xl font-semibold tracking-tight text-text-primary">Public signup is disabled.</h1>
        <p className="mt-4 text-sm leading-6 text-text-secondary">
          This portal is an internal control plane for the SDK and Memory Service. Accounts must be provisioned by an operator; the browser signup form is intentionally unavailable.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link href="/admin/login"><Button>Admin login</Button></Link>
          <Link href="/"><Button variant="secondary">Product model</Button></Link>
        </div>
      </section>
    </main>
  );
}
