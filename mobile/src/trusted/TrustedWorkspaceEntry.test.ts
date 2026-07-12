/// <reference types="jest" />

import React from 'react';
import { render, screen } from '@testing-library/react-native';

import { TrustedWorkspaceEntry } from './TrustedWorkspaceEntry';

describe('TrustedWorkspaceEntry', () => {
  test('keeps API construction behind one redesign integration seam', async () => {
    await render(React.createElement(TrustedWorkspaceEntry, {
      apiBaseUrl: 'https://facetta.test/',
      designer: 'usr_designer',
      enabled: false,
      viewportWidth: 1024,
    }));

    expect(await screen.findByText('Trusted workspace')).toBeTruthy();
    expect(screen.getByText(/internal trusted workflow is disabled/)).toBeTruthy();
  });
});
