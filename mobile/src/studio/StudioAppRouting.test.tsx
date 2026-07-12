/// <reference types="jest" />

import React from 'react';
import { fireEvent, render, waitFor } from '@testing-library/react-native';
import { clearSession, markOnboarded, saveSession } from '../auth';

jest.mock('./StudioCreateWorkspace', () => {
  const ReactLocal = require('react');
  const { Pressable, Text } = require('react-native');
  const { DEFAULT_API_URL } = require('../api');
  return {
    StudioCreateWorkspace: ({ onSave }: { onSave: (selection: any) => void }) => (
      ReactLocal.createElement(Pressable, { accessibilityRole: 'button', onPress: () => onSave({
      project: {
        id: 'project_1', root_id: 'project_1', title: 'Saved direction',
        collection: null, tags: [], owner: 'usr_designer', state: 'refining',
        design_id: null, spec: null, active_asset_id: 'asset_1',
        active_design_version: null, selected_candidate_asset_id: 'asset_1',
        active_revision: {
          asset_id: 'asset_1', root_id: 'project_1', parent_asset_id: null,
          capability: 'CREATIVE_RENDER', provenance: 'pre_spec_creative_candidate',
          revision: 1, design_id: null, design_version: null, region: null,
          instruction: 'Saved direction', drift: null, pinned: false,
          media_type: 'image/png',
          image_url: `${DEFAULT_API_URL.replace(/\/$/, '')}/assets/asset_1/image`,
          created_by: 'usr_designer', created_at: null, legacy_provenance: false,
        },
        pinned_revision: null, revisions: [], assets: [{
          asset_id: 'asset_1', root_id: 'project_1', parent_asset_id: null,
          capability: 'CREATIVE_RENDER', provenance: 'pre_spec_creative_candidate',
          revision: 1, design_id: null, design_version: null, region: null,
          instruction: 'Saved direction', drift: null, pinned: false,
          media_type: 'image/png',
          image_url: `${DEFAULT_API_URL.replace(/\/$/, '')}/assets/asset_1/image`,
          created_by: 'usr_designer', created_at: null, legacy_provenance: false,
        }], derived_assets: [],
        approval: null, factory_ready: false, factory_blockers: [],
        primary_revision_count: 1, has_factory_drawing: false,
        cover_asset_id: 'asset_1', created_at: null, updated_at: null,
      },
      selectedAssetId: 'asset_1', sentence: 'Saved direction', references: [],
      }) }, ReactLocal.createElement(Text, null, 'Save mocked direction'))
    ),
  };
});

jest.mock('./StudioRefineWorkspace', () => {
  const ReactLocal = require('react');
  const { Text } = require('react-native');
  return {
    StudioRefineWorkspace: () => ReactLocal.createElement(Text, null, 'Refine route reached'),
  };
});

jest.mock('./StudioConfirmWorkspace', () => {
  const ReactLocal = require('react');
  const { Pressable, Text } = require('react-native');
  return {
    StudioConfirmWorkspace: ({ onSaved }: { onSaved: (receipt: any) => void }) => (
      ReactLocal.createElement(Pressable, { accessibilityRole: 'button', onPress: () => onSaved({
        project: {
          id: 'project_1', root_id: 'project_1', title: 'Confirmed direction',
          collection: null, tags: [], owner: 'usr_designer', state: 'refining',
          design_id: 'design_1', spec: { jewelry_type: 'ring' },
          active_asset_id: 'asset_exact_1', active_design_version: 1,
          selected_candidate_asset_id: 'asset_1',
          active_revision: {
            asset_id: 'asset_exact_1', root_id: 'project_1', parent_asset_id: 'asset_1',
            capability: 'SPEC_RENDER', provenance: 'confirmed_design', revision: 2,
            design_id: 'design_1', design_version: 1, region: null,
            instruction: 'Confirmed direction', drift: null, pinned: false,
            media_type: 'image/png', image_url: null, created_by: 'usr_designer',
            created_at: null, legacy_provenance: false,
          },
          pinned_revision: null, revisions: [], assets: [], derived_assets: [],
          approval: null, factory_ready: true, factory_blockers: [],
          primary_revision_count: 2, has_factory_drawing: false,
          cover_asset_id: 'asset_exact_1', created_at: null, updated_at: null,
        },
      }) }, ReactLocal.createElement(Text, null, 'Confirm mocked design'))
    ),
  };
});

jest.mock('./StudioFactoryWorkspace', () => {
  const ReactLocal = require('react');
  const { Text } = require('react-native');
  return {
    StudioFactoryWorkspace: ({ lineage }: { lineage: any }) => ReactLocal.createElement(
      Text, null, `Factory route reached for ${lineage?.sourceAssetId ?? 'none'}`,
    ),
  };
});

import App from '../../App';

afterEach(() => clearSession());

test('saving a selected direction continues to Refine and authenticates its Studio cover', async () => {
  markOnboarded();
  saveSession({
    provider: 'email', email: 'designer@example.com', name: 'Designer',
    designerId: 'usr_designer', accessToken: 'server-issued-test-token',
    accessTokenExpiresAt: '2099-01-01T00:00:00Z',
  });
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(view.queryByText('Your design families')).toBeNull();

  fireEvent.press(view.getByText('Close'));
  const cover = await view.findByLabelText('Current design cover');
  expect(cover.props.source.headers).toEqual({
    Authorization: 'Bearer server-issued-test-token',
  });
});

test('confirming Design v1 returns immediately to Refine without a Collections or Factory detour', async () => {
  markOnboarded();
  saveSession({
    provider: 'email', email: 'designer@example.com', name: 'Designer',
    designerId: 'usr_designer', accessToken: 'server-issued-test-token',
    accessTokenExpiresAt: '2099-01-01T00:00:00Z',
  });
  const view = await render(<App />);

  await waitFor(() => expect(view.getByText('Start from an idea or reference')).toBeTruthy());
  fireEvent.press(view.getByText('Start from an idea or reference'));
  fireEvent.press(await view.findByText('Save mocked direction'));
  expect(await view.findByText('Refine route reached')).toBeTruthy();

  fireEvent.press(view.getByLabelText('Confirm design details'));
  fireEvent.press(await view.findByText('Confirm mocked design'));

  expect(await view.findByText('Refine route reached')).toBeTruthy();
  expect(view.queryByText('Confirm mocked design')).toBeNull();
  expect(view.queryByText('Your design families')).toBeNull();
  expect(view.queryByText(/Factory/i)).toBeNull();
  expect(view.getByLabelText('More actions')).toBeTruthy();
  fireEvent.press(view.getByLabelText('More actions'));
  expect(await view.findByText('Factory')).toBeTruthy();
  fireEvent.press(view.getByText('Factory'));
  expect(await view.findByText('Factory route reached for asset_exact_1')).toBeTruthy();
  expect(view.queryByText(/destination will use the exact active revision/i)).toBeNull();
});
