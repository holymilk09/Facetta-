import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { AuthenticatedImage as Image } from '../AuthenticatedImage';

import { Button, Notice } from '../components';
import { theme } from '../theme';
import type {
  AssetSummary,
  DesignFamilyDetail,
  DesignFamilyVariation,
  ProjectDetail,
  StudioHistoryRevision,
  StudioProjectHistory,
  WorkspaceCollection,
  WorkspaceCollectionTemplate,
} from '../trusted/types';
import { designerErrorMessage } from './designerErrorMessage';
import type { StudioGateway } from './gateway';
import { StudioComparisonInspector } from './StudioComparisonInspector';
import { StudioDestinationChooser } from './StudioDestinationChooser';
import type { StudioDestinationContext, StudioDestinationId } from './destinations';

export type StudioCollectionsApi = Pick<StudioGateway,
  | 'getDesignFamily'
  | 'listDesignFamilies'
  | 'favoriteDesignFamily'
  | 'unfavoriteDesignFamily'
  | 'updateDesignFamilyTags'
  | 'getStudioProjectHistory'
  | 'restoreStudioRevision'
  | 'assetImageUrl'
  | 'listWorkspaceCollections'
  | 'listWorkspaceCollectionMemberships'
  | 'createWorkspaceCollection'
  | 'updateWorkspaceCollection'
  | 'deleteWorkspaceCollection'
  | 'listDesignFamilyCollections'
  | 'addDesignFamilyToCollection'
  | 'removeDesignFamilyFromCollection'
>;

export interface StudioCollectionsWorkspaceProps {
  api: StudioCollectionsApi;
  project: ProjectDetail | null;
  createdBy: string;
  onOpenProject: (projectId: string) => void;
  onProjectChanged: (project: ProjectDetail) => void;
  /** Opens Create from a confirmed empty Collections state. */
  onStartDesign: () => void;
  /** Opens the canonical Vary workspace for the currently active project. */
  onVaryCurrent: () => void;
  /** Returns the selected exact variation to the canonical Refine workspace. */
  onContinueRefining?: () => void;
  /** One registry-driven handoff for the currently active immutable revision. */
  destinationContext?: StudioDestinationContext;
  onSelectDestination?: (destinationId: StudioDestinationId) => void;
  /** Host-owned authenticated delivery. Protected bytes are fetched only after Export. */
  deliverProtectedFile?: (request: {
    url: string;
    name: string;
    mediaType: string;
  }) => Promise<void>;
  /** Optional host navigation; the workspace has an internal fallback. */
  onShowAllFamilies?: () => void;
}

interface WorkspaceData {
  history: StudioProjectHistory;
  family: DesignFamilyDetail | null;
}

type FamilyIndexFilter = 'all' | 'recent' | 'favorites' | 'unfiled' | string;

const COLLECTION_TEMPLATES: readonly {
  id: WorkspaceCollectionTemplate;
  label: string;
}[] = [
  { id: 'generic', label: 'General' },
  { id: 'client', label: 'Client' },
  { id: 'order', label: 'Order' },
  { id: 'project', label: 'Project' },
  { id: 'campaign', label: 'Campaign' },
  { id: 'season', label: 'Season' },
  { id: 'jewelry_line', label: 'Jewelry line' },
  { id: 'personal_study', label: 'Personal study' },
  { id: 'custom', label: 'Custom' },
];

function familyTags(family: DesignFamilyDetail): string[] {
  return family.tags;
}

function variationName(variation: DesignFamilyVariation): string {
  return variation.variation_label?.trim()
    || `Variation ${variation.variation_index}`;
}

function variationDisplayName(variation: DesignFamilyVariation): string {
  return `Variation ${variation.variation_index} · ${variationName(variation)}`;
}

function collectionContext(collection: WorkspaceCollection): string | null {
  const clientName = collection.metadata.client_name;
  if (collection.template === 'client'
    && typeof clientName === 'string'
    && clientName.trim().length > 0) {
    return `Client · ${clientName.trim()}`;
  }
  return COLLECTION_TEMPLATES.find((template) => template.id === collection.template)?.label
    ?? null;
}

function linkedClientName(
  familyId: string | null,
  collections: WorkspaceCollection[],
  familyCollectionIds: Record<string, string[]> | null,
): string | null {
  if (familyId === null || familyCollectionIds === null) return null;
  const memberIds = new Set(familyCollectionIds[familyId] ?? []);
  const names = [...new Set(collections
    .filter((collection) => collection.template === 'client' && memberIds.has(collection.id))
    .map((collection) => collection.metadata.client_name)
    .filter((name): name is string => typeof name === 'string' && name.trim().length > 0)
    .map((name) => name.trim()))];
  return names.length === 1 ? names[0] : null;
}

/**
 * Project `updated_at` represents activity on the variation as a whole. It can
 * move for presentation or marketing work without appending a design revision,
 * so this is only a navigation/cover heuristic—not revision recency.
 */
function mostRecentlyActiveVariation(
  variations: DesignFamilyVariation[],
): DesignFamilyVariation | undefined {
  return [...variations].sort((left, right) => {
    const leftUpdatedAt = Date.parse(left.updated_at);
    const rightUpdatedAt = Date.parse(right.updated_at);
    if (Number.isNaN(leftUpdatedAt) !== Number.isNaN(rightUpdatedAt)) {
      return Number.isNaN(rightUpdatedAt) ? 1 : -1;
    }
    if (!Number.isNaN(leftUpdatedAt) && rightUpdatedAt !== leftUpdatedAt) {
      return rightUpdatedAt - leftUpdatedAt;
    }
    const sourceTimestampDifference = right.updated_at.localeCompare(left.updated_at);
    if (sourceTimestampDifference !== 0) return sourceTimestampDifference;
    const indexDifference = right.variation_index - left.variation_index;
    if (indexDifference !== 0) return indexDifference;
    return left.root_id.localeCompare(right.root_id);
  })[0];
}

function dateLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Date unavailable';
  return new Intl.DateTimeFormat('en', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
  }).format(date);
}

function revisionLineage(
  revision: StudioHistoryRevision,
  revisions: StudioHistoryRevision[],
): string {
  const sourceAssetId = revision.restored_from_asset_id ?? revision.parent_asset_id;
  const source = sourceAssetId === null
    ? null : revisions.find((candidate) => candidate.asset_id === sourceAssetId) ?? null;
  const relationship = revision.action === 'created' || source === null
    ? 'Original direction'
    : revision.action === 'restore'
      ? `Restored from Revision ${source.revision}`
      : `Refined from Revision ${source.revision}`;
  const authority = revision.design_version === null
    ? 'Visual direction'
    : 'Design facts confirmed';
  return `${relationship} · ${authority}`;
}

function variationLineage(
  variation: DesignFamilyVariation,
  family: DesignFamilyDetail,
): string {
  if (variation.branched_from_project_root_id === null) return 'Original family direction';
  const parent = family.variations.find((candidate) => (
    candidate.root_id === variation.branched_from_project_root_id
  ));
  return parent === undefined
    ? 'Branched from an earlier family direction'
    : `Branched from ${variationDisplayName(parent)}`;
}

const SAVED_OUTPUT_CAPABILITIES = new Set([
  'CLIENT_BEAUTY_RENDER',
  'CLIENT_PRODUCT_PHOTO',
  'MARKETING_IMAGE',
  'LINE_ART',
  'COLORED_LINE_ART',
  'FACTORY_DRAWING',
]);

const COLLECTIONS_DESTINATION_EXCLUSIONS = ['library'] as const;

