'use client';

import { useEffect, useState } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { Card, CardHeader, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import { getMe, logout, setToken, clearToken, changePassword } from '@/lib/api';
import { useTheme } from '@/lib/theme';
import { logError } from '@/lib/errorTracking';
import { motion } from 'framer-motion';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { cn } from '@/lib/utils';
import {
  User,
  Mail,
  Shield,
  Key,
  LogOut,
  Clock,
  Loader2,
  AlertTriangle,
} from 'lucide-react';

interface UserInfo {
  id: string;
  email: string;
  role: string;
  created_at: string;
}

type AuthState = 'loading' | 'authenticated' | 'unauthenticated' | 'error';

function apiStatus(error: unknown): number | null {
  if (!(error instanceof Error)) return null;
  try {
    const parsed = JSON.parse(error.message) as { status?: number };
    return typeof parsed.status === 'number' ? parsed.status : null;
  } catch {
    return null;
  }
}

function ProfileContent() {
  const { addToast } = useToast();
  const { isDark } = useTheme();
  const router = useRouter();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [authState, setAuthState] = useState<AuthState>('loading');
  const loading = authState === 'loading';
  const isAuthenticated = authState === 'authenticated';
  const canEndSession = authState === 'authenticated' || authState === 'error';
  const [passwordChange, setPasswordChange] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  });
  const [passwordLoading, setPasswordLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const fetchUser = async () => {
      try {
        const userData = await getMe();
        if (cancelled) return;
        setUser(userData as UserInfo);
        setToken('1');
        setAuthState('authenticated');
      } catch (err: unknown) {
        if (cancelled) return;
        const error = err instanceof Error ? err : new Error('Failed to fetch user');
        const status = apiStatus(error);
        setUser(null);
        if (status === 401 || status === 403) {
          clearToken();
          setAuthState('unauthenticated');
        } else {
          logError(error, { component: 'ProfilePage', action: 'fetchUser', status });
          setAuthState('error');
        }
      }
    };

    fetchUser();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogout = async () => {
    try {
      await logout();
      clearToken();
      setUser(null);
      setAuthState('unauthenticated');
      addToast('Logged out successfully', 'success');
      setTimeout(() => {
        router.push('/login');
      }, 1000);
    } catch (err: unknown) {
      const error = err instanceof Error ? err : new Error('Logout failed');
      logError(error, { component: 'ProfilePage', action: 'logout' });
      clearToken();
      setUser(null);
      setAuthState('unauthenticated');
      addToast('Logged out', 'info');
      setTimeout(() => {
        router.push('/login');
      }, 1000);
    }
  };

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();

    if (passwordChange.newPassword !== passwordChange.confirmPassword) {
      addToast('Passwords do not match', 'error');
      return;
    }

    if (passwordChange.newPassword.length < 8) {
      addToast('Password must be at least 8 characters', 'error');
      return;
    }

    setPasswordLoading(true);
    try {
      await changePassword(passwordChange.currentPassword, passwordChange.newPassword);
      addToast('Password changed successfully', 'success');
      setPasswordChange({ currentPassword: '', newPassword: '', confirmPassword: '' });
    } catch (err: unknown) {
      addToast('Failed to change password', 'error');
    } finally {
      setPasswordLoading(false);
    }
  };

  const profileStatus =
    authState === 'authenticated'
      ? { label: 'Active', variant: 'success' as const }
      : authState === 'unauthenticated'
        ? { label: 'Sign in required', variant: 'warning' as const }
        : authState === 'error'
          ? { label: 'Unavailable', variant: 'danger' as const }
          : { label: 'Checking', variant: 'info' as const };

  const securityItems = [
    { icon: Shield, label: 'Workspace isolation', status: 'Active', variant: 'success' as const },
    { icon: Key, label: 'Password change', status: 'Available', variant: 'success' as const },
  ];

  const infoColors: Record<string, { bg: string; icon: string }> = {
    purple: {
      bg: 'bg-muted',
      icon: 'text-text-primary',
    },
    cyan: {
      bg: 'bg-muted',
      icon: 'text-text-primary',
    },
    green: {
      bg: 'bg-muted',
      icon: 'text-text-primary',
    },
    amber: {
      bg: 'bg-muted',
      icon: 'text-text-primary',
    },
    red: {
      bg: 'bg-muted',
      icon: 'text-text-primary',
    },
  };

  return (
    <div className={cn(
      "min-h-screen bg-background transition-colors duration-300"
    )}>
      <div className="container mx-auto px-4 py-8 relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          <div className="lg:col-span-1">
            <Sidebar variant="customer" />
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
                      <User className="w-7 h-7" />
                    </div>
                    <div>
                      <h1 className={cn(
                        "text-2xl font-bold transition-colors duration-300",
                        isDark ? "text-white" : "text-slate-900"
                      )}>User Profile</h1>
                      <p className={cn(
                        "transition-colors duration-300",
                        isDark ? "text-slate-400" : "text-slate-600"
                      )}>Manage your account settings</p>
                    </div>
                  </div>
                  {canEndSession && (
                    <div className="flex items-center gap-3">
                      <Button variant="danger" onClick={handleLogout}>
                        <LogOut className="w-4 h-4" />
                        Logout
                      </Button>
                    </div>
                  )}
                </div>
              </Card>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
            >
              <Card>
                <CardHeader
                  title="Profile Information"
                  description="Your account details"
                  action={<Badge variant={profileStatus.variant} dot>{profileStatus.label}</Badge>}
                />
                <CardContent>
                  {loading ? (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 className={cn(
                        "w-6 h-6 animate-spin",
                        isDark ? "text-slate-500" : "text-slate-400"
                      )} />
                    </div>
                  ) : user ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className={cn(
                        "flex items-center gap-4 p-4 rounded-xl border transition-colors duration-300",
                        isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"
                      )}>
                        <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", infoColors.purple.bg)}>
                          <Mail className={cn("w-5 h-5", infoColors.purple.icon)} />
                        </div>
                        <div>
                          <p className={cn(
                            "text-xs transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>Email</p>
                          <p className={cn(
                            "text-sm font-medium transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>{user.email || 'Not set'}</p>
                        </div>
                      </div>
                      <div className={cn(
                        "flex items-center gap-4 p-4 rounded-xl border transition-colors duration-300",
                        isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"
                      )}>
                        <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", infoColors.cyan.bg)}>
                          <Shield className={cn("w-5 h-5", infoColors.cyan.icon)} />
                        </div>
                        <div>
                          <p className={cn(
                            "text-xs transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>Role</p>
                          <p className={cn(
                            "text-sm font-medium capitalize transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>{user.role}</p>
                        </div>
                      </div>
                      <div className={cn(
                        "flex items-center gap-4 p-4 rounded-xl border transition-colors duration-300",
                        isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"
                      )}>
                        <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", infoColors.green.bg)}>
                          <Key className={cn("w-5 h-5", infoColors.green.icon)} />
                        </div>
                        <div>
                          <p className={cn(
                            "text-xs transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>User ID</p>
                          <p className={cn(
                            "text-sm font-mono truncate transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>{user.id}</p>
                        </div>
                      </div>
                      <div className={cn(
                        "flex items-center gap-4 p-4 rounded-xl border transition-colors duration-300",
                        isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"
                      )}>
                        <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", infoColors.amber.bg)}>
                          <Clock className={cn("w-5 h-5", infoColors.amber.icon)} />
                        </div>
                        <div>
                          <p className={cn(
                            "text-xs transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>Created</p>
                          <p className={cn(
                            "text-sm font-medium transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>
                            {user.created_at ? new Date(user.created_at).toLocaleDateString() : 'Unknown'}
                          </p>
                        </div>
                      </div>
                    </div>
                  ) : authState === 'unauthenticated' ? (
                    <div className="text-center py-8">
                      <AlertTriangle className={cn(
                        "w-12 h-12 mx-auto mb-4",
                        isDark ? "text-amber-400" : "text-amber-600"
                      )} />
                      <p className={cn(
                        "mb-4 transition-colors duration-300",
                        isDark ? "text-slate-400" : "text-slate-600"
                      )}>Your session has expired. Sign in again to view your profile.</p>
                      <Link href="/login">
                        <Button>Sign In</Button>
                      </Link>
                    </div>
                  ) : (
                    <div className="text-center py-8">
                      <AlertTriangle className={cn(
                        "w-12 h-12 mx-auto mb-4",
                        isDark ? "text-red-400" : "text-red-600"
                      )} />
                      <p className={cn(
                        "mb-4 transition-colors duration-300",
                        isDark ? "text-slate-400" : "text-slate-600"
                      )}>Profile is unavailable. Refresh the page or sign in again.</p>
                      <div className="flex justify-center gap-3">
                        <Button variant="secondary" onClick={() => window.location.reload()}>Refresh</Button>
                        <Link href="/login">
                          <Button>Sign In</Button>
                        </Link>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </motion.div>

            {isAuthenticated && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.2 }}
              >
                <Card>
                  <CardHeader title="Change Password" description="Update your account password" />
                  <CardContent>
                    <form onSubmit={handlePasswordChange} className="space-y-4 max-w-md">
                      <Input
                        id="current_password"
                        label="Current Password"
                        type="password"
                        value={passwordChange.currentPassword}
                        onChange={(e) => setPasswordChange(prev => ({ ...prev, currentPassword: e.target.value }))}
                      />
                      <Input
                        id="new_password"
                        label="New Password"
                        type="password"
                        value={passwordChange.newPassword}
                        onChange={(e) => setPasswordChange(prev => ({ ...prev, newPassword: e.target.value }))}
                      />
                      <Input
                        id="confirm_password"
                        label="Confirm New Password"
                        type="password"
                        value={passwordChange.confirmPassword}
                        onChange={(e) => setPasswordChange(prev => ({ ...prev, confirmPassword: e.target.value }))}
                      />
                      <Button type="submit" loading={passwordLoading}>
                        <Key className="w-4 h-4" />
                        Change Password
                      </Button>
                    </form>
                  </CardContent>
                </Card>
              </motion.div>
            )}

            {isAuthenticated && (
              <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.3 }}
              >
                <Card>
                  <CardHeader title="Security Settings" description="Account protection status" />
                  <CardContent>
                    <div className="space-y-3">
                      {securityItems.map((item, index) => (
                        <div
                          key={index}
                          className={cn(
                            "flex items-center gap-4 p-4 rounded-xl border transition-colors duration-300",
                            isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"
                          )}
                        >
                          <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", infoColors.purple.bg)}>
                            <item.icon className={cn("w-5 h-5", infoColors.purple.icon)} />
                          </div>
                          <div className="flex-1">
                            <p className={cn(
                              "text-sm font-medium transition-colors duration-300",
                              isDark ? "text-white" : "text-slate-900"
                            )}>{item.label}</p>
                            <p className={cn(
                              "text-xs transition-colors duration-300",
                              isDark ? "text-slate-500" : "text-slate-500"
                            )}>{item.status}</p>
                          </div>
                          <Badge variant={item.variant}>{item.status}</Badge>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            )}

            {canEndSession && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.4 }}
              >
                <Card className={cn(
                  "border transition-colors duration-300",
                  isDark ? "border-red-500/20" : "border-red-200"
                )}>
                  <CardContent className="p-6">
                    <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                      <div className="flex items-center gap-4">
                        <div className={cn("w-12 h-12 rounded-xl flex items-center justify-center", infoColors.red.bg)}>
                          <LogOut className={cn("w-6 h-6", infoColors.red.icon)} />
                        </div>
                        <div>
                          <h3 className={cn(
                            "font-semibold transition-colors duration-300",
                            isDark ? "text-white" : "text-slate-900"
                          )}>Sign Out</h3>
                          <p className={cn(
                            "text-sm transition-colors duration-300",
                            isDark ? "text-slate-500" : "text-slate-500"
                          )}>End your current session</p>
                        </div>
                      </div>
                      <Button variant="danger" onClick={handleLogout}>
                        <LogOut className="w-4 h-4" />
                        Logout
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              </motion.div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ProfilePage() {
  return (
    <ToastProvider>
      <ProfileContent />
    </ToastProvider>
  );
}
