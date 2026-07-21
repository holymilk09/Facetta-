/// <reference types="jest" />
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Dimensions, Platform, StyleSheet } from 'react-native';
import { AuthenticatedImageProvider } from '../AuthenticatedImage';
import { StudioConfirmWorkspace } from './StudioConfirmWorkspace';
import type { StudioDesignConfirmationReview } from './gateway';

const lineage = { projectId: 'project_1', sourceAssetId: 'asset_7' };
const review: StudioDesignConfirmationReview = {
  reviewId: 'hidden_review',
  designerAcknowledged: false,
  factGroups: [{ key: 'design', label: 'Design identity', facts: [
    { key: 'jewelry_type', label: 'Jewelry type', value: 'ring', path: null, rawValue: 'ring', authority: 'suggested' },
    { key: 'template', label: 'Design type', value: 'solitaire', path: null, rawValue: 'solitaire', authority: 'estimated' },
  ] }, { key: 'center_stone', label: 'Center stone', facts: [
    { key: 'species', label: 'Stone', value: 'sapphire', path: 'stone.species', rawValue: 'sapphire', authority: 'estimated' },
    { key: 'color', label: 'Color', value: 'Royal Blue', path: 'stone.color.trade', rawValue: 'Royal Blue', authority: 'estimated' },
  ] }, { key: 'setting', label: 'Setting', facts: [
    { key: 'style', label: 'Setting', value: '4_prong_basket', path: 'setting.style', rawValue: '4_prong_basket', authority: 'suggested' },
    { key: 'prong_count', label: 'Prongs', value: '4', path: null, rawValue: 4, authority: 'suggested' },
  ] }, { key: 'metal', label: 'Metal', facts: [
    { key: 'material', label: 'Metal', value: 'gold', path: 'metal.material', rawValue: 'gold', authority: 'suggested' },
  ] }, { key: 'ring_fit', label: 'Sizing and proportions', facts: [
    { key: 'ring_size', label: 'Ring size', value: '6.5', path: 'ring_size.value', rawValue: 6.5, authority: 'designer_supplied' },
  ] }],
  unresolvedQuestions: [],
  sourceReview: { eligible: true, state: 'complete', reason: 'The selected visual has current evidence.' },
};
const gateway = (overrides: Record<string, unknown> = {}) => ({
  loadDesignConfirmation: jest.fn(async () => ({ data: review, error: null, status: 200 })),
  auditDesignConfirmation: jest.fn(async (next) => ({ data: { auditId: 'audit_1', status: 'pass', issues: [], review: next }, error: null, status: 200 })),
  saveDesignConfirmation: jest.fn(async () => ({ data: { confirmationId: 'confirmation_1', auditId: 'audit_1', project: { root_id: 'project_1' } }, error: null, status: 201 })),
  ...overrides,
}) as any;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

test('fails closed without an exact selected visual', async () => {
  await render(<StudioConfirmWorkspace gateway={gateway()} lineage={null} createdBy="designer" onSaved={jest.fn()} />);
  expect(screen.getByText('Choose a saved visual first')).toBeTruthy();
  expect(screen.queryByText('Save starting facts')).toBeNull();
});

test('shows the selected revision preview with an explicit inspector that stays closed initially', async () => {
  await render(
    <AuthenticatedImageProvider
      allowedOrigin="https://test"
      headers={{ Authorization: 'Bearer test-session' }}>
      <StudioConfirmWorkspace
        gateway={gateway()}
        lineage={lineage}
        createdBy="designer"
        sourceImageUrl="https://test/exact-selected-asset.png"
        imageRequestHeaders={{ Authorization: 'Bearer test-session' }}
        onSaved={jest.fn()}
      />
    </AuthenticatedImageProvider>,
  );

  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  const exactImage = screen.getByLabelText('Selected revision preview used to review starting facts');
  expect(exactImage.props.source).toMatchObject({
    uri: 'https://test/exact-selected-asset.png',
    headers: { Authorization: 'Bearer test-session' },
  });
  expect(screen.getByTestId('confirm-mobile-layout')).toBeTruthy();
  expect(screen.getByTestId('confirm-selected-visual-panel')).toBeTruthy();
  expect(screen.getByTestId('confirm-facts-panel')).toBeTruthy();
  expect(screen.getByText('Enlarge')).toBeTruthy();
  expect(screen.queryByText('DETAIL INSPECTION')).toBeNull();
  expect(screen.queryByLabelText('Selected revision preview detail view')).toBeNull();
  expect(String(screen.getByLabelText('Selected revision preview notice').props.children))
    .toMatch(/delivery note is added only to this preview/i);

  await fireEvent.press(screen.getByLabelText('Inspect Selected revision preview in detail'));
  expect(screen.getByText('DETAIL INSPECTION')).toBeTruthy();
  expect(screen.getByLabelText('Selected revision preview detail view')).toBeTruthy();
});

