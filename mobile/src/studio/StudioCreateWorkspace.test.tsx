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
    fireEvent(screen.getByLabelText(`Design ${index} preview`), 'load');
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
  expect(screen.getByText('How many designs would you like to compare?')).toBeTruthy();
  expect(screen.queryByText('Optional references')).toBeNull();
  await fireEvent.changeText(screen.getByLabelText('Design description'), 'A sculptural aquamarine collar.');
  await fireEvent.press(screen.getByLabelText('4 designs'));
  expect(screen.getByText('4 requested outputs × 15 credits = estimated 60 credits')).toBeTruthy();
  await fireEvent.press(screen.getByText('Generate 4 designs'));

  await waitFor(() => expect(createFromPrompt).toHaveBeenCalledWith({
    prompt: 'A sculptural aquamarine collar.',
    variation_count: 4,
    owner: 'designer_1',
    title: 'A sculptural aquamarine collar.',
  }));
  expect(await screen.findByText('Choose a design')).toBeTruthy();
  expect(onGenerationSucceeded).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/other generated designs stay saved for comparison/i)).toBeTruthy();
  expect(screen.queryByLabelText('Keep all other directions')).toBeNull();
  expect(screen.queryByLabelText('Only keep my Original')).toBeNull();
  expect(screen.queryByLabelText('Choose directions individually')).toBeNull();
  expect(screen.getByText('Start over')).toBeTruthy();
  expect(screen.getByLabelText('Design 1 preview').props.source.headers).toEqual({
    Authorization: 'Bearer first-party-token',
  });
  expect(screen.getByText(/visual concepts.+not production measurements/i)).toBeTruthy();
  expect(screen.getByText('Continue with Design 1')).toBeTruthy();
  expect(within(screen.getByLabelText('Design 2')).queryByText('Inspect detail')).toBeNull();
  expect(completeCreativeDirectionReview).not.toHaveBeenCalled();
  expect(onSave).not.toHaveBeenCalled();
  await loadDirection(1);
  await loadDirection(2);
  await loadDirection(3);
  await loadDirection(4);
  await fireEvent.press(screen.getByLabelText('Design 3'));
  expect(screen.getByText('Continue with Design 3')).toBeTruthy();
  expect(within(screen.getByLabelText('Design 1')).getByText('Saved as an alternative'))
    .toBeTruthy();
  expect(screen.getByLabelText('Design 1').props.accessibilityHint)
    .toBe('Saved as an alternative');
  expect(within(screen.getByLabelText('Design 3')).getByText('Selected'))
    .toBeTruthy();
  await loadDirection(3);
  await fireEvent.press(screen.getByText('Continue with Design 3'));
  await waitFor(() => expect(completeCreativeDirectionReview).toHaveBeenCalledTimes(1));
  expect(completeCreativeDirectionReview).toHaveBeenCalledWith({
    projectId: 'project_1', selectedCandidateId: 'candidate_3',
    retained: [
      { candidateId: 'candidate_1', label: 'Design 1' },
      { candidateId: 'candidate_2', label: 'Design 2' },
      { candidateId: 'candidate_4', label: 'Design 4' },
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
  await fireEvent.press(screen.getByText('Continue with Design 1'));

  await waitFor(() => expect(completeCreativeDirectionReview).toHaveBeenCalledWith({
    projectId: 'project_1', selectedCandidateId: 'candidate_1', retained: [
      { candidateId: 'candidate_2', label: 'Design 2' },
      { candidateId: 'candidate_3', label: 'Design 3' },
    ],
    createdBy: 'designer_1',
  }));
});

test('an unavailable unselected preview remains saved and does not block a loaded selection', async () => {
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
    fireEvent(screen.getByLabelText('Design 2 preview'), 'error');
  });
  await loadDirection(3);
  expect(screen.queryByText(/could not be displayed/i)).toBeNull();
  const continueButton = screen.getByText('Continue with Design 1');
  expect(continueButton.parent?.props.accessibilityState.disabled).toBe(false);
  await fireEvent.press(continueButton);

  await waitFor(() => expect(completeCreativeDirectionReview).toHaveBeenCalledWith({
    projectId: 'project_1', selectedCandidateId: 'candidate_1',
    retained: [
      { candidateId: 'candidate_2', label: 'Design 2' },
      { candidateId: 'candidate_3', label: 'Design 3' },
    ],
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
  expect(within(screen.getByLabelText('Design 5')).getByText('Saved for comparison'))
    .toBeTruthy();
  expect(within(screen.getByLabelText('Design 6')).getByText('Saved for comparison'))
    .toBeTruthy();
  expect(screen.getByLabelText('Design 4').props.accessibilityHint)
    .toBe('Saved as an alternative');
  expect(screen.getByLabelText('Design 5').props.accessibilityHint)
    .toBe('Saved for comparison');
  await fireEvent.press(screen.getByText('Continue with Design 1'));

  await waitFor(() => expect(completeCreativeDirectionReview).toHaveBeenCalledWith({
    projectId: 'project_1', selectedCandidateId: 'candidate_1', retained: [
      { candidateId: 'candidate_2', label: 'Design 2' },
      { candidateId: 'candidate_3', label: 'Design 3' },
      { candidateId: 'candidate_4', label: 'Design 4' },
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

  await fireEvent.changeText(screen.getByLabelText('Design description'), 'First submitted direction.');
  let createCompletion!: Promise<void>;
  await act(() => {
    createCompletion = fireEvent.press(screen.getByText('Generate 2 designs'));
  });
  await fireEvent.changeText(screen.getByLabelText('Design description'), 'A newer unsent direction.');
  await act(async () => {
    pending.resolve({ data: creativeProject(2), error: null, status: 201 });
    await createCompletion;
  });

  expect(await screen.findByText('Choose a design')).toBeTruthy();
  expect(onGenerationSucceeded).toHaveBeenCalledWith(expect.objectContaining({
    owner: 'designer_1',
    projectId: 'project_1',
    submittedDraft: expect.objectContaining({ sentence: 'First submitted direction.' }),
  }));
  await fireEvent.press(screen.getByText('Start over'));
  expect(screen.getByLabelText('Design description').props.value).toBe('A newer unsent direction.');
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

  await fireEvent.changeText(screen.getByLabelText('Design description'), 'Direction before navigation.');
  let createCompletion!: Promise<void>;
  await act(() => {
    createCompletion = fireEvent.press(screen.getByText('Generate 2 designs'));
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

  expect(screen.queryByText('Your other generated designs stay saved for comparison.')).toBeNull();
  await loadDirection(1);
  let commitCompletion!: Promise<void>;
  await act(() => {
    commitCompletion = fireEvent.press(screen.getByText('Continue with Design 1'));
  });
  expect(screen.getByText('Start over').parent?.props.accessibilityState)
    .toEqual({ disabled: true });
  expect(screen.getByLabelText('Design 1').props.accessibilityState)
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
    commitCompletion = fireEvent.press(screen.getByText('Continue with Design 1'));
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

  expect(await screen.findByText('Choose a design')).toBeTruthy();
  expect(createFromPrompt).not.toHaveBeenCalled();
  expect(createFromDrawing).not.toHaveBeenCalled();
  await loadDirection(1);
  await loadDirection(2);
  await loadDirection(3);
  await fireEvent.press(screen.getByLabelText('Design 2'));
  await fireEvent.press(screen.getByText('Continue with Design 2'));
  await waitFor(() => expect(completeCreativeDirectionReview).toHaveBeenCalledWith({
    projectId: 'project_1', selectedCandidateId: 'candidate_2', retained: [
      { candidateId: 'candidate_1', label: 'Design 1' },
      { candidateId: 'candidate_3', label: 'Design 3' },
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

  const continueButton = screen.getByText('Continue with Design 1');
  expect(continueButton.parent?.props.accessibilityState.disabled).toBe(true);
  fireEvent.press(continueButton);
  expect(completeCreativeDirectionReview).not.toHaveBeenCalled();

  await act(async () => {
    fireEvent(screen.getByLabelText('Design 1 preview'), 'error');
  });
  expect(screen.getByText(/selected design could not be displayed/i)).toBeTruthy();
  fireEvent.press(continueButton);
  expect(completeCreativeDirectionReview).not.toHaveBeenCalled();

  await loadDirection(1);
  await act(async () => {
    fireEvent.press(screen.getByText('Continue with Design 1'));
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
  await fireEvent.press(screen.getByLabelText('Design 3'));
  const continueLabel = 'Continue with Design 3';
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

test('starting another design clears the previous review error without reopening setup clutter', async () => {
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

  expect(screen.queryByText('Optional references')).toBeNull();
  await fireEvent.press(screen.getByText('Generate 2 designs'));
  await loadDirection(1);
  await fireEvent.press(screen.getByText('Continue with Design 1'));
  expect(await screen.findByText('Facetta could not connect. Check your connection and try again.'))
    .toBeTruthy();

  await fireEvent.press(screen.getByText('Start over'));

  expect(screen.queryByText('Facetta could not connect. Check your connection and try again.'))
    .toBeNull();
  expect(screen.queryByText('Optional references')).toBeNull();
  expect(screen.getByLabelText('Design description').props.value).toBe('First direction');
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

  await fireEvent.press(screen.getByText('Generate 2 designs'));
  expect(await screen.findByText(/other generated designs stay saved for comparison/i)).toBeTruthy();
  await loadDirection(1);
  expect(screen.getByText('Continue with Design 1')).toBeTruthy();
  await fireEvent.press(screen.getByText('Start over'));
  expect(await screen.findByLabelText('Design description')).toBeTruthy();
  expect(screen.queryByText(/other generated designs stay saved for comparison/i)).toBeNull();
  await fireEvent.press(screen.getByText('Generate 2 designs'));
  await loadDirection(1);
  expect(await screen.findByText('Continue with Design 1')).toBeTruthy();
  expect(screen.queryByLabelText('Keep all other directions')).toBeNull();
});

test('upload mode opens the picker only after Choose drawing and sends one unambiguous drawing', async () => {
  const master: StudioCreateReference = {
    id: 'master', role: 'master_geometry', label: 'Front sketch',
    imageBase64: 'bWFzdGVy', mediaType: 'image/png',
  };
  const createProjectFromDrawing = jest.fn(async () => ({
    data: creativeProject(3), error: null, status: 201,
  }));
  const createFromPrompt = jest.fn();
  const onRequestReference = jest.fn(async () => master);
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

  await fireEvent.press(screen.getByLabelText('Upload a drawing'));
  expect(onRequestReference).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Choose a drawing')).toBeTruthy();
  await fireEvent.press(screen.getByLabelText('Choose a drawing'));
  expect(onRequestReference).toHaveBeenCalledWith('master_geometry');
  await fireEvent.changeText(
    screen.getByLabelText('Drawing notes'),
    'Preserve the silhouette and make it feel lighter.',
  );
  await fireEvent.press(screen.getByLabelText('3 designs'));

  expect(screen.getByText('Generate 3 designs').parent?.props.accessibilityState).toEqual({ disabled: true });
  expect(screen.getByText('Checking your drawing before generation…')).toBeTruthy();
  expect(screen.getByLabelText('Drawing preview').props.source.uri).toBe(
    'data:image/png;base64,bWFzdGVy',
  );
  await fireEvent.press(screen.getByLabelText('Inspect Uploaded drawing · Front sketch in detail'));
  expect(screen.getByText('Uploaded drawing · Front sketch')).toBeTruthy();
  await fireEvent.press(screen.getByLabelText('Zoom image to 4x'));
  expect(screen.getByLabelText('Zoom image to 4x').props.accessibilityState).toEqual({ selected: true });
  expect(createProjectFromDrawing).not.toHaveBeenCalled();
  await fireEvent.press(screen.getByLabelText('Close image inspector'));

  await loadReferencePreview('Drawing preview');
  expect(screen.getByText('Generate 3 designs').parent?.props.accessibilityState).toEqual({ disabled: false });
  await fireEvent.press(screen.getByText('Generate 3 designs'));

  await waitFor(() => expect(createProjectFromDrawing).toHaveBeenCalledWith({
    image_base64: 'bWFzdGVy',
    source_kind: 'drawing',
    media_type: 'image/png',
    instruction: 'Preserve the silhouette and make it feel lighter.',
    references: [],
    variation_count: 3,
    owner: 'designer_1',
    title: 'Preserve the silhouette and make it feel lighter.',
  }));
  expect(createFromPrompt).not.toHaveBeenCalled();
  expect(screen.queryByText('Construction detail')).toBeNull();
  expect(screen.queryByText('Brand direction')).toBeNull();
  expect(screen.queryByText('Material & style')).toBeNull();
});

test('keeps prompt text, drawing, and drawing notes when switching starting methods', async () => {
  const master: StudioCreateReference = {
    id: 'toggle-master', role: 'master_geometry', label: 'Toggle sketch',
    imageBase64: 'dG9nZ2xl', mediaType: 'image/png',
  };
  const createFromDrawing = jest.fn(async () => ({
    data: creativeProject(1), error: null, status: 201,
  }));
  const onRequestReference = jest.fn(async () => master);
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing,
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    onRequestReference={onRequestReference}
    onSave={jest.fn()}
  />);

  await fireEvent.changeText(
    screen.getByLabelText('Design description'),
    'An emerald ring with a knife-edge band.',
  );
  await fireEvent.press(screen.getByLabelText('Upload a drawing'));
  await fireEvent.press(screen.getByLabelText('Choose a drawing'));
  await fireEvent.changeText(
    screen.getByLabelText('Drawing notes'),
    'Keep the silhouette and soften the shoulders.',
  );
  await loadReferencePreview('Drawing preview');

  await fireEvent.press(screen.getByLabelText('Describe a design'));
  expect(screen.getByLabelText('Design description').props.value)
    .toBe('An emerald ring with a knife-edge band.');

  await fireEvent.press(screen.getByLabelText('Upload a drawing'));
  expect(screen.getByLabelText('Drawing preview')).toBeTruthy();
  expect(screen.getByLabelText('Drawing notes').props.value)
    .toBe('Keep the silhouette and soften the shoulders.');
  expect(onRequestReference).toHaveBeenCalledTimes(1);

  await fireEvent.press(screen.getByText('Generate 2 designs'));
  await waitFor(() => expect(createFromDrawing).toHaveBeenCalledWith(expect.objectContaining({
    image_base64: 'dG9nZ2xl',
    instruction: 'Keep the silhouette and soften the shoulders.',
    variation_count: 2,
  })));
});

test('keeps the first screen to prompt or drawing without role taxonomy', async () => {
  await renderCreate(<StudioCreateWorkspace
    gateway={{
      createFromPrompt: jest.fn(), createFromDrawing: jest.fn(),
      completeCreativeDirectionReview: jest.fn(),
    } as CreateGateway}
    owner="designer_1"
    onSave={jest.fn()}
  />);

  expect(screen.getByLabelText('Describe a design').props.accessibilityState).toEqual({ checked: true });
  expect(screen.getByLabelText('Upload a drawing').props.accessibilityState).toEqual({ checked: false });
  expect(screen.getByText('How many designs would you like to compare?')).toBeTruthy();
  expect(screen.queryByText('Optional references')).toBeNull();
  expect(screen.queryByText('Material & style')).toBeNull();
  expect(screen.queryByText('Construction detail')).toBeNull();
  expect(screen.queryByText('Brand direction')).toBeNull();
});

test('starts from a drawing without forcing an instruction', async () => {
  const master: StudioCreateReference = {
    id: 'master', role: 'master_geometry', label: 'Pendant sketch',
    imageBase64: 'bWFzdGVy', mediaType: 'image/png', sourceKind: 'drawing',
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

  expect(screen.getByLabelText('Drawing preview').props.source.uri).toBe(
    'data:image/png;base64,bWFzdGVy',
  );
  expect(screen.getByLabelText('Replace drawing')).toBeTruthy();
  expect(screen.getByText('Generate 2 designs').parent?.props.accessibilityState).toEqual({ disabled: true });
  await loadReferencePreview('Drawing preview');
  await fireEvent.press(screen.getByText('Generate 2 designs'));
  await waitFor(() => expect(createFromDrawing).toHaveBeenCalledWith({
    image_base64: 'bWFzdGVy',
    source_kind: 'drawing',
    media_type: 'image/png',
    references: [],
    variation_count: 2,
    owner: 'designer_1',
    title: 'Pendant sketch',
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
    fireEvent(screen.getByLabelText('Drawing preview'), 'error');
  });

  expect(screen.getByText(
    'Your drawing preview could not be shown. Replace or remove it before generating designs.',
  )).toBeTruthy();
  expect(screen.getByText('Generate 2 designs').parent?.props.accessibilityState).toEqual({ disabled: true });
  await fireEvent.press(screen.getByText('Generate 2 designs'));
  expect(createFromDrawing).not.toHaveBeenCalled();
});

test('surfaces picker failures instead of leaving Choose drawing as a silent dead end', async () => {
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

  await fireEvent.press(screen.getByLabelText('Upload a drawing'));
  await fireEvent.press(screen.getByLabelText('Choose a drawing'));

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

  await fireEvent.press(screen.getByLabelText('Upload a drawing'));
  await fireEvent.changeText(screen.getByLabelText('Drawing notes'), 'Original sentence.');
  let firstCompletion!: Promise<void>;
  let secondCompletion!: Promise<void>;
  await act(() => {
    firstCompletion = fireEvent.press(screen.getByLabelText('Choose a drawing'));
  });
  await act(() => {
    secondCompletion = fireEvent.press(screen.getByLabelText('Choose a drawing'));
  });
  await fireEvent.changeText(screen.getByLabelText('Drawing notes'), 'Newer sentence.');
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
  expect(screen.getByLabelText('Drawing notes').props.value).toBe('Newer sentence.');
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
  await fireEvent.press(screen.getByLabelText('Upload a drawing'));
  onDraftChange.mockClear();
  await act(() => {
    pickerCompletion = fireEvent.press(screen.getByLabelText('Choose a drawing'));
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

  await fireEvent.changeText(screen.getByLabelText('Design description'), 'A quiet gold ring.');
  await fireEvent.press(screen.getByLabelText('4 designs'));
  await fireEvent.press(screen.getByText('Generate 4 designs'));
  expect(await screen.findByText('Facetta could not create those directions. Try again.')).toBeTruthy();
  expect(screen.queryByText(/grok|base64|asset_id|run_id|design_version/i)).toBeNull();
  expect(screen.getByLabelText('Design description').props.value).toBe('A quiet gold ring.');
  expect(screen.getByLabelText('4 designs').props.accessibilityState).toEqual({
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

  expect(screen.getByLabelText('Drawing notes').props.value)
    .toBe('A restored sapphire direction.');
  expect(screen.getByText('Restored sketch.png')).toBeTruthy();
  expect(screen.getByLabelText('4 designs').props.accessibilityState).toEqual({ checked: true });
  expect(screen.getByLabelText('Upload a drawing').props.accessibilityState).toEqual({ checked: true });
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

  await fireEvent.press(screen.getByLabelText('Upload a drawing'));
  await fireEvent.press(screen.getByLabelText('Choose a drawing'));

  expect(await screen.findByText(/Image selection is unavailable here/)).toBeTruthy();
});
