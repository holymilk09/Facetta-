/// <reference types="jest" />

import React from 'react';
import {
  fireEvent, render, screen, waitFor,
} from '@testing-library/react-native';

import { AuthenticatedImageProvider } from '../AuthenticatedImage';
import type { PreviewCandidate } from './contracts';
import { StudioVaryWorkspace } from './StudioVaryWorkspace';
import type { ProjectDetail } from '../trusted/types';

const lineage = { projectId: 'project_1', sourceAssetId: 'asset_7' };

const childProject = {
  id: 'child_project', root_id: 'child_project', title: 'Rose gold direction',
  active_asset_id: 'child_asset', active_design_version: null,
} as ProjectDetail;

const secondChildProject = {
  id: 'second_child_project', root_id: 'second_child_project', title: 'Satin direction',
  active_asset_id: 'second_child_asset', active_design_version: null,
} as ProjectDetail;

function candidate(index: number): PreviewCandidate {
  return {
    id: `candidate_${index}`, jobId: `job_${index}`, sourceRevisionId: 'asset_7',
    assetUrl: `https://test/candidate-${index}.png`, verdict: 'pass',
    status: 'pending_review', checks: [], temporary: true, expiresAt: null,
    decision: null, decidedAt: null, canonicalRevisionId: null,
  };
}

function previewResult(index: number) {
  return {
    data: {
      candidate: candidate(index), lineage,
      instruction: 'Explore warmer rose gold', scope: 'appearance' as const,
    },
    error: null,
    status: 201,
  } as const;
}

function withAuthenticatedImages(ui: React.ReactElement) {
  return (
    <AuthenticatedImageProvider
      allowedOrigin="https://test"
      headers={{ Authorization: 'Bearer studio-test-token' }}>
      {ui}
    </AuthenticatedImageProvider>
  );
}

test('generates one to four source-anchored visual directions without a naming form', async () => {
  const previewVisualRefine = jest.fn(async (request: { variant?: number }) => (
    previewResult((request.variant ?? 0) + 1)
  ));
  await render(withAuthenticatedImages(
    <StudioVaryWorkspace
      gateway={{
        previewVisualRefine,
        saveVisualPreviewAsVariation: jest.fn(),
        discardVisualRefine: jest.fn(),
      } as any}
      lineage={lineage}
      sourceImageUrl="https://test/source.png"
      createdBy="designer_1"
      onCreated={jest.fn()}
    />,
  ));

  expect(screen.queryByLabelText('Variation name')).toBeNull();
  expect(screen.queryByText('Create variation')).toBeNull();
  await fireEvent.changeText(
    screen.getByLabelText('Variation direction'),
    'Explore warmer rose gold',
  );
  await fireEvent.press(screen.getByLabelText('3 variations'));
  await fireEvent.press(screen.getByText('Generate 3 variations'));

  await waitFor(() => expect(previewVisualRefine).toHaveBeenCalledTimes(3));
  expect(previewVisualRefine).toHaveBeenNthCalledWith(1, {
    ...lineage, createdBy: 'designer_1', instruction: 'Explore warmer rose gold',
    scope: 'appearance', variant: 0, jobAction: 'vary',
  });
  expect(previewVisualRefine).toHaveBeenNthCalledWith(2, {
    ...lineage, createdBy: 'designer_1', instruction: 'Explore warmer rose gold',
    scope: 'appearance', variant: 1, jobAction: 'vary',
  });
  expect(previewVisualRefine).toHaveBeenNthCalledWith(3, {
    ...lineage, createdBy: 'designer_1', instruction: 'Explore warmer rose gold',
    scope: 'appearance', variant: 2, jobAction: 'vary',
  });
  expect(await screen.findByText('Choose the directions you want to keep.')).toBeTruthy();
  expect(screen.queryByLabelText('Variation name')).toBeNull();
});

