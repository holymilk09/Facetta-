/// <reference types="jest" />

import React from 'react';
import { Dimensions, Platform } from 'react-native';
import {
  act, fireEvent, render, screen, waitFor, within,
} from '@testing-library/react-native';

import type { StudioGateway } from './gateway';
import {
  composeCreateBalanceInstruction, composeCreateInstruction, draftAfterGeneration,
  EMPTY_STUDIO_CREATE_DRAFT, StudioCreateWorkspace, uploadOnlyInstruction,
  type StudioCreateDraft,
  type StudioCreateReference,
} from './StudioCreateWorkspace';
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
  'createFromPrompt' | 'createFromDrawing' | 'completeCreativeDirectionReview'
>;

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
};

function DraftClearingCreate({
  gateway, onSave, onGenerationSucceeded,
}: {
  gateway: CreateGateway;
  onSave: React.ComponentProps<typeof StudioCreateWorkspace>['onSave'];
  onGenerationSucceeded: NonNullable<React.ComponentProps<
    typeof StudioCreateWorkspace
  >['onGenerationSucceeded']>;
}) {
  const [draft, setDraft] = React.useState<StudioCreateDraft>(EMPTY_STUDIO_CREATE_DRAFT);
  return (
    <StudioCreateWorkspace
      gateway={gateway}
      owner="designer_1"
      draft={draft}
      onDraftChange={setDraft}
      onGenerationSucceeded={(success) => {
        setDraft((current) => draftAfterGeneration(current, success.submittedDraft));
        onGenerationSucceeded(success);
      }}
      onSave={onSave}
    />
  );
}

const renderCreate = (ui: React.ReactElement) => render(
  <AuthenticatedImageProvider
    allowedOrigin="https://facetta.test"
    headers={{ Authorization: 'Bearer first-party-token' }}>
    {ui}
  </AuthenticatedImageProvider>,
);

const loadDirection = async (index: number): Promise<void> => {
  await act(async () => {
    fireEvent(screen.getByLabelText(`Direction ${index} preview`), 'load');
  });
};

const loadReferencePreview = async (label: string): Promise<void> => {
  await act(async () => {
    fireEvent(screen.getByLabelText(label), 'load');
  });
};

test('presents sentence or rough visual source as the only primary starting choices', async () => {
  const onRequestReference = jest.fn();
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    onRequestReference={onRequestReference}
    onSave={jest.fn()}
  />);

  expect(screen.getByText('Start your jewelry design')).toBeTruthy();
  expect(screen.getByText(/choose one starting point.+sentence.+visual source/i)).toBeTruthy();
  expect(screen.getByText('Describe it in one sentence')).toBeTruthy();
  expect(screen.getByText('OR')).toBeTruthy();
  expect(screen.getByText('Upload a visual source')).toBeTruthy();
  expect(screen.getByText(/rough pencil sketches are welcome.+Facetta will interpret/i)).toBeTruthy();
  expect(screen.getByText('OUTPUT OPTIONS · OPTIONAL')).toBeTruthy();
  expect(screen.getByText('How many variations?')).toBeTruthy();
  expect(screen.getByText(/keep 1 for a single result.+up to 4 design alternatives/i)).toBeTruthy();
  const quantity = screen.getByLabelText('Number of variations');
  expect(within(quantity).getByLabelText('1 variation').props.accessibilityState).toEqual({
    checked: true,
  });
  expect(screen.getByText('15 credits per variation · 1 variation = 15 credits')).toBeTruthy();
  expect(screen.getByText('Generate')).toBeTruthy();
  expect(screen.queryByText('Create 1 direction')).toBeNull();
  expect(onRequestReference).not.toHaveBeenCalled();
});

test('defines a clear upload-only instruction for every explicit source kind', () => {
  expect(uploadOnlyInstruction('drawing')).toMatch(/drawing.+preserving.+silhouette/i);
  expect(uploadOnlyInstruction('photograph')).toMatch(/photograph.+preserving.+visible piece/i);
  expect(uploadOnlyInstruction('finished_render')).toMatch(/finished render.+preserving.+silhouette/i);
  expect(new Set([
    uploadOnlyInstruction('drawing'),
    uploadOnlyInstruction('photograph'),
    uploadOnlyInstruction('finished_render'),
  ]).size).toBe(3);
});

test('updates the disclosed total before requesting extra variations', async () => {
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    onSave={jest.fn()}
  />);

  const quantity = screen.getByLabelText('Number of variations');
  await fireEvent.press(within(quantity).getByLabelText('3 variations'));

  expect(within(quantity).getByLabelText('3 variations').props.accessibilityState).toEqual({
    checked: true,
  });
  expect(screen.getByText('15 credits per variation · 3 variations = 45 credits')).toBeTruthy();
  expect(screen.getByText('Generate')).toBeTruthy();
});

test('keeps the submitted two-variation quantity and estimate visible with its review set', async () => {
  const originalPlatform = Platform.OS;
  const originalWindow = Dimensions.get('window');
  const originalScreen = Dimensions.get('screen');
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'web' });
  Dimensions.set({
    window: { ...originalWindow, width: 1440, height: 900 },
    screen: { ...originalScreen, width: 1440, height: 900 },
  });

  try {
    await renderCreate(<DraftClearingCreate
      gateway={{
        createFromPrompt: jest.fn(async () => ({
          data: creativeProject(2), error: null, status: 201,
        })),
        createFromDrawing: jest.fn(),
        completeCreativeDirectionReview: jest.fn(),
      } as CreateGateway}
      onGenerationSucceeded={jest.fn()}
      onSave={jest.fn()}
    />);

    await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'Two ring directions.');
    await fireEvent.press(screen.getByLabelText('2 variations'));
    await fireEvent.press(screen.getByText('Generate'));

    expect(await screen.findByLabelText('Direction 2')).toBeTruthy();
    expect(screen.getByLabelText('Design sentence').props.value).toBe('');
    expect(screen.getByLabelText('2 variations').props.accessibilityState).toEqual({
      checked: true,
    });
    expect(screen.getByText('15 credits per variation · 2 variations = 30 credits')).toBeTruthy();
  } finally {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: originalPlatform });
    await act(async () => {
      Dimensions.set({ window: originalWindow, screen: originalScreen });
    });
  }
});

test('resets the variation quantity to one only after clearing review for a new request', async () => {
  const originalPlatform = Platform.OS;
  const originalWindow = Dimensions.get('window');
  const originalScreen = Dimensions.get('screen');
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'web' });
  Dimensions.set({
    window: { ...originalWindow, width: 1440, height: 900 },
    screen: { ...originalScreen, width: 1440, height: 900 },
  });

  try {
    await renderCreate(<DraftClearingCreate
      gateway={{
        createFromPrompt: jest.fn(async () => ({
          data: creativeProject(2), error: null, status: 201,
        })),
        createFromDrawing: jest.fn(),
        completeCreativeDirectionReview: jest.fn(),
      } as CreateGateway}
      onGenerationSucceeded={jest.fn()}
      onSave={jest.fn()}
    />);

    await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'Two ring directions.');
    await fireEvent.press(screen.getByLabelText('2 variations'));
    await fireEvent.press(screen.getByText('Generate'));
    expect(await screen.findByLabelText('Direction 2')).toBeTruthy();

    await fireEvent.press(screen.getByText('Clear canvas'));
    await fireEvent.press(screen.getAllByText('Clear canvas').at(-1)!);

    expect(await screen.findByText('Your designs will appear here.')).toBeTruthy();
    expect(screen.getByLabelText('1 variation').props.accessibilityState).toEqual({ checked: true });
    expect(screen.getByText('15 credits per variation · 1 variation = 15 credits')).toBeTruthy();
    expect(screen.queryByLabelText('Direction 2')).toBeNull();
  } finally {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: originalPlatform });
    await act(async () => {
      Dimensions.set({ window: originalWindow, screen: originalScreen });
    });
  }
});

test('submits one variation by default', async () => {
  const createFromPrompt = jest.fn(async () => ({
    data: creativeProject(1), error: null, status: 201,
  }));
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt, createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    onSave={jest.fn()}
  />);

  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'A simple gold ring.');
  await fireEvent.press(screen.getByText('Generate'));

  await waitFor(() => expect(createFromPrompt).toHaveBeenCalledWith({
    prompt: composeCreateBalanceInstruction('A simple gold ring.', 'symmetrical', false),
    variation_count: 1,
    comparison_views: ['three_quarter'],
    owner: 'designer_1',
    title: 'A simple gold ring.',
  }));
});

