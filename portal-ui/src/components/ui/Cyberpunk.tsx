'use client';

import { cn } from '@/lib/utils';
import { useTheme } from '@/lib/theme';
import { motion, HTMLMotionProps } from 'framer-motion';
import { ReactNode, forwardRef } from 'react';

// ============ GlowCard ============
interface GlowCardProps extends HTMLMotionProps<'div'> {
  children: ReactNode;
  glowColor?: 'cyan' | 'pink' | 'purple' | 'green' | 'orange';
  variant?: 'default' | 'bordered' | 'gradient';
  hover?: boolean;
}

export const GlowCard = forwardRef<HTMLDivElement, GlowCardProps>(
  ({ children, className, glowColor = 'cyan', variant = 'default', hover = true, ...props }, ref) => {
    const { isDark } = useTheme();

    const glowColors = {
      cyan: isDark ? 'hover:shadow-[0_0_30px_hsl(185_100%_50%/0.3)]' : 'hover:shadow-[0_0_20px_hsl(185_85%_40%/0.2)]',
      pink: isDark ? 'hover:shadow-[0_0_30px_hsl(330_100%_60%/0.3)]' : 'hover:shadow-[0_0_20px_hsl(330_85%_55%/0.2)]',
      purple: isDark ? 'hover:shadow-[0_0_30px_hsl(270_100%_60%/0.3)]' : 'hover:shadow-[0_0_20px_hsl(270_85%_50%/0.2)]',
      green: isDark ? 'hover:shadow-[0_0_30px_hsl(150_100%_50%/0.3)]' : 'hover:shadow-[0_0_20px_hsl(150_85%_40%/0.2)]',
      orange: isDark ? 'hover:shadow-[0_0_30px_hsl(25_100%_55%/0.3)]' : 'hover:shadow-[0_0_20px_hsl(25_85%_50%/0.2)]',
    };

    const borderColors = {
      cyan: isDark ? 'border-cyan-500/30 hover:border-cyan-400/50' : 'border-cyan-400/30 hover:border-cyan-500/40',
      pink: isDark ? 'border-pink-500/30 hover:border-pink-400/50' : 'border-pink-400/30 hover:border-pink-500/40',
      purple: isDark ? 'border-purple-500/30 hover:border-purple-400/50' : 'border-purple-400/30 hover:border-purple-500/40',
      green: isDark ? 'border-green-500/30 hover:border-green-400/50' : 'border-green-400/30 hover:border-green-500/40',
      orange: isDark ? 'border-orange-500/30 hover:border-orange-400/50' : 'border-orange-400/30 hover:border-orange-500/40',
    };

    const variants = {
      default: cn(
        'rounded-xl border transition-all duration-300',
        isDark ? 'bg-slate-900/80 border-white/10' : 'bg-white/90 border-slate-200',
        hover && glowColors[glowColor]
      ),
      bordered: cn(
        'rounded-xl border-2 transition-all duration-300',
        isDark ? 'bg-slate-900/60' : 'bg-white/80',
        borderColors[glowColor],
        hover && glowColors[glowColor]
      ),
      gradient: cn(
        'rounded-xl border transition-all duration-300 relative overflow-hidden',
        isDark ? 'bg-slate-900/80 border-white/10' : 'bg-white/90 border-slate-200',
        hover && glowColors[glowColor]
      ),
    };

    return (
      <motion.div
        ref={ref}
        whileHover={hover ? { scale: 1.01 } : undefined}
        className={cn(variants[variant], className)}
        {...props}
      >
        {variant === 'gradient' && (
          <div className={cn(
            'absolute inset-0 opacity-10 pointer-events-none',
            isDark
              ? 'bg-gradient-to-br from-cyan-500 via-purple-500 to-pink-500'
              : 'bg-gradient-to-br from-cyan-300 via-purple-300 to-pink-300'
          )} />
        )}
        <div className="relative z-10">{children}</div>
      </motion.div>
    );
  }
);

GlowCard.displayName = 'GlowCard';

// ============ NeonText ============
interface NeonTextProps {
  children: ReactNode;
  color?: 'cyan' | 'pink' | 'purple' | 'green' | 'gradient';
  size?: 'sm' | 'md' | 'lg' | 'xl' | '2xl';
  glow?: boolean;
  className?: string;
}

