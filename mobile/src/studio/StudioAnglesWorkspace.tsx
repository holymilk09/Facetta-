import React, { useEffect, useRef, useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, View,
} from 'react-native';

import { Notice } from '../components';
import { radius, theme } from '../theme';
import type { ProjectDetail, VisualAngleView } from '../trusted/types';
import { designerErrorMessage } from './designerErrorMessage';
import type {
  StudioGateway, StudioVisualAngleSetReview, StudioVisualLineage,
} from './gateway';
import { StudioReviewImage } from './StudioReviewImage';
import { useVisualReviewReadiness } from './useVisualReviewReadiness';

const ANGLES = [
  { id: 'front', label: 'Front', detail: 'Straight-on silhouette and setting.' },
  { id: 'three_quarter', label: 'Three-quarter', detail: 'Depth and overall form.' },
  { id: 'side', label: 'Side', detail: 'Profile and setting height.' },
] as const satisfies readonly {
  id: VisualAngleView;
  label: string;
  detail: string;
}[];

const OUTPUT_COUNT = 3;
const CREDITS_PER_OUTPUT = 18;

export interface StudioAnglesWorkspaceProps {
  gateway: Pick<StudioGateway,
    | 'createVisualAngleSet'
    | 'resumeVisualAngleSet'
    | 'acceptVisualAngleSet'
    | 'discardVisualAngleSet'>
    & Partial<Pick<StudioGateway, 'assetImageUrl'>>;
  lineage: StudioVisualLineage | null;
  createdBy: string;
  onSaved: (project: ProjectDetail) => void;
  onContinueRefining?: () => void;
  onOpenCollections?: () => void;
  imageRequestHeaders?: Readonly<Record<string, string>>;
  resumeReviewJobId?: string;
  reviewSourceIsActive?: boolean;
}

