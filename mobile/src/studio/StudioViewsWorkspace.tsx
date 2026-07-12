import React, { useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, View,
} from 'react-native';
import { AuthenticatedImage as Image } from '../AuthenticatedImage';

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

const VIEWS_CREDITS_PER_OUTPUT = getStudioAction('views').creditEstimate ?? 0;

const VIEWS = [
  { id: 'front', label: 'Front', detail: 'A clear straight-on geometry view.' },
  { id: 'three_quarter', label: 'Three-quarter', detail: 'A dimensional view that keeps the full form readable.' },
  { id: 'side', label: 'Side', detail: 'A profile view for height and setting relationships.' },
] as const;

type ViewId = typeof VIEWS[number]['id'];

export interface StudioViewsWorkspaceProps {
  gateway: Pick<StudioGateway, 'previewLineArtView' | 'acceptLineArtView' | 'discardLineArtView'>;
  lineage: ExactStudioLineage | null;
  createdBy: string;
  onSaved: (project: ProjectDetail) => void;
  imageRequestHeaders?: Readonly<Record<string, string>>;
}

export function StudioViewsWorkspace({
  gateway, lineage, createdBy, onSaved, imageRequestHeaders,
}: StudioViewsWorkspaceProps) {
  const [view, setView] = useState<ViewId>('three_quarter');
  const [preview, setPreview] = useState<StudioViewPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const createPreview = async (): Promise<void> => {
    if (lineage === null || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    const result = await gateway.previewLineArtView({
      ...lineage, createdBy, view,
    });
    setBusy(false);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'views'));
      return;
    }
    setPreview(result.data);
  };

  const accept = async (): Promise<void> => {
    if (preview === null || busy || preview.verdict === 'fail') return;
    setBusy(true);
    setError(null);
    const result = await gateway.acceptLineArtView({
      candidateId: preview.candidateId, createdBy,
    });
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
    setNotice('View saved beside the design. The active design revision did not change.');
    onSaved(result.data.project);
  };

  const discard = async (): Promise<void> => {
    if (preview === null || busy) return;
    setBusy(true);
    setError(null);
    const result = await gateway.discardLineArtView({
      candidateId: preview.candidateId, createdBy,
    });
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

  if (preview !== null) {
    const rejected = preview.verdict === 'fail';
    return (
      <ScrollView contentContainerStyle={styles.workspace}>
        <Text style={styles.eyebrow}>REVIEW VIEW</Text>
        <Text style={styles.title}>Your design is still unchanged.</Text>
        <Text style={styles.body}>
          This temporary {VIEWS.find((item) => item.id === preview.view)?.label.toLowerCase()} view came from
          {' '}the selected source revision. Save keeps it beside the design as a derived view;
          it does not replace the active revision.
        </Text>
        <Image
          accessibilityLabel={`Temporary ${preview.view} view`}
          source={{ uri: preview.previewUrl }}
          imageRequestHeaders={imageRequestHeaders}
          style={styles.preview}
        />
        <View style={styles.reviewCard}>
          <Text style={styles.reviewTitle}>{rejected ? 'This view cannot be saved' : 'Ready for your review'}</Text>
          {preview.checks.length === 0 ? (
            <Text style={styles.checkDetail}>No individual check details were returned.</Text>
          ) : preview.checks.map((check) => (
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
        {error !== null && <Notice kind="error" text={error} />}
        <View style={styles.actions}>
          <Button title={busy ? 'Working…' : 'Discard'} kind="ghost" disabled={busy} onPress={() => { void discard(); }} />
          <Button title={busy ? 'Working…' : 'Save view'} disabled={busy || rejected} onPress={() => { void accept(); }} />
        </View>
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
      <Text style={styles.eyebrow}>VIEWS</Text>
      <Text style={styles.title}>See the same design from another angle.</Text>
      <Text style={styles.body}>
        Choose one useful technical view. You will review a temporary result before anything is saved.
      </Text>
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
        <Text style={styles.sourceLabel}>Exact source</Text>
        <Text style={styles.sourceValue}>Confirmed revision {lineage.sourceDesignVersion}</Text>
      </View>
      {notice !== null && <Notice kind="ok" text={notice} />}
      {error !== null && <Notice kind="error" text={error} />}
      <Text style={styles.creditEstimate}>
        1 requested output × {VIEWS_CREDITS_PER_OUTPUT} credits = estimated {VIEWS_CREDITS_PER_OUTPUT} credits
      </Text>
      <Button title={busy ? 'Creating preview…' : 'Preview view'} disabled={busy} onPress={() => { void createPreview(); }} />
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
  preview: { width: '100%', maxWidth: 720, aspectRatio: 1.25, borderRadius: radius.lg, backgroundColor: theme.line },
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
