/// <reference types="jest" />

import React from 'react';
import { render, screen } from '@testing-library/react-native';
import { AuthenticatedImage, AuthenticatedImageProvider } from '../AuthenticatedImage';

test('same-origin protected images receive the runtime bearer header', async () => {
  await render(
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test/api"
      headers={{ Authorization: 'Bearer runtime-token' }}>
      <AuthenticatedImage
        accessibilityLabel="Same-origin design"
        source={{ uri: 'https://facetta.test/assets/asset_1/image', headers: { Authorization: 'Bearer attacker-value' } }}
      />
    </AuthenticatedImageProvider>,
  );
  expect(screen.getByLabelText('Same-origin design').props.source.headers).toEqual({
    Authorization: 'Bearer runtime-token',
  });
});

test('relative protected image paths resolve against the trusted origin and receive authorization', async () => {
  await render(
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test/api"
      headers={{ Authorization: 'Bearer runtime-token' }}>
      <AuthenticatedImage
        accessibilityLabel="Relative design"
        source={{ uri: '/assets/asset_1/image' }}
      />
    </AuthenticatedImageProvider>,
  );
  expect(screen.getByLabelText('Relative design').props.source).toMatchObject({
    uri: 'https://facetta.test/assets/asset_1/image',
    headers: { Authorization: 'Bearer runtime-token' },
  });
});

test('off-origin images fail closed without leaking Facetta authorization', async () => {
  await render(
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test"
      headers={{ Authorization: 'Bearer runtime-token' }}>
      <AuthenticatedImage
        accessibilityLabel="Foreign image"
        source={{ uri: 'https://evil.example/collect.png' }}
      />
    </AuthenticatedImageProvider>,
  );
  const locked = screen.getByLabelText('Foreign image unavailable: untrusted image origin');
  expect(locked.props.source).toBeUndefined();
  expect(screen.getByText('Image origin could not be verified')).toBeTruthy();
});

test('missing runtime token shows a fail-closed sign-in placeholder', async () => {
  await render(
    <AuthenticatedImageProvider allowedOrigin="https://facetta.test" headers={undefined}>
      <AuthenticatedImage
        accessibilityLabel="Private design"
        source={{ uri: 'https://facetta.test/assets/asset_1/image' }}
      />
    </AuthenticatedImageProvider>,
  );
  expect(screen.getByLabelText('Private design unavailable: sign in required')).toBeTruthy();
  expect(screen.getByText('Sign in to view this image')).toBeTruthy();
});