test('defaults text-only creation to a compact symmetrical balance choice', async () => {
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    onSave={jest.fn()}
  />);

  expect(screen.getByText('Symmetrical · No extra choices')).toBeTruthy();
  await fireEvent.press(screen.getByLabelText('Optional guidance'));
  const balanceOptions = screen.getByLabelText('Design balance');
  expect(within(balanceOptions).getByLabelText('Symmetrical').props.accessibilityState)
    .toEqual({ checked: true });
  expect(within(balanceOptions).getByLabelText('Asymmetrical').props.accessibilityState)
    .toEqual({ checked: false });
  expect(screen.getByText(/mirrors corresponding design and material details/i)).toBeTruthy();
});

test('threads an explicit asymmetrical choice into text-only creation', async () => {
  const createFromPrompt = jest.fn(async () => ({
    data: creativeProject(1), error: null, status: 201,
  }));
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt, createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    onSave={jest.fn()}
  />);

  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'A ruby collar.');
  await fireEvent.press(screen.getByLabelText('Optional guidance'));
  await fireEvent.press(screen.getByLabelText('Asymmetrical'));
  expect(screen.getByText('Asymmetrical · No extra choices')).toBeTruthy();
  await fireEvent.press(screen.getByText('Generate'));

  await waitFor(() => expect(createFromPrompt).toHaveBeenCalledWith(
    expect.objectContaining({
      prompt: composeCreateBalanceInstruction('A ruby collar.', 'asymmetrical', false),
    }),
  ));
});

test('uses concise loading copy for the default generation request', async () => {
  const originalPlatform = Platform.OS;
  const originalWindow = Dimensions.get('window');
  const originalScreen = Dimensions.get('screen');
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'web' });
  Dimensions.set({
    window: { ...originalWindow, width: 1440, height: 900 },
    screen: { ...originalScreen, width: 1440, height: 900 },
  });
  const pending = deferred<any>();

  try {
    const view = await renderCreate(<StudioCreateWorkspace
      gateway={{
        createFromPrompt: jest.fn(() => pending.promise), createFromDrawing: jest.fn(),
        completeCreativeDirectionReview: jest.fn(),
      } as CreateGateway}
      owner="designer_1"
      onSave={jest.fn()}
    />);

    await fireEvent.changeText(view.getByLabelText('Design sentence'), 'A simple gold ring.');
    let createCompletion!: Promise<void>;
    await act(() => {
      createCompletion = fireEvent.press(view.getByText('Generate'));
    });

    expect(view.getByText('Generating…')).toBeTruthy();
    expect(view.getByText('Generating your design.')).toBeTruthy();
    expect(view.getByText('Facetta is preparing the requested result.')).toBeTruthy();
    expect(view.queryByText(/taking shape/i)).toBeNull();

    await act(async () => {
      pending.resolve({ data: creativeProject(1), error: null, status: 201 });
      await createCompletion;
    });
    await view.unmount();
  } finally {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: originalPlatform });
    await act(async () => {
      Dimensions.set({ window: originalWindow, screen: originalScreen });
    });
  }
});

test('keeps every other previewed direction automatically and recomputes siblings when selection changes', async () => {
  const createFromPrompt = jest.fn(async () => ({
    data: creativeProject(4), error: null, status: 201,
  }));
  const completeCreativeDirectionReview = jest.fn(async ({ selectedCandidateId }) => ({
    data: {
      project: {
        ...creativeProject(4),
        selected_candidate_asset_id: selectedCandidateId,
        active_asset_id: selectedCandidateId,
      },
      retained_variations: [],
    },
    error: null,
    status: 200,
  }));
  const onSave = jest.fn();
  const onGenerationSucceeded = jest.fn();
  await renderCreate(
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test"
      headers={{ Authorization: 'Bearer first-party-token' }}>
      <DraftClearingCreate
        gateway={{
          createFromPrompt, createFromDrawing: jest.fn(), completeCreativeDirectionReview,
        } as CreateGateway}
        onGenerationSucceeded={onGenerationSucceeded}
        onSave={onSave}
      />
    </AuthenticatedImageProvider>,
  );

  expect(screen.queryByText(/factory facts/i)).toBeNull();
  expect(screen.queryByText(/structured specification/i)).toBeNull();
  expect(screen.getByText('How many variations?')).toBeTruthy();
  expect(screen.getByLabelText('Optional guidance').props.accessibilityState)
    .toEqual({ expanded: false });
  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'A sculptural aquamarine collar.');
  await fireEvent.press(screen.getByLabelText('4 variations'));
  expect(screen.getByText('15 credits per variation · 4 variations = 60 credits')).toBeTruthy();
  await fireEvent.press(screen.getByText('Generate'));

  await waitFor(() => expect(createFromPrompt).toHaveBeenCalledWith({
    prompt: composeCreateBalanceInstruction(
      'A sculptural aquamarine collar.', 'symmetrical', false,
    ),
    variation_count: 4,
    comparison_views: ['three_quarter'],
    owner: 'designer_1',
    title: 'A sculptural aquamarine collar.',
  }));
  expect(await screen.findByText('Choose a direction to continue')).toBeTruthy();
  expect(onGenerationSucceeded).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/full generated set stays preserved in this review/i)).toBeTruthy();
  expect(screen.queryByLabelText('Keep all other directions')).toBeNull();
  expect(screen.queryByLabelText('Only keep my Original')).toBeNull();
  expect(screen.queryByLabelText('Choose directions individually')).toBeNull();
  expect(screen.getByText('Start over')).toBeTruthy();
  expect(screen.getByLabelText('Direction 1 preview').props.source.headers).toEqual({
    Authorization: 'Bearer first-party-token',
  });
  expect(screen.getByText(/visual directions.+not measurements or production instructions/i)).toBeTruthy();
  expect(screen.getByText('Save & refine Direction 1')).toBeTruthy();
  expect(within(screen.getByLabelText('Direction 2')).getByText('Enlarge')).toBeTruthy();
  expect(completeCreativeDirectionReview).not.toHaveBeenCalled();
  expect(onSave).not.toHaveBeenCalled();
  await loadDirection(1);
  await loadDirection(2);
  await loadDirection(3);
  await loadDirection(4);
  await fireEvent.press(screen.getByLabelText('Inspect Direction 2 in detail'));
  expect(screen.getByLabelText('Close image inspector')).toBeTruthy();
  expect(screen.getByLabelText('Direction 1').props.accessibilityState.checked).toBe(true);
  await fireEvent.press(screen.getByLabelText('Close image inspector'));
  await fireEvent.press(screen.getByLabelText('Direction 3'));
  expect(screen.getByText('Save & refine Direction 3')).toBeTruthy();
  expect(screen.queryByLabelText('Close image inspector')).toBeNull();
  expect(within(screen.getByLabelText('Direction 1')).getByText('Will save as a variation'))
    .toBeTruthy();
  expect(screen.getByLabelText('Direction 1').props.accessibilityHint)
    .toBe('Will save as a variation');
  expect(within(screen.getByLabelText('Direction 3')).getByText('Selected to refine'))
    .toBeTruthy();
  await loadDirection(3);
  await fireEvent.press(screen.getByText('Save & refine Direction 3'));
  await waitFor(() => expect(completeCreativeDirectionReview).toHaveBeenCalledTimes(1));
  expect(completeCreativeDirectionReview).toHaveBeenCalledWith({
    projectId: 'project_1', selectedCandidateId: 'candidate_3',
    retained: [
      { candidateId: 'candidate_1', label: 'Direction 1' },
      { candidateId: 'candidate_2', label: 'Direction 2' },
      { candidateId: 'candidate_4', label: 'Direction 4' },
    ],
    createdBy: 'designer_1',
  });
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    selectedAssetId: 'candidate_3',
  }));
  expect(onSave.mock.calls[0][0]).not.toHaveProperty('sentence');
  expect(onSave.mock.calls[0][0]).not.toHaveProperty('references');
});

