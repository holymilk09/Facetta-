/// <reference types="jest" />

import React from 'react';
import {
  act, fireEvent, render, screen, waitFor, within,
} from '@testing-library/react-native';

import type { StudioGateway } from './gateway';
import {
  EMPTY_STUDIO_CREATE_DRAFT, StudioCreateWorkspace, type StudioCreateDraft,
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
        setDraft((current) => (
          current === success.submittedDraft ? EMPTY_STUDIO_CREATE_DRAFT : current
        ));
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
  expect(await screen.findByText('Choose a direction to continue')).toBeTruthy();
  expect(onGenerationSucceeded).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/full generated set stays preserved in this review/i)).toBeTruthy();
  expect(screen.queryByLabelText('Keep all other directions')).toBeNull();
  expect(screen.queryByLabelText('Only keep my Original')).toBeNull();
  expect(screen.queryByLabelText('Choose directions individually')).toBeNull();
  expect(screen.getByText('Leave in Activity & start another')).toBeTruthy();
  expect(screen.getByLabelText('Direction 1 preview').props.source.headers).toEqual({
    Authorization: 'Bearer first-party-token',
  });
  expect(screen.getByText(/visual directions.+not measurements or production instructions/i)).toBeTruthy();
  expect(screen.getByText('Continue with Direction 1')).toBeTruthy();
  expect(within(screen.getByLabelText('Direction 2')).queryByText('Inspect detail')).toBeNull();
  expect(completeCreativeDirectionReview).not.toHaveBeenCalled();
  expect(onSave).not.toHaveBeenCalled();
  await loadDirection(1);
  await loadDirection(2);
  await loadDirection(3);
  await loadDirection(4);
  await fireEvent.press(screen.getByLabelText('Direction 3'));
  expect(screen.getByText('Continue with Direction 3')).toBeTruthy();
  expect(within(screen.getByLabelText('Direction 1')).getByText('Will save as a variation'))
    .toBeTruthy();
  expect(screen.getByLabelText('Direction 1').props.accessibilityHint)
    .toBe('Will save as a variation');
  expect(within(screen.getByLabelText('Direction 3')).getByText('Selected to refine'))
    .toBeTruthy();
  await loadDirection(3);
  await fireEvent.press(screen.getByText('Continue with Direction 3'));
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
  await fireEvent.press(screen.getByText('Continue with Direction 1'));

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
  const continueButton = screen.getByText('Continue with Direction 1');
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
  await fireEvent.press(screen.getByText('Continue with Direction 1'));

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
    createCompletion = fireEvent.press(screen.getByText('Create 2 directions'));
  });
  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'A newer unsent direction.');
  await act(async () => {
    pending.resolve({ data: creativeProject(2), error: null, status: 201 });
    await createCompletion;
  });

  expect(await screen.findByText('Choose a direction to continue')).toBeTruthy();
  expect(onGenerationSucceeded).toHaveBeenCalledWith(expect.objectContaining({
    owner: 'designer_1',
    projectId: 'project_1',
    submittedDraft: expect.objectContaining({ sentence: 'First submitted direction.' }),
  }));
  await fireEvent.press(screen.getByText('Leave in Activity & start another'));
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
    createCompletion = fireEvent.press(screen.getByText('Create 2 directions'));
  });
  await view.unmount();
  await act(async () => {
    pending.resolve({ data: creativeProject(2), error: null, status: 201 });
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
    commitCompletion = fireEvent.press(screen.getByText('Continue with Direction 1'));
  });
  expect(screen.getByText('Leave in Activity & start another').parent?.props.accessibilityState)
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
    commitCompletion = fireEvent.press(screen.getByText('Continue with Direction 1'));
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
  await fireEvent.press(screen.getByText('Continue with Direction 2'));
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

  const continueButton = screen.getByText('Continue with Direction 1');
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
    fireEvent.press(screen.getByText('Continue with Direction 1'));
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
  const continueLabel = 'Continue with Direction 3';
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

  await fireEvent.press(screen.getByLabelText('References and output options'));
  expect(screen.getByText('Optional references')).toBeTruthy();
  await fireEvent.press(screen.getByText('Create 2 directions'));
  await loadDirection(1);
  await fireEvent.press(screen.getByText('Continue with Direction 1'));
  expect(await screen.findByText('Facetta could not connect. Check your connection and try again.'))
    .toBeTruthy();

  await fireEvent.press(screen.getByText('Leave in Activity & start another'));

  expect(screen.queryByText('Facetta could not connect. Check your connection and try again.'))
    .toBeNull();
  expect(screen.queryByText('Optional references')).toBeNull();
  expect(screen.getByLabelText('References and output options').props.accessibilityState)
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

  await fireEvent.press(screen.getByText('Create 2 directions'));
  expect(await screen.findByText(/full generated set stays preserved in this review/i)).toBeTruthy();
  await loadDirection(1);
  expect(screen.getByText('Continue with Direction 1')).toBeTruthy();
  await fireEvent.press(screen.getByText('Leave in Activity & start another'));
  expect(await screen.findByLabelText('Design sentence')).toBeTruthy();
  expect(screen.queryByText(/full generated set stays preserved in this review/i)).toBeNull();
  await fireEvent.press(screen.getByText('Create 2 directions'));
  await loadDirection(1);
  expect(await screen.findByText('Continue with Direction 1')).toBeTruthy();
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
    data: creativeProject(2), error: null, status: 201,
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

  await fireEvent.press(screen.getByText('Add a drawing, photo, or render'));
  expect(screen.getByText('What did you upload?')).toBeTruthy();
  await fireEvent.press(screen.getByText('Drawing'));
  await fireEvent.press(screen.getByLabelText('References and output options'));
  await fireEvent.press(screen.getByLabelText('Add Material & style reference'));
  await fireEvent.changeText(screen.getByLabelText('Design sentence'), 'Preserve the silhouette and make it feel lighter.');

  expect(screen.getByText('Create 2 directions').parent?.props.accessibilityState).toEqual({ disabled: true });
  expect(screen.getByText('Checking attached references before creation…')).toBeTruthy();
  expect(screen.getByLabelText('Visual source preview').props.source.uri).toBe(
    'data:image/png;base64,bWFzdGVy',
  );
  expect(screen.getByLabelText('Material & style reference preview').props.source.uri).toBe(
    'data:image/jpeg;base64,bWF0ZXJpYWw=',
  );

  await fireEvent.press(screen.getByLabelText('Inspect Master geometry · Front sketch in detail'));
  expect(screen.getByText('Master geometry · Front sketch')).toBeTruthy();
  await fireEvent.press(screen.getByLabelText('Zoom image to 4x'));
  expect(screen.getByLabelText('Zoom image to 4x').props.accessibilityState).toEqual({ selected: true });
  expect(createProjectFromDrawing).not.toHaveBeenCalled();
  await fireEvent.press(screen.getByLabelText('Close image inspector'));

  await fireEvent.press(screen.getByLabelText('Inspect Material & style · Brushed gold reference in detail'));
  expect(screen.getByText('Material & style · Brushed gold reference')).toBeTruthy();
  await fireEvent.press(screen.getByLabelText('Close image inspector'));
  expect(createProjectFromDrawing).not.toHaveBeenCalled();

  await loadReferencePreview('Visual source preview');
  await loadReferencePreview('Material & style reference preview');
  expect(screen.getByText('Create 2 directions').parent?.props.accessibilityState).toEqual({ disabled: false });
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

