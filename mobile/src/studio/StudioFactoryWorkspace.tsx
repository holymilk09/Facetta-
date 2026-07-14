import React, { useCallback, useEffect, useState } from 'react';
import {
  Platform, ScrollView, Share, StyleSheet, Text, View,
} from 'react-native';
import { File, Paths } from 'expo-file-system';

import { Button, Notice } from '../components';
import { radius, theme } from '../theme';
import type {
  ApprovalSummary, FactoryPackManifest, ProjectDetail,
} from '../trusted/types';
import { getStudioAction } from './actions';
import { designerErrorMessage } from './designerErrorMessage';
import type { ExactStudioLineage, StudioGateway } from './gateway';

const FACTORY_CREDITS = getStudioAction('factory').creditEstimate ?? 0;

export type StudioFactoryApi = Pick<StudioGateway,
  'createStudioJob' | 'prepareFactoryPack'
  | 'getProject' | 'createChecklist' | 'respondChecklist'>;

export interface StudioProtectedFileRequest {
  url: string;
  name: string;
  mediaType: string;
}

export interface StudioProtectedFileDeliveryOptions {
  apiUrl: string;
  accessToken: string | null;
  fetcher?: typeof fetch;
  platform?: string;
  webDownload?: (bytes: ArrayBuffer, request: StudioProtectedFileRequest) => void;
  nativeShare?: (bytes: ArrayBuffer, request: StudioProtectedFileRequest) => Promise<void>;
}

