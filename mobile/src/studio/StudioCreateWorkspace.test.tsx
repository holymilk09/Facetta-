/// <reference types="jest" />

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import type { StudioGateway } from './gateway';
import { StudioCreateReference, StudioCreateWorkspace } from './StudioCreateWorkspace';
import type { TrustedApiClient } from '../trusted/client';
import type { AssetSummary, ProjectDetail } from '../trusted/types';

const candidate = (index: number): AssetSummary => ({
  asset_id: `candidate_${index}`,
  root_id: 'project_1',
  parent_asset_id: null,
  capability: 'CREATIVE_RENDER',
  provenance: 'pre_spec_creative_candidate',
  revision: index,
  design_id: null,
  design_version: null,
  region: null,
  instruction: 'Creative direction',
  drift: null,
  pinned: false,
  media_type: 'image/png',
  image_url: `https://facetta.test/candidate-${index}.png`,
  created_by: 'designer_1',
  created_at: null,
  legacy_provenance: false,
});

const creativeProject = (count: number): ProjectDetail => {
  const candidates = Array.from({ length: count }, (_, index) => candidate(index + 1));
  return {
    id: 'project_1',
    root_id: 'project_1',
    title: 'Creative study',
    collection: null,
    tags: [],
    owner: 'designer_1',
    state: 'refining',
    design_id: null,
    spec: null,
    active_asset_id: candidates[0].asset_id,
    active_design_version: null,
    active_revision: candidates[0],
    pinned_revision: null,
    revisions: candidates.map((asset, index) => ({
      revision: index + 1,
      asset,
      spec_version: null,
      spec_change: [],
      ignored_fields: [],
      qa: null,
      routing: null,
      created_at: null,
    })),
    assets: candidates,
    derived_assets: [],
    approval: null,
    factory_ready: false,
    factory_blockers: [],
    primary_revision_count: count,
    has_factory_drawing: false,
    cover_asset_id: candidates[0].asset_id,
    created_at: null,
    updated_at: null,
  };
};

type CreateGateway = Pick<StudioGateway, 'createFromPrompt' | 'selectCreativeDirection'>;
type DrawingClient = Pick<TrustedApiClient, 'createProjectFromDrawing'>;

test('requests 1-4 prompt candidates, lets the designer choose, then saves only that direction', async () => {
  const createFromPrompt = jest.fn(async () => ({
    data: creativeProject(4), error: null, status: 201,
  }));
  const selectCreativeDirection = jest.fn(async (_projectId, candidateId) => ({
    data: { ...creativeProject(4), selected_candidate_asset_id: candidateId, active_asset_id: candidateId },
    error: null,
    status: 200,
  }));
  const onSave = jest.fn();
  await render(React.createElement(StudioCreateWorkspace, {
    gateway: { createFromPrompt, selectCreativeDirection } as CreateGateway,
    trustedClient: { createProjectFromDrawing: jest.fn() } as unknown as DrawingClient,
    owner: 'designer_1',
    onSave,
  }));

  expect(screen.queryByText(/factory facts/i)).toBeNull();
  expect(screen.queryByText(/structured specification/i)).toBeNull();
  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'A sculptural aquamarine collar.');
  await fireEvent.press(screen.getByText('4').parent!);
  await fireEvent.press(screen.getByText('Create 4 directions'));

  await waitFor(() => expect(createFromPrompt).toHaveBeenCalledWith({
    prompt: 'A sculptural aquamarine collar.',
    variation_count: 4,
    owner: 'designer_1',
    title: 'A sculptural aquamarine collar.',
  }));
  expect(await screen.findByText('Which outcome should stay in your Studio?')).toBeTruthy();
  expect(screen.getByText(/not specifications, measurements, or factory facts/i)).toBeTruthy();
  await fireEvent.press(screen.getByLabelText('Direction 3'));
  await fireEvent.press(screen.getByText('Save selected direction'));
  await waitFor(() => expect(selectCreativeDirection).toHaveBeenCalledWith(
    'project_1', 'candidate_3', 'designer_1',
  ));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    selectedAssetId: 'candidate_3',
    sentence: 'A sculptural aquamarine collar.',
  }));
});

test('uses only the supported master-geometry drawing input and labels unsupported roles honestly', async () => {
  const master: StudioCreateReference = {
    id: 'master', role: 'master_geometry', label: 'Front sketch',
    imageBase64: 'bWFzdGVy', mediaType: 'image/png',
  };
  const material: StudioCreateReference = {
    id: 'material', role: 'material_style', label: 'Brushed gold reference',
    imageBase64: 'bWF0ZXJpYWw=', mediaType: 'image/jpeg',
  };
  const createProjectFromDrawing = jest.fn(async () => ({
    data: creativeProject(2), error: null, status: 201,
  }));
  const createFromPrompt = jest.fn();
  const onRequestReference = jest.fn(async (role) => role === 'master_geometry' ? master : material);
  await render(React.createElement(StudioCreateWorkspace, {
    gateway: { createFromPrompt, selectCreativeDirection: jest.fn() } as unknown as CreateGateway,
    trustedClient: { createProjectFromDrawing } as unknown as DrawingClient,
    owner: 'designer_1',
    onRequestReference,
    onSave: jest.fn(),
  }));

  await fireEvent.press(screen.getAllByText('Add')[1]);
  expect(await screen.findByText('Reference limit in this version')).toBeTruthy();
  expect(screen.getByText(/Material & style will remain labeled in this draft/)).toBeTruthy();
  await fireEvent.press(screen.getAllByText('Add')[0]);
  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'Preserve the silhouette and make it feel lighter.');
  await fireEvent.press(screen.getByText('Create 2 directions'));

  await waitFor(() => expect(createProjectFromDrawing).toHaveBeenCalledWith({
    image_base64: 'bWFzdGVy',
    media_type: 'image/png',
    instruction: 'Preserve the silhouette and make it feel lighter.',
    variation_count: 2,
    owner: 'designer_1',
    title: 'Preserve the silhouette and make it feel lighter.',
  }));
  expect(createFromPrompt).not.toHaveBeenCalled();
});
