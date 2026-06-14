'use client';

import { Sidebar } from '@/components/Sidebar';
import { Card, CardHeader } from '@/components/ui/Card';
import { ChatWindow } from '@/components/ChatWindow';
import { ToastProvider, useToast } from '@/components/ui/Toast';
import { useTheme } from '@/lib/theme';
import { cn } from '@/lib/utils';
import { motion } from 'framer-motion';
import { useParams } from 'next/navigation';

function AdminChatPageContent() {
  const params = useParams();
  const agentId = params.agent as string || 'code-assistant';
  const { isDark } = useTheme();

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
            ? "bg-gradient-to-br from-purple-900/10 via-transparent to-cyan-900/10"
            : "bg-gradient-to-br from-purple-100/30 via-transparent to-cyan-100/30"
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
          <div className="lg:col-span-1">
            <Sidebar variant="admin" />
          </div>

          <div className="lg:col-span-3">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
            >
              <Card className="overflow-hidden">
                <CardHeader
                  title={`Chat: ${agentId}`}
                  description="Admin chat interface for testing and debugging"
                  action={
                    <div className="flex items-center gap-2">
                      <span className={cn(
                        "text-xs transition-colors duration-300",
                        isDark ? "text-slate-500" : "text-slate-500"
                      )}>Press</span>
                      <kbd className={cn(
                        "px-2 py-1 text-xs rounded border transition-colors duration-300",
                        isDark ? "bg-white/5 border-white/10 text-slate-400" : "bg-slate-100 border-slate-200 text-slate-600"
                      )}>Enter</kbd>
                      <span className={cn(
                        "text-xs transition-colors duration-300",
                        isDark ? "text-slate-500" : "text-slate-500"
                      )}>to send</span>
                    </div>
                  }
                />
                <ChatWindow agentId={agentId} />
              </Card>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AdminChatPage() {
  return (
    <ToastProvider>
      <AdminChatPageContent />
    </ToastProvider>
  );
}