/** Fetch protected bytes with the session bearer before any local delivery. */
export async function deliverAuthenticatedProtectedFile(
  request: StudioProtectedFileRequest,
  options: StudioProtectedFileDeliveryOptions,
): Promise<void> {
  if (options.accessToken === null) {
    throw new Error('Sign in again before opening this protected file.');
  }
  const apiOrigin = new URL(options.apiUrl).origin;
  const resolved = new URL(request.url, `${options.apiUrl.replace(/\/$/, '')}/`);
  if (resolved.origin !== apiOrigin || resolved.username || resolved.password) {
    throw new Error('This protected file does not belong to the Facetta workspace.');
  }
  const response = await (options.fetcher ?? fetch)(resolved.toString(), {
    redirect: 'error',
    headers: {
      Authorization: `Bearer ${options.accessToken}`,
      Accept: request.mediaType,
    },
  });
  if (!response.ok) {
    throw new Error('Facetta could not retrieve this protected file. Try again.');
  }
  const bytes = await response.arrayBuffer();
  if ((options.platform ?? Platform.OS) === 'web') {
    if (options.webDownload !== undefined) {
      options.webDownload(bytes, request);
      return;
    }
    const objectUrl = URL.createObjectURL(new Blob([bytes], { type: request.mediaType }));
    try {
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = request.name;
      anchor.rel = 'noopener';
      anchor.click();
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
    return;
  }
  if (options.nativeShare !== undefined) {
    await options.nativeShare(bytes, request);
    return;
  }
  const safeName = request.name.replace(/[^a-zA-Z0-9._-]/g, '_') || 'facetta-file';
  const file = new File(Paths.cache, safeName);
  file.create({ overwrite: true, intermediates: true });
  file.write(new Uint8Array(bytes));
  await Share.share({ title: request.name, url: file.uri, message: file.uri });
}

export interface StudioFactoryWorkspaceProps {
  api: StudioFactoryApi;
  lineage: ExactStudioLineage | null;
  createdBy: string;
  deliverProtectedFile: (request: StudioProtectedFileRequest) => Promise<void>;
  onProjectUpdated?: (project: ProjectDetail) => void;
}

export function StudioFactoryWorkspace({
  api, lineage, createdBy, deliverProtectedFile, onProjectUpdated,
}: StudioFactoryWorkspaceProps) {
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [approval, setApproval] = useState<ApprovalSummary | null>(null);
  const [readinessBusy, setReadinessBusy] = useState(false);
  const [readinessError, setReadinessError] = useState<string | null>(null);
  const [pack, setPack] = useState<FactoryPackManifest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deliveryError, setDeliveryError] = useState<string | null>(null);
  const [pendingDelivery, setPendingDelivery] = useState<StudioProtectedFileRequest | null>(null);
  const [delivering, setDelivering] = useState<string | null>(null);

  const refreshReadiness = useCallback(async (): Promise<ProjectDetail | null> => {
    if (lineage === null) return null;
    const result = await api.getProject(lineage.projectId);
    if (result.error !== null
      || result.data.active_asset_id !== lineage.sourceAssetId
      || result.data.active_design_version !== lineage.sourceDesignVersion) {
      setReadinessError(result.error === null
        ? 'This design changed while Factory readiness was open. Reopen the exact revision before continuing.'
        : designerErrorMessage(result.error, 'factory'));
      return null;
    }
    setProject(result.data);
    setApproval(result.data.approval);
    setReadinessError(null);
    onProjectUpdated?.(result.data);
    return result.data;
  }, [api, lineage, onProjectUpdated]);

  useEffect(() => {
    setProject(null);
    setApproval(null);
    setPack(null);
    if (lineage !== null) void refreshReadiness();
  }, [lineage?.projectId, lineage?.sourceAssetId, lineage?.sourceDesignVersion]);

  const startChecklist = async (): Promise<void> => {
    if (lineage === null || readinessBusy) return;
    setReadinessBusy(true);
    setReadinessError(null);
    const result = await api.createChecklist(lineage.sourceAssetId, {
      created_by: createdBy,
      mode: 'auto_pin',
    });
    if (result.error !== null) {
      setReadinessError(designerErrorMessage(result.error, 'factory'));
    } else {
      setApproval(result.data);
      await refreshReadiness();
    }
    setReadinessBusy(false);
  };

  const approveFact = async (itemKey: string): Promise<void> => {
    if (lineage === null || readinessBusy) return;
    setReadinessBusy(true);
    setReadinessError(null);
    const result = await api.respondChecklist(lineage.sourceAssetId, {
      item_key: itemKey,
      approved: true,
      created_by: createdBy,
      interpret: false,
    });
    if (result.error !== null) {
      setReadinessError(designerErrorMessage(result.error, 'factory'));
    } else {
      setApproval(result.data);
      await refreshReadiness();
    }
    setReadinessBusy(false);
  };

  const deliver = async (request: StudioProtectedFileRequest): Promise<void> => {
    if (delivering !== null) return;
    setDelivering(request.name);
    setDeliveryError(null);
    setPendingDelivery(null);
    try {
      await deliverProtectedFile(request);
    } catch {
      setPendingDelivery(request);
      setDeliveryError(
        'Facetta could not open that protected file. Your review pack and credit record are unchanged.',
      );
    } finally {
      setDelivering(null);
    }
  };

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
    const result = await api.prepareFactoryPack(lineage.projectId, {
      studio_job_id: jobId,
      owner: createdBy,
    });
    const exact = result.error === null
      && result.data.project_id === lineage.projectId
      && result.data.pinned_asset_id === lineage.sourceAssetId
      && result.data.design_version === lineage.sourceDesignVersion;
    if (result.error !== null || !exact) {
      setBusy(false);
      setError(result.error === null
        ? 'The prepared material did not match the selected revision, so it was not displayed. Check Activity before trying again.'
        : designerErrorMessage(result.error, 'factory'));
      return;
    }
    setBusy(false);
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

  const exactPinnedRevision = project?.pinned_revision?.asset_id === lineage.sourceAssetId
    && project?.pinned_revision?.design_version === lineage.sourceDesignVersion;
  const factoryReady = project?.factory_ready === true && exactPinnedRevision;
  const blockers = project?.factory_blockers ?? [];

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
      <Text style={styles.eyebrow}>OPTIONAL FACTORY READINESS</Text>
      <Text style={styles.title}>Review this exact revision before sharing it with a manufacturer.</Text>
      <Text style={styles.body}>
        Confirm only facts you know are correct. This is a readiness review—not a production-ready claim—and it never alters the selected Studio revision.
      </Text>
      <Notice kind="info" text="The exact saved revision is selected for this readiness review." />
      {readinessError !== null && <Notice kind="error" text={readinessError} />}
      {project === null ? (
        <Text style={styles.small}>Checking the exact revision and its readiness record…</Text>
      ) : (
        <View style={styles.packCard}>
          <Text style={styles.packTitle}>{factoryReady ? 'Ready for optional Factory preparation' : 'Readiness review'}</Text>
          {blockers.length > 0 && (
            <View style={styles.blockerList}>
              <Text style={styles.sectionTitle}>What still needs attention</Text>
              {blockers.map((blocker) => (
                <Text key={`${blocker.code}:${blocker.subject_id}`} style={styles.blockerText}>• {blocker.detail}</Text>
              ))}
            </View>
          )}
          {approval === null ? (
            <>
              <Text style={styles.body}>Create a checklist derived from this revision's exact specification. Each confirmation is recorded against this immutable revision.</Text>
              <Button
                title={readinessBusy ? 'Creating checklist…' : 'Start exact-fact checklist'}
                disabled={readinessBusy}
                onPress={() => { void startChecklist(); }}
              />
            </>
          ) : (
            <>
              <Text style={styles.body}>{approval.approved_count} of {approval.total} exact facts confirmed</Text>
              {approval.items.map((item) => {
                const confirmed = approval.answers[item.key]?.approved === true;
                return (
                  <View key={item.key} style={styles.factRow}>
                    <View style={styles.artifactCopy}>
                      <Text style={styles.artifactName}>{item.label}</Text>
                      <Text style={styles.small}>{item.fact}</Text>
                    </View>
                    {confirmed ? (
                      <Text style={styles.confirmed}>Confirmed</Text>
                    ) : (
                      <Button
                        title="Confirm fact"
                        kind="ghost"
                        disabled={readinessBusy}
                        onPress={() => { void approveFact(item.key); }}
                      />
                    )}
                  </View>
                );
              })}
              {!approval.all_approved && (
                <Notice kind="info" text="If a fact is wrong, return to Refine or Advanced specifications. Do not confirm it just to unlock Factory." />
              )}
            </>
          )}
          {factoryReady && <Notice kind="ok" text="All required facts are confirmed and this exact revision is pinned. Factory remains optional." />}
        </View>
      )}
      {error !== null && <Notice kind="error" text={error} />}
      {!factoryReady ? null : pack === null ? (
        <>
          <Text style={styles.creditEstimate}>
            1 requested output × {FACTORY_CREDITS} credits = estimated {FACTORY_CREDITS} credits
          </Text>
          <Text style={styles.small}>
            You pay only for a usable requested output. Unsuccessful results cost 0 credits.
          </Text>
          <Button
            title={busy ? 'Preparing review material…' : 'Prepare factory review material'}
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
              <View style={styles.artifactCopy}>
                <Text style={styles.artifactName}>{artifact.name}</Text>
                <Text style={styles.small}>{artifact.media_type}</Text>
              </View>
              <Button
                title={delivering === artifact.name ? 'Opening…' : `Open ${artifact.name}`}
                kind="ghost"
                disabled={delivering !== null}
                onPress={() => { void deliver({
                  url: artifact.url,
                  name: artifact.name,
                  mediaType: artifact.media_type,
                }); }}
              />
            </View>
          ))}
          <Button
            title={delivering === 'facetta-factory-review.zip'
              ? 'Preparing download…' : 'Download complete review pack'}
            disabled={delivering !== null}
            onPress={() => { void deliver({
              url: pack.bundle_url,
              name: 'facetta-factory-review.zip',
              mediaType: 'application/zip',
            }); }}
          />
          {deliveryError !== null && <Notice kind="error" text={deliveryError} />}
          {pendingDelivery !== null && (
            <Button
              title="Retry protected file"
              kind="ghost"
              disabled={delivering !== null}
              onPress={() => { void deliver(pendingDelivery); }}
            />
          )}
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
  blockerList: { gap: 6 },
  blockerText: { color: theme.faint, fontSize: 13, lineHeight: 19 },
  factRow: {
    borderTopWidth: 1, borderTopColor: theme.line, paddingTop: 10, gap: 10,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
  },
  confirmed: { color: theme.ok, fontSize: 12, fontWeight: '800' },
  artifactRow: {
    borderTopWidth: 1, borderTopColor: theme.line, paddingTop: 8, gap: 8,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
  },
  artifactCopy: { flex: 1, gap: 2 },
  artifactName: { color: theme.ink, fontWeight: '700' },
});
