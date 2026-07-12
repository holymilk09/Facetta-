import React, { useMemo, useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';
import { AuthenticatedImage as Image } from '../AuthenticatedImage';

import type { StudioGateway } from './gateway';
import type { ReferenceRole } from './contracts';
import type { AssetSummary, ProjectDetail } from '../trusted/types';
import { radius, theme } from '../theme';
import { designerErrorMessage } from './designerErrorMessage';

export type CreateReferenceRole = Extract<ReferenceRole,
  'master_geometry' | 'material_style' | 'construction_detail' | 'brand_direction'>;
type SecondaryCreateReferenceRole = Exclude<CreateReferenceRole, 'master_geometry'>;

export interface StudioCreateReference {
  id: string;
  role: CreateReferenceRole;
  label: string;
  imageBase64: string;
  mediaType: 'image/png' | 'image/jpeg' | 'image/webp';
}

export interface StudioCreateSelection {
  project: ProjectDetail;
  selectedAssetId: string;
  sentence: string;
  references: readonly StudioCreateReference[];
}

export interface StudioCreateWorkspaceProps {
  gateway: Pick<StudioGateway,
    'createFromPrompt' | 'createFromDrawing' | 'selectCreativeDirection'
  >;
  owner: string;
  initialSentence?: string;
  initialReferences?: readonly StudioCreateReference[];
  onRequestReference?: (
    role: CreateReferenceRole,
  ) => StudioCreateReference | null | Promise<StudioCreateReference | null>;
  onSave: (selection: StudioCreateSelection) => void;
}

const ROLES: readonly { role: CreateReferenceRole; label: string; help: string }[] = [
  { role: 'master_geometry', label: 'Master geometry', help: 'The source design whose visible form must be preserved.' },
  { role: 'material_style', label: 'Material & style', help: 'Surface, color, and finish only—not jewelry geometry.' },
  { role: 'construction_detail', label: 'Construction detail', help: 'Visual guidance for one detail, not a confirmed production fact.' },
  { role: 'brand_direction', label: 'Brand direction', help: 'Mood and visual language only—not product geometry or branding to copy.' },
] as const;

const labelForRole = (role: CreateReferenceRole) => (
  ROLES.find((item) => item.role === role)?.label ?? role
);

export function creativeCandidates(project: ProjectDetail): readonly AssetSummary[] {
  const revisions = project.revisions
    .map((revision) => revision.asset)
    .filter((asset) => asset.capability === 'CREATIVE_RENDER');
  if (revisions.length > 0) return revisions;
  return project.active_revision === null ? [] : [project.active_revision];
}

export function StudioCreateWorkspace({
  gateway,
  owner,
  initialSentence = '',
  initialReferences = [],
  onRequestReference,
  onSave,
}: StudioCreateWorkspaceProps) {
  const [sentence, setSentence] = useState(initialSentence);
  const [references, setReferences] = useState<StudioCreateReference[]>([...initialReferences]);
  const [candidateCount, setCandidateCount] = useState<1 | 2 | 3 | 4>(2);
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const candidates = useMemo(() => project === null ? [] : creativeCandidates(project), [project]);
  const masterReference = references.find((reference) => reference.role === 'master_geometry') ?? null;
  const secondaryReferences = references.filter(
    (reference): reference is StudioCreateReference & { role: SecondaryCreateReferenceRole } => (
      reference.role !== 'master_geometry'
    ),
  );
  const canCreate = !busy && (sentence.trim().length > 0 || masterReference !== null)
    && !(masterReference === null && secondaryReferences.length > 0);

  const requestReference = async (role: CreateReferenceRole) => {
    setError(null);
    if (onRequestReference === undefined) {
      setError('Image selection is unavailable here. You can continue with a sentence or try again on a supported device.');
      return;
    }
    try {
      const reference = await onRequestReference(role);
      if (reference === null) return;
      setReferences((current) => [
        ...current.filter((item) => item.role !== role),
        { ...reference, role },
      ]);
    } catch (cause) {
      setError(cause instanceof Error
        ? cause.message
        : 'The selected image could not be added. Choose another file and try again.');
    }
  };

  const create = async () => {
    const prompt = sentence.trim();
    if ((!prompt && masterReference === null) || busy) return;
    setBusy(true);
    setError(null);
    setProject(null);
    setSelectedAssetId(null);
    const sourceTitle = prompt || masterReference?.label || 'Untitled reference study';
    const title = sourceTitle.length > 64 ? `${sourceTitle.slice(0, 61)}…` : sourceTitle;
    const result = masterReference === null
      ? await gateway.createFromPrompt({
          prompt,
          variation_count: candidateCount,
          owner,
          title,
        })
      : await gateway.createFromDrawing({
          image_base64: masterReference.imageBase64,
          media_type: masterReference.mediaType,
          ...(prompt.length === 0 ? {} : { instruction: prompt }),
          references: secondaryReferences.map((reference) => ({
            role: reference.role,
            image_base64: reference.imageBase64,
            media_type: reference.mediaType,
          })),
          variation_count: candidateCount,
          owner,
          title,
        });
    setBusy(false);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'create'));
      return;
    }
    const nextCandidates = creativeCandidates(result.data);
    if (nextCandidates.length === 0) {
      setError('The project was created, but it did not include a reviewable creative candidate.');
      return;
    }
    setProject(result.data);
    setSelectedAssetId(nextCandidates[0].asset_id);
  };

  if (project !== null) {
    return (
      <ScrollView style={styles.root} contentContainerStyle={styles.content}>
        <Text style={styles.eyebrow}>CHOOSE A DIRECTION</Text>
        <Text style={styles.title}>Which outcome should stay in your Studio?</Text>
        <Text style={styles.body}>
          These are visual directions—not measurements or production instructions.
        </Text>
        <View style={styles.candidateGrid}>
          {candidates.map((candidate, index) => {
            const selected = selectedAssetId === candidate.asset_id;
            return (
              <Pressable
                key={candidate.asset_id}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected }}
                accessibilityLabel={`Direction ${index + 1}`}
                style={[styles.candidateCard, selected && styles.candidateCardSelected]}
                onPress={() => setSelectedAssetId(candidate.asset_id)}>
                {candidate.image_url === null ? (
                  <View style={styles.imageFallback}><Text style={styles.imageFallbackText}>Preview unavailable</Text></View>
                ) : (
                  <Image
                    accessibilityLabel={`Direction ${index + 1} preview`}
                    source={{ uri: candidate.image_url }}
                    style={styles.candidateImage}
                  />
                )}
                <View style={styles.candidateCopy}>
                  <Text style={styles.candidateTitle}>Direction {index + 1}</Text>
                  <Text style={styles.candidateMeta}>{selected ? 'Selected' : 'Tap to choose'}</Text>
                </View>
              </Pressable>
            );
          })}
        </View>
        {error !== null && <Text style={styles.error}>{error}</Text>}
        <View style={styles.footerActions}>
          <Pressable style={styles.secondaryButton} onPress={() => setProject(null)}>
            <Text style={styles.secondaryButtonText}>Try another sentence</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ disabled: selectedAssetId === null || busy }}
            style={[styles.primaryButton, (selectedAssetId === null || busy) && styles.buttonDisabled]}
            disabled={selectedAssetId === null || busy}
            onPress={async () => {
              if (selectedAssetId === null || busy) return;
              setBusy(true);
              setError(null);
              const result = await gateway.selectCreativeDirection(
                project.root_id, selectedAssetId, owner,
              );
              setBusy(false);
              if (result.error !== null) {
                setError(designerErrorMessage(result.error, 'create'));
                return;
              }
              onSave({
                project: result.data,
                selectedAssetId,
                sentence: sentence.trim(),
                references,
              });
            }}>
            <Text style={styles.primaryButtonText}>{busy ? 'Saving…' : 'Save selected direction'}</Text>
          </Pressable>
        </View>
      </ScrollView>
    );
  }

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.content}>
      <Text style={styles.eyebrow}>CREATE</Text>
      <Text style={styles.title}>What would you like to see?</Text>
      <Text style={styles.body}>
        Start with one sentence. References are optional, and production details can wait until you choose a direction.
      </Text>
      <TextInput
        accessibilityLabel="Design sentence"
        placeholder="A sculptural aquamarine collar with articulated white-gold links…"
        placeholderTextColor={theme.faint}
        multiline
        value={sentence}
        onChangeText={setSentence}
        style={styles.prompt}
      />

      <Text style={styles.sectionTitle}>How many directions?</Text>
      <View style={styles.countRow}>
        {([1, 2, 3, 4] as const).map((count) => (
          <Pressable
            key={count}
            accessibilityRole="radio"
            accessibilityState={{ checked: candidateCount === count }}
            style={[styles.countChip, candidateCount === count && styles.countChipSelected]}
            onPress={() => setCandidateCount(count)}>
            <Text style={[styles.countText, candidateCount === count && styles.countTextSelected]}>{count}</Text>
          </Pressable>
        ))}
      </View>

      <Text style={styles.sectionTitle}>Optional references</Text>
      <Text style={styles.sectionHelp}>Give every image one role so intent stays unambiguous.</Text>
      <View style={styles.referenceList}>
        {ROLES.map(({ role, label, help }) => {
          const reference = references.find((item) => item.role === role);
          return (
            <View key={role} style={styles.referenceRow}>
              <View style={styles.referenceCopy}>
                <Text style={styles.referenceTitle}>{label}</Text>
                <Text style={styles.referenceHelp}>{reference?.label ?? help}</Text>
              </View>
              {reference === undefined ? (
                <Pressable
                  accessibilityRole="button"
                  accessibilityState={{ disabled: role !== 'master_geometry' && masterReference === null }}
                  disabled={role !== 'master_geometry' && masterReference === null}
                  style={[
                    styles.referenceButton,
                    role !== 'master_geometry' && masterReference === null && styles.buttonDisabled,
                  ]}
                  onPress={() => requestReference(role)}>
                  <Text style={styles.referenceButtonText}>
                    {role !== 'master_geometry' && masterReference === null ? 'Add master first' : 'Add'}
                  </Text>
                </Pressable>
              ) : (
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={`Remove ${label}`}
                  style={styles.referenceButton}
                  onPress={() => setReferences((current) => current.filter((item) => item.id !== reference.id))}>
                  <Text style={styles.referenceButtonText}>Remove</Text>
                </Pressable>
              )}
            </View>
          );
        })}
      </View>

      {masterReference === null && secondaryReferences.length > 0 && (
        <View style={styles.limitNotice}>
          <Text style={styles.limitTitle}>Master geometry required</Text>
          <Text style={styles.limitBody}>
            Add the source design whose geometry should be preserved before using {secondaryReferences.map((item) => labelForRole(item.role)).join(', ')}.
          </Text>
        </View>
      )}

      {error !== null && <Text style={styles.error}>{error}</Text>}
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: !canCreate }}
        disabled={!canCreate}
        style={[styles.primaryButton, !canCreate && styles.buttonDisabled]}
        onPress={create}>
        <Text style={styles.primaryButtonText}>{busy ? 'Creating…' : `Create ${candidateCount} direction${candidateCount === 1 ? '' : 's'}`}</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.paper },
  content: { width: '100%', maxWidth: 760, alignSelf: 'center', padding: 20, paddingBottom: 60 },
  eyebrow: { color: '#6f52d9', fontSize: 10, fontWeight: '800', letterSpacing: 1.4 },
  title: { color: theme.ink, fontFamily: theme.serif, fontSize: 30, lineHeight: 37, marginTop: 8 },
  body: { color: theme.faint, fontSize: 14, lineHeight: 21, marginTop: 8, maxWidth: 560 },
  prompt: { minHeight: 112, borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, color: theme.ink, fontSize: 16, lineHeight: 23, padding: 16, marginTop: 22, textAlignVertical: 'top' },
  sectionTitle: { color: theme.ink, fontSize: 14, fontWeight: '700', marginTop: 22 },
  sectionHelp: { color: theme.faint, fontSize: 11, lineHeight: 16, marginTop: 4 },
  countRow: { flexDirection: 'row', gap: 8, marginTop: 10 },
  countChip: { width: 44, height: 40, alignItems: 'center', justifyContent: 'center', borderRadius: radius.pill, borderWidth: 1, borderColor: theme.line, backgroundColor: theme.card },
  countChipSelected: { backgroundColor: '#6f52d9', borderColor: '#6f52d9' },
  countText: { color: theme.faint, fontWeight: '700' },
  countTextSelected: { color: '#ffffff' },
  referenceList: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, marginTop: 10, overflow: 'hidden' },
  referenceRow: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderBottomWidth: 1, borderBottomColor: theme.line },
  referenceCopy: { flex: 1 },
  referenceTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  referenceHelp: { color: theme.faint, fontSize: 10, lineHeight: 15, marginTop: 3 },
  referenceButton: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 7 },
  referenceButtonText: { color: theme.ink, fontSize: 11, fontWeight: '600' },
  limitNotice: { borderRadius: radius.md, borderWidth: 1, borderColor: '#c99f48', backgroundColor: '#fff9e9', padding: 13, marginTop: 14 },
  limitTitle: { color: '#745513', fontSize: 12, fontWeight: '700' },
  limitBody: { color: '#745513', fontSize: 10, lineHeight: 16, marginTop: 4 },
  error: { color: theme.danger, fontSize: 12, lineHeight: 17, marginTop: 14 },
  primaryButton: { alignItems: 'center', borderRadius: radius.pill, backgroundColor: '#6f52d9', paddingHorizontal: 18, paddingVertical: 14, marginTop: 20 },
  primaryButtonText: { color: '#ffffff', fontSize: 13, fontWeight: '800' },
  secondaryButton: { alignItems: 'center', borderRadius: radius.pill, borderWidth: 1, borderColor: theme.line, paddingHorizontal: 18, paddingVertical: 13, marginTop: 20 },
  secondaryButtonText: { color: theme.ink, fontSize: 12, fontWeight: '700' },
  buttonDisabled: { opacity: 0.42 },
  candidateGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 22 },
  candidateCard: { width: '48%', borderRadius: radius.lg, borderWidth: 1, borderColor: theme.line, backgroundColor: theme.card, overflow: 'hidden' },
  candidateCardSelected: { borderColor: '#6f52d9', borderWidth: 2 },
  candidateImage: { width: '100%', aspectRatio: 1, backgroundColor: '#ebe7ef' },
  imageFallback: { width: '100%', aspectRatio: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#ebe7ef' },
  imageFallbackText: { color: theme.faint, fontSize: 11 },
  candidateCopy: { padding: 12 },
  candidateTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  candidateMeta: { color: theme.faint, fontSize: 10, marginTop: 3 },
  footerActions: { gap: 0 },
});
