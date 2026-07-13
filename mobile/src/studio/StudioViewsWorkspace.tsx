import React, { useEffect, useRef, useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, View,
} from 'react-native';

import { Button, Notice } from '../components';
import { radius, theme } from '../theme';
import type { ProjectDetail } from '../trusted/types';
import type {
  ExactStudioLineage, StudioGateway, StudioViewPreview,
} from './gateway';
import {
  designerCheckDetail, designerCheckLabel, designerReviewState,
} from './designerReviewLanguage';
import { designerErrorMessage } from './designerErrorMessage';
import { getStudioAction } from './actions';
import { useVisualReviewReadiness } from './useVisualReviewReadiness';
import { StudioReviewImage } from './StudioReviewImage';

const VIEWS_CREDITS_PER_OUTPUT = getStudioAction('views').creditEstimate ?? 0;

const VIEWS = [
  { id: 'front', label: 'Front', detail: 'A clear straight-on geometry view.' },
  { id: 'three_quarter', label: 'Three-quarter', detail: 'A dimensional view that keeps the full form readable.' },
  { id: 'side', label: 'Side', detail: 'A profile view for height and setting relationships.' },
] as const;

type ViewId = typeof VIEWS[number]['id'];

export interface StudioViewsWorkspaceProps {
  gateway: Pick<StudioGateway,
    'previewLineArtView' | 'resumeViews' | 'acceptLineArtView' | 'discardLineArtView'>
    & Partial<Pick<StudioGateway, 'assetImageUrl'>>;
  lineage: ExactStudioLineage | null;
  createdBy: string;
  onSaved: (project: ProjectDetail) => void;
  /** Optional host navigation shown only after a view is saved. */
  onOpenCollections?: () => void;
  imageRequestHeaders?: Readonly<Record<string, string>>;
  resumeReviewJobId?: string;
  reviewSourceIsActive?: boolean;
}

