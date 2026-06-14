'use client';

import { useEffect } from 'react';
import { logError } from '@/lib/errorTracking';

interface ErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

/**
 * Global error boundary for the entire application.
 * This is a Next.js error.tsx file that catches errors at the app level.
 */
export default function Error({ error, reset }: ErrorProps) {
  useEffect(() => {
    // Log the error to our error tracking service
    logError(error, {
      component: 'GlobalErrorBoundary',
      digest: error.digest,
    });
  }, [error]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
      <div className="text-center px-6">
        <div className="text-red-500 mb-6">
          <svg
            className="w-16 h-16 mx-auto"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
            />
          </svg>
        </div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-3">
          Application Error
        </h1>
        <p className="text-gray-600 dark:text-gray-400 mb-6 max-w-md">
          We apologize for the inconvenience. An unexpected error has occurred.
        </p>
        {process.env.NODE_ENV !== 'production' && (
          <div className="mb-6 text-left max-w-lg mx-auto">
            <pre className="text-xs bg-gray-100 dark:bg-gray-800 p-4 rounded overflow-auto max-h-[200px] text-red-600 dark:text-red-400">
              {error.message}
              {error.stack && (
                <>
                  {'\n\n'}
                  {error.stack.split('\n').slice(0, 5).join('\n')}
                </>
              )}
            </pre>
          </div>
        )}
        <div className="flex gap-4 justify-center">
          <button
            onClick={reset}
            className="px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors font-medium"
          >
            Try again
          </button>
          <button
            onClick={() => (window.location.href = '/')}
            className="px-6 py-2 bg-gray-200 dark:bg-gray-700 text-gray-900 dark:text-white rounded-lg hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors font-medium"
          >
            Go home
          </button>
        </div>
      </div>
    </div>
  );
}
