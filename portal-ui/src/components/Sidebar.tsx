'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import {
  Activity,
  Bot,
  Folder,
  Gauge,
  Home,
  MessageSquare,
  Settings,
  Shield,
  Terminal,
  User,
  Users,
  Wrench,
} from 'lucide-react';

interface SidebarProps {
  variant?: 'admin' | 'customer';
}

export function getPortalVariant(pathname: string): 'admin' | 'customer' {
  return pathname.startsWith('/admin') ? 'admin' : 'customer';
}

const adminLinks = [
  { href: '/admin', label: 'Overview', icon: Home, tag: 'control' },
  { href: '/admin/workspaces', label: 'Workspaces', icon: Folder, tag: 'tenant' },
  { href: '/admin/memory', label: 'Memory', icon: Activity, tag: 'inspect' },
  { href: '/admin/runs', label: 'Runs', icon: Terminal, tag: 'trace' },
  { href: '/admin/tools', label: 'Tools', icon: Wrench, tag: 'policy' },
  { href: '/admin/agents', label: 'Agents', icon: Bot, tag: 'runtime' },
  { href: '/admin/users', label: 'Users', icon: Users, tag: 'rbac' },
  { href: '/admin/monitoring', label: 'Monitoring', icon: Gauge, tag: 'audit' },
  { href: '/admin/me', label: 'Profile', icon: User, tag: 'admin' },
];

const customerLinks = [
  { href: '/workspace', label: 'Workspace', icon: Folder, tag: 'scope' },
  { href: '/config', label: 'Configuration', icon: Settings, tag: 'runtime' },
  { href: '/tools', label: 'Tools', icon: Wrench, tag: 'mcp' },
  { href: '/profile', label: 'Profile', icon: User, tag: 'me' },
];

export function Sidebar({ variant: propVariant }: SidebarProps) {
  const pathname = usePathname();
  const variant = propVariant || getPortalVariant(pathname);
  const links = variant === 'admin' ? adminLinks : customerLinks;

  return (
    <aside className="sticky top-4">
      <div className="overflow-hidden rounded-xl sidebar-light">
        <div className="border-b p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg border bg-foreground text-background">
              <Shield className="h-4 w-4" />
            </div>
            <div>
              <h1 className="text-sm font-semibold text-text-primary">Memory Control</h1>
              <p className="mt-0.5 text-xs text-text-muted">{variant === 'admin' ? 'Admin plane' : 'Developer console'}</p>
            </div>
          </div>
          <div className="mt-4 rounded-lg border bg-muted/50 p-3">
            <p className="console-kicker">Product model</p>
            <p className="mt-1 text-xs leading-5 text-text-secondary">
              API first. Official Python SDK. Portal for workspace controls and debugging.
            </p>
          </div>
        </div>

        <nav className="p-2">
          {links.map((link) => {
            const isActive =
              pathname === link.href ||
              (link.href !== '/admin' && link.href !== '/' && pathname.startsWith(`${link.href}/`));
            return (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  'group flex items-center justify-between rounded-lg px-3 py-2.5 text-sm transition-colors',
                  isActive ? 'bg-foreground text-background' : 'text-text-secondary hover:bg-muted hover:text-text-primary'
                )}
              >
                <span className="flex items-center gap-2.5">
                  <link.icon className="h-4 w-4" />
                  <span className="font-medium">{link.label}</span>
                </span>
                <span className={cn('rounded border px-1.5 py-0.5 font-mono text-[10px]', isActive ? 'border-background/20 text-background/80' : 'border-border text-text-muted')}>
                  {link.tag}
                </span>
              </Link>
            );
          })}
        </nav>

        <div className="border-t p-4">
          <div className="flex items-center gap-3 rounded-lg bg-muted/50 p-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full border bg-card text-xs font-semibold text-text-primary">
              {variant === 'admin' ? 'A' : 'D'}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-text-primary">{variant === 'admin' ? 'Administrator' : 'Developer'}</p>
              <p className="truncate text-xs text-text-muted">{variant === 'admin' ? 'role gated' : 'workspace scoped'}</p>
            </div>
          </div>
          {variant === 'admin' && (
            <Link href="/admin/chat/code-assistant" className="mt-3 flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-text-secondary hover:bg-muted hover:text-text-primary">
              <MessageSquare className="h-4 w-4" />
              Debug chat
            </Link>
          )}
        </div>
      </div>
    </aside>
  );
}
