import React, { useEffect, useRef, useState } from 'react';
import {
  Platform, Pressable, ScrollView, StyleSheet, Text, TextInput,
  useWindowDimensions, View,
} from 'react-native';
import { Button, Notice } from '../components';
import { radius, theme } from '../theme';
import type { StudioFactPath } from '../trusted/types';
import { designerErrorMessage } from './designerErrorMessage';
import { reconcileStartingFactQuestions } from './gateway';
import type {
  StudioDesignConfirmationAudit, StudioDesignConfirmationGateway, StudioDesignConfirmationReview,
  StudioDesignConfirmationReceipt, StudioDesignFactAuthority, StudioVisualLineage,
} from './gateway';
import { StudioReviewImage } from './StudioReviewImage';

const authorityLabels: Record<StudioDesignFactAuthority, string> = {
  suggested: 'Suggested',
  estimated: 'Estimate',
  designer_supplied: 'Measured or supplied',
};

const settingStyleOptions = [
  { value: '4_prong_basket', label: '4-prong basket', prongs: 4 },
  { value: '6_prong_basket', label: '6-prong basket', prongs: 6 },
  { value: 'bezel', label: 'Bezel', prongs: null },
  { value: 'semi_bezel', label: 'Semi-bezel', prongs: null },
] as const;

function settingOption(value: string | number) {
  return settingStyleOptions.find((option) => option.value === value);
}

export interface StudioConfirmWorkspaceProps {
  gateway: StudioDesignConfirmationGateway;
  lineage: StudioVisualLineage | null;
  createdBy: string;
  onSaved: (receipt: StudioDesignConfirmationReceipt) => void;
  sourceImageUrl?: string | null;
  imageRequestHeaders?: Readonly<Record<string, string>>;
}

