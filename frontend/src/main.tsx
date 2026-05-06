// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import '@aws-amplify/ui-react/styles.css';
import App from './App.tsx';
import { configureAuth } from './auth';
import { loadRuntimeConfig } from './config';
import { Authenticator } from '@aws-amplify/ui-react';

// Load runtime config, configure Amplify, then render with Authenticator.
loadRuntimeConfig().then(() => {
  configureAuth();

  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <Authenticator>
        <App />
      </Authenticator>
    </StrictMode>,
  );
});