test('selects Direction 2 without enlarging it and keeps enlargement an explicit separate action', async () => {
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    resumeProject={creativeProject(2)}
    onSave={jest.fn()}
  />);

  expect(screen.getByLabelText('Direction 1').props.accessibilityState.checked).toBe(true);
  expect(screen.getByLabelText('Direction 2').props.accessibilityState.checked).toBe(false);
  expect(within(screen.getByLabelText('Direction 1')).getByText('✓ Selected')).toBeTruthy();

  await fireEvent.press(screen.getByLabelText('Direction 2'));

  expect(screen.getByLabelText('Direction 1').props.accessibilityState.checked).toBe(false);
  expect(screen.getByLabelText('Direction 2').props.accessibilityState.checked).toBe(true);
  expect(within(screen.getByLabelText('Direction 2')).getByText('✓ Selected')).toBeTruthy();
  expect(within(screen.getByLabelText('Direction 1')).queryByText('✓ Selected')).toBeNull();
  expect(screen.getByText('Save & refine Direction 2')).toBeTruthy();
  expect(screen.queryByText('DETAIL INSPECTION')).toBeNull();

  await fireEvent.press(screen.getByLabelText('Direction 2 preview'));
  expect(screen.queryByText('DETAIL INSPECTION')).toBeNull();
  expect(screen.getByLabelText('Direction 2').props.accessibilityState.checked).toBe(true);

  await fireEvent.press(screen.getByLabelText('Inspect Direction 2 in detail'));
  expect(screen.getByText('DETAIL INSPECTION')).toBeTruthy();
  expect(screen.getByLabelText('Direction 2').props.accessibilityState.checked).toBe(true);
});

test('requires confirmation before clearing a review and keeps it after cancellation', async () => {
  const gateway = {
    createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
    completeCreativeDirectionReview: jest.fn(),
  } as CreateGateway;
  await renderCreate(<StudioCreateWorkspace
    gateway={gateway}
    owner="designer_1"
    resumeProject={creativeProject(2)}
    onSave={jest.fn()}
  />);

  await fireEvent.press(screen.getByLabelText('Direction 2'));
  await fireEvent.press(screen.getByText('Start over'));
  expect(screen.getByText('Clear these results?')).toBeTruthy();
  expect(gateway.completeCreativeDirectionReview).not.toHaveBeenCalled();

  await fireEvent.press(screen.getByText('Keep results'));
  expect(screen.queryByText('Clear these results?')).toBeNull();
  expect(screen.getByLabelText('Direction 2').props.accessibilityState.checked).toBe(true);

  await fireEvent.press(screen.getByText('Start over'));
  await fireEvent.press(screen.getByText('Clear canvas'));
  expect(screen.queryByLabelText('Direction 2')).toBeNull();
  expect(screen.getByLabelText('Design sentence')).toBeTruthy();
  expect(gateway.completeCreativeDirectionReview).not.toHaveBeenCalled();
});

test('does not expose retention administration during direction selection', async () => {
  const completeCreativeDirectionReview = jest.fn(async ({ selectedCandidateId }) => ({
    data: {
      project: {
        ...creativeProject(3),
        selected_candidate_asset_id: selectedCandidateId,
        active_asset_id: selectedCandidateId,
      },
      retained_variations: [],
    },
    error: null,
    status: 200,
  }));
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview,
    } as CreateGateway}
    owner="designer_1"
    resumeProject={creativeProject(3)}
    onSave={jest.fn()}
  />);

  expect(screen.queryByLabelText('Keep all other directions')).toBeNull();
  expect(screen.queryByLabelText('Only keep my Original')).toBeNull();
  expect(screen.queryByLabelText('Choose directions individually')).toBeNull();
  await loadDirection(1);
  await loadDirection(2);
  await loadDirection(3);
  await fireEvent.press(screen.getByText('Save & refine Direction 1'));

  await waitFor(() => expect(completeCreativeDirectionReview).toHaveBeenCalledWith({
    projectId: 'project_1', selectedCandidateId: 'candidate_1', retained: [
      { candidateId: 'candidate_2', label: 'Direction 2' },
      { candidateId: 'candidate_3', label: 'Direction 3' },
    ],
    createdBy: 'designer_1',
  }));
});

test('an unavailable unselected preview does not block a loaded selected direction', async () => {
  const completeCreativeDirectionReview = jest.fn(async ({ selectedCandidateId }) => ({
    data: {
      project: {
        ...creativeProject(3),
        selected_candidate_asset_id: selectedCandidateId,
        active_asset_id: selectedCandidateId,
      },
      retained_variations: [],
    },
    error: null,
    status: 200,
  }));
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview,
    } as CreateGateway}
    owner="designer_1"
    resumeProject={creativeProject(3)}
    onSave={jest.fn()}
  />);

  await loadDirection(1);
  await act(async () => {
    fireEvent(screen.getByLabelText('Direction 2 preview'), 'error');
  });
  await loadDirection(3);
  expect(screen.queryByText(/could not be displayed/i)).toBeNull();
  const continueButton = screen.getByText('Save & refine Direction 1');
  expect(continueButton.parent?.props.accessibilityState.disabled).toBe(false);
  await fireEvent.press(continueButton);

  await waitFor(() => expect(completeCreativeDirectionReview).toHaveBeenCalledWith({
    projectId: 'project_1', selectedCandidateId: 'candidate_1',
    retained: [{ candidateId: 'candidate_3', label: 'Direction 3' }],
    createdBy: 'designer_1',
  }));
});

test('legacy review sets retain at most three previewed siblings without blocking selection', async () => {
  const completeCreativeDirectionReview = jest.fn(async ({ selectedCandidateId }) => ({
    data: {
      project: {
        ...creativeProject(6),
        selected_candidate_asset_id: selectedCandidateId,
        active_asset_id: selectedCandidateId,
      },
      retained_variations: [],
    },
    error: null,
    status: 200,
  }));
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview,
    } as CreateGateway}
    owner="designer_1"
    resumeProject={creativeProject(6)}
    onSave={jest.fn()}
  />);

  for (let index = 1; index <= 6; index += 1) await loadDirection(index);
  expect(within(screen.getByLabelText('Direction 5')).getByText('Preserved in review set'))
    .toBeTruthy();
  expect(within(screen.getByLabelText('Direction 6')).getByText('Preserved in review set'))
    .toBeTruthy();
  expect(screen.getByLabelText('Direction 4').props.accessibilityHint)
    .toBe('Will save as a variation');
  expect(screen.getByLabelText('Direction 5').props.accessibilityHint)
    .toBe('Preserved in review set');
  await fireEvent.press(screen.getByText('Save & refine Direction 1'));

  await waitFor(() => expect(completeCreativeDirectionReview).toHaveBeenCalledWith({
    projectId: 'project_1', selectedCandidateId: 'candidate_1', retained: [
      { candidateId: 'candidate_2', label: 'Direction 2' },
      { candidateId: 'candidate_3', label: 'Direction 3' },
      { candidateId: 'candidate_4', label: 'Direction 4' },
    ],
    createdBy: 'designer_1',
  }));
});

test('a deferred generation clears only its exact submitted draft', async () => {
  const pending = deferred<any>();
  const onGenerationSucceeded = jest.fn();
  await renderCreate(<DraftClearingCreate
    gateway={{
      createFromPrompt: jest.fn(() => pending.promise),
      createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    onGenerationSucceeded={onGenerationSucceeded}
    onSave={jest.fn()}
  />);

  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'First submitted direction.');
  let createCompletion!: Promise<void>;
  await act(() => {
    createCompletion = fireEvent.press(screen.getByText('Generate'));
  });
  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'A newer unsent direction.');
  await act(async () => {
    pending.resolve({ data: creativeProject(1), error: null, status: 201 });
    await createCompletion;
  });

  expect(await screen.findByText('Choose a direction to continue')).toBeTruthy();
  expect(onGenerationSucceeded).toHaveBeenCalledWith(expect.objectContaining({
    owner: 'designer_1',
    projectId: 'project_1',
    submittedDraft: expect.objectContaining({ sentence: 'First submitted direction.' }),
  }));
  await fireEvent.press(screen.getByText('Start over'));
  await fireEvent.press(screen.getByText('Clear canvas'));
  expect(screen.getByLabelText('Design sentence').props.value).toBe('A newer unsent direction.');
});

