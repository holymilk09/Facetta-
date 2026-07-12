import React, { useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';

import { Button, Notice } from '../components';
import { radius, theme } from '../theme';
import type { TrustedApiClient } from '../trusted/client';
import type { FactoryPackManifest } from '../trusted/types';
import { getStudioAction } from './actions';
import { designerErrorMessage } from './designerErrorMessage';
import type { ExactStudioLineage } from './gateway';

const FACTORY_CREDITS = getStudioAction('factory').creditEstimate ?? 0;

export type StudioFactoryApi = Pick<TrustedApiClient,
  'createStudioJob' | 'transitionStudioJob' | 'getFactoryPack'>;

export interface StudioFactoryWorkspaceProps {
  api: StudioFactoryApi;
  lineage: ExactStudioLineage | null;
  createdBy: string;
}

export function StudioFactoryWorkspace({
  api, lineage, createdBy,
}: StudioFactoryWorkspaceProps) {
  const [pack, setPack] = useState<FactoryPackManifest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const prepare = async (): Promise<void> => {
    if (lineage === null || busy || pack !== null) return;
    setBusy(true);
    setError(null);
    const created = await api.createStudioJob({
      owner: createdBy,
      action_id: 'factory',
      lane: 'trusted_structural',
      active_design_id: lineage.projectId,
      source_revision_id: lineage.sourceAssetId,
      requested_outputs: 1,
      credits_per_output: FACTORY_CREDITS,
    });
    if (created.error !== null) {
      setBusy(false);
      setError(designerErrorMessage(created.error, 'factory'));
      return;
    }
    const jobId = created.data.job_id;
    const running = await api.transitionStudioJob(jobId, {
      owner: createdBy, status: 'running', progress: 0.05,
    });
    if (running.error !== null) {
      await api.transitionStudioJob(jobId, {
        owner: createdBy, status: 'failed', progress: 0.1,
        error_code: 'factory_context_changed',
      });
      setBusy(false);
      setError(designerErrorMessage(running.error, 'factory'));
      return;
    }
    const result = await api.getFactoryPack(lineage.projectId);
    const exact = result.error === null
      && result.data.project_id === lineage.projectId
      && result.data.pinned_asset_id === lineage.sourceAssetId
      && result.data.design_version === lineage.sourceDesignVersion;
    if (result.error !== null || !exact) {
      await api.transitionStudioJob(jobId, {
        owner: createdBy, status: 'failed', progress: 0.9,
        error_code: result.error?.code ?? 'factory_lineage_mismatch',
      });
      setBusy(false);
      setError(result.error === null
        ? 'The prepared material did not match the selected revision, so it was not delivered or charged.'
        : designerErrorMessage(result.error, 'factory'));
      return;
    }
    const succeeded = await api.transitionStudioJob(jobId, {
      owner: createdBy, status: 'succeeded', progress: 1, completed_outputs: 1,
    });
    setBusy(false);
    if (succeeded.error !== null) {
      setError('Facetta prepared the material but could not verify its Activity record. Reopen the design before trying again.');
      return;
    }
    setPack(result.data);
  };

  if (lineage === null) {
    return (
      <View style={styles.empty}>
        <Text style={styles.title}>Choose an eligible revision first</Text>
        <Text style={styles.body}>Factory preparation is optional and always starts from one exact approved revision.</Text>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
      <Text style={styles.eyebrow}>OPTIONAL FACTORY PREPARATION</Text>
      <Text style={styles.title}>Prepare this exact revision for production review.</Text>
      <Text style={styles.body}>
        This creates review material for a jeweler or manufacturer. It is not a production-ready claim,
        and it does not alter the selected Studio revision.
      </Text>
      <Notice kind="info" text={`Exact revision ${lineage.sourceDesignVersion} is pinned for this request.`} />
      {error !== null && <Notice kind="error" text={error} />}
      {pack === null ? (
        <>
          <Text style={styles.creditEstimate}>
            1 requested output × {FACTORY_CREDITS} credits = estimated {FACTORY_CREDITS} credits
          </Text>
          <Text style={styles.small}>
            Failed preparation and internal retries are not charged. A successful verified pack charges once.
          </Text>
          <Button
            title={busy ? 'Preparing review material…' : 'Prepare production-review material'}
            disabled={busy}
            onPress={() => { void prepare(); }}
          />
        </>
      ) : (
        <View style={styles.packCard}>
          <Text style={styles.packTitle}>Review material prepared</Text>
          <Text style={styles.body}>
            {pack.factory_sheet_fact_plan.confirmed_fact_count} confirmed facts · {' '}
            {pack.factory_sheet_fact_plan.pending_confirmation_count} pending confirmations
          </Text>
          {pack.factory_sheet_fact_plan.has_estimates && (
            <Notice kind="info" text="Estimated values remain labeled for review and must be confirmed before production decisions." />
          )}
          <Text style={styles.sectionTitle}>Included files</Text>
          {pack.artifacts.map((artifact) => (
            <View key={artifact.name} style={styles.artifactRow}>
              <Text style={styles.artifactName}>{artifact.name}</Text>
              <Text style={styles.small}>{artifact.media_type}</Text>
            </View>
          ))}
          <Notice kind="ok" text="The pack is bound to the exact approved revision and recorded in Activity." />
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  workspace: { padding: 22, paddingBottom: 120, gap: 12 },
  empty: { padding: 28, alignItems: 'center', gap: 8 },
  eyebrow: { color: theme.accent, fontSize: 11, fontWeight: '800', letterSpacing: 2 },
  title: { color: theme.ink, fontFamily: theme.serif, fontSize: 28, lineHeight: 34 },
  body: { color: theme.faint, fontSize: 14, lineHeight: 21, maxWidth: 680 },
  small: { color: theme.faint, fontSize: 12, lineHeight: 17 },
  creditEstimate: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  packCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 16, gap: 10, backgroundColor: theme.card },
  packTitle: { color: theme.ink, fontSize: 18, fontWeight: '800' },
  sectionTitle: { color: theme.ink, fontSize: 12, fontWeight: '800', letterSpacing: 1.2, marginTop: 4 },
  artifactRow: { borderTopWidth: 1, borderTopColor: theme.line, paddingTop: 8, gap: 2 },
  artifactName: { color: theme.ink, fontWeight: '700' },
});
