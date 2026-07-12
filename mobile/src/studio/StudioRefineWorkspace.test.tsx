import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { AuthenticatedImageProvider } from '../AuthenticatedImage';
import { StudioRefineWorkspace } from './StudioRefineWorkspace';
import type { ProjectDetail } from '../trusted/types';

const project = {
  id: 'project_1', root_id: 'project_1', title: 'Orbit', collection: null,
  tags: [], owner: 'designer', state: 'refining', design_id: 'design_1', spec: {},
  active_asset_id: 'asset_2', active_design_version: 2, active_revision: null,
  pinned_revision: null, revisions: [], assets: [], derived_assets: [], approval: null,
  factory_ready: false, factory_blockers: [], primary_revision_count: 2,
  has_factory_drawing: false, cover_asset_id: 'asset_2', created_at: null, updated_at: null,
} as ProjectDetail;

const preSpecProject = {
  ...project,
  design_id: null,
  spec: null,
  active_asset_id: 'creative_2',
  active_design_version: null,
  active_revision: {
    asset_id: 'creative_2', root_id: 'project_1', parent_asset_id: 'creative_1',
    capability: 'CREATIVE_RENDER', provenance: 'pre_spec_creative_candidate',
    revision: 2, design_version: null, region: null, instruction: 'Softer finish',
    drift: null, pinned: false, media_type: 'image/png', image_url: 'https://test/applied.png',
    created_by: 'designer', created_at: null, legacy_provenance: false,
  },
} as ProjectDetail;

const exactFactProject = {
  ...project,
  spec: {
    jewelry_type: 'ring',
    metal: { material: 'gold', karat: 18, color: 'yellow', finish: 'polished' },
    stone: {
      species: 'sapphire', cut: 'oval', carat: 1.2,
      dimensions_mm: { length: 8, width: 6, depth: 3.8 },
      color: { trade: 'royal_blue', gia: 'blue' },
    },
    setting: { style: 'prong', prong_count: 4 },
    band: { profile: 'half_round', width_mm: 2.1, thickness_mm: 1.8 },
    ring_size: { system: 'US', value: 6.5, inner_diameter_mm: 16.9 },
  },
} as ProjectDetail;

const catalog = {
  component_path: 'metal.color' as const,
  display: 'Metal color', applicable_jewelry_types: ['ring'],
  image_agent_status: 'catalog_ready' as const,
  options: [{
    id: 'rose_gold', display: 'Rose gold', visual_geometry: [],
    isolation_target: 'Visible metal surfaces', frozen_facts: ['stone geometry'],
    factory_fields: {}, derived_factory_fields: [], selection_requirements: [],
  }],
};

const responderEvent = (locationX: number, locationY: number) => ({
  nativeEvent: { locationX, locationY },
});

function renderWithAuth(ui: React.ReactElement) {
  return render(
    <AuthenticatedImageProvider
      allowedOrigin="https://test"
      headers={{ Authorization: 'Bearer test-session-token' }}>
      {ui}
    </AuthenticatedImageProvider>,
  );
}

