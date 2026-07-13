import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { AuthenticatedImageProvider } from '../AuthenticatedImage';
import { StudioRefineWorkspace } from './StudioRefineWorkspace';
import type { ProjectDetail, StudioComponentTargeting } from '../trusted/types';

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

const readyTargeting: StudioComponentTargeting = {
  schema_version: 'facetta.studio-component-targeting.v1',
  asset_id: 'asset_2',
  asset_sha256: 'a'.repeat(64),
  jewelry_type: 'ring',
  component_map: {
    state: 'ready', scope: 'ring_v1', map_sha256: 'b'.repeat(64),
    mapper_contract: 'facetta.ring-component-map.v1', raster_width: 1024, raster_height: 1024,
  },
  catalog_paths: [
    { component_path: 'metal.color', status: 'ready', required_component_kinds: ['metal'], component_ids: ['shank'], reason_code: null },
    { component_path: 'metal.material', status: 'ready', required_component_kinds: ['metal'], component_ids: ['shank'], reason_code: null },
    { component_path: 'stone.color', status: 'ready', required_component_kinds: ['stone'], component_ids: ['center_stone'], reason_code: null },
    { component_path: 'stone.cut', status: 'unresolved', required_component_kinds: ['stone'], component_ids: [], reason_code: 'structural_child_mapping_unavailable' },
    { component_path: 'setting.style', status: 'unresolved', required_component_kinds: ['setting'], component_ids: [], reason_code: 'structural_child_mapping_unavailable' },
    { component_path: 'chain.style', status: 'unresolved', required_component_kinds: ['chain'], component_ids: [], reason_code: 'not_applicable' },
  ],
  authority: 'exact_revision_image_editing_only',
};

