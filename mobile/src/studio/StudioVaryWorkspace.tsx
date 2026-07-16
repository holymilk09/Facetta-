import React, {
  useEffect, useMemo, useRef, useState,
} from 'react';
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';

import { radius, theme } from '../theme';
import type { ProjectDetail } from '../trusted/types';
import type { PreviewCandidate } from './contracts';
import { designerErrorMessage } from './designerErrorMessage';
import type { StudioGateway, StudioVisualLineage } from './gateway';
import { getStudioAction } from './actions';
import { StudioReviewImage } from './StudioReviewImage';
import { useVisualReviewReadiness } from './useVisualReviewReadiness';

export type StudioVariationLineage = StudioVisualLineage;
export type StudioVariationCount = 1 | 2 | 3 | 4;

interface VariationPreview {
  candidate: PreviewCandidate;
  ordinal: number;
}

export interface StudioVaryWorkspaceProps {
  gateway: Pick<StudioGateway,
    'previewVisualRefine' | 'saveVisualPreviewAsVariation' | 'discardVisualRefine'>
    & Partial<Pick<StudioGateway, 'resumeRefine'>>;
  lineage: StudioVariationLineage | null;
  createdBy: string;
  sourceImageUrl?: string | null;
  onCreated: (project: ProjectDetail) => void;
  imageRequestHeaders?: Readonly<Record<string, string>>;
  resumeReviewJobId?: string;
}

const VARY_CREDITS_PER_OUTPUT = getStudioAction('vary').creditEstimate ?? 0;

function variationLabel(instruction: string, ordinal: number): string {
  const compact = instruction.trim().replace(/\s+/g, ' ');
  const summary = compact.length > 54 ? `${compact.slice(0, 51)}…` : compact;
  return `Variation ${ordinal} · ${summary}`;
}

