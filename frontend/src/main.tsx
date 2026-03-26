import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App.tsx';
import { configureAuth, AuthProvider } from './auth';
import { loadRuntimeConfig } from './config';

// Load runtime config (from /runtime-config.json or env var fallbacks),
// then configure auth and render the app.
loadRuntimeConfig().then(() => {
  configureAuth();

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <AuthProvider>
        <App />
      </AuthProvider>
    </StrictMode>,
  );
});
