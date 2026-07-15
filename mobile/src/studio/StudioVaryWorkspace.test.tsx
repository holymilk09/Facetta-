/// <reference types="jest" />

import React from 'react';
import {
  act, fireEvent, render, screen, waitFor,
} from '@testing-library/react-native';

import { StudioVaryWorkspace } from './StudioVaryWorkspace';

const project = {
  root_id: 'child_project', active_asset_id: 'child_asset', active_design_version: null,
} as any;

const CURRENT_SOURCE_SHA256 = '7'.repeat(64);

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

function currentLineage(sourceAssetId = 'asset_7', sourceRevision = 7) {
  return {
    mode: 'current' as const,
    projectId: 'project_1',
    sourceAssetId,
    sourceDesignVersion: null,
    sourceSha256: CURRENT_SOURCE_SHA256,
    expectedActiveAssetId: sourceAssetId,
    expectedActiveDesignVersion: null,
    sourceRevision,
  };
}

test('branches only the hidden exact source and opens the child variation', async () => {
  const createOperationId = jest.fn()
    .mockReturnValueOnce('vary:request-0001')
    .mockReturnValueOnce('vary:request-0002');
  const saveRevisionAsVariation = jest.fn(async () => ({
    data: {
      status: 'variation_created', family_id: 'family_1', variation_index: 2,
      source_project_id: 'project_1', source_asset_id: 'asset_7', project,
    },
    error: null,
    status: 201,
  }));
  const onCreated = jest.fn();
  const onContinueRefining = jest.fn();
  const onSelectDestination = jest.fn();
  await render(<StudioVaryWorkspace
    gateway={{ saveRevisionAsVariation } as any}
    lineage={currentLineage()}
    createdBy="designer_1"
    onCreated={onCreated}
    onContinueRefining={onContinueRefining}
    destinationContext={{
      activeProjectId: 'child_project', activeRevisionId: 'child_asset',
      hasExactSpecification: false, factoryEligible: false,
    }}
    onSelectDestination={onSelectDestination}
    createOperationId={createOperationId}
  />);

  expect(screen.queryByText(/compare|restore|all families/i)).toBeNull();
  expect(screen.queryByText(/project_1|asset_7/i)).toBeNull();
  expect(screen.getByText('Revision 7')).toBeTruthy();
  await fireEvent.changeText(screen.getByLabelText('Variation name'), 'Rose gold study');
  await fireEvent.press(screen.getByText('Create variation'));

  await waitFor(() => expect(saveRevisionAsVariation).toHaveBeenCalledWith({
    projectId: 'project_1', sourceAssetId: 'asset_7', sourceDesignVersion: null,
    sourceSha256: CURRENT_SOURCE_SHA256, expectedActiveAssetId: 'asset_7',
    expectedActiveDesignVersion: null,
    createdBy: 'designer_1', label: 'Rose gold study', operationId: 'vary:request-0001',
  }));
  expect(onCreated).toHaveBeenCalledWith(project);
  expect(await screen.findByText('Rose gold study is ready.')).toBeTruthy();
  expect(screen.queryByText('Create variation')).toBeNull();
  await fireEvent.press(screen.getByText('Continue refining'));
  await fireEvent.press(screen.getByText('Library'));
  expect(onContinueRefining).toHaveBeenCalledTimes(1);
  expect(onSelectDestination).toHaveBeenCalledWith('library');
  expect(saveRevisionAsVariation).toHaveBeenCalledTimes(1);
  expect(createOperationId).toHaveBeenCalledTimes(2);
});

test('accepts the current response after StrictMode replays effect cleanup and setup', async () => {
  const onCreated = jest.fn();
  const saveRevisionAsVariation = jest.fn(async () => ({
    data: {
      status: 'variation_created', family_id: 'family_1', variation_index: 2,
      source_project_id: 'project_1', source_asset_id: 'asset_7', project,
    },
    error: null,
    status: 201,
  }));
  await render(
    <React.StrictMode>
      <StudioVaryWorkspace
        gateway={{ saveRevisionAsVariation } as any}
        lineage={currentLineage()}
        createdBy="designer_1"
        onCreated={onCreated}
        createOperationId={() => 'vary:strict-mode-0001'}
      />
    </React.StrictMode>,
  );

  await fireEvent.changeText(screen.getByLabelText('Variation name'), 'Strict direction');
  await fireEvent.press(screen.getByText('Create variation'));

  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(project));
  expect(await screen.findByText('Strict direction is ready.')).toBeTruthy();
});