export function StudioVaryWorkspace({
  gateway, lineage, createdBy, sourceImageUrl = null, onCreated,
  imageRequestHeaders, resumeReviewJobId,
}: StudioVaryWorkspaceProps) {
  const [instruction, setInstruction] = useState('');
  const [count, setCount] = useState<StudioVariationCount>(2);
  const [previews, setPreviews] = useState<readonly VariationPreview[]>([]);
  const [reviewStarted, setReviewStarted] = useState(false);
  const [reviewEpoch, setReviewEpoch] = useState(0);
  const [savedCount, setSavedCount] = useState(0);
  const [lastSavedProject, setLastSavedProject] = useState<ProjectDetail | null>(null);
  const [generating, setGenerating] = useState(false);
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestEpochRef = useRef(0);
  const mountedRef = useRef(true);
  const lineageKey = lineage === null
    ? 'none'
    : `${createdBy}:${lineage.projectId}:${lineage.sourceAssetId}`;
  const lineageKeyRef = useRef(lineageKey);
  lineageKeyRef.current = lineageKey;

  const visualScope = `${lineageKey}:${sourceImageUrl ?? 'missing'}:${reviewEpoch}`;
  const visualReview = useVisualReviewReadiness(visualScope);
  const sourceVisualKey = sourceImageUrl === null
    ? null
    : `vary-source:${lineage?.sourceAssetId ?? 'none'}:${sourceImageUrl}`;
  const candidateVisualKey = (candidate: PreviewCandidate): string => (
    `vary-candidate:${candidate.id}:${candidate.assetUrl}`
  );
  const sourceReady = visualReview.allReady([sourceVisualKey]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestEpochRef.current += 1;
    };
  }, []);

  useEffect(() => {
    requestEpochRef.current += 1;
    setInstruction('');
    setCount(2);
    setPreviews([]);
    setReviewStarted(false);
    setReviewEpoch((current) => current + 1);
    setSavedCount(0);
    setLastSavedProject(null);
    setGenerating(false);
    setDecidingId(null);
    setError(null);
  }, [lineageKey]);

  useEffect(() => {
    if (lineage === null || resumeReviewJobId === undefined
        || gateway.resumeRefine === undefined) return () => {};
    const requestedLineageKey = lineageKey;
    const requestEpoch = requestEpochRef.current + 1;
    requestEpochRef.current = requestEpoch;
    let current = true;
    setGenerating(true);
    setReviewEpoch((value) => value + 1);
    setError(null);
    void gateway.resumeRefine(
      lineage, createdBy, resumeReviewJobId, 'vary',
    ).then((result) => {
      if (!current || !mountedRef.current || requestEpochRef.current !== requestEpoch
          || lineageKeyRef.current !== requestedLineageKey) return;
      setGenerating(false);
      if (result.error !== null) {
        setError(designerErrorMessage(result.error, 'vary'));
        return;
      }
      if (result.data === null || result.data.kind !== 'visual') {
        setError('This variation preview is no longer available. Generate a new direction.');
        return;
      }
      setReviewStarted(true);
      setPreviews([{ candidate: result.data.candidate, ordinal: 1 }]);
    });
    return () => { current = false; };
  }, [createdBy, gateway, lineage, lineageKey, resumeReviewJobId]);

  const generate = async (): Promise<void> => {
    const requestedInstruction = instruction.trim();
    if (lineage === null || requestedInstruction.length === 0 || generating
        || decidingId !== null) return;
    const requestedLineageKey = lineageKey;
    const requestEpoch = requestEpochRef.current + 1;
    requestEpochRef.current = requestEpoch;
    setGenerating(true);
    setReviewEpoch((value) => value + 1);
    setError(null);
    setPreviews([]);
    const results = await Promise.all(
      Array.from({ length: count }, (_, index) => gateway.previewVisualRefine({
        ...lineage,
        createdBy,
        instruction: requestedInstruction,
        scope: 'appearance' as const,
        variant: index,
        jobAction: 'vary' as const,
      })),
    );
    const ready = results.flatMap((result, index) => (
      result.error === null
        ? [{ candidate: result.data.candidate, ordinal: index + 1 }]
        : []
    ));
    // Vary jobs and review candidates are durable. If this screen is no longer
    // current, Activity is the safe place to resume them; a fire-and-forget
    // discard here could fail invisibly and orphan only part of the batch.
    if (!mountedRef.current || requestEpochRef.current !== requestEpoch
        || lineageKeyRef.current !== requestedLineageKey) return;
    setGenerating(false);
    setPreviews(ready);
    if (ready.length === 0) {
      const firstFailure = results.find((result) => result.error !== null);
      setError(firstFailure?.error === null || firstFailure === undefined
        ? 'Facetta could not generate these variations. Try a shorter direction.'
        : designerErrorMessage(firstFailure.error, 'vary'));
      return;
    }
    setReviewStarted(true);
    if (ready.length < count) {
      setError(`${ready.length} of ${count} variations are ready. Failed attempts are not charged.`);
    }
  };

  const settleDiscard = async (targets: readonly VariationPreview[]) => {
    const results = await Promise.all(targets.map(async (preview) => ({
      preview,
      result: await gateway.discardVisualRefine({
        candidateId: preview.candidate.id, createdBy,
      }),
    })));
    return {
      failed: results.filter(({ result }) => result.error !== null),
      succeeded: results.filter(({ result }) => result.error === null),
    };
  };

  const clearPreviews = async (): Promise<void> => {
    if (generating || decidingId !== null || previews.length === 0) return;
    setDecidingId('discard-all');
    setError(null);
    const { failed, succeeded } = await settleDiscard(previews);
    if (!mountedRef.current) return;
    setDecidingId(null);
    setPreviews(failed.map(({ preview }) => preview));
    const firstFailure = failed[0]?.result.error ?? null;
    if (firstFailure !== null) {
      setError(
        `${succeeded.length} preview${succeeded.length === 1 ? '' : 's'} discarded. `
        + `${failed.length} still need review. ${designerErrorMessage(firstFailure, 'vary')}`,
      );
      return;
    }
    if (savedCount === 0) setReviewStarted(false);
  };

  const keep = async (selected: VariationPreview): Promise<void> => {
    if (decidingId !== null || selected.candidate.verdict === 'reject'
        || !sourceReady
        || !visualReview.allReady([candidateVisualKey(selected.candidate)])) return;
    setDecidingId(selected.candidate.id);
    setError(null);
    const saved = await gateway.saveVisualPreviewAsVariation({
      candidateId: selected.candidate.id,
      createdBy,
      label: variationLabel(instruction || 'Saved direction', selected.ordinal),
    });
    if (!mountedRef.current) return;
    if (saved.error !== null) {
      setDecidingId(null);
      setError(designerErrorMessage(saved.error, 'vary'));
      return;
    }
    setPreviews((current) => current.filter(
      ({ candidate }) => candidate.id !== selected.candidate.id,
    ));
    setSavedCount((current) => current + 1);
    setLastSavedProject(saved.data.project);
    setDecidingId(null);
  };

  const finish = async (): Promise<void> => {
    if (lastSavedProject === null || decidingId !== null || generating) return;
    setDecidingId('finish');
    setError(null);
    const { failed, succeeded } = await settleDiscard(previews);
    if (!mountedRef.current) return;
    setPreviews(failed.map(({ preview }) => preview));
    setDecidingId(null);
    const firstFailure = failed[0]?.result.error ?? null;
    if (firstFailure !== null) {
      setError(
        `${succeeded.length} unkept preview${succeeded.length === 1 ? '' : 's'} discarded. `
        + `${failed.length} still need review before finishing. `
        + designerErrorMessage(firstFailure, 'vary'),
      );
      return;
    }
    onCreated(lastSavedProject);
  };

  const estimatedCredits = useMemo(() => (
    count * VARY_CREDITS_PER_OUTPUT
  ), [count]);

  if (lineage === null) {
    return (
      <View style={styles.empty}>
        <Text style={styles.title}>Choose a saved direction first</Text>
        <Text style={styles.body}>Variations always begin with the exact design you are viewing.</Text>
      </View>
    );
  }

  if (reviewStarted) {
    return (
      <ScrollView style={styles.root} contentContainerStyle={styles.content}>
        <Text style={styles.eyebrow}>VARIATIONS</Text>
        <Text style={styles.title}>Choose the directions you want to keep.</Text>
        <Text style={styles.body}>
          Keep one or several. Each saved direction becomes an independent sibling and never replaces the current design.
        </Text>
        <Text style={styles.help}>Unfinished previews stay available in Activity if you leave.</Text>
        <View style={styles.sourceCard}>
          <Text style={styles.sourceLabel}>CURRENT SAVED DESIGN</Text>
          {sourceImageUrl === null ? (
            <Text style={styles.error}>The current design image is unavailable. Reopen it before saving a variation.</Text>
          ) : (
            <StudioReviewImage
              accessibilityLabel="Current saved design"
              inspectionLabel="Current saved design"
              source={{ uri: sourceImageUrl }}
              imageRequestHeaders={imageRequestHeaders}
              onLoad={() => visualReview.markReady(sourceVisualKey!)}
              onError={() => visualReview.markFailed(sourceVisualKey!)}
              style={styles.sourceImage}
            />
          )}
        </View>
        {savedCount > 0 && (
          <Text accessibilityLabel="Saved variation credits" style={styles.savedSummary}>
            {savedCount} saved output{savedCount === 1 ? '' : 's'} × {VARY_CREDITS_PER_OUTPUT} credits = {savedCount * VARY_CREDITS_PER_OUTPUT} credits
          </Text>
        )}
        <View style={styles.previewGrid}>
          {previews.map((preview) => {
            const visualKey = candidateVisualKey(preview.candidate);
            const visualReady = visualReview.allReady([visualKey]);
            const rejected = preview.candidate.verdict === 'reject';
            return (
              <View key={preview.candidate.id} style={styles.previewCard}>
                <Text style={styles.previewTitle}>Direction {preview.ordinal}</Text>
                <StudioReviewImage
                  accessibilityLabel={`Variation direction ${preview.ordinal}`}
                  inspectionLabel={`Variation direction ${preview.ordinal}`}
                  source={{ uri: preview.candidate.assetUrl }}
                  imageRequestHeaders={imageRequestHeaders}
                  onLoad={() => visualReview.markReady(visualKey)}
                  onError={() => visualReview.markFailed(visualKey)}
                  style={styles.previewImage}
                />
                <Text style={[styles.status, rejected && styles.error]}>{rejected
                  ? 'This direction changed too much and cannot be kept.'
                  : preview.candidate.verdict === 'warn'
                    ? 'Ready for your review. Compare it carefully with the source.'
                    : 'Ready to keep.'}</Text>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`Keep direction ${preview.ordinal} as a variation`}
                  accessibilityState={{
                    disabled: decidingId !== null || rejected || !sourceReady || !visualReady,
                  }}
                  disabled={decidingId !== null || rejected || !sourceReady || !visualReady}
                  style={[
                    styles.primaryButton,
                    (decidingId !== null || rejected || !sourceReady || !visualReady)
                      && styles.disabled,
                  ]}
                  onPress={() => { void keep(preview); }}>
                  <Text style={styles.primaryButtonText}>{decidingId === preview.candidate.id
                    ? 'Saving…' : 'Keep as variation'}</Text>
                </Pressable>
              </View>
            );
          })}
        </View>
        {previews.length === 0 && (
          <Text style={styles.resolved}>All generated directions have been resolved.</Text>
        )}
        {error !== null && <Text style={styles.errorNotice}>{error}</Text>}
        {previews.length > 0 && (
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ disabled: decidingId !== null }}
            disabled={decidingId !== null}
            style={styles.secondaryButton}
            onPress={() => { void clearPreviews(); }}>
            <Text style={styles.secondaryButtonText}>{decidingId === 'discard-all'
              ? 'Discarding…'
              : savedCount > 0 ? 'Discard remaining previews' : 'Discard and try another direction'}</Text>
          </Pressable>
        )}
        {lastSavedProject !== null && (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Finish variation review"
            accessibilityState={{ disabled: decidingId !== null }}
            disabled={decidingId !== null}
            style={[styles.primaryButton, decidingId !== null && styles.disabled]}
            onPress={() => { void finish(); }}>
            <Text style={styles.primaryButtonText}>{decidingId === 'finish'
              ? 'Finishing…'
              : previews.length > 0
                ? `Done · discard ${previews.length} unkept preview${previews.length === 1 ? '' : 's'}`
                : 'Done'}</Text>
          </Pressable>
        )}
      </ScrollView>
    );
  }

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.content}>
      <Text style={styles.eyebrow}>VARY THIS DESIGN</Text>
      <Text style={styles.title}>What direction should we explore?</Text>
      <Text style={styles.body}>
        Describe one change. Facetta keeps the jewelry form anchored to the current saved design and shows temporary options before anything is saved.
      </Text>
      <Text style={styles.fieldLabel}>Variation direction</Text>
      <TextInput
        accessibilityLabel="Variation direction"
        value={instruction}
        onChangeText={setInstruction}
        placeholder="For example: explore warm rose gold with a satin finish"
        placeholderTextColor={theme.faint}
        multiline
        style={styles.input}
      />
      <Text style={styles.fieldLabel}>How many directions?</Text>
      <Text style={styles.help}>Choose 1 for speed, or 2–4 to compare.</Text>
      <View style={styles.countRow}>
        {([1, 2, 3, 4] as const).map((option) => (
          <Pressable
            key={option}
            accessibilityRole="radio"
            accessibilityLabel={`${option} variation${option === 1 ? '' : 's'}`}
            accessibilityState={{ checked: count === option }}
            style={[styles.countChip, count === option && styles.countChipSelected]}
            onPress={() => setCount(option)}>
            <Text style={[styles.countText, count === option && styles.countTextSelected]}>{option}</Text>
          </Pressable>
        ))}
      </View>
      {error !== null && <Text style={styles.errorNotice}>{error}</Text>}
      <Text style={styles.creditEstimate}>
        {VARY_CREDITS_PER_OUTPUT} credits for each variation you keep · maximum {estimatedCredits} credits if you keep all {count}. Discarded or failed previews are not charged.
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: generating || instruction.trim().length === 0 }}
        disabled={generating || instruction.trim().length === 0}
        style={[
          styles.primaryButton,
          (generating || instruction.trim().length === 0) && styles.disabled,
        ]}
        onPress={() => { void generate(); }}>
        {generating && <ActivityIndicator color="#ffffff" size="small" />}
        <Text style={styles.primaryButtonText}>{generating
          ? 'Generating variations…'
          : `Generate ${count} variation${count === 1 ? '' : 's'}`}</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.paper },
  content: {
    width: '100%', maxWidth: 760, alignSelf: 'center', padding: 20, paddingBottom: 60,
  },
  empty: { padding: 24, backgroundColor: theme.paper, gap: 8 },
  eyebrow: { color: '#6f52d9', fontSize: 10, fontWeight: '800', letterSpacing: 1.4 },
  title: {
    color: theme.ink, fontFamily: theme.serif, fontSize: 30, lineHeight: 37, marginTop: 8,
  },
  body: { color: theme.faint, fontSize: 14, lineHeight: 21, marginTop: 8, maxWidth: 600 },
  fieldLabel: { color: theme.ink, fontSize: 13, fontWeight: '700', marginTop: 22 },
  help: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 4 },
  input: {
    minHeight: 112, borderWidth: 1, borderColor: theme.line, borderRadius: radius.md,
    backgroundColor: theme.card, color: theme.ink, fontSize: 15, lineHeight: 22,
    padding: 14, marginTop: 8, textAlignVertical: 'top',
  },
  countRow: { flexDirection: 'row', gap: 10, marginTop: 12 },
  countChip: {
    width: 48, height: 48, borderRadius: 24, borderWidth: 1, borderColor: theme.line,
    backgroundColor: theme.card, alignItems: 'center', justifyContent: 'center',
  },
  countChipSelected: { backgroundColor: '#6f52d9', borderColor: '#6f52d9' },
  countText: { color: theme.faint, fontSize: 14, fontWeight: '800' },
  countTextSelected: { color: '#ffffff' },
  creditEstimate: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 22 },
  primaryButton: {
    minHeight: 50, flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center',
    borderRadius: radius.pill, backgroundColor: '#6f52d9', paddingHorizontal: 18,
    paddingVertical: 14, marginTop: 14,
  },
  primaryButtonText: { color: '#ffffff', fontSize: 13, fontWeight: '800' },
  secondaryButton: {
    alignItems: 'center', borderRadius: radius.pill, borderWidth: 1,
    borderColor: theme.line, paddingHorizontal: 18, paddingVertical: 14, marginTop: 20,
  },
  secondaryButtonText: { color: theme.ink, fontSize: 13, fontWeight: '800' },
  disabled: { opacity: 0.42 },
  sourceCard: {
    borderWidth: 1, borderColor: theme.line, borderRadius: radius.md,
    backgroundColor: theme.card, padding: 12, marginTop: 20,
  },
  sourceLabel: { color: theme.faint, fontSize: 10, fontWeight: '800', letterSpacing: 0.8 },
  sourceImage: {
    width: '100%', aspectRatio: 1.45, borderRadius: radius.sm,
    backgroundColor: theme.line, marginTop: 8,
  },
  savedSummary: {
    color: theme.ink, fontSize: 12, fontWeight: '700', lineHeight: 18,
    borderWidth: 1, borderColor: '#cabdf8', borderRadius: radius.sm,
    backgroundColor: '#f4f0ff', padding: 10, marginTop: 14,
  },
  previewGrid: { gap: 14, marginTop: 16 },
  previewCard: {
    borderWidth: 1, borderColor: theme.line, borderRadius: radius.md,
    backgroundColor: theme.card, padding: 12,
  },
  previewTitle: { color: theme.ink, fontSize: 14, fontWeight: '800', marginBottom: 8 },
  previewImage: {
    width: '100%', aspectRatio: 1, borderRadius: radius.sm, backgroundColor: theme.line,
  },
  status: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 10 },
  resolved: {
    color: theme.faint, fontSize: 13, lineHeight: 20, textAlign: 'center', marginTop: 20,
  },
  error: { color: theme.danger, fontSize: 12, lineHeight: 18, marginTop: 8 },
  errorNotice: {
    color: theme.danger, fontSize: 12, lineHeight: 18, borderWidth: 1,
    borderColor: theme.danger, borderRadius: radius.sm, padding: 10, marginTop: 14,
  },
});
