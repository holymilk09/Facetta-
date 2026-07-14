import React, { useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Button, Notice } from '../components';
import { radius, theme } from '../theme';
import { designerErrorMessage } from './designerErrorMessage';
import type {
  StudioDesignConfirmationAudit, StudioDesignConfirmationGateway, StudioDesignConfirmationReview,
  StudioDesignConfirmationReceipt, StudioDesignFactAuthority, StudioVisualLineage,
} from './gateway';

const authorityLabels: Record<StudioDesignFactAuthority, string> = {
  suggested: 'Suggested',
  estimated: 'Estimate',
  designer_supplied: 'Measured or supplied',
};

export interface StudioConfirmWorkspaceProps {
  gateway: StudioDesignConfirmationGateway;
  lineage: StudioVisualLineage | null;
  createdBy: string;
  onSaved: (receipt: StudioDesignConfirmationReceipt) => void;
}

export function StudioConfirmWorkspace({ gateway, lineage, createdBy, onSaved }: StudioConfirmWorkspaceProps) {
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

  const changeFact = (path: string, text: string) => {
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
    <View style={styles.sourceCard}><Text style={styles.sourceLabel}>Starting visual</Text><Text style={styles.sourceValue}>Exact selected visual</Text></View>
    {busy && currentReview === null ? <Text style={styles.body}>Loading design details…</Text> : null}
    {currentReview?.factGroups.map((group, index) => <View key={group.key} style={styles.group}>
      <Text style={styles.groupStep}>{index + 1} · {group.label.toUpperCase()}</Text>
      {group.facts.map((fact) => <View key={fact.key} style={styles.fact}>
        <Text style={styles.fieldLabel}>{fact.label}</Text>
        {fact.path !== null && editingFacts[fact.path] ? <>
          <TextInput
            accessibilityLabel={`Edit ${fact.label}`}
            autoCapitalize="none"
            editable={!busy}
            keyboardType={typeof originalFactsRef.current.get(fact.path)?.rawValue === 'number'
              ? 'decimal-pad' : 'default'}
            onChangeText={(text) => changeFact(fact.path as string, text)}
            style={[styles.factInput, factErrors[fact.path] && styles.factInputError]}
            value={factDrafts[fact.path] ?? String(fact.rawValue)}
          />
          {factErrors[fact.path] ? <Text style={styles.fieldError}>{factErrors[fact.path]}</Text> : null}
        </> : <View style={styles.factValueRow}>
          <Text accessibilityLabel={fact.label} style={styles.factValue}>{fact.value}</Text>
          {fact.path !== null ? <Pressable
            accessibilityLabel={`Edit ${fact.label}`}
            disabled={busy}
            onPress={() => editFact(fact.path as string, fact)}
            style={styles.editButton}>
            <Text style={styles.editButtonText}>Edit</Text>
          </Pressable> : null}
        </View>}
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
  </ScrollView>;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.paper }, content: { maxWidth: 760, width: '100%', alignSelf: 'center', padding: 22, paddingBottom: 100, gap: 14 },
  empty: { padding: 28, gap: 8 }, eyebrow: { color: '#6f52d9', fontSize: 10, fontWeight: '800', letterSpacing: 1.5 },
  title: { color: theme.ink, fontFamily: theme.serif, fontSize: 28, lineHeight: 35 }, body: { color: theme.faint, fontSize: 14, lineHeight: 21 },
  sourceCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, backgroundColor: theme.card, padding: 14 },
  sourceLabel: { color: theme.faint, fontSize: 10, fontWeight: '700', textTransform: 'uppercase' }, sourceValue: { color: theme.ink, fontWeight: '700', marginTop: 5 },
  group: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, padding: 16, gap: 10 },
  groupStep: { color: '#6f52d9', fontSize: 10, fontWeight: '800', letterSpacing: 1.2 }, fact: { borderTopWidth: 1, borderTopColor: theme.line, paddingTop: 10, gap: 7 },
  fieldLabel: { color: theme.ink, fontSize: 12, fontWeight: '700' },
  factValueRow: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: 8 },
  factValue: { color: theme.ink, fontSize: 14 }, authorityBadge: { alignSelf: 'flex-start', color: '#6f52d9', backgroundColor: '#f0ebff', borderRadius: radius.pill, paddingHorizontal: 9, paddingVertical: 5, fontSize: 10, fontWeight: '800' },
  factInput: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.sm, backgroundColor: theme.paper, color: theme.ink, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14 },
  factInputError: { borderColor: '#b42318' }, fieldError: { color: '#b42318', fontSize: 11 },
  editButton: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.pill, paddingHorizontal: 11, paddingVertical: 6 },
  editButtonText: { color: '#6f52d9', fontSize: 11, fontWeight: '800' },
  question: { color: theme.ink, fontSize: 13, lineHeight: 19 }, reviewReason: { color: theme.faint, fontSize: 12 },
  acknowledgement: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 14, backgroundColor: theme.card },
  acknowledgementSelected: { borderColor: '#6f52d9', borderWidth: 2 }, ackMark: { color: '#6f52d9', fontSize: 18, fontWeight: '800' }, ackText: { flex: 1, color: theme.ink, fontSize: 13, lineHeight: 19 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
});
