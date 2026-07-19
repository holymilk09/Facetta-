import React, { useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { radius, theme } from '../theme';
import type {
  ProjectDetail, StudioContinuationPrompt, StudioContinuationPromptState,
} from '../trusted/types';

export interface StudioPromptHistoryEntry {
  id: string;
  prompt: string;
  revision: number | null;
  state: StudioContinuationPromptState | 'initial' | 'legacy_saved';
}

export interface StudioPromptHistoryProps {
  project: ProjectDetail | null;
  /** Raw append-only designer prompts. Null means the legacy endpoint is unavailable. */
  continuationPrompts?: readonly StudioContinuationPrompt[] | null;
  previewPrompt?: string | null;
  onStartNewDesign?: () => void;
  compact?: boolean;
}

const NON_DESIGN_INSTRUCTIONS = [
  /^saved reviewed candidate as variation/i,
  /^saved as variation from/i,
  /^restored from revision asset/i,
  /^selected this reviewed create direction as original/i,
];

function designerPrompt(value: string | null): string | null {
  const prompt = value?.trim() ?? '';
  if (prompt.length === 0 || NON_DESIGN_INSTRUCTIONS.some((pattern) => pattern.test(prompt))) {
    return null;
  }
  return prompt;
}

/**
 * New projects use the append-only raw prompt ledger. The revision-derived
 * path remains only as a compatibility reader for projects saved before that
 * ledger existed; it must never replace available raw prompt records.
 */
export function studioPromptHistory(
  project: ProjectDetail | null,
  continuationPrompts: readonly StudioContinuationPrompt[] | null = null,
): StudioPromptHistoryEntry[] {
  if (project === null) return [];
  const ordered = [...project.revisions].sort((left, right) => left.revision - right.revision);

  if (continuationPrompts !== null) {
    const sequenced: Array<{ entry: StudioPromptHistoryEntry; order: number; tie: number }> = [];
    const initial = ordered.find((revision) => designerPrompt(revision.asset.instruction) !== null);
    const initialPrompt = designerPrompt(initial?.asset.instruction ?? null);
    if (initial !== undefined && initialPrompt !== null) {
      sequenced.push({
        entry: {
          id: `initial:${initial.asset.asset_id}`,
          prompt: initialPrompt,
          revision: initial.revision,
          state: 'initial',
        },
        order: initial.revision,
        tie: 0,
      });
    }
    const ledgerAssetIds = new Set(continuationPrompts.flatMap((prompt) => (
      prompt.applied_asset_id === null ? [] : [prompt.applied_asset_id]
    )));
    [...continuationPrompts]
      .sort((left, right) => left.sequence - right.sequence)
      .forEach((continuation) => {
        const appliedRevision = continuation.applied_asset_id === null
          ? null
          : ordered.find(
            (revision) => revision.asset.asset_id === continuation.applied_asset_id,
          )?.revision ?? null;
        sequenced.push({
          entry: {
            id: continuation.prompt_id,
            prompt: continuation.prompt,
            revision: appliedRevision,
            state: continuation.state,
          },
          order: appliedRevision ?? Number.MAX_SAFE_INTEGER,
          tie: continuation.sequence,
        });
      });
    // Exact-spec markup revisions predate the continuation ledger integration.
    // Merge only revision instructions that have no ledger-owned applied asset;
    // this preserves those designer prompts without exposing the compiled text
    // already replaced by a raw continuation row.
    ordered.forEach((revision) => {
      if (revision.asset.asset_id === initial?.asset.asset_id
        || ledgerAssetIds.has(revision.asset.asset_id)) return;
      const prompt = designerPrompt(revision.asset.instruction);
      if (prompt === null) return;
      sequenced.push({
        entry: {
          id: revision.asset.asset_id,
          prompt,
          revision: revision.revision,
          state: 'legacy_saved',
        },
        order: revision.revision,
        tie: 1,
      });
    });
    return sequenced
      .sort((left, right) => left.order - right.order || left.tie - right.tie)
      .map(({ entry }) => entry);
  }

  const entries: StudioPromptHistoryEntry[] = [];
  ordered.forEach((revision) => {
    const prompt = designerPrompt(revision.asset.instruction);
    if (prompt === null || entries.at(-1)?.prompt === prompt) return;
    entries.push({
      id: revision.asset.asset_id,
      prompt,
      revision: revision.revision,
      state: 'legacy_saved',
    });
  });
  if (entries.length === 0) {
    const prompt = designerPrompt(project.active_revision?.instruction ?? null);
    if (prompt !== null && project.active_revision !== null) {
      entries.push({
        id: project.active_revision.asset_id,
        prompt,
        revision: project.active_revision.revision,
        state: 'legacy_saved',
      });
    }
  }
  return entries;
}

export function StudioPromptHistory({
  project, continuationPrompts = null, previewPrompt = null, onStartNewDesign, compact = false,
}: StudioPromptHistoryProps) {
  const entries = useMemo(
    () => studioPromptHistory(project, continuationPrompts),
    [continuationPrompts, project],
  );
  const [expanded, setExpanded] = useState(true);
  const temporaryPrompt = previewPrompt?.trim() ?? '';
  const temporaryAlreadyRecorded = entries.some((entry) => (
    entry.prompt === temporaryPrompt
      && (entry.state === 'requested' || entry.state === 'preview_ready')
  ));
  if (entries.length === 0 && temporaryPrompt.length === 0) return null;

  const statusText = (entry: StudioPromptHistoryEntry): string => {
    if (entry.state === 'initial') return `Started in Revision ${entry.revision ?? 1}`;
    if (entry.state === 'applied') {
      return entry.revision === null ? 'Applied as a saved revision' : `Saved in Revision ${entry.revision}`;
    }
    if (entry.state === 'saved_as_variation') return 'Saved as a separate variation';
    if (entry.state === 'discarded') return 'Discarded · no revision saved';
    if (entry.state === 'failed') return 'Could not generate · no revision saved';
    if (entry.state === 'requested') return 'Requested · generation in progress';
    if (entry.state === 'preview_ready') return 'Temporary preview · apply to save';
    return entry.revision === null ? 'Saved prompt' : `Saved in Revision ${entry.revision}`;
  };

  return (
    <View accessibilityLabel="Design prompt history" style={[styles.card, compact && styles.compactCard]}>
      <View style={styles.header}>
        <View style={styles.headerCopy}>
          <Text style={styles.eyebrow}>DESIGN HISTORY</Text>
          <Text style={styles.title}>Prompt history</Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={expanded ? 'Hide design prompt history' : 'Show design prompt history'}
          accessibilityState={{ expanded }}
          onPress={() => setExpanded((current) => !current)}
          style={styles.toggle}>
          <Text style={styles.toggleText}>{expanded ? 'Hide' : `${entries.length} step${entries.length === 1 ? '' : 's'}`}</Text>
        </Pressable>
      </View>
      <Text style={styles.help}>
        Your next edit continues from the exact saved image. Starting a separate idea is always optional.
      </Text>

      {expanded && (
        <View style={styles.timeline}>
          {entries.map((entry, index) => (
            <View key={entry.id} style={styles.step}>
              <View style={styles.stepNumber}>
                <Text style={styles.stepNumberText}>{index + 1}</Text>
              </View>
              <View style={styles.stepCopy}>
                <Text style={styles.stepLabel}>{entry.state === 'initial' || index === 0
                  ? 'STARTED WITH' : 'THEN REQUESTED'}</Text>
                <Text style={styles.prompt}>{entry.prompt}</Text>
                <Text style={styles.revisionLabel}>{statusText(entry)}</Text>
              </View>
            </View>
          ))}
          {temporaryPrompt.length > 0 && !temporaryAlreadyRecorded && (
            <View style={styles.step}>
              <View style={[styles.stepNumber, styles.temporaryNumber]}>
                <Text style={styles.temporaryNumberText}>{entries.length + 1}</Text>
              </View>
              <View style={styles.stepCopy}>
                <Text style={styles.temporaryLabel}>TEMPORARY PREVIEW</Text>
                <Text style={styles.prompt}>{temporaryPrompt}</Text>
                <Text style={styles.revisionLabel}>Apply to save this as the next revision.</Text>
              </View>
            </View>
          )}
        </View>
      )}

      {onStartNewDesign !== undefined && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Start a separate design"
          onPress={onStartNewDesign}
          style={styles.newDesignButton}>
          <Text style={styles.newDesignText}>Start a separate design</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    width: '100%',
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.lg,
    backgroundColor: theme.card,
    padding: 16,
  },
  compactCard: { padding: 14 },
  header: { alignItems: 'flex-start', flexDirection: 'row', gap: 10, justifyContent: 'space-between' },
  headerCopy: { flex: 1 },
  eyebrow: { color: '#6f52d9', fontSize: 9, fontWeight: '800', letterSpacing: 1.2 },
  title: { color: theme.ink, fontFamily: theme.serif, fontSize: 19, lineHeight: 24, marginTop: 4 },
  help: { color: theme.faint, fontSize: 10, lineHeight: 15, marginTop: 5 },
  toggle: { minHeight: 36, justifyContent: 'center', paddingHorizontal: 6 },
  toggleText: { color: '#5c3fc0', fontSize: 10, fontWeight: '800' },
  timeline: { gap: 13, marginTop: 15 },
  step: { alignItems: 'flex-start', flexDirection: 'row', gap: 10 },
  stepNumber: {
    width: 24,
    height: 24,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 12,
    backgroundColor: '#eee9ff',
  },
  stepNumberText: { color: '#5c3fc0', fontSize: 10, fontWeight: '800' },
  temporaryNumber: { backgroundColor: '#fff6de', borderWidth: 1, borderColor: '#dec681' },
  temporaryNumberText: { color: '#83631b', fontSize: 10, fontWeight: '800' },
  stepCopy: { flex: 1, minWidth: 0 },
  stepLabel: { color: theme.faint, fontSize: 8, fontWeight: '800', letterSpacing: 0.8 },
  temporaryLabel: { color: '#83631b', fontSize: 8, fontWeight: '800', letterSpacing: 0.8 },
  prompt: { color: theme.ink, fontSize: 11, lineHeight: 16, marginTop: 2 },
  revisionLabel: { color: theme.faint, fontSize: 8, lineHeight: 12, marginTop: 3 },
  newDesignButton: {
    alignSelf: 'flex-start',
    minHeight: 36,
    justifyContent: 'center',
    marginTop: 14,
    paddingHorizontal: 2,
  },
  newDesignText: { color: '#5c3fc0', fontSize: 10, fontWeight: '800' },
});
