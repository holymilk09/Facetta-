/// <reference types="jest" />

import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { Text } from 'react-native';

import type { ProjectDetail } from '../trusted/types';
import {
  StudioCollectionsWorkspace,
  type StudioCollectionsApi,
} from './StudioCollectionsWorkspace';
import { AuthenticatedImageProvider } from '../AuthenticatedImage';

const project: ProjectDetail = {
  id: 'project_main', root_id: 'project_main', title: 'Sapphire orbit ring',
  collection: 'Orbit collection', tags: ['sapphire'], owner: 'usr_designer',
  state: 'refining', design_id: 'design_ring', spec: { jewelry_type: 'ring' },
  active_asset_id: 'asset_2', active_design_version: 2, active_revision: null,
  pinned_revision: null, revisions: [], assets: [], derived_assets: [], approval: null,
  factory_ready: false, factory_blockers: [], primary_revision_count: 2,
  has_factory_drawing: false, cover_asset_id: 'asset_2', created_at: null, updated_at: null,
};

const history = {
  project_id: 'project_main', family_id: 'family_orbit', variation_index: 1,
  variation_label: 'Original', active_asset_id: 'asset_2',
  revisions: [
    {
      revision: 1, asset_id: 'asset_1', parent_asset_id: null,
      design_version: 1, capability: 'SPEC_RENDER', image_url: 'https://test/revision-1.png',
      pinned: false, action: 'created' as const, raw_intent: {}, interpretation: {},
      change_summary: 'Created the original direction.', restored_from_asset_id: null,
      created_by: 'usr_designer', created_at: '2026-07-12T01:00:00Z',
    },
    {
      revision: 2, asset_id: 'asset_2', parent_asset_id: 'asset_1',
      design_version: 2, capability: 'LOCALIZED_EDIT', image_url: 'https://test/revision-2.png',
      pinned: false, action: 'edit' as const, raw_intent: {}, interpretation: {},
      change_summary: 'Changed the metal to rose gold.', restored_from_asset_id: null,
      created_by: 'usr_designer', created_at: '2026-07-12T02:00:00Z',
    },
  ],
};

const family = {
  family_id: 'family_orbit', owner: 'usr_designer', title: 'Sapphire orbit ring',
  tags: ['sapphire'],
  created_at: '2026-07-12T01:00:00Z', updated_at: '2026-07-12T03:00:00Z',
  is_favorite: false, favorited_at: null,
  variations: [
    {
      root_id: 'project_main', title: 'Sapphire orbit ring', collection: 'Orbit collection',
      tags: ['sapphire'], owner: 'usr_designer', counts: {}, item_count: 2,
      primary_revision_count: 2, has_factory_drawing: false, cover_asset_id: 'asset_2',
      created_at: '2026-07-12T01:00:00Z', updated_at: '2026-07-12T02:00:00Z',
      variation_index: 1, variation_label: 'Original',
      branched_from_project_root_id: null, branched_from_asset_id: null,
    },
    {
      root_id: 'project_white', title: 'Sapphire orbit ring', collection: 'Orbit collection',
      tags: ['sapphire'], owner: 'usr_designer', counts: {}, item_count: 1,
      primary_revision_count: 1, has_factory_drawing: false, cover_asset_id: 'asset_white',
      created_at: '2026-07-12T03:00:00Z', updated_at: '2026-07-12T03:00:00Z',
      variation_index: 2, variation_label: 'White metal study',
      branched_from_project_root_id: 'project_main', branched_from_asset_id: 'asset_2',
    },
  ],
};

function api(overrides: Partial<StudioCollectionsApi> = {}): StudioCollectionsApi {
  return {
    listDesignFamilies: jest.fn(async () => ({ data: { families: [family] }, error: null, status: 200 })),
    favoriteDesignFamily: jest.fn(async () => ({ data: { status: 'updated' as const }, error: null, status: 204 })),
    unfavoriteDesignFamily: jest.fn(async () => ({ data: { status: 'updated' as const }, error: null, status: 204 })),
    updateDesignFamilyTags: jest.fn(async (familyId: string, _owner: string, tags: string[]) => ({
      data: { family_id: familyId, tags }, error: null, status: 200,
    })),
    getStudioProjectHistory: jest.fn(async () => ({ data: history, error: null, status: 200 })),
    getDesignFamily: jest.fn(async () => ({ data: family, error: null, status: 200 })),
    listWorkspaceCollections: jest.fn(async () => ({ data: { collections: [] }, error: null, status: 200 })),
    listWorkspaceCollectionMemberships: jest.fn(async () => ({
      data: { family_collection_ids: { [family.family_id]: [] } }, error: null, status: 200,
    })),
    createWorkspaceCollection: jest.fn(),
    updateWorkspaceCollection: jest.fn(),
    deleteWorkspaceCollection: jest.fn(),
    listDesignFamilyCollections: jest.fn(async () => ({ data: { collections: [] }, error: null, status: 200 })),
    addDesignFamilyToCollection: jest.fn(),
    removeDesignFamilyFromCollection: jest.fn(),
    restoreStudioRevision: jest.fn(async () => ({
      data: {
        status: 'restored_as_new_revision' as const,
        restored_from_asset_id: 'asset_1', new_asset_id: 'asset_3',
        new_design_version: 3, spec_change: [],
        project: { ...project, active_asset_id: 'asset_3', active_design_version: 3 },
      },
      error: null,
      status: 201,
    })),
    assetImageUrl: jest.fn((assetId: string) => `https://test/assets/${assetId}.png`),
    ...overrides,
  } as StudioCollectionsApi;
}

const callbacks = () => ({
  onOpenProject: jest.fn(),
  onProjectChanged: jest.fn(),
  onStartDesign: jest.fn(),
  onVaryCurrent: jest.fn(),
  onContinueRefining: jest.fn(),
  destinationContext: {
    activeProjectId: project.root_id,
    activeRevisionId: project.active_asset_id,
    hasExactSpecification: true,
    factoryEligible: false,
  },
  onSelectDestination: jest.fn(),
});

