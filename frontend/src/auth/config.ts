import { Amplify, type ResourcesConfig } from 'aws-amplify';

const authConfig: ResourcesConfig = {
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID ?? '',
      userPoolClientId: import.meta.env.VITE_COGNITO_USER_POOL_CLIENT_ID ?? '',
      identityPoolId: import.meta.env.VITE_COGNITO_IDENTITY_POOL_ID ?? '',
    },
  },
};

export function configureAuth(): void {
  Amplify.configure(authConfig);
}

export { authConfig };
