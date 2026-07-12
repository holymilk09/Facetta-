import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

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

describe('StudioRefineWorkspace', () => {
  test('fails closed when there is no exact immutable revision', async () => {
    await render(
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
    await render(
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
    await render(
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
    expect(screen.getByText(/still pre-spec/i)).toBeTruthy();
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
    await render(
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
    await render(
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
});
