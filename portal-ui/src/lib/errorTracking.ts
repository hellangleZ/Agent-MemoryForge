/**
 * Error tracking utility for Portal UI.
 * Provides centralized error logging with production-ready error tracking integration.
 */

interface ErrorContext {
  component?: string;
  action?: string;
  userId?: string;
  workspaceId?: string;
  [key: string]: unknown;
}

/**
 * Log an error with optional context.
 * In production, this would send errors to a tracking service (e.g., Sentry, LogRocket).
 */
export function logError(error: Error, context?: ErrorContext): void {
  // In development, always log to console
  if (process.env.NODE_ENV !== 'production') {
    console.error('[Error]', error.message, {
      stack: error.stack,
      context,
    });
    return;
  }

  // In production, send to error tracking service
  // Example integration with Sentry:
  // import * as Sentry from '@sentry/nextjs';
  // Sentry.captureException(error, { extra: context });

  // For now, log to console in production as well
  // This should be replaced with actual error tracking
  console.error('[Production Error]', {
    message: error.message,
    name: error.name,
    context,
  });
}

/**
 * Log a warning with optional context.
 */
export function logWarning(message: string, context?: ErrorContext): void {
  if (process.env.NODE_ENV !== 'production') {
    console.warn('[Warning]', message, context);
  }
}

/**
 * Create an error with additional context.
 */
export function createError(message: string, cause?: Error, context?: ErrorContext): Error {
  const error = new Error(message, { cause });
  // Attach context as a non-enumerable property
  Object.defineProperty(error, 'context', {
    value: context,
    enumerable: false,
    writable: true,
  });
  return error;
}

/**
 * Wrap an async function with error logging.
 */
export function withErrorLogging<T extends (...args: unknown[]) => Promise<unknown>>(
  fn: T,
  context?: ErrorContext
): T {
  return (async (...args: Parameters<T>) => {
    try {
      return await fn(...args);
    } catch (error) {
      logError(error as Error, context);
      throw error;
    }
  }) as T;
}

const errorTracking = { logError, logWarning, createError, withErrorLogging };

export default errorTracking;