test('a generation resolving after unmount cannot reset parent Create state', async () => {
  const pending = deferred<any>();
  const onGenerationSucceeded = jest.fn();
  const view = await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(() => pending.promise),
      createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    onGenerationSucceeded={onGenerationSucceeded}
    onSave={jest.fn()}
  />);

  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'Direction before navigation.');
  let createCompletion!: Promise<void>;
  await act(() => {
    createCompletion = fireEvent.press(screen.getByText('Generate'));
  });
  await view.unmount();
  await act(async () => {
    pending.resolve({ data: creativeProject(1), error: null, status: 201 });
    await createCompletion;
  });

  expect(onGenerationSucceeded).not.toHaveBeenCalled();
});

test('a deferred direction commit cannot navigate after its review unmounts', async () => {
  const pending = deferred<any>();
  const onSave = jest.fn();
  const view = await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(),
      createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(() => pending.promise),
    } as CreateGateway}
    owner="designer_1"
    resumeProject={creativeProject(1)}
    onSave={onSave}
  />);

  await loadDirection(1);
  let commitCompletion!: Promise<void>;
  await act(() => {
    commitCompletion = fireEvent.press(screen.getByText('Save & refine Direction 1'));
  });
  expect(screen.getByText('Start over').parent?.props.accessibilityState)
    .toEqual({ disabled: true });
  expect(screen.getByLabelText('Direction 1').props.accessibilityState)
    .toEqual({ checked: true, disabled: true });
  await view.unmount();
  await act(async () => {
    pending.resolve({
      data: {
        project: { ...creativeProject(1), active_asset_id: 'candidate_1' },
        retained_variations: [],
      },
      error: null,
      status: 200,
    });
    await commitCompletion;
  });

  expect(onSave).not.toHaveBeenCalled();
});

test('a deferred direction commit cannot save into a new owner session', async () => {
  const pending = deferred<any>();
  const onSave = jest.fn();
  const gateway = {
    createFromPrompt: jest.fn(),
    createFromDrawing: jest.fn(),
    completeCreativeDirectionReview: jest.fn(() => pending.promise),
  } as CreateGateway;
  const review = (owner: string) => (
    <AuthenticatedImageProvider
      allowedOrigin="https://facetta.test"
      headers={{ Authorization: 'Bearer first-party-token' }}>
      <StudioCreateWorkspace
        gateway={gateway}
        owner={owner}
        resumeProject={creativeProject(1)}
        onSave={onSave}
      />
    </AuthenticatedImageProvider>
  );
  const view = await render(review('designer_1'));

  await loadDirection(1);
  let commitCompletion!: Promise<void>;
  await act(() => {
    commitCompletion = fireEvent.press(screen.getByText('Save & refine Direction 1'));
  });
  await view.rerender(review('designer_2'));
  await act(async () => {
    pending.resolve({
      data: {
        project: { ...creativeProject(1), active_asset_id: 'candidate_1' },
        retained_variations: [],
      },
      error: null,
      status: 200,
    });
    await commitCompletion;
  });

  expect(onSave).not.toHaveBeenCalled();
});

test('reopens a durable reviewing Create job with automatic sibling retention', async () => {
  const createFromPrompt = jest.fn();
  const createFromDrawing = jest.fn();
  const completeCreativeDirectionReview = jest.fn(async ({ selectedCandidateId }) => ({
    data: {
      project: {
        ...creativeProject(3),
        selected_candidate_asset_id: selectedCandidateId,
        active_asset_id: selectedCandidateId,
      },
      retained_variations: [],
    },
    error: null,
    status: 200,
  }));
  const onSave = jest.fn();
  await renderCreate(
    <StudioCreateWorkspace
      gateway={{
        createFromPrompt, createFromDrawing, completeCreativeDirectionReview,
      } as CreateGateway}
      owner="designer_1"
      resumeProject={creativeProject(3)}
      resumeStudioJobId="studio_job_create"
      onSave={onSave}
    />,
  );

  expect(await screen.findByText('Choose a direction to continue')).toBeTruthy();
  expect(createFromPrompt).not.toHaveBeenCalled();
  expect(createFromDrawing).not.toHaveBeenCalled();
  await loadDirection(1);
  await loadDirection(2);
  await loadDirection(3);
  await fireEvent.press(screen.getByLabelText('Direction 2'));
  await fireEvent.press(screen.getByText('Save & refine Direction 2'));
  await waitFor(() => expect(completeCreativeDirectionReview).toHaveBeenCalledWith({
    projectId: 'project_1', selectedCandidateId: 'candidate_2', retained: [
      { candidateId: 'candidate_1', label: 'Direction 1' },
      { candidateId: 'candidate_3', label: 'Direction 3' },
    ],
    createdBy: 'designer_1', studioJobId: 'studio_job_create',
  }));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    selectedAssetId: 'candidate_2',
  }));
  expect(Object.keys(onSave.mock.calls[0][0]).sort()).toEqual(['project', 'selectedAssetId']);
  expect(onSave.mock.calls[0][0].project.active_asset_id).toBe('candidate_2');
});

test('saves the selected direction for later without opening the refine callback', async () => {
  const completeCreativeDirectionReview = jest.fn(async ({ selectedCandidateId }) => ({
    data: {
      project: {
        ...creativeProject(2),
        selected_candidate_asset_id: selectedCandidateId,
        active_asset_id: selectedCandidateId,
      },
      retained_variations: [],
    },
    error: null,
    status: 200,
  }));
  const onSave = jest.fn();
  const onSaveForLater = jest.fn();

  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview,
    } as CreateGateway}
    owner="designer_1"
    resumeProject={creativeProject(2)}
    onSave={onSave}
    onSaveForLater={onSaveForLater}
  />);

  await loadDirection(1);
  await loadDirection(2);
  await fireEvent.press(screen.getByLabelText('Direction 2'));
  await fireEvent.press(screen.getByText('Save for later'));

  await waitFor(() => expect(onSaveForLater).toHaveBeenCalledWith(expect.objectContaining({
    selectedAssetId: 'candidate_2',
  })));
  expect(completeCreativeDirectionReview).toHaveBeenCalledTimes(1);
  expect(onSave).not.toHaveBeenCalled();
});

test('switches every direction through the same paired comparison angle', async () => {
  const project = creativeProject(2);
  const candidatesWithViews = project.creative_candidates!.map((item, index) => ({
    ...item,
    views: [
      {
        asset_id: item.asset_id,
        view: 'primary' as const,
        media_type: 'image/png',
        sha256: `primary-${index}`,
        image_url: item.image_url!,
      },
      {
        asset_id: `${item.asset_id}_three_quarter`,
        view: 'three_quarter' as const,
        media_type: 'image/png',
        sha256: `three-quarter-${index}`,
        image_url: `https://facetta.test/candidate-${index + 1}-three-quarter.png`,
      },
    ],
  }));
  project.creative_candidates = candidatesWithViews;
  project.assets = candidatesWithViews;

  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    resumeProject={project}
    onSave={jest.fn()}
  />);

  expect(screen.getByText('Compare every direction in the same view')).toBeTruthy();
  expect(screen.getByLabelText('Main view').props.accessibilityState.checked).toBe(true);
  expect(screen.getByLabelText('Direction 1 preview').props.source.uri).toBe(
    'https://facetta.test/candidate-1.png',
  );
  expect(screen.getByLabelText('Direction 2 preview').props.source.uri).toBe(
    'https://facetta.test/candidate-2.png',
  );

  await fireEvent.press(screen.getByLabelText('3/4 view'));

  expect(screen.getByLabelText('Direction 1 preview').props.source.uri).toBe(
    'https://facetta.test/candidate-1-three-quarter.png',
  );
  expect(screen.getByLabelText('Direction 2 preview').props.source.uri).toBe(
    'https://facetta.test/candidate-2-three-quarter.png',
  );
});

