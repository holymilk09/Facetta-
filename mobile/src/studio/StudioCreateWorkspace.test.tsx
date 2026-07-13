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
  revision: null,
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
    active_asset_id: null,
    active_design_version: null,
    active_revision: null,
    pinned_revision: null,
    revisions: [],
    creative_candidates: candidates,
    assets: candidates,
    derived_assets: [],
    approval: null,
    factory_ready: false,
    factory_blockers: [],
    primary_revision_count: 0,
    has_factory_drawing: false,
    cover_asset_id: candidates[0].asset_id,
    created_at: null,
    updated_at: null,
  };
};

type CreateGateway = Pick<StudioGateway,
  'createFromPrompt' | 'createFromDrawing' | 'selectCreativeDirection'
>;

test('stages sibling variations locally and commits them only with the explicit Continue action', async () => {
  const createFromPrompt = jest.fn(async () => ({
    data: creativeProject(4), error: null, status: 201,
  }));
  const selectCreativeDirection = jest.fn(async (_projectId, candidateId) => ({
    data: { ...creativeProject(4), selected_candidate_asset_id: candidateId, active_asset_id: candidateId },
    error: null,
    status: 200,
  }));
  const saveCreativeDirectionAsVariation = jest.fn(async ({ candidateId }) => ({
    data: {
      status: 'variation_created' as const,
      family_id: 'family_1', variation_index: 2,
      source_project_id: 'project_1', source_asset_id: candidateId,
      project: creativeProject(1),
    },
    error: null,
    status: 201,
  }));
  const onSave = jest.fn();
  await render(
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test"
      headers={{ Authorization: 'Bearer first-party-token' }}>
      <StudioCreateWorkspace
        gateway={{
          createFromPrompt, createFromDrawing: jest.fn(), selectCreativeDirection,
          saveCreativeDirectionAsVariation,
        } as CreateGateway}
        owner="designer_1"
        onSave={onSave}
      />
    </AuthenticatedImageProvider>,
  );

  expect(screen.queryByText(/factory facts/i)).toBeNull();
  expect(screen.queryByText(/structured specification/i)).toBeNull();
  expect(screen.queryByText('How many directions?')).toBeNull();
  expect(screen.queryByText('Optional references')).toBeNull();
  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'A sculptural aquamarine collar.');
  await fireEvent.press(screen.getByLabelText('References and output options'));
  await fireEvent.press(screen.getByLabelText('4 creative directions'));
  expect(screen.getByText('4 requested outputs × 15 credits = estimated 60 credits')).toBeTruthy();
  await fireEvent.press(screen.getByText('Create 4 directions'));

  await waitFor(() => expect(createFromPrompt).toHaveBeenCalledWith({
    prompt: 'A sculptural aquamarine collar.',
    variation_count: 4,
    owner: 'designer_1',
    title: 'A sculptural aquamarine collar.',
  }));
  expect(await screen.findByText('Which direction do you want to refine?')).toBeTruthy();
  expect(screen.getByText(/Your choice becomes the Original/i)).toBeTruthy();
  expect(screen.getByText(/keep as a sibling variation/i)).toBeTruthy();
  expect(screen.getByText('Leave in Activity & start another')).toBeTruthy();
  expect(screen.getByLabelText('Direction 1 preview').props.source.headers).toEqual({
    Authorization: 'Bearer first-party-token',
  });
  expect(screen.getByText(/visual directions.+not measurements or production instructions/i)).toBeTruthy();
  await fireEvent.press(screen.getAllByText('Keep as variation')[0]);
  expect(selectCreativeDirection).not.toHaveBeenCalled();
  expect(saveCreativeDirectionAsVariation).not.toHaveBeenCalled();
  expect(onSave).not.toHaveBeenCalled();
  expect(screen.getByText('Remove from kept variations')).toBeTruthy();

  await fireEvent.press(screen.getByText('Remove from kept variations'));
  expect(screen.getByText('Continue with Direction 1')).toBeTruthy();
  expect(selectCreativeDirection).not.toHaveBeenCalled();
  expect(saveCreativeDirectionAsVariation).not.toHaveBeenCalled();

  await fireEvent.press(screen.getAllByText('Keep as variation')[0]);
  await fireEvent.press(screen.getByLabelText('Direction 3'));
  expect(screen.getByText('Continue with Direction 3 · keep 1 variation')).toBeTruthy();
  await fireEvent.press(screen.getByText('Continue with Direction 3 · keep 1 variation'));
  await waitFor(() => expect(selectCreativeDirection).toHaveBeenCalledWith(
    'project_1', 'candidate_3', 'designer_1',
  ));
  await waitFor(() => expect(saveCreativeDirectionAsVariation).toHaveBeenCalledWith({
    projectId: 'project_1', candidateId: 'candidate_2', activeAssetId: 'candidate_3',
    createdBy: 'designer_1', label: 'Direction 2',
  }));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    selectedAssetId: 'candidate_3',
    sentence: 'A sculptural aquamarine collar.',
  }));
});

