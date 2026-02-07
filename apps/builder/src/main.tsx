import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider } from '@mantine/core';
import '@mantine/core/styles.css';
import App from './App';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider
      theme={{
        fontFamily: "'Space Grotesk', 'Segoe UI', sans-serif",
        headings: { fontFamily: "'Space Grotesk', 'Segoe UI', sans-serif" },
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
      }}
      defaultColorScheme="light"
    >
      <App />
    </MantineProvider>
  </React.StrictMode>
);