test('keeps multiple reviewed candidates independently and charges only saved outputs', async () => {
  const previewVisualRefine = jest.fn(async (request: { variant?: number }) => (
    previewResult((request.variant ?? 0) + 1)
  ));
  const discardVisualRefine = jest.fn();
  const saveVisualPreviewAsVariation = jest.fn(async (
    { candidateId }: { candidateId: string },
  ) => ({
    data: {
      candidate: {
        ...candidate(candidateId === 'candidate_2' ? 2 : 1),
        status: 'saved_as_variation' as const,
      },
      project: candidateId === 'candidate_2' ? childProject : secondChildProject,
    },
    error: null,
    status: 201,
  }));
  const onCreated = jest.fn();
  await render(withAuthenticatedImages(
    <StudioVaryWorkspace
      gateway={{
        previewVisualRefine, saveVisualPreviewAsVariation, discardVisualRefine,
      } as any}
      lineage={lineage}
      sourceImageUrl="https://test/source.png"
      createdBy="designer_1"
      onCreated={onCreated}
    />,
  ));

  await fireEvent.changeText(
    screen.getByLabelText('Variation direction'),
    'Explore warmer rose gold',
  );
  await fireEvent.press(screen.getByText('Generate 2 variations'));
  expect(await screen.findByText('Choose the directions you want to keep.')).toBeTruthy();
  await fireEvent(screen.getByLabelText('Current saved design'), 'load');
  await fireEvent(screen.getByLabelText('Variation direction 1'), 'load');
  await fireEvent(screen.getByLabelText('Variation direction 2'), 'load');
  await fireEvent.press(screen.getByLabelText('Keep direction 2 as a variation'));

  await waitFor(() => expect(saveVisualPreviewAsVariation).toHaveBeenCalledWith({
    candidateId: 'candidate_2', createdBy: 'designer_1',
    label: 'Variation 2 · Explore warmer rose gold',
  }));
  expect(discardVisualRefine).not.toHaveBeenCalled();
  expect(onCreated).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Variation direction 1')).toBeTruthy();
  expect(screen.queryByLabelText('Variation direction 2')).toBeNull();
  expect(screen.getByLabelText('Saved variation credits').props.children.join(''))
    .toBe('1 saved output × 20 credits = 20 credits');

  await fireEvent.press(screen.getByLabelText('Keep direction 1 as a variation'));
  await waitFor(() => expect(saveVisualPreviewAsVariation).toHaveBeenCalledWith({
    candidateId: 'candidate_1', createdBy: 'designer_1',
    label: 'Variation 1 · Explore warmer rose gold',
  }));
  expect(discardVisualRefine).not.toHaveBeenCalled();
  expect(onCreated).not.toHaveBeenCalled();
  expect(screen.queryByLabelText('Variation direction 1')).toBeNull();
  expect(screen.getByLabelText('Saved variation credits').props.children.join(''))
    .toBe('2 saved outputs × 20 credits = 40 credits');
  expect(screen.getByText('All generated directions have been resolved.')).toBeTruthy();

  await fireEvent.press(screen.getByLabelText('Finish variation review'));
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(secondChildProject));
  expect(discardVisualRefine).not.toHaveBeenCalled();
});

