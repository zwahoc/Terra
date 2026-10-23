import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

// Preserve saved ingestion links while the team upload screen is integrated.
const ingestion = new URLSearchParams(window.location.search).get('sandbox') === 'ingestion'
  || window.location.hash.startsWith('#batch=');

async function mountApp() {
  const { default: App } = ingestion
    ? await import('./App')
    : await import('./app/TerraApp');
  if (ingestion) await import('./ingestion.css');
  else await import('./index.css');
  createRoot(document.getElementById('root')!).render(
    <StrictMode><App /></StrictMode>,
  );
}

void mountApp();