describe('StudioRefineWorkspace', () => {
  test('fails closed when there is no exact immutable revision', async () => {
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog: jest.fn(async () => ({ data: catalog, error: null, status: 200 })),
          readMarkup: jest.fn(),
        }}
        gateway={{
          previewVisualRefine: jest.fn(), applyVisualRefine: jest.fn(), discardVisualRefine: jest.fn(),
          previewCatalogRefine: jest.fn(), applyCatalogRefine: jest.fn(), discardCatalogRefine: jest.fn(),
          previewMarkupRefine: jest.fn(), applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
        }}
        lineage={null}
        createdBy="designer"
        onApplied={jest.fn()}
      />,
    );
    expect(screen.getByText('Choose a saved direction first')).toBeTruthy();
  });

  test('keeps a candidate temporary until explicit apply', async () => {
    const onApplied = jest.fn();
    const previewCatalogRefine = jest.fn(async () => ({
      data: {
        lineage: { projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 },
        componentPath: 'metal.color' as const, optionId: 'rose_gold',
        candidate: {
          id: 'candidate_1', jobId: 'run_1', sourceRevisionId: 'asset_2',
          assetUrl: 'https://test/preview.png', verdict: 'pass' as const,
          status: 'pending_review' as const, checks: [{
            id: 'drift', label: 'Outside drift', verdict: 'pass' as const, detail: 'Unrelated geometry stayed fixed.',
          }], temporary: true, expiresAt: null, decision: null,
          decidedAt: null, canonicalRevisionId: null,
        },
      },
      error: null,
      status: 201,
    }));
    const applyCatalogRefine = jest.fn(async () => ({
      data: { candidate: {}, project }, error: null, status: 201,
    }));
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog: jest.fn(async () => ({ data: catalog, error: null, status: 200 })),
          readMarkup: jest.fn(),
        }}
        gateway={{ previewCatalogRefine, applyCatalogRefine, discardCatalogRefine: jest.fn() } as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        onApplied={onApplied}
      />,
    );

    expect(screen.getByText('1 requested output × 20 credits = estimated 20 credits')).toBeTruthy();
    await act(async () => { fireEvent.press(await screen.findByText('Preview change')); });
    expect(await screen.findByText('Nothing has changed yet.')).toBeTruthy();
    expect(onApplied).not.toHaveBeenCalled();
    await act(async () => { fireEvent.press(screen.getByText('Apply as new revision')); });
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(project));
  });

  test('refines a selected pre-spec direction without inventing specification authority', async () => {
    const getComponentCatalog = jest.fn();
    const previewVisualRefine = jest.fn(async () => ({
      data: {
        lineage: { projectId: 'project_1', sourceAssetId: 'creative_1' },
        instruction: 'Make the lighting warmer', scope: 'appearance' as const,
        candidate: {
          id: 'candidate_visual', jobId: 'run_visual', sourceRevisionId: 'creative_1',
          assetUrl: 'https://test/preview.png', verdict: 'pass' as const,
          status: 'pending_review' as const, checks: [], temporary: true,
          expiresAt: null, decision: null, decidedAt: null, canonicalRevisionId: null,
        },
      }, error: null, status: 201,
    }));
    const applyVisualRefine = jest.fn(async () => ({
      data: {
        candidate: {
          id: 'candidate_visual', jobId: 'run_visual', sourceRevisionId: 'creative_1',
          assetUrl: 'https://test/preview.png', verdict: 'pass' as const,
          status: 'applied' as const, checks: [], temporary: true,
          expiresAt: null, decision: 'apply' as const, decidedAt: '2026-07-12T00:00:00Z',
          canonicalRevisionId: 'creative_2',
        },
        project: preSpecProject,
      }, error: null, status: 201,
    }));
    const onApplied = jest.fn();
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{ getComponentCatalog, readMarkup: jest.fn() }}
        gateway={{
          previewVisualRefine, applyVisualRefine, discardVisualRefine: jest.fn(),
          previewCatalogRefine: jest.fn(), applyCatalogRefine: jest.fn(), discardCatalogRefine: jest.fn(),
          previewMarkupRefine: jest.fn(), applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
        }}
        lineage={{ projectId: 'project_1', sourceAssetId: 'creative_1' }}
        sourceImageUrl="https://test/source.png"
        createdBy="designer"
        onApplied={onApplied}
      />,
    );

    expect(getComponentCatalog).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Component refine mode').props.accessibilityState.disabled).toBe(true);
    expect(screen.getByText(/Design facts are not confirmed yet/i)).toBeTruthy();
    await act(async () => {
      fireEvent.changeText(
        screen.getByPlaceholderText(/make the presentation softer/i),
        'Make the lighting warmer',
      );
    });
    await waitFor(() => expect(screen.getByDisplayValue('Make the lighting warmer')).toBeTruthy());
    await act(async () => { fireEvent.press(screen.getByText('Preview change')); });
    await waitFor(() => expect(previewVisualRefine).toHaveBeenCalledWith({
      projectId: 'project_1', sourceAssetId: 'creative_1', createdBy: 'designer',
      instruction: 'Make the lighting warmer', scope: 'appearance',
    }));
    expect(screen.getByLabelText('Exact source revision')).toBeTruthy();
    expect(screen.getByLabelText('Temporary refinement preview')).toBeTruthy();
    await act(async () => { fireEvent.press(screen.getByText('Apply as new revision')); });
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(preSpecProject));
    expect(preSpecProject.active_design_version).toBeNull();
  });

  test('routes pre-spec annotation through exact saved markup provenance', async () => {
    const readMarkup = jest.fn(async () => ({
      data: {
        markup_asset_id: 'markup_exact', assistant_name: 'Facetta',
        design_id: null, expected_design_version: null,
        interpretation: {
          target_region: 'highlighted upper-left metal',
          requested_change: 'Warm only this surface',
          impact: 'visual_only' as const,
          target_spec_reference: null, target_section: null, target_index: null,
          target_element_id: null, frozen_elements: ['all jewelry geometry'],
          confidence: 0.98, clarification_question: null,
          understood_as: 'Warm only the highlighted surface; preserve geometry.',
        },
      }, error: null, status: 200,
    }));
    const previewVisualRefine = jest.fn(async () => ({
      data: {
        lineage: { projectId: 'project_1', sourceAssetId: 'creative_1' },
        instruction: 'Warm only this surface', scope: 'marked_region' as const,
        candidate: {
          id: 'candidate_markup', jobId: 'run_markup', sourceRevisionId: 'creative_1',
          assetUrl: 'https://test/markup-preview.png', verdict: 'pass' as const,
          status: 'pending_review' as const, checks: [], temporary: true,
          expiresAt: null, decision: null, decidedAt: null, canonicalRevisionId: null,
        },
      }, error: null, status: 201,
    }));
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{ getComponentCatalog: jest.fn(), readMarkup }}
        gateway={{
          previewVisualRefine, applyVisualRefine: jest.fn(), discardVisualRefine: jest.fn(),
          previewCatalogRefine: jest.fn(), applyCatalogRefine: jest.fn(), discardCatalogRefine: jest.fn(),
          previewMarkupRefine: jest.fn(), applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
        }}
        lineage={{ projectId: 'project_1', sourceAssetId: 'creative_1' }}
        sourceImageUrl="https://test/source.png"
        createdBy="designer"
        onApplied={jest.fn()}
      />,
    );

    await act(async () => { fireEvent.press(screen.getByLabelText('Mark up refine mode')); });
    const canvas = await screen.findByLabelText('Jewelry image annotation canvas');
    await fireEvent(canvas, 'layout', {
      nativeEvent: { layout: { x: 0, y: 0, width: 200, height: 160 } },
    });
    await fireEvent(canvas, 'responderGrant', responderEvent(20, 20));
    await fireEvent(canvas, 'responderRelease', responderEvent(90, 80));
    await act(async () => { fireEvent.press(screen.getByText('Preview change')); });

    await waitFor(() => expect(readMarkup).toHaveBeenCalledWith(
      'creative_1',
      expect.objectContaining({ created_by: 'designer' }),
    ));
    await waitFor(() => expect(previewVisualRefine).toHaveBeenCalledWith({
      projectId: 'project_1', sourceAssetId: 'creative_1', createdBy: 'designer',
      instruction: 'Warm only this surface', scope: 'marked_region', markupAssetId: 'markup_exact',
    }));
    expect(screen.getByText(/Warm only the highlighted surface/)).toBeTruthy();
    expect(screen.getByLabelText('Temporary refinement preview')).toBeTruthy();
  });

  test('plain language is constrained to appearance and still previews first', async () => {
    const previewMarkupRefine = jest.fn(async () => ({
      data: {
        lineage: { projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 },
        annotation: {},
        candidate: {
          id: 'candidate_plain', jobId: 'run_plain', sourceRevisionId: 'asset_2',
          assetUrl: 'https://test/plain.png', verdict: 'pass' as const,
          status: 'pending_review' as const, checks: [], temporary: true,
          expiresAt: null, decision: null, decidedAt: null, canonicalRevisionId: null,
        },
      }, error: null, status: 201,
    }));
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog: jest.fn(async () => ({ data: catalog, error: null, status: 200 })),
          readMarkup: jest.fn(),
        }}
        gateway={{
          previewCatalogRefine: jest.fn(), applyCatalogRefine: jest.fn(), discardCatalogRefine: jest.fn(),
          previewMarkupRefine, applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
        } as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        onApplied={jest.fn()}
      />,
    );
    fireEvent.press(screen.getByLabelText('Describe refine mode'));
    expect(await screen.findByText(/changes presentation only/i)).toBeTruthy();
    fireEvent.changeText(
      screen.getByPlaceholderText(/make the presentation softer/i),
      'Make the background warmer',
    );
    await waitFor(() => expect(screen.getByDisplayValue('Make the background warmer')).toBeTruthy());
    await act(async () => { fireEvent.press(screen.getByText('Preview change')); });
    await waitFor(() => expect(previewMarkupRefine).toHaveBeenCalledWith(expect.objectContaining({
      sourceAssetId: 'asset_2',
      annotation: expect.objectContaining({
        impact: 'visual_only',
        change_instruction: 'Make the background warmer',
      }),
    })));
    expect(await screen.findByText('Nothing has changed yet.')).toBeTruthy();
  });

  test('reopens an exact-lineage pending preview for authenticated source comparison and Apply', async () => {
    const onApplied = jest.fn();
    const resumeRefine = jest.fn(async () => ({
      data: {
        kind: 'catalog' as const,
        understoodAs: 'A pending component preview was restored for review.',
        candidate: {
          id: 'candidate_resumed', jobId: 'run_resumed', sourceRevisionId: 'asset_2',
          assetUrl: 'https://test/resumed.png', verdict: 'pass' as const,
          status: 'pending_review' as const, checks: [], temporary: true,
          expiresAt: '2099-01-01T00:00:00Z', decision: null,
          decidedAt: null, canonicalRevisionId: null,
        },
      },
      error: null,
      status: 200,
    }));
    const applyCatalogRefine = jest.fn(async () => ({
      data: { candidate: {}, project }, error: null, status: 201,
    }));
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog: jest.fn(async () => ({ data: catalog, error: null, status: 200 })),
          readMarkup: jest.fn(),
        }}
        gateway={{
          resumeRefine, previewCatalogRefine: jest.fn(), applyCatalogRefine,
          discardCatalogRefine: jest.fn(), previewMarkupRefine: jest.fn(),
          applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
          previewVisualRefine: jest.fn(), applyVisualRefine: jest.fn(),
          discardVisualRefine: jest.fn(),
        } as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        sourceImageUrl="https://test/source.png"
        imageRequestHeaders={{ Authorization: 'Bearer test-session-token' }}
        onApplied={onApplied}
      />,
    );

    expect(await screen.findByText(/pending component preview was restored/i)).toBeTruthy();
    expect(screen.getByLabelText('Exact source revision').props.source.headers).toEqual({
      Authorization: 'Bearer test-session-token',
    });
    expect(screen.getByLabelText('Temporary refinement preview').props.source.headers).toEqual({
      Authorization: 'Bearer test-session-token',
    });
    await act(async () => { fireEvent.press(screen.getByText('Apply as new revision')); });
    expect(applyCatalogRefine).toHaveBeenCalledWith({
      candidateId: 'candidate_resumed', createdBy: 'designer',
    });
    expect(onApplied).toHaveBeenCalledWith(project);
  });

  test('asks for a name and saves one catalog preview variation without applying the source', async () => {
    const onApplied = jest.fn();
    const onVariationCreated = jest.fn();
    const variationProject = {
      ...project, id: 'variation_2', root_id: 'variation_2',
      active_asset_id: 'variation_2', cover_asset_id: 'variation_2',
    } as ProjectDetail;
    const resumeRefine = jest.fn(async () => ({
      data: {
        kind: 'catalog' as const,
        understoodAs: 'A pending component preview was restored for review.',
        candidate: {
          id: 'candidate_variation', jobId: 'run_variation', sourceRevisionId: 'asset_2',
          assetUrl: 'https://test/variation-preview.png', verdict: 'pass' as const,
          status: 'pending_review' as const, checks: [], temporary: true,
          expiresAt: '2099-01-01T00:00:00Z', decision: null,
          decidedAt: null, canonicalRevisionId: null,
        },
      }, error: null, status: 200,
    }));
    const saveCatalogPreviewAsVariation = jest.fn(() => new Promise(() => {}));
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog: jest.fn(async () => ({ data: catalog, error: null, status: 200 })),
          readMarkup: jest.fn(),
        }}
        gateway={{
          resumeRefine, saveCatalogPreviewAsVariation,
          previewCatalogRefine: jest.fn(), applyCatalogRefine: jest.fn(),
          discardCatalogRefine: jest.fn(), previewMarkupRefine: jest.fn(),
          applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
          previewVisualRefine: jest.fn(), applyVisualRefine: jest.fn(),
          discardVisualRefine: jest.fn(),
        } as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        sourceImageUrl="https://test/source.png"
        onApplied={onApplied}
        onVariationCreated={onVariationCreated}
      />,
    );

    expect(await screen.findByText('Save as Variation')).toBeTruthy();
    fireEvent.press(screen.getByText('Save as Variation'));
    expect(await screen.findByText(/source revision stays unchanged/i)).toBeTruthy();
    expect(saveCatalogPreviewAsVariation).not.toHaveBeenCalled();
    fireEvent.changeText(screen.getByPlaceholderText('e.g. Rose gold halo'), '  Rose halo  ');
    expect(await screen.findByDisplayValue('  Rose halo  ')).toBeTruthy();
    fireEvent.press(screen.getByText('Save named variation'));
    expect(saveCatalogPreviewAsVariation).toHaveBeenCalledTimes(1);
    expect(saveCatalogPreviewAsVariation).toHaveBeenCalledWith({
      candidateId: 'candidate_variation', createdBy: 'designer', label: 'Rose halo',
    });
    expect(onApplied).not.toHaveBeenCalled();
    expect(onVariationCreated).not.toHaveBeenCalled();
  });

  test('corrects a categorical fact and stone dimension with zero-credit immutable lineage', async () => {
    const revisedProject = {
      ...exactFactProject, active_asset_id: 'asset_3', active_design_version: 3,
    } as ProjectDetail;
    let resolveRevision: ((value: any) => void) | null = null;
    const reviseStudioFacts = jest.fn(() => new Promise<any>((resolve) => {
      resolveRevision = resolve;
    }));
    const onApplied = jest.fn();
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog: jest.fn(async () => ({ data: catalog, error: null, status: 200 })),
          readMarkup: jest.fn(), getProject: jest.fn(async () => ({
            data: exactFactProject, error: null, status: 200,
          })), reviseStudioFacts,
        }}
        gateway={{} as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        onApplied={onApplied}
      />,
    );

    const factsMode = await screen.findByText('Facts');
    fireEvent.press(factsMode);
    expect(await screen.findByDisplayValue('8')).toBeTruthy();
    expect(screen.getAllByText(/0 credits/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/image pixels stay unchanged/i)).toBeTruthy();
    expect(screen.queryByText(/provider/i)).toBeNull();
    expect(screen.queryByText(/factory/i)).toBeNull();
    fireEvent.press(screen.getByText('Save fact revision'));
    expect(await screen.findByText(/Nothing changed/i)).toBeTruthy();
    fireEvent.changeText(screen.getByDisplayValue('8'), '-1');
    await waitFor(() => expect(screen.getByDisplayValue('-1')).toBeTruthy());
    expect(screen.queryByText(/Nothing changed/i)).toBeNull();
    fireEvent.press(screen.getByText('Save fact revision'));
    expect(await screen.findByText(/Stone length must be a valid positive number/i)).toBeTruthy();
    expect(reviseStudioFacts).not.toHaveBeenCalled();
    fireEvent.changeText(screen.getByDisplayValue('-1'), '8');
    await waitFor(() => expect(screen.getByDisplayValue('8')).toBeTruthy());
    fireEvent.press(screen.getByText('Rose'));
    fireEvent.changeText(screen.getByDisplayValue('8'), '8.2');
    await waitFor(() => expect(screen.getByDisplayValue('8.2')).toBeTruthy());
    fireEvent.press(screen.getByText('Save fact revision'));
    await waitFor(() => expect(reviseStudioFacts).toHaveBeenCalledWith('project_1', {
      expected_active_asset_id: 'asset_2', expected_design_version: 2,
      created_by: 'designer', changes: [
        { path: 'metal.color', value: 'rose' },
        { path: 'stone.dimensions_mm.length', value: 8.2 },
      ],
    }));
    await act(async () => {
      resolveRevision?.({
        data: {
          status: 'applied', project_root_id: 'project_1', source_asset_id: 'asset_2',
          asset_id: 'asset_3', design_id: 'design_1', previous_design_version: 2,
          design_version: 3, spec_change: [], project_detail: revisedProject,
        }, error: null, status: 200,
      });
      await Promise.resolve();
    });
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(revisedProject));
    expect(onApplied).toHaveBeenCalledWith(revisedProject);
    expect(await screen.findByText('Save fact revision')).toBeTruthy();
  });
});
