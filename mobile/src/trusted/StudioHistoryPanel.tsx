import React, { useEffect, useState } from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Notice } from '../components';
import { theme } from '../theme';
import type { TrustedApiClient } from './client';
import type {
  DesignFamilyDetail,
  ProjectDetail,
  StudioHistoryRevision,
  StudioProjectHistory,
} from './types';

export interface StudioHistoryPanelProps {
  client: TrustedApiClient;
  project: ProjectDetail;
  createdBy: string;
  onOpenProject: (projectId: string) => void;
  onProjectChanged: (project: ProjectDetail) => void;
}

export function StudioHistoryPanel({
  client,
  project,
  createdBy,
  onOpenProject,
  onProjectChanged,
}: StudioHistoryPanelProps) {
  const [history, setHistory] = useState<StudioProjectHistory | null>(null);
  const [family, setFamily] = useState<DesignFamilyDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [restoreBusy, setRestoreBusy] = useState<string | null>(null);
  const [compareIds, setCompareIds] = useState<string[]>([]);

  const load = async (active = { current: true }): Promise<void> => {
    setLoading(true);
    setError(null);
    const response = await client.getStudioProjectHistory(project.root_id);
    if (!active.current) return;
    if (response.error !== null) {
      setError(response.error.message);
      setLoading(false);
      return;
    }
    setHistory(response.data);
    if (response.data.family_id !== null) {
      const familyResponse = await client.getDesignFamily(response.data.family_id);
      if (!active.current) return;
      if (familyResponse.error !== null) setError(familyResponse.error.message);
      else setFamily(familyResponse.data);
    } else {
      setFamily(null);
    }
    setLoading(false);
  };

  useEffect(() => {
    const active = { current: true };
    setHistory(null);
    setFamily(null);
    setCompareIds([]);
    void load(active);
    return () => { active.current = false; };
  }, [client, project.root_id]);

  const toggleCompare = (assetId: string): void => {
    setCompareIds((current) => {
      if (current.includes(assetId)) return current.filter((id) => id !== assetId);
      return [...current.slice(-1), assetId];
    });
  };

  const restore = async (revision: StudioHistoryRevision): Promise<void> => {
    if (project.active_asset_id === null || restoreBusy !== null) return;
    setRestoreBusy(revision.asset_id);
    setError(null);
    const response = await client.restoreStudioRevision(
      project.root_id,
      revision.asset_id,
      {
        created_by: createdBy,
        expected_active_asset_id: project.active_asset_id,
        expected_design_version: project.active_design_version,
      },
    );
    setRestoreBusy(null);
    if (response.error !== null) {
      setError(response.error.message);
      return;
    }
    onProjectChanged(response.data.project);
  };

  const compared = (history?.revisions ?? []).filter((revision) => (
    compareIds.includes(revision.asset_id)
  ));

  if (loading) return <Text style={styles.meta}>Loading immutable history…</Text>;
  return (
    <View style={styles.wrap}>
      {error !== null && <Notice kind="error" text={error} />}
      {family !== null && (
        <View style={styles.group}>
          <Text style={styles.groupTitle}>Variations</Text>
          <Text style={styles.meta}>Independent directions in the same design family</Text>
          <View style={styles.variationGrid}>
            {family.variations.map((variation) => {
              const current = variation.root_id === project.root_id;
              return (
                <Pressable
                  key={variation.root_id}
                  accessibilityRole="button"
                  disabled={current}
                  onPress={() => onOpenProject(variation.root_id)}
                  style={[styles.variationCard, current && styles.currentVariation]}>
                  {variation.cover_asset_id !== null && (
                    <Image
                      source={{ uri: client.assetImageUrl(variation.cover_asset_id) }}
                      style={styles.variationImage}
                      resizeMode="contain"
                    />
                  )}
                  <Text style={styles.variationTitle}>
                    {variation.variation_label ?? `Variation ${variation.variation_index}`}
                  </Text>
                  <Text style={styles.meta}>
                    {variation.primary_revision_count} revision{variation.primary_revision_count === 1 ? '' : 's'}
                    {current ? ' · Current' : ''}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      )}

      {compared.length === 2 && (
        <View style={styles.group}>
          <Text style={styles.groupTitle}>Compare exact revisions</Text>
          <View style={styles.compareGrid}>
            {compared.map((revision) => (
              <View key={revision.asset_id} style={styles.compareCard}>
                <Image source={{ uri: revision.image_url }} style={styles.compareImage} resizeMode="contain" />
                <Text style={styles.variationTitle}>Revision {revision.revision}</Text>
                <Text style={styles.meta}>{revision.change_summary}</Text>
              </View>
            ))}
          </View>
        </View>
      )}

      <View style={styles.group}>
        <Text style={styles.groupTitle}>Revision record</Text>
        <Text style={styles.meta}>Select two to compare. Restore always appends a new revision.</Text>
        {history?.revisions.map((revision) => {
          const active = revision.asset_id === history.active_asset_id;
          const selected = compareIds.includes(revision.asset_id);
          return (
            <View key={revision.asset_id} style={styles.revisionRow}>
              <Pressable
                accessibilityRole="checkbox"
                accessibilityState={{ checked: selected }}
                onPress={() => toggleCompare(revision.asset_id)}
                style={[styles.compareToggle, selected && styles.compareToggleSelected]}>
                <Text style={selected ? styles.compareTextSelected : styles.compareText}>
                  {selected ? '✓ Compare' : 'Compare'}
                </Text>
              </Pressable>
              <View style={styles.revisionCopy}>
                <Text style={styles.variationTitle}>
                  Revision {revision.revision}{active ? ' · Active' : ''}
                </Text>
                <Text style={styles.summary}>{revision.change_summary}</Text>
                <Text style={styles.meta}>
                  {revision.action}{revision.design_version === null ? '' : ` · spec ${revision.design_version}`}
                  {revision.restored_from_asset_id === null ? '' : ' · restored from earlier revision'}
                </Text>
              </View>
              {!active && (
                <Button
                  title={restoreBusy === revision.asset_id ? 'Restoring…' : 'Restore as new'}
                  kind="ghost"
                  disabled={restoreBusy !== null || project.active_asset_id === null}
                  onPress={() => { void restore(revision); }}
                />
              )}
            </View>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 12 },
  group: { gap: 8 },
  groupTitle: { color: theme.ink, fontFamily: theme.serif, fontSize: 15 },
  meta: { color: theme.faint, fontSize: 11, lineHeight: 16 },
  variationGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  variationCard: {
    width: 150, borderColor: theme.line, borderWidth: 1, borderRadius: 10,
    padding: 8, backgroundColor: theme.paper,
  },
  currentVariation: { borderColor: theme.accent, backgroundColor: theme.blush },
  variationImage: { width: '100%', height: 84, marginBottom: 6 },
  variationTitle: { color: theme.ink, fontSize: 12, fontWeight: '700' },
  compareGrid: { flexDirection: 'row', gap: 8 },
  compareCard: { flex: 1, borderWidth: 1, borderColor: theme.line, borderRadius: 10, padding: 8 },
  compareImage: { width: '100%', height: 180, backgroundColor: theme.paper, marginBottom: 6 },
  revisionRow: {
    borderTopColor: theme.line, borderTopWidth: 1, paddingTop: 9,
    flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center',
  },
  revisionCopy: { flex: 1, minWidth: 180 },
  summary: { color: theme.ink, fontSize: 12, lineHeight: 17, marginTop: 2 },
  compareToggle: {
    borderWidth: 1, borderColor: theme.line, borderRadius: 999,
    paddingHorizontal: 8, paddingVertical: 5,
  },
  compareToggleSelected: { backgroundColor: theme.ink, borderColor: theme.ink },
  compareText: { color: theme.ink, fontSize: 11 },
  compareTextSelected: { color: theme.paper, fontSize: 11 },
});