test('does not offer a mismatched angle comparison when one direction lacks the shared slot', async () => {
  const project = creativeProject(2);
  project.creative_candidates = project.creative_candidates!.map((item, index) => ({
    ...item,
    views: index === 0 ? [{
      asset_id: `${item.asset_id}_three_quarter`,
      view: 'three_quarter' as const,
      media_type: 'image/png',
      sha256: 'three-quarter-only-first',
      image_url: 'https://facetta.test/candidate-1-three-quarter.png',
    }] : [],
  }));
  project.assets = [...project.creative_candidates];

  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    resumeProject={project}
    onSave={jest.fn()}
  />);

  expect(screen.queryByText('Compare every direction in the same view')).toBeNull();
  expect(screen.queryByLabelText('3/4 view')).toBeNull();
  expect(screen.getByLabelText('Direction 1 preview').props.source.uri).toBe(
    'https://facetta.test/candidate-1.png',
  );
  expect(screen.getByLabelText('Direction 2 preview').props.source.uri).toBe(
    'https://facetta.test/candidate-2.png',
  );
});

test('does not create an immutable revision until its selected preview renders', async () => {
  const completeCreativeDirectionReview = jest.fn(async () => ({
    data: { project: creativeProject(1), retained_variations: [] },
    error: null,
    status: 200,
  }));
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview,
    } as CreateGateway}
    owner="designer_1"
    resumeProject={creativeProject(1)}
    onSave={jest.fn()}
  />);

  const continueButton = screen.getByText('Save & refine Direction 1');
  expect(continueButton.parent?.props.accessibilityState.disabled).toBe(true);
  fireEvent.press(continueButton);
  expect(completeCreativeDirectionReview).not.toHaveBeenCalled();

  await act(async () => {
    fireEvent(screen.getByLabelText('Direction 1 preview'), 'error');
  });
  expect(screen.getByText(/selected direction could not be displayed/i)).toBeTruthy();
  fireEvent.press(continueButton);
  expect(completeCreativeDirectionReview).not.toHaveBeenCalled();

  await loadDirection(1);
  await act(async () => {
    fireEvent.press(screen.getByText('Save & refine Direction 1'));
  });
  await waitFor(() => expect(completeCreativeDirectionReview).toHaveBeenCalledTimes(1));
});

test('keeps the complete review staged after an atomic commit error and retries the same decision', async () => {
  const completedProject = {
    ...creativeProject(3),
    selected_candidate_asset_id: 'candidate_3',
    active_asset_id: 'candidate_3',
  };
  const completeCreativeDirectionReview = jest.fn()
    .mockResolvedValueOnce({
      data: null,
      error: {
        code: 'NETWORK_ERROR', category: 'network', status: 0,
        message: 'Connection lost before the response.', retryable: true,
      },
      status: 0,
    })
    .mockResolvedValueOnce({
      data: { project: completedProject, retained_variations: [] },
      error: null,
      status: 200,
    });
  const onSave = jest.fn();
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview,
    } as CreateGateway}
    owner="designer_1"
    resumeProject={creativeProject(3)}
    resumeStudioJobId="studio_job_create"
    onSave={onSave}
  />);

  await loadDirection(3);
  await fireEvent.press(screen.getByLabelText('Direction 3'));
  const continueLabel = 'Save & refine Direction 3';
  await fireEvent.press(screen.getByText(continueLabel));

  await waitFor(() => expect(completeCreativeDirectionReview).toHaveBeenCalledTimes(1));
  expect(onSave).not.toHaveBeenCalled();
  expect(await screen.findByText(continueLabel)).toBeTruthy();

  await fireEvent.press(screen.getByText(continueLabel));
  await waitFor(() => expect(completeCreativeDirectionReview).toHaveBeenCalledTimes(2));
  expect(completeCreativeDirectionReview.mock.calls[0]).toEqual(
    completeCreativeDirectionReview.mock.calls[1],
  );
  expect(onSave).toHaveBeenCalledTimes(1);
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    project: completedProject,
    selectedAssetId: 'candidate_3',
  }));
});

test('starting another brief clears the previous review error and collapses advanced setup', async () => {
  const createFromPrompt = jest.fn(async () => ({
    data: creativeProject(1), error: null, status: 201,
  }));
  const completeCreativeDirectionReview = jest.fn(async () => ({
    data: null,
    error: {
      code: 'NETWORK_ERROR', category: 'network', status: 0,
      message: 'Connection lost before the response.', retryable: true,
    },
    status: 0,
  }));
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt, createFromDrawing: jest.fn(), completeCreativeDirectionReview,
    } as CreateGateway}
    owner="designer_1"
    initialSentence="First direction"
    onSave={jest.fn()}
  />);

  await fireEvent.press(screen.getByLabelText('Optional guidance'));
  expect(screen.getAllByText('Optional guidance')).toHaveLength(1);
  await fireEvent.press(screen.getByText('Generate'));
  await loadDirection(1);
  await fireEvent.press(screen.getByText('Save & refine Direction 1'));
  expect(await screen.findByText('Facetta could not connect. Check your connection and try again.'))
    .toBeTruthy();

  await fireEvent.press(screen.getByText('Start over'));
  expect(screen.getByText('Clear these results?')).toBeTruthy();
  await fireEvent.press(screen.getByText('Clear canvas'));

  expect(screen.queryByText('Facetta could not connect. Check your connection and try again.'))
    .toBeNull();
  expect(screen.getAllByText('Optional guidance')).toHaveLength(1);
  expect(screen.getByLabelText('Optional guidance').props.accessibilityState)
    .toEqual({ expanded: false });
});

test('keeps an already-created direction set when the designer starts another brief', async () => {
  const createFromPrompt = jest.fn(async () => ({
    data: creativeProject(2), error: null, status: 201,
  }));
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt, createFromDrawing: jest.fn(), completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    initialSentence="First direction"
    onSave={jest.fn()}
  />);

  await fireEvent.press(screen.getByLabelText('2 variations'));
  await fireEvent.press(screen.getByText('Generate'));
  expect(await screen.findByText(/full generated set stays preserved in this review/i)).toBeTruthy();
  await loadDirection(1);
  expect(screen.getByText('Save & refine Direction 1')).toBeTruthy();
  await fireEvent.press(screen.getByText('Start over'));
  await fireEvent.press(screen.getByText('Clear canvas'));
  expect(await screen.findByLabelText('Design sentence')).toBeTruthy();
  expect(screen.queryByText(/full generated set stays preserved in this review/i)).toBeNull();
  await fireEvent.press(screen.getByText('Generate'));
  await loadDirection(1);
  expect(await screen.findByText('Save & refine Direction 1')).toBeTruthy();
  expect(screen.queryByLabelText('Keep all other directions')).toBeNull();
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
    data: creativeProject(1), error: null, status: 201,
  }));
  const createFromPrompt = jest.fn();
  const onRequestReference = jest.fn(async (role) => role === 'master_geometry' ? master : material);
  await renderCreate(React.createElement(StudioCreateWorkspace, {
    gateway: {
      createFromPrompt,
      createFromDrawing: createProjectFromDrawing,
      completeCreativeDirectionReview: jest.fn(),
    } as unknown as CreateGateway,
    owner: 'designer_1',
    onRequestReference,
    onSave: jest.fn(),
  }));

  await fireEvent.press(screen.getByText('Add a rough sketch, photo, or render'));
  expect(screen.getByText('What did you upload?')).toBeTruthy();
  await loadReferencePreview('Visual source preview');
  await fireEvent.changeText(
    screen.getByLabelText('Design sentence'),
    'Preserve the silhouette and make it feel lighter.',
  );
  expect(screen.getByText('Generate').parent?.props.accessibilityState).toEqual({ disabled: true });
  expect(screen.getByText('Drawing').parent?.props.accessibilityState).toEqual({ checked: false });
  expect(screen.getByText('Photograph').parent?.props.accessibilityState).toEqual({ checked: false });
  expect(screen.getByText('Finished render').parent?.props.accessibilityState).toEqual({ checked: false });
  await fireEvent.press(screen.getByText('Drawing'));
  await fireEvent.press(screen.getByLabelText('Optional guidance'));
  await fireEvent.press(screen.getByLabelText('Material & finish options'));
  await fireEvent.press(screen.getByLabelText('Add image for Material & finish'));

  expect(screen.getByText('Generate').parent?.props.accessibilityState).toEqual({ disabled: true });
  expect(screen.getByText('Checking attached references before creation…')).toBeTruthy();
  expect(screen.getByLabelText('Visual source preview').props.source.uri).toBe(
    'data:image/png;base64,bWFzdGVy',
  );
  expect(screen.getByLabelText('Material & finish reference preview').props.source.uri).toBe(
    'data:image/jpeg;base64,bWF0ZXJpYWw=',
  );

  await fireEvent.press(screen.getByLabelText('Inspect Master geometry · Front sketch in detail'));
  expect(screen.getByText('Master geometry · Front sketch')).toBeTruthy();
  await fireEvent.press(screen.getByLabelText('Zoom image to 4x'));
  expect(screen.getByLabelText('Zoom image to 4x').props.accessibilityState).toEqual({ selected: true });
  expect(createProjectFromDrawing).not.toHaveBeenCalled();
  await fireEvent.press(screen.getByLabelText('Close image inspector'));

  await fireEvent.press(screen.getByLabelText('Inspect Material & finish · Brushed gold reference in detail'));
  expect(screen.getByText('Material & finish · Brushed gold reference')).toBeTruthy();
  await fireEvent.press(screen.getByLabelText('Close image inspector'));
  expect(createProjectFromDrawing).not.toHaveBeenCalled();

  await loadReferencePreview('Material & finish reference preview');
  expect(screen.getByText('Generate').parent?.props.accessibilityState).toEqual({ disabled: false });
  await fireEvent.press(screen.getByText('Generate'));

  await waitFor(() => expect(createProjectFromDrawing).toHaveBeenCalledWith({
    image_base64: 'bWFzdGVy',
    source_kind: 'drawing',
    media_type: 'image/png',
    instruction: composeCreateBalanceInstruction(
      'Preserve the silhouette and make it feel lighter.', 'symmetrical', true,
    ),
    references: [{
      role: 'material_style',
      image_base64: 'bWF0ZXJpYWw=',
      media_type: 'image/jpeg',
    }],
    variation_count: 1,
    comparison_views: ['three_quarter'],
    owner: 'designer_1',
    title: 'Preserve the silhouette and make it feel lighter.',
  }));
  expect(createFromPrompt).not.toHaveBeenCalled();
  expect(screen.queryByText(/Reference limit|cannot send|remain labeled/i)).toBeNull();
});

