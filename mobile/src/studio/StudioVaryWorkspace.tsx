import React, { useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';

import { radius, theme } from '../theme';
import type { ProjectDetail } from '../trusted/types';
import type { StudioGateway, StudioVariationRequest } from './gateway';
import { designerErrorMessage } from './designerErrorMessage';

export type StudioVariationLineage = Pick<StudioVariationRequest,
  'projectId' | 'sourceAssetId' | 'sourceDesignVersion'>;

export interface StudioVaryWorkspaceProps {
  gateway: Pick<StudioGateway, 'saveCurrentAsVariation'>;
  lineage: StudioVariationLineage | null;
  createdBy: string;
  onCreated: (project: ProjectDetail) => void;
}

export function StudioVaryWorkspace({
  gateway, lineage, createdBy, onCreated,
}: StudioVaryWorkspaceProps) {
  const [label, setLabel] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (lineage === null) {
    return (
      <View style={styles.empty}>
        <Text style={styles.title}>Choose a saved direction first</Text>
        <Text style={styles.body}>A variation starts from the revision you are currently viewing.</Text>
      </View>
    );
  }

  const create = async (): Promise<void> => {
    const nextLabel = label.trim();
    if (!nextLabel || busy) return;
    setBusy(true);
    setError(null);
    const result = await gateway.saveCurrentAsVariation({
      ...lineage,
      createdBy,
      label: nextLabel,
    });
    setBusy(false);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'vary'));
      return;
    }
    onCreated(result.data.project);
  };

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.content}>
      <Text style={styles.eyebrow}>NEW VARIATION</Text>
      <Text style={styles.title}>Preserve this direction, then explore.</Text>
      <Text style={styles.body}>
        Facetta copies the revision you are viewing into a named sibling. The current direction and its history stay unchanged.
      </Text>
      <View style={styles.sourceCard}>
        <Text style={styles.sourceLabel}>Starting point</Text>
        <Text style={styles.sourceValue}>Current saved revision</Text>
      </View>
      <Text style={styles.fieldLabel}>Variation name</Text>
      <TextInput
        accessibilityLabel="Variation name"
        value={label}
        onChangeText={setLabel}
        placeholder="Rose gold study"
        placeholderTextColor={theme.faint}
        style={styles.input}
      />
      {error !== null && <Text style={styles.error}>{error}</Text>}
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: busy || label.trim().length === 0 }}
        disabled={busy || label.trim().length === 0}
        onPress={create}
        style={[styles.primaryButton, (busy || label.trim().length === 0) && styles.disabled]}>
        <Text style={styles.primaryButtonText}>{busy ? 'Creating…' : 'Create variation'}</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.paper },
  content: { width: '100%', maxWidth: 640, alignSelf: 'center', padding: 20, paddingBottom: 60 },
  empty: { padding: 24, backgroundColor: theme.paper, gap: 8 },
  eyebrow: { color: '#6f52d9', fontSize: 10, fontWeight: '800', letterSpacing: 1.4 },
  title: { color: theme.ink, fontFamily: theme.serif, fontSize: 28, lineHeight: 35, marginTop: 8 },
  body: { color: theme.faint, fontSize: 14, lineHeight: 21, marginTop: 8, maxWidth: 540 },
  sourceCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, backgroundColor: theme.card, padding: 14, marginTop: 22 },
  sourceLabel: { color: theme.faint, fontSize: 10, fontWeight: '700', letterSpacing: 0.7, textTransform: 'uppercase' },
  sourceValue: { color: theme.ink, fontSize: 14, fontWeight: '700', marginTop: 5 },
  fieldLabel: { color: theme.ink, fontSize: 13, fontWeight: '700', marginTop: 20 },
  input: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, backgroundColor: theme.card, color: theme.ink, fontSize: 15, padding: 14, marginTop: 8 },
  error: { color: theme.danger, fontSize: 12, lineHeight: 17, marginTop: 12 },
  primaryButton: { alignItems: 'center', borderRadius: radius.pill, backgroundColor: '#6f52d9', paddingHorizontal: 18, paddingVertical: 14, marginTop: 20 },
  primaryButtonText: { color: '#ffffff', fontSize: 13, fontWeight: '800' },
  disabled: { opacity: 0.42 },
});