test('branches an exact historical revision without restoring over the active source', async () => {
  const saveRevisionAsVariation = jest.fn(async () => ({
    data: {
      status: 'variation_created', family_id: 'family_1', variation_index: 3,
      source_project_id: 'project_1', source_asset_id: 'asset_1', project,
    },
    error: null,
    status: 201,
  }));
  const onCreated = jest.fn();
  await render(<StudioVaryWorkspace
    gateway={{ saveRevisionAsVariation } as any}
    lineage={{
      mode: 'saved_revision', projectId: 'project_1', sourceAssetId: 'asset_1',
      sourceDesignVersion: 1, sourceSha256: '1'.repeat(64), sourceRevision: 1,
      expectedActiveAssetId: 'asset_2', expectedActiveDesignVersion: 2,
    }}
    createdBy="designer_1"
    onCreated={onCreated}
    createOperationId={() => 'vary:history-0001'}
  />);

  expect(screen.getByText('Revision 1')).toBeTruthy();
  expect(screen.getByText(
    'Copied directly from saved history. The source Variation stays on its current revision.',
  )).toBeTruthy();
  await fireEvent.changeText(screen.getByLabelText('Variation name'), 'Earlier geometry study');
  await fireEvent.press(screen.getByText('Create variation'));

  await waitFor(() => expect(saveRevisionAsVariation).toHaveBeenCalledWith({
    projectId: 'project_1', sourceAssetId: 'asset_1', sourceDesignVersion: 1,
    sourceSha256: '1'.repeat(64), expectedActiveAssetId: 'asset_2',
    expectedActiveDesignVersion: 2, createdBy: 'designer_1',
    label: 'Earlier geometry study', operationId: 'vary:history-0001',
  }));
  expect(onCreated).toHaveBeenCalledWith(project);
});

test('reuses one operation id after a failed response', async () => {
  const createOperationId = jest.fn()
    .mockReturnValueOnce('vary:retry-stable-0001')
    .mockReturnValueOnce('vary:after-success-0002');
  const saveRevisionAsVariation = jest.fn()
    .mockResolvedValueOnce({
      data: null,
      error: {
        code: 'NETWORK_ERROR', message: 'Connection lost.', category: 'network',
        status: 0, retryable: true,
      },
      status: 0,
    })
    .mockResolvedValueOnce({
      data: {
        status: 'variation_created', family_id: 'family_1', variation_index: 2,
        source_project_id: 'project_1', source_asset_id: 'asset_7', project,
      },
      error: null,
      status: 201,
    });

  await render(<StudioVaryWorkspace
    gateway={{ saveRevisionAsVariation } as any}
    lineage={currentLineage()}
    createdBy="designer_1"
    onCreated={jest.fn()}
    createOperationId={createOperationId}
  />);
  await fireEvent.changeText(screen.getByLabelText('Variation name'), 'Retry me');
  await fireEvent.press(screen.getByText('Create variation'));
  await waitFor(() => expect(saveRevisionAsVariation).toHaveBeenCalledTimes(1));
  await fireEvent.press(screen.getByText('Create variation'));
  await waitFor(() => expect(saveRevisionAsVariation).toHaveBeenCalledTimes(2));

  const first = saveRevisionAsVariation.mock.calls[0]?.[0];
  const retry = saveRevisionAsVariation.mock.calls[1]?.[0];
  expect(first.operationId).toBe('vary:retry-stable-0001');
  expect(retry.operationId).toBe(first.operationId);
  expect(createOperationId).toHaveBeenCalledTimes(2);
  expect(await screen.findByText('Retry me is ready.')).toBeTruthy();
});

