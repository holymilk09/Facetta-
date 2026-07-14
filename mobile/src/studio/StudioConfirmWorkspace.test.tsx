/// <reference types="jest" />
import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
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
    { key: 'species', label: 'Stone', value: 'sapphire', path: null, rawValue: 'sapphire', authority: 'estimated' },
    { key: 'color', label: 'Color', value: 'Royal Blue', path: 'stone.color.trade', rawValue: 'Royal Blue', authority: 'estimated' },
  ] }, { key: 'setting', label: 'Setting', facts: [
    { key: 'style', label: 'Setting', value: '4_prong_basket', path: null, rawValue: '4_prong_basket', authority: 'suggested' },
  ] }, { key: 'metal', label: 'Metal', facts: [
    { key: 'material', label: 'Metal', value: 'gold', path: null, rawValue: 'gold', authority: 'suggested' },
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

test('loads projected facts and renders all designer authority labels without internal payloads', async () => {
  const withQuestion = {
    ...review,
    unresolvedQuestions: ['Confirm the band profile against the selected visual.'],
    sourceReview: { eligible: false, state: 'not_ready' as const, reason: 'Answer the remaining source questions first.' },
  };
  await render(<StudioConfirmWorkspace gateway={gateway({ loadDesignConfirmation: jest.fn(async () => ({ data: withQuestion, error: null, status: 200 })) })} lineage={lineage} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Exact selected visual')).toBeTruthy());
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

test('edits independent facts while keeping coupled material, setting, and dense identity read-only', async () => {
  const g = gateway();
  await render(<StudioConfirmWorkspace gateway={g} lineage={lineage} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());

  expect(screen.queryByLabelText('Edit Metal')).toBeNull();
  expect(screen.queryByLabelText('Edit Stone')).toBeNull();
  await fireEvent.press(screen.getByLabelText('Edit Color'));
  await fireEvent.changeText(screen.getByLabelText('Edit Color'), 'Cornflower Blue');
  expect(screen.queryByLabelText('Edit Setting')).toBeNull();
  await fireEvent.press(screen.getByLabelText('Edit Ring size'));
  await fireEvent.changeText(screen.getByLabelText('Edit Ring size'), '7.25');
  await fireEvent.press(screen.getByLabelText('I reviewed these starting facts'));
  await fireEvent.press(screen.getByText('Save starting facts'));

  await waitFor(() => expect(g.saveDesignConfirmation).toHaveBeenCalledTimes(1));
  const audited = g.auditDesignConfirmation.mock.calls[0][0] as StudioDesignConfirmationReview;
  const facts = audited.factGroups.flatMap((group) => group.facts);
  expect(facts.find((fact) => fact.key === 'material')).toMatchObject({ path: null, rawValue: 'gold', authority: 'suggested' });
  expect(facts.find((fact) => fact.path === 'stone.color.trade')).toMatchObject({ rawValue: 'Cornflower Blue', authority: 'designer_supplied' });
  expect(facts.find((fact) => fact.key === 'species')).toMatchObject({ path: null, rawValue: 'sapphire', authority: 'estimated' });
  expect(facts.find((fact) => fact.key === 'style')).toMatchObject({ path: null, rawValue: '4_prong_basket', authority: 'suggested' });
  expect(facts.find((fact) => fact.path === 'ring_size.value')).toMatchObject({ rawValue: 7.25, authority: 'designer_supplied' });
  expect(facts.find((fact) => fact.key === 'template')).toMatchObject({ rawValue: 'solitaire', authority: 'estimated' });
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
  await waitFor(() => expect(screen.getByText(/could not connect/i)).toBeTruthy());
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
