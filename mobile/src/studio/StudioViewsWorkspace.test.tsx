import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import type { ProjectDetail } from '../trusted/types';
import { StudioViewsWorkspace } from './StudioViewsWorkspace';
import { AuthenticatedImageProvider } from '../AuthenticatedImage';

const lineage = {
  projectId: 'project_1', sourceAssetId: 'asset_7', sourceDesignVersion: 4,
};

const project = {
  id: 'project_1', root_id: 'project_1', title: 'Orbit', collection: null,
  tags: [], owner: 'designer', state: 'refining', design_id: 'design_1', spec: {},
  active_asset_id: 'asset_7', active_design_version: 4, active_revision: null,
  pinned_revision: null, revisions: [], assets: [], derived_assets: [], approval: null,
  factory_ready: false, factory_blockers: [], primary_revision_count: 4,
  has_factory_drawing: false, cover_asset_id: 'asset_7', created_at: null, updated_at: null,
} as ProjectDetail;

const preview = {
  candidateId: 'candidate_view', runId: 'run_view', previewUrl: 'https://test/view.png',
  view: 'front' as const, lineage, verdict: 'pass' as const,
  checks: [{ id: 'geometry', label: 'Geometry', verdict: 'pass' as const, detail: 'Matched.' }],
};

describe('StudioViewsWorkspace', () => {
  test('fails closed without an exact saved revision', async () => {
    await render(
      <AuthenticatedImageProvider allowedOrigin="https://test" headers={{ Authorization: 'Bearer first-party-token' }}>
        <StudioViewsWorkspace
          gateway={{
            previewLineArtView: jest.fn(), acceptLineArtView: jest.fn(), discardLineArtView: jest.fn(),
          }}
          lineage={null}
          createdBy="designer"
          onSaved={jest.fn()}
        />
      </AuthenticatedImageProvider>,
    );
    expect(screen.getByText('Choose a saved direction first')).toBeTruthy();
  });

  test('previews from exact lineage and saves only after explicit review', async () => {
    const onSaved = jest.fn();
    const previewLineArtView = jest.fn(async () => ({ data: preview, error: null, status: 202 }));
    const acceptLineArtView = jest.fn(async () => ({
      data: { preview, project }, error: null, status: 201,
    }));
    await render(
      <AuthenticatedImageProvider allowedOrigin="https://test" headers={{ Authorization: 'Bearer first-party-token' }}>
        <StudioViewsWorkspace
          gateway={{ previewLineArtView, acceptLineArtView, discardLineArtView: jest.fn() } as any}
          lineage={lineage}
          createdBy="designer"
          onSaved={onSaved}
          imageRequestHeaders={{ Authorization: 'Bearer first-party-token' }}
        />
      </AuthenticatedImageProvider>,
    );

    expect(screen.getByText('1 requested output × 15 credits = estimated 15 credits')).toBeTruthy();
    await act(async () => { fireEvent.press(screen.getByText('Front')); });
    await act(async () => { fireEvent.press(screen.getByText('Preview view')); });
    expect(await screen.findByText('Your design is still unchanged.')).toBeTruthy();
    expect(previewLineArtView).toHaveBeenCalledWith({ ...lineage, createdBy: 'designer', view: 'front' });
    expect(screen.getByLabelText('Temporary front view').props.source.headers).toEqual({
      Authorization: 'Bearer first-party-token',
    });
    expect(onSaved).not.toHaveBeenCalled();

    await act(async () => { fireEvent.press(screen.getByText('Save view')); });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(project));
    expect(screen.getByText('View saved beside the design. The active design revision did not change.')).toBeTruthy();
  });

  test('disables saving when fidelity checks reject the preview', async () => {
    const acceptLineArtView = jest.fn();
    await render(
      <StudioViewsWorkspace
        gateway={{
          previewLineArtView: jest.fn(async () => ({
            data: { ...preview, verdict: 'fail' as const }, error: null, status: 202,
          })),
          acceptLineArtView,
          discardLineArtView: jest.fn(),
        } as any}
        lineage={lineage}
        createdBy="designer"
        onSaved={jest.fn()}
      />,
    );
    await act(async () => { fireEvent.press(screen.getByText('Preview view')); });
    fireEvent.press(await screen.findByText('Save view'));
    expect(acceptLineArtView).not.toHaveBeenCalled();
    expect(screen.getByText('This view cannot be saved')).toBeTruthy();
  });
});
