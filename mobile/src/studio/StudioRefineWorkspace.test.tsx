import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { AuthenticatedImageProvider } from '../AuthenticatedImage';
import { StudioRefineWorkspace } from './StudioRefineWorkspace';
import type { ComponentCatalog, ProjectDetail, StudioComponentTargeting } from '../trusted/types';

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
      species: 'sapphire', cut: 'oval_brilliant', carat: 1.2,
      dimensions_mm: { length: 8, width: 6, depth: 3.8 },
      color: { trade: 'royal_blue', gia: 'blue' },
    },
    setting: { style: '4_prong_basket', prong_count: 4, prong_tip_mm: 0.9 },
    band: { profile: 'half_round', width_mm: 2.1, thickness_mm: 1.8 },
    ring_size: { system: 'US', value: 6.5, inner_diameter_mm: 16.9 },
  },
} as ProjectDetail;

const catalog: ComponentCatalog = {
  component_path: 'metal.color' as const,
  display: 'Metal color', applicable_jewelry_types: ['ring'],
  image_agent_status: 'catalog_ready' as const,
  preview_execution_modes: ['instant', 'provider'],
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

function withAuth(ui: React.ReactElement) {
  return (
    <AuthenticatedImageProvider
      allowedOrigin="https://test"
      headers={{ Authorization: 'Bearer test-session-token' }}>
      {ui}
    </AuthenticatedImageProvider>
  );
}

function renderWithAuth(ui: React.ReactElement) {
  return render(withAuth(ui));
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
    const onSelectDestination = jest.fn();
    const appliedProject = {
      ...project,
      active_asset_id: 'asset_3',
      active_design_version: 3,
      active_revision: {
        asset_id: 'asset_3', root_id: 'project_1', parent_asset_id: 'asset_2',
        capability: 'LOCALIZED_EDIT', provenance: 'catalog_candidate_accept',
        revision: 3, design_version: 3, region: null, instruction: 'Use rose gold',
        drift: null, pinned: false, media_type: 'image/png',
        image_url: 'https://test/applied.png', created_by: 'designer',
        created_at: null, legacy_provenance: false,
      },
    } as ProjectDetail;
    const previewCatalogRefine = jest.fn(async () => ({
      data: {
        lineage: { projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 },
        componentPath: 'metal.color' as const, optionId: 'rose_gold',
        executionMode: 'instant' as const, estimatedCredits: 0,
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
      data: { candidate: {}, project: appliedProject }, error: null, status: 201,
    }));
    const api = {
      getComponentCatalog: jest.fn(async () => ({ data: catalog, error: null, status: 200 })),
      getStudioComponentTargeting: getReadyTargeting,
      readMarkup: jest.fn(),
    };
    const gateway = {
      previewCatalogRefine, applyCatalogRefine, discardCatalogRefine: jest.fn(),
    } as any;
    function ApplyHarness() {
      const [activeLineage, setActiveLineage] = React.useState({
        projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2,
      });
      return (
        <StudioRefineWorkspace
          api={api}
          gateway={gateway}
          lineage={activeLineage}
          sourceImageUrl="https://test/source.png"
          createdBy="designer"
          onReviewStartingDesign={jest.fn()}
          onApplied={(savedProject) => {
            onApplied(savedProject);
            setActiveLineage({
              projectId: savedProject.root_id,
              sourceAssetId: savedProject.active_asset_id ?? '',
              sourceDesignVersion: savedProject.active_design_version ?? 0,
            });
          }}
          destinationContext={{
            activeProjectId: activeLineage.projectId,
            activeRevisionId: activeLineage.sourceAssetId,
            hasExactSpecification: true,
            factoryEligible: false,
          }}
          onSelectDestination={onSelectDestination}
        />
      );
    }
    await renderWithAuth(<ApplyHarness />);

    expect(screen.queryByText('Review starting design')).toBeNull();
    expect(screen.getByText('1 requested output × 20 credits = estimated 20 credits')).toBeTruthy();
    await waitFor(() => expect(screen.getByLabelText('Component refine mode')).toBeTruthy());
    await fireEvent.press(screen.getByLabelText('Component refine mode'));
    await waitFor(() => expect(screen.getByText('Rose gold')).toBeTruthy());
    expect(screen.getByText('Quick preview · 0 credits')).toBeTruthy();
    await fireEvent.press(await screen.findByText('Preview change'));
    expect(previewCatalogRefine).toHaveBeenCalledWith(expect.objectContaining({
      executionMode: 'instant',
    }));
    expect(await screen.findByText('Nothing has changed yet.')).toBeTruthy();
    expect(screen.getByText('Quick preview · 0 credits')).toBeTruthy();
    expect(screen.getByText('Visual consistency')).toBeTruthy();
    expect(screen.queryByText(/Grok|QA|model routing|evaluator trace/i)).toBeNull();
    expect(onApplied).not.toHaveBeenCalled();
    expect(screen.getByTestId('refine-comparison-inspector')).toBeTruthy();
    expect(screen.getByLabelText('Inspect comparison in detail')).toBeTruthy();
    expect(screen.getByText('Apply as new revision').parent?.props.accessibilityState.disabled).toBe(true);
    await fireEvent.press(screen.getByLabelText('Inspect comparison in detail'));
    expect(await screen.findByText('Inspect source and temporary preview')).toBeTruthy();
    await fireEvent(
      screen.getByLabelText('Preview: Temporary refinement candidate detail view'),
      'load',
    );
    expect(screen.getByText('Apply as new revision').parent?.props.accessibilityState.disabled).toBe(true);
    await fireEvent.press(screen.getByLabelText('Show Source: Exact selected revision in detail'));
    await fireEvent(
      await screen.findByLabelText('Source: Exact selected revision detail view'),
      'load',
    );
    expect(screen.getByText('Apply as new revision').parent?.props.accessibilityState.disabled).toBe(true);
    await fireEvent.press(screen.getByLabelText('Close comparison inspector'));
    await waitFor(() => {
      expect(screen.queryByText('Inspect source and temporary preview')).toBeNull();
    });
    await fireEvent(screen.getByLabelText('Exact source revision'), 'load');
    await fireEvent(screen.getByLabelText('Temporary refinement preview'), 'load');
    await waitFor(() => {
      expect(
        screen.getByText('Apply as new revision').parent?.props.accessibilityState.disabled,
      ).toBe(false);
    });
    expect(applyCatalogRefine).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByText('Apply as new revision'));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(appliedProject));
    expect(await screen.findByText('Saved as Revision 3.')).toBeTruthy();
    expect(screen.getByText('Refine another change')).toBeTruthy();
    expect(screen.queryByText('Factory')).toBeNull();
    await fireEvent.press(screen.getByText('Library'));
    await fireEvent.press(screen.getByText('Client'));
    expect(onSelectDestination).toHaveBeenNthCalledWith(1, 'library');
    expect(onSelectDestination).toHaveBeenNthCalledWith(2, 'client');
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
    const cutCatalog: ComponentCatalog = {
      component_path: 'stone.cut' as const,
      display: 'Stone cut',
      applicable_jewelry_types: ['ring'],
      image_agent_status: 'catalog_ready' as const,
      preview_execution_modes: ['provider'],
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
        executionMode: 'provider' as const,
        estimatedCredits: 20,
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

    await waitFor(() => expect(screen.getByLabelText('Component refine mode')).toBeTruthy());
    await fireEvent.press(screen.getByLabelText('Component refine mode'));
    await waitFor(() => expect(
      screen.getByLabelText('Stone cut component path').props.accessibilityState.disabled,
    ).toBe(false));
    await fireEvent.press(screen.getByLabelText('Stone cut component path'));
    await waitFor(() => expect(getComponentCatalog).toHaveBeenCalledWith('stone.cut'));
    expect(screen.getByText('1 requested output × 20 credits = estimated 20 credits')).toBeTruthy();
    await fireEvent.press(await screen.findByText('Emerald cut'));
    await fireEvent.press(screen.getByText('Preview change'));
    await waitFor(() => expect(previewCatalogRefine).toHaveBeenCalledWith({
      projectId: 'project_1',
      sourceAssetId: 'asset_2',
      sourceDesignVersion: 2,
      createdBy: 'designer',
      componentPath: 'stone.cut',
      optionId: 'emerald_cut',
      executionMode: 'provider',
    }));
    expect(await screen.findByText('Nothing has changed yet.')).toBeTruthy();
    expect(screen.getByText('REQUESTED CHANGE')).toBeTruthy();
    expect(screen.getByText('Stone cut → Emerald cut')).toBeTruthy();
    expect(screen.getByText(/Only stone cut may change.*every other component/)).toBeTruthy();
    expect(screen.getByText(/Standard preview · estimated 20 credits/)).toBeTruthy();
    expect(screen.queryByText(/provider/i)).toBeNull();
    expect(screen.getByLabelText('Temporary refinement preview')).toBeTruthy();
    await fireEvent.press(screen.getByText('Apply as new revision'));
    expect(applyCatalogRefine).not.toHaveBeenCalled();
    expect(onApplied).not.toHaveBeenCalled();

    await fireEvent(screen.getByLabelText('Exact source revision'), 'load');
    await fireEvent(screen.getByLabelText('Temporary refinement preview'), 'load');
    await fireEvent.press(screen.getByText('Apply as new revision'));
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
    expect(screen.queryByLabelText('Component refine mode')).toBeNull();
    expect(screen.getByLabelText('What would you like to change?')).toBeTruthy();
    expect(screen.getByText('Unlock precise ring edits')).toBeTruthy();
    expect(screen.getByText(/image-derived starting facts/i)).toBeTruthy();
    expect(screen.getByText(/Technical views become available after those facts are recorded/)).toBeTruthy();
    expect(screen.getByText(/you can keep refining or presenting without them/)).toBeTruthy();
    await fireEvent.press(screen.getByText('Review starting design'));
    expect(onReviewStartingDesign).toHaveBeenCalledTimes(1);
    await fireEvent.changeText(
      screen.getByPlaceholderText(/make the presentation softer/i),
      'Make the lighting warmer',
    );
    await waitFor(() => expect(screen.getByDisplayValue('Make the lighting warmer')).toBeTruthy());
    await fireEvent.press(screen.getByText('Preview change'));
    await waitFor(() => expect(previewVisualRefine).toHaveBeenCalledWith({
      projectId: 'project_1', sourceAssetId: 'creative_1', createdBy: 'designer',
      instruction: 'Make the lighting warmer', scope: 'appearance',
    }));
    expect(screen.getByText('REQUESTED CHANGE')).toBeTruthy();
    expect(screen.getByText('Make the lighting warmer')).toBeTruthy();
    expect(screen.getByText('Appearance-only change')).toBeTruthy();
    expect(screen.getByLabelText('Exact source revision')).toBeTruthy();
    expect(screen.getByLabelText('Temporary refinement preview')).toBeTruthy();
    await fireEvent(screen.getByLabelText('Exact source revision'), 'load');
    await fireEvent(screen.getByLabelText('Temporary refinement preview'), 'load');
    await fireEvent.press(screen.getByText('Apply as new revision'));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(preSpecProject));
    await waitFor(() => expect(
      screen.getByPlaceholderText(/make the presentation softer/i).props.value,
    ).toBe(''));
    expect(screen.getByText('Preview change').parent?.props.accessibilityState.disabled).toBe(true);
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

    expect(screen.queryByText('Unlock precise ring edits')).toBeNull();
    expect(screen.queryByLabelText('Component refine mode')).toBeNull();
    expect(screen.queryByText('Review starting design')).toBeNull();
  });

  test('routes an exact rose-gold sentence to one authorized component preview', async () => {
    const previewCatalogRefine = jest.fn(async () => ({
      data: {
        lineage: { projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 },
        componentPath: 'metal.color' as const, optionId: 'rose_gold',
        executionMode: 'instant' as const, estimatedCredits: 0,
        candidate: {
          id: 'candidate_routed', jobId: 'run_routed', sourceRevisionId: 'asset_2',
          assetUrl: 'https://test/routed.png', verdict: 'pass' as const,
          status: 'pending_review' as const, checks: [], temporary: true,
          expiresAt: null, decision: null, decidedAt: null, canonicalRevisionId: null,
        },
      }, error: null, status: 201,
    }));
    const getComponentCatalog = jest.fn(async () => ({ data: catalog, error: null, status: 200 }));
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{ getComponentCatalog, getStudioComponentTargeting: getReadyTargeting, readMarkup: jest.fn() }}
        gateway={{
          previewCatalogRefine, applyCatalogRefine: jest.fn(), discardCatalogRefine: jest.fn(),
          previewMarkupRefine: jest.fn(), applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
          previewVisualRefine: jest.fn(), applyVisualRefine: jest.fn(), discardVisualRefine: jest.fn(),
        }}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        sourceImageUrl="https://test/source.png"
        createdBy="designer"
        onApplied={jest.fn()}
      />,
    );
    await waitFor(() => expect(screen.getByLabelText('Component refine mode')).toBeTruthy());
    await fireEvent.changeText(
      screen.getByLabelText('What would you like to change?'),
      'Use rose gold',
    );
    await fireEvent.press(screen.getByText('Preview change'));
    await waitFor(() => expect(getComponentCatalog).toHaveBeenCalledWith('metal.color'));
    await waitFor(() => expect(previewCatalogRefine).toHaveBeenCalledWith({
      projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2,
      createdBy: 'designer', componentPath: 'metal.color', optionId: 'rose_gold',
      executionMode: 'instant',
    }));
    expect(screen.getByText('Nothing has changed yet.')).toBeTruthy();
  });

  test('routes a localized structural sentence to markup without generating or charging', async () => {
    const getComponentCatalog = jest.fn(async () => ({ data: catalog, error: null, status: 200 }));
    const readMarkup = jest.fn();
    const previewCatalogRefine = jest.fn();
    const previewMarkupRefine = jest.fn();
    const previewVisualRefine = jest.fn();
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{ getComponentCatalog, getStudioComponentTargeting: getReadyTargeting, readMarkup }}
        gateway={{
          previewCatalogRefine, applyCatalogRefine: jest.fn(), discardCatalogRefine: jest.fn(),
          previewMarkupRefine, applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
          previewVisualRefine, applyVisualRefine: jest.fn(), discardVisualRefine: jest.fn(),
        }}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        sourceImageUrl="https://test/source.png"
        createdBy="designer"
        onApplied={jest.fn()}
      />,
    );
    await waitFor(() => expect(screen.getByLabelText('Component refine mode')).toBeTruthy());
    await fireEvent.changeText(
      screen.getByLabelText('What would you like to change?'),
      'Make the left prong rose gold',
    );
    await fireEvent.press(screen.getByText('Preview change'));

    expect(await screen.findByText(/tap the exact region you mean/i)).toBeTruthy();
    expect(screen.getByLabelText('Annotation text').props.value).toBe(
      'Make the left prong rose gold',
    );
    expect(readMarkup).not.toHaveBeenCalled();
    expect(previewCatalogRefine).not.toHaveBeenCalled();
    expect(previewMarkupRefine).not.toHaveBeenCalled();
    expect(previewVisualRefine).not.toHaveBeenCalled();
  });

  test('keeps a pre-spec material sentence and requests facts without generating', async () => {
    const previewVisualRefine = jest.fn();
    const getComponentCatalog = jest.fn();
    const onReviewStartingDesign = jest.fn();
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{ getComponentCatalog, getStudioComponentTargeting: getReadyTargeting, readMarkup: jest.fn() }}
        gateway={{
          previewVisualRefine, applyVisualRefine: jest.fn(), discardVisualRefine: jest.fn(),
          previewCatalogRefine: jest.fn(), applyCatalogRefine: jest.fn(), discardCatalogRefine: jest.fn(),
          previewMarkupRefine: jest.fn(), applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
        }}
        lineage={{ projectId: 'project_1', sourceAssetId: 'creative_1' }}
        sourceImageUrl="https://test/source.png"
        createdBy="designer"
        onReviewStartingDesign={onReviewStartingDesign}
        onApplied={jest.fn()}
      />,
    );
    await fireEvent.changeText(
      screen.getByLabelText('What would you like to change?'),
      'Use rose gold',
    );
    await fireEvent.press(screen.getByText('Preview change'));
    expect(await screen.findByText(/review the starting design facts first/i)).toBeTruthy();
    expect(getComponentCatalog).not.toHaveBeenCalled();
    expect(previewVisualRefine).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByText('Review starting design'));
    expect(onReviewStartingDesign).toHaveBeenCalledWith('Use rose gold');
  });

  test('clears a consumed instruction after saving its preview as a variation', async () => {
    const variationProject = {
      ...preSpecProject,
      id: 'variation_visual', root_id: 'variation_visual', active_asset_id: 'variation_visual',
      cover_asset_id: 'variation_visual',
    } as ProjectDetail;
    const candidate = {
      id: 'candidate_visual_variation', jobId: 'run_visual_variation',
      sourceRevisionId: 'creative_1', assetUrl: 'https://test/variation-preview.png',
      verdict: 'pass' as const, status: 'pending_review' as const, checks: [], temporary: true,
      expiresAt: null, decision: null, decidedAt: null, canonicalRevisionId: null,
    };
    const previewVisualRefine = jest.fn(async () => ({
      data: {
        lineage: { projectId: 'project_1', sourceAssetId: 'creative_1' },
        instruction: 'Make the lighting warmer', scope: 'appearance' as const, candidate,
      }, error: null, status: 201,
    }));
    const saveVisualPreviewAsVariation = jest.fn(async () => ({
      data: {
        candidate: { ...candidate, status: 'saved_as_variation' as const },
        project: variationProject,
      }, error: null, status: 201,
    }));
    const onVariationCreated = jest.fn();
    const workspace = (activeLineage: { projectId: string; sourceAssetId: string }) => withAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog: jest.fn(), getStudioComponentTargeting: getReadyTargeting,
          readMarkup: jest.fn(),
        }}
        gateway={{
          previewVisualRefine, saveVisualPreviewAsVariation,
          applyVisualRefine: jest.fn(), discardVisualRefine: jest.fn(),
          previewCatalogRefine: jest.fn(), applyCatalogRefine: jest.fn(),
          discardCatalogRefine: jest.fn(), previewMarkupRefine: jest.fn(),
          applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
        } as any}
        lineage={activeLineage}
        sourceImageUrl="https://test/source.png"
        createdBy="designer"
        onApplied={jest.fn()}
        onVariationCreated={onVariationCreated}
      />,
    );
    const rendered = await render(
      workspace({ projectId: 'project_1', sourceAssetId: 'creative_1' }),
    );

    await fireEvent.changeText(
      screen.getByPlaceholderText(/make the presentation softer/i),
      'Make the lighting warmer',
    );
    await waitFor(() => expect(screen.getByDisplayValue('Make the lighting warmer')).toBeTruthy());
    await fireEvent.press(screen.getByText('Preview change'));
    expect(await screen.findByText('Nothing has changed yet.')).toBeTruthy();
    await fireEvent(screen.getByLabelText('Exact source revision'), 'load');
    await fireEvent(screen.getByLabelText('Temporary refinement preview'), 'load');
    await fireEvent.press(screen.getByText('Save as Variation'));
    await fireEvent.changeText(
      screen.getByPlaceholderText('e.g. Rose gold halo'),
      'Warm direction',
    );
    await waitFor(() => expect(screen.getByDisplayValue('Warm direction')).toBeTruthy());
    await fireEvent.press(screen.getByText('Save named variation'));

    await waitFor(() => expect(saveVisualPreviewAsVariation).toHaveBeenCalledWith({
      candidateId: 'candidate_visual_variation', createdBy: 'designer', label: 'Warm direction',
    }));
    await waitFor(() => expect(onVariationCreated).toHaveBeenCalledWith(variationProject));
    expect(screen.getByText('Variation “Warm direction” is ready.')).toBeTruthy();
    await rendered.rerender(workspace({
      projectId: 'variation_visual', sourceAssetId: 'variation_visual',
    }));
    expect(await screen.findByText('Variation “Warm direction” is ready.')).toBeTruthy();
    expect(screen.getByPlaceholderText(/make the presentation softer/i).props.value).toBe('');
    expect(screen.getByText('Preview change').parent?.props.accessibilityState.disabled).toBe(true);
    await rendered.rerender(
      workspace({ projectId: 'another_project', sourceAssetId: 'another_asset' }),
    );
    await waitFor(() => {
      expect(screen.queryByText('Variation “Warm direction” is ready.')).toBeNull();
    });
  });

  test('routes pre-spec annotation through exact saved markup provenance', async () => {
    const annotationCandidate = {
      id: 'candidate_markup', jobId: 'run_markup', sourceRevisionId: 'creative_1',
      assetUrl: 'https://test/markup-preview.png', verdict: 'pass' as const,
      status: 'pending_review' as const, checks: [], temporary: true,
      expiresAt: null, decision: null, decidedAt: null, canonicalRevisionId: null,
    };
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
        candidate: annotationCandidate,
      }, error: null, status: 201,
    }));
    const discardVisualRefine = jest.fn(async () => ({
      data: {
        candidate: { ...annotationCandidate, status: 'discarded' as const }, project: null,
      }, error: null, status: 200,
    }));
    const applyVisualRefine = jest.fn(async () => ({
      data: {
        candidate: { ...annotationCandidate, status: 'applied' as const }, project: preSpecProject,
      }, error: null, status: 201,
    }));
    const onApplied = jest.fn();
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{ getComponentCatalog: jest.fn(), getStudioComponentTargeting: getReadyTargeting, readMarkup }}
        gateway={{
          previewVisualRefine, applyVisualRefine, discardVisualRefine,
          previewCatalogRefine: jest.fn(), applyCatalogRefine: jest.fn(), discardCatalogRefine: jest.fn(),
          previewMarkupRefine: jest.fn(), applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
        }}
        lineage={{ projectId: 'project_1', sourceAssetId: 'creative_1' }}
        sourceImageUrl="https://test/source.png"
        createdBy="designer"
        onApplied={onApplied}
      />,
    );

    await fireEvent.press(screen.getByLabelText('Mark up refine mode'));
    const canvas = await screen.findByLabelText('Jewelry image annotation canvas');
    await fireEvent(canvas, 'layout', {
      nativeEvent: { layout: { x: 0, y: 0, width: 200, height: 160 } },
    });
    await fireEvent(canvas, 'responderGrant', responderEvent(20, 20));
    await fireEvent(canvas, 'responderRelease', responderEvent(90, 80));
    await fireEvent.press(screen.getByText('Preview change'));

    await waitFor(() => expect(readMarkup).toHaveBeenCalledWith(
      'creative_1',
      expect.objectContaining({ created_by: 'designer' }),
    ));
    await waitFor(() => expect(previewVisualRefine).toHaveBeenCalledWith({
      projectId: 'project_1', sourceAssetId: 'creative_1', createdBy: 'designer',
      instruction: 'Warm only this surface', scope: 'marked_region', markupAssetId: 'markup_exact',
    }));
    expect(screen.getByText(/Warm only the highlighted surface/)).toBeTruthy();
    expect(screen.getByText('Warm only this surface')).toBeTruthy();
    expect(screen.getByText(/Region: highlighted upper-left metal/)).toBeTruthy();
    expect(screen.getByText(/Only the marked region and requested detail may change/)).toBeTruthy();
    expect(screen.getByLabelText('Temporary refinement preview')).toBeTruthy();

    await fireEvent.press(screen.getByText('Discard'));
    await waitFor(() => expect(discardVisualRefine).toHaveBeenCalledWith({
      candidateId: 'candidate_markup', createdBy: 'designer',
    }));
    expect(await screen.findByLabelText('Jewelry image annotation canvas')).toBeTruthy();
    expect(screen.getByLabelText('Clear all annotations').props.accessibilityState.disabled).toBe(false);
    expect(screen.getByText('Preview change').parent?.props.accessibilityState.disabled).toBe(false);

    await fireEvent.press(screen.getByText('Preview change'));
    expect(await screen.findByText('Nothing has changed yet.')).toBeTruthy();
    await fireEvent(screen.getByLabelText('Exact source revision'), 'load');
    await fireEvent(screen.getByLabelText('Temporary refinement preview'), 'load');
    await fireEvent.press(screen.getByText('Apply as new revision'));
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(preSpecProject));
    expect(screen.getByLabelText('What would you like to change?').props.value).toBe('');
    await fireEvent.press(screen.getByLabelText('Mark up refine mode'));
    expect(screen.getByLabelText('Clear all annotations').props.accessibilityState.disabled).toBe(true);
    expect(screen.getByText('Preview change').parent?.props.accessibilityState.disabled).toBe(true);
  });

  test('clears markup instead of rebinding it when the exact source revision changes', async () => {
    const api = {
      getComponentCatalog: jest.fn(),
      getStudioComponentTargeting: getReadyTargeting,
      readMarkup: jest.fn(),
    };
    const gateway = {
      previewVisualRefine: jest.fn(), applyVisualRefine: jest.fn(),
      discardVisualRefine: jest.fn(), previewCatalogRefine: jest.fn(),
      applyCatalogRefine: jest.fn(), discardCatalogRefine: jest.fn(),
      previewMarkupRefine: jest.fn(), applyMarkupRefine: jest.fn(),
      discardMarkupRefine: jest.fn(),
    };
    const workspace = (sourceAssetId: string, sourceImageUrl: string) => (
      <AuthenticatedImageProvider
        allowedOrigin="https://test"
        headers={{ Authorization: 'Bearer test-session-token' }}>
        <StudioRefineWorkspace
          api={api}
          gateway={gateway}
          lineage={{ projectId: 'project_1', sourceAssetId }}
          sourceImageUrl={sourceImageUrl}
          createdBy="designer"
          onApplied={jest.fn()}
        />
      </AuthenticatedImageProvider>
    );
    const rendered = await render(workspace('creative_1', 'https://test/source-1.png'));

    await fireEvent.press(screen.getByLabelText('Mark up refine mode'));
    const canvas = await screen.findByLabelText('Jewelry image annotation canvas');
    await fireEvent(canvas, 'layout', {
      nativeEvent: { layout: { x: 0, y: 0, width: 200, height: 160 } },
    });
    await fireEvent(canvas, 'responderGrant', responderEvent(20, 20));
    await fireEvent(canvas, 'responderRelease', responderEvent(90, 80));
    expect(screen.getByLabelText('Clear all annotations').props.accessibilityState).toEqual({
      disabled: false,
    });
    expect(screen.getByText('Preview change').parent?.props.accessibilityState.disabled).toBe(false);

    await rendered.rerender(workspace('creative_1', 'https://test/source-1-refreshed.png'));
    expect(screen.getByLabelText('Clear all annotations').props.accessibilityState).toEqual({
      disabled: false,
    });

    await rendered.rerender(workspace('creative_2', 'https://test/source-2.png'));
    expect(screen.getByLabelText('Clear all annotations').props.accessibilityState).toEqual({
      disabled: true,
    });
    expect(screen.getByText('Preview change').parent?.props.accessibilityState.disabled).toBe(true);
    expect(screen.queryByLabelText('rectangle annotation annotation-1')).toBeNull();
  });

  test('does not rebind a draft or accept an A-to-B-to-A late preview', async () => {
    let resolvePreview: ((value: any) => void) | null = null;
    const previewVisualRefine = jest.fn(() => new Promise<any>((resolve) => {
      resolvePreview = resolve;
    }));
    const api = {
      getComponentCatalog: jest.fn(),
      getStudioComponentTargeting: getReadyTargeting,
      readMarkup: jest.fn(),
    };
    const gateway = {
      previewVisualRefine, applyVisualRefine: jest.fn(), discardVisualRefine: jest.fn(),
      previewCatalogRefine: jest.fn(), applyCatalogRefine: jest.fn(),
      discardCatalogRefine: jest.fn(), previewMarkupRefine: jest.fn(),
      applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
    };
    const workspace = (sourceAssetId: string, sourceImageUrl: string) => (
      <AuthenticatedImageProvider
        allowedOrigin="https://test"
        headers={{ Authorization: 'Bearer test-session-token' }}>
        <StudioRefineWorkspace
          api={api}
          gateway={gateway}
          lineage={{ projectId: 'project_1', sourceAssetId }}
          sourceImageUrl={sourceImageUrl}
          createdBy="designer"
          onApplied={jest.fn()}
        />
      </AuthenticatedImageProvider>
    );
    const rendered = await render(workspace('creative_1', 'https://test/source-1.png'));

    await fireEvent.changeText(
      rendered.getByPlaceholderText(/make the presentation softer/i),
      'Warm only the shoulders',
    );
    await waitFor(() => expect(
      rendered.getByPlaceholderText(/make the presentation softer/i).props.value,
    ).toBe('Warm only the shoulders'));
    await fireEvent.press(rendered.getByText('Preview change'));
    await waitFor(() => expect(previewVisualRefine).toHaveBeenCalledWith(expect.objectContaining({
      sourceAssetId: 'creative_1', instruction: 'Warm only the shoulders',
    })));

    await rendered.rerender(workspace('creative_2', 'https://test/source-2.png'));
    await waitFor(() => expect(
      rendered.getByPlaceholderText(/make the presentation softer/i).props.value,
    ).toBe(''));
    expect(rendered.getByText('Preview change').parent?.props.accessibilityState.disabled).toBe(true);

    // Returning to the same lineage key must not revive work started in its earlier epoch.
    await rendered.rerender(workspace('creative_1', 'https://test/source-1.png'));
    expect(rendered.getByPlaceholderText(/make the presentation softer/i).props.value).toBe('');

    await act(async () => {
      resolvePreview?.({
        data: {
          lineage: { projectId: 'project_1', sourceAssetId: 'creative_1' },
          instruction: 'Warm only the shoulders', scope: 'appearance' as const,
          candidate: {
            id: 'candidate_from_old_source', jobId: 'run_old_source',
            sourceRevisionId: 'creative_1', assetUrl: 'https://test/old-preview.png',
            verdict: 'pass' as const, status: 'pending_review' as const, checks: [],
            temporary: true, expiresAt: null, decision: null, decidedAt: null,
            canonicalRevisionId: null,
          },
        },
        error: null,
        status: 201,
      });
    });

    expect(rendered.queryByText('Nothing has changed yet.')).toBeNull();
    expect(rendered.queryByText('REQUESTED CHANGE')).toBeNull();
    expect(rendered.queryByText('Warm only the shoulders')).toBeNull();
    expect(rendered.queryByLabelText('Temporary refinement preview')).toBeNull();
    expect(rendered.getByPlaceholderText(/make the presentation softer/i).props.value).toBe('');
  });

  test('ignores a late Apply completion after the designer switches source revisions', async () => {
    const candidate = {
      id: 'candidate_for_old_source', jobId: 'run_for_old_source',
      sourceRevisionId: 'creative_1', assetUrl: 'https://test/old-preview.png',
      verdict: 'pass' as const, status: 'pending_review' as const, checks: [],
      temporary: true, expiresAt: null, decision: null, decidedAt: null,
      canonicalRevisionId: null,
    };
    let resolveApply: ((value: any) => void) | null = null;
    const applyVisualRefine = jest.fn(() => new Promise<any>((resolve) => {
      resolveApply = resolve;
    }));
    const api = {
      getComponentCatalog: jest.fn(),
      getStudioComponentTargeting: getReadyTargeting,
      readMarkup: jest.fn(),
    };
    const gateway = {
      previewVisualRefine: jest.fn(async () => ({
        data: {
          lineage: { projectId: 'project_1', sourceAssetId: 'creative_1' },
          instruction: 'Warm the metal', scope: 'appearance' as const, candidate,
        },
        error: null,
        status: 201,
      })),
      applyVisualRefine,
      discardVisualRefine: jest.fn(),
      previewCatalogRefine: jest.fn(), applyCatalogRefine: jest.fn(),
      discardCatalogRefine: jest.fn(), previewMarkupRefine: jest.fn(),
      applyMarkupRefine: jest.fn(), discardMarkupRefine: jest.fn(),
    };
    const onApplied = jest.fn();
    const workspace = (sourceAssetId: string, sourceImageUrl: string) => (
      <AuthenticatedImageProvider
        allowedOrigin="https://test"
        headers={{ Authorization: 'Bearer test-session-token' }}>
        <StudioRefineWorkspace
          api={api}
          gateway={gateway}
          lineage={{ projectId: 'project_1', sourceAssetId }}
          sourceImageUrl={sourceImageUrl}
          createdBy="designer"
          onApplied={onApplied}
        />
      </AuthenticatedImageProvider>
    );
    const rendered = await render(workspace('creative_1', 'https://test/source-1.png'));

    await fireEvent.changeText(
      rendered.getByPlaceholderText(/make the presentation softer/i),
      'Warm the metal',
    );
    await waitFor(() => expect(
      rendered.getByPlaceholderText(/make the presentation softer/i).props.value,
    ).toBe('Warm the metal'));
    await fireEvent.press(rendered.getByText('Preview change'));
    expect(await rendered.findByText('Nothing has changed yet.')).toBeTruthy();
    await fireEvent(rendered.getByLabelText('Exact source revision'), 'load');
    await fireEvent(rendered.getByLabelText('Temporary refinement preview'), 'load');
    await fireEvent.press(rendered.getByText('Apply as new revision'));
    await waitFor(() => expect(applyVisualRefine).toHaveBeenCalledWith({
      candidateId: 'candidate_for_old_source', createdBy: 'designer',
    }));

    await rendered.rerender(workspace('creative_2', 'https://test/source-2.png'));
    await act(async () => {
      resolveApply?.({
        data: {
          candidate: { ...candidate, status: 'applied' as const },
          project: preSpecProject,
        },
        error: null,
        status: 201,
      });
    });

    expect(onApplied).not.toHaveBeenCalled();
    expect(rendered.queryByText('Nothing has changed yet.')).toBeNull();
    expect(rendered.getByPlaceholderText(/make the presentation softer/i).props.value).toBe('');
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
    expect(await screen.findByText(/only presentation changes proceed directly/i)).toBeTruthy();
    await fireEvent.changeText(
      screen.getByPlaceholderText(/make the presentation softer/i),
      'Make the background warmer',
    );
    await waitFor(() => expect(screen.getByDisplayValue('Make the background warmer')).toBeTruthy());
    await fireEvent.press(screen.getByText('Preview change'));
    await waitFor(() => expect(previewMarkupRefine).toHaveBeenCalledWith(expect.objectContaining({
      sourceAssetId: 'asset_2',
      annotation: expect.objectContaining({
        impact: 'visual_only',
        change_instruction: 'Make the background warmer',
      }),
    })));
    expect(await screen.findByText('Nothing has changed yet.')).toBeTruthy();
    expect(screen.queryByTestId('refine-comparison-inspector')).toBeNull();
    expect(screen.getByLabelText('Temporary refinement preview')).toBeTruthy();
  });

  test('reopens an exact-lineage pending preview for authenticated source comparison and Apply', async () => {
    const onApplied = jest.fn();
    const resumeRefine = jest.fn(async () => ({
      data: {
        kind: 'catalog' as const,
        understoodAs: 'A pending component preview was restored for review.',
        intent: {
          kind: 'component' as const, componentPath: 'stone.cut' as const,
          optionId: 'emerald_cut', requestedChange: 'Apply emerald cut',
        },
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
    expect(screen.getByText('Stone cut → Emerald cut')).toBeTruthy();
    expect(screen.getByLabelText('Exact source revision').props.source.headers).toEqual({
      Authorization: 'Bearer test-session-token',
    });
    expect(screen.getByLabelText('Temporary refinement preview').props.source.headers).toEqual({
      Authorization: 'Bearer test-session-token',
    });
    await fireEvent(screen.getByLabelText('Exact source revision'), 'load');
    await fireEvent(screen.getByLabelText('Temporary refinement preview'), 'load');
    await fireEvent.press(screen.getByText('Apply as new revision'));
    expect(applyCatalogRefine).toHaveBeenCalledWith({
      candidateId: 'candidate_resumed', createdBy: 'designer',
    });
    expect(onApplied).toHaveBeenCalledWith(project);
  });

  test('keeps Apply unavailable for a stale-source preview after both compact images load', async () => {
    const resumeRefine = jest.fn(async () => ({
      data: {
        kind: 'catalog' as const,
        understoodAs: 'A pending component preview was restored for review.',
        intent: {
          kind: 'component' as const, componentPath: 'stone.cut' as const,
          optionId: 'emerald_cut', requestedChange: 'Apply emerald cut',
        },
        candidate: {
          id: 'candidate_stale', jobId: 'run_stale', sourceRevisionId: 'asset_1',
          assetUrl: 'https://test/stale.png', verdict: 'pass' as const,
          status: 'pending_review' as const, checks: [], temporary: true,
          expiresAt: '2099-01-01T00:00:00Z', decision: null,
          decidedAt: null, canonicalRevisionId: null,
        },
      },
      error: null,
      status: 200,
    }));
    const applyCatalogRefine = jest.fn();

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
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1 }}
        createdBy="designer"
        sourceImageUrl="https://test/source-stale.png"
        reviewSourceIsActive={false}
        onApplied={jest.fn()}
      />,
    );

    expect(await screen.findByText(/created from an earlier revision/i)).toBeTruthy();
    expect(screen.getByTestId('refine-comparison-inspector')).toBeTruthy();
    await fireEvent(screen.getByLabelText('Exact source revision'), 'load');
    await fireEvent(screen.getByLabelText('Temporary refinement preview'), 'load');
    expect(screen.getByText('Apply as new revision').parent?.props.accessibilityState.disabled).toBe(true);
    await fireEvent.press(screen.getByText('Apply as new revision'));
    expect(applyCatalogRefine).not.toHaveBeenCalled();
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
        intent: {
          kind: 'component' as const, componentPath: 'metal.color' as const,
          optionId: 'rose', requestedChange: 'Apply rose gold',
        },
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
    await fireEvent(screen.getByLabelText('Exact source revision'), 'load');
    await fireEvent(screen.getByLabelText('Temporary refinement preview'), 'load');
    await fireEvent.press(screen.getByText('Save as Variation'));
    expect(await screen.findByText(/source revision stays unchanged/i)).toBeTruthy();
    expect(saveCatalogPreviewAsVariation).not.toHaveBeenCalled();
    await fireEvent.changeText(
      screen.getByPlaceholderText('e.g. Rose gold halo'),
      '  Rose halo  ',
    );
    expect(await screen.findByDisplayValue('  Rose halo  ')).toBeTruthy();
    await fireEvent.press(screen.getByText('Save named variation'));
    expect(saveCatalogPreviewAsVariation).toHaveBeenCalledTimes(1);
    expect(saveCatalogPreviewAsVariation).toHaveBeenCalledWith({
      candidateId: 'candidate_variation', createdBy: 'designer', label: 'Rose halo',
    });
    expect(onApplied).not.toHaveBeenCalled();
    expect(onVariationCreated).not.toHaveBeenCalled();
  });

  test('keeps Advanced specifications out of the ordinary Refine workspace', async () => {
    const getStudioComponentTargeting = jest.fn(async () => ({
      data: readyTargeting, error: null, status: 200,
    }));
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog: jest.fn(async () => ({ data: catalog, error: null, status: 200 })),
          getStudioComponentTargeting,
          readMarkup: jest.fn(),
          getProject: jest.fn(async () => ({
            data: exactFactProject, error: null, status: 200,
          })),
          reviseStudioFacts: jest.fn(),
        }}
        gateway={{ resumeRefine: jest.fn(async () => ({
          data: null, error: null, status: 200,
        })) } as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        onApplied={jest.fn()}
      />,
    );

    expect(await screen.findByLabelText('What would you like to change?')).toBeTruthy();
    expect(screen.queryByLabelText('Advanced design facts')).toBeNull();
    expect(screen.queryByText('Review fact changes')).toBeNull();
    expect(screen.queryByLabelText('Identity fact group')).toBeNull();
    expect(screen.getByText('Preview change')).toBeTruthy();
    expect(getStudioComponentTargeting).toHaveBeenCalledWith('asset_2');
  });

  test('corrects a categorical fact and stone dimension in the focused Specifications workspace', async () => {
    const revisedProject = {
      ...exactFactProject, active_asset_id: 'asset_3', active_design_version: 3,
    } as ProjectDetail;
    let resolveRevision: ((value: any) => void) | null = null;
    const reviseStudioFacts = jest.fn(() => new Promise<any>((resolve) => {
      resolveRevision = resolve;
    }));
    const getComponentCatalog = jest.fn(async () => ({ data: catalog, error: null, status: 200 }));
    const getStudioComponentTargeting = jest.fn(async () => ({
      data: readyTargeting, error: null, status: 200,
    }));
    const prepareStudioComponentMap = jest.fn();
    const resumeRefine = jest.fn();
    const onApplied = jest.fn();
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog,
          getStudioComponentTargeting,
          prepareStudioComponentMap,
          readMarkup: jest.fn(), getProject: jest.fn(async () => ({
            data: exactFactProject, error: null, status: 200,
          })), reviseStudioFacts,
        }}
        gateway={{ resumeRefine } as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        workspaceMode="specifications"
        onApplied={onApplied}
      />,
    );

    expect(screen.getByText('SPECIFICATIONS')).toBeTruthy();
    expect(screen.getByText('Correct the recorded facts for this revision.')).toBeTruthy();
    expect(screen.queryByText('REFINE')).toBeNull();
    expect(screen.queryByLabelText('Component refine mode')).toBeNull();
    expect(screen.queryByLabelText('What would you like to change?')).toBeNull();
    expect(screen.queryByLabelText('Mark up refine mode')).toBeNull();
    expect(screen.queryByText('Preview change')).toBeNull();
    expect(screen.queryByLabelText('Advanced design facts')).toBeNull();
    expect(screen.queryByText('Stone species')).toBeNull();
    expect(await screen.findByText('Identity')).toBeTruthy();
    expect(getStudioComponentTargeting).not.toHaveBeenCalled();
    expect(prepareStudioComponentMap).not.toHaveBeenCalled();
    expect(getComponentCatalog).not.toHaveBeenCalled();
    expect(resumeRefine).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Identity fact group').props.accessibilityState.expanded).toBe(true);
    expect(screen.getByLabelText('Stone fact group').props.accessibilityState.expanded).toBe(false);
    expect(screen.queryByText('Stone species')).toBeNull();
    expect(screen.getAllByText(/0 credits/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/image pixels stay unchanged/i)).toBeTruthy();
    expect(screen.queryByText(/provider/i)).toBeNull();
    expect(screen.queryByText(/factory/i)).toBeNull();
    await fireEvent.press(screen.getByText('Review fact changes'));
    expect(await screen.findByText(/Nothing changed/i)).toBeTruthy();
    await fireEvent.press(screen.getByLabelText('Dimensions fact group'));
    await waitFor(() => {
      expect(screen.getByLabelText('Identity fact group').props.accessibilityState.expanded).toBe(false);
      expect(screen.getByLabelText('Dimensions fact group').props.accessibilityState.expanded).toBe(true);
    });
    expect(await screen.findByDisplayValue('8')).toBeTruthy();
    await fireEvent.changeText(screen.getByDisplayValue('8'), '-1');
    await waitFor(() => expect(screen.getByDisplayValue('-1')).toBeTruthy());
    expect(screen.queryByText(/Nothing changed/i)).toBeNull();
    await fireEvent.press(screen.getByText('Review fact changes'));
    expect(await screen.findByText(/Stone length must be a valid positive number/i)).toBeTruthy();
    expect(reviseStudioFacts).not.toHaveBeenCalled();
    await fireEvent.changeText(screen.getByDisplayValue('-1'), '8');
    await waitFor(() => expect(screen.getByDisplayValue('8')).toBeTruthy());
    await fireEvent.press(screen.getByLabelText('Identity fact group'));
    const roseOption = await screen.findByText('Rose');
    await fireEvent.press(roseOption);
    await fireEvent.press(screen.getByLabelText('Dimensions fact group'));
    const stoneLength = await screen.findByDisplayValue('8');
    await fireEvent.changeText(stoneLength, '8.2');
    await waitFor(() => expect(screen.getByDisplayValue('8.2')).toBeTruthy());
    await fireEvent.press(screen.getByText('Review fact changes'));
    expect(await screen.findByText('Review only what changed')).toBeTruthy();
    expect(screen.getByText('Yellow → Rose')).toBeTruthy();
    expect(screen.getByText('8 → 8.2 mm')).toBeTruthy();
    expect(reviseStudioFacts).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByText('Save fact revision'));
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

  test('restores gold and a prong setting only with their explicit grouped dependencies', async () => {
    const coupledProject = {
      ...exactFactProject,
      spec: {
        ...(exactFactProject.spec as any),
        metal: { material: 'platinum', karat: null, color: null, finish: 'polished' },
        setting: { style: 'bezel', prong_count: null, prong_tip_mm: null },
      },
    } as ProjectDetail;
    const reviseStudioFacts = jest.fn(async () => ({
      data: {
        status: 'applied' as const, project_root_id: 'project_1', source_asset_id: 'asset_2',
        asset_id: 'asset_3', design_id: 'design_1', previous_design_version: 2,
        design_version: 3, spec_change: [], project_detail: coupledProject,
      },
      error: null, status: 200,
    }));
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog: jest.fn(),
          getStudioComponentTargeting: jest.fn(),
          getProject: jest.fn(async () => ({ data: coupledProject, error: null, status: 200 })),
          reviseStudioFacts,
          readMarkup: jest.fn(),
        }}
        gateway={{} as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        workspaceMode="specifications"
        onApplied={jest.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByLabelText('Identity fact group')).toBeTruthy());
    await fireEvent.press(screen.getByText('Gold'));
    await fireEvent.press(screen.getByText('Yellow'));
    await fireEvent.changeText(screen.getByLabelText('Gold karat'), '18');
    await fireEvent.press(screen.getByLabelText('Setting fact group'));
    await fireEvent.press(await screen.findByText('4 Prong Basket'));
    await fireEvent.changeText(screen.getByLabelText('Prong-tip gauge (mm)'), '0.9');
    expect(screen.queryByText('Halo')).toBeNull();
    expect(screen.queryByText('Pave')).toBeNull();
    expect(screen.queryByText('Channel')).toBeNull();
    await fireEvent.press(screen.getByText('Review fact changes'));
    expect(await screen.findByText('Review only what changed')).toBeTruthy();
    await fireEvent.press(screen.getByText('Save fact revision'));
    await waitFor(() => expect(reviseStudioFacts).toHaveBeenCalledWith('project_1', {
      expected_active_asset_id: 'asset_2',
      expected_design_version: 2,
      created_by: 'designer',
      changes: [
        { path: 'metal.material', value: 'gold' },
        { path: 'metal.color', value: 'yellow' },
        { path: 'metal.karat', value: 18 },
        { path: 'setting.style', value: '4_prong_basket' },
        { path: 'setting.prong_tip_mm', value: 0.9 },
      ],
    }));
  });

  test('hides setting constructions that are incompatible with the exact stone cut', async () => {
    const emeraldProject = {
      ...exactFactProject,
      spec: {
        ...(exactFactProject.spec as any),
        stone: { ...(exactFactProject.spec as any).stone, cut: 'emerald_cut' },
        setting: { style: 'bezel', prong_count: null, prong_tip_mm: null },
      },
    } as ProjectDetail;
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog: jest.fn(),
          getStudioComponentTargeting: jest.fn(),
          getProject: jest.fn(async () => ({ data: emeraldProject, error: null, status: 200 })),
          reviseStudioFacts: jest.fn(),
          readMarkup: jest.fn(),
        }}
        gateway={{} as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        workspaceMode="specifications"
        onApplied={jest.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByLabelText('Setting fact group')).toBeTruthy());
    await fireEvent.press(screen.getByLabelText('Setting fact group'));
    expect(await screen.findByText('4 Prong Basket')).toBeTruthy();
    expect(screen.queryByText('6 Prong Basket')).toBeNull();
    expect(screen.getByText('Bezel')).toBeTruthy();
    expect(screen.getByText('Semi Bezel')).toBeTruthy();
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

    await waitFor(() => expect(screen.getByText(/will not guess component geometry/i)).toBeTruthy());
    expect(screen.queryByLabelText('Component refine mode')).toBeNull();
    expect(screen.getByLabelText('What would you like to change?')).toBeTruthy();
    expect(screen.getByText('What would you like to change?')).toBeTruthy();
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
    await waitFor(() => expect(screen.getByLabelText('Component refine mode')).toBeTruthy());
    expect(getComponentCatalog).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByLabelText('Component refine mode'));
    await waitFor(() => expect(getComponentCatalog).toHaveBeenCalledWith('metal.color'));
  });

  test('offers mapped material paths while disabling unresolved structural paths', async () => {
    const getComponentCatalog = jest.fn(async () => ({ data: catalog, error: null, status: 200 }));
    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog,
          getStudioComponentTargeting: getReadyTargeting,
          readMarkup: jest.fn(),
        }}
        gateway={{} as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        onApplied={jest.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByLabelText('Component refine mode')).toBeTruthy());
    expect(getComponentCatalog).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByLabelText('Component refine mode'));
    await waitFor(() => expect(
      screen.getByLabelText('Metal color component path').props.accessibilityState.disabled,
    ).toBe(false));
    expect(screen.getByLabelText('Stone color component path').props.accessibilityState.disabled).toBe(true);
    expect(screen.getByText(/Record the exact stone species/i)).toBeTruthy();
    expect(screen.getByLabelText('Stone cut component path').props.accessibilityState.disabled).toBe(true);
    expect(screen.getByLabelText('Setting component path').props.accessibilityState.disabled).toBe(true);
    expect(screen.getAllByText(/not ready for that precise component change yet/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/calibrated|structural mapping|component identity/i)).toBeNull();
    expect(screen.getByText(/creates a temporary candidate before anything enters design history/i)).toBeTruthy();
  });

  test('loads stone colors only with the exact lineage-checked stone species', async () => {
    const stoneColorCatalog: ComponentCatalog = {
      component_path: 'stone.color' as const,
      display: 'Stone color', applicable_jewelry_types: ['ring'],
      image_agent_status: 'catalog_ready' as const,
      preview_execution_modes: ['provider'],
      options: [{
        id: 'cornflower_blue', display: 'Cornflower blue', visual_geometry: [],
        isolation_target: 'Center stone', frozen_facts: ['stone geometry', 'setting geometry'],
        factory_fields: {}, derived_factory_fields: [], selection_requirements: [],
      }],
    };
    const getComponentCatalog = jest.fn(async (componentPath: string) => ({
      data: componentPath === 'stone.color' ? stoneColorCatalog : catalog,
      error: null,
      status: 200,
    }));

    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog,
          getStudioComponentTargeting: getReadyTargeting,
          getProject: jest.fn(async () => ({
            data: exactFactProject, error: null, status: 200,
          })),
          readMarkup: jest.fn(),
        }}
        gateway={{} as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        onApplied={jest.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByLabelText('Component refine mode')).toBeTruthy());
    await fireEvent.press(screen.getByLabelText('Component refine mode'));
    await waitFor(() => expect(
      screen.getByLabelText('Stone color component path').props.accessibilityState.disabled,
    ).toBe(false));
    await fireEvent.press(screen.getByLabelText('Stone color component path'));
    await waitFor(() => expect(getComponentCatalog).toHaveBeenCalledWith('stone.color', {
      stoneSpecies: 'sapphire',
    }));
    expect(await screen.findByText('Cornflower blue')).toBeTruthy();
  });

  test('fails closed when the species-scoped stone color catalog is unavailable', async () => {
    const getComponentCatalog = jest.fn(async (componentPath: string) => (
      componentPath === 'stone.color'
        ? {
          data: null,
          error: {
            code: 'stone_species_invalid', message: 'unknown gemstone species',
            category: 'validation' as const, status: 422, retryable: false,
          },
          status: 422,
        }
        : { data: catalog, error: null, status: 200 }
    ));

    await renderWithAuth(
      <StudioRefineWorkspace
        api={{
          getComponentCatalog,
          getStudioComponentTargeting: getReadyTargeting,
          getProject: jest.fn(async () => ({
            data: exactFactProject, error: null, status: 200,
          })),
          readMarkup: jest.fn(),
        }}
        gateway={{ previewCatalogRefine: jest.fn() } as any}
        lineage={{ projectId: 'project_1', sourceAssetId: 'asset_2', sourceDesignVersion: 2 }}
        createdBy="designer"
        onApplied={jest.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByLabelText('Component refine mode')).toBeTruthy());
    await fireEvent.press(screen.getByLabelText('Component refine mode'));
    await waitFor(() => expect(
      screen.getByLabelText('Stone color component path').props.accessibilityState.disabled,
    ).toBe(false));
    await fireEvent.press(screen.getByLabelText('Stone color component path'));
    expect(await screen.findByText('Check the requested change or reference, then try again.')).toBeTruthy();
    expect(screen.queryByText(/stone_species_invalid|unknown gemstone species/i)).toBeNull();
    expect(screen.getByText('Preview change').parent?.props.accessibilityState.disabled).toBe(true);
  });
});