test('uses a side-by-side fact review layout on wide web screens', async () => {
  const originalPlatform = Platform.OS;
  const originalWindow = Dimensions.get('window');
  const originalScreen = Dimensions.get('screen');
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'web' });
  Dimensions.set({
    window: { ...originalWindow, width: 1440, height: 900 },
    screen: { ...originalScreen, width: 1440, height: 900 },
  });

  try {
    const view = await render(<StudioConfirmWorkspace
      gateway={gateway()}
      lineage={lineage}
      createdBy="designer"
      sourceImageUrl={null}
      onSaved={jest.fn()}
    />);
    await waitFor(() => expect(view.getByText('Jewelry type')).toBeTruthy());

    expect(view.getByTestId('confirm-web-layout')).toBeTruthy();
    expect(StyleSheet.flatten(view.getByTestId('confirm-web-layout').props.style))
      .toMatchObject({ flexDirection: 'row', alignItems: 'flex-start' });
    expect(StyleSheet.flatten(view.getByTestId('confirm-selected-visual-panel').props.style))
      .toMatchObject({ width: 420, flexShrink: 0 });
    expect(view.getByText('Selected visual could not be displayed.')).toBeTruthy();
    await view.unmount();
  } finally {
    Object.defineProperty(Platform, 'OS', { configurable: true, value: originalPlatform });
    await act(async () => {
      Dimensions.set({ window: originalWindow, screen: originalScreen });
    });
  }
});

