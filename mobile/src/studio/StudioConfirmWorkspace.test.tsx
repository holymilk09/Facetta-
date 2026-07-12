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
    { key: 'jewelry_type', label: 'Jewelry type', value: 'ring', authority: 'suggested' },
    { key: 'template', label: 'Design type', value: 'solitaire', authority: 'estimated' },
  ] }, { key: 'ring_fit', label: 'Sizing and proportions', facts: [
    { key: 'ring_size', label: 'Ring size', value: 'US 6.5', authority: 'designer_supplied' },
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
  expect(screen.queryByText('Create immutable Design v1')).toBeNull();
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
  expect(screen.queryByLabelText('Jewelry type: Measured or supplied')).toBeNull();
  expect(screen.queryByText(/hidden_review|continuation|project_1|asset_7|provider|factory|QA/i)).toBeNull();
});

test('cannot review or save without explicit acknowledgement of image-derived suggestions', async () => {
  const g = gateway();
  await render(<StudioConfirmWorkspace gateway={g} lineage={lineage} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  await fireEvent.press(screen.getByText('Check Design v1 readiness'));
  await fireEvent.press(screen.getByText('Create immutable Design v1'));
  expect(g.auditDesignConfirmation).not.toHaveBeenCalled();
  expect(g.saveDesignConfirmation).not.toHaveBeenCalled();
  expect(screen.getByText(/image-derived suggestions/i)).toBeTruthy();
  expect(screen.getByText(/Advanced Specifications/i)).toBeTruthy();
});

test('failed audit disables Save', async () => {
  const save = jest.fn();
  const g = gateway({
    auditDesignConfirmation: jest.fn(async (next) => ({ data: { auditId: 'a', status: 'fail', issues: ['Answer the remaining source questions.'], review: next }, error: null, status: 200 })),
    saveDesignConfirmation: save,
  });
  await render(<StudioConfirmWorkspace gateway={g} lineage={lineage} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  await fireEvent.press(screen.getByLabelText('I reviewed the image-derived suggestions'));
  await fireEvent.press(screen.getByText('Check Design v1 readiness'));
  await waitFor(() => expect(screen.getByText(/Answer the remaining/i)).toBeTruthy());
  await fireEvent.press(screen.getByText('Create immutable Design v1'));
  expect(save).not.toHaveBeenCalled();
});

test('audits the read-only projection, saves, and invokes callback', async () => {
  const g = gateway(); const onSaved = jest.fn();
  await render(<StudioConfirmWorkspace gateway={g} lineage={lineage} createdBy="designer" onSaved={onSaved} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  await fireEvent.press(screen.getByLabelText('I reviewed the image-derived suggestions'));
  await fireEvent.press(screen.getByText('Check Design v1 readiness'));
  await waitFor(() => expect(screen.getByText(/Ready to create immutable/i)).toBeTruthy());
  await fireEvent.press(screen.getByText('Create immutable Design v1'));
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ confirmationId: 'confirmation_1' })));
  const audited = g.auditDesignConfirmation.mock.calls[0][0];
  expect(audited.factGroups[0].facts[0].authority).toBe('suggested');
});

test('switching A to B clears A immediately and ignores a late A load', async () => {
  const a = deferred<any>();
  const b = deferred<any>();
  const load = jest.fn((request) => request.projectId === 'project_a' ? a.promise : b.promise);
  const g = gateway({ loadDesignConfirmation: load });
  const view = await render(<StudioConfirmWorkspace gateway={g} lineage={{ projectId: 'project_a', sourceAssetId: 'candidate_a' }} createdBy="designer" onSaved={jest.fn()} />);
  await view.rerender(<StudioConfirmWorkspace gateway={g} lineage={{ projectId: 'project_b', sourceAssetId: 'candidate_b' }} createdBy="designer" onSaved={jest.fn()} />);
  expect(screen.queryByText('Jewelry type')).toBeNull();
  const reviewB = { ...review, reviewId: 'review_b', factGroups: [{ key: 'design' as const, label: 'Design identity', facts: [{ key: 'template', label: 'B design', value: 'B', authority: 'suggested' as const }] }] };
  await act(async () => b.resolve({ data: reviewB, error: null, status: 200 }));
  await waitFor(() => expect(screen.getByText('B design')).toBeTruthy());
  const reviewA = { ...review, reviewId: 'review_a', factGroups: [{ key: 'design' as const, label: 'Design identity', facts: [{ key: 'template', label: 'A design', value: 'A', authority: 'suggested' as const }] }] };
  await act(async () => a.resolve({ data: reviewA, error: null, status: 200 }));
  expect(screen.queryByText('A design')).toBeNull();
  expect(screen.getByText('B design')).toBeTruthy();
});

test('switching lineage invalidates a prior audit and ignores its late response', async () => {
  const lateAudit = deferred<any>();
  const save = jest.fn();
  const g = gateway({
    loadDesignConfirmation: jest.fn(async (request) => ({ data: { ...review, reviewId: `review_${request.projectId}` }, error: null, status: 200 })),
    auditDesignConfirmation: jest.fn(() => lateAudit.promise),
    saveDesignConfirmation: save,
  });
  const view = await render(<StudioConfirmWorkspace gateway={g} lineage={{ projectId: 'project_a', sourceAssetId: 'candidate_a' }} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  await fireEvent.press(screen.getByLabelText('I reviewed the image-derived suggestions'));
  await fireEvent.press(screen.getByText('Check Design v1 readiness'));
  await view.rerender(<StudioConfirmWorkspace gateway={g} lineage={{ projectId: 'project_b', sourceAssetId: 'candidate_b' }} createdBy="designer" onSaved={jest.fn()} />);
  await waitFor(() => expect(screen.getByText('Jewelry type')).toBeTruthy());
  await act(async () => lateAudit.resolve({ data: { auditId: 'review_project_a', status: 'pass', issues: [], review: { ...review, reviewId: 'review_project_a' } }, error: null, status: 200 }));
  expect(screen.queryByText(/Ready to create immutable/i)).toBeNull();
  await fireEvent.press(screen.getByText('Create immutable Design v1'));
  expect(save).not.toHaveBeenCalled();
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
  await fireEvent.press(screen.getByText('Create immutable Design v1'));
  expect(save).not.toHaveBeenCalled();
});
