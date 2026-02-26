import type { MantineThemeOverride } from '@mantine/core';

export type ThemePackName = 'default' | 'workcore';

const baseTheme = {
  radius: {
    xs: '6px',
    sm: '8px',
    md: '10px',
    lg: '14px',
    xl: '18px'
  },
  headings: {
    fontFamily: "'Space Grotesk', 'Segoe UI', sans-serif"
  }
} as const;

const packs: Record<ThemePackName, MantineThemeOverride> = {
  default: {
    ...baseTheme,
    fontFamily: "'Inter', 'Segoe UI', sans-serif",
    primaryColor: 'blue'
  },
  workcore: {
    ...baseTheme,
    fontFamily: "'Space Grotesk', 'Segoe UI', sans-serif",
    colors: {
      brand: [
        '#e9f0ff',
        '#d6e2ff',
        '#b0c6ff',
        '#88a9ff',
        '#5c85ff',
        '#3b6af5',
        '#2a5de0',
        '#204cb6',
        '#173c8c',
        '#0d2b63'
      ]
    },
    primaryColor: 'brand'
  }
};

export const isThemePackName = (value: string): value is ThemePackName => value === 'default' || value === 'workcore';

export const buildChatForkTheme = (pack: ThemePackName): MantineThemeOverride => packs[pack] || packs.workcore;
