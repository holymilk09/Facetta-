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

describe('StudioRefineWorkspace', () => {
  test('fails closed when there is no exact immutable revision', async () => {
    await render(
      <StudioRefineWorkspace
        api={{ getComponentCatalog: jest.fn(async () => ({ data: catalog, error: null, status: 200 })) }}
        gateway={{
          previewCatalogRefine: jest.fn(), applyCatalogRefine: jest.fn(), discardCatalogRefine: jest.fn(),
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
        api={{ getComponentCatalog: jest.fn(async () => ({ data: catalog, error: null, status: 200 })) }}
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
});