export function StudioViewsWorkspace({
  gateway, lineage, createdBy, onSaved, onOpenCollections, imageRequestHeaders,
  resumeReviewJobId, reviewSourceIsActive = true,
}: StudioViewsWorkspaceProps) {
  const [view, setView] = useState<ViewId>('three_quarter');
  const [preview, setPreview] = useState<StudioViewPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [savedForLineage, setSavedForLineage] = useState(false);
  const lineageKey = lineage === null ? 'none'
    : `${lineage.projectId}:${lineage.sourceAssetId}:${lineage.sourceDesignVersion}`;
  const lineageKeyRef = useRef(lineageKey);
  lineageKeyRef.current = lineageKey;
  const [uiLineageKey, setUiLineageKey] = useState(lineageKey);
  const uiMatchesLineage = uiLineageKey === lineageKey;
  const visibleNotice = uiMatchesLineage ? notice : null;
  const visibleError = uiMatchesLineage ? error : null;
  const previewForLineage = preview !== null && lineage !== null
    && preview.lineage.projectId === lineage.projectId
    && preview.lineage.sourceAssetId === lineage.sourceAssetId
    && preview.lineage.sourceDesignVersion === lineage.sourceDesignVersion
    ? preview : null;
  const sourceImageUrl = lineage === null || typeof gateway.assetImageUrl !== 'function'
    ? null : gateway.assetImageUrl(lineage.sourceAssetId);
  const visualReviewScope = `${lineageKey}:${sourceImageUrl ?? 'missing'}:${previewForLineage?.candidateId ?? 'no-preview'}:${previewForLineage?.previewUrl ?? 'missing'}`;
  const visualReview = useVisualReviewReadiness(visualReviewScope);
  const sourceVisualKey = sourceImageUrl === null
    ? null : `views-source:${lineage?.sourceAssetId ?? 'none'}:${sourceImageUrl}`;
  const candidateVisualKey = previewForLineage === null
    ? null : `views-candidate:${previewForLineage.candidateId}:${previewForLineage.previewUrl}`;
  const comparisonVisualKeys = [sourceVisualKey, candidateVisualKey] as const;
  const comparisonReady = visualReview.allReady(comparisonVisualKeys);

  useEffect(() => {
    setUiLineageKey(lineageKey);
    setPreview(null);
    setNotice(null);
    setSavedForLineage(false);
    setError(null);
    setBusy(false);
    if (lineage === null || typeof gateway.resumeViews !== 'function') return undefined;
    const requestedLineageKey = lineageKey;
    let active = true;
    const resumed = resumeReviewJobId === undefined
      ? gateway.resumeViews(lineage, createdBy)
      : gateway.resumeViews(lineage, createdBy, resumeReviewJobId);
    void resumed.then((result) => {
      if (!active || lineageKeyRef.current !== requestedLineageKey) return;
      if (result.error !== null) {
        setError(designerErrorMessage(result.error, 'views'));
        return;
      }
      if (result.data === null) return;
      setPreview((current) => current ?? result.data);
      setNotice((current) => current ?? 'A saved view preview was resumed for review.');
    });
    return () => { active = false; };
  }, [createdBy, gateway, lineageKey, resumeReviewJobId]);

  const createPreview = async (): Promise<void> => {
    if (lineage === null || busy || !reviewSourceIsActive) return;
    const requestedLineageKey = lineageKey;
    setBusy(true);
    setError(null);
    setNotice(null);
    const result = await gateway.previewLineArtView({
      ...lineage, createdBy, view,
    });
    if (lineageKeyRef.current !== requestedLineageKey) return;
    setBusy(false);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'views'));
      return;
    }
    setPreview(result.data);
  };

  const accept = async (): Promise<void> => {
    if (previewForLineage === null || busy || previewForLineage.verdict === 'fail'
      || !reviewSourceIsActive || !comparisonReady) return;
    const requestedLineageKey = lineageKey;
    setBusy(true);
    setError(null);
    const result = await gateway.acceptLineArtView({
      candidateId: previewForLineage.candidateId, createdBy,
    });
    if (lineageKeyRef.current !== requestedLineageKey) return;
    setBusy(false);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'views'));
      return;
    }
    if (result.data.project === null) {
      setError('The view was not saved. Your active revision remains unchanged.');
      return;
    }
    setPreview(null);
    setSavedForLineage(true);
    setNotice('View saved beside the design. The active design revision did not change.');
    onSaved(result.data.project);
  };

  const discard = async (): Promise<void> => {
    if (previewForLineage === null || busy) return;
    const requestedLineageKey = lineageKey;
    setBusy(true);
    setError(null);
    const result = await gateway.discardLineArtView({
      candidateId: previewForLineage.candidateId, createdBy,
    });
    if (lineageKeyRef.current !== requestedLineageKey) return;
    setBusy(false);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'views'));
      return;
    }
    setPreview(null);
    setNotice('Preview discarded. Nothing was added to the design.');
  };

  if (lineage === null) {
    return (
      <View style={styles.empty}>
        <Text style={styles.title}>Choose a saved direction first</Text>
        <Text style={styles.body}>Views always start from one saved revision.</Text>
      </View>
    );
  }

  if (previewForLineage !== null) {
    const rejected = previewForLineage.verdict === 'fail';
    return (
      <ScrollView contentContainerStyle={styles.workspace}>
        <Text style={styles.eyebrow}>REVIEW VIEW</Text>
        <Text style={styles.title}>Your design is still unchanged.</Text>
        <Text style={styles.body}>
          This temporary {VIEWS.find((item) => item.id === previewForLineage.view)?.label.toLowerCase()} view came from
          {' '}the selected source revision. Save keeps it beside the design as a derived view;
          it does not replace the active revision.
        </Text>
        {!reviewSourceIsActive && <Notice kind="info" text="This view was created from an earlier revision. Saving it is unavailable, but you can discard it without changing or charging the current design." />}
        <View style={styles.comparisonCard}>
          <Text style={styles.comparisonTitle}>Compare before saving</Text>
          <Text style={styles.comparisonDetail}>
            Check that the full form, setting, and proportions still match the exact source.
          </Text>
          <View style={styles.comparisonRow}>
            {sourceImageUrl !== null && (
              <View style={styles.comparisonPanel}>
                <Text style={styles.comparisonLabel}>Exact source · unchanged</Text>
                <StudioReviewImage
                  accessibilityLabel="Exact source revision"
                  inspectionLabel="Exact source revision"
                  source={{ uri: sourceImageUrl }}
                  imageRequestHeaders={imageRequestHeaders}
                  onLoad={() => visualReview.markReady(sourceVisualKey)}
                  onError={() => visualReview.markFailed(sourceVisualKey)}
                  style={styles.preview}
                />
              </View>
            )}
            <View style={styles.comparisonPanel}>
              <Text style={styles.comparisonLabel}>Candidate · not saved</Text>
              <StudioReviewImage
                accessibilityLabel={`Temporary ${previewForLineage.view} view`}
                inspectionLabel={`Temporary ${previewForLineage.view.replace('_', '-')} view candidate`}
                source={{ uri: previewForLineage.previewUrl }}
                imageRequestHeaders={imageRequestHeaders}
                onLoad={() => visualReview.markReady(candidateVisualKey)}
                onError={() => visualReview.markFailed(candidateVisualKey)}
                style={styles.preview}
              />
            </View>
          </View>
        </View>
        {sourceImageUrl === null && (
          <Notice
            kind="error"
            text="The exact source cannot be displayed, so this view cannot be saved. Reopen the design and compare again."
          />
        )}
        {sourceImageUrl !== null && !comparisonReady && (
          <Notice
            kind="error"
            text={visualReview.anyFailed(comparisonVisualKeys)
              ? 'The exact source or candidate could not be displayed. Generate the view again before saving it.'
              : 'Wait for the exact source and candidate to finish loading before saving this view.'}
          />
        )}
        <View style={styles.reviewCard}>
          <Text style={styles.reviewTitle}>{rejected ? 'This view cannot be saved' : 'Ready for your review'}</Text>
          {previewForLineage.checks.length === 0 ? (
            <Text style={styles.checkDetail}>No individual check details were returned.</Text>
          ) : previewForLineage.checks.map((check) => (
            <View key={check.id} style={styles.checkRow}>
              <Text style={[styles.checkVerdict, check.verdict === 'reject' && styles.reject]}>
                {designerReviewState(check.verdict)}
              </Text>
              <View style={styles.checkCopy}>
                <Text style={styles.checkLabel}>{designerCheckLabel(check)}</Text>
                <Text style={styles.checkDetail}>{designerCheckDetail(check)}</Text>
              </View>
            </View>
          ))}
        </View>
        {visibleNotice !== null && <Notice kind="ok" text={visibleNotice} />}
        {visibleError !== null && <Notice kind="error" text={visibleError} />}
        <View style={styles.actions}>
          <Button title={busy ? 'Working…' : 'Discard'} kind="ghost" disabled={busy} onPress={() => { void discard(); }} />
          <Button
            title={busy ? 'Working…' : 'Save view'}
            disabled={busy || rejected || !reviewSourceIsActive || !comparisonReady}
            onPress={() => { void accept(); }}
          />
        </View>
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
      <Text style={styles.eyebrow}>TECHNICAL VIEWS</Text>
      <Text style={styles.title}>See the confirmed design from another angle.</Text>
      <Text style={styles.body}>
        Choose one line-art angle generated from this revision and its confirmed design facts.
        You will review a temporary result before anything is saved.
      </Text>
      {!reviewSourceIsActive && <Notice kind="info" text="This Activity result was created from an earlier revision. Only its existing preview can be reviewed or discarded." />}
      <View style={styles.viewGrid}>
        {VIEWS.map((item) => (
          <Pressable
            key={item.id}
            accessibilityRole="button"
            accessibilityState={{ selected: view === item.id }}
            onPress={() => setView(item.id)}
            style={[styles.viewCard, view === item.id && styles.selectedCard]}
          >
            <Text style={styles.viewTitle}>{item.label}</Text>
            <Text style={styles.viewDetail}>{item.detail}</Text>
          </Pressable>
        ))}
      </View>
      <View style={styles.sourceCard}>
        <Text style={styles.sourceLabel}>Confirmed saved source</Text>
        <Text style={styles.sourceValue}>Confirmed design · Version {lineage.sourceDesignVersion}</Text>
      </View>
      {visibleNotice !== null && <Notice kind="ok" text={visibleNotice} />}
      {savedForLineage && onOpenCollections !== undefined && (
        <Button title="Open in Collections" kind="ghost" onPress={onOpenCollections} />
      )}
      {visibleError !== null && <Notice kind="error" text={visibleError} />}
      <Text style={styles.creditEstimate}>
        1 requested output × {VIEWS_CREDITS_PER_OUTPUT} credits = estimated {VIEWS_CREDITS_PER_OUTPUT} credits
      </Text>
      <Button title={busy ? 'Creating preview…' : 'Preview view'} disabled={busy || !reviewSourceIsActive} onPress={() => { void createPreview(); }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  workspace: { padding: 22, paddingBottom: 120, gap: 14 },
  empty: { padding: 28, alignItems: 'center', gap: 8 },
  eyebrow: { color: theme.accent, fontSize: 11, fontWeight: '800', letterSpacing: 2 },
  title: { color: theme.ink, fontFamily: theme.serif, fontSize: 28, lineHeight: 34 },
  body: { color: theme.faint, fontSize: 14, lineHeight: 21, maxWidth: 680 },
  creditEstimate: { color: theme.faint, fontSize: 12, lineHeight: 18 },
  viewGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  viewCard: { width: 200, minHeight: 96, borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 14, backgroundColor: theme.card },
  selectedCard: { borderColor: theme.accent, borderWidth: 2 },
  viewTitle: { color: theme.ink, fontWeight: '800', fontSize: 16 },
  viewDetail: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 5 },
  sourceCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 13, backgroundColor: theme.card },
  sourceLabel: { color: theme.faint, fontSize: 11, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 1 },
  sourceValue: { color: theme.ink, fontSize: 13, marginTop: 4 },
  comparisonCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, padding: 14, backgroundColor: theme.card, gap: 6 },
  comparisonTitle: { color: theme.ink, fontSize: 16, fontWeight: '800' },
  comparisonDetail: { color: theme.faint, fontSize: 12, lineHeight: 18 },
  comparisonRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 4 },
  comparisonPanel: { flex: 1, minWidth: 220, maxWidth: 350, gap: 5 },
  comparisonLabel: { color: theme.faint, fontSize: 10, fontWeight: '800', textTransform: 'uppercase' },
  preview: { width: '100%', aspectRatio: 1.25, borderRadius: radius.md, backgroundColor: theme.line },
  reviewCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 14, backgroundColor: theme.card, gap: 8 },
  reviewTitle: { color: theme.ink, fontWeight: '800', fontSize: 16 },
  checkRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  checkVerdict: { color: theme.ok, width: 145, fontSize: 10, lineHeight: 14, fontWeight: '800', textTransform: 'uppercase' },
  reject: { color: theme.danger },
  checkCopy: { flex: 1 },
  checkLabel: { color: theme.ink, fontWeight: '600' },
  checkDetail: { color: theme.faint, fontSize: 12, marginTop: 2 },
  actions: { flexDirection: 'row', flexWrap: 'wrap' },
});
