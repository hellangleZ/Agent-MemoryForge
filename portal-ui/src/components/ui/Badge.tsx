'use client';

import { cn } from '@/lib/utils';

interface BadgeProps {
  children: React.ReactNode;
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'info';
  dot?: boolean;
  className?: string;
}

export function Badge({ children, variant = 'default', dot = false, className }: BadgeProps) {
  const variants = {
    default: 'border-slate-200 bg-slate-50 text-slate-700',
    success: 'border-slate-300 bg-slate-100 text-slate-800',
    warning: 'border-slate-300 bg-slate-100 text-slate-700',
    danger: 'border-slate-400 bg-slate-200 text-slate-900',
    info: 'border-slate-200 bg-slate-50 text-slate-600',
  };

  const dotColors = {
    default: 'bg-slate-400',
    success: 'bg-slate-600',
    warning: 'bg-slate-500',
    danger: 'bg-slate-700',
    info: 'bg-slate-400',
  };

  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium', variants[variant], className)}>
      {dot && <span className={cn('h-1.5 w-1.5 rounded-full', dotColors[variant])} />}
      {children}
    </span>
  );
}

interface StatusDotProps {
  status: 'online' | 'offline' | 'warning' | 'error';
}

export function StatusDot({ status }: StatusDotProps) {
  const colors = {
    online: 'bg-slate-700',
    offline: 'bg-slate-300',
    warning: 'bg-slate-500',
    error: 'bg-slate-800',
  };

  return <span className={cn('h-2 w-2 rounded-full', colors[status])} />;
}
