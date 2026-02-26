import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import '@mantine/core/styles.css';
import App from './App';
import { buildChatForkTheme, isThemePackName, type ThemePackName } from './theme/tokens';

const params = new URLSearchParams(window.location.search);
const packFromQuery = params.get('theme_pack') || '';
const packFromEnv = import.meta.env.VITE_CHAT_FORK_THEME_PACK || 'workcore';
const selectedPack = (isThemePackName(packFromQuery)
  ? packFromQuery
  : isThemePackName(packFromEnv)
    ? packFromEnv
    : 'workcore') as ThemePackName;
const selectedScheme = params.get('theme') === 'dark' ? 'dark' : 'light';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={buildChatForkTheme(selectedPack)} defaultColorScheme={selectedScheme}>
      <App />
    </MantineProvider>
  </React.StrictMode>
);
