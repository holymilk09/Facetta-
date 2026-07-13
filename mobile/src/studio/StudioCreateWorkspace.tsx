import React, { useMemo, useState } from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';
import { AuthenticatedImage as Image } from '../AuthenticatedImage';

import type { StudioGateway } from './gateway';
import type { AssetSummary, CreativeSourceKind, ProjectDetail } from '../trusted/types';
import { radius, theme } from '../theme';
import { designerErrorMessage } from './designerErrorMessage';
import { getStudioAction } from './actions';
import {
  STUDIO_CREATE_REFERENCE_CONTROLS, type CreateReferenceRole,
} from './workspaceControls';

export { STUDIO_CREATE_REFERENCE_CONTROLS } from './workspaceControls';
export type { CreateReferenceRole } from './workspaceControls';

const CREATE_CREDITS_PER_OUTPUT = getStudioAction('create').creditEstimate ?? 0;

type SecondaryCreateReferenceRole = Exclude<CreateReferenceRole, 'master_geometry'>;

export interface StudioCreateReference {
  id: string;
  role: CreateReferenceRole;
  label: string;
  imageBase64: string;
  mediaType: 'image/png' | 'image/jpeg' | 'image/webp';
  /** Set only on the master; never inferred from file bytes or its name. */
  sourceKind?: CreativeSourceKind;
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
  > & Partial<Pick<StudioGateway, 'saveCreativeDirectionAsVariation'>>;
  owner: string;
  initialSentence?: string;
  initialReferences?: readonly StudioCreateReference[];
  /** Durable review state reopened from a reviewing Create Activity job. */
  resumeProject?: ProjectDetail | null;
  resumeStudioJobId?: string | null;
  onRequestReference?: (
    role: CreateReferenceRole,
  ) => StudioCreateReference | null | Promise<StudioCreateReference | null>;
  onSave: (selection: StudioCreateSelection) => void;
}

const labelForRole = (role: CreateReferenceRole) => (
  STUDIO_CREATE_REFERENCE_CONTROLS.find((item) => item.role === role)?.label ?? role
);

const referencePreviewUri = (reference: StudioCreateReference): string => (
  `data:${reference.mediaType};base64,${reference.imageBase64}`
);

export function creativeCandidates(project: ProjectDetail): readonly AssetSummary[] {
  if ((project.creative_candidates?.length ?? 0) > 0) {
    return project.creative_candidates ?? [];
  }
  // Compatibility for snapshots created before the explicit candidate contract.
  return project.assets.filter((asset) => (
    asset.capability === 'CREATIVE_RENDER' && asset.design_version === null
  ));
}