const savedOutputLabel = (capability: string): string => ({
  CLIENT_BEAUTY_RENDER: 'Client beauty render',
  CLIENT_PRODUCT_PHOTO: 'Client product photo',
  MARKETING_IMAGE: 'Marketing image',
  LINE_ART: 'Saved technical view',
  COLORED_LINE_ART: 'Saved color view',
  FACTORY_DRAWING: 'Factory review drawing',
})[capability] ?? 'Saved output';

function savedOutputFileName(output: AssetSummary): string {
  const stem = savedOutputLabel(output.capability).toLowerCase().replace(/[^a-z0-9]+/g, '-');
  const extension = ({
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
    'image/avif': 'avif',
    'image/svg+xml': 'svg',
  })[output.media_type] ?? 'bin';
  return `facetta-${stem}.${extension}`;
}

function savedOutputLineage(
  output: AssetSummary,
  project: ProjectDetail,
  revisions: StudioHistoryRevision[],
): string {
  const revisionsByAsset = new Map(revisions.map((revision) => (
    [revision.asset_id, revision] as const
  )));
  const assetsById = new Map(
    [...project.assets, ...project.derived_assets].map((asset) => (
      [asset.asset_id, asset] as const
    )),
  );
  const visited = new Set<string>();
  let sourceId = output.parent_asset_id;
  while (sourceId !== null && !visited.has(sourceId)) {
    visited.add(sourceId);
    const sourceRevision = revisionsByAsset.get(sourceId);
    if (sourceRevision !== undefined) return `From Revision ${sourceRevision.revision}`;
    const sourceAsset = assetsById.get(sourceId);
    if (sourceAsset === undefined) {
      return 'Source details unavailable';
    }
    sourceId = sourceAsset.parent_asset_id;
  }
  return 'Source details unavailable';
}

