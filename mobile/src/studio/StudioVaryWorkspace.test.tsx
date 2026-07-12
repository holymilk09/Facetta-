/// <reference types="jest" />

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { StudioVaryWorkspace } from './StudioVaryWorkspace';

const project = {
  root_id: 'child_project', active_asset_id: 'child_asset', active_design_version: null,
} as any;

test('branches only the hidden exact source and opens the child variation', async () => {
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
  />);

  expect(screen.queryByText(/compare|restore|all families/i)).toBeNull();
  expect(screen.queryByText(/project_1|asset_7/i)).toBeNull();
  await fireEvent.changeText(screen.getByLabelText('Variation name'), 'Rose gold study');
  await fireEvent.press(screen.getByText('Create variation'));

  await waitFor(() => expect(saveCurrentAsVariation).toHaveBeenCalledWith({
    projectId: 'project_1', sourceAssetId: 'asset_7', sourceDesignVersion: null,
    createdBy: 'designer_1', label: 'Rose gold study',
  }));
  expect(onCreated).toHaveBeenCalledWith(project);
  expect(await screen.findByText('Rose gold study is ready.')).toBeTruthy();
  expect(screen.queryByText('Create variation')).toBeNull();
  await fireEvent.press(screen.getByText('Continue refining'));
  await fireEvent.press(screen.getByText('Open Collections'));
  expect(onContinueRefining).toHaveBeenCalledTimes(1);
  expect(onOpenCollections).toHaveBeenCalledTimes(1);
  expect(saveCurrentAsVariation).toHaveBeenCalledTimes(1);
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
