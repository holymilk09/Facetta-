/// <reference types="jest" />

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { AuthenticatedImageProvider } from '../AuthenticatedImage';
import type { ProjectDetail, VisualAngleView } from '../trusted/types';
import { StudioAnglesWorkspace } from './StudioAnglesWorkspace';

const lineage = { projectId: 'project_1', sourceAssetId: 'asset_selected' };

const project = {
  id: 'project_1', root_id: 'project_1', title: 'Selected ring', collection: null,
  tags: [], owner: 'designer', state: 'refining', design_id: null, spec: null,
  active_asset_id: 'asset_selected', active_design_version: null,
  selected_candidate_asset_id: 'asset_selected', confirmable_pre_spec: true,
  active_revision: null, pinned_revision: null, revisions: [], assets: [],
  derived_assets: [], approval: null, factory_ready: false, factory_blockers: [],
  primary_revision_count: 1, has_factory_drawing: false,
  cover_asset_id: 'asset_selected', created_at: null, updated_at: null,
} as ProjectDetail;

const candidate = (view: VisualAngleView, index: number) => ({
  candidate_id: `candidate_${view}`,
  image_run_id: `run_${view}`,
  view,
  output_sha256: `${index}`.repeat(64),
  qa: {
    verdict: 'pass' as const,
    accepted: false,
    review_required: true,
    score: 1,
    summary: 'Ready for designer review.',
    failed_checks: [],
    warnings: [],
    checks: [],
  },
  routing: {
    run_id: `run_${view}`,
    attempt_count: 1,
    used_retry: false,
    used_fallback: false,
    cache_hit: false,
  },
  status: 'reviewing' as const,
  accepted_asset_id: null,
  preview_url: `https://test/${view}.png`,
});

const review = {
  angleSetId: 'angle_set_1',
  studioJobId: 'job_angles_1',
  lineage,
  sourceSha256: 'a'.repeat(64),
  status: 'reviewing' as const,
  expiresAt: '2026-07-20T00:00:00Z',
  candidates: [candidate('front', 1), candidate('three_quarter', 2), candidate('side', 3)],
  requestedOutputs: 3 as const,
  creditsPerOutput: 18,
  estimatedCredits: 54,
  billingPolicy: 'Charged only after saving all three.',
};

const renderAngles = (ui: React.ReactElement) => render(
  <AuthenticatedImageProvider
    allowedOrigin="https://test"
    headers={{ Authorization: 'Bearer first-party-token' }}>
    {ui}
  </AuthenticatedImageProvider>,
);