export function StudioCreateWorkspace({
  gateway,
  owner,
  initialSentence = '',
  initialReferences = [],
  resumeProject = null,
  resumeStudioJobId = null,
  onRequestReference,
  onSave,
}: StudioCreateWorkspaceProps) {
  const [sentence, setSentence] = useState(initialSentence);
  const [references, setReferences] = useState<StudioCreateReference[]>([...initialReferences]);
  const [sourceKind, setSourceKind] = useState<CreativeSourceKind | null>(() => (
    initialReferences.find((reference) => reference.role === 'master_geometry')?.sourceKind ?? null
  ));
  const [candidateCount, setCandidateCount] = useState<1 | 2 | 3 | 4>(2);
  const [setupOpen, setSetupOpen] = useState(initialReferences.length > 0);
  const [project, setProject] = useState<ProjectDetail | null>(resumeProject);
  const resumedCandidates = resumeProject === null ? [] : creativeCandidates(resumeProject);
  const resumedSelection = resumeProject?.selected_candidate_asset_id;
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(() => (
    resumedSelection !== null && resumedSelection !== undefined
      && resumedCandidates.some((candidate) => candidate.asset_id === resumedSelection)
      ? resumedSelection
      : resumedCandidates[0]?.asset_id ?? null
  ));
  const [selectionStudioJobId, setSelectionStudioJobId] = useState<string | null>(
    resumeStudioJobId,
  );
  const [stagedCandidateIds, setStagedCandidateIds] = useState<Set<string>>(new Set());
  const [savedCandidateIds, setSavedCandidateIds] = useState<Set<string>>(new Set());
  const [originalLocked, setOriginalLocked] = useState(false);
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
    && !(masterReference === null && secondaryReferences.length > 0)
    && (masterReference === null || sourceKind !== null);

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
      if (role === 'master_geometry') setSourceKind(reference.sourceKind ?? null);
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
    setSelectionStudioJobId(null);
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
          source_kind: sourceKind!,
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

  const toggleDirectionToKeep = (candidateId: string): void => {
    if (busy || originalLocked) return;
    setStagedCandidateIds((current) => {
      const next = new Set(current);
      if (next.has(candidateId)) next.delete(candidateId);
      else next.add(candidateId);
      return next;
    });
  };

  const continueWithSelection = async (): Promise<void> => {
    if (project === null || selectedAssetId === null || busy) return;
    if (stagedCandidateIds.size > 0 && gateway.saveCreativeDirectionAsVariation === undefined) {
      setError('Saving another direction is unavailable here. Remove the kept variations or try again later.');
      return;
    }

    setBusy(true);
    setError(null);
    let selectedProject = project;
    let activeAssetId = project.active_asset_id ?? selectedAssetId;

    if (!originalLocked) {
      const selected = selectionStudioJobId === null
        ? await gateway.selectCreativeDirection(project.root_id, selectedAssetId, owner)
        : await gateway.selectCreativeDirection(
            project.root_id, selectedAssetId, owner, selectionStudioJobId,
          );
      if (selected.error !== null) {
        setBusy(false);
        setError(designerErrorMessage(selected.error, 'create'));
        return;
      }
      selectedProject = selected.data;
      activeAssetId = selected.data.active_asset_id ?? selectedAssetId;
      setProject(selected.data);
      setSelectionStudioJobId(null);
      setOriginalLocked(true);
    }

    const directionsToKeep = candidates.filter((candidate) => (
      candidate.asset_id !== selectedAssetId && stagedCandidateIds.has(candidate.asset_id)
    ));
    for (const candidate of directionsToKeep) {
      const index = candidates.findIndex((item) => item.asset_id === candidate.asset_id);
      const saved = await gateway.saveCreativeDirectionAsVariation!({
        projectId: project.root_id,
        candidateId: candidate.asset_id,
        activeAssetId,
        createdBy: owner,
        label: `Direction ${index + 1}`,
      });
      if (saved.error !== null) {
        setBusy(false);
        setError(designerErrorMessage(saved.error, 'vary'));
        return;
      }
      setSavedCandidateIds((current) => new Set(current).add(candidate.asset_id));
      setStagedCandidateIds((current) => {
        const remaining = new Set(current);
        remaining.delete(candidate.asset_id);
        return remaining;
      });
    }

    setBusy(false);
    onSave({
      project: selectedProject,
      selectedAssetId,
      sentence: sentence.trim(),
      references,
    });
  };

  if (project !== null) {
    return (
      <ScrollView style={styles.root} contentContainerStyle={styles.content}>
        <Text style={styles.eyebrow}>CHOOSE A DIRECTION</Text>
        <Text style={styles.title}>Which direction do you want to refine?</Text>
        <Text style={styles.body}>
          These are visual directions—not measurements or production instructions.
        </Text>
        <Text style={styles.retainedCopy}>
          Your choice becomes the Original and starts its immutable revision history. Mark any other useful direction to keep as a sibling variation, then continue once.
        </Text>
        <View style={styles.candidateGrid}>
          {candidates.map((candidate, index) => {
            const selected = selectedAssetId === candidate.asset_id;
            const stagedToKeep = stagedCandidateIds.has(candidate.asset_id);
            const savedAsVariation = savedCandidateIds.has(candidate.asset_id);
            const candidateDisabled = busy || originalLocked;
            return (
              <Pressable
                key={candidate.asset_id}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected, disabled: candidateDisabled }}
                accessibilityLabel={`Direction ${index + 1}`}
                disabled={candidateDisabled}
                style={[styles.candidateCard, selected && styles.candidateCardSelected]}
                onPress={() => {
                  if (candidateDisabled) return;
                  setSelectedAssetId(candidate.asset_id);
                  setStagedCandidateIds((current) => {
                    const next = new Set(current);
                    next.delete(candidate.asset_id);
                    return next;
                  });
                }}>
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
                  <Text style={styles.candidateMeta}>{selected
                    ? originalLocked ? 'Original' : 'Selected as Original'
                    : savedAsVariation ? 'Saved as variation' : stagedToKeep ? 'Will be kept as a variation' : originalLocked ? 'Not kept' : 'Tap to choose'}</Text>
                  {!selected && (
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={savedAsVariation
                        ? `Direction ${index + 1} saved as variation`
                        : `${stagedToKeep ? 'Remove' : 'Keep'} Direction ${index + 1} ${stagedToKeep ? 'from' : 'as'} variations`}
                      accessibilityState={{
                        disabled: candidateDisabled || savedAsVariation,
                        selected: stagedToKeep,
                      }}
                      disabled={candidateDisabled || savedAsVariation}
                      style={styles.keepButton}
                      onPress={(event) => {
                        event.stopPropagation();
                        toggleDirectionToKeep(candidate.asset_id);
                      }}>
                      <Text style={styles.keepButtonText}>
                        {savedAsVariation
                          ? 'Saved as variation'
                          : stagedToKeep ? 'Remove from kept variations' : 'Keep as variation'}
                      </Text>
                    </Pressable>
                  )}
                </View>
              </Pressable>
            );
          })}
        </View>
        {error !== null && <Text style={styles.error}>{error}</Text>}
        <View style={styles.footerActions}>
          <Pressable style={styles.secondaryButton} onPress={() => {
            setProject(null);
            setSelectedAssetId(null);
            setSelectionStudioJobId(null);
            setStagedCandidateIds(new Set());
            setSavedCandidateIds(new Set());
            setOriginalLocked(false);
          }}>
            <Text style={styles.secondaryButtonText}>Keep these directions &amp; start another</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ disabled: selectedAssetId === null || busy }}
            style={[styles.primaryButton, (selectedAssetId === null || busy) && styles.buttonDisabled]}
            disabled={selectedAssetId === null || busy}
            onPress={() => void continueWithSelection()}>
            <Text style={styles.primaryButtonText}>{busy
              ? 'Saving directions…'
              : `Continue with Direction ${candidates.findIndex((candidate) => candidate.asset_id === selectedAssetId) + 1}${stagedCandidateIds.size === 0
                ? ''
                : ` · keep ${stagedCandidateIds.size} variation${stagedCandidateIds.size === 1 ? '' : 's'}`}`}</Text>
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

      <View style={styles.masterSourceCard}>
        {masterReference !== null && (
          <Image
            accessibilityLabel="Visual source preview"
            source={{ uri: referencePreviewUri(masterReference) }}
            style={styles.referenceThumbnail}
          />
        )}
        <View style={styles.referenceCopy}>
          <Text style={styles.referenceTitle}>Visual source</Text>
          <Text style={styles.referenceHelp}>{masterReference === null
            ? 'Optional. Add one source design to preserve its visible form.'
            : masterReference.label}</Text>
        </View>
        {masterReference === null ? (
          <Pressable
            accessibilityRole="button"
            style={styles.addSourceButton}
            onPress={() => requestReference('master_geometry')}>
            <Text style={styles.addSourceButtonText}>Add a drawing, photo, or render</Text>
          </Pressable>
        ) : (
          <View style={styles.referenceActions}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Replace visual source"
              style={styles.referenceButton}
              onPress={() => requestReference('master_geometry')}>
              <Text style={styles.referenceButtonText}>Replace</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Remove visual source"
              style={styles.referenceButton}
              onPress={() => {
                setReferences((current) => current.filter(
                  (item) => item.role !== 'master_geometry',
                ));
                setSourceKind(null);
              }}>
              <Text style={styles.referenceButtonText}>Remove</Text>
            </Pressable>
          </View>
        )}
      </View>
      {masterReference !== null && (
        <View style={styles.sourceKindBlock}>
          <Text style={styles.sourceKindPrompt}>What did you upload?</Text>
          <View style={styles.sourceKindRow}>
            {([
              ['drawing', 'Drawing'],
              ['photograph', 'Photograph'],
              ['finished_render', 'Finished render'],
            ] as const).map(([kind, label]) => (
              <Pressable
                key={kind}
                accessibilityRole="radio"
                accessibilityState={{ checked: sourceKind === kind }}
                style={[styles.sourceKindChip, sourceKind === kind && styles.sourceKindChipSelected]}
                onPress={() => setSourceKind(kind)}>
                <Text style={[
                  styles.sourceKindText,
                  sourceKind === kind && styles.sourceKindTextSelected,
                ]}>{label}</Text>
              </Pressable>
            ))}
          </View>
          {sourceKind === null && (
            <Text style={styles.sourceKindHelp}>Choose one so Facetta preserves truthful source history.</Text>
          )}
        </View>
      )}

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="References and output options"
        accessibilityState={{ expanded: setupOpen }}
        onPress={() => setSetupOpen((current) => !current)}
        style={[styles.setupDisclosure, setupOpen && styles.setupDisclosureOpen]}>
        <View style={styles.setupDisclosureCopy}>
          <Text style={styles.setupDisclosureTitle}>References &amp; output options</Text>
          <Text style={styles.setupDisclosureSummary}>
            {candidateCount} direction{candidateCount === 1 ? '' : 's'} · {references.length === 0
              ? 'No references'
              : `${references.length} role-labeled reference${references.length === 1 ? '' : 's'}`}
          </Text>
        </View>
        <Text style={styles.disclosureGlyph}>{setupOpen ? '−' : '+'}</Text>
      </Pressable>

      {setupOpen && (
        <View style={styles.setupPanel}>
          <Text style={styles.sectionTitle}>How many directions?</Text>
          <View style={styles.countRow}>
            {([1, 2, 3, 4] as const).map((count) => (
              <Pressable
                key={count}
                accessibilityRole="radio"
                accessibilityLabel={`${count} creative direction${count === 1 ? '' : 's'}`}
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
            {STUDIO_CREATE_REFERENCE_CONTROLS.filter(
              ({ role }) => role !== 'master_geometry',
            ).map(({ role, label, help }) => {
              const reference = references.find((item) => item.role === role);
              return (
                <View key={role} style={styles.referenceRow}>
                  {reference !== undefined && (
                    <Image
                      accessibilityLabel={`${label} reference preview`}
                      source={{ uri: referencePreviewUri(reference) }}
                      style={styles.referenceThumbnail}
                    />
                  )}
                  <View style={styles.referenceCopy}>
                    <Text style={styles.referenceTitle}>{label}</Text>
                    <Text style={styles.referenceHelp}>{reference?.label ?? help}</Text>
                  </View>
                  {reference === undefined ? (
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={`Add ${label} reference`}
                      accessibilityHint={masterReference === null
                        ? 'Add a visual source before adding this supporting reference.'
                        : help}
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
                    <View style={styles.referenceActions}>
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel={`Replace ${label} reference`}
                        style={styles.referenceButton}
                        onPress={() => requestReference(role)}>
                        <Text style={styles.referenceButtonText}>Replace</Text>
                      </Pressable>
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel={`Remove ${label} reference`}
                        style={styles.referenceButton}
                        onPress={() => setReferences((current) => current.filter((item) => item.id !== reference.id))}>
                        <Text style={styles.referenceButtonText}>Remove</Text>
                      </Pressable>
                    </View>
                  )}
                </View>
              );
            })}
          </View>
        </View>
      )}

      {masterReference === null && secondaryReferences.length > 0 && (
        <View style={styles.limitNotice}>
          <Text style={styles.limitTitle}>Master geometry required</Text>
          <Text style={styles.limitBody}>
            Add the source design whose geometry should be preserved before using {secondaryReferences.map((item) => labelForRole(item.role)).join(', ')}.
          </Text>
        </View>
      )}

      {error !== null && <Text style={styles.error}>{error}</Text>}
      <Text style={styles.creditEstimate}>
        {candidateCount} requested output{candidateCount === 1 ? '' : 's'} × {CREATE_CREDITS_PER_OUTPUT} credits = estimated {candidateCount * CREATE_CREDITS_PER_OUTPUT} credits
      </Text>
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
  retainedCopy: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 10, maxWidth: 560 },
  prompt: { minHeight: 112, borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, color: theme.ink, fontSize: 16, lineHeight: 23, padding: 16, marginTop: 22, textAlignVertical: 'top' },
  sectionTitle: { color: theme.ink, fontSize: 14, fontWeight: '700', marginTop: 22 },
  sectionHelp: { color: theme.faint, fontSize: 11, lineHeight: 16, marginTop: 4 },
  countRow: { flexDirection: 'row', gap: 8, marginTop: 10 },
  countChip: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: radius.pill, borderWidth: 1, borderColor: theme.line, backgroundColor: theme.card },
  countChipSelected: { backgroundColor: '#6f52d9', borderColor: '#6f52d9' },
  countText: { color: theme.faint, fontWeight: '700' },
  countTextSelected: { color: '#ffffff' },
  setupDisclosure: {
    borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg,
    backgroundColor: theme.card, padding: 14, marginTop: 16,
    flexDirection: 'row', alignItems: 'center', gap: 12,
  },
  setupDisclosureOpen: { borderColor: '#6f52d9' },
  setupDisclosureCopy: { flex: 1 },
  setupDisclosureTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  setupDisclosureSummary: { color: theme.faint, fontSize: 11, lineHeight: 16, marginTop: 3 },
  disclosureGlyph: { color: '#6f52d9', fontSize: 22, fontWeight: '500' },
  setupPanel: { paddingHorizontal: 2 },
  masterSourceCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, padding: 14, marginTop: 14, flexDirection: 'row', alignItems: 'center', gap: 12 },
  addSourceButton: { minHeight: 44, justifyContent: 'center', borderRadius: radius.pill, backgroundColor: '#eee9ff', paddingHorizontal: 14, paddingVertical: 9 },
  addSourceButtonText: { color: '#5c3fc0', fontSize: 11, fontWeight: '800' },
  sourceKindBlock: { marginTop: 10 },
  sourceKindPrompt: { color: theme.ink, fontSize: 11, fontWeight: '700' },
  sourceKindRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 7, marginTop: 7 },
  sourceKindChip: { minHeight: 44, justifyContent: 'center', borderWidth: 1, borderColor: theme.line, borderRadius: radius.pill, paddingHorizontal: 11, paddingVertical: 7, backgroundColor: theme.card },
  sourceKindChipSelected: { borderColor: '#6f52d9', backgroundColor: '#eee9ff' },
  sourceKindText: { color: theme.faint, fontSize: 10, fontWeight: '700' },
  sourceKindTextSelected: { color: '#5c3fc0' },
  sourceKindHelp: { color: '#745513', fontSize: 10, marginTop: 6 },
  referenceList: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, marginTop: 10, overflow: 'hidden' },
  referenceRow: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderBottomWidth: 1, borderBottomColor: theme.line },
  referenceThumbnail: { width: 52, height: 52, borderRadius: radius.sm, backgroundColor: theme.line },
  referenceActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, justifyContent: 'flex-end' },
  referenceCopy: { flex: 1 },
  referenceTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  referenceHelp: { color: theme.faint, fontSize: 10, lineHeight: 15, marginTop: 3 },
  referenceButton: { minHeight: 44, justifyContent: 'center', borderWidth: 1, borderColor: theme.line, borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 7 },
  referenceButtonText: { color: theme.ink, fontSize: 11, fontWeight: '600' },
  limitNotice: { borderRadius: radius.md, borderWidth: 1, borderColor: '#c99f48', backgroundColor: '#fff9e9', padding: 13, marginTop: 14 },
  limitTitle: { color: '#745513', fontSize: 12, fontWeight: '700' },
  limitBody: { color: '#745513', fontSize: 10, lineHeight: 16, marginTop: 4 },
  error: { color: theme.danger, fontSize: 12, lineHeight: 17, marginTop: 14 },
  creditEstimate: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 18 },
  primaryButton: { minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: radius.pill, backgroundColor: '#6f52d9', paddingHorizontal: 18, paddingVertical: 14, marginTop: 20 },
  primaryButtonText: { color: '#ffffff', fontSize: 13, fontWeight: '800' },
  secondaryButton: { minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: radius.pill, borderWidth: 1, borderColor: theme.line, paddingHorizontal: 18, paddingVertical: 13, marginTop: 20 },
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
  keepButton: { minHeight: 44, justifyContent: 'center', alignSelf: 'flex-start', borderWidth: 1, borderColor: theme.line, borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 6, marginTop: 10 },
  keepButtonText: { color: theme.ink, fontSize: 10, fontWeight: '700' },
  footerActions: { gap: 0 },
});