export function StudioConfirmWorkspace({
  gateway, lineage, createdBy, onSaved, sourceImageUrl = null, imageRequestHeaders,
}: StudioConfirmWorkspaceProps) {
  const [review, setReview] = useState<StudioDesignConfirmationReview | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [audit, setAudit] = useState<StudioDesignConfirmationAudit | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingFacts, setEditingFacts] = useState<Record<string, boolean>>({});
  const [factDrafts, setFactDrafts] = useState<Record<string, string>>({});
  const [factErrors, setFactErrors] = useState<Record<string, string>>({});
  const originalFactsRef = useRef(new Map<string, {
    rawValue: string | number;
    value: string;
    authority: StudioDesignFactAuthority;
  }>());
  const lineageKey = lineage === null ? null : `${lineage.projectId}:${lineage.sourceAssetId}`;
  const currentLineageKeyRef = useRef<string | null>(lineageKey);
  currentLineageKeyRef.current = lineageKey;
  const currentReview = loadedFor === lineageKey ? review : null;
  const currentAudit = audit !== null && currentReview !== null
    && audit.review.reviewId === currentReview.reviewId ? audit : null;
  const selectedSettingStyle = currentReview?.factGroups
    .find((group) => group.key === 'setting')?.facts
    .find((fact) => fact.path === 'setting.style')?.rawValue;
  const selectedSettingOption = selectedSettingStyle === undefined
    ? undefined : settingOption(selectedSettingStyle);
  const { width } = useWindowDimensions();
  const isWideReview = Platform.OS === 'web' && width >= 1000;

  useEffect(() => {
    setReview(null);
    setLoadedFor(null);
    setAudit(null);
    setError(null);
    setEditingFacts({});
    setFactDrafts({});
    setFactErrors({});
    originalFactsRef.current = new Map();
    if (lineage === null) {
      setBusy(false);
      return;
    }
    let active = true;
    setBusy(true);
    void gateway.loadDesignConfirmation({ ...lineage, createdBy }).then((result) => {
      if (!active) return;
      setBusy(false);
      if (result.error !== null) setError(designerErrorMessage(result.error, 'confirm'));
      else {
        originalFactsRef.current = new Map(result.data.factGroups.flatMap((group) => (
          group.facts.filter((fact) => fact.path !== null).map((fact) => [
            fact.path as string,
            { rawValue: fact.rawValue, value: fact.value, authority: fact.authority },
          ] as const)
        )));
        setReview(result.data);
        setLoadedFor(`${lineage.projectId}:${lineage.sourceAssetId}`);
      }
    });
    return () => { active = false; };
  }, [createdBy, gateway, lineage?.projectId, lineage?.sourceAssetId]);

  if (lineage === null) return <View style={styles.empty}>
    <Text style={styles.title}>Choose a saved visual first</Text>
    <Text style={styles.body}>Confirm design starts from the exact visual you selected. No dimensions are confirmed from the image.</Text>
  </View>;

  const saveStartingFacts = async () => {
    if (currentReview === null || !currentReview.designerAcknowledged || busy
      || Object.keys(factErrors).length > 0) return;
    const requestLineageKey = lineageKey;
    setBusy(true); setError(null);
    setAudit(null);
    const audited = await gateway.auditDesignConfirmation(currentReview);
    if (currentLineageKeyRef.current !== requestLineageKey) return;
    if (audited.error !== null) {
      setBusy(false);
      setError(designerErrorMessage(audited.error, 'confirm'));
      return;
    }
    setAudit(audited.data);
    if (audited.data.status !== 'pass') {
      setBusy(false);
      return;
    }
    const saved = await gateway.saveDesignConfirmation(audited.data);
    if (currentLineageKeyRef.current !== requestLineageKey) return;
    setBusy(false);
    if (saved.error !== null) setError(designerErrorMessage(saved.error, 'confirm'));
    else onSaved(saved.data);
  };

  const editFact = (
    path: string,
    fact: StudioDesignConfirmationReview['factGroups'][number]['facts'][number],
  ) => {
    setEditingFacts((current) => ({ ...current, [path]: true }));
    setFactDrafts((current) => ({
      ...current,
      [path]: current[path] ?? String(fact.rawValue),
    }));
  };

  const changeFact = (path: StudioFactPath, text: string) => {
    setFactDrafts((current) => ({ ...current, [path]: text }));
    const original = originalFactsRef.current.get(path);
    if (original === undefined) return;
    const trimmed = text.trim();
    const parsed = typeof original.rawValue === 'number' ? Number(trimmed) : trimmed;
    const invalid = trimmed.length === 0
      || (typeof original.rawValue === 'number'
        && (!Number.isFinite(parsed) || typeof parsed !== 'number'));
    if (invalid) {
      setFactErrors((current) => ({ ...current, [path]: 'Enter a valid value.' }));
      setAudit(null);
      return;
    }
    setFactErrors((current) => {
      const next = { ...current };
      delete next[path];
      return next;
    });
    setAudit(null);
    setReview((current) => current === null ? null : {
      ...current,
      unresolvedQuestions: reconcileStartingFactQuestions(
        current.unresolvedQuestions,
        path,
        parsed,
      ),
      factGroups: current.factGroups.map((group) => ({
        ...group,
        facts: group.facts.map((fact) => {
          if (fact.path !== path) return fact;
          const unchanged = parsed === original.rawValue;
          const rawText = String(original.rawValue);
          const suffix = original.value.startsWith(rawText)
            ? original.value.slice(rawText.length)
            : '';
          return {
            ...fact,
            value: unchanged ? original.value : `${parsed}${suffix}`,
            rawValue: parsed,
            authority: unchanged ? original.authority : 'designer_supplied',
          };
        }),
      })),
    });
  };

  return <ScrollView style={styles.root} contentContainerStyle={styles.content}>
    <Text style={styles.eyebrow}>STARTING FACTS</Text>
    <Text style={styles.title}>Review and save starting facts.</Text>
    <Text style={styles.body}>Facetta estimated these facts from the selected jewelry image. Correct anything you know now; unchanged estimates remain estimates. Saving appends a new immutable revision and leaves the earlier revision unchanged. This does not make the design production-ready.</Text>
    <View
      testID={isWideReview ? 'confirm-web-layout' : 'confirm-mobile-layout'}
      style={[styles.reviewLayout, isWideReview && styles.reviewLayoutWide]}>
      <View testID="confirm-selected-visual-panel" style={[
        styles.visualColumn, isWideReview && styles.visualColumnWide,
      ]}>
        <View style={styles.sourceCard}>
          <Text style={styles.sourceLabel}>Starting visual</Text>
          <Text style={styles.sourceValue}>Selected revision preview</Text>
          <Text accessibilityLabel="Selected revision preview notice" style={styles.sourceHelp}>
            Compare every suggested fact with this saved revision before confirming it. The standard
            delivery note is added only to this preview; the stored revision remains unchanged.
          </Text>
          {sourceImageUrl !== null ? (
            <StudioReviewImage
              accessibilityLabel="Selected revision preview used to review starting facts"
              imageRequestHeaders={imageRequestHeaders}
              inspectionLabel="Selected revision preview"
              resizeMode="contain"
              source={{ uri: sourceImageUrl }}
              style={styles.sourceImage}
            />
          ) : (
            <View accessibilityLabel="Exact selected visual unavailable" style={styles.sourceUnavailable}>
              <Text style={styles.sourceUnavailableText}>Selected visual could not be displayed.</Text>
            </View>
          )}
        </View>
      </View>

      <View testID="confirm-facts-panel" style={styles.factsColumn}>
        {busy && currentReview === null ? <Text style={styles.body}>Loading design details…</Text> : null}
        {currentReview?.factGroups.map((group, index) => <View key={group.key} style={styles.group}>
          <Text style={styles.groupStep}>{index + 1} · {group.label.toUpperCase()}</Text>
          {group.facts.map((fact) => <View key={fact.key} style={styles.fact}>
            <Text style={styles.fieldLabel}>{fact.label}</Text>
            {fact.path !== null && editingFacts[fact.path] ? <>
              {fact.path === 'setting.style' ? <View
                accessibilityLabel="Choose setting style"
                style={styles.optionRow}>
                {settingStyleOptions.map((option) => <Pressable
                  key={option.value}
                  accessibilityLabel={`Set Setting to ${option.label}`}
                  accessibilityRole="button"
                  accessibilityState={{ selected: fact.rawValue === option.value }}
                  disabled={busy}
                  onPress={() => {
                    changeFact(fact.path as StudioFactPath, option.value);
                    setEditingFacts((current) => ({ ...current, [fact.path as string]: false }));
                  }}
                  style={[
                    styles.optionButton,
                    fact.rawValue === option.value && styles.optionButtonSelected,
                  ]}>
                  <Text style={[
                    styles.optionButtonText,
                    fact.rawValue === option.value && styles.optionButtonTextSelected,
                  ]}>{option.label}</Text>
                </Pressable>)}
              </View> : <TextInput
                accessibilityLabel={`Edit ${fact.label}`}
                autoCapitalize="none"
                editable={!busy}
                keyboardType={typeof originalFactsRef.current.get(fact.path)?.rawValue === 'number'
                  ? 'decimal-pad' : 'default'}
                onChangeText={(text) => changeFact(fact.path as StudioFactPath, text)}
                style={[styles.factInput, factErrors[fact.path] && styles.factInputError]}
                value={factDrafts[fact.path] ?? String(fact.rawValue)}
              />}
              {factErrors[fact.path] ? <Text style={styles.fieldError}>{factErrors[fact.path]}</Text> : null}
            </> : <View style={styles.factValueRow}>
              <Text accessibilityLabel={fact.label} style={styles.factValue}>{
                fact.key === 'prong_count' && selectedSettingOption !== undefined
                  ? (selectedSettingOption.prongs ?? 'No prongs')
                  : fact.path === 'setting.style'
                    ? (settingOption(fact.rawValue)?.label ?? fact.value)
                    : fact.value
              }</Text>
              {fact.path !== null ? <Pressable
                accessibilityLabel={`Edit ${fact.label}`}
                disabled={busy}
                onPress={() => editFact(fact.path as string, fact)}
                style={styles.editButton}>
                <Text style={styles.editButtonText}>Edit</Text>
              </Pressable> : null}
            </View>}
            {fact.key === 'prong_count' && selectedSettingOption !== undefined
              ? <Text style={styles.factHelp}>Updates automatically with the selected setting.</Text>
              : null}
            <Text style={styles.authorityBadge}>{authorityLabels[fact.authority]}</Text>
          </View>)}
        </View>)}
        {currentReview && <View style={styles.group}>
          <Text style={styles.groupStep}>QUESTIONS KEPT FOR LATER</Text>
          {currentReview.unresolvedQuestions.length === 0 ? <Text style={styles.body}>No unresolved source questions were found.</Text>
            : currentReview.unresolvedQuestions.map((question) => <Text key={question} style={styles.question}>• {question}</Text>)}
          <Text style={styles.body}>These questions do not block Studio creation or refinement. They remain attached to this direction for later review.</Text>
        </View>}
        {currentReview && <Pressable
          accessibilityRole="checkbox"
          accessibilityLabel="I reviewed these starting facts"
          accessibilityState={{ checked: currentReview.designerAcknowledged, disabled: busy }}
          disabled={busy}
          onPress={() => {
            if (busy) return;
            setAudit(null);
            setReview({ ...currentReview, designerAcknowledged: !currentReview.designerAcknowledged });
          }}
          style={[styles.acknowledgement, currentReview.designerAcknowledged && styles.acknowledgementSelected]}>
          <Text style={styles.ackMark}>{currentReview.designerAcknowledged ? '✓' : '○'}</Text>
          <Text style={styles.ackText}>I reviewed these starting facts. Unchanged estimates remain estimates.</Text>
        </Pressable>}
        {currentAudit?.status === 'fail' && <Notice kind="error" text={currentAudit.issues.join(' ')} />}
        {error && <Notice kind="error" text={error} />}
        <View style={styles.actions}>
          <Button title={busy ? 'Saving starting facts…' : 'Save starting facts'} disabled={busy || currentReview === null || !currentReview.designerAcknowledged || Object.keys(factErrors).length > 0} onPress={() => void saveStartingFacts()} />
        </View>
      </View>
    </View>
  </ScrollView>;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.paper }, content: { maxWidth: 1180, width: '100%', alignSelf: 'center', padding: 22, paddingBottom: 100, gap: 14 },
  empty: { padding: 28, gap: 8 }, eyebrow: { color: '#6f52d9', fontSize: 10, fontWeight: '800', letterSpacing: 1.5 },
  title: { color: theme.ink, fontFamily: theme.serif, fontSize: 28, lineHeight: 35 }, body: { color: theme.faint, fontSize: 14, lineHeight: 21, maxWidth: 760 },
  reviewLayout: { width: '100%', gap: 14 },
  reviewLayoutWide: { flexDirection: 'row', alignItems: 'flex-start', gap: 20 },
  visualColumn: { width: '100%' },
  visualColumnWide: { width: 420, flexShrink: 0 },
  factsColumn: { flex: 1, minWidth: 0, gap: 14 },
  sourceCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, backgroundColor: theme.card, padding: 14 },
  sourceLabel: { color: theme.faint, fontSize: 10, fontWeight: '700', textTransform: 'uppercase' }, sourceValue: { color: theme.ink, fontWeight: '700', marginTop: 5 },
  sourceHelp: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 5 },
  sourceImage: { width: '100%', aspectRatio: 1, marginTop: 12, borderRadius: radius.sm, backgroundColor: '#ebe7ef' },
  sourceUnavailable: { width: '100%', aspectRatio: 1, marginTop: 12, alignItems: 'center', justifyContent: 'center', borderRadius: radius.sm, backgroundColor: '#ebe7ef', padding: 18 },
  sourceUnavailableText: { color: theme.faint, fontSize: 12, textAlign: 'center' },
  group: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, padding: 16, gap: 10 },
  groupStep: { color: '#6f52d9', fontSize: 10, fontWeight: '800', letterSpacing: 1.2 }, fact: { borderTopWidth: 1, borderTopColor: theme.line, paddingTop: 10, gap: 7 },
  fieldLabel: { color: theme.ink, fontSize: 12, fontWeight: '700' },
  factValueRow: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: 8 },
  factValue: { color: theme.ink, fontSize: 14 }, authorityBadge: { alignSelf: 'flex-start', color: '#6f52d9', backgroundColor: '#f0ebff', borderRadius: radius.pill, paddingHorizontal: 9, paddingVertical: 5, fontSize: 10, fontWeight: '800' },
  factInput: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.sm, backgroundColor: theme.paper, color: theme.ink, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14 },
  factInputError: { borderColor: '#b42318' }, fieldError: { color: '#b42318', fontSize: 11 },
  factHelp: { color: theme.faint, fontSize: 11, lineHeight: 16 },
  optionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  optionButton: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: theme.paper },
  optionButtonSelected: { borderColor: '#6f52d9', backgroundColor: '#f0ebff' },
  optionButtonText: { color: theme.ink, fontSize: 11, fontWeight: '700' },
  optionButtonTextSelected: { color: '#6f52d9' },
  editButton: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.pill, paddingHorizontal: 11, paddingVertical: 6 },
  editButtonText: { color: '#6f52d9', fontSize: 11, fontWeight: '800' },
  question: { color: theme.ink, fontSize: 13, lineHeight: 19 }, reviewReason: { color: theme.faint, fontSize: 12 },
  acknowledgement: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 14, backgroundColor: theme.card },
  acknowledgementSelected: { borderColor: '#6f52d9', borderWidth: 2 }, ackMark: { color: '#6f52d9', fontSize: 18, fontWeight: '800' }, ackText: { flex: 1, color: theme.ink, fontSize: 13, lineHeight: 19 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