test('accepts role-labeled advisory guidance after a sentence without requiring a master', async () => {
  const material: StudioCreateReference = {
    id: 'material', role: 'material_style', label: 'Hammered gold reference',
    imageBase64: 'bWF0ZXJpYWw=', mediaType: 'image/jpeg',
  };
  const createFromPrompt = jest.fn(async () => ({
    data: creativeProject(2), error: null, status: 201,
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

  await fireEvent.press(screen.getByLabelText('References and output options'));
  const addMaterial = screen.getByLabelText('Add Material & style reference');
  expect(addMaterial.props.accessibilityState).toEqual({ disabled: true });
  expect(screen.getAllByText('Add an idea first')).toHaveLength(3);
  expect(screen.getByText('2 directions · No supporting references')).toBeTruthy();

  await fireEvent.changeText(
    screen.getByLabelText('Design sentence'),
    'A broad sculptural gold cuff with one clean opening.',
  );
  expect(screen.getByLabelText('Add Material & style reference').props.accessibilityState).toEqual({
    disabled: false,
  });
  await fireEvent.press(screen.getByLabelText('Add Material & style reference'));
  expect(onRequestReference).toHaveBeenCalledWith('material_style');
  expect(screen.getByText('2 directions · 1 supporting reference')).toBeTruthy();
  expect(screen.queryByText('Master geometry required')).toBeNull();
  expect(screen.queryByText('Add a design idea')).toBeNull();
  expect(screen.getByText('Create 2 directions').parent?.props.accessibilityState).toEqual({ disabled: true });

  await loadReferencePreview('Material & style reference preview');
  await fireEvent.press(screen.getByText('Create 2 directions'));
  await waitFor(() => expect(createFromPrompt).toHaveBeenCalledWith({
    prompt: 'A broad sculptural gold cuff with one clean opening.',
    references: [{
      role: 'material_style',
      image_base64: 'bWF0ZXJpYWw=',
      media_type: 'image/jpeg',
    }],
    variation_count: 2,
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

  await loadReferencePreview('Material & style reference preview');
  expect(screen.getByText('2 directions · 1 supporting reference')).toBeTruthy();
  expect(screen.getByText('Add a design idea')).toBeTruthy();
  expect(screen.getByText(
    'Supporting references can guide material, construction, or brand direction after you add a design sentence or one visual source. They do not define the jewelry on their own.',
  )).toBeTruthy();
  expect(screen.queryByText('Master geometry required')).toBeNull();
  expect(screen.getByText('Create 2 directions').parent?.props.accessibilityState).toEqual({
    disabled: true,
  });
  await fireEvent.press(screen.getByText('Create 2 directions'));
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
  expect(screen.getByText('Create 2 directions').parent?.props.accessibilityState).toEqual({ disabled: true });
  await loadReferencePreview('Visual source preview');
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
  expect(screen.getByText('Create 2 directions').parent?.props.accessibilityState).toEqual({ disabled: true });
  await fireEvent.press(screen.getByText('Create 2 directions'));
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

  await fireEvent.press(screen.getByText('Add a drawing, photo, or render'));

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
    firstCompletion = fireEvent.press(screen.getByText('Add a drawing, photo, or render'));
  });
  await act(() => {
    secondCompletion = fireEvent.press(screen.getByText('Add a drawing, photo, or render'));
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
    pickerCompletion = fireEvent.press(screen.getByText('Add a drawing, photo, or render'));
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
  await fireEvent.press(screen.getByLabelText('References and output options'));
  await fireEvent.press(screen.getByLabelText('4 creative directions'));
  await fireEvent.press(screen.getByText('Create 4 directions'));
  expect(await screen.findByText('Facetta could not create those directions. Try again.')).toBeTruthy();
  expect(screen.queryByText(/grok|base64|asset_id|run_id|design_version/i)).toBeNull();
  expect(screen.getByLabelText('Design sentence').props.value).toBe('A quiet gold ring.');
  expect(screen.getByLabelText('4 creative directions').props.accessibilityState).toEqual({
    checked: true,
  });
  expect(onGenerationSucceeded).not.toHaveBeenCalled();
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
  expect(screen.getByText('4 directions · No supporting references')).toBeTruthy();
  expect(screen.getByText('Drawing').parent?.props.accessibilityState).toEqual({ checked: true });
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

  await fireEvent.press(screen.getByText('Add a drawing, photo, or render'));

  expect(await screen.findByText(/Image selection is unavailable here/)).toBeTruthy();
});