export function NeonText({
  children,
  color = 'cyan',
  size = 'md',
  glow = true,
  className,
}: NeonTextProps) {
  const { isDark } = useTheme();

  const colors = {
    cyan: isDark ? 'text-cyan-400' : 'text-cyan-600',
    pink: isDark ? 'text-pink-400' : 'text-pink-600',
    purple: isDark ? 'text-purple-400' : 'text-purple-600',
    green: isDark ? 'text-green-400' : 'text-green-600',
    gradient: 'gradient-text',
  };

  const glowStyles = glow && isDark ? {
    cyan: 'drop-shadow-[0_0_8px_hsl(185_100%_50%/0.5)]',
    pink: 'drop-shadow-[0_0_8px_hsl(330_100%_60%/0.5)]',
    purple: 'drop-shadow-[0_0_8px_hsl(270_100%_60%/0.5)]',
    green: 'drop-shadow-[0_0_8px_hsl(150_100%_50%/0.5)]',
    gradient: '',
  } : {
    cyan: '',
    pink: '',
    purple: '',
    green: '',
    gradient: '',
  };

  const sizes = {
    sm: 'text-sm',
    md: 'text-base',
    lg: 'text-lg',
    xl: 'text-xl',
    '2xl': 'text-2xl',
  };

  return (
    <span
      className={cn(
        'font-semibold transition-colors duration-300',
        colors[color],
        glowStyles[color],
        sizes[size],
        className
      )}
    >
      {children}
    </span>
  );
}

// ============ CyberButton ============
interface CyberButtonProps extends Omit<HTMLMotionProps<'button'>, 'children'> {
  children: ReactNode;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'glow';
  size?: 'sm' | 'md' | 'lg';
  glowColor?: 'cyan' | 'pink' | 'purple';
  loading?: boolean;
}

export const CyberButton = forwardRef<HTMLButtonElement, CyberButtonProps>(
  ({ children, className, variant = 'primary', size = 'md', glowColor = 'cyan', loading, disabled, ...props }, ref) => {
    const { isDark } = useTheme();

    const baseStyles = 'inline-flex items-center justify-center gap-2 font-medium rounded-lg transition-all duration-300 focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed';

    const variants = {
      primary: cn(
        'btn-primary',
        isDark ? 'text-slate-900' : 'text-white'
      ),
      secondary: 'btn-secondary',
      ghost: cn(
        'bg-transparent border border-transparent',
        isDark
          ? 'text-slate-300 hover:text-white hover:bg-white/5 hover:border-white/10'
          : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 hover:border-slate-200'
      ),
      danger: cn(
        'border',
        isDark
          ? 'bg-red-500/10 text-red-400 border-red-500/30 hover:bg-red-500/20 hover:border-red-400/50'
          : 'bg-red-50 text-red-600 border-red-200 hover:bg-red-100 hover:border-red-300'
      ),
      glow: cn(
        'border-2 bg-transparent',
        glowColor === 'cyan' && (isDark
          ? 'border-cyan-500/50 text-cyan-400 hover:bg-cyan-500/10 hover:shadow-[0_0_20px_hsl(185_100%_50%/0.3)]'
          : 'border-cyan-400/50 text-cyan-600 hover:bg-cyan-50 hover:shadow-[0_0_15px_hsl(185_85%_40%/0.2)]'),
        glowColor === 'pink' && (isDark
          ? 'border-pink-500/50 text-pink-400 hover:bg-pink-500/10 hover:shadow-[0_0_20px_hsl(330_100%_60%/0.3)]'
          : 'border-pink-400/50 text-pink-600 hover:bg-pink-50 hover:shadow-[0_0_15px_hsl(330_85%_55%/0.2)]'),
        glowColor === 'purple' && (isDark
          ? 'border-purple-500/50 text-purple-400 hover:bg-purple-500/10 hover:shadow-[0_0_20px_hsl(270_100%_60%/0.3)]'
          : 'border-purple-400/50 text-purple-600 hover:bg-purple-50 hover:shadow-[0_0_15px_hsl(270_85%_50%/0.2)]')
      ),
    };

    const sizes = {
      sm: 'px-3 py-1.5 text-xs',
      md: 'px-5 py-2.5 text-sm',
      lg: 'px-6 py-3 text-base',
    };

    return (
      <motion.button
        ref={ref}
        whileHover={{ scale: disabled || loading ? 1 : 1.02 }}
        whileTap={{ scale: disabled || loading ? 1 : 0.98 }}
        className={cn(baseStyles, variants[variant], sizes[size], className)}
        disabled={disabled || loading}
        {...props}
      >
        {loading && (
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
        )}
        {children}
      </motion.button>
    );
  }
);

CyberButton.displayName = 'CyberButton';

// ============ GridBackground ============
interface GridBackgroundProps {
  children: ReactNode;
  showGrid?: boolean;
  showGradient?: boolean;
  className?: string;
}

