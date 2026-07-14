import React, { useRef, useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';

import { createClientOperationId } from '../operationId';
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
  onContinueRefining?: () => void;
  onOpenCollections?: () => void;
  createOperationId?: () => string;
}

function defaultOperationId(): string {
  return createClientOperationId('vary');
}

export function StudioVaryWorkspace({
  gateway, lineage, createdBy, onCreated, onContinueRefining, onOpenCollections,
  createOperationId = defaultOperationId,
}: StudioVaryWorkspaceProps) {
  const lineageKey = lineage === null
    ? 'none'
    : `${createdBy}:${lineage.projectId}:${lineage.sourceAssetId}:${lineage.sourceDesignVersion ?? 'none'}`;
  const operationRef = useRef<{ key: string; id: string } | null>(null);
  if (operationRef.current === null) {
    operationRef.current = { key: lineageKey, id: createOperationId() };
  }
  if (operationRef.current.key !== lineageKey) {
    operationRef.current = { key: lineageKey, id: createOperationId() };
  }
  const [labelState, setLabelState] = useState({ key: lineageKey, value: '' });
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [errorState, setErrorState] = useState<{ key: string; message: string } | null>(null);
  const [successState, setSuccessState] = useState<{ key: string; label: string } | null>(null);
  const label = labelState.key === lineageKey ? labelState.value : '';
  const busy = busyKey === lineageKey;
  const error = errorState?.key === lineageKey ? errorState.message : null;
  const createdLabel = successState?.key === lineageKey ? successState.label : null;

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
    const requestLineageKey = lineageKey;
    const operationId = operationRef.current!.id;
    setBusyKey(requestLineageKey);
    setErrorState(null);
    const result = await gateway.saveCurrentAsVariation({
      ...lineage,
      createdBy,
      label: nextLabel,
      operationId,
    });
    if (operationRef.current?.key !== requestLineageKey) return;
    setBusyKey(null);
    if (result.error !== null) {
      setErrorState({
        key: requestLineageKey,
        message: designerErrorMessage(result.error, 'vary'),
      });
      return;
    }
    operationRef.current = { key: requestLineageKey, id: createOperationId() };
    onCreated(result.data.project);
    setSuccessState({ key: requestLineageKey, label: nextLabel });
  };

  if (createdLabel !== null) {
    return (
      <View style={styles.successState}>
        <Text style={styles.eyebrow}>VARIATION SAVED</Text>
        <Text style={styles.title}>{createdLabel} is ready.</Text>
        <Text style={styles.body}>The source direction and its history are unchanged. Continue with this new variation or review the family in Collections.</Text>
        <View style={styles.successActions}>
          {onContinueRefining !== undefined && (
            <Pressable accessibilityRole="button" onPress={onContinueRefining} style={styles.primaryButton}>
              <Text style={styles.primaryButtonText}>Continue refining</Text>
            </Pressable>
          )}
          {onOpenCollections !== undefined && (
            <Pressable accessibilityRole="button" onPress={onOpenCollections} style={styles.secondaryButton}>
              <Text style={styles.secondaryButtonText}>Open Collections</Text>
            </Pressable>
          )}
        </View>
      </View>
    );
  }

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
        onChangeText={(value) => setLabelState({ key: lineageKey, value })}
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
  successState: { padding: 24, backgroundColor: theme.paper, gap: 10 },
  successActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, alignItems: 'center' },
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
  secondaryButton: { alignItems: 'center', borderRadius: radius.pill, borderWidth: 1, borderColor: theme.line, paddingHorizontal: 18, paddingVertical: 14, marginTop: 20 },
  secondaryButtonText: { color: theme.ink, fontSize: 13, fontWeight: '800' },
  disabled: { opacity: 0.42 },
});
