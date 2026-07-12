/// <reference types="jest" />

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import type { StudioGateway } from './gateway';
import { StudioCreateReference, StudioCreateWorkspace } from './StudioCreateWorkspace';
import type { AssetSummary, ProjectDetail } from '../trusted/types';
import { AuthenticatedImageProvider } from '../AuthenticatedImage';

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

type CreateGateway = Pick<StudioGateway,
  'createFromPrompt' | 'createFromDrawing' | 'selectCreativeDirection'
>;

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
  await render(
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test"
      headers={{ Authorization: 'Bearer first-party-token' }}>
      <StudioCreateWorkspace
        gateway={{
          createFromPrompt, createFromDrawing: jest.fn(), selectCreativeDirection,
        } as CreateGateway}
        owner="designer_1"
        onSave={onSave}
      />
    </AuthenticatedImageProvider>,
  );

  expect(screen.queryByText(/factory facts/i)).toBeNull();
  expect(screen.queryByText(/structured specification/i)).toBeNull();
  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'A sculptural aquamarine collar.');
  await fireEvent.press(screen.getByText('4').parent!);
  expect(screen.getByText('4 requested outputs × 15 credits = estimated 60 credits')).toBeTruthy();
  await fireEvent.press(screen.getByText('Create 4 directions'));

  await waitFor(() => expect(createFromPrompt).toHaveBeenCalledWith({
    prompt: 'A sculptural aquamarine collar.',
    variation_count: 4,
    owner: 'designer_1',
    title: 'A sculptural aquamarine collar.',
  }));
  expect(await screen.findByText('Which direction should become active?')).toBeTruthy();
  expect(screen.getByText(/Every direction in this set is already retained/i)).toBeTruthy();
  expect(screen.getByText(/already retained in Collections/i)).toBeTruthy();
  expect(screen.getByText('Keep these directions & start another')).toBeTruthy();
  expect(screen.getByLabelText('Direction 1 preview').props.source.headers).toEqual({
    Authorization: 'Bearer first-party-token',
  });
  expect(screen.getByText(/visual directions.+not measurements or production instructions/i)).toBeTruthy();
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

test('keeps an already-created direction set when the designer starts another brief', async () => {
  const createFromPrompt = jest.fn(async () => ({
    data: creativeProject(2), error: null, status: 201,
  }));
  await render(<StudioCreateWorkspace
    gateway={{
      createFromPrompt, createFromDrawing: jest.fn(), selectCreativeDirection: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    initialSentence="First direction"
    onSave={jest.fn()}
  />);

  await fireEvent.press(screen.getByText('Create 2 directions'));
  expect(await screen.findByText(/already retained in Collections/i)).toBeTruthy();
  await fireEvent.press(screen.getByText('Keep these directions & start another'));
  expect(await screen.findByLabelText('Design sentence')).toBeTruthy();
  expect(screen.queryByText(/already retained in Collections/i)).toBeNull();
});

test('sends every enabled role with the master geometry input', async () => {
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
    gateway: {
      createFromPrompt,
      createFromDrawing: createProjectFromDrawing,
      selectCreativeDirection: jest.fn(),
    } as unknown as CreateGateway,
    owner: 'designer_1',
    onRequestReference,
    onSave: jest.fn(),
  }));

  await fireEvent.press(screen.getAllByText('Add')[0]);
  await fireEvent.press(screen.getAllByText('Add')[0]);
  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'Preserve the silhouette and make it feel lighter.');
  await fireEvent.press(screen.getByText('Create 2 directions'));

  await waitFor(() => expect(createProjectFromDrawing).toHaveBeenCalledWith({
    image_base64: 'bWFzdGVy',
    media_type: 'image/png',
    instruction: 'Preserve the silhouette and make it feel lighter.',
    references: [{
      role: 'material_style',
      image_base64: 'bWF0ZXJpYWw=',
      media_type: 'image/jpeg',
    }],
    variation_count: 2,
    owner: 'designer_1',
    title: 'Preserve the silhouette and make it feel lighter.',
  }));
  expect(createFromPrompt).not.toHaveBeenCalled();
  expect(screen.queryByText(/Reference limit|cannot send|remain labeled/i)).toBeNull();
});

test('starts from a master image without forcing a sentence', async () => {
  const master: StudioCreateReference = {
    id: 'master', role: 'master_geometry', label: 'Pendant photograph',
    imageBase64: 'bWFzdGVy', mediaType: 'image/png',
  };
  const createFromDrawing = jest.fn(async () => ({
    data: creativeProject(1), error: null, status: 201,
  }));
  await render(React.createElement(StudioCreateWorkspace, {
    gateway: {
      createFromPrompt: jest.fn(), createFromDrawing,
      selectCreativeDirection: jest.fn(),
    } as unknown as CreateGateway,
    owner: 'designer_1',
    initialReferences: [master],
    onSave: jest.fn(),
  }));

  await fireEvent.press(screen.getByText('Create 2 directions'));
  await waitFor(() => expect(createFromDrawing).toHaveBeenCalledWith({
    image_base64: 'bWFzdGVy',
    media_type: 'image/png',
    references: [],
    variation_count: 2,
    owner: 'designer_1',
    title: 'Pendant photograph',
  }));
});

test('surfaces picker failures instead of leaving Add as a silent dead end', async () => {
  const onRequestReference = jest.fn(async () => {
    throw new Error('Choose a PNG, JPEG, or WebP image. Other file types are not supported.');
  });
  await render(React.createElement(StudioCreateWorkspace, {
    gateway: {
      createFromPrompt: jest.fn(),
      createFromDrawing: jest.fn(),
      selectCreativeDirection: jest.fn(),
    } as unknown as CreateGateway,
    owner: 'designer_1',
    onRequestReference,
    onSave: jest.fn(),
  }));

  await fireEvent.press(screen.getAllByText('Add')[0]);

  expect(await screen.findByText(/Choose a PNG, JPEG, or WebP image/)).toBeTruthy();
  expect(onRequestReference).toHaveBeenCalledWith('master_geometry');
});

test('does not expose backend diagnostics when generation fails', async () => {
  await render(React.createElement(StudioCreateWorkspace, {
    gateway: {
      createFromPrompt: jest.fn(async () => ({
        data: null,
        error: {
          code: 'provider_failure', category: 'server', status: 500,
          message: 'Grok rejected base64 asset_id=ast_1 run_id=run_2 expected_design_version=4',
        },
        status: 500,
      })),
      createFromDrawing: jest.fn(),
      selectCreativeDirection: jest.fn(),
    } as unknown as CreateGateway,
    owner: 'designer_1',
    onSave: jest.fn(),
  }));

  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'A quiet gold ring.');
  await fireEvent.press(screen.getByText('Create 2 directions'));
  expect(await screen.findByText('Facetta could not create those directions. Try again.')).toBeTruthy();
  expect(screen.queryByText(/grok|base64|asset_id|run_id|design_version/i)).toBeNull();
});

test('explains when image selection is unavailable instead of silently ignoring Add', async () => {
  await render(React.createElement(StudioCreateWorkspace, {
    gateway: {
      createFromPrompt: jest.fn(),
      createFromDrawing: jest.fn(),
      selectCreativeDirection: jest.fn(),
    } as unknown as CreateGateway,
    owner: 'designer_1',
    onSave: jest.fn(),
  }));

  await fireEvent.press(screen.getAllByText('Add')[0]);

  expect(await screen.findByText(/Image selection is unavailable here/)).toBeTruthy();
});