test('loads projected facts and renders all designer authority labels without internal payloads', async () => {
  const withQuestion = {
    ...review,
    unresolvedQuestions: ['Confirm the band profile against the selected visual.'],
    sourceReview: { eligible: false, state: 'not_ready' as const, reason: 'Answer the remaining source questions first.' },
  };
  await render(<StudioConfirmWorkspace gateway={gateway({ loadDesignConfirmation: jest.fn(async () => ({ data: withQuestion, error: null, status: 200 })) })} lineage={lineage} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Selected revision preview')).toBeTruthy());
  expect(screen.getAllByText('Suggested').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Estimate').length).toBeGreaterThan(0);
  expect(screen.getAllByText('Measured or supplied').length).toBeGreaterThan(0);
  expect(screen.getByText(/Confirm the band profile/i)).toBeTruthy();
  expect(screen.getByText('QUESTIONS KEPT FOR LATER')).toBeTruthy();
  expect(screen.getByText(/remain attached to this direction for later review/i)).toBeTruthy();
  expect(screen.queryByText(/Factory/i)).toBeNull();
  expect(screen.queryByLabelText('Jewelry type: Measured or supplied')).toBeNull();
  expect(screen.queryByText(/hidden_review|continuation|project_1|asset_7|provider|QA/i)).toBeNull();
});

test('cannot audit or save without explicit acknowledgement of starting facts', async () => {
  const g = gateway();
  await render(<StudioConfirmWorkspace gateway={g} lineage={lineage} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  expect(screen.getByText('Save starting facts').parent?.props.accessibilityState)
    .toEqual({ disabled: true });
  await fireEvent.press(screen.getByText('Save starting facts'));
  expect(g.auditDesignConfirmation).not.toHaveBeenCalled();
  expect(g.saveDesignConfirmation).not.toHaveBeenCalled();
  expect(screen.getAllByText(/unchanged estimates remain estimates/i).length).toBeGreaterThan(0);
  expect(screen.getByText(/appends a new immutable revision/i)).toBeTruthy();
  expect(screen.getByText(/does not make the design production-ready/i)).toBeTruthy();
  expect(screen.queryByText(/Design v1|Create Design|Review starting design/i)).toBeNull();
});

test('one save action stops after a failed audit', async () => {
  const save = jest.fn();
  const g = gateway({
    auditDesignConfirmation: jest.fn(async (next) => ({ data: { auditId: 'a', status: 'fail', issues: ['Answer the remaining source questions.'], review: next }, error: null, status: 200 })),
    saveDesignConfirmation: save,
  });
  await render(<StudioConfirmWorkspace gateway={g} lineage={lineage} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  await fireEvent.press(screen.getByLabelText('I reviewed these starting facts'));
  await fireEvent.press(screen.getByText('Save starting facts'));
  await waitFor(() => expect(screen.getByText(/Answer the remaining/i)).toBeTruthy());
  expect(g.auditDesignConfirmation).toHaveBeenCalledTimes(1);
  expect(save).not.toHaveBeenCalled();
});

test('one acknowledgement-gated action audits, saves, and invokes callback in order', async () => {
  const g = gateway(); const onSaved = jest.fn();
  await render(<StudioConfirmWorkspace gateway={g} lineage={lineage} createdBy="designer" onSaved={onSaved} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  await fireEvent.press(screen.getByLabelText('I reviewed these starting facts'));
  await fireEvent.press(screen.getByText('Save starting facts'));
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ confirmationId: 'confirmation_1' })));
  expect(g.auditDesignConfirmation).toHaveBeenCalledTimes(1);
  expect(g.saveDesignConfirmation).toHaveBeenCalledTimes(1);
  expect(g.auditDesignConfirmation.mock.invocationCallOrder[0])
    .toBeLessThan(g.saveDesignConfirmation.mock.invocationCallOrder[0]);
  const audited = g.auditDesignConfirmation.mock.calls[0][0];
  expect(audited.factGroups[0].facts[0].authority).toBe('suggested');
});

test('corrects visible facts and uses a one-tap coupled setting choice', async () => {
  const g = gateway();
  await render(<StudioConfirmWorkspace gateway={g} lineage={lineage} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());

  expect(screen.getByLabelText('Edit Metal')).toBeTruthy();
  expect(screen.getByLabelText('Edit Stone')).toBeTruthy();
  await fireEvent.press(screen.getByLabelText('Edit Color'));
  await fireEvent.changeText(screen.getByLabelText('Edit Color'), 'Cornflower Blue');
  await fireEvent.press(screen.getByLabelText('Edit Setting'));
  await fireEvent.press(screen.getByLabelText('Set Setting to 6-prong basket'));
  expect(screen.getByLabelText('Prongs').props.children).toBe(6);
  expect(screen.getByText(/updates automatically with the selected setting/i)).toBeTruthy();
  await fireEvent.press(screen.getByLabelText('Edit Ring size'));
  await fireEvent.changeText(screen.getByLabelText('Edit Ring size'), '7.25');
  await fireEvent.press(screen.getByLabelText('I reviewed these starting facts'));
  await fireEvent.press(screen.getByText('Save starting facts'));

  await waitFor(() => expect(g.saveDesignConfirmation).toHaveBeenCalledTimes(1));
  const audited = g.auditDesignConfirmation.mock.calls[0][0] as StudioDesignConfirmationReview;
  const facts = audited.factGroups.flatMap((group) => group.facts);
  expect(facts.find((fact) => fact.key === 'material')).toMatchObject({ path: 'metal.material', rawValue: 'gold', authority: 'suggested' });
  expect(facts.find((fact) => fact.path === 'stone.color.trade')).toMatchObject({ rawValue: 'Cornflower Blue', authority: 'designer_supplied' });
  expect(facts.find((fact) => fact.key === 'species')).toMatchObject({ path: 'stone.species', rawValue: 'sapphire', authority: 'estimated' });
  expect(facts.find((fact) => fact.key === 'style')).toMatchObject({ path: 'setting.style', rawValue: '6_prong_basket', authority: 'designer_supplied' });
  expect(facts.find((fact) => fact.path === 'ring_size.value')).toMatchObject({ rawValue: 7.25, authority: 'designer_supplied' });
  expect(facts.find((fact) => fact.key === 'template')).toMatchObject({ rawValue: 'solitaire', authority: 'estimated' });
});

test('replaces a stale 6-prong source question when the setting changes to 4-prong', async () => {
  const staleSettingReview: StudioDesignConfirmationReview = {
    ...review,
    factGroups: review.factGroups.map((group) => group.key !== 'setting' ? group : {
      ...group,
      facts: group.facts.map((fact) => fact.key === 'style'
        ? { ...fact, value: '6_prong_basket', rawValue: '6_prong_basket' }
        : fact.key === 'prong_count'
          ? { ...fact, value: '6', rawValue: 6 }
          : fact),
    }),
    unresolvedQuestions: [
      'Review 6_prong_basket setting with 6 prongs against the selected visual.',
    ],
  };
  const g = gateway({
    loadDesignConfirmation: jest.fn(async () => ({
      data: staleSettingReview, error: null, status: 200,
    })),
  });
  await render(<StudioConfirmWorkspace
    gateway={g}
    lineage={lineage}
    createdBy="designer"
    onSaved={jest.fn()}
  />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());

  expect(screen.getByText(
    /Review 6_prong_basket setting with 6 prongs against the selected visual/i,
  )).toBeTruthy();
  await fireEvent.press(screen.getByLabelText('Edit Setting'));
  await fireEvent.press(screen.getByLabelText('Set Setting to 4-prong basket'));

  expect(screen.queryByText(
    /Review 6_prong_basket setting with 6 prongs against the selected visual/i,
  )).toBeNull();
  expect(screen.getByText(
    '• Review the selected setting as 4-prong basket against the visual.',
  )).toBeTruthy();
  expect(screen.getByLabelText('Prongs').props.children).toBe(4);

  await fireEvent.press(screen.getByLabelText('I reviewed these starting facts'));
  await fireEvent.press(screen.getByText('Save starting facts'));
  await waitFor(() => expect(g.saveDesignConfirmation).toHaveBeenCalledTimes(1));
  const audited = g.auditDesignConfirmation.mock.calls[0][0] as StudioDesignConfirmationReview;
  expect(audited.unresolvedQuestions).toEqual([
    'Review the selected setting as 4-prong basket against the visual.',
  ]);
});

test('invalid numeric edits stay local and cannot reach audit or persistence', async () => {
  const g = gateway();
  await render(<StudioConfirmWorkspace gateway={g} lineage={lineage} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Ring size')).toBeTruthy());
  await fireEvent.press(screen.getByLabelText('Edit Ring size'));
  await fireEvent.changeText(screen.getByLabelText('Edit Ring size'), 'not-a-size');
  await fireEvent.press(screen.getByLabelText('I reviewed these starting facts'));
  expect(screen.getByText('Enter a valid value.')).toBeTruthy();
  expect(screen.getByText('Save starting facts').parent?.props.accessibilityState).toEqual({ disabled: true });
  await fireEvent.press(screen.getByText('Save starting facts'));
  expect(g.auditDesignConfirmation).not.toHaveBeenCalled();
  expect(g.saveDesignConfirmation).not.toHaveBeenCalled();
});

test('a save failure stays on Starting facts and does not navigate', async () => {
  const onSaved = jest.fn();
  const g = gateway({
    saveDesignConfirmation: jest.fn(async () => ({
      data: null,
      error: {
        code: 'NETWORK_ERROR', category: 'network', status: 0,
        message: 'provider detail that must stay hidden', retryable: true,
      },
      status: 0,
    })),
  });
  await render(<StudioConfirmWorkspace gateway={g} lineage={lineage} createdBy="designer" onSaved={onSaved} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  await fireEvent.press(screen.getByLabelText('I reviewed these starting facts'));
  await fireEvent.press(screen.getByText('Save starting facts'));
  await waitFor(() => expect(screen.getByText(/temporarily unavailable/i)).toBeTruthy());
  expect(onSaved).not.toHaveBeenCalled();
  expect(screen.queryByText(/provider detail/i)).toBeNull();
  expect(screen.getByText('Save starting facts')).toBeTruthy();
});

test('switching A to B clears A immediately and ignores a late A load', async () => {
  const a = deferred<any>();
  const b = deferred<any>();
  const load = jest.fn((request) => request.projectId === 'project_a' ? a.promise : b.promise);
  const g = gateway({ loadDesignConfirmation: load });
  const view = await render(<StudioConfirmWorkspace gateway={g} lineage={{ projectId: 'project_a', sourceAssetId: 'candidate_a' }} createdBy="designer" onSaved={jest.fn()} />);
  await view.rerender(<StudioConfirmWorkspace gateway={g} lineage={{ projectId: 'project_b', sourceAssetId: 'candidate_b' }} createdBy="designer" onSaved={jest.fn()} />);
  expect(screen.queryByText('Jewelry type')).toBeNull();
  const reviewB = { ...review, reviewId: 'review_b', factGroups: [{ key: 'design' as const, label: 'Design identity', facts: [{ key: 'template', label: 'B design', value: 'B', path: null, rawValue: 'B', authority: 'suggested' as const }] }] };
  await act(async () => b.resolve({ data: reviewB, error: null, status: 200 }));
  await waitFor(() => expect(screen.getByText('B design')).toBeTruthy());
  const reviewA = { ...review, reviewId: 'review_a', factGroups: [{ key: 'design' as const, label: 'Design identity', facts: [{ key: 'template', label: 'A design', value: 'A', path: null, rawValue: 'A', authority: 'suggested' as const }] }] };
  await act(async () => a.resolve({ data: reviewA, error: null, status: 200 }));
  expect(screen.queryByText('A design')).toBeNull();
  expect(screen.getByText('B design')).toBeTruthy();
});

test('switching lineage invalidates a prior audit and cannot save its late response', async () => {
  const lateAudit = deferred<any>();
  const save = jest.fn();
  const g = gateway({
    loadDesignConfirmation: jest.fn(async (request) => ({ data: { ...review, reviewId: `review_${request.projectId}` }, error: null, status: 200 })),
    auditDesignConfirmation: jest.fn(() => lateAudit.promise),
    saveDesignConfirmation: save,
  });
  const view = await render(<StudioConfirmWorkspace gateway={g} lineage={{ projectId: 'project_a', sourceAssetId: 'candidate_a' }} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  await fireEvent.press(screen.getByLabelText('I reviewed these starting facts'));
  await fireEvent.press(screen.getByText('Save starting facts'));
  await view.rerender(<StudioConfirmWorkspace gateway={g} lineage={{ projectId: 'project_b', sourceAssetId: 'candidate_b' }} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  await act(async () => lateAudit.resolve({ data: { auditId: 'review_project_a', status: 'pass', issues: [], review: { ...review, reviewId: 'review_project_a' } }, error: null, status: 200 }));
  expect(save).not.toHaveBeenCalled();
});

test('switching lineage after audit prevents a late save from navigating', async () => {
  const lateSave = deferred<any>();
  const onSaved = jest.fn();
  const g = gateway({
    loadDesignConfirmation: jest.fn(async (request) => ({ data: { ...review, reviewId: `review_${request.projectId}` }, error: null, status: 200 })),
    saveDesignConfirmation: jest.fn(() => lateSave.promise),
  });
  const view = await render(<StudioConfirmWorkspace gateway={g} lineage={{ projectId: 'project_a', sourceAssetId: 'candidate_a' }} createdBy="designer" onSaved={onSaved} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  await fireEvent.press(screen.getByLabelText('I reviewed these starting facts'));
  await fireEvent.press(screen.getByText('Save starting facts'));
  await waitFor(() => expect(g.saveDesignConfirmation).toHaveBeenCalledTimes(1));
  await view.rerender(<StudioConfirmWorkspace gateway={g} lineage={{ projectId: 'project_b', sourceAssetId: 'candidate_b' }} createdBy="designer" onSaved={onSaved} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  await act(async () => lateSave.resolve({ data: { confirmationId: 'confirmation_a' }, error: null, status: 201 }));
  expect(onSaved).not.toHaveBeenCalled();
});

test('a failed B load cannot leave A facts or a prior save path visible', async () => {
  const save = jest.fn();
  const g = gateway({
    loadDesignConfirmation: jest.fn(async (request) => request.projectId === 'project_a'
      ? { data: { ...review, reviewId: 'review_a' }, error: null, status: 200 }
      : { data: null, error: { code: 'LOAD_FAILED' }, status: 409 }),
    saveDesignConfirmation: save,
  });
  const view = await render(<StudioConfirmWorkspace gateway={g} lineage={{ projectId: 'project_a', sourceAssetId: 'candidate_a' }} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  await view.rerender(<StudioConfirmWorkspace gateway={g} lineage={{ projectId: 'project_b', sourceAssetId: 'candidate_b' }} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText(/could not review/i)).toBeTruthy());
  expect(screen.queryByText('Jewelry type')).toBeNull();
  await fireEvent.press(screen.getByText('Save starting facts'));
  expect(save).not.toHaveBeenCalled();
});
