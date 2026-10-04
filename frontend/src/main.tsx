import React from 'react';
import ReactDOM from 'react-dom/client';
import { AuthShell } from './auth/AuthShell';
import { App } from './App';
import './index.css';
import './styles/editorial.css';
import './styles/dark.css';
import './styles/glass.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {import.meta.env.DEV && ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)
      && window.location.pathname === '/workstation' ? <App workstation /> : <AuthShell />}
  </React.StrictMode>
);