test('finishes explicitly by discarding only the remaining unkept previews', async () => {
  const previewVisualRefine = jest.fn(async (request: { variant?: number }) => (
    previewResult((request.variant ?? 0) + 1)
  ));
  const discardVisualRefine = jest.fn(async ({ candidateId }: { candidateId: string }) => ({
    data: { ...candidate(1), id: candidateId, status: 'discarded' as const },
    error: null,
    status: 200,
  }));
  const saveVisualPreviewAsVariation = jest.fn(async () => ({
    data: {
      candidate: { ...candidate(2), status: 'saved_as_variation' as const },
      project: childProject,
    },
    error: null,
    status: 201,
  }));
  const onCreated = jest.fn();
  await render(withAuthenticatedImages(
    <StudioVaryWorkspace
      gateway={{
        previewVisualRefine, saveVisualPreviewAsVariation, discardVisualRefine,
      } as any}
      lineage={lineage}
      sourceImageUrl="https://test/source.png"
      createdBy="designer_1"
      onCreated={onCreated}
    />,
  ));

  await fireEvent.changeText(screen.getByLabelText('Variation direction'), 'Try a satin finish');
  await fireEvent.press(screen.getByText('Generate 2 variations'));
  expect(await screen.findByText('Choose the directions you want to keep.')).toBeTruthy();
  await fireEvent(screen.getByLabelText('Current saved design'), 'load');
  await fireEvent(screen.getByLabelText('Variation direction 1'), 'load');
  await fireEvent(screen.getByLabelText('Variation direction 2'), 'load');
  await fireEvent.press(screen.getByLabelText('Keep direction 2 as a variation'));
  await waitFor(() => expect(screen.queryByLabelText('Variation direction 2')).toBeNull());

  await fireEvent.press(screen.getByLabelText('Finish variation review'));
  await waitFor(() => expect(discardVisualRefine).toHaveBeenCalledTimes(1));
  expect(discardVisualRefine).toHaveBeenCalledWith({
    candidateId: 'candidate_1', createdBy: 'designer_1',
  });
  expect(onCreated).toHaveBeenCalledWith(childProject);
});

test('discards temporary candidates before starting over', async () => {
  const previewVisualRefine = jest.fn(async (request: { variant?: number }) => (
    previewResult((request.variant ?? 0) + 1)
  ));
  const discardVisualRefine = jest.fn(async ({ candidateId }: { candidateId: string }) => ({
    data: { ...candidate(1), id: candidateId, status: 'discarded' as const },
    error: null,
    status: 200,
  }));
  await render(withAuthenticatedImages(
    <StudioVaryWorkspace
      gateway={{
        previewVisualRefine,
        saveVisualPreviewAsVariation: jest.fn(),
        discardVisualRefine,
      } as any}
      lineage={lineage}
      sourceImageUrl="https://test/source.png"
      createdBy="designer_1"
      onCreated={jest.fn()}
    />,
  ));

  await fireEvent.changeText(screen.getByLabelText('Variation direction'), 'Try a softer finish');
  await fireEvent.press(screen.getByText('Generate 2 variations'));
  expect(await screen.findByText('Choose the directions you want to keep.')).toBeTruthy();
  await fireEvent.press(screen.getByText('Discard and try another direction'));

  await waitFor(() => expect(discardVisualRefine).toHaveBeenCalledTimes(2));
  expect(discardVisualRefine).toHaveBeenCalledWith({
    candidateId: 'candidate_1', createdBy: 'designer_1',
  });
  expect(discardVisualRefine).toHaveBeenCalledWith({
    candidateId: 'candidate_2', createdBy: 'designer_1',
  });
  expect(await screen.findByText('What direction should we explore?')).toBeTruthy();
});

test('removes successful discards but keeps failed candidates visible for retry', async () => {
  const previewVisualRefine = jest.fn(async (request: { variant?: number }) => (
    previewResult((request.variant ?? 0) + 1)
  ));
  let candidateTwoAttempts = 0;
  const discardVisualRefine = jest.fn(async ({ candidateId }: { candidateId: string }) => {
    if (candidateId === 'candidate_2' && candidateTwoAttempts === 0) {
      candidateTwoAttempts += 1;
      return {
        data: null,
        error: {
          code: 'NETWORK_ERROR', message: 'offline', category: 'network' as const,
          status: 0, retryable: true,
        },
        status: 0,
      };
    }
    return {
      data: { ...candidate(1), id: candidateId, status: 'discarded' as const },
      error: null,
      status: 200,
    };
  });
  await render(withAuthenticatedImages(
    <StudioVaryWorkspace
      gateway={{
        previewVisualRefine,
        saveVisualPreviewAsVariation: jest.fn(),
        discardVisualRefine,
      } as any}
      lineage={lineage}
      sourceImageUrl="https://test/source.png"
      createdBy="designer_1"
      onCreated={jest.fn()}
    />,
  ));

  await fireEvent.changeText(screen.getByLabelText('Variation direction'), 'Explore three options');
  await fireEvent.press(screen.getByLabelText('3 variations'));
  await fireEvent.press(screen.getByText('Generate 3 variations'));
  expect(await screen.findByText('Choose the directions you want to keep.')).toBeTruthy();
  await fireEvent.press(screen.getByText('Discard and try another direction'));

  await waitFor(() => expect(discardVisualRefine).toHaveBeenCalledTimes(3));
  expect(screen.queryByLabelText('Variation direction 1')).toBeNull();
  expect(screen.getByLabelText('Variation direction 2')).toBeTruthy();
  expect(screen.queryByLabelText('Variation direction 3')).toBeNull();
  expect(screen.getByText(
    '2 previews discarded. 1 still need review. Facetta could not connect. Check your connection and try again.',
  )).toBeTruthy();

  await fireEvent.press(screen.getByText('Discard and try another direction'));
  await waitFor(() => expect(discardVisualRefine).toHaveBeenCalledTimes(4));
  expect(await screen.findByText('What direction should we explore?')).toBeTruthy();
});