export function StudioAnglesWorkspace({
  gateway,
  lineage,
  createdBy,
  onSaved,
  onContinueRefining,
  onOpenCollections,
  imageRequestHeaders,
  resumeReviewJobId,
  reviewSourceIsActive = true,
}: StudioAnglesWorkspaceProps) {
  const [review, setReview] = useState<StudioVisualAngleSetReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const lineageKey = lineage === null
    ? 'none' : `${lineage.projectId}:${lineage.sourceAssetId}`;
  const lineageKeyRef = useRef(lineageKey);
  lineageKeyRef.current = lineageKey;
  const sourceImageUrl = lineage === null || typeof gateway.assetImageUrl !== 'function'
    ? null : gateway.assetImageUrl(lineage.sourceAssetId);
  const reviewForLineage = review !== null && lineage !== null
    && review.lineage.projectId === lineage.projectId
    && review.lineage.sourceAssetId === lineage.sourceAssetId
    ? review : null;
  const visualScope = `${lineageKey}:${reviewForLineage?.angleSetId ?? 'configure'}`;
  const visualReview = useVisualReviewReadiness(visualScope);
  const sourceVisualKey = sourceImageUrl === null
    ? null : `angles-source:${lineage?.sourceAssetId ?? 'none'}:${sourceImageUrl}`;
  const candidateVisualKeys = reviewForLineage?.candidates.map((candidate) => (
    `angles-candidate:${candidate.candidate_id}:${candidate.preview_url}`
  )) ?? [];
  const requiredVisualKeys = sourceVisualKey === null
    ? candidateVisualKeys : [sourceVisualKey, ...candidateVisualKeys];
  const allVisualsReady = visualReview.allReady(requiredVisualKeys);
  const anyVisualFailed = visualReview.anyFailed(requiredVisualKeys);

  useEffect(() => {
    setReview(null);
    setBusy(false);
    setError(null);
    setNotice(null);
    if (lineage === null) return undefined;
    const requestedLineageKey = lineageKey;
    let active = true;
    void gateway.resumeVisualAngleSet(lineage, createdBy, resumeReviewJobId).then((result) => {
      if (!active || lineageKeyRef.current !== requestedLineageKey) return;
      if (result.error !== null) {
        setError(designerErrorMessage(result.error, 'angles'));
        return;
      }
      if (result.data !== null) {
        setReview(result.data);
        setNotice('Your unfinished three-angle review was restored.');
      }
    });
    return () => { active = false; };
  }, [createdBy, gateway, lineageKey, resumeReviewJobId]);

  const generate = async (): Promise<void> => {
    if (lineage === null || busy || !reviewSourceIsActive) return;
    const requestedLineageKey = lineageKey;
    setBusy(true);
    setError(null);
    setNotice(null);
    const result = await gateway.createVisualAngleSet(lineage, createdBy);
    if (lineageKeyRef.current !== requestedLineageKey) return;
    setBusy(false);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'angles'));
      return;
    }
    setReview(result.data);
  };

  const save = async (): Promise<void> => {
    if (reviewForLineage === null || busy || !reviewSourceIsActive || !allVisualsReady) return;
    const requestedLineageKey = lineageKey;
    setBusy(true);
    setError(null);
    const result = await gateway.acceptVisualAngleSet(reviewForLineage.angleSetId, createdBy);
    if (lineageKeyRef.current !== requestedLineageKey) return;
    setBusy(false);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'angles'));
      return;
    }
    if (result.data.project === null) {
      setError('The angle set was not saved. Your selected design remains unchanged.');
      return;
    }
    setReview(result.data.review);
    setNotice('All three views were saved beside the design. The selected design did not change.');
    onSaved(result.data.project);
  };

  const discard = async (): Promise<void> => {
    if (reviewForLineage === null || busy) return;
    const requestedLineageKey = lineageKey;
    setBusy(true);
    setError(null);
    const result = await gateway.discardVisualAngleSet(reviewForLineage.angleSetId, createdBy);
    if (lineageKeyRef.current !== requestedLineageKey) return;
    setBusy(false);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'angles'));
      return;
    }
    setReview(null);
    setNotice('Angle set discarded. Nothing was saved or charged.');
  };

  if (lineage === null) {
    return (
      <View style={styles.empty}>
        <Text style={styles.title}>Choose a design first</Text>
        <Text style={styles.body}>Angle views start after you select one generated design.</Text>
      </View>
    );
  }

  if (reviewForLineage?.status === 'accepted') {
    return (
      <ScrollView contentContainerStyle={styles.workspace}>
        <Text style={styles.eyebrow}>VIEWS SAVED</Text>
        <Text style={styles.title}>Your three views are ready.</Text>
        <Text style={styles.body}>
          Front, three-quarter, and side were saved beside this design. They did not replace it.
        </Text>
        {notice !== null && <Notice kind="ok" text={notice} />}
        <View style={styles.angleGrid}>
          {reviewForLineage.candidates.map((candidate) => {
            const angle = ANGLES.find((item) => item.id === candidate.view)!;
            const acceptedUrl = candidate.accepted_asset_id !== null
              && typeof gateway.assetImageUrl === 'function'
              ? gateway.assetImageUrl(candidate.accepted_asset_id)
              : null;
            return (
              <View key={candidate.candidate_id} style={styles.angleCard}>
                {acceptedUrl === null ? (
                  <View style={[styles.angleImage, styles.savedImageFallback]}>
                    <Text style={styles.cardDetail}>Saved view available in Collections</Text>
                  </View>
                ) : (
                  <StudioReviewImage
                    accessibilityLabel={`${angle.label} saved view`}
                    imageRequestHeaders={imageRequestHeaders}
                    inspectionLabel={`${angle.label} saved view`}
                    source={{ uri: acceptedUrl }}
                    style={styles.angleImage}
                  />
                )}
                <Text style={styles.cardTitle}>{angle.label}</Text>
                <Text style={styles.cardDetail}>{angle.detail}</Text>
              </View>
            );
          })}
        </View>
        <View style={styles.actionRow}>
          {onContinueRefining !== undefined && (
            <ActionButton label="Refine this design" onPress={onContinueRefining} />
          )}
          {onOpenCollections !== undefined && (
            <ActionButton label="View in Collections" kind="secondary" onPress={onOpenCollections} />
          )}
        </View>
      </ScrollView>
    );
  }

  if (reviewForLineage !== null) {
    return (
      <ScrollView contentContainerStyle={styles.workspace}>
        <Text style={styles.eyebrow}>REVIEW THREE VIEWS</Text>
        <Text style={styles.title}>Check the design from three key angles.</Text>
        <Text style={styles.body}>
          These are temporary visual studies. Save all three only when the jewelry still matches
          {' '}your selected design.
        </Text>
        {!reviewSourceIsActive && (
          <Notice kind="info" text="These views came from an earlier design. You can discard them, but saving is unavailable." />
        )}
        {sourceImageUrl === null && (
          <Notice kind="error" text="The selected design cannot be displayed, so these views cannot be saved." />
        )}
        {sourceImageUrl !== null && (
          <View style={styles.sourceCard}>
            <Text style={styles.cardTitle}>Selected design</Text>
            <StudioReviewImage
              accessibilityLabel="Selected design source"
              imageRequestHeaders={imageRequestHeaders}
              inspectionLabel="Selected design source"
              onError={() => visualReview.markFailed(sourceVisualKey)}
              onLoad={() => visualReview.markReady(sourceVisualKey)}
              source={{ uri: sourceImageUrl }}
              style={styles.sourceImage}
            />
          </View>
        )}
        <View style={styles.angleGrid}>
          {reviewForLineage.candidates.map((candidate) => {
            const angle = ANGLES.find((item) => item.id === candidate.view)!;
            const visualKey = `angles-candidate:${candidate.candidate_id}:${candidate.preview_url}`;
            return (
              <View key={candidate.candidate_id} style={styles.angleCard}>
                <StudioReviewImage
                  accessibilityLabel={`${angle.label} angle preview`}
                  imageRequestHeaders={imageRequestHeaders}
                  inspectionLabel={`${angle.label} angle preview`}
                  onError={() => visualReview.markFailed(visualKey)}
                  onLoad={() => visualReview.markReady(visualKey)}
                  source={{ uri: candidate.preview_url }}
                  style={styles.angleImage}
                />
                <Text style={styles.cardTitle}>{angle.label}</Text>
                <Text style={styles.cardDetail}>{angle.detail}</Text>
              </View>
            );
          })}
        </View>
        {anyVisualFailed && (
          <Notice kind="error" text="One or more images could not be displayed. Reopen this review before saving." />
        )}
        {error !== null && <Notice kind="error" text={error} />}
        <Text style={styles.creditLine}>
          3 views × {reviewForLineage.creditsPerOutput} credits = {reviewForLineage.estimatedCredits} credits when saved
        </Text>
        <Text style={styles.billingNote}>Discarding this set costs 0 credits.</Text>
        <View style={styles.actionRow}>
          <ActionButton
            disabled={busy || !reviewSourceIsActive || sourceImageUrl === null || !allVisualsReady}
            label={busy ? 'Saving views…' : 'Save all 3 views'}
            onPress={() => { void save(); }}
          />
          <ActionButton
            disabled={busy}
            kind="secondary"
            label="Discard set"
            onPress={() => { void discard(); }}
          />
        </View>
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
      <Text style={styles.eyebrow}>VIEWS</Text>
      <Text style={styles.title}>Create all three useful views.</Text>
      <Text style={styles.body}>
        One tap creates a matched front, three-quarter, and side set from your selected direction.
        {' '}Your design stays unchanged until you review and save the set.
      </Text>
      <View style={styles.includedCard}>
        <Text style={styles.includedTitle}>Included in this set</Text>
        {ANGLES.map((angle) => (
          <View key={angle.id} style={styles.includedRow}>
            <Text style={styles.includedLabel}>{angle.label}</Text>
            <Text style={styles.includedDetail}>{angle.detail}</Text>
          </View>
        ))}
      </View>
      {!reviewSourceIsActive && (
        <Notice kind="info" text="Choose the current selected design before generating new angle views." />
      )}
      {notice !== null && <Notice kind="info" text={notice} />}
      {error !== null && <Notice kind="error" text={error} />}
      <Text style={styles.creditLine}>
        {OUTPUT_COUNT} views × {CREDITS_PER_OUTPUT} credits = {OUTPUT_COUNT * CREDITS_PER_OUTPUT} credits
      </Text>
      <Text style={styles.billingNote}>
        You are charged only if you save all three. Failed generation, quality retries, and discard cost 0 credits.
      </Text>
      <View style={styles.actionRow}>
        <ActionButton
          disabled={busy || !reviewSourceIsActive}
          label={busy ? 'Creating 3 views…' : 'Create all 3 views'}
          onPress={() => { void generate(); }}
        />
        {onContinueRefining !== undefined && (
          <ActionButton
            disabled={busy}
            kind="secondary"
            label="Skip for now"
            onPress={onContinueRefining}
          />
        )}
      </View>
    </ScrollView>
  );
}

