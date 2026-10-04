import React from 'react';
import ReactDOM from 'react-dom/client';
import { AuthShell } from './auth/AuthShell';
import './index.css';
import './styles/editorial.css';
import './styles/dark.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthShell />
  </React.StrictMode>
);