export function StudioCollectionsWorkspace({
  api,
  project,
  createdBy,
  onOpenProject,
  onProjectChanged,
  onStartDesign,
  onVaryCurrent,
  onContinueRefining,
  destinationContext,
  onSelectDestination,
  onShowAllFamilies,
  deliverProtectedFile,
}: StudioCollectionsWorkspaceProps) {
  const [data, setData] = useState<WorkspaceData | null>(null);
  const [loading, setLoading] = useState(project !== null);
  const [error, setError] = useState<string | null>(null);
  const [compareAssetIds, setCompareAssetIds] = useState<string[]>([]);
  const [restoringAssetId, setRestoringAssetId] = useState<string | null>(null);
  const [families, setFamilies] = useState<DesignFamilyDetail[] | null>(null);
  const [collections, setCollections] = useState<WorkspaceCollection[]>([]);
  const [familyCollectionIds, setFamilyCollectionIds] = useState<Record<string, string[]> | null>(null);
  const [organizationError, setOrganizationError] = useState<string | null>(null);
  const [selectedFilter, setSelectedFilter] = useState<FamilyIndexFilter>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [showCreateCollection, setShowCreateCollection] = useState(false);
  const [collectionName, setCollectionName] = useState('');
  const [collectionTemplate, setCollectionTemplate] = useState<WorkspaceCollectionTemplate>('project');
  const [collectionClientName, setCollectionClientName] = useState('');
  const [collectionMutation, setCollectionMutation] = useState<string | null>(null);
  const [favoriteMutationFamilyId, setFavoriteMutationFamilyId] = useState<string | null>(null);
  const [tagEditingFamilyId, setTagEditingFamilyId] = useState<string | null>(null);
  const [tagDraft, setTagDraft] = useState('');
  const [tagMutationFamilyId, setTagMutationFamilyId] = useState<string | null>(null);
  const [collectionNotice, setCollectionNotice] = useState<string | null>(null);
  const [deleteConfirmationId, setDeleteConfirmationId] = useState<string | null>(null);
  const [viewingAllFamilies, setViewingAllFamilies] = useState(false);
  const [exportingAssetId, setExportingAssetId] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [showPresentationImages, setShowPresentationImages] = useState(false);
  const [showRevisionHistory, setShowRevisionHistory] = useState(false);
  const loadRequestId = useRef(0);

  const loadFamilyIndex = useCallback(async (requestId: number): Promise<void> => {
    const [result, collectionResult, membershipIndexResult] = await Promise.all([
      api.listDesignFamilies(createdBy),
      api.listWorkspaceCollections({ owner: createdBy }),
      api.listWorkspaceCollectionMemberships(createdBy),
    ]);
    if (loadRequestId.current !== requestId) return;
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'collections'));
      setLoading(false);
      return;
    }
    setFamilies(result.data.families);
    if (collectionResult.error !== null || membershipIndexResult.error !== null) {
      setOrganizationError('Collection organization is temporarily unavailable. All Designs is still safe to browse.');
      setLoading(false);
      return;
    }
    setCollections(collectionResult.data.collections);
    const familyIds = new Set(result.data.families.map((familyItem) => familyItem.family_id));
    const activeCollectionIds = new Set(collectionResult.data.collections.map((collection) => collection.id));
    const membershipIndex = membershipIndexResult.data.family_collection_ids;
    const indexedFamilyIds = Object.keys(membershipIndex);
    const indexMatchesFamilies = indexedFamilyIds.length === familyIds.size
      && indexedFamilyIds.every((familyId) => familyIds.has(familyId));
    const membershipsReferenceActiveCollections = Object.values(membershipIndex).every((collectionIds) => (
      collectionIds.every((collectionId) => activeCollectionIds.has(collectionId))
    ));
    if (!indexMatchesFamilies || !membershipsReferenceActiveCollections) {
      setOrganizationError('Collection memberships could not be verified. No design history was changed.');
      setLoading(false);
      return;
    }
    setFamilyCollectionIds(membershipIndex);
    setLoading(false);
  }, [api, createdBy]);

  const loadSelectedProjectHistory = useCallback(async (
    requestId: number,
    projectRootId: string,
    activeAssetId: string | null,
  ): Promise<void> => {
    const historyResult = await api.getStudioProjectHistory(projectRootId);
    if (loadRequestId.current !== requestId) return;
    if (historyResult.error !== null) {
      setError(designerErrorMessage(historyResult.error, 'collections'));
      setLoading(false);
      return;
    }
    if (historyResult.data.project_id !== projectRootId
      || historyResult.data.active_asset_id !== activeAssetId) {
      setError('This design changed while its history was opening. Reopen it to continue.');
      setLoading(false);
      return;
    }
    let family: DesignFamilyDetail | null = null;
    if (historyResult.data.family_id !== null) {
      const familyResult = await api.getDesignFamily(historyResult.data.family_id);
      if (loadRequestId.current !== requestId) return;
      if (familyResult.error !== null) {
        setError(designerErrorMessage(familyResult.error, 'collections'));
        setLoading(false);
        return;
      }
      if (familyResult.data.family_id !== historyResult.data.family_id
        || !familyResult.data.variations.some((variation) => (
          variation.root_id === projectRootId
        ))) {
        setError('This family no longer contains the selected variation. Return to All families.');
        setLoading(false);
        return;
      }
      family = familyResult.data;
    }
    setData({ history: historyResult.data, family });
    const collectionResult = await api.listWorkspaceCollections({ owner: createdBy });
    if (loadRequestId.current !== requestId) return;
    if (collectionResult.error !== null) {
      setOrganizationError('Collection organization is temporarily unavailable. This design history is unchanged.');
    } else {
      setCollections(collectionResult.data.collections);
      if (historyResult.data.family_id !== null) {
        const membershipResult = await api.listDesignFamilyCollections(historyResult.data.family_id);
        if (loadRequestId.current !== requestId) return;
        if (membershipResult.error !== null) {
          setOrganizationError('This family’s Collection memberships could not be verified.');
        } else {
          setFamilyCollectionIds({
            [historyResult.data.family_id]: membershipResult.data.collections.map((collection) => collection.id),
          });
        }
      }
    }
    setLoading(false);
  }, [api, createdBy]);

  const loadWorkspace = useCallback((): void => {
    const requestId = loadRequestId.current + 1;
    loadRequestId.current = requestId;
    setData(null);
    setError(null);
    setCompareAssetIds([]);
    setExportingAssetId(null);
    setExportError(null);
    setShowPresentationImages(false);
    setShowRevisionHistory(false);
    setFamilies(null);
    setCollections([]);
    setFamilyCollectionIds(null);
    setOrganizationError(null);
    setCollectionNotice(null);
    setDeleteConfirmationId(null);
    setLoading(true);
    if (project === null || viewingAllFamilies) {
      void loadFamilyIndex(requestId);
      return;
    }
    void loadSelectedProjectHistory(
      requestId,
      project.root_id,
      project.active_asset_id,
    );
  }, [
    loadFamilyIndex,
    loadSelectedProjectHistory,
    project?.active_asset_id,
    project?.active_design_version,
    project?.root_id,
    viewingAllFamilies,
  ]);

  useEffect(() => {
    loadWorkspace();
    return () => {
      loadRequestId.current += 1;
    };
  }, [loadWorkspace]);

  const exportSavedOutput = async (output: AssetSummary): Promise<void> => {
    if (deliverProtectedFile === undefined) return;
    setExportingAssetId(output.asset_id);
    setExportError(null);
    try {
      await deliverProtectedFile({
        url: api.assetImageUrl(output.asset_id),
        name: savedOutputFileName(output),
        mediaType: output.media_type,
      });
    } catch {
      setExportError(`Facetta could not export the ${savedOutputLabel(output.capability).toLowerCase()}. Try again.`);
    } finally {
      setExportingAssetId(null);
    }
  };

  const showAllFamilies = (): void => {
    if (onShowAllFamilies !== undefined) {
      onShowAllFamilies();
      return;
    }
    setViewingAllFamilies(true);
  };

  const openFromFamilyIndex = (projectId: string): void => {
    setViewingAllFamilies(false);
    onOpenProject(projectId);
  };

  const compared = useMemo(() => {
    if (data === null) return [];
    return data.history.revisions.filter((revision) => (
      compareAssetIds.includes(revision.asset_id)
    ));
  }, [compareAssetIds, data]);

  const toggleComparison = (assetId: string): void => {
    setCompareAssetIds((selected) => {
      if (selected.includes(assetId)) {
        return selected.filter((candidate) => candidate !== assetId);
      }
      return [...selected.slice(-1), assetId];
    });
  };

  const restoreRevision = async (revision: StudioHistoryRevision): Promise<void> => {
    if (project === null || project.active_asset_id === null
      || restoringAssetId !== null) return;
    setRestoringAssetId(revision.asset_id);
    setError(null);
    const result = await api.restoreStudioRevision(
      project.root_id,
      revision.asset_id,
      {
        created_by: createdBy,
        expected_active_asset_id: project.active_asset_id,
        expected_design_version: project.active_design_version,
      },
    );
    setRestoringAssetId(null);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'collections'));
      return;
    }
    if (result.data.restored_from_asset_id !== revision.asset_id
      || result.data.project.active_asset_id !== result.data.new_asset_id) {
      setError('Facetta could not verify the restored revision. Nothing was changed.');
      return;
    }
    onProjectChanged(result.data.project);
  };

  const createCollection = async (): Promise<void> => {
    const name = collectionName.trim();
    if (name.length === 0 || collectionMutation !== null) return;
    setCollectionMutation('create');
    setOrganizationError(null);
    const result = await api.createWorkspaceCollection({
      owner: createdBy,
      name,
      template: collectionTemplate,
      ...(collectionTemplate === 'client' && collectionClientName.trim().length > 0
        ? { metadata: { client_name: collectionClientName.trim() } }
        : {}),
    });
    setCollectionMutation(null);
    if (result.error !== null) {
      setOrganizationError(designerErrorMessage(result.error, 'collections'));
      return;
    }
    setCollections((current) => [...current, result.data].sort((left, right) => (
      left.name.localeCompare(right.name)
    )));
    setCollectionName('');
    setCollectionClientName('');
    setShowCreateCollection(false);
    setSelectedFilter('all');
    setCollectionNotice(`${result.data.name} is ready. Add families when you choose.`);
  };

  const archiveCollection = async (collection: WorkspaceCollection): Promise<void> => {
    if (collectionMutation !== null) return;
    setCollectionMutation(collection.id);
    setOrganizationError(null);
    const result = await api.updateWorkspaceCollection(collection.id, { archived: true });
    setCollectionMutation(null);
    if (result.error !== null) {
      setOrganizationError(designerErrorMessage(result.error, 'collections'));
      return;
    }
    setCollections((current) => current.filter((item) => item.id !== collection.id));
    setFamilyCollectionIds((current) => current === null ? null : Object.fromEntries(
      Object.entries(current).map(([familyId, ids]) => (
        [familyId, ids.filter((id) => id !== collection.id)]
      )),
    ));
    setSelectedFilter('all');
    setCollectionNotice(`${collection.name} was archived. Its design families and history are unchanged.`);
  };

  const deleteCollection = async (collection: WorkspaceCollection): Promise<void> => {
    if (deleteConfirmationId !== collection.id) {
      setDeleteConfirmationId(collection.id);
      return;
    }
    if (collectionMutation !== null) return;
    setCollectionMutation(collection.id);
    setOrganizationError(null);
    const result = await api.deleteWorkspaceCollection(collection.id);
    setCollectionMutation(null);
    if (result.error !== null) {
      setOrganizationError(designerErrorMessage(result.error, 'collections'));
      return;
    }
    setCollections((current) => current.filter((item) => item.id !== collection.id));
    setFamilyCollectionIds((current) => current === null ? null : Object.fromEntries(
      Object.entries(current).map(([familyId, ids]) => (
        [familyId, ids.filter((id) => id !== collection.id)]
      )),
    ));
    setDeleteConfirmationId(null);
    setSelectedFilter('all');
    setCollectionNotice(`${collection.name} was deleted. Only its memberships were removed.`);
  };

  const toggleFamilyCollection = async (
    familyId: string,
    collection: WorkspaceCollection,
  ): Promise<void> => {
    if (collectionMutation !== null || familyCollectionIds === null) return;
    const currentIds = familyCollectionIds[familyId] ?? [];
    const removing = currentIds.includes(collection.id);
    setCollectionMutation(collection.id);
    setOrganizationError(null);
    const result = removing
      ? await api.removeDesignFamilyFromCollection(familyId, collection.id)
      : await api.addDesignFamilyToCollection(familyId, collection.id);
    setCollectionMutation(null);
    if (result.error !== null) {
      setOrganizationError(designerErrorMessage(result.error, 'collections'));
      return;
    }
    const nextIds = removing
      ? currentIds.filter((id) => id !== collection.id)
      : [...currentIds, collection.id];
    setFamilyCollectionIds((current) => ({ ...(current ?? {}), [familyId]: nextIds }));
    setCollections((current) => current.map((item) => item.id === collection.id ? {
      ...item,
      family_count: Math.max(0, item.family_count + (removing ? -1 : 1)),
    } : item));
    setCollectionNotice(removing
      ? `Removed this family from ${collection.name}. Its revisions are unchanged.`
      : `Added this family to ${collection.name}.`);
  };

  const toggleFamilyFavorite = async (familyItem: DesignFamilyDetail): Promise<void> => {
    if (favoriteMutationFamilyId !== null) return;
    const nextFavorite = !familyItem.is_favorite;
    setFavoriteMutationFamilyId(familyItem.family_id);
    setOrganizationError(null);
    const result = nextFavorite
      ? await api.favoriteDesignFamily(familyItem.family_id, createdBy)
      : await api.unfavoriteDesignFamily(familyItem.family_id, createdBy);
    setFavoriteMutationFamilyId(null);
    if (result.error !== null) {
      setOrganizationError(designerErrorMessage(result.error, 'collections'));
      return;
    }
    setFamilies((current) => current?.map((candidate) => (
      candidate.family_id === familyItem.family_id
        ? {
            ...candidate,
            is_favorite: nextFavorite,
            favorited_at: nextFavorite ? new Date().toISOString() : null,
          }
        : candidate
    )) ?? null);
    setCollectionNotice(nextFavorite
      ? `${familyItem.title} was added to Favorites.`
      : `${familyItem.title} was removed from Favorites.`);
  };

  const saveFamilyTags = async (familyItem: DesignFamilyDetail): Promise<void> => {
    if (tagMutationFamilyId !== null) return;
    const requestedTags = tagDraft.split(',').map((tag) => tag.trim()).filter(Boolean);
    setTagMutationFamilyId(familyItem.family_id);
    setOrganizationError(null);
    const result = await api.updateDesignFamilyTags(
      familyItem.family_id,
      createdBy,
      requestedTags,
    );
    setTagMutationFamilyId(null);
    if (result.error !== null) {
      setOrganizationError(designerErrorMessage(result.error, 'collections'));
      return;
    }
    if (result.data.family_id !== familyItem.family_id) {
      setOrganizationError('Facetta could not verify which family was tagged. No local result was applied.');
      return;
    }
    setFamilies((current) => current?.map((candidate) => (
      candidate.family_id === familyItem.family_id
        ? { ...candidate, tags: result.data.tags }
        : candidate
    )) ?? null);
    setTagEditingFamilyId(null);
    setTagDraft('');
    setCollectionNotice(result.data.tags.length === 0
      ? `Cleared tags from ${familyItem.title}. Its design history is unchanged.`
      : `Saved tags for ${familyItem.title}.`);
  };

  const allTags = useMemo(() => [...new Set((families ?? []).flatMap(familyTags))]
    .sort((left, right) => left.localeCompare(right)), [families]);

  const collectionsById = useMemo(() => new Map(
    collections.map((collection) => [collection.id, collection] as const),
  ), [collections]);

  const visibleFamilies = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    const recentFamilies = [...(families ?? [])].sort((left, right) => {
      const activityOrder = right.updated_at.localeCompare(left.updated_at);
      return activityOrder !== 0 ? activityOrder : left.family_id.localeCompare(right.family_id);
    }).slice(0, 12);
    const candidates = selectedFilter === 'recent' ? recentFamilies : (families ?? []);
    return candidates.filter((familyItem) => {
      const tags = familyTags(familyItem);
      const memberships = familyCollectionIds?.[familyItem.family_id];
      const organizationTerms = (memberships ?? []).flatMap((collectionId) => {
        const collection = collectionsById.get(collectionId);
        if (collection === undefined) return [];
        return [
          collection.name,
          collectionContext(collection) ?? '',
          ...Object.values(collection.metadata).filter((value): value is string => (
            typeof value === 'string'
          )),
        ];
      });
      const matchesQuery = normalizedQuery.length === 0 || [
        familyItem.title,
        ...familyItem.variations.map((variation) => variation.title),
        ...tags,
        ...organizationTerms,
      ].some((value) => value.toLowerCase().includes(normalizedQuery));
      const matchesTag = selectedTag === null || tags.includes(selectedTag);
      const matchesFilter = selectedFilter === 'all' || selectedFilter === 'recent'
        ? true
        : selectedFilter === 'favorites'
          ? familyItem.is_favorite
          : selectedFilter === 'unfiled'
            ? memberships?.length === 0
            : memberships?.includes(selectedFilter) === true;
      return matchesQuery && matchesTag && matchesFilter;
    });
  }, [collectionsById, families, familyCollectionIds, searchQuery, selectedFilter, selectedTag]);

  if (project === null || viewingAllFamilies) {
    if (loading) {
      return (
        <View style={styles.loadingState}>
          <ActivityIndicator color={theme.accent} />
          <Text style={styles.meta}>Loading design families…</Text>
        </View>
      );
    }
    return (
      <ScrollView contentContainerStyle={styles.workspace}>
        {viewingAllFamilies && project !== null && (
          <View style={styles.backRow}>
            <Button
              title="Back to current variation"
              kind="ghost"
              onPress={() => setViewingAllFamilies(false)}
            />
          </View>
        )}
        <Text style={styles.eyebrow}>COLLECTIONS</Text>
        <Text style={styles.familyTitle}>Your design families</Text>
        <Text style={styles.sectionCopy}>
          Design families stay intact. Collections only organize them and never change their revisions.
        </Text>
        {error !== null && <Notice kind="error" text={error} />}
        {organizationError !== null && <Notice kind="error" text={organizationError} />}
        {collectionNotice !== null && <Notice kind="ok" text={collectionNotice} />}
        {error !== null ? (
          <View style={styles.emptyState}>
            <Text style={styles.emptyTitle}>Collections are temporarily unavailable</Text>
            <Text style={styles.emptyCopy}>Your saved design history is unchanged. Check the connection and try again.</Text>
            <View style={styles.emptyAction}>
              <Button title="Retry" onPress={loadWorkspace} />
            </View>
          </View>
        ) : families?.length === 0 ? (
          <View style={styles.emptyState}>
            <Text style={styles.emptyTitle}>No saved families yet</Text>
            <Text style={styles.emptyCopy}>Start a design and its saved directions will appear here.</Text>
            <View style={styles.emptyAction}>
              <Button title="Start a design" onPress={onStartDesign} />
            </View>
          </View>
        ) : (
          <>
            <View style={styles.organizationPanel}>
              <TextInput
                accessibilityLabel="Search designs"
                value={searchQuery}
                onChangeText={setSearchQuery}
                placeholder="Search designs and tags"
                placeholderTextColor={theme.faint}
                style={styles.searchInput}
              />
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.filterRow}>
                {([
                  ['all', 'All Designs'],
                  ['recent', 'Recent'],
                  ['favorites', 'Favorites'],
                  ['unfiled', 'Unfiled'],
                ] as const).map(([id, label]) => (
                  <Pressable
                    key={id}
                    accessibilityRole="button"
                    accessibilityState={{ selected: selectedFilter === id }}
                    disabled={id === 'unfiled' && familyCollectionIds === null}
                    onPress={() => setSelectedFilter(id)}
                    style={[styles.filterChip, selectedFilter === id && styles.filterChipSelected]}>
                    <Text style={selectedFilter === id ? styles.filterChipTextSelected : styles.filterChipText}>
                      {label}
                    </Text>
                  </Pressable>
                ))}
                {collections.map((collection) => (
                  <Pressable
                    key={collection.id}
                    accessibilityRole="button"
                    accessibilityState={{ selected: selectedFilter === collection.id }}
                    disabled={familyCollectionIds === null}
                    onPress={() => {
                      setSelectedFilter(collection.id);
                      setDeleteConfirmationId(null);
                    }}
                    style={[styles.filterChip, selectedFilter === collection.id && styles.filterChipSelected]}>
                    <Text style={selectedFilter === collection.id ? styles.filterChipTextSelected : styles.filterChipText}>
                      {collection.name} · {collection.family_count}
                    </Text>
                  </Pressable>
                ))}
              </ScrollView>
              {allTags.length > 0 && (
                <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.tagRow}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityState={{ selected: selectedTag === null }}
                    onPress={() => setSelectedTag(null)}
                    style={[styles.tagChip, selectedTag === null && styles.tagChipSelected]}>
                    <Text style={styles.tagText}>All tags</Text>
                  </Pressable>
                  {allTags.map((tag) => (
                    <Pressable
                      key={tag}
                      accessibilityRole="button"
                      accessibilityState={{ selected: selectedTag === tag }}
                      onPress={() => setSelectedTag(tag)}
                      style={[styles.tagChip, selectedTag === tag && styles.tagChipSelected]}>
                      <Text style={styles.tagText}>#{tag}</Text>
                    </Pressable>
                  ))}
                </ScrollView>
              )}
              <View style={styles.collectionActionsRow}>
                <Button
                  title={showCreateCollection ? 'Cancel new Collection' : 'New Collection'}
                  kind="ghost"
                  onPress={() => setShowCreateCollection((showing) => !showing)}
                />
              </View>
              {showCreateCollection && (
                <View style={styles.collectionEditor}>
                  <Text style={styles.branchTitle}>Create a flat Collection</Text>
                  <Text style={styles.meta}>Choose a starting label. You can use it for any purpose.</Text>
                  <View style={styles.templateRow}>
                    {COLLECTION_TEMPLATES.map((template) => (
                      <Pressable
                        key={template.id}
                        accessibilityRole="button"
                        accessibilityState={{ selected: collectionTemplate === template.id }}
                        onPress={() => {
                          setCollectionTemplate(template.id);
                          if (template.id !== 'client') setCollectionClientName('');
                        }}
                        style={[styles.tagChip, collectionTemplate === template.id && styles.tagChipSelected]}>
                        <Text style={styles.tagText}>{template.label}</Text>
                      </Pressable>
                    ))}
                  </View>
                  <TextInput
                    accessibilityLabel="Collection name"
                    value={collectionName}
                    onChangeText={setCollectionName}
                    placeholder="e.g. Lin engagement ring"
                    placeholderTextColor={theme.faint}
                    style={styles.searchInput}
                  />
                  {collectionTemplate === 'client' && (
                    <TextInput
                      accessibilityLabel="Client name (optional)"
                      value={collectionClientName}
                      onChangeText={setCollectionClientName}
                      placeholder="Client name (optional)"
                      placeholderTextColor={theme.faint}
                      style={styles.searchInput}
                    />
                  )}
                  <View style={styles.collectionActionsRow}>
                    <Button
                      title={collectionMutation === 'create' ? 'Creating…' : 'Create Collection'}
                      disabled={collectionName.trim().length === 0 || collectionMutation !== null}
                      onPress={() => { void createCollection(); }}
                    />
                  </View>
                </View>
              )}
              {collections.map((collection) => collection.id === selectedFilter ? (
                <View key={collection.id} style={styles.collectionSafetyCard}>
                  <Text style={styles.branchTitle}>{collection.name}</Text>
                  {collectionContext(collection) !== null && (
                    <Text style={styles.meta}>{collectionContext(collection)}</Text>
                  )}
                  <Text style={styles.meta}>
                    Archiving or deleting this Collection removes memberships only. Designs and revision history remain.
                  </Text>
                  <View style={styles.collectionActionsRow}>
                    <Button
                      title={collectionMutation === collection.id ? 'Archiving…' : 'Archive Collection'}
                      kind="ghost"
                      disabled={collectionMutation !== null}
                      onPress={() => { void archiveCollection(collection); }}
                    />
                    <Button
                      title={deleteConfirmationId === collection.id
                        ? 'Confirm delete Collection'
                        : 'Delete Collection'}
                      kind="ghost"
                      disabled={collectionMutation !== null}
                      onPress={() => { void deleteCollection(collection); }}
                    />
                  </View>
                </View>
              ) : null)}
            </View>
            {visibleFamilies.length === 0 ? (
              <View style={styles.inlineEmpty}>
                <Text style={styles.emptyTitle}>No matching design families</Text>
                <Text style={styles.emptyCopy}>Try All Designs, clear the search, or choose another tag.</Text>
              </View>
            ) : (
              <View style={styles.variationGrid}>
            {visibleFamilies.map((familyItem) => {
              const representative = mostRecentlyActiveVariation(familyItem.variations);
              const cover = representative?.cover_asset_id ?? null;
              return (
                <View key={familyItem.family_id} style={styles.variationCard}>
                  <Pressable
                    accessibilityLabel={representative === undefined
                      ? `Open ${familyItem.title}`
                      : `Open recently active variation: ${variationName(representative)}`}
                    disabled={representative === undefined}
                    onPress={() => representative !== undefined && openFromFamilyIndex(representative.root_id)}>
                    {cover === null ? <View style={[styles.variationCover, styles.coverPlaceholder]} /> : (
                      <Image source={{ uri: api.assetImageUrl(cover) }} style={styles.variationCover} />
                    )}
                    <Text style={styles.variationTitle}>{familyItem.title}</Text>
                    <Text style={styles.meta}>{familyItem.variations.length} variation{familyItem.variations.length === 1 ? '' : 's'}</Text>
                    {representative !== undefined && (
                      <Text style={styles.meta}>Recently active · {variationName(representative)}</Text>
                    )}
                  </Pressable>
                  {familyItem.tags.length > 0 && (
                    <Text style={styles.familyTags}>
                      {familyItem.tags.map((tag) => `#${tag}`).join('  ')}
                    </Text>
                  )}
                  {tagEditingFamilyId === familyItem.family_id ? (
                    <View style={styles.familyTagEditor}>
                      <TextInput
                        accessibilityLabel={`Tags for ${familyItem.title}`}
                        value={tagDraft}
                        onChangeText={setTagDraft}
                        placeholder="e.g. bridal, sapphire, client review"
                        placeholderTextColor={theme.faint}
                        style={styles.searchInput}
                      />
                      <Text style={styles.meta}>Separate tags with commas. Saving never changes the design.</Text>
                      <View style={styles.collectionActionsRow}>
                        <Button
                          title={tagMutationFamilyId === familyItem.family_id ? 'Saving…' : 'Save tags'}
                          disabled={tagMutationFamilyId !== null}
                          onPress={() => { void saveFamilyTags(familyItem); }}
                        />
                        <Button
                          title="Cancel"
                          kind="ghost"
                          disabled={tagMutationFamilyId !== null}
                          onPress={() => {
                            setTagEditingFamilyId(null);
                            setTagDraft('');
                          }}
                        />
                      </View>
                    </View>
                  ) : (
                    <Button
                      title="Edit tags"
                      kind="ghost"
                      disabled={tagMutationFamilyId !== null}
                      onPress={() => {
                        setTagEditingFamilyId(familyItem.family_id);
                        setTagDraft(familyItem.tags.join(', '));
                      }}
                    />
                  )}
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${familyItem.is_favorite ? 'Remove' : 'Add'} ${familyItem.title} ${familyItem.is_favorite ? 'from' : 'to'} Favorites`}
                    accessibilityState={{
                      selected: familyItem.is_favorite,
                      busy: favoriteMutationFamilyId === familyItem.family_id,
                    }}
                    disabled={favoriteMutationFamilyId !== null}
                    onPress={() => { void toggleFamilyFavorite(familyItem); }}
                    style={[styles.favoriteButton, familyItem.is_favorite && styles.favoriteButtonSelected]}>
                    <Text style={styles.favoriteButtonText}>
                      {favoriteMutationFamilyId === familyItem.family_id
                        ? 'Saving…'
                        : familyItem.is_favorite ? '★ Favorited' : '☆ Favorite'}
                    </Text>
                  </Pressable>
                </View>
              );
            })}
              </View>
            )}
          </>
        )}
      </ScrollView>
    );
  }

  if (loading) {
    return (
      <View style={styles.loadingState}>
        <ActivityIndicator color={theme.accent} />
        <Text style={styles.meta}>Loading this design family and saved history…</Text>
      </View>
    );
  }

  if (data === null) {
    return (
      <ScrollView contentContainerStyle={styles.workspace}>
        <View style={styles.backRow}>
          <Button title="All families" kind="ghost" onPress={showAllFamilies} />
        </View>
        {error !== null && <Notice kind="error" text={error} />}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Saved history is unavailable</Text>
          <Text style={styles.sectionCopy}>
            Facetta will not guess at missing history. The selected design remains unchanged.
          </Text>
          <Button title="Retry" onPress={loadWorkspace} />
        </View>
        <View style={styles.section}>
          <Text style={styles.branchTitle}>Explore from the selected active revision</Text>
          <Text style={styles.meta}>
            Open Vary to name a sibling from this exact saved revision. Collections stays focused
            on browsing, comparing, and restoring history.
          </Text>
          <Button
            title="Vary this revision"
            disabled={project.active_asset_id === null}
            onPress={onVaryCurrent}
          />
        </View>
      </ScrollView>
    );
  }

  const family = data.family;
  const currentVariation = family?.variations.find((variation) => (
    variation.root_id === project.root_id
  )) ?? null;
  const familyCoverAssetId = currentVariation?.cover_asset_id
    ?? project.cover_asset_id
    ?? family?.variations.find((variation) => variation.cover_asset_id !== null)?.cover_asset_id
    ?? null;
  const activeAssetId = data.history.active_asset_id;
  const savedOutputs = [...project.derived_assets]
    .filter((asset) => asset.image_url !== null && SAVED_OUTPUT_CAPABILITIES.has(asset.capability))
    .sort((left, right) => (right.created_at ?? '').localeCompare(left.created_at ?? ''));
  const clientName = linkedClientName(data.history.family_id, collections, familyCollectionIds);

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
      <View style={styles.backRow}>
        <Button title="All families" kind="ghost" onPress={showAllFamilies} />
      </View>
      {error !== null && <Notice kind="error" text={error} />}

      <View style={styles.familyHero}>
        <View style={styles.familyHeader}>
          <View style={styles.familyHeadingCopy}>
            <Text style={styles.eyebrow}>Design family</Text>
            <Text numberOfLines={2} style={styles.familyTitle}>{family?.title ?? project.title}</Text>
            <Text style={styles.meta}>
              {family === null
                ? 'First saved direction · every revision preserved'
                : `${family.variations.length} variation${family.variations.length === 1 ? '' : 's'} · every revision preserved`}
            </Text>
          </View>
        </View>
        {familyCoverAssetId !== null ? (
          <Image
            accessibilityLabel="Design family cover"
            source={{ uri: api.assetImageUrl(familyCoverAssetId) }}
            resizeMode="contain"
            style={styles.familyCover}
          />
        ) : (
          <View style={[styles.familyCover, styles.coverPlaceholder]}>
            <Text style={styles.coverPlaceholderText}>No cover yet</Text>
          </View>
        )}
        {(onContinueRefining !== undefined || project.active_asset_id !== null) && (
          <View style={styles.familyActions}>
            {onContinueRefining !== undefined && (
              <Button
                title="Refine design"
                disabled={project.active_asset_id === null}
                onPress={onContinueRefining}
              />
            )}
            <Button
              title="Create variation"
              kind="ghost"
              disabled={project.active_asset_id === null}
              onPress={onVaryCurrent}
            />
          </View>
        )}
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Organize this family</Text>
        <Text style={styles.sectionCopy}>
          Add this entire Design Family to any number of Collections. Variations and revisions are never moved or copied.
        </Text>
        {organizationError !== null && <Notice kind="error" text={organizationError} />}
        {collectionNotice !== null && <Notice kind="ok" text={collectionNotice} />}
        {data.history.family_id === null ? (
          <Text style={styles.meta}>This older design will become organizable after its family migration is available.</Text>
        ) : familyCollectionIds === null ? (
          <Text style={styles.meta}>Collection memberships are unavailable right now.</Text>
        ) : collections.length === 0 ? (
          <Text style={styles.meta}>Unfiled · Create a Collection from All Designs when you are ready.</Text>
        ) : (
          <View style={styles.membershipGrid}>
            {collections.map((collection) => {
              const member = familyCollectionIds[data.history.family_id!]?.includes(collection.id) === true;
              return (
                <Pressable
                  key={collection.id}
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: member }}
                  accessibilityLabel={`${member ? 'Remove from' : 'Add to'} ${collection.name}`}
                  disabled={collectionMutation !== null}
                  onPress={() => {
                    void toggleFamilyCollection(data.history.family_id!, collection);
                  }}
                  style={[styles.membershipCard, member && styles.membershipCardSelected]}>
                  <Text style={styles.variationTitle}>{collection.name}</Text>
                  {collectionContext(collection) !== null && (
                    <Text style={styles.meta}>{collectionContext(collection)}</Text>
                  )}
                  <Text style={styles.meta}>{member ? 'Included · tap to remove' : 'Tap to add'}</Text>
                </Pressable>
              );
            })}
          </View>
        )}
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Variations</Text>
        <Text style={styles.sectionCopy}>
          Independent directions share a family, but each keeps its own revision history.
        </Text>
        {family === null ? (
          <View style={styles.inlineEmpty}>
            <Text style={styles.meta}>No sibling variations yet.</Text>
          </View>
        ) : (
          <View style={styles.variationGrid}>
            {family.variations.map((variation) => {
              const selected = variation.root_id === project.root_id;
              return (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`Open ${variationName(variation)}`}
                  disabled={selected}
                  key={variation.root_id}
                  onPress={() => onOpenProject(variation.root_id)}
                  style={[styles.variationCard, selected && styles.variationCurrent]}>
                  {variation.cover_asset_id !== null ? (
                    <Image
                      source={{ uri: api.assetImageUrl(variation.cover_asset_id) }}
                      resizeMode="cover"
                      style={styles.variationCover}
                    />
                  ) : (
                    <View style={[styles.variationCover, styles.coverPlaceholder]} />
                  )}
                  <Text style={styles.variationTitle}>
                    {variationDisplayName(variation)}{selected ? ' · Current' : ''}
                  </Text>
                  <Text style={styles.meta}>
                    {variation.primary_revision_count} revision{variation.primary_revision_count === 1 ? '' : 's'}
                  </Text>
                  <Text style={styles.lineage}>
                    {variationLineage(variation, family)}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        )}

        <View style={styles.branchCard}>
          <Text style={styles.branchTitle}>Explore without changing this direction</Text>
          <Text style={styles.meta}>
            Vary starts from the current Revision {data.history.revisions.find((revision) => (
              revision.asset_id === activeAssetId
            ))?.revision ?? data.history.revisions.length} in Studio, where you can name the new
            sibling before creating it.
          </Text>
          <Button
            title="Vary this revision"
            disabled={project.active_asset_id === null}
            onPress={onVaryCurrent}
          />
        </View>
      </View>

      {destinationContext !== undefined && onSelectDestination !== undefined && (
        <View style={styles.destinationCard}>
          <StudioDestinationChooser
            context={destinationContext}
            title="Create images from this revision"
            description={destinationContext.hasExactSpecification
              ? 'Prepare this exact saved revision for client review, a campaign, or optional eligible Factory review. Its design history will not change.'
              : 'Prepare this saved visual direction for client review or a campaign. Its design history will not change.'}
            excludeDestinations={COLLECTIONS_DESTINATION_EXCLUSIONS}
            destinationCopy={{
              client: {
                label: clientName === null ? 'Client review' : `For ${clientName}`,
                description: 'Create one polished image to share for approval.',
              },
              marketing: {
                label: 'Campaign image set',
                description: 'Create a coordinated image set for ecommerce and campaigns.',
              },
            }}
            onSelect={onSelectDestination}
          />
        </View>
      )}

      <View style={styles.section}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`${showPresentationImages ? 'Hide' : 'Show'} ready-to-share images (${savedOutputs.length})`}
          accessibilityState={{ expanded: showPresentationImages }}
          onPress={() => setShowPresentationImages((visible) => !visible)}
          style={styles.disclosureRow}>
          <View style={styles.disclosureCopy}>
            <Text style={styles.sectionTitle}>Ready-to-share images</Text>
            <Text style={styles.meta}>
              {savedOutputs.length === 0
                ? 'None yet · create one from the options above'
                : `${savedOutputs.length} saved image${savedOutputs.length === 1 ? '' : 's'}`}
            </Text>
          </View>
          <Text style={styles.disclosureMark}>{showPresentationImages ? '−' : '+'}</Text>
        </Pressable>
        {showPresentationImages && (
          <>
            <Text style={styles.sectionCopy}>
              Polished client-review, campaign, and technical images saved from this exact
              revision. They never replace design history.
            </Text>
            {savedOutputs.length === 0 ? (
              <View style={styles.inlineEmpty}>
                <Text style={styles.meta}>No ready-to-share images have been saved for this variation.</Text>
              </View>
            ) : (
              <View style={styles.outputGrid}>
                {savedOutputs.map((output) => (
                  <View key={output.asset_id} style={styles.outputCard}>
                    <Image
                      accessibilityLabel={savedOutputLabel(output.capability)}
                      source={{ uri: api.assetImageUrl(output.asset_id) }}
                      resizeMode="cover"
                      style={styles.outputImage}
                    />
                    <Text style={styles.variationTitle}>{savedOutputLabel(output.capability)}</Text>
                    <Text style={styles.lineage}>
                      {savedOutputLineage(output, project, data.history.revisions)}
                    </Text>
                    {output.created_at !== null && <Text style={styles.meta}>{dateLabel(output.created_at)}</Text>}
                    {deliverProtectedFile !== undefined && (
                      <Button
                        title={exportingAssetId === output.asset_id
                          ? `Exporting ${savedOutputLabel(output.capability).toLowerCase()}…`
                          : `Export ${savedOutputLabel(output.capability).toLowerCase()}`}
                        kind="ghost"
                        disabled={exportingAssetId !== null}
                        onPress={() => { void exportSavedOutput(output); }}
                      />
                    )}
                  </View>
                ))}
              </View>
            )}
            {exportError !== null && <Notice kind="error" text={exportError} />}
          </>
        )}
      </View>

      <View style={styles.section}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`${showRevisionHistory ? 'Hide' : 'Show'} revision history (${data.history.revisions.length})`}
          accessibilityState={{ expanded: showRevisionHistory }}
          onPress={() => {
            if (showRevisionHistory) setCompareAssetIds([]);
            setShowRevisionHistory(!showRevisionHistory);
          }}
          style={styles.disclosureRow}>
          <View style={styles.disclosureCopy}>
            <Text style={styles.sectionTitle}>Revision history</Text>
            <Text style={styles.meta}>
              {data.history.revisions.length} immutable revision{data.history.revisions.length === 1 ? '' : 's'}
            </Text>
          </View>
          <Text style={styles.disclosureMark}>{showRevisionHistory ? '−' : '+'}</Text>
        </Pressable>
        {showRevisionHistory && (
          <>
            <Text style={styles.sectionCopy}>
              Compare two revisions. Restoring copies an earlier revision forward as a new one; nothing is overwritten.
            </Text>
            {compared.length === 2 && (
              <View style={styles.compareArea}>
                <Text style={styles.sectionTitle}>
                  Comparing revision {compared[0].revision} and revision {compared[1].revision}
                </Text>
                <StudioComparisonInspector
                  before={{
                    accessibilityLabel: `Revision ${compared[0].revision} comparison`,
                    label: `Revision ${compared[0].revision}`,
                    source: { uri: compared[0].image_url },
                  }}
                  after={{
                    accessibilityLabel: `Revision ${compared[1].revision} comparison`,
                    label: `Revision ${compared[1].revision}`,
                    source: { uri: compared[1].image_url },
                  }}
                  compactHeight={340}
                  inspectionTitle={`Compare Revision ${compared[0].revision} with Revision ${compared[1].revision}`}
                  testID="selected-revision-comparison"
                />
                <View style={styles.compareMetadataGrid}>
                  {compared.map((revision) => (
                    <View key={revision.asset_id} style={styles.compareCard}>
                      <Text style={styles.variationTitle}>Revision {revision.revision}</Text>
                      <Text style={styles.meta}>{dateLabel(revision.created_at)}</Text>
                      <Text style={styles.sectionCopy}>{revision.change_summary}</Text>
                      <Text style={styles.lineage}>{revisionLineage(revision, data.history.revisions)}</Text>
                    </View>
                  ))}
                </View>
              </View>
            )}
            {data.history.revisions.length === 0 ? (
              <View style={styles.inlineEmpty}>
                <Text style={styles.meta}>No saved visual revisions are recorded for this design yet.</Text>
              </View>
            ) : data.history.revisions.map((revision) => {
              const active = revision.asset_id === activeAssetId;
              const comparing = compareAssetIds.includes(revision.asset_id);
              return (
                <View key={revision.asset_id} style={styles.revisionRow}>
                  <Image source={{ uri: revision.image_url }} resizeMode="cover" style={styles.revisionThumb} />
                  <View style={styles.revisionCopy}>
                    <Text style={styles.variationTitle}>
                      Revision {revision.revision}{active ? ' · Active' : ''}
                    </Text>
                    <Text style={styles.meta}>{dateLabel(revision.created_at)}</Text>
                    <Text style={styles.sectionCopy}>{revision.change_summary}</Text>
                    <Text style={styles.lineage}>{revisionLineage(revision, data.history.revisions)}</Text>
                  </View>
                  <View style={styles.revisionActions}>
                    <Pressable
                      accessibilityRole="checkbox"
                      accessibilityState={{ checked: comparing }}
                      accessibilityLabel={`Compare revision ${revision.revision}`}
                      onPress={() => toggleComparison(revision.asset_id)}
                      style={[styles.compareButton, comparing && styles.compareButtonSelected]}>
                      <Text style={comparing ? styles.compareTextSelected : styles.compareText}>
                        {comparing ? 'Selected' : 'Compare'}
                      </Text>
                    </Pressable>
                    {!active && (
                      <Button
                        title={restoringAssetId === revision.asset_id
                          ? 'Restoring…'
                          : `Restore revision ${revision.revision} as new`}
                        kind="ghost"
                        disabled={restoringAssetId !== null || project.active_asset_id === null}
                        onPress={() => { void restoreRevision(revision); }}
                      />
                    )}
                  </View>
                </View>
              );
            })}
          </>
        )}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  workspace: { padding: 16, paddingBottom: 40, backgroundColor: theme.paper },
  backRow: { alignItems: 'flex-start', marginBottom: 10 },
  loadingState: {
    minHeight: 240, alignItems: 'center', justifyContent: 'center', gap: 10,
    backgroundColor: theme.paper,
  },
  emptyState: {
    minHeight: 240, alignItems: 'center', justifyContent: 'center', padding: 24,
    backgroundColor: theme.paper,
  },
  emptyTitle: { color: theme.ink, fontFamily: theme.serif, fontSize: 22, marginBottom: 8 },
  emptyCopy: { color: theme.faint, fontSize: 13, lineHeight: 19, textAlign: 'center', maxWidth: 420 },
  emptyAction: { marginTop: 16 },
  familyHero: {
    borderWidth: 1, borderColor: theme.line, borderRadius: 20, overflow: 'hidden',
    backgroundColor: theme.card, marginBottom: 14,
  },
  familyHeader: { paddingHorizontal: 16, paddingTop: 14, paddingBottom: 10 },
  familyHeadingCopy: { maxWidth: 680 },
  familyCover: { width: '100%', height: 340, backgroundColor: theme.paper },
  familyActions: {
    flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8,
    borderTopWidth: 1, borderTopColor: theme.line, padding: 12,
  },
  destinationCard: {
    borderWidth: 1, borderColor: theme.line, borderRadius: 16, padding: 14,
    backgroundColor: theme.card, marginBottom: 14, gap: 14,
  },
  destinationCopy: { maxWidth: 520 },
  destinationActions: { alignItems: 'flex-start', gap: 8 },
  eyebrow: {
    color: theme.accent, fontSize: 10, fontWeight: '700', letterSpacing: 1.2,
    textTransform: 'uppercase', marginBottom: 5,
  },
  familyTitle: { color: theme.ink, fontFamily: theme.serif, fontSize: 19, lineHeight: 24, marginBottom: 4 },
  meta: { color: theme.faint, fontSize: 12, lineHeight: 17 },
  section: {
    borderWidth: 1, borderColor: theme.line, borderRadius: 16, padding: 14,
    backgroundColor: theme.card, marginBottom: 14,
  },
  sectionTitle: { color: theme.ink, fontFamily: theme.serif, fontSize: 17, marginBottom: 4 },
  sectionCopy: { color: theme.faint, fontSize: 12, lineHeight: 17 },
  organizationPanel: {
    borderWidth: 1, borderColor: theme.line, borderRadius: 16, padding: 12,
    backgroundColor: theme.card, marginTop: 14, marginBottom: 4, gap: 10,
  },
  searchInput: {
    borderWidth: 1, borderColor: theme.line, borderRadius: 10,
    paddingHorizontal: 12, paddingVertical: 9, color: theme.ink,
    backgroundColor: theme.paper, fontSize: 14,
  },
  filterRow: { gap: 8, paddingRight: 8 },
  filterChip: {
    borderWidth: 1, borderColor: theme.line, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 8, backgroundColor: theme.paper,
  },
  filterChipSelected: { borderColor: theme.ink, backgroundColor: theme.ink },
  filterChipText: { color: theme.ink, fontSize: 12 },
  filterChipTextSelected: { color: theme.paper, fontSize: 12 },
  tagRow: { gap: 6, paddingRight: 8 },
  tagChip: {
    borderWidth: 1, borderColor: theme.line, borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 6, backgroundColor: theme.paper,
  },
  tagChipSelected: { borderColor: theme.accent, backgroundColor: theme.blush },
  tagText: { color: theme.ink, fontSize: 11 },
  familyTags: { color: theme.accent, fontSize: 11, lineHeight: 16, marginTop: 7 },
  familyTagEditor: { borderTopWidth: 1, borderTopColor: theme.line, marginTop: 8, paddingTop: 8, gap: 6 },
  templateRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginVertical: 8 },
  collectionEditor: {
    borderTopWidth: 1, borderTopColor: theme.line, paddingTop: 12, gap: 8,
  },
  collectionSafetyCard: {
    borderTopWidth: 1, borderTopColor: theme.line, paddingTop: 12,
  },
  collectionActionsRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center' },
  membershipGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 12 },
  membershipCard: {
    minWidth: 150, flexGrow: 1, borderWidth: 1, borderColor: theme.line,
    borderRadius: 10, padding: 10, backgroundColor: theme.paper,
  },
  membershipCardSelected: { borderColor: theme.accent, backgroundColor: theme.blush },
  disclosureRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12,
  },
  disclosureCopy: { flex: 1 },
  disclosureMark: { color: theme.ink, fontSize: 22, lineHeight: 24 },
  inlineEmpty: { borderTopWidth: 1, borderTopColor: theme.line, marginTop: 12, paddingTop: 12 },
  variationGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 12 },
  variationCard: {
    width: 190, borderWidth: 1, borderColor: theme.line, borderRadius: 12,
    padding: 8, backgroundColor: theme.paper,
  },
  favoriteButton: {
    alignSelf: 'flex-start', borderWidth: 1, borderColor: theme.line, borderRadius: 999,
    paddingHorizontal: 9, paddingVertical: 6, marginTop: 8, backgroundColor: theme.card,
  },
  favoriteButtonSelected: { borderColor: theme.accent, backgroundColor: theme.blush },
  favoriteButtonText: { color: theme.ink, fontSize: 11, fontWeight: '700' },
  variationCurrent: { borderColor: theme.accent, backgroundColor: theme.blush },
  variationCover: { width: '100%', height: 112, borderRadius: 8, marginBottom: 8 },
  coverPlaceholder: { alignItems: 'center', justifyContent: 'center' },
  coverPlaceholderText: { color: theme.faint, fontSize: 12 },
  variationTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  lineage: { color: theme.faint, fontSize: 10, lineHeight: 14, marginTop: 3 },
  branchCard: {
    borderTopWidth: 1, borderTopColor: theme.line, marginTop: 14, paddingTop: 14,
  },
  branchTitle: { color: theme.ink, fontSize: 13, fontWeight: '700', marginBottom: 4 },
  compareArea: { borderTopWidth: 1, borderTopColor: theme.line, marginTop: 12, paddingTop: 12 },
  compareMetadataGrid: { flexDirection: 'row', gap: 10, marginTop: 10 },
  compareCard: { flex: 1, minWidth: 0 },
  revisionRow: {
    borderTopWidth: 1, borderTopColor: theme.line, paddingTop: 12, marginTop: 12,
    flexDirection: 'row', flexWrap: 'wrap', gap: 10, alignItems: 'center',
  },
  revisionThumb: { width: 82, height: 82, borderRadius: 8, backgroundColor: theme.paper },
  revisionCopy: { flex: 1, minWidth: 190 },
  revisionActions: { alignItems: 'flex-end', minWidth: 130 },
  compareButton: {
    borderWidth: 1, borderColor: theme.line, borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 6, marginBottom: 8,
  },
  compareButtonSelected: { backgroundColor: theme.ink, borderColor: theme.ink },
  compareText: { color: theme.ink, fontSize: 11 },
  compareTextSelected: { color: theme.paper, fontSize: 11 },
  outputGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 12 },
  outputCard: {
    width: 190, borderWidth: 1, borderColor: theme.line, borderRadius: 12,
    padding: 8, backgroundColor: theme.paper,
  },
  outputImage: { width: '100%', height: 150, borderRadius: 8, marginBottom: 8, backgroundColor: theme.blush },
});