test('reopens a durable reviewing Create job and settles that exact job on selection', async () => {
  const createFromPrompt = jest.fn();
  const createFromDrawing = jest.fn();
  const selectCreativeDirection = jest.fn(async (_projectId, candidateId) => ({
    data: {
      ...creativeProject(3),
      selected_candidate_asset_id: candidateId,
      active_asset_id: candidateId,
    },
    error: null,
    status: 200,
  }));
  const onSave = jest.fn();
  await render(
    <StudioCreateWorkspace
      gateway={{
        createFromPrompt, createFromDrawing, selectCreativeDirection,
      } as CreateGateway}
      owner="designer_1"
      resumeProject={creativeProject(3)}
      resumeStudioJobId="studio_job_create"
      onSave={onSave}
    />,
  );

  expect(await screen.findByText('Which direction do you want to refine?')).toBeTruthy();
  expect(createFromPrompt).not.toHaveBeenCalled();
  expect(createFromDrawing).not.toHaveBeenCalled();
  await fireEvent.press(screen.getByLabelText('Direction 2'));
  await fireEvent.press(screen.getByText('Continue with Direction 2'));
  await waitFor(() => expect(selectCreativeDirection).toHaveBeenCalledWith(
    'project_1', 'candidate_2', 'designer_1', 'studio_job_create',
  ));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    selectedAssetId: 'candidate_2',
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
  expect(await screen.findByText(/Your choice becomes the Original/i)).toBeTruthy();
  await fireEvent.press(screen.getAllByText('Keep as variation')[0]);
  expect(screen.getByText('Continue with Direction 1 · keep 1 variation')).toBeTruthy();
  await fireEvent.press(screen.getByText('Leave in Activity & start another'));
  expect(await screen.findByLabelText('Design sentence')).toBeTruthy();
  expect(screen.queryByText(/Your choice becomes the Original/i)).toBeNull();
  await fireEvent.press(screen.getByText('Create 2 directions'));
  expect(await screen.findByText('Continue with Direction 1')).toBeTruthy();
  expect(screen.queryByText(/keep 1 variation/i)).toBeNull();
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

  await fireEvent.press(screen.getByText('Add a drawing, photo, or render'));
  expect(screen.getByText('What did you upload?')).toBeTruthy();
  await fireEvent.press(screen.getByText('Drawing'));
  await fireEvent.press(screen.getByLabelText('References and output options'));
  await fireEvent.press(screen.getByLabelText('Add Material & style reference'));
  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'Preserve the silhouette and make it feel lighter.');
  await fireEvent.press(screen.getByText('Create 2 directions'));

  await waitFor(() => expect(createProjectFromDrawing).toHaveBeenCalledWith({
    image_base64: 'bWFzdGVy',
    source_kind: 'drawing',
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
    imageBase64: 'bWFzdGVy', mediaType: 'image/png', sourceKind: 'photograph',
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

  expect(screen.getByLabelText('Visual source preview').props.source.uri).toBe(
    'data:image/png;base64,bWFzdGVy',
  );
  expect(screen.getByLabelText('Replace visual source')).toBeTruthy();
  await fireEvent.press(screen.getByText('Create 2 directions'));
  await waitFor(() => expect(createFromDrawing).toHaveBeenCalledWith({
    image_base64: 'bWFzdGVy',
    source_kind: 'photograph',
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

  await fireEvent.press(screen.getByText('Add a drawing, photo, or render'));

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

  await fireEvent.press(screen.getByText('Add a drawing, photo, or render'));

  expect(await screen.findByText(/Image selection is unavailable here/)).toBeTruthy();
});
