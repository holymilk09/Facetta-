import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { Button, Notice } from '../components';
import { theme } from '../theme';
import type { StudioJobAction, StudioJobRecord, StudioJobStatus } from '../trusted/types';
import { designerErrorMessage } from './designerErrorMessage';
import type { StudioGateway } from './gateway';

export type StudioActivityApi = Pick<StudioGateway,
  'listStudioJobs' | 'cancelStudioJob'
>;

export interface StudioActivityWorkspaceProps {
  api: StudioActivityApi;
  owner: string;
  onOpenDesign?: (designId: string) => void;
  onOpenReview?: (job: StudioJobRecord) => void;
}

const ACTION_LABELS: Record<StudioJobAction, string> = {
  create: 'Create directions',
  vary: 'Create variation',
  refine: 'Refine design',
  views: 'Prepare views',
  present: 'Prepare presentation',
  factory: 'Prepare factory review',
};

const STATUS_LABELS: Record<StudioJobStatus, string> = {
  queued: 'Waiting',
  running: 'Creating',
  reviewing: 'Ready to review',
  succeeded: 'Ready',
  failed: 'Did not finish',
  canceled: 'Canceled',
};

function billingLine(job: StudioJobRecord): string {
  const { billing } = job;
  if (job.status === 'succeeded') {
    return `${billing.completed_outputs} of ${billing.requested_outputs} requested output${billing.requested_outputs === 1 ? '' : 's'} ready · ${billing.charged_credits} credits charged`;
  }
  if (job.status === 'failed' || job.status === 'canceled') {
    return `0 credits charged · ${billing.requested_outputs} output${billing.requested_outputs === 1 ? '' : 's'} requested`;
  }
  return `${billing.requested_outputs} output${billing.requested_outputs === 1 ? '' : 's'} requested · up to ${billing.estimated_credits} credits`;
}

