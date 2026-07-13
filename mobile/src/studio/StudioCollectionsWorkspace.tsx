import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { AuthenticatedImage as Image } from '../AuthenticatedImage';

import { Button, Field, Notice } from '../components';
import { theme } from '../theme';
import type {
  AssetSummary,
  DesignFamilyDetail,
  DesignFamilyVariation,
  ProjectDetail,
  StudioHistoryRevision,
  StudioProjectHistory,
} from '../trusted/types';
import { designerErrorMessage } from './designerErrorMessage';
import type { StudioGateway } from './gateway';

export type StudioCollectionsApi = Pick<StudioGateway,
  | 'getDesignFamily'
  | 'listDesignFamilies'
  | 'getStudioProjectHistory'
  | 'restoreStudioRevision'
  | 'saveAsVariation'
  | 'assetImageUrl'
>;

export interface StudioCollectionsWorkspaceProps {
  api: StudioCollectionsApi;
  project: ProjectDetail | null;
  createdBy: string;
  onOpenProject: (projectId: string) => void;
  onProjectChanged: (project: ProjectDetail) => void;
  onVariationCreated: (project: ProjectDetail) => void;
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

function variationName(variation: DesignFamilyVariation): string {
  return variation.variation_label?.trim()
    || `Variation ${variation.variation_index}`;
}

function variationDisplayName(variation: DesignFamilyVariation): string {
  return `Variation ${variation.variation_index} · ${variationName(variation)}`;
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
      return 'Source revision unavailable · lineage not shown';
    }
    sourceId = sourceAsset.parent_asset_id;
  }
  return 'Source revision unavailable · lineage not shown';
}