function ActionButton({
  disabled = false,
  kind = 'primary',
  label,
  onPress,
}: {
  disabled?: boolean;
  kind?: 'primary' | 'secondary';
  label: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={[
        styles.button,
        kind === 'secondary' && styles.buttonSecondary,
        disabled && styles.buttonDisabled,
      ]}>
      <Text style={[
        styles.buttonText,
        kind === 'secondary' && styles.buttonSecondaryText,
      ]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  workspace: { padding: 20, paddingBottom: 80, gap: 14 },
  empty: { padding: 24, gap: 8 },
  eyebrow: { color: '#6f52d9', fontSize: 11, fontWeight: '800', letterSpacing: 1.8 },
  title: { color: theme.ink, fontFamily: theme.serif, fontSize: 32, lineHeight: 39 },
  body: { color: theme.faint, fontSize: 15, lineHeight: 23, maxWidth: 760 },
  includedCard: {
    borderColor: theme.line,
    borderRadius: radius.lg,
    borderWidth: 1,
    backgroundColor: theme.card,
    overflow: 'hidden',
  },
  includedTitle: {
    color: theme.ink,
    fontSize: 14,
    fontWeight: '800',
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 8,
  },
  includedRow: {
    borderTopColor: theme.line,
    borderTopWidth: 1,
    paddingHorizontal: 16,
    paddingVertical: 12,
    gap: 3,
  },
  includedLabel: { color: theme.ink, fontSize: 14, fontWeight: '800' },
  includedDetail: { color: theme.faint, fontSize: 12, lineHeight: 17 },
  sourceCard: {
    borderColor: theme.line,
    borderRadius: radius.lg,
    borderWidth: 1,
    backgroundColor: theme.card,
    padding: 12,
    gap: 8,
  },
  sourceImage: { width: '100%', height: 220, borderRadius: radius.md, backgroundColor: '#f2f0eb' },
  angleGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  angleCard: {
    flexGrow: 1,
    flexBasis: 220,
    minWidth: 190,
    borderColor: theme.line,
    borderRadius: radius.lg,
    borderWidth: 1,
    backgroundColor: theme.card,
    padding: 10,
    gap: 5,
  },
  angleImage: { width: '100%', height: 230, borderRadius: radius.md, backgroundColor: '#f2f0eb' },
  savedImageFallback: { alignItems: 'center', justifyContent: 'center', padding: 16 },
  cardTitle: { color: theme.ink, fontSize: 15, fontWeight: '800' },
  cardDetail: { color: theme.faint, fontSize: 12, lineHeight: 17 },
  creditLine: { color: theme.ink, fontSize: 14, fontWeight: '700', marginTop: 4 },
  billingNote: { color: theme.faint, fontSize: 12, lineHeight: 18 },
  actionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  button: {
    minHeight: 50,
    flexGrow: 1,
    minWidth: 220,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.pill,
    backgroundColor: '#6f52d9',
    paddingHorizontal: 18,
    paddingVertical: 13,
  },
  buttonSecondary: {
    flexGrow: 0,
    borderColor: theme.line,
    borderWidth: 1,
    backgroundColor: theme.card,
  },
  buttonDisabled: { opacity: 0.42 },
  buttonText: { color: '#ffffff', fontSize: 14, fontWeight: '800' },
  buttonSecondaryText: { color: theme.ink },
});