function dateLine(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function StudioActivityWorkspace({
  api,
  owner,
  onOpenDesign,
  onOpenReview,
}: StudioActivityWorkspaceProps) {
  const [jobs, setJobs] = useState<StudioJobRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cancelingId, setCancelingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const response = await api.listStudioJobs(owner);
    if (response.error !== null) {
      setError(designerErrorMessage(response.error, 'activity'));
      setJobs((current) => current ?? []);
      return;
    }
    setJobs(response.data.jobs);
  }, [api, owner]);

  useEffect(() => {
    void load();
  }, [load]);

  const hasActiveJob = jobs?.some((job) => (
    job.status === 'queued' || job.status === 'running'
  )) === true;

  useEffect(() => {
    if (!hasActiveJob) return () => {};
    const timer = setTimeout(() => { void load(); }, 3_000);
    return () => clearTimeout(timer);
  }, [hasActiveJob, jobs, load]);

  const cancel = async (job: StudioJobRecord) => {
    setCancelingId(job.job_id);
    setError(null);
    const response = await api.cancelStudioJob(job.job_id, owner);
    setCancelingId(null);
    if (response.error !== null) {
      setError(designerErrorMessage(response.error, 'activity'));
      return;
    }
    setJobs((current) => current?.map((item) => (
      item.job_id === response.data.job_id ? response.data : item
    )) ?? [response.data]);
  };

  if (jobs === null) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color={theme.accent} />
        <Text style={styles.muted}>Loading your work…</Text>
      </View>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
      <View style={styles.headerRow}>
        <View style={styles.headerCopy}>
          <Text style={styles.eyebrow}>ACTIVITY</Text>
          <Text style={styles.title}>Your work, in one place</Text>
          <Text style={styles.subtitle}>Follow each request from waiting to ready. Leaving this screen will not stop it.</Text>
        </View>
        <Button title="Refresh" kind="ghost" onPress={() => void load()} />
      </View>

      {error !== null && <Notice kind="error" text={error} />}

      {jobs.length === 0 && error === null ? (
        <View style={styles.empty}>
          <Text style={styles.emptyTitle}>Nothing is running yet</Text>
          <Text style={styles.muted}>Generation requests from Create, Refine, Views, and Present will stay visible here.</Text>
        </View>
      ) : jobs.map((job) => {
        const cancellable = job.status === 'queued' || job.status === 'running';
        const openable = job.active_design_id !== null && onOpenDesign !== undefined;
        const reviewable = job.status === 'reviewing'
          && ['create', 'refine', 'views', 'present'].includes(job.action_id)
          && job.active_design_id !== null && onOpenReview !== undefined;
        const archivedCreate = job.status === 'succeeded' && job.action_id === 'create';
        return (
          <View key={job.job_id} style={styles.card}>
            <View style={styles.cardHeader}>
              <View style={styles.cardTitleBlock}>
                <Text style={styles.action}>{ACTION_LABELS[job.action_id]}</Text>
                <Text style={styles.muted}>{dateLine(job.created_at)}</Text>
              </View>
              <View style={[
                styles.statusPill,
                job.status === 'succeeded' && styles.statusReady,
                (job.status === 'failed' || job.status === 'canceled') && styles.statusQuiet,
              ]}>
                <Text style={styles.statusText}>{STATUS_LABELS[job.status]}</Text>
              </View>
            </View>

            <View style={styles.progressTrack} accessibilityLabel={`${Math.round(job.progress * 100)}% complete`}>
              <View style={[styles.progressFill, { width: `${Math.round(job.progress * 100)}%` }]} />
            </View>
            <Text style={styles.billing}>{billingLine(job)}</Text>
            {job.status === 'failed' && (
              <Text style={styles.failureCopy}>This request did not produce a usable result. Your saved design is unchanged.</Text>
            )}

            <View style={styles.actions}>
              {reviewable && (
                <Pressable
                  accessibilityRole="button"
                  onPress={() => onOpenReview?.(job)}
                  style={styles.textAction}>
                  <Text style={styles.textActionLabel}>Review result</Text>
                </Pressable>
              )}
              {openable && !reviewable && (
                <Pressable
                  accessibilityRole="button"
                  onPress={() => onOpenDesign?.(job.active_design_id as string)}
                  style={styles.textAction}>
                  <Text style={styles.textActionLabel}>
                    {archivedCreate ? 'Review generated directions' : 'Open design'}
                  </Text>
                </Pressable>
              )}
              {cancellable && (
                <Pressable
                  accessibilityRole="button"
                  disabled={cancelingId === job.job_id}
                  onPress={() => void cancel(job)}
                  style={styles.textAction}>
                  <Text style={styles.cancelLabel}>{cancelingId === job.job_id ? 'Canceling…' : 'Cancel request'}</Text>
                </Pressable>
              )}
            </View>
          </View>
        );
      })}

      <View style={styles.policy}>
        <Text style={styles.policyTitle}>Clear credit policy</Text>
        <Text style={styles.muted}>You pay only for usable requested outputs. Unsuccessful results cost 0 credits.</Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  workspace: { padding: 24, gap: 14, maxWidth: 940, width: '100%', alignSelf: 'center' },
  loading: { flex: 1, minHeight: 280, alignItems: 'center', justifyContent: 'center', gap: 10 },
  headerRow: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: 18 },
  headerCopy: { flex: 1, gap: 5 },
  eyebrow: { color: theme.accent, fontSize: 12, fontWeight: '800', letterSpacing: 1.4 },
  title: { color: theme.ink, fontSize: 28, fontWeight: '800' },
  subtitle: { color: theme.faint, fontSize: 14, lineHeight: 21, maxWidth: 620 },
  muted: { color: theme.faint, fontSize: 12, lineHeight: 18 },
  empty: { borderWidth: 1, borderColor: theme.line, borderRadius: 16, padding: 24, gap: 6 },
  emptyTitle: { color: theme.ink, fontSize: 17, fontWeight: '700' },
  card: { borderWidth: 1, borderColor: theme.line, borderRadius: 16, padding: 18, gap: 13, backgroundColor: theme.card },
  cardHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 },
  cardTitleBlock: { flex: 1, gap: 3 },
  action: { color: theme.ink, fontSize: 17, fontWeight: '700' },
  statusPill: { borderRadius: 999, paddingHorizontal: 11, paddingVertical: 6, backgroundColor: theme.goldSoft },
  statusReady: { backgroundColor: 'rgba(68, 183, 123, 0.16)' },
  statusQuiet: { backgroundColor: 'rgba(140, 140, 140, 0.14)' },
  statusText: { color: theme.ink, fontSize: 12, fontWeight: '700' },
  progressTrack: { height: 5, borderRadius: 999, overflow: 'hidden', backgroundColor: theme.line },
  progressFill: { height: '100%', borderRadius: 999, backgroundColor: theme.accent },
  billing: { color: theme.ink, fontSize: 13, fontWeight: '600' },
  failureCopy: { color: theme.faint, fontSize: 13, lineHeight: 19 },
  actions: { flexDirection: 'row', gap: 18, alignItems: 'center' },
  textAction: { paddingVertical: 4 },
  textActionLabel: { color: theme.accent, fontSize: 13, fontWeight: '700' },
  cancelLabel: { color: theme.faint, fontSize: 13, fontWeight: '700' },
  policy: { marginTop: 6, borderTopWidth: 1, borderTopColor: theme.line, paddingTop: 16, gap: 4 },
  policyTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
});
