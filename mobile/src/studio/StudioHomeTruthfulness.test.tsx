/// <reference types="jest" />

import React from 'react';
import { render } from '@testing-library/react-native';

import App from '../../App';
import { clearSession, saveSession } from '../auth';

afterEach(() => clearSession());

test('signed-in Studio home offers one start decision without a duplicate feature menu', async () => {
  saveSession({
    provider: 'email', email: 'designer@example.com', name: 'Designer',
    designerId: 'usr_designer',
  });
  const view = await render(<App />);

  expect(view.getByText('Start from an idea or reference')).toBeTruthy();
  expect(view.queryByText('Creative studios')).toBeNull();
  expect(view.queryByText('Preserve a new direction')).toBeNull();
  expect(view.queryByText('Prepare presentation imagery')).toBeNull();
  expect(view.queryByText(/Builder|Share design|Factory/i)).toBeNull();
  expect(view.queryByText(/Developer connection|API URL|designer id/i)).toBeNull();
  expect(view.queryByLabelText('Create')).toBeNull();
  view.unmount();
});