describe('StudioAnglesWorkspace', () => {
  test('fails closed until one generated design is selected', async () => {
    await renderAngles(<StudioAnglesWorkspace
      gateway={{} as any}
      lineage={null}
      createdBy="designer"
      onSaved={jest.fn()}
    />);

    expect(screen.getByText('Choose a design first')).toBeTruthy();
    expect(screen.getByText(/after you select one generated design/i)).toBeTruthy();
  });

  test('explains the three fixed views and transparent atomic price', async () => {
    const resumeVisualAngleSet = jest.fn(async () => ({ data: null, error: null, status: 200 }));
    const onContinueRefining = jest.fn();
    await renderAngles(<StudioAnglesWorkspace
      gateway={{
        resumeVisualAngleSet,
        createVisualAngleSet: jest.fn(),
        acceptVisualAngleSet: jest.fn(),
        discardVisualAngleSet: jest.fn(),
        assetImageUrl: () => 'https://test/source.png',
      } as any}
      lineage={lineage}
      createdBy="designer"
      onSaved={jest.fn()}
      onContinueRefining={onContinueRefining}
    />);

    expect(screen.getByText('Create all three useful views.')).toBeTruthy();
    expect(screen.getByText('Front')).toBeTruthy();
    expect(screen.getByText('Three-quarter')).toBeTruthy();
    expect(screen.getByText('Side')).toBeTruthy();
    expect(screen.getByText('3 views × 18 credits = 54 credits')).toBeTruthy();
    expect(screen.getByText(/charged only if you save all three/i)).toBeTruthy();
    expect(resumeVisualAngleSet).toHaveBeenCalledWith(lineage, 'designer', undefined);
    await fireEvent.press(screen.getByText('Skip for now'));
    expect(onContinueRefining).toHaveBeenCalledTimes(1);
  });

  test('generates one temporary set and saves only after all four comparison images load', async () => {
    const createVisualAngleSet = jest.fn(async () => ({ data: review, error: null, status: 201 }));
    const acceptVisualAngleSet = jest.fn(async () => ({
      data: {
        review: {
          ...review,
          status: 'accepted' as const,
          candidates: review.candidates.map((item, index) => ({
            ...item,
            status: 'accepted' as const,
            accepted_asset_id: `angle_asset_${index + 1}`,
          })),
        },
        project,
      },
      error: null,
      status: 201,
    }));
    const onSaved = jest.fn();

    await renderAngles(<StudioAnglesWorkspace
      gateway={{
        resumeVisualAngleSet: jest.fn(async () => ({ data: null, error: null, status: 200 })),
        createVisualAngleSet,
        acceptVisualAngleSet,
        discardVisualAngleSet: jest.fn(),
        assetImageUrl: () => 'https://test/source.png',
      } as any}
      lineage={lineage}
      createdBy="designer"
      onSaved={onSaved}
      imageRequestHeaders={{ Authorization: 'Bearer first-party-token' }}
    />);

    await fireEvent.press(screen.getByText('Create all 3 views'));
    expect(createVisualAngleSet).toHaveBeenCalledWith(lineage, 'designer');
    expect(await screen.findByText('Check the design from three key angles.')).toBeTruthy();
    expect(screen.getByText('3 views × 18 credits = 54 credits when saved')).toBeTruthy();
    expect(screen.getByText('Discarding this set costs 0 credits.')).toBeTruthy();

    await fireEvent.press(screen.getByText('Save all 3 views'));
    expect(acceptVisualAngleSet).not.toHaveBeenCalled();

    await fireEvent(screen.getByLabelText('Selected design source'), 'load');
    await fireEvent(screen.getByLabelText('Front angle preview'), 'load');
    await fireEvent(screen.getByLabelText('Three-quarter angle preview'), 'load');
    await fireEvent(screen.getByLabelText('Side angle preview'), 'load');
    await fireEvent.press(screen.getByText('Save all 3 views'));

    await waitFor(() => expect(acceptVisualAngleSet).toHaveBeenCalledWith('angle_set_1', 'designer'));
    expect(onSaved).toHaveBeenCalledWith(project);
    expect(screen.getByText('Your three views are ready.')).toBeTruthy();
    expect(screen.getByText(/They did not replace it/i)).toBeTruthy();
    expect(screen.getByLabelText('Front saved view')).toBeTruthy();
    expect(screen.getByLabelText('Three-quarter saved view')).toBeTruthy();
    expect(screen.getByLabelText('Side saved view')).toBeTruthy();
  });

  test('restores a durable Activity review by job id and discards it without charging', async () => {
    const resumeVisualAngleSet = jest.fn(async () => ({ data: review, error: null, status: 200 }));
    const discardVisualAngleSet = jest.fn(async () => ({
      data: {
        review: {
          ...review,
          status: 'discarded' as const,
          candidates: review.candidates.map((item) => ({ ...item, status: 'discarded' as const })),
        },
        project: null,
      },
      error: null,
      status: 200,
    }));

    await renderAngles(<StudioAnglesWorkspace
      gateway={{
        resumeVisualAngleSet,
        createVisualAngleSet: jest.fn(),
        acceptVisualAngleSet: jest.fn(),
        discardVisualAngleSet,
        assetImageUrl: () => 'https://test/source.png',
      } as any}
      lineage={lineage}
      createdBy="designer"
      onSaved={jest.fn()}
      resumeReviewJobId="job_angles_1"
    />);

    expect(await screen.findByText('Check the design from three key angles.')).toBeTruthy();
    expect(resumeVisualAngleSet).toHaveBeenCalledWith(lineage, 'designer', 'job_angles_1');
    await fireEvent.press(screen.getByText('Discard set'));
    expect(discardVisualAngleSet).toHaveBeenCalledWith('angle_set_1', 'designer');
    expect(screen.getByText('Angle set discarded. Nothing was saved or charged.')).toBeTruthy();
    expect(screen.getByText('Create all three useful views.')).toBeTruthy();
  });
});
