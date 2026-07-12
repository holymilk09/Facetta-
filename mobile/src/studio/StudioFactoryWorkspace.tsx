import React, { useState } from 'react';
import {
  Platform, ScrollView, Share, StyleSheet, Text, View,
} from 'react-native';
import { File, Paths } from 'expo-file-system';

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
}

export function StudioFactoryWorkspace({
  api, lineage, createdBy, deliverProtectedFile,
}: StudioFactoryWorkspaceProps) {
  const [pack, setPack] = useState<FactoryPackManifest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deliveryError, setDeliveryError] = useState<string | null>(null);
  const [pendingDelivery, setPendingDelivery] = useState<StudioProtectedFileRequest | null>(null);
  const [delivering, setDelivering] = useState<string | null>(null);

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
  artifactRow: {
    borderTopWidth: 1, borderTopColor: theme.line, paddingTop: 8, gap: 8,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
  },
  artifactCopy: { flex: 1, gap: 2 },
  artifactName: { color: theme.ink, fontWeight: '700' },
});
