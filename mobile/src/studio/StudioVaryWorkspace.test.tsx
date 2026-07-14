/// <reference types="jest" />

import React from 'react';
import {
  fireEvent, render, screen, waitFor,
} from '@testing-library/react-native';

import { StudioVaryWorkspace } from './StudioVaryWorkspace';

const project = {
  root_id: 'child_project', active_asset_id: 'child_asset', active_design_version: null,
} as any;

test('branches only the hidden exact source and opens the child variation', async () => {
  const createOperationId = jest.fn()
    .mockReturnValueOnce('vary:request-0001')
    .mockReturnValueOnce('vary:request-0002');
  const saveCurrentAsVariation = jest.fn(async () => ({
    data: {
      status: 'variation_created', family_id: 'family_1', variation_index: 2,
      source_project_id: 'project_1', source_asset_id: 'asset_7', project,
    },
    error: null,
    status: 201,
  }));
  const onCreated = jest.fn();
  const onContinueRefining = jest.fn();
  const onOpenCollections = jest.fn();
  await render(<StudioVaryWorkspace
    gateway={{ saveCurrentAsVariation } as any}
    lineage={{ projectId: 'project_1', sourceAssetId: 'asset_7', sourceDesignVersion: null }}
    createdBy="designer_1"
    onCreated={onCreated}
    onContinueRefining={onContinueRefining}
    onOpenCollections={onOpenCollections}
    createOperationId={createOperationId}
  />);

  expect(screen.queryByText(/compare|restore|all families/i)).toBeNull();
  expect(screen.queryByText(/project_1|asset_7/i)).toBeNull();
  await fireEvent.changeText(screen.getByLabelText('Variation name'), 'Rose gold study');
  await fireEvent.press(screen.getByText('Create variation'));

  await waitFor(() => expect(saveCurrentAsVariation).toHaveBeenCalledWith({
    projectId: 'project_1', sourceAssetId: 'asset_7', sourceDesignVersion: null,
    createdBy: 'designer_1', label: 'Rose gold study', operationId: 'vary:request-0001',
  }));
  expect(onCreated).toHaveBeenCalledWith(project);
  expect(await screen.findByText('Rose gold study is ready.')).toBeTruthy();
  expect(screen.queryByText('Create variation')).toBeNull();
  await fireEvent.press(screen.getByText('Continue refining'));
  await fireEvent.press(screen.getByText('Open Collections'));
  expect(onContinueRefining).toHaveBeenCalledTimes(1);
  expect(onOpenCollections).toHaveBeenCalledTimes(1);
  expect(saveCurrentAsVariation).toHaveBeenCalledTimes(1);
  expect(createOperationId).toHaveBeenCalledTimes(2);
});

test('reuses one operation id after a failed response', async () => {
  const createOperationId = jest.fn()
    .mockReturnValueOnce('vary:retry-stable-0001')
    .mockReturnValueOnce('vary:after-success-0002');
  const saveCurrentAsVariation = jest.fn()
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
    gateway={{ saveCurrentAsVariation } as any}
    lineage={{ projectId: 'project_1', sourceAssetId: 'asset_7', sourceDesignVersion: null }}
    createdBy="designer_1"
    onCreated={jest.fn()}
    createOperationId={createOperationId}
  />);
  await fireEvent.changeText(screen.getByLabelText('Variation name'), 'Retry me');
  await fireEvent.press(screen.getByText('Create variation'));
  await waitFor(() => expect(saveCurrentAsVariation).toHaveBeenCalledTimes(1));
  await fireEvent.press(screen.getByText('Create variation'));
  await waitFor(() => expect(saveCurrentAsVariation).toHaveBeenCalledTimes(2));

  const first = saveCurrentAsVariation.mock.calls[0]?.[0];
  const retry = saveCurrentAsVariation.mock.calls[1]?.[0];
  expect(first.operationId).toBe('vary:retry-stable-0001');
  expect(retry.operationId).toBe(first.operationId);
  expect(createOperationId).toHaveBeenCalledTimes(2);
  expect(await screen.findByText('Retry me is ready.')).toBeTruthy();
});

test('rotates the operation id and clears stale input when source lineage changes', async () => {
  const saveCurrentAsVariation = jest.fn().mockResolvedValueOnce({
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
    gateway={{ saveCurrentAsVariation } as any}
    lineage={{ projectId: 'project_1', sourceAssetId: 'asset_7', sourceDesignVersion: null }}
    createdBy="designer_1"
    onCreated={onCreated}
    createOperationId={createOperationId}
  />);

  await fireEvent.changeText(screen.getByLabelText('Variation name'), 'Old source');
  await view.rerender(<StudioVaryWorkspace
    gateway={{ saveCurrentAsVariation } as any}
    lineage={{ projectId: 'project_1', sourceAssetId: 'asset_8', sourceDesignVersion: null }}
    createdBy="designer_1"
    onCreated={onCreated}
    createOperationId={createOperationId}
  />);
  expect(screen.getByLabelText('Variation name').props.value).toBe('');

  await fireEvent.changeText(screen.getByLabelText('Variation name'), 'New source');
  await fireEvent.press(screen.getByText('Create variation'));
  await waitFor(() => expect(saveCurrentAsVariation).toHaveBeenCalledTimes(1));
  expect(saveCurrentAsVariation.mock.calls[0]?.[0].operationId).toBe('vary:source-two-0002');
  await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
});

test('fails closed without a selected revision', async () => {
  await render(<StudioVaryWorkspace
    gateway={{ saveCurrentAsVariation: jest.fn() } as any}
    lineage={null}
    createdBy="designer_1"
    onCreated={jest.fn()}
  />);
  expect(screen.getByText('Choose a saved direction first')).toBeTruthy();
  expect(screen.queryByText('Create variation')).toBeNull();
});
