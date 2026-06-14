'use client';

import { cn } from '@/lib/utils';
import { InputHTMLAttributes, forwardRef, useId } from 'react';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, id, ...props }, ref) => {
    const generatedId = useId();
    const inputId = id || (label ? generatedId : undefined);

    return (
      <div className="space-y-1.5">
        {label && (
          <label htmlFor={inputId} className="block text-sm font-medium text-text-secondary">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            'h-10 w-full rounded-md border bg-card px-3 text-sm text-text-primary shadow-sm transition-colors placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ring/15',
            error && 'border-red-300 focus:ring-red-500/15',
            className
          )}
          {...props}
        />
        {error && <p className="text-sm text-red-600 dark:text-red-300">{error}</p>}
      </div>
    );
  }
);

Input.displayName = 'Input';

interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, label, error, id, ...props }, ref) => {
    const generatedId = useId();
    const textareaId = id || (label ? generatedId : undefined);

    return (
      <div className="space-y-1.5">
        {label && (
          <label htmlFor={textareaId} className="block text-sm font-medium text-text-secondary">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={textareaId}
          className={cn(
            'min-h-[110px] w-full resize-y rounded-md border bg-card px-3 py-2 text-sm text-text-primary shadow-sm transition-colors placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-ring/15',
            error && 'border-red-300 focus:ring-red-500/15',
            className
          )}
          {...props}
        />
        {error && <p className="text-sm text-red-600 dark:text-red-300">{error}</p>}
      </div>
    );
  }
);

Textarea.displayName = 'Textarea';