describe('StudioCollectionsWorkspace', () => {
  test('retries an unavailable family index without presenting it as an empty account', async () => {
    const listDesignFamilies = jest.fn()
      .mockResolvedValueOnce({
        data: null,
        error: {
          code: 'NETWORK_ERROR', message: 'Collections are unavailable.',
          category: 'network' as const, status: 503, retryable: true,
        },
        status: 503,
      })
      .mockResolvedValueOnce({ data: { families: [family] }, error: null, status: 200 });
    const client = api({ listDesignFamilies });

    await render(
      <StudioCollectionsWorkspace
        api={client}
        project={null}
        createdBy="usr_designer"
        {...callbacks()}
      />,
    );

    expect(await screen.findByText('Collections are temporarily unavailable')).toBeTruthy();
    expect(screen.queryByText('No saved families yet')).toBeNull();
    expect(listDesignFamilies).toHaveBeenCalledTimes(1);
    expect(listDesignFamilies).toHaveBeenLastCalledWith('usr_designer');

    await fireEvent.press(screen.getByText('Retry'));

    expect(await screen.findByText('Sapphire orbit ring')).toBeTruthy();
    expect(screen.queryByText('Collections are temporarily unavailable')).toBeNull();
    expect(listDesignFamilies).toHaveBeenCalledTimes(2);
    expect(listDesignFamilies).toHaveBeenLastCalledWith('usr_designer');
  });

  test('filters family-based All Designs by search, tags, Collection, and Unfiled membership', async () => {
    const clientCollection = {
      id: 'collection_client', name: 'Lin commission', template: 'client' as const,
      metadata: { client_name: 'Lin Chen' }, archived_at: null, created_at: '2026-07-12T00:00:00Z',
      updated_at: '2026-07-12T00:00:00Z', family_count: 1,
    };
    const unfiledFamily = {
      ...family,
      family_id: 'family_unfiled',
      title: 'Emerald leaf pendant',
      tags: ['emerald'],
      variations: [{
        ...family.variations[0], root_id: 'project_emerald', title: 'Emerald leaf pendant',
        tags: ['emerald'], cover_asset_id: 'asset_emerald',
      }],
    };
    const listWorkspaceCollectionMemberships = jest.fn(async () => ({
      data: {
        family_collection_ids: {
          [family.family_id]: [clientCollection.id],
          [unfiledFamily.family_id]: [],
        },
      },
      error: null,
      status: 200,
    }));
    const client = api({
      listDesignFamilies: jest.fn(async () => ({
        data: { families: [family, unfiledFamily] }, error: null, status: 200,
      })),
      listWorkspaceCollections: jest.fn(async () => ({
        data: { collections: [clientCollection] }, error: null, status: 200,
      })),
      listWorkspaceCollectionMemberships,
    });

    await render(
      <StudioCollectionsWorkspace
        api={client}
        project={null}
        createdBy="usr_designer"
        {...callbacks()}
      />,
    );

    expect(await screen.findByText('All Designs')).toBeTruthy();
    expect(screen.getByText('Sapphire orbit ring')).toBeTruthy();
    expect(screen.getByText('Emerald leaf pendant')).toBeTruthy();
    expect(listWorkspaceCollectionMemberships).toHaveBeenCalledTimes(1);
    expect(listWorkspaceCollectionMemberships).toHaveBeenCalledWith('usr_designer');
    expect(client.listDesignFamilyCollections).not.toHaveBeenCalled();
    expect(client.listWorkspaceCollections).toHaveBeenCalledWith({ owner: 'usr_designer' });

    await fireEvent.press(screen.getByText('Unfiled'));
    expect(screen.queryByText('Sapphire orbit ring')).toBeNull();
    expect(screen.getByText('Emerald leaf pendant')).toBeTruthy();

    await fireEvent.press(screen.getByText('Lin commission · 1'));
    expect(screen.getByText('Sapphire orbit ring')).toBeTruthy();
    expect(screen.queryByText('Emerald leaf pendant')).toBeNull();

    await fireEvent.press(screen.getByText('All Designs'));
    await fireEvent.changeText(screen.getByLabelText('Search designs'), 'Lin Chen');
    expect(screen.getByText('Sapphire orbit ring')).toBeTruthy();
    expect(screen.queryByText('Emerald leaf pendant')).toBeNull();
    await fireEvent.changeText(screen.getByLabelText('Search designs'), 'emerald');
    expect(screen.queryByText('Sapphire orbit ring')).toBeNull();
    expect(screen.getByText('Emerald leaf pendant')).toBeTruthy();
    await fireEvent.press(screen.getAllByText('#emerald')[0]);
    expect(screen.getByText('Emerald leaf pendant')).toBeTruthy();
  });

  test('edits canonical family tags and immediately uses them for family search', async () => {
    const updateDesignFamilyTags = jest.fn(async () => ({
      data: { family_id: family.family_id, tags: ['bridal', 'client review'] },
      error: null,
      status: 200,
    }));
    const client = api({ updateDesignFamilyTags });

    await render(
      <StudioCollectionsWorkspace
        api={client}
        project={null}
        createdBy="usr_designer"
        {...callbacks()}
      />,
    );

    expect(await screen.findByText('Sapphire orbit ring')).toBeTruthy();
    await fireEvent.press(screen.getByText('Edit tags'));
    await fireEvent.changeText(
      screen.getByLabelText('Tags for Sapphire orbit ring'),
      'Bridal, client review',
    );
    await fireEvent.press(screen.getByText('Save tags'));

    await waitFor(() => expect(updateDesignFamilyTags).toHaveBeenCalledWith(
      family.family_id,
      'usr_designer',
      ['Bridal', 'client review'],
    ));
    expect(await screen.findByText('#bridal  #client review')).toBeTruthy();
    await fireEvent.changeText(screen.getByLabelText('Search designs'), 'client review');
    expect(screen.getByText('Sapphire orbit ring')).toBeTruthy();
  });

  test('loads one owner-scoped aggregate membership index for many families', async () => {
    const manyFamilies = Array.from({ length: 24 }, (_, index) => ({
      ...family,
      family_id: `family_${index}`,
      title: `Family ${index}`,
      variations: family.variations.map((variation) => ({
        ...variation,
        root_id: `${variation.root_id}_${index}`,
      })),
    }));
    const listWorkspaceCollectionMemberships = jest.fn(async () => ({
      data: {
        family_collection_ids: Object.fromEntries(manyFamilies.map((item) => [item.family_id, []])),
      },
      error: null,
      status: 200,
    }));
    const client = api({
      listDesignFamilies: jest.fn(async () => ({
        data: { families: manyFamilies }, error: null, status: 200,
      })),
      listWorkspaceCollectionMemberships,
    });

    await render(
      <StudioCollectionsWorkspace api={client} project={null} createdBy="usr_designer" {...callbacks()} />,
    );

    expect(await screen.findByText('Family 0')).toBeTruthy();
    expect(screen.getByText('Family 23')).toBeTruthy();
    expect(listWorkspaceCollectionMemberships).toHaveBeenCalledTimes(1);
    expect(listWorkspaceCollectionMemberships).toHaveBeenCalledWith('usr_designer');
    expect(client.listDesignFamilyCollections).not.toHaveBeenCalled();
  });

  test('keeps All Designs available when the aggregate membership index fails', async () => {
    const client = api({
      listWorkspaceCollectionMemberships: jest.fn(async () => ({
        data: null,
        error: {
          code: 'NETWORK_ERROR', message: 'Membership index unavailable.',
          category: 'network' as const, status: 503, retryable: true,
        },
        status: 503,
      })),
    });

    await render(
      <StudioCollectionsWorkspace api={client} project={null} createdBy="usr_designer" {...callbacks()} />,
    );

    expect(await screen.findByText('Sapphire orbit ring')).toBeTruthy();
    expect(screen.getByText(
      'Collection organization is temporarily unavailable. All Designs is still safe to browse.',
    )).toBeTruthy();
    expect(client.listDesignFamilyCollections).not.toHaveBeenCalled();
  });

  test('persists Favorites across reload and removes an unfavorited family without navigation', async () => {
    let favoriteSaved = false;
    const listDesignFamilies = jest.fn(async () => ({
      data: {
        families: [{
          ...family,
          is_favorite: favoriteSaved,
          favorited_at: favoriteSaved ? '2026-07-12T04:00:00Z' : null,
          variations: family.variations.map((variation) => ({
            ...variation,
            tags: [...variation.tags, 'favorite'],
          })),
        }],
      },
      error: null,
      status: 200,
    }));
    const favoriteDesignFamily = jest.fn(async () => {
      favoriteSaved = true;
      return { data: { status: 'updated' as const }, error: null, status: 204 };
    });
    const unfavoriteDesignFamily = jest.fn(async () => {
      favoriteSaved = false;
      return { data: { status: 'updated' as const }, error: null, status: 204 };
    });
    const client = api({ listDesignFamilies, favoriteDesignFamily, unfavoriteDesignFamily });
    const handlers = callbacks();

    const first = await render(
      <StudioCollectionsWorkspace api={client} project={null} createdBy="usr_designer" {...handlers} />,
    );
    await screen.findByText('Sapphire orbit ring');
    await fireEvent.press(screen.getByText('Favorites'));
    expect(screen.queryByText('Sapphire orbit ring')).toBeNull();
    await fireEvent.press(screen.getByText('All Designs'));
    await fireEvent.press(screen.getByLabelText('Add Sapphire orbit ring to Favorites'));
    await waitFor(() => expect(favoriteDesignFamily).toHaveBeenCalledWith(
      'family_orbit', 'usr_designer',
    ));
    expect(handlers.onOpenProject).not.toHaveBeenCalled();
    expect(client.restoreStudioRevision).not.toHaveBeenCalled();
    await first.unmount();

    await render(
      <StudioCollectionsWorkspace api={client} project={null} createdBy="usr_designer" {...handlers} />,
    );
    await screen.findByText('Sapphire orbit ring');
    await fireEvent.press(screen.getByText('Favorites'));
    expect(screen.getByText('Sapphire orbit ring')).toBeTruthy();
    await fireEvent.press(screen.getByLabelText('Remove Sapphire orbit ring from Favorites'));
    await waitFor(() => expect(unfavoriteDesignFamily).toHaveBeenCalledWith(
      'family_orbit', 'usr_designer',
    ));
    expect(screen.queryByText('Sapphire orbit ring')).toBeNull();
    expect(handlers.onOpenProject).not.toHaveBeenCalled();
  });

  test('defines Recent as the latest 12 design-active families with a family-id tie break', async () => {
    const recentFamilies = Array.from({ length: 14 }, (_, index) => ({
      ...family,
      family_id: `family_${String(index).padStart(2, '0')}`,
      title: `Recent family ${String(index).padStart(2, '0')}`,
      updated_at: index >= 12
        ? '2026-07-14T00:00:00Z'
        : `2026-07-${String(index + 1).padStart(2, '0')}T00:00:00Z`,
      is_favorite: index === 0,
      favorited_at: index === 0 ? '2026-07-30T00:00:00Z' : null,
      variations: family.variations.map((variation) => ({
        ...variation,
        root_id: `${variation.root_id}_${index}`,
      })),
    })).reverse();
    const client = api({
      listDesignFamilies: jest.fn(async () => ({
        data: { families: recentFamilies }, error: null, status: 200,
      })),
    });
    await render(
      <StudioCollectionsWorkspace api={client} project={null} createdBy="usr_designer" {...callbacks()} />,
    );

    await screen.findByText('Recent family 13');
    await fireEvent.press(screen.getByText('Recent'));

    const titles = screen.getAllByText(/^Recent family /).map((node) => node.props.children);
    expect(titles).toEqual([
      'Recent family 12',
      'Recent family 13',
      'Recent family 11',
      'Recent family 10',
      'Recent family 09',
      'Recent family 08',
      'Recent family 07',
      'Recent family 06',
      'Recent family 05',
      'Recent family 04',
      'Recent family 03',
      'Recent family 02',
    ]);
    expect(screen.queryByText('Recent family 01')).toBeNull();
    expect(screen.queryByText('Recent family 00')).toBeNull();
  });

  test('creates a flat templated Collection without filing a family during creation', async () => {
    const createdCollection = {
      id: 'collection_campaign', name: 'Holiday campaign', template: 'campaign' as const,
      metadata: {}, archived_at: null, created_at: '2026-07-12T00:00:00Z',
      updated_at: '2026-07-12T00:00:00Z', family_count: 0,
    };
    const createWorkspaceCollection = jest.fn(async () => ({
      data: createdCollection, error: null, status: 201,
    }));
    const client = api({ createWorkspaceCollection });
    await render(
      <StudioCollectionsWorkspace api={client} project={null} createdBy="usr_designer" {...callbacks()} />,
    );

    await screen.findByText('All Designs');
    await fireEvent.press(screen.getByRole('button', { name: 'New Collection' }));
    expect(screen.getByText('General')).toBeTruthy();
    expect(screen.getByText('Client')).toBeTruthy();
    expect(screen.getByText('Order')).toBeTruthy();
    expect(screen.getByText('Project')).toBeTruthy();
    expect(screen.getByText('Season')).toBeTruthy();
    expect(screen.getByText('Jewelry line')).toBeTruthy();
    expect(screen.getByText('Personal study')).toBeTruthy();
    expect(screen.getByText('Custom')).toBeTruthy();
    await fireEvent.press(screen.getByText('Campaign'));
    await fireEvent.changeText(screen.getByLabelText('Collection name'), 'Holiday campaign');
    await fireEvent.press(screen.getByRole('button', { name: 'Create Collection' }));

    await waitFor(() => expect(createWorkspaceCollection).toHaveBeenCalledWith({
      owner: 'usr_designer', name: 'Holiday campaign', template: 'campaign',
    }));
    expect(client.addDesignFamilyToCollection).not.toHaveBeenCalled();
    expect(await screen.findByText('Holiday campaign is ready. Add families when you choose.')).toBeTruthy();
    expect(screen.getByText('Sapphire orbit ring')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'New Collection' })).toBeTruthy();
  });

  test('captures optional client metadata only for a Client Collection', async () => {
    const createdCollection = {
      id: 'collection_client', name: 'Lin engagement', template: 'client' as const,
      metadata: { client_name: 'Lin Chen' }, archived_at: null,
      created_at: '2026-07-12T00:00:00Z', updated_at: '2026-07-12T00:00:00Z',
      family_count: 0,
    };
    const createWorkspaceCollection = jest.fn(async () => ({
      data: createdCollection, error: null, status: 201,
    }));
    const client = api({ createWorkspaceCollection });
    await render(
      <StudioCollectionsWorkspace api={client} project={null} createdBy="usr_designer" {...callbacks()} />,
    );

    await screen.findByText('All Designs');
    await fireEvent.press(screen.getByRole('button', { name: 'New Collection' }));
    expect(screen.queryByLabelText('Client name (optional)')).toBeNull();
    await fireEvent.press(screen.getByText('Client'));
    await fireEvent.changeText(screen.getByLabelText('Collection name'), 'Lin engagement');
    await fireEvent.changeText(screen.getByLabelText('Client name (optional)'), '  Lin Chen  ');
    await fireEvent.press(screen.getByRole('button', { name: 'Create Collection' }));

    await waitFor(() => expect(createWorkspaceCollection).toHaveBeenCalledWith({
      owner: 'usr_designer',
      name: 'Lin engagement',
      template: 'client',
      metadata: { client_name: 'Lin Chen' },
    }));
    expect(await screen.findByText('Lin engagement is ready. Add families when you choose.')).toBeTruthy();
  });

  test('adds and removes the whole family from several Collections without revision mutations', async () => {
    const clientCollection = {
      id: 'collection_client', name: 'Lin commission', template: 'client' as const,
      metadata: {}, archived_at: null, created_at: '2026-07-12T00:00:00Z',
      updated_at: '2026-07-12T00:00:00Z', family_count: 0,
    };
    const projectCollection = { ...clientCollection, id: 'collection_project', name: 'Halo studies', template: 'project' as const };
    const addDesignFamilyToCollection = jest.fn(async () => ({
      data: { status: 'updated' as const }, error: null, status: 204,
    }));
    const removeDesignFamilyFromCollection = jest.fn(async () => ({
      data: { status: 'updated' as const }, error: null, status: 204,
    }));
    const client = api({
      listWorkspaceCollections: jest.fn(async () => ({
        data: { collections: [clientCollection, projectCollection] }, error: null, status: 200,
      })),
      addDesignFamilyToCollection,
      removeDesignFamilyFromCollection,
    });
    await render(
      <StudioCollectionsWorkspace api={client} project={project} createdBy="usr_designer" {...callbacks()} />,
    );

    await screen.findByText('Organize this family');
    await fireEvent.press(screen.getByLabelText('Add to Lin commission'));
    await waitFor(() => expect(addDesignFamilyToCollection).toHaveBeenCalledWith(
      'family_orbit', 'collection_client',
    ));
    await fireEvent.press(screen.getByLabelText('Add to Halo studies'));
    expect(addDesignFamilyToCollection).toHaveBeenCalledWith('family_orbit', 'collection_project');
    await fireEvent.press(screen.getByLabelText('Remove from Lin commission'));
    expect(removeDesignFamilyFromCollection).toHaveBeenCalledWith('family_orbit', 'collection_client');
    expect(client.restoreStudioRevision).not.toHaveBeenCalled();
  });

  test('requires explicit confirmation before safe Collection deletion', async () => {
    const clientCollection = {
      id: 'collection_client', name: 'Lin commission', template: 'client' as const,
      metadata: {}, archived_at: null, created_at: '2026-07-12T00:00:00Z',
      updated_at: '2026-07-12T00:00:00Z', family_count: 1,
    };
    const deleteWorkspaceCollection = jest.fn(async () => ({
      data: { status: 'updated' as const }, error: null, status: 204,
    }));
    const client = api({
      listWorkspaceCollections: jest.fn(async () => ({
        data: { collections: [clientCollection] }, error: null, status: 200,
      })),
      listDesignFamilyCollections: jest.fn(async () => ({
        data: { collections: [clientCollection] }, error: null, status: 200,
      })),
      deleteWorkspaceCollection,
    });
    await render(
      <StudioCollectionsWorkspace api={client} project={null} createdBy="usr_designer" {...callbacks()} />,
    );

    await screen.findByText('All Designs');
    await fireEvent.press(screen.getByText('Lin commission · 1'));
    expect(screen.getByRole('button', { name: 'Archive Collection' })).toBeTruthy();
    await fireEvent.press(screen.getByRole('button', { name: 'Delete Collection' }));
    expect(deleteWorkspaceCollection).not.toHaveBeenCalled();
    await fireEvent.press(screen.getByText('Confirm delete Collection'));
    await waitFor(() => expect(deleteWorkspaceCollection).toHaveBeenCalledWith('collection_client'));
    expect(await screen.findByText('Lin commission was deleted. Only its memberships were removed.')).toBeTruthy();
    expect(client.restoreStudioRevision).not.toHaveBeenCalled();
  });

  test('ignores a stale family response after the owner scope changes', async () => {
    const staleResult = {
      data: null,
      error: {
        code: 'NETWORK_ERROR', message: 'Old account request failed.',
        category: 'network' as const, status: 503, retryable: true,
      },
      status: 503,
    };
    let resolveStale!: (result: typeof staleResult) => void;
    const staleRequest = new Promise<typeof staleResult>((resolve) => {
      resolveStale = resolve;
    });
    const listDesignFamilies = jest.fn((owner: string) => (
      owner === 'usr_previous'
        ? staleRequest
        : Promise.resolve({ data: { families: [family] }, error: null, status: 200 })
    ));
    const client = api({ listDesignFamilies });
    const view = await render(
      <StudioCollectionsWorkspace
        api={client}
        project={null}
        createdBy="usr_previous"
        {...callbacks()}
      />,
    );
    await waitFor(() => expect(listDesignFamilies).toHaveBeenCalledWith('usr_previous'));

    await view.rerender(
      <StudioCollectionsWorkspace
        api={client}
        project={null}
        createdBy="usr_designer"
        {...callbacks()}
      />,
    );
    expect(await screen.findByText('Sapphire orbit ring')).toBeTruthy();

    await act(async () => {
      resolveStale(staleResult);
      await staleRequest;
    });

    expect(screen.getByText('Sapphire orbit ring')).toBeTruthy();
    expect(screen.queryByText('Collections are temporarily unavailable')).toBeNull();
    expect(listDesignFamilies).toHaveBeenLastCalledWith('usr_designer');
  });

  test('offers a direct Studio start only after Collections confirms there are no saved families', async () => {
    const client = api({
      listDesignFamilies: jest.fn(async () => ({
        data: { families: [] }, error: null, status: 200,
      })),
    });
    const handlers = callbacks();

    await render(
      <StudioCollectionsWorkspace
        api={client}
        project={null}
        createdBy="usr_designer"
        {...handlers}
      />,
    );

    expect(await screen.findByText('No saved families yet')).toBeTruthy();
    expect(screen.getByText('Start a design and its saved directions will appear here.')).toBeTruthy();
    fireEvent.press(screen.getByText('Start a design'));
    expect(handlers.onStartDesign).toHaveBeenCalledTimes(1);
  });

  test('lists canonical design families when no project is selected', async () => {
    const client = api();
    const handlers = callbacks();
    await render(
      <StudioCollectionsWorkspace
        api={client}
        project={null}
        createdBy="usr_designer"
        {...handlers}
      />,
    );

    expect(await screen.findByText('Sapphire orbit ring')).toBeTruthy();
    expect(client.getStudioProjectHistory).not.toHaveBeenCalled();
    expect(client.getDesignFamily).not.toHaveBeenCalled();
    expect(screen.queryByText(/factory/i)).toBeNull();
  });

  test('opens the recently active variation from an unsorted family without claiming revision recency', async () => {
    const unsortedFamily = {
      ...family,
      variations: [
        {
          ...family.variations[1],
          root_id: 'project_newest',
          variation_label: 'Newest direction',
          cover_asset_id: 'asset_newest',
          updated_at: '2026-07-12T05:00:00Z',
        },
        {
          ...family.variations[0],
          root_id: 'project_oldest',
          variation_label: 'Oldest direction',
          cover_asset_id: 'asset_oldest',
          updated_at: '2026-07-12T01:00:00Z',
        },
        {
          ...family.variations[1],
          root_id: 'project_middle',
          variation_label: 'Middle direction',
          cover_asset_id: 'asset_middle',
          updated_at: '2026-07-12T03:00:00Z',
        },
      ],
    };
    const client = api({
      listDesignFamilies: jest.fn(async () => ({
        data: { families: [unsortedFamily] }, error: null, status: 200,
      })),
    });
    const handlers = callbacks();

    await render(
      <StudioCollectionsWorkspace
        api={client}
        project={null}
        createdBy="usr_designer"
        {...handlers}
      />,
    );

    expect(await screen.findByText('Recently active · Newest direction')).toBeTruthy();
    expect(screen.queryByText(/latest.*revision|newest.*revision/i)).toBeNull();
    expect(client.assetImageUrl).toHaveBeenCalledWith('asset_newest');
    expect(client.assetImageUrl).not.toHaveBeenCalledWith('asset_oldest');
    expect(client.assetImageUrl).not.toHaveBeenCalledWith('asset_middle');

    await fireEvent.press(screen.getByLabelText('Open recently active variation: Newest direction'));
    expect(handlers.onOpenProject).toHaveBeenCalledWith('project_newest');
  });

  test('shows semantic family lineage, revision compare, and sibling navigation without raw IDs', async () => {
    const client = api();
    const handlers = callbacks();
    await render(
      <AuthenticatedImageProvider
        allowedOrigin="https://test"
        headers={{ Authorization: 'Bearer first-party-token' }}>
        <StudioCollectionsWorkspace
          api={client}
          project={project}
          createdBy="usr_designer"
          {...handlers}
        />
      </AuthenticatedImageProvider>,
    );

    expect(await screen.findByText('Sapphire orbit ring')).toBeTruthy();
    expect(screen.getByLabelText('Design family cover').props.source.headers).toEqual({
      Authorization: 'Bearer first-party-token',
    });
    expect(screen.getByText('Original family direction')).toBeTruthy();
    expect(screen.getByText('Branched from Variation 1 · Original')).toBeTruthy();
    expect(screen.getByText('Variation 2 · White metal study')).toBeTruthy();
    expect(screen.queryByText(/project_main|project_white|asset_1|asset_2|family_orbit|design_ring/i)).toBeNull();
    await fireEvent.press(screen.getByLabelText('Open White metal study'));
    expect(handlers.onOpenProject).toHaveBeenCalledWith('project_white');

    expect(screen.queryByLabelText('Compare revision 1')).toBeNull();
    expect(screen.queryByText('Restore revision 1 as new')).toBeNull();
    await fireEvent.press(screen.getByLabelText('Show revision history (2)'));
    await fireEvent.press(screen.getByLabelText('Compare revision 1'));
    await fireEvent.press(screen.getByLabelText('Compare revision 2'));
    expect(screen.getByText('Comparing revision 1 and revision 2')).toBeTruthy();
    expect(screen.getByTestId('selected-revision-comparison')).toBeTruthy();
    expect(screen.getByText('Before: Revision 1')).toBeTruthy();
    expect(screen.getByText('After: Revision 2')).toBeTruthy();
    expect(screen.getByLabelText('Revision 1 comparison').props.source.headers).toEqual({
      Authorization: 'Bearer first-party-token',
    });
    expect(screen.getByLabelText('Revision 2 comparison').props.source.headers).toEqual({
      Authorization: 'Bearer first-party-token',
    });
    expect(screen.getByLabelText('Inspect comparison in detail')).toBeTruthy();
    expect(screen.getAllByText('Original direction · Design facts confirmed').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Refined from Revision 1 · Design facts confirmed').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Jul 12, 2026').length).toBeGreaterThan(0);
    expect(screen.queryByText(/project_main|project_white|asset_1|asset_2|family_orbit|design_ring/i)).toBeNull();
  });

  test('keeps saved client, marketing, and view outputs discoverable beside their exact revision', async () => {
    const savedProject: ProjectDetail = {
      ...project,
      assets: [
        {
          asset_id: 'asset_1', root_id: 'project_main', parent_asset_id: null,
          capability: 'SPEC_RENDER', provenance: 'generated_concept', revision: 1,
          design_id: 'design_ring', design_version: 1, region: null, instruction: null,
          drift: null, pinned: false, media_type: 'image/png', image_url: 'https://test/revision-1.png',
          created_by: 'usr_designer', created_at: '2026-07-12T01:00:00Z', legacy_provenance: false,
        },
        {
          asset_id: 'asset_2', root_id: 'project_main', parent_asset_id: 'asset_1',
          capability: 'LOCALIZED_EDIT', provenance: 'localized_edit', revision: 2,
          design_id: 'design_ring', design_version: 2, region: 'metal', instruction: 'Rose gold',
          drift: 0.01, pinned: false, media_type: 'image/png', image_url: 'https://test/revision-2.png',
          created_by: 'usr_designer', created_at: '2026-07-12T02:00:00Z', legacy_provenance: false,
        },
      ],
      derived_assets: [
        {
          asset_id: 'presentation_source', root_id: 'project_main', parent_asset_id: 'asset_2',
          capability: 'EVALUATION_IMAGE', provenance: 'generated_concept', revision: null,
          design_id: 'design_ring', design_version: 2, region: null, instruction: null,
          drift: 0.01, pinned: false, media_type: 'image/png', image_url: 'https://test/source.png',
          created_by: 'usr_designer', created_at: '2026-07-12T03:30:00Z', legacy_provenance: false,
        },
        {
          asset_id: 'client_output', root_id: 'project_main', parent_asset_id: 'presentation_source',
          capability: 'CLIENT_BEAUTY_RENDER', provenance: 'generated_concept', revision: null,
          design_id: 'design_ring', design_version: 2, region: null, instruction: null,
          drift: 0.01, pinned: false, media_type: 'image/png', image_url: 'https://test/client.png',
          created_by: 'usr_designer', created_at: '2026-07-12T04:00:00Z', legacy_provenance: false,
        },
        {
          asset_id: 'view_output', root_id: 'project_main', parent_asset_id: 'asset_2',
          capability: 'LINE_ART', provenance: 'designer_confirmed_line_art', revision: null,
          design_id: 'design_ring', design_version: 2, region: null, instruction: null,
          drift: 0.01, pinned: false, media_type: 'image/png', image_url: 'https://test/view.png',
          created_by: 'usr_designer', created_at: '2026-07-12T03:00:00Z', legacy_provenance: false,
        },
        {
          asset_id: 'marketing_output', root_id: 'project_main', parent_asset_id: 'asset_2',
          capability: 'MARKETING_IMAGE', provenance: 'generated_concept', revision: null,
          design_id: 'design_ring', design_version: 2, region: null, instruction: null,
          drift: 0.01, pinned: false, media_type: 'image/webp', image_url: 'https://test/marketing.webp',
          created_by: 'usr_designer', created_at: '2026-07-12T05:00:00Z', legacy_provenance: false,
        },
      ],
    };
    const client = api();
    const deliverProtectedFile = jest.fn(async () => undefined);
    await render(
      <AuthenticatedImageProvider
        allowedOrigin="https://test"
        headers={{ Authorization: 'Bearer first-party-token' }}>
        <StudioCollectionsWorkspace
          api={client}
          project={savedProject}
          createdBy="usr_designer"
          deliverProtectedFile={deliverProtectedFile}
          {...callbacks()}
        />
      </AuthenticatedImageProvider>,
    );

    expect(await screen.findByText('Presentation images')).toBeTruthy();
    expect(screen.getByLabelText('Show presentation images (3)').props.accessibilityState).toEqual({
      expanded: false,
    });
    expect(screen.queryByText('Client beauty render')).toBeNull();
    await fireEvent.press(screen.getByLabelText('Show presentation images (3)'));
    expect(screen.getByLabelText('Hide presentation images (3)').props.accessibilityState).toEqual({
      expanded: true,
    });
    expect(screen.getByText('Client beauty render')).toBeTruthy();
    expect(screen.getByText('Saved technical view')).toBeTruthy();
    expect(screen.getByText('Marketing image')).toBeTruthy();
    expect(screen.getAllByText('From Revision 2')).toHaveLength(3);
    expect(screen.getByLabelText('Client beauty render').props.source.headers).toEqual({
      Authorization: 'Bearer first-party-token',
    });
    expect(screen.queryByText(/generated_concept|designer_confirmed|CLIENT_BEAUTY_RENDER|LINE_ART/i)).toBeNull();
    expect(deliverProtectedFile).not.toHaveBeenCalled();

    await fireEvent.press(screen.getByText('Export client beauty render'));
    await waitFor(() => expect(deliverProtectedFile).toHaveBeenCalledWith({
      url: 'https://test/assets/client_output.png',
      name: 'facetta-client-beauty-render.png',
      mediaType: 'image/png',
    }));
    await fireEvent.press(screen.getByText('Export saved technical view'));
    await waitFor(() => expect(deliverProtectedFile).toHaveBeenCalledWith({
      url: 'https://test/assets/view_output.png',
      name: 'facetta-saved-technical-view.png',
      mediaType: 'image/png',
    }));
    await fireEvent.press(screen.getByText('Export marketing image'));
    await waitFor(() => expect(deliverProtectedFile).toHaveBeenCalledWith({
      url: 'https://test/assets/marketing_output.png',
      name: 'facetta-marketing-image.webp',
      mediaType: 'image/webp',
    }));
  });

  test('fails closed when a saved output source cannot be resolved', async () => {
    const unresolvedProject: ProjectDetail = {
      ...project,
      derived_assets: [{
        asset_id: 'client_output', root_id: 'project_main', parent_asset_id: 'missing_source',
        capability: 'CLIENT_BEAUTY_RENDER', provenance: 'generated_concept', revision: null,
        design_id: 'design_ring', design_version: 2, region: null, instruction: null,
        drift: 0.01, pinned: false, media_type: 'image/png', image_url: 'https://test/client.png',
        created_by: 'usr_designer', created_at: '2026-07-12T04:00:00Z', legacy_provenance: false,
      }],
    };
    await render(
      <StudioCollectionsWorkspace
        api={api()}
        project={unresolvedProject}
        createdBy="usr_designer"
        {...callbacks()}
      />,
    );

    await screen.findByText('Presentation images');
    await fireEvent.press(screen.getByLabelText('Show presentation images (1)'));
    expect(await screen.findByText('Client beauty render')).toBeTruthy();
    expect(screen.getByText('Source details unavailable')).toBeTruthy();
    expect(screen.queryByText(/lineage/i)).toBeNull();
    expect(screen.queryByText(/exact source retained/i)).toBeNull();
  });

  test('reports a protected export failure without opening or changing the saved output', async () => {
    const savedProject: ProjectDetail = {
      ...project,
      derived_assets: [{
        asset_id: 'client_output', root_id: 'project_main', parent_asset_id: 'asset_2',
        capability: 'CLIENT_BEAUTY_RENDER', provenance: 'generated_concept', revision: null,
        design_id: 'design_ring', design_version: 2, region: null, instruction: null,
        drift: 0.01, pinned: false, media_type: 'image/png', image_url: 'https://test/client.png',
        created_by: 'usr_designer', created_at: '2026-07-12T04:00:00Z', legacy_provenance: false,
      }],
    };
    const deliverProtectedFile = jest.fn(async () => { throw new Error('Session expired'); });
    await render(
      <StudioCollectionsWorkspace
        api={api()}
        project={savedProject}
        createdBy="usr_designer"
        deliverProtectedFile={deliverProtectedFile}
        {...callbacks()}
      />,
    );

    await screen.findByText('Presentation images');
    await fireEvent.press(screen.getByLabelText('Show presentation images (1)'));
    await screen.findByText('Client beauty render');
    await fireEvent.press(screen.getByText('Export client beauty render'));
    expect(await screen.findByText(
      'Facetta could not export the client beauty render. Try again.',
    )).toBeTruthy();
    expect(screen.getByText('Client beauty render')).toBeTruthy();
  });

  test('navigates to All families and back without requiring host-level state changes', async () => {
    const client = api();
    const handlers = callbacks();
    await render(
      <StudioCollectionsWorkspace
        api={client}
        project={project}
        createdBy="usr_designer"
        {...handlers}
      />,
    );
    await screen.findByText('Revision history');
    await fireEvent.press(screen.getByRole('button', { name: 'All families' }));
    expect(await screen.findByText('All Designs')).toBeTruthy();
    expect(screen.queryByText('Revision history')).toBeNull();

    await fireEvent.press(screen.getByText('Back to current variation'));
    expect(await screen.findByText('Revision history')).toBeTruthy();
    expect(handlers.onOpenProject).not.toHaveBeenCalled();
  });

  test('routes variation creation to canonical Vary and restores only against exact active lineage', async () => {
    const client = api();
    const handlers = callbacks();
    await render(
      <StudioCollectionsWorkspace
        api={client}
        project={project}
        createdBy="usr_designer"
        {...handlers}
      />,
    );
    await screen.findByText('Revision history');

    expect(screen.queryByText('Variation name')).toBeNull();
    expect(screen.queryByPlaceholderText('Rose gold study')).toBeNull();
    await fireEvent.press(screen.getByText('Vary this revision'));
    expect(handlers.onVaryCurrent).toHaveBeenCalledTimes(1);

    expect(screen.queryByText('Restore revision 1 as new')).toBeNull();
    await fireEvent.press(screen.getByLabelText('Show revision history (2)'));
    await fireEvent.press(screen.getByText('Restore revision 1 as new'));
    await waitFor(() => expect(client.restoreStudioRevision).toHaveBeenCalledWith(
      'project_main',
      'asset_1',
      {
        created_by: 'usr_designer',
        expected_active_asset_id: 'asset_2',
        expected_design_version: 2,
      },
    ));
    expect(handlers.onProjectChanged).toHaveBeenCalledWith(expect.objectContaining({
      active_asset_id: 'asset_3',
    }));
  });

  test('refreshes history after Restore and presents the newly active immutable revision', async () => {
    const restoredHistory = {
      ...history,
      active_asset_id: 'asset_3',
      revisions: [
        ...history.revisions,
        {
          ...history.revisions[0],
          revision: 3,
          asset_id: 'asset_3',
          parent_asset_id: 'asset_2',
          design_version: 3,
          action: 'restore' as const,
          change_summary: 'Restored Revision 1 as a new revision.',
          restored_from_asset_id: 'asset_1',
          created_at: '2026-07-12T03:00:00Z',
        },
      ],
    };
    const restoredProject: ProjectDetail = {
      ...project,
      active_asset_id: 'asset_3',
      active_design_version: 3,
      cover_asset_id: 'asset_3',
      primary_revision_count: 3,
    };
    const getStudioProjectHistory = jest.fn()
      .mockResolvedValueOnce({ data: history, error: null, status: 200 })
      .mockResolvedValueOnce({ data: restoredHistory, error: null, status: 200 });
    const client = api({
      getStudioProjectHistory,
      restoreStudioRevision: jest.fn(async () => ({
        data: {
          status: 'restored_as_new_revision' as const,
          restored_from_asset_id: 'asset_1',
          new_asset_id: 'asset_3',
          new_design_version: 3,
          spec_change: [],
          project: restoredProject,
        },
        error: null,
        status: 201,
      })),
    });
    const onSelectDestination = jest.fn();

    function CollectionsHarness() {
      const [currentProject, setCurrentProject] = React.useState(project);
      return (
        <>
          <Text>Harness active asset: {currentProject.active_asset_id}</Text>
          <StudioCollectionsWorkspace
            api={client}
            project={currentProject}
            createdBy="usr_designer"
            onOpenProject={jest.fn()}
            onProjectChanged={setCurrentProject}
            onStartDesign={jest.fn()}
            onVaryCurrent={jest.fn()}
            onContinueRefining={jest.fn()}
            destinationContext={{
              activeProjectId: currentProject.root_id,
              activeRevisionId: currentProject.active_asset_id,
              hasExactSpecification: currentProject.active_design_version !== null,
              factoryEligible: false,
            }}
            onSelectDestination={(destinationId) => {
              onSelectDestination(destinationId, currentProject.active_asset_id);
            }}
          />
        </>
      );
    }

    await render(<CollectionsHarness />);
    await screen.findByLabelText('Show revision history (2)');
    await fireEvent.press(screen.getByLabelText('Show revision history (2)'));
    await fireEvent.press(screen.getByText('Restore revision 1 as new'));

    expect(await screen.findByText('Harness active asset: asset_3')).toBeTruthy();
    expect(await screen.findByLabelText('Show revision history (3)')).toBeTruthy();
    expect(getStudioProjectHistory).toHaveBeenCalledTimes(2);
    await fireEvent.press(screen.getByText('Client'));
    expect(onSelectDestination).toHaveBeenCalledWith('client', 'asset_3');
  });

  test('keeps dense family records collapsed and continues refining the exact selected variation', async () => {
    const handlers = callbacks();
    await render(
      <StudioCollectionsWorkspace
        api={api()}
        project={project}
        createdBy="usr_designer"
        {...handlers}
      />,
    );

    expect(await screen.findByText('Sapphire orbit ring')).toBeTruthy();
    expect(screen.getByLabelText('Show presentation images (0)').props.accessibilityState).toEqual({
      expanded: false,
    });
    expect(screen.getByLabelText('Show revision history (2)').props.accessibilityState).toEqual({
      expanded: false,
    });
    expect(screen.queryByText('No presentation or view images have been saved for this variation.')).toBeNull();
    expect(screen.queryByLabelText('Compare revision 1')).toBeNull();
    expect(screen.queryByText('Restore revision 1 as new')).toBeNull();

    await fireEvent.press(screen.getByText('Client'));
    expect(handlers.onSelectDestination).toHaveBeenCalledWith('client');
    expect(screen.getByText('Use this revision')).toBeTruthy();
    expect(screen.queryByText('Library')).toBeNull();
    expect(screen.queryByText('Factory')).toBeNull();

    await fireEvent.press(screen.getByRole('button', { name: 'Continue refining' }));
    expect(handlers.onContinueRefining).toHaveBeenCalledTimes(1);
    expect(handlers.onOpenProject).not.toHaveBeenCalled();

    await fireEvent.press(screen.getByLabelText('Show revision history (2)'));
    expect(screen.getByText('Revision 2 · Active')).toBeTruthy();
    expect(screen.getByText('Refined from Revision 1 · Design facts confirmed')).toBeTruthy();
    expect(screen.getByText('Restore revision 1 as new')).toBeTruthy();

    await fireEvent.press(screen.getByLabelText('Hide revision history (2)'));
    expect(screen.queryByText('Revision 2 · Active')).toBeNull();
    expect(screen.queryByText('Restore revision 1 as new')).toBeNull();
  });

  test('shows Factory in the shared chooser only when the host verifies eligibility', async () => {
    const handlers = callbacks();
    await render(
      <StudioCollectionsWorkspace
        api={api()}
        project={project}
        createdBy="usr_designer"
        {...handlers}
        destinationContext={{ ...handlers.destinationContext, factoryEligible: true }}
      />,
    );

    expect(await screen.findByText('Use this revision')).toBeTruthy();
    expect(screen.queryByText('Library')).toBeNull();
    await fireEvent.press(screen.getByText('Factory'));
    expect(handlers.onSelectDestination).toHaveBeenCalledWith('factory');
  });

  test('describes pre-spec Collections assets as saved visual directions', async () => {
    const handlers = callbacks();
    await render(
      <StudioCollectionsWorkspace
        api={api()}
        project={{ ...project, active_design_version: null }}
        createdBy="usr_designer"
        {...handlers}
        destinationContext={{
          ...handlers.destinationContext,
          hasExactSpecification: false,
        }}
      />,
    );

    expect(await screen.findByText(
      'Prepare this saved visual direction for a client or marketing. Its design history will not change.',
    )).toBeTruthy();
    expect(screen.queryByText(/exact saved revision/)).toBeNull();
    expect(screen.queryByText('Factory')).toBeNull();
  });

  test('does not invent family data when history is unavailable, then retries the exact project', async () => {
    const unavailable = {
      data: null,
      error: {
        code: 'INVALID_RESPONSE', message: 'History response is unavailable.',
        category: 'invalid_response' as const, status: 200, retryable: false,
      },
      status: 200,
    };
    const getStudioProjectHistory = jest.fn()
      .mockResolvedValueOnce(unavailable)
      .mockResolvedValueOnce({ data: history, error: null, status: 200 });
    const client = api({
      getStudioProjectHistory,
    });
    const handlers = callbacks();
    await render(
      <StudioCollectionsWorkspace
        api={client}
        project={project}
        createdBy="usr_designer"
        {...handlers}
      />,
    );

    expect(await screen.findByText('Saved history is unavailable')).toBeTruthy();
    expect(screen.getByText(
      'Facetta will not guess at missing history. The selected design remains unchanged.',
    )).toBeTruthy();
    expect(client.getDesignFamily).not.toHaveBeenCalled();
    expect(screen.queryByText(/project_main|asset_2|design_ring/i)).toBeNull();

    expect(screen.queryByText('Variation name')).toBeNull();
    await fireEvent.press(screen.getByText('Vary this revision'));
    expect(handlers.onVaryCurrent).toHaveBeenCalledTimes(1);

    await fireEvent.press(screen.getByText('Retry'));

    expect(await screen.findByText('Use this revision')).toBeTruthy();
    expect(screen.queryByText('Library')).toBeNull();
    expect(screen.queryByText('Saved history is unavailable')).toBeNull();
    expect(getStudioProjectHistory).toHaveBeenCalledTimes(2);
    expect(getStudioProjectHistory).toHaveBeenLastCalledWith('project_main');
    expect(client.getDesignFamily).toHaveBeenCalledTimes(1);
    expect(client.getDesignFamily).toHaveBeenCalledWith('family_orbit');
  });

  test('disables Vary navigation when the selected project has no active revision', async () => {
    const client = api();
    const handlers = callbacks();
    await render(
      <StudioCollectionsWorkspace
        api={client}
        project={{ ...project, active_asset_id: null, cover_asset_id: null }}
        createdBy="usr_designer"
        {...handlers}
      />,
    );
    await screen.findByText('Saved history is unavailable');
    expect(screen.getByText('Vary this revision').parent?.props.accessibilityState).toEqual({ disabled: true });
    await fireEvent.press(screen.getByText('Vary this revision'));
    expect(handlers.onVaryCurrent).not.toHaveBeenCalled();
  });
});