export function GridBackground({
  children,
  showGrid = true,
  showGradient = true,
  className,
}: GridBackgroundProps) {
  const { isDark } = useTheme();

  return (
    <div
      className={cn(
        'relative min-h-screen transition-colors duration-300',
        isDark ? 'bg-[hsl(230_25%_7%)]' : 'bg-[hsl(220_20%_97%)]',
        className
      )}
    >
      {/* Gradient overlay */}
      {showGradient && (
        <div
          className={cn(
            'absolute inset-0 pointer-events-none',
            isDark
              ? 'bg-gradient-to-br from-purple-900/20 via-transparent to-cyan-900/20'
              : 'bg-gradient-to-br from-purple-100/50 via-transparent to-cyan-100/50'
          )}
        />
      )}

      {/* Grid pattern */}
      {showGrid && (
        <div
          className={cn(
            'absolute inset-0 pointer-events-none',
            isDark ? 'bg-grid' : 'bg-grid'
          )}
          style={{
            backgroundImage: isDark
              ? 'linear-gradient(hsl(185 100% 50% / 0.03) 1px, transparent 1px), linear-gradient(90deg, hsl(185 100% 50% / 0.03) 1px, transparent 1px)'
              : 'linear-gradient(hsl(185 85% 40% / 0.05) 1px, transparent 1px), linear-gradient(90deg, hsl(185 85% 40% / 0.05) 1px, transparent 1px)',
            backgroundSize: '50px 50px',
          }}
        />
      )}

      {/* Content */}
      <div className="relative z-10">{children}</div>
    </div>
  );
}

// ============ CyberInput ============
interface CyberInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  icon?: ReactNode;
}

export const CyberInput = forwardRef<HTMLInputElement, CyberInputProps>(
  ({ className, label, error, icon, ...props }, ref) => {
    const { isDark } = useTheme();

    return (
      <div className="w-full">
        {label && (
          <label
            className={cn(
              'block text-sm font-medium mb-2 transition-colors duration-300',
              isDark ? 'text-slate-300' : 'text-slate-700'
            )}
          >
            {label}
          </label>
        )}
        <div className="relative">
          {icon && (
            <div
              className={cn(
                'absolute left-3 top-1/2 -translate-y-1/2',
                isDark ? 'text-slate-400' : 'text-slate-500'
              )}
            >
              {icon}
            </div>
          )}
          <input
            ref={ref}
            className={cn(
              'w-full px-4 py-3 rounded-lg border transition-all duration-300',
              'focus:outline-none focus:ring-2',
              icon && 'pl-10',
              isDark
                ? 'bg-slate-800/50 border-white/10 text-white placeholder:text-slate-500 focus:border-cyan-500/50 focus:ring-cyan-500/20'
                : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-cyan-400/50 focus:ring-cyan-400/20',
              error && (isDark
                ? 'border-red-500/50 focus:border-red-500/50 focus:ring-red-500/20'
                : 'border-red-400/50 focus:border-red-400/50 focus:ring-red-400/20'),
              className
            )}
            {...props}
          />
        </div>
        {error && (
          <p className={cn(
            'mt-1 text-sm',
            isDark ? 'text-red-400' : 'text-red-600'
          )}>
            {error}
          </p>
        )}
      </div>
    );
  }
);

CyberInput.displayName = 'CyberInput';

// ============ CyberBadge ============
interface CyberBadgeProps {
  children: ReactNode;
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'info';
  dot?: boolean;
  className?: string;
}

export function CyberBadge({
  children,
  variant = 'default',
  dot = false,
  className,
}: CyberBadgeProps) {
  const { isDark } = useTheme();

  const variants = {
    default: cn(
      'border',
      isDark
        ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400'
        : 'bg-cyan-50 border-cyan-200 text-cyan-700'
    ),
    success: cn(
      'border',
      isDark
        ? 'bg-green-500/10 border-green-500/30 text-green-400'
        : 'bg-green-50 border-green-200 text-green-700'
    ),
    warning: cn(
      'border',
      isDark
        ? 'bg-orange-500/10 border-orange-500/30 text-orange-400'
        : 'bg-orange-50 border-orange-200 text-orange-700'
    ),
    danger: cn(
      'border',
      isDark
        ? 'bg-red-500/10 border-red-500/30 text-red-400'
        : 'bg-red-50 border-red-200 text-red-700'
    ),
    info: cn(
      'border',
      isDark
        ? 'bg-purple-500/10 border-purple-500/30 text-purple-400'
        : 'bg-purple-50 border-purple-200 text-purple-700'
    ),
  };

  const dotColors = {
    default: isDark ? 'bg-cyan-400' : 'bg-cyan-500',
    success: isDark ? 'bg-green-400' : 'bg-green-500',
    warning: isDark ? 'bg-orange-400' : 'bg-orange-500',
    danger: isDark ? 'bg-red-400' : 'bg-red-500',
    info: isDark ? 'bg-purple-400' : 'bg-purple-500',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-colors duration-300',
        variants[variant],
        className
      )}
    >
      {dot && (
        <span
          className={cn(
            'w-1.5 h-1.5 rounded-full animate-pulse',
            dotColors[variant]
          )}
        />
      )}
      {children}
    </span>
  );
}