export function StudioCollectionsWorkspace({
  api,
  project,
  createdBy,
  onOpenProject,
  onProjectChanged,
  onVariationCreated,
  onShowAllFamilies,
  deliverProtectedFile,
}: StudioCollectionsWorkspaceProps) {
  const [data, setData] = useState<WorkspaceData | null>(null);
  const [loading, setLoading] = useState(project !== null);
  const [error, setError] = useState<string | null>(null);
  const [compareAssetIds, setCompareAssetIds] = useState<string[]>([]);
  const [variationLabel, setVariationLabel] = useState('');
  const [branching, setBranching] = useState(false);
  const [restoringAssetId, setRestoringAssetId] = useState<string | null>(null);
  const [families, setFamilies] = useState<DesignFamilyDetail[] | null>(null);
  const [viewingAllFamilies, setViewingAllFamilies] = useState(false);
  const [exportingAssetId, setExportingAssetId] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setData(null);
    setError(null);
    setCompareAssetIds([]);
    setVariationLabel('');
    setExportingAssetId(null);
    setExportError(null);
    if (project === null || viewingAllFamilies) {
      setLoading(true);
      setFamilies(null);
      void api.listDesignFamilies(createdBy).then((result) => {
        if (!current) return;
        setLoading(false);
        if (result.error !== null) {
          setError(designerErrorMessage(result.error, 'collections'));
          setFamilies([]);
          return;
        }
        setFamilies(result.data.families);
      });
      return () => { current = false; };
    }
    setLoading(true);
    void api.getStudioProjectHistory(project.root_id).then(async (historyResult) => {
      if (!current) return;
      if (historyResult.error !== null) {
        setError(designerErrorMessage(historyResult.error, 'collections'));
        setLoading(false);
        return;
      }
      if (historyResult.data.project_id !== project.root_id
        || historyResult.data.active_asset_id !== project.active_asset_id) {
        setError('This design changed while its history was opening. Reopen it to continue.');
        setLoading(false);
        return;
      }
      let family: DesignFamilyDetail | null = null;
      if (historyResult.data.family_id !== null) {
        const familyResult = await api.getDesignFamily(historyResult.data.family_id);
        if (!current) return;
        if (familyResult.error !== null) {
          setError(designerErrorMessage(familyResult.error, 'collections'));
          setLoading(false);
          return;
        }
        if (familyResult.data.family_id !== historyResult.data.family_id
          || !familyResult.data.variations.some((variation) => (
            variation.root_id === project.root_id
          ))) {
          setError('This family no longer contains the selected variation. Return to All families.');
          setLoading(false);
          return;
        }
        family = familyResult.data;
      }
      setData({ history: historyResult.data, family });
      setLoading(false);
    });
    return () => { current = false; };
  }, [api, createdBy, project?.root_id, viewingAllFamilies]);

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

  const createVariation = async (): Promise<void> => {
    const label = variationLabel.trim();
    if (project === null || project.active_asset_id === null || !label || branching) return;
    setBranching(true);
    setError(null);
    const result = await api.saveAsVariation(project.root_id, {
      created_by: createdBy,
      expected_active_asset_id: project.active_asset_id,
      expected_design_version: project.active_design_version,
      label,
    });
    setBranching(false);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'collections'));
      return;
    }
    if (result.data.source_project_id !== project.root_id
      || result.data.source_asset_id !== project.active_asset_id) {
      setError('Facetta could not verify the source revision. No variation was created.');
      return;
    }
    setVariationLabel('');
    onVariationCreated(result.data.project);
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
        <Text style={styles.sectionCopy}>Choose a direction to open its variations and saved revision history.</Text>
        {error !== null && <Notice kind="error" text={error} />}
        {error !== null ? (
          <View style={styles.emptyState}>
            <Text style={styles.emptyTitle}>Collections are temporarily unavailable</Text>
            <Text style={styles.emptyCopy}>Your saved design history is unchanged. Check the connection and try again.</Text>
          </View>
        ) : families?.length === 0 ? (
          <View style={styles.emptyState}>
            <Text style={styles.emptyTitle}>No saved families yet</Text>
            <Text style={styles.emptyCopy}>Create a direction in Studio and it will appear here.</Text>
          </View>
        ) : (
          <View style={styles.variationGrid}>
            {families?.map((familyItem) => {
              const representative = familyItem.variations[0];
              const cover = familyItem.variations.find((item) => item.cover_asset_id !== null)?.cover_asset_id ?? null;
              return (
                <Pressable
                  key={familyItem.family_id}
                  disabled={representative === undefined}
                  onPress={() => representative !== undefined && openFromFamilyIndex(representative.root_id)}
                  style={styles.variationCard}>
                  {cover === null ? <View style={[styles.variationCover, styles.coverPlaceholder]} /> : (
                    <Image source={{ uri: api.assetImageUrl(cover) }} style={styles.variationCover} />
                  )}
                  <Text style={styles.variationTitle}>{familyItem.title}</Text>
                  <Text style={styles.meta}>{familyItem.variations.length} variation{familyItem.variations.length === 1 ? '' : 's'}</Text>
                </Pressable>
              );
            })}
          </View>
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
        </View>
        <View style={styles.section}>
          <Text style={styles.branchTitle}>Explore from the selected active revision</Text>
          <Text style={styles.meta}>
            A new variation can still begin from the current saved revision. Its starting point
            remains attached behind the scenes.
          </Text>
          <Field
            label="Variation name"
            value={variationLabel}
            onChange={setVariationLabel}
            placeholder="Rose gold study"
          />
          <Button
            title={branching ? 'Creating variation…' : 'Create variation'}
            disabled={branching || project.active_asset_id === null || !variationLabel.trim()}
            onPress={() => { void createVariation(); }}
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

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
      <View style={styles.backRow}>
        <Button title="All families" kind="ghost" onPress={showAllFamilies} />
      </View>
      {error !== null && <Notice kind="error" text={error} />}

      <View style={styles.familyHero}>
        {familyCoverAssetId !== null ? (
          <Image
            accessibilityLabel="Design family cover"
            source={{ uri: api.assetImageUrl(familyCoverAssetId) }}
            resizeMode="cover"
            style={styles.familyCover}
          />
        ) : (
          <View style={[styles.familyCover, styles.coverPlaceholder]}>
            <Text style={styles.coverPlaceholderText}>No cover yet</Text>
          </View>
        )}
        <View style={styles.familyCopy}>
          <Text style={styles.eyebrow}>Design family</Text>
          <Text style={styles.familyTitle}>{family?.title ?? project.title}</Text>
          <Text style={styles.meta}>
            {family === null
              ? 'This is the first saved direction. Create a variation to begin its family.'
              : `${family.variations.length} variation${family.variations.length === 1 ? '' : 's'} · every revision preserved`}
          </Text>
        </View>
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
            The new variation begins from the current Revision {data.history.revisions.find((revision) => (
              revision.asset_id === activeAssetId
            ))?.revision ?? data.history.revisions.length}. The starting point remains attached
            behind the scenes.
          </Text>
          <Field
            label="Variation name"
            value={variationLabel}
            onChange={setVariationLabel}
            placeholder="Rose gold study"
          />
          <Button
            title={branching ? 'Creating variation…' : 'Create variation'}
            disabled={branching || project.active_asset_id === null || !variationLabel.trim()}
            onPress={() => { void createVariation(); }}
          />
        </View>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Saved outputs</Text>
        <Text style={styles.sectionCopy}>
          Client, marketing, and view images live beside the exact design revision they came
          from. They never replace design history.
        </Text>
        {savedOutputs.length === 0 ? (
          <View style={styles.inlineEmpty}>
            <Text style={styles.meta}>No presentation or view images have been saved for this variation.</Text>
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
      </View>

      {compared.length === 2 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>
            Comparing revision {compared[0].revision} and revision {compared[1].revision}
          </Text>
          <View style={styles.compareGrid}>
            {compared.map((revision) => (
              <View key={revision.asset_id} style={styles.compareCard}>
                <Image source={{ uri: revision.image_url }} resizeMode="contain" style={styles.compareImage} />
                <Text style={styles.variationTitle}>Revision {revision.revision}</Text>
                <Text style={styles.meta}>{dateLabel(revision.created_at)}</Text>
                <Text style={styles.sectionCopy}>{revision.change_summary}</Text>
                <Text style={styles.lineage}>{revisionLineage(revision, data.history.revisions)}</Text>
              </View>
            ))}
          </View>
        </View>
      )}

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Saved revision history</Text>
        <Text style={styles.sectionCopy}>
          Compare two revisions. Restoring copies an earlier revision forward as a new one; nothing is overwritten.
        </Text>
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
  familyHero: {
    borderWidth: 1, borderColor: theme.line, borderRadius: 20, overflow: 'hidden',
    backgroundColor: theme.card, marginBottom: 14,
  },
  familyCover: { width: '100%', height: 260, backgroundColor: theme.blush },
  familyCopy: { padding: 16 },
  eyebrow: {
    color: theme.accent, fontSize: 10, fontWeight: '700', letterSpacing: 1.2,
    textTransform: 'uppercase', marginBottom: 5,
  },
  familyTitle: { color: theme.ink, fontFamily: theme.serif, fontSize: 24, marginBottom: 5 },
  meta: { color: theme.faint, fontSize: 12, lineHeight: 17 },
  section: {
    borderWidth: 1, borderColor: theme.line, borderRadius: 16, padding: 14,
    backgroundColor: theme.card, marginBottom: 14,
  },
  sectionTitle: { color: theme.ink, fontFamily: theme.serif, fontSize: 17, marginBottom: 4 },
  sectionCopy: { color: theme.faint, fontSize: 12, lineHeight: 17 },
  inlineEmpty: { borderTopWidth: 1, borderTopColor: theme.line, marginTop: 12, paddingTop: 12 },
  variationGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 12 },
  variationCard: {
    width: 190, borderWidth: 1, borderColor: theme.line, borderRadius: 12,
    padding: 8, backgroundColor: theme.paper,
  },
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
  compareGrid: { flexDirection: 'row', gap: 10, marginTop: 10 },
  compareCard: { flex: 1, minWidth: 0 },
  compareImage: { width: '100%', height: 220, backgroundColor: theme.paper, marginBottom: 7 },
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