test('accepts role-labeled advisory guidance after a sentence without requiring a master', async () => {
  const material: StudioCreateReference = {
    id: 'material', role: 'material_style', label: 'Hammered gold reference',
    imageBase64: 'bWF0ZXJpYWw=', mediaType: 'image/jpeg',
  };
  const createFromPrompt = jest.fn(async () => ({
    data: creativeProject(1), error: null, status: 201,
  }));
  const createFromDrawing = jest.fn();
  const onRequestReference = jest.fn(async () => material);
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt, createFromDrawing, completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    onRequestReference={onRequestReference}
    onSave={jest.fn()}
  />);

  await fireEvent.press(screen.getByLabelText('Optional guidance'));
  await fireEvent.press(screen.getByLabelText('Material & finish options'));
  const addMaterial = screen.getByLabelText('Add image for Material & finish');
  expect(addMaterial.props.accessibilityState?.disabled).not.toBe(true);
  expect(screen.getByText('Symmetrical · No extra choices')).toBeTruthy();

  await fireEvent.changeText(
    screen.getByLabelText('Design sentence'),
    'A broad sculptural gold cuff with one clean opening.',
  );
  await fireEvent.press(screen.getByLabelText('Add image for Material & finish'));
  expect(onRequestReference).toHaveBeenCalledWith('material_style');
  expect(screen.getByText('Symmetrical · 1 extra choice')).toBeTruthy();
  expect(screen.queryByText('Master geometry required')).toBeNull();
  expect(screen.queryByText('Add a design idea')).toBeNull();
  expect(screen.getByText('Generate').parent?.props.accessibilityState).toEqual({ disabled: true });

  await loadReferencePreview('Material & finish reference preview');
  await fireEvent.press(screen.getByText('Generate'));
  await waitFor(() => expect(createFromPrompt).toHaveBeenCalledWith({
    prompt: composeCreateBalanceInstruction(
      'A broad sculptural gold cuff with one clean opening.', 'symmetrical', false,
    ),
    references: [{
      role: 'material_style',
      image_base64: 'bWF0ZXJpYWw=',
      media_type: 'image/jpeg',
    }],
    variation_count: 1,
    comparison_views: ['three_quarter'],
    owner: 'designer_1',
    title: 'A broad sculptural gold cuff with one clean opening.',
  }));
  expect(createFromDrawing).not.toHaveBeenCalled();
});

test('rejects an advisory-only setup until the designer supplies a sentence or master', async () => {
  const material: StudioCreateReference = {
    id: 'material', role: 'material_style', label: 'Hammered gold reference',
    imageBase64: 'bWF0ZXJpYWw=', mediaType: 'image/jpeg',
  };
  const createFromPrompt = jest.fn();
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt, createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    initialReferences={[material]}
    onSave={jest.fn()}
  />);

  await fireEvent.press(screen.getByLabelText('Material & finish options'));
  await loadReferencePreview('Material & finish reference preview');
  expect(screen.getByText('Symmetrical · 1 extra choice')).toBeTruthy();
  expect(screen.getByText('Add a design idea')).toBeTruthy();
  expect(screen.getByText(
    'Optional guidance can shape material, details, or mood after you add a design sentence or one visual source. It does not define the jewelry on its own.',
  )).toBeTruthy();
  expect(screen.queryByText('Master geometry required')).toBeNull();
  expect(screen.getByText('Generate').parent?.props.accessibilityState).toEqual({
    disabled: true,
  });
  await fireEvent.press(screen.getByText('Generate'));
  expect(createFromPrompt).not.toHaveBeenCalled();
});

test('starts from a master image without forcing a sentence', async () => {
  const master: StudioCreateReference = {
    id: 'master', role: 'master_geometry', label: 'Pendant photograph',
    imageBase64: 'bWFzdGVy', mediaType: 'image/png', sourceKind: 'photograph',
  };
  const createFromDrawing = jest.fn(async () => ({
    data: creativeProject(1), error: null, status: 201,
  }));
  await renderCreate(React.createElement(StudioCreateWorkspace, {
    gateway: {
      createFromPrompt: jest.fn(), createFromDrawing,
      completeCreativeDirectionReview: jest.fn(),
    } as unknown as CreateGateway,
    owner: 'designer_1',
    initialReferences: [master],
    onSave: jest.fn(),
  }));

  expect(screen.getByLabelText('Visual source preview').props.source.uri).toBe(
    'data:image/png;base64,bWFzdGVy',
  );
  expect(screen.getByLabelText('Replace visual source')).toBeTruthy();
  expect(screen.getByText('Preserve source balance · No extra choices')).toBeTruthy();
  expect(screen.getByText('Preserve source balance')).toBeTruthy();
  expect(screen.getByText(/follows the uploaded design.+symmetrical or intentionally asymmetrical/i))
    .toBeTruthy();
  expect(screen.queryByLabelText('Design balance')).toBeNull();
  expect(screen.getByText(
    'A sentence is optional. Facetta will preserve the photographed piece and turn it into a polished design render.',
  )).toBeTruthy();
  expect(screen.getByText('Generate').parent?.props.accessibilityState).toEqual({ disabled: true });
  await loadReferencePreview('Visual source preview');
  await fireEvent.press(screen.getByText('Generate'));
  await waitFor(() => expect(createFromDrawing).toHaveBeenCalledWith({
    image_base64: 'bWFzdGVy',
    source_kind: 'photograph',
    media_type: 'image/png',
    instruction: composeCreateBalanceInstruction(
      uploadOnlyInstruction('photograph'), 'symmetrical', true,
    ),
    references: [],
    variation_count: 1,
    comparison_views: ['three_quarter'],
    owner: 'designer_1',
    title: 'Pendant photograph',
  }));
});

test('fails closed when an attached reference cannot render', async () => {
  const master: StudioCreateReference = {
    id: 'master-failed', role: 'master_geometry', label: 'Unreadable sketch',
    imageBase64: 'ZmFpbGVk', mediaType: 'image/png', sourceKind: 'drawing',
  };
  const createFromDrawing = jest.fn();
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing,
      completeCreativeDirectionReview: jest.fn(),
    } as unknown as CreateGateway}
    owner="designer_1"
    initialReferences={[master]}
    onSave={jest.fn()}
  />);

  await act(async () => {
    fireEvent(screen.getByLabelText('Visual source preview'), 'error');
  });

  expect(screen.getByText(
    'A reference preview could not be shown. Replace or remove it before creating directions.',
  )).toBeTruthy();
  expect(screen.getByText('Generate').parent?.props.accessibilityState).toEqual({ disabled: true });
  await fireEvent.press(screen.getByText('Generate'));
  expect(createFromDrawing).not.toHaveBeenCalled();
});

