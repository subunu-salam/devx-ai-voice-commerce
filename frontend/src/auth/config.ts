// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { Amplify, type ResourcesConfig } from 'aws-amplify';
import { getRuntimeConfig } from '../config';

export function configureAuth(): void {
  const config = getRuntimeConfig();
  const authConfig: ResourcesConfig = {
    Auth: {
      Cognito: {
        userPoolId: config.userPoolId,
        userPoolClientId: config.userPoolClientId,
      },
    },
  };
  Amplify.configure(authConfig);
}