const getReadyTargeting = jest.fn(async () => ({ data: readyTargeting, error: null, status: 200 }));

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
          getStudioComponentTargeting: getReadyTargeting,
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
          }, {
            id: 'provider_trace', label: 'Grok QA model routing', verdict: 'warn' as const,
            detail: 'Internal evaluator trace must remain server-side.',
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
          getStudioComponentTargeting: getReadyTargeting,
          readMarkup: jest.fn(),
        }}
        gateway={{ previewCatalogRefine, applyCatalogRefine, discardCatalogRefine: jest.fn() } as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        sourceImageUrl="https://test/source.png"
        createdBy="designer"
        onReviewStartingDesign={jest.fn()}
        onApplied={onApplied}
      />,
    );

    expect(screen.queryByText('Review starting design')).toBeNull();
    expect(screen.getByText('1 requested output × 20 credits = estimated 20 credits')).toBeTruthy();
    await act(async () => { fireEvent.press(await screen.findByText('Preview change')); });
    expect(await screen.findByText('Nothing has changed yet.')).toBeTruthy();
    expect(screen.getByText('Visual consistency')).toBeTruthy();
    expect(screen.queryByText(/Grok|QA|model routing|evaluator trace/i)).toBeNull();
    expect(onApplied).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent(screen.getByLabelText('Exact source revision'), 'load');
      fireEvent(screen.getByLabelText('Temporary refinement preview'), 'error');
    });
    expect(screen.getByText(/source or preview could not be displayed/i)).toBeTruthy();
    expect(screen.getByText('Discard').parent?.props.accessibilityState.disabled).toBe(false);
    fireEvent.press(screen.getByText('Apply as new revision'));
    expect(applyCatalogRefine).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent(screen.getByLabelText('Temporary refinement preview'), 'load');
    });
    await act(async () => { fireEvent.press(screen.getByText('Apply as new revision')); });
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(project));
  });

  test('keeps a structural cut direction temporary and bound to the exact revision', async () => {
    const structuralTargeting: StudioComponentTargeting = {
      ...readyTargeting,
      catalog_paths: readyTargeting.catalog_paths.map((candidate) => (
        candidate.component_path === 'stone.cut'
          ? {
            ...candidate,
            status: 'ready' as const,
            required_component_kinds: ['center_stone', 'prongs', 'setting'],
            component_ids: ['center', 'prongs', 'setting'],
            reason_code: null,
          }
          : candidate
      )),
    };
    const cutCatalog = {
      component_path: 'stone.cut' as const,
      display: 'Stone cut',
      applicable_jewelry_types: ['ring'],
      image_agent_status: 'catalog_ready' as const,
      options: [{
        id: 'emerald_cut', display: 'Emerald cut', visual_geometry: [],
        isolation_target: 'Center stone, prongs, and setting',
        frozen_facts: ['shank', 'shoulders', 'gallery'],
        factory_fields: {}, derived_factory_fields: [], selection_requirements: [],
      }],
    };
    const getComponentCatalog = jest.fn(async (componentPath: string) => ({
      data: componentPath === 'stone.cut' ? cutCatalog : catalog,
      error: null,
      status: 200,
    }));
    const previewCatalogRefine = jest.fn(async () => ({
      data: {
        lineage: {
          projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2,
        },
        componentPath: 'stone.cut' as const,
        optionId: 'emerald_cut',
        candidate: {
          id: 'candidate_cut', jobId: 'run_cut', sourceRevisionId: 'asset_2',
          assetUrl: 'https://test/cut-preview.png', verdict: 'pass' as const,
          status: 'pending_review' as const, checks: [], temporary: true,
          expiresAt: null, decision: null, decidedAt: null, canonicalRevisionId: null,
        },
      },
      error: null,
      status: 201,
    }));
    const applyCatalogRefine = jest.fn(async () => ({
      data: { candidate: {}, project }, error: null, status: 201,
    }));
    const onApplied = jest.fn();

    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog,
          getStudioComponentTargeting: jest.fn(async () => ({
            data: structuralTargeting, error: null, status: 200,
          })),
          readMarkup: jest.fn(),
        }}
        gateway={{
          previewCatalogRefine, applyCatalogRefine, discardCatalogRefine: jest.fn(),
        } as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        sourceImageUrl="https://test/source.png"
        createdBy="designer"
        onApplied={onApplied}
      />,
    );

    await waitFor(() => expect(
      screen.getByLabelText('Stone cut component path').props.accessibilityState.disabled,
    ).toBe(false));
    await act(async () => {
      fireEvent.press(screen.getByLabelText('Stone cut component path'));
      await Promise.resolve();
    });
    await waitFor(() => expect(getComponentCatalog).toHaveBeenCalledWith('stone.cut'));
    await act(async () => {
      fireEvent.press(await screen.findByText('Emerald cut'));
      await Promise.resolve();
    });
    await act(async () => {
      fireEvent.press(screen.getByText('Preview change'));
      await Promise.resolve();
    });
    await waitFor(() => expect(previewCatalogRefine).toHaveBeenCalledWith({
      projectId: 'project_1',
      sourceAssetId: 'asset_2',
      sourceDesignVersion: 2,
      createdBy: 'designer',
      componentPath: 'stone.cut',
      optionId: 'emerald_cut',
    }));
    expect(await screen.findByText('Nothing has changed yet.')).toBeTruthy();
    expect(screen.getByLabelText('Temporary refinement preview')).toBeTruthy();
    await act(async () => {
      fireEvent.press(screen.getByText('Apply as new revision'));
      await Promise.resolve();
    });
    expect(applyCatalogRefine).not.toHaveBeenCalled();
    expect(onApplied).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent(screen.getByLabelText('Exact source revision'), 'load');
      fireEvent(screen.getByLabelText('Temporary refinement preview'), 'load');
      await Promise.resolve();
    });
    await act(async () => {
      fireEvent.press(screen.getByText('Apply as new revision'));
      await Promise.resolve();
    });
    await waitFor(() => expect(applyCatalogRefine).toHaveBeenCalledWith({
      candidateId: 'candidate_cut', createdBy: 'designer',
    }));
    expect(onApplied).toHaveBeenCalledWith(project);
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
    const onReviewStartingDesign = jest.fn();
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{ getComponentCatalog, getStudioComponentTargeting: getReadyTargeting, readMarkup: jest.fn() }}
        gateway={{
          previewVisualRefine, applyVisualRefine, discardVisualRefine: jest.fn(),
          previewCatalogRefine: jest.fn(), applyCatalogRefine: jest.fn(), discardCatalogRefine: jest.fn(),
          previewMarkupRefine: jest.fn(), applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
        }}
        lineage={{ projectId: 'project_1', sourceAssetId: 'creative_1' }}
        sourceImageUrl="https://test/source.png"
        createdBy="designer"
        onReviewStartingDesign={onReviewStartingDesign}
        onApplied={onApplied}
      />,
    );

    expect(getComponentCatalog).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Component refine mode').props.accessibilityState.disabled).toBe(true);
    expect(screen.getByText('Unlock precise ring edits')).toBeTruthy();
    expect(screen.getByText(/image-derived starting facts/i)).toBeTruthy();
    expect(screen.getByText(/Technical views become available after those facts are recorded/)).toBeTruthy();
    expect(screen.getByText(/you can keep refining or presenting without them/)).toBeTruthy();
    await act(async () => { fireEvent.press(screen.getByText('Review starting design')); });
    expect(onReviewStartingDesign).toHaveBeenCalledTimes(1);
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
    await act(async () => {
      fireEvent(screen.getByLabelText('Exact source revision'), 'load');
      fireEvent(screen.getByLabelText('Temporary refinement preview'), 'load');
    });
    await act(async () => { fireEvent.press(screen.getByText('Apply as new revision')); });
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(preSpecProject));
    expect(preSpecProject.active_design_version).toBeNull();
  });

  test('does not offer starting-design review without an eligible selected visual', async () => {
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog: jest.fn(),
          getStudioComponentTargeting: getReadyTargeting,
          readMarkup: jest.fn(),
        }}
        gateway={{
          previewVisualRefine: jest.fn(), applyVisualRefine: jest.fn(),
          discardVisualRefine: jest.fn(), previewCatalogRefine: jest.fn(),
          applyCatalogRefine: jest.fn(), discardCatalogRefine: jest.fn(),
          previewMarkupRefine: jest.fn(), applyMarkupRefine: jest.fn(),
          discardMarkupRefine: jest.fn(),
        }}
        lineage={{ projectId: 'project_1', sourceAssetId: 'source_not_confirmable' }}
        sourceImageUrl="https://test/source.png"
        createdBy="designer"
        onApplied={jest.fn()}
      />,
    );

    expect(screen.getByText('Unlock precise ring edits')).toBeTruthy();
    expect(screen.queryByText('Review starting design')).toBeNull();
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
          target_component_id: 'metal.upper-left',
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
        api={{ getComponentCatalog: jest.fn(), getStudioComponentTargeting: getReadyTargeting, readMarkup }}
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
          getStudioComponentTargeting: getReadyTargeting,
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
          getStudioComponentTargeting: getReadyTargeting,
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
    await act(async () => {
      fireEvent(screen.getByLabelText('Exact source revision'), 'load');
      fireEvent(screen.getByLabelText('Temporary refinement preview'), 'load');
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
          getStudioComponentTargeting: getReadyTargeting,
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
    await act(async () => {
      fireEvent(screen.getByLabelText('Exact source revision'), 'load');
      fireEvent(screen.getByLabelText('Temporary refinement preview'), 'load');
    });
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
          getStudioComponentTargeting: getReadyTargeting,
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

    expect(screen.queryByText('Facts')).toBeNull();
    expect(screen.queryByText('Stone species')).toBeNull();
    fireEvent.press(await screen.findByLabelText('Advanced design facts'));
    expect(await screen.findByText('Identity')).toBeTruthy();
    expect(screen.getByLabelText('Identity fact group').props.accessibilityState.expanded).toBe(true);
    expect(screen.getByLabelText('Stone fact group').props.accessibilityState.expanded).toBe(false);
    expect(screen.queryByText('Stone species')).toBeNull();
    expect(screen.getAllByText(/0 credits/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/image pixels stay unchanged/i)).toBeTruthy();
    expect(screen.queryByText(/provider/i)).toBeNull();
    expect(screen.queryByText(/factory/i)).toBeNull();
    fireEvent.press(screen.getByText('Review fact changes'));
    expect(await screen.findByText(/Nothing changed/i)).toBeTruthy();
    fireEvent.press(screen.getByLabelText('Dimensions fact group'));
    await waitFor(() => {
      expect(screen.getByLabelText('Identity fact group').props.accessibilityState.expanded).toBe(false);
      expect(screen.getByLabelText('Dimensions fact group').props.accessibilityState.expanded).toBe(true);
    });
    expect(await screen.findByDisplayValue('8')).toBeTruthy();
    fireEvent.changeText(screen.getByDisplayValue('8'), '-1');
    await waitFor(() => expect(screen.getByDisplayValue('-1')).toBeTruthy());
    expect(screen.queryByText(/Nothing changed/i)).toBeNull();
    fireEvent.press(screen.getByText('Review fact changes'));
    expect(await screen.findByText(/Stone length must be a valid positive number/i)).toBeTruthy();
    expect(reviseStudioFacts).not.toHaveBeenCalled();
    fireEvent.changeText(screen.getByDisplayValue('-1'), '8');
    await waitFor(() => expect(screen.getByDisplayValue('8')).toBeTruthy());
    fireEvent.press(screen.getByLabelText('Identity fact group'));
    const roseOption = await screen.findByText('Rose');
    await act(async () => { fireEvent.press(roseOption); await Promise.resolve(); });
    fireEvent.press(screen.getByLabelText('Dimensions fact group'));
    const stoneLength = await screen.findByDisplayValue('8');
    fireEvent.changeText(stoneLength, '8.2');
    await waitFor(() => expect(screen.getByDisplayValue('8.2')).toBeTruthy());
    fireEvent.press(screen.getByText('Review fact changes'));
    expect(await screen.findByText('Review only what changed')).toBeTruthy();
    expect(screen.getByText('Yellow → Rose')).toBeTruthy();
    expect(screen.getByText('8 → 8.2 mm')).toBeTruthy();
    expect(reviseStudioFacts).not.toHaveBeenCalled();
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

  test('fails closed when the exact revision has no mapped component regions', async () => {
    const getComponentCatalog = jest.fn();
    const previewCatalogRefine = jest.fn();
    const unmapped: StudioComponentTargeting = {
      ...readyTargeting,
      component_map: { ...readyTargeting.component_map, state: 'unmapped', map_sha256: null },
      catalog_paths: readyTargeting.catalog_paths.map((candidate) => ({
        ...candidate, status: 'unmapped' as const, component_ids: [], reason_code: 'component_map_not_found',
      })),
    };
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog,
          getStudioComponentTargeting: jest.fn(async () => ({ data: unmapped, error: null, status: 200 })),
          readMarkup: jest.fn(),
        }}
        gateway={{ previewCatalogRefine } as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        onApplied={jest.fn()}
      />,
    );

    await waitFor(() => expect(
      screen.getByLabelText('Component refine mode').props.accessibilityState.disabled,
    ).toBe(true));
    expect(screen.getByText(/will not guess component geometry/i)).toBeTruthy();
    expect(screen.getByText('Appearance change')).toBeTruthy();
    expect(getComponentCatalog).not.toHaveBeenCalled();
    expect(previewCatalogRefine).not.toHaveBeenCalled();
  });

  test('prepares an unmapped ring revision once and reveals safe component paths', async () => {
    const getStudioComponentTargeting = jest.fn(async () => ({
      data: {
        ...readyTargeting,
        component_map: { ...readyTargeting.component_map, state: 'unmapped' as const, map_sha256: null },
        catalog_paths: readyTargeting.catalog_paths.map((candidate) => ({
          ...candidate,
          status: 'unmapped' as const,
          component_ids: [],
          reason_code: 'component_map_not_found',
        })),
      },
      error: null,
      status: 200,
    }));
    const prepareStudioComponentMap = jest.fn(async () => ({
      data: readyTargeting, error: null, status: 200,
    }));
    const getComponentCatalog = jest.fn(async () => ({ data: catalog, error: null, status: 200 }));

    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog,
          getStudioComponentTargeting,
          prepareStudioComponentMap,
          readMarkup: jest.fn(),
        }}
        gateway={{} as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        onApplied={jest.fn()}
      />,
    );

    await waitFor(() => expect(prepareStudioComponentMap).toHaveBeenCalledWith('asset_2'));
    await waitFor(() => expect(
      screen.getByLabelText('Component refine mode').props.accessibilityState.disabled,
    ).toBe(false));
    expect(getComponentCatalog).toHaveBeenCalledWith('metal.color');
  });

  test('offers mapped material paths while disabling unresolved structural paths', async () => {
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog: jest.fn(async () => ({ data: catalog, error: null, status: 200 })),
          getStudioComponentTargeting: getReadyTargeting,
          readMarkup: jest.fn(),
        }}
        gateway={{} as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        onApplied={jest.fn()}
      />,
    );

    await waitFor(() => expect(
      screen.getByLabelText('Metal color component path').props.accessibilityState.disabled,
    ).toBe(false));
    expect(screen.getByLabelText('Stone cut component path').props.accessibilityState.disabled).toBe(true);
    expect(screen.getByLabelText('Setting component path').props.accessibilityState.disabled).toBe(true);
    expect(screen.getAllByText(/not ready for that precise component change yet/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/calibrated|structural mapping|component identity/i)).toBeNull();
  });
});
