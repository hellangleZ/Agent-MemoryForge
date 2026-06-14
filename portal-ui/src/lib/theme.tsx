'use client';

import { createContext, useContext, ReactNode } from 'react';

interface ThemeContextType {
  theme: 'light';
  isDark: false;
}

const ThemeContext = createContext<ThemeContextType>({ theme: 'light', isDark: false });

export function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <ThemeContext.Provider value={{ theme: 'light', isDark: false }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
