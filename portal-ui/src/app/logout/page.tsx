'use client';

import { useCallback, useEffect, useState } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { Card, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import { logout, clearToken, hasToken } from '@/lib/api';
import { logError } from '@/lib/errorTracking';
import { motion } from 'framer-motion';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { LogOut, AlertTriangle, CheckCircle, ArrowRight } from 'lucide-react';

function LogoutContent() {
  const { addToast } = useToast();
  const router = useRouter();
  const [countdown, setCountdown] = useState(3);
  const [isHydrated, setIsHydrated] = useState(false);
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  useEffect(() => {
    setIsLoggedIn(hasToken());
    setIsHydrated(true);
  }, []);

  const handleLogout = useCallback(async () => {
    try { await logout().catch(() => {}); } catch (err: unknown) {
      const error = err instanceof Error ? err : new Error('Logout error');
      logError(error, { component: 'LogoutPage', action: 'handleLogout' });
    }
    finally {
      clearToken();
      setIsLoggedIn(false);
      addToast('Successfully logged out', 'success');
      router.push('/login');
    }
  }, [addToast, router]);

  useEffect(() => {
    if (!isHydrated) return;
    if (!isLoggedIn) {
      const timer = setTimeout(() => router.push('/login'), 1000);
      return () => clearTimeout(timer);
    }
  }, [isHydrated, isLoggedIn, router]);

  useEffect(() => {
    if (!isHydrated || !isLoggedIn) return;
    const timer = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) { clearInterval(timer); handleLogout(); return 0; }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [handleLogout, isHydrated, isLoggedIn]);

  if (!isHydrated) {
    return <div className="min-h-screen" />;
  }

  if (!isLoggedIn) {
    return (
      <div className="min-h-screen">
        <div className="fixed inset-0 -z-10">
          <div className="absolute inset-0 bg-gradient-to-br from-brand-500/10 via-transparent to-cyan-500/10" />
        </div>
        <div className="container mx-auto px-4 py-8">
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
            <div className="lg:col-span-1"><Sidebar variant="customer" /></div>
            <div className="lg:col-span-3">
              <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
                <Card className="max-w-md mx-auto">
                  <CardContent className="p-8 text-center">
                    <div className="w-16 h-16 rounded-2xl bg-green-500/10 flex items-center justify-center mx-auto mb-4">
                      <CheckCircle className="w-8 h-8 text-green-400" />
                    </div>
                    <h2 className="text-2xl font-bold text-text-primary mb-2">Already Logged Out</h2>
                    <p className="text-text-secondary mb-6">You are not currently logged in.</p>
                    <Link href="/login"><Button>Sign In <ArrowRight className="w-4 h-4" /></Button></Link>
                  </CardContent>
                </Card>
              </motion.div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <div className="fixed inset-0 -z-10">
        <div className="absolute inset-0 bg-gradient-to-br from-brand-500/10 via-transparent to-cyan-500/10" />
        <div className="absolute top-0 left-1/4 w-96 h-96 bg-brand-500/20 rounded-full blur-3xl" />
      </div>
      
      <div className="container mx-auto px-4 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          <div className="lg:col-span-1"><Sidebar variant="customer" /></div>
          <div className="lg:col-span-3">
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
              <Card className="max-w-md mx-auto">
                <CardContent className="p-8 text-center">
                  <div className="w-16 h-16 rounded-2xl bg-amber-500/10 flex items-center justify-center mx-auto mb-4">
                    <AlertTriangle className="w-8 h-8 text-amber-400" />
                  </div>
                  <h2 className="text-2xl font-bold text-text-primary mb-2">Confirm Logout</h2>
                  <p className="text-text-secondary mb-6">Are you sure you want to sign out?</p>
                  <div className="space-y-4">
                    <div className="p-4 rounded-xl bg-white/5 border border-white/10 text-left">
                      <h4 className="text-sm font-medium text-text-primary mb-2">What happens when you logout:</h4>
                      <ul className="text-sm text-text-muted space-y-1">
                        <li className="flex items-center gap-2"><CheckCircle className="w-4 h-4 text-green-400" />Your session token will be cleared</li>
                        <li className="flex items-center gap-2"><CheckCircle className="w-4 h-4 text-green-400" />You will be redirected to login page</li>
                        <li className="flex items-center gap-2"><CheckCircle className="w-4 h-4 text-green-400" />Your workspace configuration is saved</li>
                      </ul>
                    </div>
                    <div className="flex flex-col gap-3">
                      <Button variant="danger" onClick={handleLogout} className="w-full"><LogOut className="w-4 h-4" />Yes, Logout</Button>
                      <Link href="/" className="w-full"><Button variant="secondary" className="w-full">Cancel</Button></Link>
                    </div>
                    <p className="text-xs text-text-muted text-center">Auto redirecting in {countdown} seconds...</p>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function LogoutPage() {
  return (<ToastProvider><LogoutContent /></ToastProvider>);
}