// ============ CyberDivider ============
interface CyberDividerProps {
  orientation?: 'horizontal' | 'vertical';
  gradient?: boolean;
  className?: string;
}

export function CyberDivider({
  orientation = 'horizontal',
  gradient = false,
  className,
}: CyberDividerProps) {
  const { isDark } = useTheme();

  if (orientation === 'vertical') {
    return (
      <div
        className={cn(
          'w-px h-full',
          gradient
            ? 'bg-gradient-to-b from-transparent via-current to-transparent'
            : '',
          isDark ? 'bg-white/10' : 'bg-slate-200',
          className
        )}
      />
    );
  }

  return (
    <div
      className={cn(
        'h-px w-full',
        gradient
          ? isDark
            ? 'bg-gradient-to-r from-transparent via-cyan-500/30 to-transparent'
            : 'bg-gradient-to-r from-transparent via-cyan-400/30 to-transparent'
          : isDark
            ? 'bg-white/10'
            : 'bg-slate-200',
        className
      )}
    />
  );
}

// ============ CyberSkeleton ============
interface CyberSkeletonProps {
  className?: string;
  variant?: 'text' | 'circular' | 'rectangular';
  width?: string | number;
  height?: string | number;
}

export function CyberSkeleton({
  className,
  variant = 'text',
  width,
  height,
}: CyberSkeletonProps) {
  const { isDark } = useTheme();

  const variants = {
    text: 'h-4 rounded',
    circular: 'rounded-full',
    rectangular: 'rounded-lg',
  };

  return (
    <div
      className={cn(
        'animate-pulse',
        isDark ? 'bg-slate-700/50' : 'bg-slate-200',
        variants[variant],
        className
      )}
      style={{
        width: width,
        height: height,
      }}
    />
  );
}

// ============ CyberProgress ============
interface CyberProgressProps {
  value: number;
  max?: number;
  color?: 'cyan' | 'pink' | 'purple' | 'green';
  size?: 'sm' | 'md' | 'lg';
  showLabel?: boolean;
  className?: string;
}

export function CyberProgress({
  value,
  max = 100,
  color = 'cyan',
  size = 'md',
  showLabel = false,
  className,
}: CyberProgressProps) {
  const { isDark } = useTheme();
  const percentage = Math.min(100, Math.max(0, (value / max) * 100));

  const colors = {
    cyan: isDark
      ? 'from-cyan-500 to-blue-500 shadow-[0_0_10px_hsl(185_100%_50%/0.3)]'
      : 'from-cyan-400 to-blue-400',
    pink: isDark
      ? 'from-pink-500 to-purple-500 shadow-[0_0_10px_hsl(330_100%_60%/0.3)]'
      : 'from-pink-400 to-purple-400',
    purple: isDark
      ? 'from-purple-500 to-indigo-500 shadow-[0_0_10px_hsl(270_100%_60%/0.3)]'
      : 'from-purple-400 to-indigo-400',
    green: isDark
      ? 'from-green-500 to-emerald-500 shadow-[0_0_10px_hsl(150_100%_50%/0.3)]'
      : 'from-green-400 to-emerald-400',
  };

  const sizes = {
    sm: 'h-1',
    md: 'h-2',
    lg: 'h-3',
  };

  return (
    <div className={cn('w-full', className)}>
      <div
        className={cn(
          'w-full rounded-full overflow-hidden',
          sizes[size],
          isDark ? 'bg-slate-700/50' : 'bg-slate-200'
        )}
      >
        <div
          className={cn(
            'h-full rounded-full bg-gradient-to-r transition-all duration-500 ease-out',
            colors[color]
          )}
          style={{ width: `${percentage}%` }}
        />
      </div>
      {showLabel && (
        <div
          className={cn(
            'mt-1 text-xs text-right',
            isDark ? 'text-slate-400' : 'text-slate-600'
          )}
        >
          {Math.round(percentage)}%
        </div>
      )}
    </div>
  );
}
