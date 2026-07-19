/// <reference types="jest" />

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import type { TrustedApiClient } from './client';
import { StudioHistoryPanel } from './StudioHistoryPanel';
import type { ProjectDetail } from './types';

const project: ProjectDetail = {
  id: 'project_main', root_id: 'project_main', title: 'Sapphire ring',
  collection: null, tags: [], owner: 'usr_designer', state: 'refining',
  design_id: 'design_ring', spec: { jewelry_type: 'ring' },
  active_asset_id: 'asset_2', active_design_version: 2,
  active_revision: null, pinned_revision: null, revisions: [], assets: [], derived_assets: [],
  approval: null, factory_ready: false, factory_blockers: [], primary_revision_count: 2,
  has_factory_drawing: false, cover_asset_id: 'asset_2', created_at: null, updated_at: null,
};

describe('StudioHistoryPanel', () => {
  test('shows sibling variations, compares exact revisions, and restores by appending', async () => {
    const getStudioProjectHistory = jest.fn(async () => ({
      data: {
        project_id: 'project_main', family_id: 'family_ring', variation_index: 1,
        variation_label: 'Original', active_asset_id: 'asset_2',
        revisions: [
          {
            revision: 1, asset_id: 'asset_1', parent_asset_id: null,
            design_version: 1, capability: 'SPEC_RENDER', image_url: 'https://test/1.png',
            pinned: false, action: 'created' as const, raw_intent: {}, interpretation: {},
            change_summary: 'Created the original direction.', restored_from_asset_id: null,
            created_by: 'usr_designer', created_at: '2026-07-12T01:00:00Z',
          },
          {
            revision: 2, asset_id: 'asset_2', parent_asset_id: 'asset_1',
            design_version: 2, capability: 'LOCALIZED_EDIT', image_url: 'https://test/2.png',
            pinned: false, action: 'edit' as const, raw_intent: {}, interpretation: {},
            change_summary: 'Changed the metal to rose gold.', restored_from_asset_id: null,
            created_by: 'usr_designer', created_at: '2026-07-12T02:00:00Z',
          },
        ],
      },
      error: null,
      status: 200,
    }));
    const getDesignFamily = jest.fn(async () => ({
      data: {
        family_id: 'family_ring', owner: 'usr_designer', title: 'Sapphire ring', tags: ['sapphire'],
        is_favorite: false, favorited_at: null,
        created_at: '2026-07-12T01:00:00Z', updated_at: '2026-07-12T02:00:00Z',
        variations: [
          {
            root_id: 'project_main', title: 'Sapphire ring', collection: 'Unfiled', tags: [],
            owner: 'usr_designer', counts: {}, item_count: 2, primary_revision_count: 2,
            has_factory_drawing: false, cover_asset_id: 'asset_2',
            created_at: '2026-07-12T01:00:00Z', updated_at: '2026-07-12T02:00:00Z',
            variation_index: 1, variation_label: 'Original',
            branched_from_project_root_id: null, branched_from_asset_id: null,
          },
          {
            root_id: 'project_rose', title: 'Sapphire ring', collection: 'Unfiled', tags: [],
            owner: 'usr_designer', counts: {}, item_count: 1, primary_revision_count: 1,
            has_factory_drawing: false, cover_asset_id: 'asset_rose',
            created_at: '2026-07-12T03:00:00Z', updated_at: '2026-07-12T03:00:00Z',
            variation_index: 2, variation_label: 'Rose study',
            branched_from_project_root_id: 'project_main', branched_from_asset_id: 'asset_2',
          },
        ],
      },
      error: null,
      status: 200,
    }));
    const restoreStudioRevision = jest.fn(async () => ({
      data: {
        status: 'restored_as_new_revision' as const, restored_from_asset_id: 'asset_1',
        new_asset_id: 'asset_3', new_design_version: 3, spec_change: [],
        project: { ...project, active_asset_id: 'asset_3', active_design_version: 3 },
      },
      error: null,
      status: 201,
    }));
    const assetImageUrl = jest.fn((assetId: string) => `https://test/${assetId}.png`);
    const client = {
      getStudioProjectHistory, getDesignFamily, restoreStudioRevision, assetImageUrl,
    } as unknown as TrustedApiClient;
    const onOpenProject = jest.fn();
    const onProjectChanged = jest.fn();

    await render(<StudioHistoryPanel
      client={client}
      project={project}
      createdBy="usr_designer"
      onOpenProject={onOpenProject}
      onProjectChanged={onProjectChanged}
    />);

    expect(await screen.findByText('Rose study')).toBeTruthy();
    await fireEvent.press(screen.getByText('Rose study'));
    expect(onOpenProject).toHaveBeenCalledWith('project_rose');

    const compareButtons = screen.getAllByText('Compare');
    await fireEvent.press(compareButtons[0]);
    await fireEvent.press(screen.getByText('Compare'));
    expect(screen.getByText('Compare exact revisions')).toBeTruthy();

    await fireEvent.press(screen.getByText('Restore as new'));
    await waitFor(() => expect(restoreStudioRevision).toHaveBeenCalledWith(
      'project_main', 'asset_1', {
        created_by: 'usr_designer', expected_active_asset_id: 'asset_2',
        expected_design_version: 2,
      },
    ));
    expect(onProjectChanged).toHaveBeenCalledWith(expect.objectContaining({
      active_asset_id: 'asset_3',
    }));
  });
});
