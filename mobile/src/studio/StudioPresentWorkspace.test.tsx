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
    const onProjectUpdated = jest.fn();
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
    const acceptPresentationCandidate = jest.fn(async () => ({
      data: { candidateId: 'candidate_1', project: { root_id: 'project_1' } },
      error: null,
      status: 201,
    }));
    await render(<StudioPresentWorkspace
      gateway={{
        createBeautyPresentation: jest.fn(), createProductPresentation,
        createMarketingPresentation: jest.fn(), acceptPresentationCandidate,
        discardPresentationCandidate: jest.fn(),
      } as any}
      lineage={lineage}
      createdBy="designer"
      onProjectUpdated={onProjectUpdated}
    />);

    expect(screen.getByText('Confirmed revision 4')).toBeTruthy();
    expect(screen.queryByText(/asset_4/)).toBeNull();
    expect(screen.getByText('1 requested output · estimated 18 credits')).toBeTruthy();
    fireEvent.press(screen.getByText('Product photo'));
    const generate = await screen.findByText('Create client product photo');
    await act(async () => { fireEvent.press(generate); });

    await waitFor(() => expect(createProductPresentation).toHaveBeenCalledWith('project_1', {
      created_by: 'designer', expected_asset_id: 'asset_4', expected_design_version: 4,
      preset: 'catalog_white', framing: 'square', presentation_only: true,
    }));
    expect(await screen.findByText('Not saved · choose what to keep')).toBeTruthy();
    expect(screen.queryByText(/canonical|quality|QA/i)).toBeNull();
    await act(async () => { fireEvent.press(screen.getByText('Save presentation')); });
    await waitFor(() => expect(acceptPresentationCandidate).toHaveBeenCalledWith({
      candidateId: 'candidate_1', createdBy: 'designer',
    }));
    expect(await screen.findByText(/Saved presentation .* Review recommended/)).toBeTruthy();
    expect(onProjectUpdated).toHaveBeenCalledWith({ root_id: 'project_1' });
  });

  test('lets a designer discard a beauty preview without saving it', async () => {
    const discardPresentationCandidate = jest.fn(async () => ({
      data: { candidateId: 'candidate_beauty', project: { root_id: 'project_1' } },
      error: null,
      status: 200,
    }));
    await render(<StudioPresentWorkspace
      gateway={{
        createBeautyPresentation: jest.fn(async () => ({
          data: {
            status: 'review_required', project_id: 'project_1', source_asset_id: 'asset_4',
            image_run_id: 'run_beauty', quality_report: { verdict: 'warn' }, routing: {},
            warning_candidate: {
              run_id: 'run_beauty', candidate_id: 'candidate_beauty',
              preview_url: 'https://test/beauty.png',
            },
          },
          error: null,
          status: 202,
        })),
        createProductPresentation: jest.fn(), createMarketingPresentation: jest.fn(),
        acceptPresentationCandidate: jest.fn(), discardPresentationCandidate,
      } as any}
      lineage={lineage}
      createdBy="designer"
    />);

    await act(async () => { fireEvent.press(screen.getByText('Create client beauty render')); });
    expect(await screen.findByText('Beauty render needs review')).toBeTruthy();
    await act(async () => { fireEvent.press(screen.getByText('Discard')); });
    expect(discardPresentationCandidate).toHaveBeenCalledWith({
      candidateId: 'candidate_beauty', createdBy: 'designer',
    });
    expect(await screen.findByText('Presentation discarded. Your selected design revision is unchanged.')).toBeTruthy();
    expect(screen.queryByText('Beauty render needs review')).toBeNull();
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
        createMarketingPresentation, acceptPresentationCandidate: jest.fn(),
        discardPresentationCandidate: jest.fn(async ({ candidateId }) => ({
          data: { candidateId, project: { root_id: 'project_1' } }, error: null, status: 200,
        })),
      } as any}
      lineage={lineage}
      createdBy="designer"
    />);

    fireEvent.press(screen.getByText('Marketing'));
    expect(await screen.findByText('2 requested outputs · estimated 36 credits')).toBeTruthy();
    expect(screen.getByText('You are charged only for the requested outputs you save. Discarded and unusable results cost 0 credits.')).toBeTruthy();
    expect(screen.queryByText(/failed quality checks/i)).toBeNull();
    await act(async () => { fireEvent.press(screen.getByText('Generate 2 presentation previews')); });

    await waitFor(() => expect(createMarketingPresentation).toHaveBeenCalledWith('project_1', {
      created_by: 'designer', expected_asset_id: 'asset_4', expected_design_version: 4,
      presets: ['catalog_white', 'luxury_studio'], framing: 'square',
    }));
    expect(await screen.findByText('1 of 2 requested outputs are ready for review. Nothing changed your design revision.')).toBeTruthy();
    expect(screen.getByText(/Design preserved/)).toBeTruthy();
    expect(screen.getByText('Luxury studio: Could not preserve the setting.')).toBeTruthy();
    await act(async () => { fireEvent.press(screen.getByText('Discard')); });
    expect(await screen.findByText('Presentation discarded. Your selected design revision is unchanged.')).toBeTruthy();
    expect(screen.queryByText('Catalog white needs review')).toBeNull();
  });

  test('replaces backend lineage diagnostics with designer recovery guidance', async () => {
    await render(<StudioPresentWorkspace
      gateway={{
        createBeautyPresentation: jest.fn(async () => ({
          data: null,
          error: {
            code: 'presentation_candidate_lineage_mismatch',
            message: 'source_spec_visual_hash mismatch for run run_secret',
            category: 'conflict', status: 409, retryable: false,
          },
          status: 409,
        })),
        createProductPresentation: jest.fn(), createMarketingPresentation: jest.fn(),
        acceptPresentationCandidate: jest.fn(), discardPresentationCandidate: jest.fn(),
      } as any}
      lineage={lineage}
      createdBy="designer"
    />);

    await act(async () => { fireEvent.press(screen.getByText('Create client beauty render')); });
    expect(await screen.findByText(
      'This preview belongs to an earlier design revision. Generate it again from the selected revision.',
    )).toBeTruthy();
    expect(screen.queryByText(/source_spec_visual_hash|run_secret/)).toBeNull();
  });
});