test('resumes a Vary review by its durable job identity', async () => {
  const resumeRefine = jest.fn(async () => ({
    data: {
      kind: 'visual' as const, candidate: candidate(1),
      understoodAs: 'A pending visual preview was restored for review.',
    },
    error: null,
    status: 200,
  }));
  await render(withAuthenticatedImages(
    <StudioVaryWorkspace
      gateway={{
        previewVisualRefine: jest.fn(), resumeRefine,
        saveVisualPreviewAsVariation: jest.fn(), discardVisualRefine: jest.fn(),
      } as any}
      lineage={lineage}
      sourceImageUrl="https://test/source.png"
      createdBy="designer_1"
      resumeReviewJobId="vary_job_1"
      onCreated={jest.fn()}
    />,
  ));

  await waitFor(() => expect(resumeRefine).toHaveBeenCalledWith(
    lineage, 'designer_1', 'vary_job_1', 'vary',
  ));
  expect(await screen.findByText('Choose the directions you want to keep.')).toBeTruthy();
});

test('leaves late durable candidates in Activity instead of silently discarding on unmount', async () => {
  let resolvePreview: ((result: ReturnType<typeof previewResult>) => void) | undefined;
  const previewVisualRefine = jest.fn(() => new Promise<ReturnType<typeof previewResult>>((resolve) => {
    resolvePreview = resolve;
  }));
  const discardVisualRefine = jest.fn();
  const view = await render(withAuthenticatedImages(
    <StudioVaryWorkspace
      gateway={{
        previewVisualRefine,
        saveVisualPreviewAsVariation: jest.fn(),
        discardVisualRefine,
      } as any}
      lineage={lineage}
      sourceImageUrl="https://test/source.png"
      createdBy="designer_1"
      onCreated={jest.fn()}
    />,
  ));

  await fireEvent.changeText(screen.getByLabelText('Variation direction'), 'Explore one direction');
  await fireEvent.press(screen.getByLabelText('1 variation'));
  await fireEvent.press(screen.getByText('Generate 1 variation'));
  await waitFor(() => expect(previewVisualRefine).toHaveBeenCalledTimes(1));
  view.unmount();
  resolvePreview?.(previewResult(1));
  await Promise.resolve();
  expect(discardVisualRefine).not.toHaveBeenCalled();
});

test('fails closed without a selected revision', async () => {
  await render(<StudioVaryWorkspace
    gateway={{
      previewVisualRefine: jest.fn(), saveVisualPreviewAsVariation: jest.fn(),
      discardVisualRefine: jest.fn(),
    } as any}
    lineage={null}
    createdBy="designer_1"
    onCreated={jest.fn()}
  />);
  expect(screen.getByText('Choose a saved direction first')).toBeTruthy();
  expect(screen.queryByText(/Generate \d variation/)).toBeNull();
});
