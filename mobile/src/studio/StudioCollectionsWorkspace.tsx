import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { Button, Field, Notice } from '../components';
import { theme } from '../theme';
import type { TrustedApiClient } from '../trusted/client';
import type {
  DesignFamilyDetail,
  DesignFamilyVariation,
  ProjectDetail,
  StudioHistoryRevision,
  StudioProjectHistory,
} from '../trusted/types';

/**
 * The backend currently resolves a family only from a selected Project. It
 * does not expose an all-family listing route, so this workspace deliberately
 * accepts an exact selected Project instead of fabricating a collection index.
 */
export type StudioCollectionsApi = Pick<TrustedApiClient,
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
}

interface WorkspaceData {
  history: StudioProjectHistory;
  family: DesignFamilyDetail | null;
}

function variationName(variation: DesignFamilyVariation): string {
  return variation.variation_label?.trim()
    || `Variation ${variation.variation_index}`;
}

function revisionLineage(revision: StudioHistoryRevision): string {
  const parent = revision.parent_asset_id === null
    ? 'original source'
    : `parent ${revision.parent_asset_id}`;
  const spec = revision.design_version === null
    ? 'legacy spec provenance'
    : `spec ${revision.design_version}`;
  return `${revision.asset_id} · ${spec} · ${parent}`;
}

export function StudioCollectionsWorkspace({
  api,
  project,
  createdBy,
  onOpenProject,
  onProjectChanged,
  onVariationCreated,
}: StudioCollectionsWorkspaceProps) {
  const [data, setData] = useState<WorkspaceData | null>(null);
  const [loading, setLoading] = useState(project !== null);
  const [error, setError] = useState<string | null>(null);
  const [compareAssetIds, setCompareAssetIds] = useState<string[]>([]);
  const [variationLabel, setVariationLabel] = useState('');
  const [branching, setBranching] = useState(false);
  const [restoringAssetId, setRestoringAssetId] = useState<string | null>(null);
  const [families, setFamilies] = useState<DesignFamilyDetail[] | null>(null);

  useEffect(() => {
    let current = true;
    setData(null);
    setError(null);
    setCompareAssetIds([]);
    setVariationLabel('');
    if (project === null) {
      setLoading(true);
      void api.listDesignFamilies(createdBy).then((result) => {
        if (!current) return;
        setLoading(false);
        if (result.error !== null) {
          setError(result.error.message);
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
        setError(historyResult.error.message);
        setLoading(false);
        return;
      }
      if (historyResult.data.project_id !== project.root_id
        || historyResult.data.active_asset_id !== project.active_asset_id) {
        setError('The saved history no longer matches the selected active revision. Reopen the design.');
        setLoading(false);
        return;
      }
      let family: DesignFamilyDetail | null = null;
      if (historyResult.data.family_id !== null) {
        const familyResult = await api.getDesignFamily(historyResult.data.family_id);
        if (!current) return;
        if (familyResult.error !== null) {
          setError(familyResult.error.message);
          setLoading(false);
          return;
        }
        if (familyResult.data.family_id !== historyResult.data.family_id
          || !familyResult.data.variations.some((variation) => (
            variation.root_id === project.root_id
          ))) {
          setError('The design family response did not preserve the selected project lineage.');
          setLoading(false);
          return;
        }
        family = familyResult.data;
      }
      setData({ history: historyResult.data, family });
      setLoading(false);
    });
    return () => { current = false; };
  }, [api, createdBy, project?.root_id]);

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
      setError(result.error.message);
      return;
    }
    if (result.data.source_project_id !== project.root_id
      || result.data.source_asset_id !== project.active_asset_id) {
      setError('The new variation did not preserve the selected active revision lineage.');
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
      setError(result.error.message);
      return;
    }
    if (result.data.restored_from_asset_id !== revision.asset_id
      || result.data.project.active_asset_id !== result.data.new_asset_id) {
      setError('The restored revision response did not preserve its exact source lineage.');
      return;
    }
    onProjectChanged(result.data.project);
  };

  if (project === null) {
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
        <Text style={styles.eyebrow}>COLLECTIONS</Text>
        <Text style={styles.familyTitle}>Your design families</Text>
        <Text style={styles.sectionCopy}>Choose a direction to open its variations and immutable revision history.</Text>
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
                  onPress={() => representative !== undefined && onOpenProject(representative.root_id)}
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
        <Text style={styles.meta}>Loading this design family and exact history…</Text>
      </View>
    );
  }

  if (data === null) {
    return (
      <ScrollView contentContainerStyle={styles.workspace}>
        {error !== null && <Notice kind="error" text={error} />}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Saved history is unavailable</Text>
          <Text style={styles.sectionCopy}>
            No family or revision data is being inferred. The selected design remains unchanged.
          </Text>
        </View>
        <View style={styles.section}>
          <Text style={styles.branchTitle}>Explore from the selected active revision</Text>
          <Text style={styles.meta}>
            A new variation can still start from asset {project.active_asset_id ?? 'unavailable'}
            {project.active_design_version === null
              ? ' · legacy specification provenance'
              : ` · spec ${project.active_design_version}`}.
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

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
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
          Independent directions share a family, but each keeps its own exact revision chain.
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
                    {variationName(variation)}{selected ? ' · Current' : ''}
                  </Text>
                  <Text style={styles.meta}>
                    {variation.primary_revision_count} revision{variation.primary_revision_count === 1 ? '' : 's'}
                  </Text>
                  <Text style={styles.lineage}>
                    {variation.branched_from_asset_id === null
                      ? `Root project ${variation.root_id}`
                      : `From ${variation.branched_from_project_root_id} · asset ${variation.branched_from_asset_id}`}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        )}

        <View style={styles.branchCard}>
          <Text style={styles.branchTitle}>Explore without changing this direction</Text>
          <Text style={styles.meta}>
            The new variation begins from active asset {project.active_asset_id ?? 'unavailable'}
            {project.active_design_version === null
              ? ' · legacy specification provenance'
              : ` · spec ${project.active_design_version}`}.
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
                <Text style={styles.sectionCopy}>{revision.change_summary}</Text>
                <Text style={styles.lineage}>{revisionLineage(revision)}</Text>
              </View>
            ))}
          </View>
        </View>
      )}

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Immutable revision history</Text>
        <Text style={styles.sectionCopy}>
          Compare two revisions. Restoring copies an earlier revision forward as a new one; nothing is overwritten.
        </Text>
        {data.history.revisions.length === 0 ? (
          <View style={styles.inlineEmpty}>
            <Text style={styles.meta}>No immutable visual revisions are recorded for this design yet.</Text>
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
                <Text style={styles.sectionCopy}>{revision.change_summary}</Text>
                <Text style={styles.lineage}>{revisionLineage(revision)}</Text>
                {revision.restored_from_asset_id !== null && (
                  <Text style={styles.lineage}>
                    Restored from exact asset {revision.restored_from_asset_id}
                  </Text>
                )}
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
});