test('surfaces picker failures instead of leaving Add as a silent dead end', async () => {
  const onRequestReference = jest.fn(async () => {
    throw new Error('Choose a PNG, JPEG, or WebP image. Other file types are not supported.');
  });
  await renderCreate(React.createElement(StudioCreateWorkspace, {
    gateway: {
      createFromPrompt: jest.fn(),
      createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as unknown as CreateGateway,
    owner: 'designer_1',
    onRequestReference,
    onSave: jest.fn(),
  }));

  await fireEvent.press(screen.getByText('Add a rough sketch, photo, or render'));

  expect(await screen.findByText(/Choose a PNG, JPEG, or WebP image/)).toBeTruthy();
  expect(onRequestReference).toHaveBeenCalledWith('master_geometry');
});

test('the latest deferred picker merges into the current controlled draft', async () => {
  const first = deferred<StudioCreateReference | null>();
  const second = deferred<StudioCreateReference | null>();
  const onRequestReference = jest.fn()
    .mockImplementationOnce(() => first.promise)
    .mockImplementationOnce(() => second.promise);
  function ControlledPickerCreate() {
    const [draft, setDraft] = React.useState<StudioCreateDraft>(EMPTY_STUDIO_CREATE_DRAFT);
    return <StudioCreateWorkspace
      gateway={{
        createFromPrompt: jest.fn(),
        createFromDrawing: jest.fn(),
        completeCreativeDirectionReview: jest.fn(),
      } as unknown as CreateGateway}
      owner="designer_1"
      draft={draft}
      onDraftChange={setDraft}
      onRequestReference={onRequestReference}
      onSave={jest.fn()}
    />;
  }
  await renderCreate(<ControlledPickerCreate />);

  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'Original sentence.');
  let firstCompletion!: Promise<void>;
  let secondCompletion!: Promise<void>;
  await act(() => {
    firstCompletion = fireEvent.press(screen.getByText('Add a rough sketch, photo, or render'));
  });
  await act(() => {
    secondCompletion = fireEvent.press(screen.getByText('Add a rough sketch, photo, or render'));
  });
  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'Newer sentence.');
  await act(async () => {
    first.resolve({
      id: 'stale', role: 'master_geometry', label: 'Stale sketch.png',
      imageBase64: 'c3RhbGU=', mediaType: 'image/png', sourceKind: 'drawing',
    });
    await firstCompletion;
  });
  expect(screen.queryByText('Stale sketch.png')).toBeNull();

  await act(async () => {
    second.resolve({
      id: 'current', role: 'master_geometry', label: 'Current sketch.png',
      imageBase64: 'Y3VycmVudA==', mediaType: 'image/png', sourceKind: 'drawing',
    });
    await secondCompletion;
  });
  expect(screen.getByText('Current sketch.png')).toBeTruthy();
  expect(screen.getByLabelText('Design sentence').props.value).toBe('Newer sentence.');
});

test('a picker resolving after unmount cannot write to its former controlled owner', async () => {
  const pending = deferred<StudioCreateReference | null>();
  const onDraftChange = jest.fn();
  const view = await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(),
      createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as unknown as CreateGateway}
    owner="designer_1"
    draft={EMPTY_STUDIO_CREATE_DRAFT}
    onDraftChange={onDraftChange}
    onRequestReference={() => pending.promise}
    onSave={jest.fn()}
  />);

  let pickerCompletion!: Promise<void>;
  await act(() => {
    pickerCompletion = fireEvent.press(screen.getByText('Add a rough sketch, photo, or render'));
  });
  await view.unmount();
  await act(async () => {
    pending.resolve({
      id: 'late', role: 'master_geometry', label: 'Late sketch.png',
      imageBase64: 'bGF0ZQ==', mediaType: 'image/png', sourceKind: 'drawing',
    });
    await pickerCompletion;
  });
  expect(onDraftChange).not.toHaveBeenCalled();
});

test('does not expose backend diagnostics when generation fails', async () => {
  const onGenerationSucceeded = jest.fn();
  await renderCreate(React.createElement(StudioCreateWorkspace, {
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
      completeCreativeDirectionReview: jest.fn(),
    } as unknown as CreateGateway,
    owner: 'designer_1',
    onGenerationSucceeded,
    onSave: jest.fn(),
  }));

  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'A quiet gold ring.');
  await fireEvent.press(screen.getByLabelText('4 variations'));
  await fireEvent.press(screen.getByText('Generate'));
  expect(await screen.findByText('Facetta could not create those directions. Try again.')).toBeTruthy();
  expect(screen.queryByText(/grok|base64|asset_id|run_id|design_version/i)).toBeNull();
  expect(screen.getByLabelText('Design sentence').props.value).toBe('A quiet gold ring.');
  expect(screen.getByLabelText('4 variations').props.accessibilityState).toEqual({
    checked: true,
  });
  expect(onGenerationSucceeded).not.toHaveBeenCalled();
});

test('keeps partial direction results visible and explains the uncharged failure', async () => {
  const partialProject = creativeProject(1);
  await renderCreate(React.createElement(StudioCreateWorkspace, {
    gateway: {
      createFromPrompt: jest.fn(async () => ({
        data: partialProject, error: null, status: 201,
      })),
      createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as unknown as CreateGateway,
    owner: 'designer_1',
    onSave: jest.fn(),
  }));

  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'A gold ring with 3 diamonds.');
  await fireEvent.press(screen.getByLabelText('2 variations'));
  await fireEvent.press(screen.getByText('Generate'));

  expect(await screen.findByText(
    '1 of 2 requested directions is ready. The other 1 failed quality or provider checks and will not be charged.',
  )).toBeTruthy();
  expect(screen.getByLabelText('Direction 1 preview')).toBeTruthy();
});

test('hydrates a controlled draft with its master source truth and output count', async () => {
  const masterReference: StudioCreateReference = {
    id: 'master_restored',
    role: 'master_geometry',
    label: 'Restored sketch.png',
    imageBase64: 'cmVzdG9yZWQ=',
    mediaType: 'image/png',
    sourceKind: 'drawing',
  };
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    draft={{
      sentence: 'A restored sapphire direction.',
      references: [masterReference],
      candidateCount: 4,
    }}
    onDraftChange={jest.fn()}
    onSave={jest.fn()}
  />);

  expect(screen.getByLabelText('Design sentence').props.value)
    .toBe('A restored sapphire direction.');
  expect(screen.getByText('Restored sketch.png')).toBeTruthy();
  expect(screen.getByText('Preserve source balance · No extra choices')).toBeTruthy();
  expect(screen.getByLabelText('4 variations').props.accessibilityState).toEqual({ checked: true });
  expect(screen.getByText('15 credits per variation · 4 variations = 60 credits')).toBeTruthy();
  expect(screen.getByText('Drawing').parent?.props.accessibilityState).toEqual({ checked: true });
});

