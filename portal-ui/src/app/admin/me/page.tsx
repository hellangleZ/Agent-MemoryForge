'use client';

import { useEffect, useState } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { Card, CardHeader, CardContent } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import { useTheme } from '@/lib/theme';
import { cn } from '@/lib/utils';
import { getMe, hasToken } from '@/lib/api';
import { motion } from 'framer-motion';
import { User, Mail, Shield, Key, Clock, AlertTriangle, Loader2 } from 'lucide-react';

interface UserInfo { id: string; email: string; role: string; created_at: string; }

function AdminMeContent() {
  const { addToast } = useToast();
  const { isDark } = useTheme();
  const [user, setUser] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchUser = async () => {
      if (hasToken()) {
        try {
          const userData = await getMe();
          setUser(userData as UserInfo);
        } catch (err: any) {
          addToast('Failed to fetch user info', 'error');
        }
      }
      setLoading(false);
    };
    fetchUser();
  }, [addToast]);

  const securityItems = [
    { icon: Shield, label: 'Admin Access', status: 'Granted', variant: 'success' as const },
    { icon: Key, label: 'Token Valid', status: 'Active', variant: 'success' as const },
    { icon: User, label: 'Scope', status: 'x-workspace-id', variant: 'info' as const },
  ];

  const infoColors: Record<string, { bg: string; icon: string }> = {
    brand: {
      bg: isDark ? 'bg-purple-500/10' : 'bg-purple-100',
      icon: isDark ? 'text-purple-400' : 'text-purple-600',
    },
    cyan: {
      bg: isDark ? 'bg-cyan-500/10' : 'bg-cyan-100',
      icon: isDark ? 'text-cyan-400' : 'text-cyan-600',
    },
    green: {
      bg: isDark ? 'bg-green-500/10' : 'bg-green-100',
      icon: isDark ? 'text-green-400' : 'text-green-600',
    },
    amber: {
      bg: isDark ? 'bg-amber-500/10' : 'bg-amber-100',
      icon: isDark ? 'text-amber-400' : 'text-amber-600',
    },
  };

  return (
    <div className={cn(
      "min-h-screen transition-colors duration-300",
      isDark ? "bg-[hsl(230_25%_7%)]" : "bg-[hsl(220_20%_97%)]"
    )}>
      {/* Background effects */}
      <div className="fixed inset-0 -z-10 overflow-hidden">
        <div className={cn(
          "absolute inset-0 transition-colors duration-300",
          isDark
            ? "bg-gradient-to-br from-purple-900/20 via-transparent to-cyan-900/20"
            : "bg-gradient-to-br from-purple-100/50 via-transparent to-cyan-100/50"
        )} />
        <div className={cn(
          "absolute top-0 right-1/4 w-96 h-96 rounded-full blur-3xl transition-colors duration-300",
          isDark ? "bg-purple-600/20" : "bg-purple-300/30"
        )} />
        {/* Grid pattern */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage: isDark
              ? 'linear-gradient(hsl(185 100% 50% / 0.02) 1px, transparent 1px), linear-gradient(90deg, hsl(185 100% 50% / 0.02) 1px, transparent 1px)'
              : 'linear-gradient(hsl(185 85% 40% / 0.03) 1px, transparent 1px), linear-gradient(90deg, hsl(185 85% 40% / 0.03) 1px, transparent 1px)',
            backgroundSize: '50px 50px',
          }}
        />
      </div>

      <div className="container mx-auto px-4 py-8 relative z-10">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          <div className="lg:col-span-1"><Sidebar variant="admin" /></div>
          <div className="lg:col-span-3 space-y-6">
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
              <Card className="p-6">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                  <div className="flex items-center gap-4">
                    <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-500 to-cyan-500 flex items-center justify-center shadow-lg shadow-purple-500/25">
                      <User className="w-7 h-7 text-white" />
                    </div>
                    <div>
                      <h1 className={cn(
                        "text-2xl font-bold transition-colors duration-300",
                        isDark ? "text-white" : "text-slate-900"
                      )}>Admin Profile</h1>
                      <p className={cn(
                        "transition-colors duration-300",
                        isDark ? "text-slate-400" : "text-slate-600"
                      )}>Your administrator account</p>
                    </div>
                  </div>
                  <Badge variant="success" dot>Admin Mode</Badge>
                </div>
              </Card>
            </motion.div>

            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.1 }}>
              <Card>
                <CardHeader title="Account Information" description="Your admin account details" />
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
                        <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", infoColors.brand.bg)}>
                          <Mail className={cn("w-5 h-5", infoColors.brand.icon)} />
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
                          )}>{user.created_at ? new Date(user.created_at).toLocaleDateString() : 'Unknown'}</p>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="text-center py-8">
                      <AlertTriangle className={cn(
                        "w-12 h-12 mx-auto mb-4",
                        isDark ? "text-amber-400" : "text-amber-500"
                      )} />
                      <p className={cn(
                        "mb-4 transition-colors duration-300",
                        isDark ? "text-slate-400" : "text-slate-600"
                      )}>Not authenticated as admin</p>
                      <Button onClick={() => window.location.href = '/admin/login'}>Go to Admin Login</Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            </motion.div>

            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, delay: 0.2 }}>
              <Card>
                <CardHeader title="Admin Privileges" description="Current session permissions" />
                <CardContent>
                  <div className="space-y-3">
                    {securityItems.map((item, index) => (
                      <div key={index} className={cn(
                        "flex items-center gap-4 p-4 rounded-xl border transition-colors duration-300",
                        isDark ? "bg-white/5 border-white/10" : "bg-slate-50 border-slate-200"
                      )}>
                        <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center", infoColors.brand.bg)}>
                          <item.icon className={cn("w-5 h-5", infoColors.brand.icon)} />
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
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AdminMePage() {
  return (<ToastProvider><AdminMeContent /></ToastProvider>);
}
