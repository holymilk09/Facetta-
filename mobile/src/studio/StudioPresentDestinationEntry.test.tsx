import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react-native';

import { AuthenticatedImageProvider } from '../AuthenticatedImage';
import { StudioPresentWorkspace } from './StudioPresentWorkspace';

const lineage = {
  projectId: 'project_1', sourceAssetId: 'asset_4', sourceDesignVersion: 4,
};

const gateway = {
  createBeautyPresentation: jest.fn(),
  createProductPresentation: jest.fn(),
  createMarketingPresentation: jest.fn(),
  acceptPresentationCandidate: jest.fn(),
  discardPresentationCandidate: jest.fn(),
  createPreSpecPresentation: jest.fn(),
  acceptPreSpecPresentation: jest.fn(),
  discardPreSpecPresentation: jest.fn(),
};

describe('StudioPresentWorkspace destination entry', () => {
  test('uses a chooser-selected destination without asking the same question twice', async () => {
    await render(
      <AuthenticatedImageProvider allowedOrigin="https://test" headers={{}}>
        <StudioPresentWorkspace
          gateway={gateway as any}
          lineage={lineage}
          createdBy="designer"
          initialDestination="marketing"
        />
      </AuthenticatedImageProvider>,
    );

    expect(screen.getByText('Campaign image set selected')).toBeTruthy();
    expect(screen.queryByText('What do you need?')).toBeNull();
    expect(screen.queryByRole('radio', { name: 'Client review' })).toBeNull();
    expect(screen.getByText('2 requested outputs · estimated 36 credits')).toBeTruthy();

    await act(async () => {
      fireEvent.press(screen.getByText('Change destination'));
    });

    expect(screen.getByText('What do you need?')).toBeTruthy();
    expect(screen.getByRole('radio', { name: 'Client review' })).toBeTruthy();
  });
});