test('manual guidance uses one-tap choices without opening a file picker', async () => {
  const onRequestReference = jest.fn();
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    onRequestReference={onRequestReference}
    onSave={jest.fn()}
  />);

  expect(screen.getByLabelText('Optional guidance').props.accessibilityState)
    .toEqual({ expanded: false });
  expect(screen.queryByLabelText('Metal color & material: Yellow gold')).toBeNull();
  await fireEvent.press(screen.getByLabelText('Optional guidance'));
  await fireEvent.press(screen.getByLabelText('Material & finish options'));
  expect(screen.getByLabelText('Material & finish options').props.accessibilityState)
    .toEqual({ expanded: true });

  const yellowGold = screen.getByLabelText('Metal color & material: Yellow gold');
  expect(yellowGold.props.accessibilityRole).toBe('checkbox');
  expect(yellowGold.props.accessibilityState).toEqual({ checked: false });
  expect(yellowGold.props.accessibilityHint).toMatch(/tap again to remove/i);
  await fireEvent.press(yellowGold);
  await fireEvent.press(screen.getByLabelText('Surface & finish: Brushed'));
  await fireEvent.press(screen.getByLabelText('Color palette: Warm neutral'));
  expect(onRequestReference).not.toHaveBeenCalled();
  expect(screen.getByText('Symmetrical · 3 extra choices')).toBeTruthy();
  expect(screen.getByLabelText('Metal color & material: Yellow gold').props.accessibilityState)
    .toEqual({ checked: true });

  await fireEvent.press(screen.getByLabelText('Metal color & material: Yellow gold'));
  expect(screen.getByLabelText('Metal color & material: Yellow gold').props.accessibilityState)
    .toEqual({ checked: false });
  expect(screen.getByText('Symmetrical · 2 extra choices')).toBeTruthy();

  await fireEvent.press(screen.getByLabelText('Add image for Material & finish'));
  expect(onRequestReference).toHaveBeenCalledTimes(1);
  expect(onRequestReference).toHaveBeenCalledWith('material_style');
});

test('maps material, detail, and brand choices into advisory-only provider guidance', async () => {
  const createFromPrompt = jest.fn(async () => ({
    data: creativeProject(1), error: null, status: 201,
  }));
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt, createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    initialSentence="A simple three-stone ring."
    onSave={jest.fn()}
  />);

  await fireEvent.press(screen.getByLabelText('Optional guidance'));
  await fireEvent.press(screen.getByLabelText('Material & finish options'));
  await fireEvent.press(screen.getByLabelText('Metal color & material: Rose gold'));
  await fireEvent.press(screen.getByLabelText('Surface & finish: Satin'));
  await fireEvent.press(screen.getByLabelText('Color palette: Soft pastel'));
  await fireEvent.changeText(
    screen.getByLabelText('Material & finish note'),
    'Restrained warmth',
  );

  await fireEvent.press(screen.getByLabelText('Specific design detail options'));
  expect(screen.getByText(/prongs, an open gallery, a hidden hinge/i)).toBeTruthy();
  await fireEvent.changeText(
    screen.getByLabelText('Specific design detail note'),
    'Use fine rounded prongs and an open gallery.',
  );

  await fireEvent.press(screen.getByLabelText('Brand mood options'));
  expect(screen.getByText(/not another brand’s logo or jewelry shape/i)).toBeTruthy();
  await fireEvent.press(screen.getByLabelText('Brand mood: Quiet luxury'));
  await fireEvent.changeText(
    screen.getByLabelText('Brand mood note'),
    'Calm gallery lighting',
  );

  await fireEvent.press(screen.getByText('Generate'));
  const guidance = {
    material: {
      metal: 'rose_gold' as const,
      finish: 'satin' as const,
      palette: 'soft_pastel' as const,
      note: 'Restrained warmth',
    },
    detail: { note: 'Use fine rounded prongs and an open gallery.' },
    brand: { mood: 'quiet_luxury' as const, note: 'Calm gallery lighting' },
  };
  const submittedPrompt = composeCreateInstruction(
    composeCreateBalanceInstruction('A simple three-stone ring.', 'symmetrical', false),
    guidance,
  );
  await waitFor(() => expect(createFromPrompt).toHaveBeenCalledWith({
    prompt: submittedPrompt,
    variation_count: 1,
    comparison_views: ['three_quarter'],
    owner: 'designer_1',
    title: 'A simple three-stone ring.',
  }));
  expect(submittedPrompt).toMatch(/appearance only; keep geometry/i);
  expect(submittedPrompt).toMatch(/not a production fact/i);
  expect(submittedPrompt).toMatch(/no copied branding or geometry/i);
});

test('keeps optional guidance usable inside the narrow composer and wide web rail', async () => {
  const originalPlatform = Platform.OS;
  const originalWindow = Dimensions.get('window');
  const originalScreen = Dimensions.get('screen');

  const narrow = await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    onSave={jest.fn()}
  />);
  await fireEvent.press(narrow.getByLabelText('Optional guidance'));
  expect(narrow.getByLabelText('Specific design detail options')).toBeTruthy();
  await narrow.unmount();

  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'web' });
  Dimensions.set({
    window: { ...originalWindow, width: 1440, height: 900 },
    screen: { ...originalScreen, width: 1440, height: 900 },
  });
  try {
    const wide = await renderCreate(<StudioCreateWorkspace
      gateway={{
        createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
        completeCreativeDirectionReview: jest.fn(),
      } as CreateGateway}
      owner="designer_1"
      onSave={jest.fn()}
    />);
    expect(wide.getByTestId('create-web-composer')).toBeTruthy();
    expect(wide.getByTestId('create-web-canvas')).toBeTruthy();
    await fireEvent.press(wide.getByLabelText('Optional guidance'));
    await fireEvent.press(wide.getByLabelText('Brand mood options'));
    expect(wide.getByLabelText('Brand mood: Bold editorial')).toBeTruthy();
    await wide.unmount();
  } finally {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: originalPlatform });
    await act(async () => {
      Dimensions.set({ window: originalWindow, screen: originalScreen });
    });
  }
});

test('explains when image selection is unavailable instead of silently ignoring Add', async () => {
  await renderCreate(React.createElement(StudioCreateWorkspace, {
    gateway: {
      createFromPrompt: jest.fn(),
      createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as unknown as CreateGateway,
    owner: 'designer_1',
    onSave: jest.fn(),
  }));

  await fireEvent.press(screen.getByText('Add a rough sketch, photo, or render'));

  expect(await screen.findByText(/Image selection is unavailable here/)).toBeTruthy();
});

test('wide web keeps the prompt composer beside the live direction canvas', async () => {
  const originalPlatform = Platform.OS;
  const originalWindow = Dimensions.get('window');
  const originalScreen = Dimensions.get('screen');
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'web' });
  Dimensions.set({
    window: { ...originalWindow, width: 1440, height: 900 },
    screen: { ...originalScreen, width: 1440, height: 900 },
  });

  try {
    const view = await renderCreate(<StudioCreateWorkspace
      gateway={{
        createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
        completeCreativeDirectionReview: jest.fn(),
      } as CreateGateway}
      owner="designer_1"
      resumeProject={creativeProject(2)}
      onSave={jest.fn()}
    />);

    expect(view.getByTestId('create-web-composer')).toBeTruthy();
    expect(view.getByTestId('create-web-canvas')).toBeTruthy();
    expect(view.getByLabelText('Design sentence')).toBeTruthy();
    expect(view.getByLabelText('Direction 1')).toBeTruthy();
    expect(view.getByText('Choose a direction to refine—or describe another idea.')).toBeTruthy();
    await view.unmount();
  } finally {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: originalPlatform });
    await act(async () => {
      Dimensions.set({ window: originalWindow, screen: originalScreen });
    });
  }
});

test('wide web preserves the current render while a new request is running', async () => {
  const originalPlatform = Platform.OS;
  const originalWindow = Dimensions.get('window');
  const originalScreen = Dimensions.get('screen');
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'web' });
  Dimensions.set({
    window: { ...originalWindow, width: 1440, height: 900 },
    screen: { ...originalScreen, width: 1440, height: 900 },
  });
  const pending = deferred<any>();

  try {
    const view = await renderCreate(<StudioCreateWorkspace
      gateway={{
        createFromPrompt: jest.fn(() => pending.promise), createFromDrawing: jest.fn(),
        completeCreativeDirectionReview: jest.fn(),
      } as CreateGateway}
      owner="designer_1"
      resumeProject={creativeProject(2)}
      onSave={jest.fn()}
    />);

    await fireEvent.changeText(view.getByLabelText('Design sentence'), 'A new emerald pendant.');
    let createCompletion!: Promise<void>;
    await act(() => {
      createCompletion = fireEvent.press(view.getByText('Generate'));
    });

    expect(view.getAllByText('Generating…')).toHaveLength(2);
    expect(view.getByLabelText('Direction 1')).toBeTruthy();

    await act(async () => {
      pending.resolve({ data: creativeProject(1), error: null, status: 201 });
      await createCompletion;
    });
    await view.unmount();
  } finally {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: originalPlatform });
    await act(async () => {
      Dimensions.set({ window: originalWindow, screen: originalScreen });
    });
  }
});