test('rotates the operation id and clears stale input when source lineage changes', async () => {
  const saveRevisionAsVariation = jest.fn().mockResolvedValueOnce({
    data: {
      status: 'variation_created', family_id: 'family_1', variation_index: 2,
      source_project_id: 'project_1', source_asset_id: 'asset_8', project,
    },
    error: null,
    status: 201,
  });
  const createOperationId = jest.fn()
    .mockReturnValueOnce('vary:source-one-0001')
    .mockReturnValueOnce('vary:source-two-0002')
    .mockReturnValueOnce('vary:after-success-0003');
  const onCreated = jest.fn();
  const view = await render(<StudioVaryWorkspace
    gateway={{ saveRevisionAsVariation } as any}
    lineage={currentLineage()}
    createdBy="designer_1"
    onCreated={onCreated}
    createOperationId={createOperationId}
  />);

  await fireEvent.changeText(screen.getByLabelText('Variation name'), 'Old source');
  await view.rerender(<StudioVaryWorkspace
    gateway={{ saveRevisionAsVariation } as any}
    lineage={currentLineage('asset_8', 8)}
    createdBy="designer_1"
    onCreated={onCreated}
    createOperationId={createOperationId}
  />);
  expect(screen.getByLabelText('Variation name').props.value).toBe('');

  await fireEvent.changeText(screen.getByLabelText('Variation name'), 'New source');
  await fireEvent.press(screen.getByText('Create variation'));
  await waitFor(() => expect(saveRevisionAsVariation).toHaveBeenCalledTimes(1));
  expect(saveRevisionAsVariation.mock.calls[0]?.[0].operationId).toBe('vary:source-two-0002');
  await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
});

test('does not reopen a late variation after the designer leaves the workspace', async () => {
  const pending = deferred<any>();
  const onCreated = jest.fn();
  const view = await render(<StudioVaryWorkspace
    gateway={{ saveRevisionAsVariation: jest.fn(() => pending.promise) } as any}
    lineage={currentLineage()}
    createdBy="designer_1"
    onCreated={onCreated}
    createOperationId={() => 'vary:leave-0001'}
  />);

  await fireEvent.changeText(screen.getByLabelText('Variation name'), 'Late direction');
  let completion!: Promise<void>;
  await act(async () => {
    completion = fireEvent.press(screen.getByText('Create variation'));
    await Promise.resolve();
  });
  await act(async () => { view.unmount(); });
  await act(async () => {
    pending.resolve({
      data: {
        status: 'variation_created', family_id: 'family_1', variation_index: 2,
        source_project_id: 'project_1', source_asset_id: 'asset_7', project,
      },
      error: null,
      status: 201,
    });
    await completion;
  });

  expect(onCreated).not.toHaveBeenCalled();
});

test('rejects an A-to-B-to-A late variation response', async () => {
  const pending = deferred<any>();
  const onCreated = jest.fn();
  const gateway = { saveRevisionAsVariation: jest.fn(() => pending.promise) } as any;
  const props = (lineage: ReturnType<typeof currentLineage>) => (
    <StudioVaryWorkspace
      gateway={gateway}
      lineage={lineage}
      createdBy="designer_1"
      onCreated={onCreated}
      createOperationId={() => `vary:${lineage.sourceAssetId}`}
    />
  );
  const view = await render(props(currentLineage('asset_a', 1)));

  await fireEvent.changeText(screen.getByLabelText('Variation name'), 'First A request');
  let completion!: Promise<void>;
  await act(async () => {
    completion = fireEvent.press(screen.getByText('Create variation'));
    await Promise.resolve();
  });
  await view.rerender(props(currentLineage('asset_b', 2)));
  await view.rerender(props(currentLineage('asset_a', 1)));
  await act(async () => {
    pending.resolve({
      data: {
        status: 'variation_created', family_id: 'family_1', variation_index: 2,
        source_project_id: 'project_1', source_asset_id: 'asset_a', project,
      },
      error: null,
      status: 201,
    });
    await completion;
  });

  expect(onCreated).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Variation name').props.value).toBe('');
  expect(screen.getByText('Create variation')).toBeTruthy();
});

test('fails closed without a selected revision', async () => {
  await render(<StudioVaryWorkspace
    gateway={{ saveRevisionAsVariation: jest.fn() } as any}
    lineage={null}
    createdBy="designer_1"
    onCreated={jest.fn()}
  />);
  expect(screen.getByText('Choose a saved direction first')).toBeTruthy();
  expect(screen.queryByText('Create variation')).toBeNull();
});
