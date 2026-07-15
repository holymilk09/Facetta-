import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { StudioPresentWorkspace } from './StudioPresentWorkspace';
import { AuthenticatedImageProvider } from '../AuthenticatedImage';

const lineage = {
  projectId: 'project_1', sourceAssetId: 'asset_4', sourceDesignVersion: 4,
};

const renderPresent = (ui: React.ReactElement) => render(
  <AuthenticatedImageProvider
    allowedOrigin="https://test"
    headers={{ Authorization: 'Bearer first-party-token' }}>
    {ui}
  </AuthenticatedImageProvider>,
);

describe('StudioPresentWorkspace', () => {
  test('fails closed without a saved design source', async () => {
    await renderPresent(<StudioPresentWorkspace gateway={{} as any} lineage={null} createdBy="designer" />);
    expect(screen.getByText('Choose a saved direction first')).toBeTruthy();
    expect(screen.getByText('Present always starts from one saved design source.')).toBeTruthy();
  });

  test('opens the already-saved Library destination without generation or a job', async () => {
    const onOpenCollections = jest.fn();
    const generation = {
      createBeautyPresentation: jest.fn(),
      createProductPresentation: jest.fn(),
      createMarketingPresentation: jest.fn(),
      createPreSpecPresentation: jest.fn(),
    };
    await renderPresent(<StudioPresentWorkspace
      gateway={{
        ...generation,
        acceptPresentationCandidate: jest.fn(), discardPresentationCandidate: jest.fn(),
        acceptPreSpecPresentation: jest.fn(), discardPreSpecPresentation: jest.fn(),
      } as any}
      lineage={lineage}
      createdBy="designer"
      onOpenCollections={onOpenCollections}
    />);

    await act(async () => { fireEvent.press(screen.getByRole('radio', { name: 'Library' })); });
    expect(screen.getByText('Already saved · 0 credits')).toBeTruthy();
    expect(screen.getByText(/Viewing it creates no copy or job/i)).toBeTruthy();
    expect(screen.queryByText(/Generate .*preview/i)).toBeNull();
    fireEvent.press(screen.getByText('View in Collections'));
    expect(onOpenCollections).toHaveBeenCalledTimes(1);
    Object.values(generation).forEach((method) => expect(method).not.toHaveBeenCalled());
  });

  test('labels an earlier Library source instead of silently presenting the current revision', async () => {
    const onOpenCollections = jest.fn();
    await renderPresent(<StudioPresentWorkspace
      gateway={{
        createBeautyPresentation: jest.fn(), createProductPresentation: jest.fn(),
        createMarketingPresentation: jest.fn(), createPreSpecPresentation: jest.fn(),
        acceptPresentationCandidate: jest.fn(), discardPresentationCandidate: jest.fn(),
        acceptPreSpecPresentation: jest.fn(), discardPreSpecPresentation: jest.fn(),
      } as any}
      lineage={lineage}
      createdBy="designer"
      reviewSourceIsActive={false}
      onOpenCollections={onOpenCollections}
    />);

    await act(async () => {
      fireEvent.press(screen.getByRole('radio', { name: 'Library' }));
    });
    expect(screen.getByText(/This earlier source remains in immutable history/i)).toBeTruthy();
    expect(screen.queryByText('View in Collections')).toBeNull();
    fireEvent.press(screen.getByText('View project history'));
    expect(onOpenCollections).toHaveBeenCalledTimes(1);
  });

  test('restores exact-revision presentation previews after remount', async () => {
    const acceptPresentationCandidate = jest.fn();
    const resumeExactPresentations = jest.fn(async () => ({
      data: [{
        lineage,
        candidate: {
          candidate_id: 'candidate_resumed', image_run_id: 'run_resumed',
          project_id: 'project_1', source_asset_id: 'asset_4', source_sha256: 'a'.repeat(64),
          design_version: 4, destination: 'client', preview_url: 'https://test/resumed.png',
          studio_job_id: 'job_resumed', capability: 'CLIENT_PRODUCT_PHOTO',
          preset: 'catalog_white', framing: 'square', qa: { verdict: 'pass', checks: [] },
          status: 'reviewing', accepted_asset_id: null, expires_at: '2026-07-14T00:00:00Z',
        },
      }],
      error: null,
      status: 200,
    }));
    await renderPresent(<StudioPresentWorkspace
      gateway={{
        resumeExactPresentations, createBeautyPresentation: jest.fn(),
        createProductPresentation: jest.fn(), createMarketingPresentation: jest.fn(),
        acceptPresentationCandidate, discardPresentationCandidate: jest.fn(),
        createPreSpecPresentation: jest.fn(), resumePreSpecPresentations: jest.fn(),
        acceptPreSpecPresentation: jest.fn(), discardPreSpecPresentation: jest.fn(),
      } as any}
      lineage={lineage}
      createdBy="designer"
    />);
    expect(await screen.findByText('Catalog white')).toBeTruthy();
    expect(screen.getByText('1 saved preview resumed for review.')).toBeTruthy();
    expect(screen.queryByText('1 · Destination')).toBeNull();
    expect(screen.queryByText('Create client beauty render')).toBeNull();
    expect(screen.getByText(/exact source revision cannot be displayed/i)).toBeTruthy();
    fireEvent.press(screen.getByText('Save presentation'));
    expect(acceptPresentationCandidate).not.toHaveBeenCalled();
    expect(resumeExactPresentations).toHaveBeenCalledWith(lineage, 'designer');
  });

  test('hides revision A cards immediately while deferred revision B resumes', async () => {
    const lineageB = { projectId: 'project_2', sourceAssetId: 'asset_8', sourceDesignVersion: 5 };
    const resumed = (candidateId: string, requestedLineage: typeof lineage) => ({
      data: [{
        lineage: requestedLineage,
        candidate: {
          candidate_id: candidateId, image_run_id: `run_${candidateId}`,
          project_id: requestedLineage.projectId, source_asset_id: requestedLineage.sourceAssetId,
          source_sha256: 'a'.repeat(64), design_version: requestedLineage.sourceDesignVersion,
          destination: 'client', preview_url: `https://test/${candidateId}.png`,
          studio_job_id: `job_${candidateId}`, capability: 'CLIENT_BEAUTY_RENDER',
          preset: 'luxury_studio', framing: 'square', qa: { verdict: 'pass', checks: [] },
          status: 'reviewing', accepted_asset_id: null, expires_at: '2026-07-14T00:00:00Z',
        },
      }], error: null, status: 200,
    });
    let resolveB: ((value: any) => void) | null = null;
    const resumeExactPresentations = jest.fn((requested: typeof lineage) => (
      requested.projectId === 'project_1' ? Promise.resolve(resumed('candidate_a', lineage))
        : new Promise((resolve) => { resolveB = resolve; })
    ));
    const gateway = {
      resumeExactPresentations, createBeautyPresentation: jest.fn(),
      createProductPresentation: jest.fn(), createMarketingPresentation: jest.fn(),
      acceptPresentationCandidate: jest.fn(), discardPresentationCandidate: jest.fn(),
      createPreSpecPresentation: jest.fn(), resumePreSpecPresentations: jest.fn(),
      acceptPreSpecPresentation: jest.fn(), discardPreSpecPresentation: jest.fn(),
    } as any;
    const rendered = await renderPresent(<StudioPresentWorkspace
      gateway={gateway} lineage={lineage} createdBy="designer"
    />);
    expect(await screen.findByText('Results')).toBeTruthy();
    expect(screen.getByText('1 saved preview resumed for review.')).toBeTruthy();

    await act(async () => {
      rendered.rerender(<StudioPresentWorkspace
        gateway={gateway} lineage={lineageB} createdBy="designer"
      />);
    });
    expect(screen.queryByText('Results')).toBeNull();
    expect(screen.queryByText('1 saved preview resumed for review.')).toBeNull();
    expect(screen.getByText('Exact saved revision')).toBeTruthy();
    expect(screen.queryByText(/(?:Version|Design v)\s*5/i)).toBeNull();
    expect(resumeExactPresentations).toHaveBeenLastCalledWith(lineageB, 'designer');

    await act(async () => { resolveB?.(resumed('candidate_b', lineageB)); });
    expect(await screen.findByText('Results')).toBeTruthy();
  });

  test('creates a client product photo from the exact source and shows cost first', async () => {
    const onProjectUpdated = jest.fn();
    const onOpenCollections = jest.fn();
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
    await renderPresent(<StudioPresentWorkspace
      gateway={{
        createBeautyPresentation: jest.fn(), createProductPresentation,
        createMarketingPresentation: jest.fn(), acceptPresentationCandidate,
        discardPresentationCandidate: jest.fn(),
        assetImageUrl: jest.fn(() => 'https://test/source.png'),
      } as any}
      lineage={lineage}
      createdBy="designer"
      onProjectUpdated={onProjectUpdated}
      onOpenCollections={onOpenCollections}
    />);

    expect(screen.getByText('Exact saved revision')).toBeTruthy();
    expect(screen.queryByText(/(?:Version|Design v)\s*4/i)).toBeNull();
    expect(screen.getByText('What would you like to do with this exact design?')).toBeTruthy();
    expect(screen.getByText('Exact revision source')).toBeTruthy();
    expect(screen.queryByText(/asset_4/)).toBeNull();
    expect(screen.getByText('1 requested output · estimated 18 credits')).toBeTruthy();
    expect(screen.getByText(/Generation creates review previews only/i)).toBeTruthy();
    expect(screen.getByText(/charged only for the outputs you explicitly save/i)).toBeTruthy();
    await act(async () => { fireEvent.press(screen.getByLabelText('Style and framing')); });
    fireEvent.press(screen.getByText('Product photo'));
    const generate = await screen.findByText('Create client product photo');
    await act(async () => { fireEvent.press(generate); });

    await waitFor(() => expect(createProductPresentation).toHaveBeenCalledWith('project_1', {
      created_by: 'designer', expected_asset_id: 'asset_4', expected_design_version: 4,
      preset: 'catalog_white', framing: 'square', presentation_only: true,
    }));
    expect(await screen.findByText('Not saved · choose what to keep')).toBeTruthy();
    expect(screen.getByTestId('presentation-comparison-candidate_1')).toBeTruthy();
    expect(screen.getByText('Source: Exact saved revision')).toBeTruthy();
    expect(screen.getByText('Candidate: Catalog white needs review')).toBeTruthy();
    expect(screen.queryByText('1 · Destination')).toBeNull();
    expect(screen.queryByText('Create client product photo')).toBeNull();
    expect(screen.queryByText(/canonical|quality|QA/i)).toBeNull();
    fireEvent.press(screen.getByText('Save presentation'));
    expect(acceptPresentationCandidate).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent(screen.getByLabelText('Exact source revision'), 'load');
      fireEvent(screen.getByLabelText('Catalog white needs review'), 'error');
    });
    expect(screen.getByText(/comparison could not be displayed/i)).toBeTruthy();
    fireEvent.press(screen.getByText('Save presentation'));
    expect(acceptPresentationCandidate).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent(screen.getByLabelText('Catalog white needs review'), 'load');
    });
    await act(async () => { fireEvent.press(screen.getByText('Save presentation')); });
    await waitFor(() => expect(acceptPresentationCandidate).toHaveBeenCalledWith({
      candidateId: 'candidate_1', createdBy: 'designer',
    }));
    expect(await screen.findByText(/Saved presentation .* Review recommended/)).toBeTruthy();
    expect(onProjectUpdated).toHaveBeenCalledWith({ root_id: 'project_1' });
    expect(screen.getByText('Create another presentation')).toBeTruthy();
    expect(screen.getAllByText('Open in Collections')).toHaveLength(1);
    fireEvent.press(screen.getByText('Open in Collections'));
    expect(onOpenCollections).toHaveBeenCalledTimes(1);
  });

  test('lets a designer discard a beauty preview without saving it', async () => {
    const discardPresentationCandidate = jest.fn(async () => ({
      data: { candidateId: 'candidate_beauty', project: { root_id: 'project_1' } },
      error: null,
      status: 200,
    }));
    await renderPresent(<StudioPresentWorkspace
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
    expect(screen.getByText('Create another presentation')).toBeTruthy();
    await act(async () => {
      fireEvent.press(screen.getByText('Create another presentation'));
    });
    expect(await screen.findByText('What do you need?')).toBeTruthy();
    expect(screen.getByLabelText('Presentation destination').props.accessibilityRole)
      .toBe('radiogroup');
    expect(screen.getByText('Create client beauty render')).toBeTruthy();
  });

  test('keeps an unresolved presentation visible until its decision succeeds', async () => {
    const discardPresentationCandidate = jest.fn()
      .mockResolvedValueOnce({
        data: null,
        error: {
          code: 'temporary_failure', message: 'temporary failure',
          category: 'network', status: 503, retryable: true,
        },
        status: 503,
      })
      .mockResolvedValueOnce({
        data: { candidateId: 'candidate_pending', project: { root_id: 'project_1' } },
        error: null,
        status: 200,
      });
    const createBeautyPresentation = jest.fn(async () => ({
      data: {
        status: 'review_required', project_id: 'project_1', source_asset_id: 'asset_4',
        image_run_id: 'run_pending', quality_report: { verdict: 'pass' }, routing: {},
        warning_candidate: {
          run_id: 'run_pending', candidate_id: 'candidate_pending',
          preview_url: 'https://test/pending.png',
        },
      },
      error: null,
      status: 202,
    }));
    await renderPresent(<StudioPresentWorkspace
      gateway={{
        createBeautyPresentation, createProductPresentation: jest.fn(),
        createMarketingPresentation: jest.fn(), acceptPresentationCandidate: jest.fn(),
        discardPresentationCandidate, assetImageUrl: jest.fn(() => 'https://test/source.png'),
      } as any}
      lineage={lineage}
      createdBy="designer"
    />);

    await act(async () => { fireEvent.press(screen.getByText('Create client beauty render')); });
    expect(await screen.findByText('Beauty render needs review')).toBeTruthy();
    expect(screen.queryByText('Create client beauty render')).toBeNull();
    await act(async () => { fireEvent.press(screen.getByText('Discard')); });
    expect(screen.getByText('Beauty render needs review')).toBeTruthy();
    expect(screen.queryByText('Create another presentation')).toBeNull();
    expect(createBeautyPresentation).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(
      'Facetta could not reach the image service. Check your connection and try again.',
    )).toBeTruthy();

    await act(async () => { fireEvent.press(screen.getByText('Discard')); });
    expect(screen.queryByText('Beauty render needs review')).toBeNull();
    expect(screen.getByText('Create another presentation')).toBeTruthy();
  });

  test('fails closed instead of displaying a generation-time auto-saved Client output', async () => {
    const onProjectUpdated = jest.fn();
    await renderPresent(<StudioPresentWorkspace
      gateway={{
        createBeautyPresentation: jest.fn(async () => ({
          data: {
            status: 'accepted', asset_id: 'unexpected_saved', source_asset_id: 'asset_4',
            image_run_id: 'run_unexpected', qa: { verdict: 'pass' },
            project: { root_id: 'project_1', assets: [], derived_assets: [] },
          },
          error: null,
          status: 201,
        })),
        createProductPresentation: jest.fn(), createMarketingPresentation: jest.fn(),
        acceptPresentationCandidate: jest.fn(), discardPresentationCandidate: jest.fn(),
        assetImageUrl: jest.fn(() => 'https://test/source.png'),
      } as any}
      lineage={lineage}
      createdBy="designer"
      onProjectUpdated={onProjectUpdated}
    />);

    await act(async () => { fireEvent.press(screen.getByText('Create client beauty render')); });
    expect(await screen.findByText(
      'Facetta could not open a safe review preview. Nothing was saved or charged.',
    )).toBeTruthy();
    expect(screen.queryByText('Saved presentation')).toBeNull();
    expect(onProjectUpdated).not.toHaveBeenCalled();
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
        failures: [{
          preset: 'luxury_studio', image_run_id: null,
          error_category: 'provider', code: 'openai_provider_not_configured',
          detail: 'OpenAI transport failed for model gpt-image-secret.',
        }],
      },
      error: null,
      status: 201,
    }));
    await renderPresent(<StudioPresentWorkspace
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
    expect(screen.getByText(/Generation creates review previews only/i)).toBeTruthy();
    expect(screen.queryByText(/saved and charged when generation finishes/i)).toBeNull();
    expect(screen.queryByText(/failed quality checks/i)).toBeNull();
    await act(async () => { fireEvent.press(screen.getByText('Generate 2 presentation previews')); });

    await waitFor(() => expect(createMarketingPresentation).toHaveBeenCalledWith('project_1', {
      created_by: 'designer', expected_asset_id: 'asset_4', expected_design_version: 4,
      presets: ['catalog_white', 'luxury_studio'], framing: 'square',
    }));
    expect(await screen.findByText('1 of 2 requested outputs are ready for review. Nothing changed your design revision.')).toBeTruthy();
    expect(screen.getByText(/Design preserved/)).toBeTruthy();
    expect(screen.getByText(
      'Luxury studio: Facetta could not finish this output. Nothing was saved or charged; try it again.',
    )).toBeTruthy();
    expect(screen.queryByText(/OpenAI|gpt-image|provider_not_configured/i)).toBeNull();
    await act(async () => { fireEvent.press(screen.getByText('Discard')); });
    expect(await screen.findByText('Presentation discarded. Your selected design revision is unchanged.')).toBeTruthy();
    expect(screen.queryByText('Catalog white needs review')).toBeNull();
  });

  test('replaces backend lineage diagnostics with designer recovery guidance', async () => {
    await renderPresent(<StudioPresentWorkspace
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

  test('creates and saves Client material from a selected pre-spec visual', async () => {
    const visualLineage = { projectId: 'project_visual', sourceAssetId: 'asset_visual' };
    const createPreSpecPresentation = jest.fn(async () => ({
      data: {
        status: 'review_required', project_id: 'project_visual',
        source_asset_id: 'asset_visual', source_sha256: 'a'.repeat(64),
        design_version: null, destination: 'client', client_format: 'beauty',
        candidate: {
          candidate_id: 'candidate_client', image_run_id: 'run_client',
          preview_url: 'https://test/client.png', capability: 'CLIENT_BEAUTY_RENDER',
          preset: 'luxury_studio', framing: 'square', qa: { verdict: 'pass' },
        },
      },
      error: null,
      status: 201,
    }));
    const acceptPreSpecPresentation = jest.fn(async () => ({
      data: { candidateId: 'candidate_client', project: { root_id: 'project_visual' } },
      error: null,
      status: 201,
    }));
    await renderPresent(<StudioPresentWorkspace
      gateway={{
        createPreSpecPresentation, acceptPreSpecPresentation,
        discardPreSpecPresentation: jest.fn(), createBeautyPresentation: jest.fn(),
        createProductPresentation: jest.fn(), createMarketingPresentation: jest.fn(),
        acceptPresentationCandidate: jest.fn(), discardPresentationCandidate: jest.fn(),
        assetImageUrl: jest.fn(() => 'https://test/source.png'),
      } as any}
      lineage={visualLineage}
      createdBy="designer"
    />);

    expect(screen.getByText('Selected visual direction · specification not confirmed')).toBeTruthy();
    expect(screen.getByText('What would you like to do with this saved visual direction?')).toBeTruthy();
    expect(screen.getByText('Selected visual source')).toBeTruthy();
    expect(screen.queryByText(/this exact design/i)).toBeNull();
    expect(screen.queryByText('Exact revision source')).toBeNull();
    await act(async () => { fireEvent.press(screen.getByText('Create client beauty render')); });
    await waitFor(() => expect(createPreSpecPresentation).toHaveBeenCalledWith('project_visual', {
      created_by: 'designer', expected_active_asset_id: 'asset_visual',
      destination: 'client', client_format: 'beauty', preset: 'luxury_studio',
      framing: 'square',
    }));
    expect(await screen.findByText('Not saved · choose what to keep')).toBeTruthy();
    await act(async () => {
      fireEvent(screen.getByLabelText('Selected visual source'), 'load');
      fireEvent(screen.getByLabelText('Client beauty render'), 'load');
    });
    await act(async () => { fireEvent.press(screen.getByText('Save presentation')); });
    expect(acceptPreSpecPresentation).toHaveBeenCalledWith({
      candidateId: 'candidate_client', createdBy: 'designer',
    });
    expect(screen.queryByText(/factory|production-ready/i)).toBeNull();
  });

  test('generates a selectable pre-spec Marketing set and discards through visual lineage', async () => {
    const calls: any[] = [];
    const createPreSpecPresentation = jest.fn(async (_projectId: string, request: any) => {
      calls.push(request);
      return {
        data: {
          status: 'review_required', project_id: 'project_visual',
          source_asset_id: 'asset_visual', source_sha256: 'b'.repeat(64),
          design_version: null, destination: 'marketing', client_format: 'product',
          candidate: {
            candidate_id: `candidate_${request.preset}`, image_run_id: `run_${request.preset}`,
            preview_url: `https://test/${request.preset}.png`, capability: 'MARKETING_IMAGE',
            preset: request.preset, framing: 'square', qa: { verdict: 'pass' },
          },
        },
        error: null,
        status: 201,
      };
    });
    const discardPreSpecPresentation = jest.fn(async ({ candidateId }) => ({
      data: { candidateId, project: { root_id: 'project_visual' } },
      error: null, status: 200,
    }));
    const acceptPreSpecPresentation = jest.fn(async ({ candidateId }) => ({
      data: { candidateId, project: { root_id: 'project_visual' } },
      error: null, status: 201,
    }));
    await renderPresent(<StudioPresentWorkspace
      gateway={{
        createPreSpecPresentation, discardPreSpecPresentation,
        acceptPreSpecPresentation, createBeautyPresentation: jest.fn(),
        createProductPresentation: jest.fn(), createMarketingPresentation: jest.fn(),
        acceptPresentationCandidate: jest.fn(), discardPresentationCandidate: jest.fn(),
        assetImageUrl: jest.fn(() => 'https://test/source.png'),
      } as any}
      lineage={{ projectId: 'project_visual', sourceAssetId: 'asset_visual' }}
      createdBy="designer"
    />);

    await act(async () => { fireEvent.press(screen.getByText('Marketing')); });
    expect(screen.getByText(/charged only for the outputs you explicitly save/i)).toBeTruthy();
    const generate = await screen.findByText('Generate 2 presentation previews');
    await act(async () => { fireEvent.press(generate); });
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls.map((call) => call.preset)).toEqual(['catalog_white', 'luxury_studio']);
    expect(await screen.findByText('2 of 2 requested outputs are ready for review. Your selected visual is unchanged.')).toBeTruthy();
    expect(screen.getAllByText('Source: Selected visual direction · specification not confirmed')).toHaveLength(2);
    expect(screen.getByText('Candidate: Catalog white')).toBeTruthy();
    expect(screen.getByText('Candidate: Luxury studio')).toBeTruthy();
    expect(screen.getAllByLabelText('Selected visual source')).toHaveLength(2);
    expect(screen.getByTestId('presentation-comparison-candidate_catalog_white')).toBeTruthy();
    expect(screen.getByTestId('presentation-comparison-candidate_luxury_studio')).toBeTruthy();
    await act(async () => {
      fireEvent(screen.getAllByLabelText('Selected visual source')[0], 'load');
      fireEvent(screen.getByLabelText('Catalog white'), 'load');
    });
    const saveButtons = screen.getAllByText('Save presentation');
    fireEvent.press(saveButtons[1]);
    expect(acceptPreSpecPresentation).not.toHaveBeenCalled();
    await act(async () => { fireEvent.press(saveButtons[0]); });
    expect(acceptPreSpecPresentation).toHaveBeenCalledWith({
      candidateId: 'candidate_catalog_white', createdBy: 'designer',
    });
    const discardButtons = screen.getAllByText('Discard');
    await act(async () => { fireEvent.press(discardButtons[0]); });
    expect(discardPreSpecPresentation).toHaveBeenCalledWith({
      candidateId: 'candidate_luxury_studio', createdBy: 'designer',
    });
    expect(screen.getByText('Catalog white')).toBeTruthy();
  });

  test('resumes durable pre-spec previews after the workspace remounts', async () => {
    const resumePreSpecPresentations = jest.fn(async () => ({
      data: [{
        status: 'review_required', project_id: 'project_visual',
        source_asset_id: 'asset_visual', source_sha256: 'c'.repeat(64),
        design_version: null, destination: 'client', client_format: 'product',
        candidate: {
          candidate_id: 'candidate_resumed', image_run_id: 'run_resumed',
          preview_url: 'https://test/resumed.png', studio_job_id: 'job_resumed',
          capability: 'CLIENT_PRODUCT_PHOTO', preset: 'catalog_white',
          framing: 'square', qa: { verdict: 'pass' },
        },
      }],
      error: null,
      status: 200,
    }));
    await renderPresent(<StudioPresentWorkspace
      gateway={{
        resumePreSpecPresentations, createPreSpecPresentation: jest.fn(),
        acceptPreSpecPresentation: jest.fn(), discardPreSpecPresentation: jest.fn(),
        createBeautyPresentation: jest.fn(), createProductPresentation: jest.fn(),
        createMarketingPresentation: jest.fn(), acceptPresentationCandidate: jest.fn(),
        discardPresentationCandidate: jest.fn(),
      } as any}
      lineage={{ projectId: 'project_visual', sourceAssetId: 'asset_visual' }}
      createdBy="designer"
    />);

    expect(await screen.findByText('1 saved preview resumed for review.')).toBeTruthy();
    expect(screen.getByText('Catalog white')).toBeTruthy();
    expect(screen.getByText('Not saved · choose what to keep')).toBeTruthy();
    expect(screen.queryByText('1 · Destination')).toBeNull();
    expect(screen.queryByText('Create client beauty render')).toBeNull();
  });
});
