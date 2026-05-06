// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SignInForm } from './SignInForm';
import { AuthProvider } from './AuthContext';

vi.mock('aws-amplify/auth', () => ({
  signIn: vi.fn(),
  signOut: vi.fn(),
  getCurrentUser: vi.fn(),
  fetchAuthSession: vi.fn(),
}));

import {
  signIn as amplifySignIn,
  getCurrentUser,
} from 'aws-amplify/auth';

const mockSignIn = vi.mocked(amplifySignIn);
const mockGetCurrentUser = vi.mocked(getCurrentUser);

function renderSignInForm() {
  return render(
    <AuthProvider>
      <SignInForm />
    </AuthProvider>,
  );
}

describe('SignInForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetCurrentUser.mockRejectedValue(new Error('No user'));
  });

  it('renders email and password fields with a submit button', async () => {
    renderSignInForm();

    await waitFor(() => {
      expect(screen.getByLabelText('Email')).toBeEnabled();
    });

    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign In' })).toBeInTheDocument();
  });

  it('calls signIn with entered credentials on submit', async () => {
    mockSignIn.mockResolvedValue({
      isSignedIn: true,
      nextStep: { signInStep: 'DONE' },
    });
    mockGetCurrentUser
      .mockRejectedValueOnce(new Error('No user'))
      .mockResolvedValue({ userId: 'u1', username: 'test' });

    const user = userEvent.setup();
    renderSignInForm();

    await waitFor(() => {
      expect(screen.getByLabelText('Email')).toBeEnabled();
    });

    await user.type(screen.getByLabelText('Email'), 'test@example.com');
    await user.type(screen.getByLabelText('Password'), 'mypassword');
    await user.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(mockSignIn).toHaveBeenCalledWith({
        username: 'test@example.com',
        password: 'mypassword',
      });
    });
  });

  it('displays error message on sign-in failure', async () => {
    const authError = new Error('Incorrect username or password.');
    authError.name = 'NotAuthorizedException';
    mockSignIn.mockRejectedValue(authError);

    const user = userEvent.setup();
    renderSignInForm();

    await waitFor(() => {
      expect(screen.getByLabelText('Email')).toBeEnabled();
    });

    await user.type(screen.getByLabelText('Email'), 'bad@example.com');
    await user.type(screen.getByLabelText('Password'), 'wrong');
    await user.click(screen.getByRole('button', { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Incorrect username or password.',
      );
    });
  });

  it('shows loading text while sign-in is in progress', async () => {
    // signIn never resolves to keep loading state
    mockSignIn.mockReturnValue(new Promise(() => {}));

    const user = userEvent.setup();
    renderSignInForm();

    await waitFor(() => {
      expect(screen.getByLabelText('Email')).toBeEnabled();
    });

    await user.type(screen.getByLabelText('Email'), 'a@b.com');
    await user.type(screen.getByLabelText('Password'), 'pass');
    await user.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(screen.getByRole('button')).toHaveTextContent('Signing in…');
    });
  });
});
