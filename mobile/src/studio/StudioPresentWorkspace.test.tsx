import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { StudioPresentWorkspace } from './StudioPresentWorkspace';

const lineage = {
  projectId: 'project_1', sourceAssetId: 'asset_4', sourceDesignVersion: 4,
};

describe('StudioPresentWorkspace', () => {
  test('fails closed without an exact immutable revision', async () => {
    await render(<StudioPresentWorkspace gateway={{} as any} lineage={null} createdBy="designer" />);
    expect(screen.getByText('Choose a saved direction first')).toBeTruthy();
    expect(screen.getByText('Present always starts from one exact immutable revision.')).toBeTruthy();
  });

  test('creates a client product photo from the exact source and shows cost first', async () => {
    const createProductPresentation = jest.fn(async () => ({
      data: {
        status: 'review_required', project_id: 'project_1', image_run_id: 'run_1',
        quality_report: { verdict: 'warn' }, routing: {},
        presentation: {
          preset: 'catalog_white', framing: 'square', source_asset_id: 'asset_4', design_version: 4,
        },
        warning_candidate: {
          candidate_id: 'candidate_1', preview_url: 'https://test/product.png',
        },
      },
      error: null,
      status: 201,
    }));
    await render(<StudioPresentWorkspace
      gateway={{
        createBeautyPresentation: jest.fn(), createProductPresentation,
        createMarketingPresentation: jest.fn(),
      } as any}
      lineage={lineage}
      createdBy="designer"
    />);

    expect(screen.getByText('Revision 4 · asset_4')).toBeTruthy();
    expect(screen.getByText('1 requested output · estimated 18 credits')).toBeTruthy();
    fireEvent.press(screen.getByText('Product photo'));
    const generate = await screen.findByText('Create client product photo');
    await act(async () => { fireEvent.press(generate); });

    await waitFor(() => expect(createProductPresentation).toHaveBeenCalledWith('project_1', {
      created_by: 'designer', expected_asset_id: 'asset_4', expected_design_version: 4,
      preset: 'catalog_white', framing: 'square', presentation_only: true,
    }));
    expect(await screen.findByText('Review-only · not part of canonical design history')).toBeTruthy();
  });

  test('prices marketing by requested outputs and reports partial QA failures honestly', async () => {
    const createMarketingPresentation = jest.fn(async () => ({
      data: {
        status: 'review_required', project_id: 'project_1', source_asset_id: 'asset_4',
        design_version: 4, requested_count: 2, candidate_count: 1, failed_count: 1,
        maximum_provider_attempts: 6, actual_attempts: 3,
        candidates: [{
          preset: 'catalog_white', framing: 'square', image_run_id: 'run_1',
          candidate_id: 'candidate_1', preview_url: 'https://test/market.png', qa: { verdict: 'pass' }, routing: {},
        }],
        failures: [{ preset: 'luxury_studio', detail: 'Could not preserve the setting.' }],
      },
      error: null,
      status: 201,
    }));
    await render(<StudioPresentWorkspace
      gateway={{
        createBeautyPresentation: jest.fn(), createProductPresentation: jest.fn(),
        createMarketingPresentation,
      } as any}
      lineage={lineage}
      createdBy="designer"
    />);

    fireEvent.press(screen.getByText('Marketing'));
    expect(await screen.findByText('2 requested outputs · estimated 36 credits')).toBeTruthy();
    expect(screen.getByText('Estimate: 18 credits per requested output. Internal retries and failed quality checks add 0 credits.')).toBeTruthy();
    await act(async () => { fireEvent.press(screen.getByText('Generate 2 review candidates')); });

    await waitFor(() => expect(createMarketingPresentation).toHaveBeenCalledWith('project_1', {
      created_by: 'designer', expected_asset_id: 'asset_4', expected_design_version: 4,
      presets: ['catalog_white', 'luxury_studio'], framing: 'square',
    }));
    expect(await screen.findByText('1 of 2 requested outputs are ready for review. Nothing changed your design revision.')).toBeTruthy();
    expect(screen.getByText('Luxury studio: Could not preserve the setting.')).toBeTruthy();
  });
});
