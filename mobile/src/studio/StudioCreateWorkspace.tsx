import React, {
  type Dispatch, type SetStateAction, useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';

import type { StudioGateway } from './gateway';
import type { AssetSummary, CreativeSourceKind, ProjectDetail } from '../trusted/types';
import { radius, theme } from '../theme';
import { designerErrorMessage } from './designerErrorMessage';
import { getStudioAction } from './actions';
import {
  STUDIO_CREATE_REFERENCE_CONTROLS, type CreateReferenceRole,
} from './workspaceControls';
import { useVisualReviewReadiness } from './useVisualReviewReadiness';
import { StudioReviewImage } from './StudioReviewImage';

export { STUDIO_CREATE_REFERENCE_CONTROLS } from './workspaceControls';
export type { CreateReferenceRole } from './workspaceControls';

const CREATE_CREDITS_PER_OUTPUT = getStudioAction('create').creditEstimate ?? 0;

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
}

export type StudioCreateCandidateCount = 1 | 2 | 3 | 4;
export type StudioCreateMode = 'prompt' | 'drawing';

/**
 * The complete pre-generation Create setup. The master reference owns its
 * explicit sourceKind so source truth cannot drift from a parallel field.
 */
export interface StudioCreateDraft {
  /** Last active text, retained for compatibility with saved Create jobs. */
  sentence: string;
  references: readonly StudioCreateReference[];
  candidateCount: StudioCreateCandidateCount;
  /** Keeps the two simple starting methods independent when the user toggles. */
  mode?: StudioCreateMode;
  promptText?: string;
  drawingNotes?: string;
}

export const EMPTY_STUDIO_CREATE_DRAFT: StudioCreateDraft = {
  sentence: '',
  references: [],
  candidateCount: 2,
  mode: 'prompt',
  promptText: '',
  drawingNotes: '',
};

export interface StudioCreateGenerationSuccess {
  owner: string;
  projectId: string;
  submittedDraft: StudioCreateDraft;
}

export interface StudioCreateWorkspaceProps {
  gateway: Pick<StudioGateway,
    'createFromPrompt' | 'createFromDrawing' | 'completeCreativeDirectionReview'
  >;
  owner: string;
  /** Controlled draft used by App so setup survives workspace navigation. */
  draft?: StudioCreateDraft;
  onDraftChange?: Dispatch<SetStateAction<StudioCreateDraft>>;
  /** Called only after a request returns reviewable directions. */
  onGenerationSucceeded?: (success: StudioCreateGenerationSuccess) => void;
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

const referencePreviewUri = (reference: StudioCreateReference): string => (
  `data:${reference.mediaType};base64,${reference.imageBase64}`
);

const MAX_RETAINED_VARIATIONS = 3;

const candidateVisualKey = (candidate: AssetSummary): string | null => (
  candidate.image_url === null
    ? null
    : `create-candidate:${candidate.asset_id}:${candidate.image_url}`
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
  draft: controlledDraft,
  onDraftChange,
  onGenerationSucceeded,
  initialSentence = '',
  initialReferences = [],
  resumeProject = null,
  resumeStudioJobId = null,
  onRequestReference,
  onSave,
}: StudioCreateWorkspaceProps) {
  const [localDraft, setLocalDraft] = useState<StudioCreateDraft>(() => ({
    sentence: initialSentence,
    references: [...initialReferences],
    candidateCount: 2,
    mode: initialReferences.some((reference) => reference.role === 'master_geometry')
      ? 'drawing' : 'prompt',
    promptText: initialReferences.some((reference) => reference.role === 'master_geometry')
      ? '' : initialSentence,
    drawingNotes: initialReferences.some((reference) => reference.role === 'master_geometry')
      ? initialSentence : '',
  }));
  const createDraft = controlledDraft ?? localDraft;
  const { sentence, references, candidateCount } = createDraft;
  const controlledDraftRef = useRef(controlledDraft);
  controlledDraftRef.current = controlledDraft;
  const onDraftChangeRef = useRef(onDraftChange);
  onDraftChangeRef.current = onDraftChange;
  const updateDraft = useCallback((
    update: (current: StudioCreateDraft) => StudioCreateDraft,
  ): void => {
    if (controlledDraftRef.current === undefined) {
      setLocalDraft(update);
      return;
    }
    onDraftChangeRef.current?.(update);
  }, []);
  const mountedRef = useRef(true);
  const ownerRef = useRef(owner);
  const generationRequestIdRef = useRef(0);
  const referenceRequestIdRef = useRef(0);
  const selectionRequestIdRef = useRef(0);
  if (ownerRef.current !== owner) {
    ownerRef.current = owner;
    generationRequestIdRef.current += 1;
    referenceRequestIdRef.current += 1;
    selectionRequestIdRef.current += 1;
  }
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      generationRequestIdRef.current += 1;
      referenceRequestIdRef.current += 1;
      selectionRequestIdRef.current += 1;
    };
  }, []);
  const [createMode, setCreateMode] = useState<StudioCreateMode>(() => (
    controlledDraft?.mode ?? (
      (controlledDraft?.references ?? initialReferences).some(
        (reference) => reference.role === 'master_geometry',
      ) ? 'drawing' : 'prompt'
    )
  ));
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const candidates = useMemo(() => project === null ? [] : creativeCandidates(project), [project]);
  const visualReview = useVisualReviewReadiness(project?.root_id ?? 'create-setup');
  const referenceVisualKey = (reference: StudioCreateReference): string => (
    `create-reference:${reference.role}:${reference.id}:${reference.mediaType}:${reference.imageBase64}`
  );
  const intendedRetainedCandidates = useMemo(() => (
    candidates
      // Persistence follows the generated project record, not transient image
      // loading. A thumbnail failure must never silently drop a direction.
      .filter((candidate) => candidate.asset_id !== selectedAssetId)
      .slice(0, MAX_RETAINED_VARIATIONS)
  ), [candidates, selectedAssetId]);
  const selectedCandidate = candidates.find(
    (candidate) => candidate.asset_id === selectedAssetId,
  ) ?? null;
  const selectedVisualKey = selectedCandidate === null ? null : candidateVisualKey(selectedCandidate);
  const decisionVisualsReady = selectedAssetId !== null
    && selectedCandidate !== null
    && visualReview.allReady([selectedVisualKey]);
  const selectedVisualFailed = selectedAssetId !== null
    && visualReview.anyFailed([selectedVisualKey]);
  const masterReference = references.find((reference) => reference.role === 'master_geometry') ?? null;
  const promptText = createDraft.promptText
    ?? (masterReference === null ? sentence : '');
  const drawingNotes = createDraft.drawingNotes
    ?? (masterReference === null ? '' : sentence);
  const activeText = createMode === 'prompt' ? promptText : drawingNotes;
  const activeReferences = createMode === 'drawing' && masterReference !== null
    ? [masterReference] : [];
  const referenceVisualKeys = activeReferences.map(referenceVisualKey);
  const referenceVisualsReady = referenceVisualKeys.length === 0
    || visualReview.allReady(referenceVisualKeys);
  const referenceVisualFailed = visualReview.anyFailed(referenceVisualKeys);
  const canCreate = !busy
    && (createMode === 'prompt' ? activeText.trim().length > 0 : masterReference !== null)
    && referenceVisualsReady;

  const chooseMode = (mode: StudioCreateMode): void => {
    setCreateMode(mode);
    setError(null);
    updateDraft((current) => {
      const currentMaster = current.references.some(
        (reference) => reference.role === 'master_geometry',
      );
      const nextText = mode === 'prompt'
        ? (current.promptText ?? (currentMaster ? '' : current.sentence))
        : (current.drawingNotes ?? (currentMaster ? current.sentence : ''));
      return {
        ...current,
        mode,
        sentence: nextText,
      };
    });
  };

  const requestReference = async (role: CreateReferenceRole) => {
    const requestId = referenceRequestIdRef.current + 1;
    referenceRequestIdRef.current = requestId;
    const requestOwner = owner;
    setError(null);
    if (onRequestReference === undefined) {
      setError('Image selection is unavailable here. You can continue with a sentence or try again on a supported device.');
      return;
    }
    try {
      const reference = await onRequestReference(role);
      if (!mountedRef.current
        || referenceRequestIdRef.current !== requestId
        || ownerRef.current !== requestOwner) return;
      if (reference === null) return;
      updateDraft((current) => ({
        ...current,
        mode: role === 'master_geometry' ? 'drawing' : current.mode,
        references: role === 'master_geometry'
          ? [{ ...reference, role, sourceKind: 'drawing' }]
          : current.references,
      }));
      if (role === 'master_geometry') setCreateMode('drawing');
    } catch (cause) {
      if (!mountedRef.current
        || referenceRequestIdRef.current !== requestId
        || ownerRef.current !== requestOwner) return;
      setError(cause instanceof Error
        ? cause.message
        : 'The selected image could not be added. Choose another file and try again.');
    }
  };

  const create = async () => {
    const submittedDraft = createDraft;
    const submittedReferences = submittedDraft.references;
    const submittedMaster = submittedReferences.find(
      (reference) => reference.role === 'master_geometry',
    ) ?? null;
    const submittedSourceKind = submittedMaster?.sourceKind ?? 'drawing';
    const prompt = (createMode === 'prompt'
      ? (submittedDraft.promptText ?? submittedDraft.sentence)
      : (submittedDraft.drawingNotes ?? submittedDraft.sentence)).trim();
    if ((createMode === 'prompt' ? !prompt : submittedMaster === null) || busy) return;
    const requestId = generationRequestIdRef.current + 1;
    generationRequestIdRef.current = requestId;
    const requestOwner = owner;
    setBusy(true);
    setError(null);
    setProject(null);
    setSelectedAssetId(null);
    setSelectionStudioJobId(null);
    const sourceTitle = prompt || submittedMaster?.label || 'Untitled drawing';
    const title = sourceTitle.length > 64 ? `${sourceTitle.slice(0, 61)}…` : sourceTitle;
    const result = createMode === 'prompt'
      ? await gateway.createFromPrompt({
          prompt,
          variation_count: submittedDraft.candidateCount,
          owner: requestOwner,
          title,
        })
      : await gateway.createFromDrawing({
          image_base64: submittedMaster!.imageBase64,
          source_kind: submittedSourceKind,
          media_type: submittedMaster!.mediaType,
          ...(prompt.length === 0 ? {} : { instruction: prompt }),
          references: [],
          variation_count: submittedDraft.candidateCount,
          owner: requestOwner,
          title,
        });
    if (!mountedRef.current
      || generationRequestIdRef.current !== requestId
      || ownerRef.current !== requestOwner) return;
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
    onGenerationSucceeded?.({
      owner: requestOwner,
      projectId: result.data.root_id,
      submittedDraft,
    });
  };

  const continueWithSelection = async (): Promise<void> => {
    if (project === null || selectedAssetId === null || busy || !decisionVisualsReady) return;

    const requestId = selectionRequestIdRef.current + 1;
    selectionRequestIdRef.current = requestId;
    const requestOwner = owner;
    const requestProjectId = project.root_id;
    const requestSelectedAssetId = selectedAssetId;
    setBusy(true);
    setError(null);
    const retained = intendedRetainedCandidates.map((candidate) => {
      const index = candidates.findIndex((item) => item.asset_id === candidate.asset_id);
      return {
        candidateId: candidate.asset_id,
        label: `Design ${index + 1}`,
      };
    });
    const committed = await gateway.completeCreativeDirectionReview({
      projectId: requestProjectId,
      selectedCandidateId: requestSelectedAssetId,
      retained,
      createdBy: requestOwner,
      ...(selectionStudioJobId === null ? {} : { studioJobId: selectionStudioJobId }),
    });
    if (!mountedRef.current
      || selectionRequestIdRef.current !== requestId
      || ownerRef.current !== requestOwner) return;
    if (committed.error !== null) {
      setBusy(false);
      setError(designerErrorMessage(committed.error, 'create'));
      return;
    }

    setBusy(false);
    setProject(committed.data.project);
    setSelectionStudioJobId(null);
    onSave({
      project: committed.data.project,
      selectedAssetId: requestSelectedAssetId,
    });
  };

  const leaveReviewAndStartAnother = (): void => {
    if (busy) return;
    selectionRequestIdRef.current += 1;
    setError(null);
    setProject(null);
    setSelectedAssetId(null);
    setSelectionStudioJobId(null);
  };

  if (project !== null) {
    return (
      <ScrollView style={styles.root} contentContainerStyle={styles.content}>
        <Text style={styles.eyebrow}>YOUR DESIGNS</Text>
        <Text style={styles.title}>Choose a design</Text>
        <Text style={styles.body}>
          Pick the design you want to keep working on. These images are visual concepts, not production measurements.
        </Text>
        {candidates.length > 1 && (
          <Text style={styles.retainedCopy}>
            Your other generated designs stay saved for comparison.
          </Text>
        )}
        <View style={styles.candidateGrid}>
          {candidates.map((candidate, index) => {
            const selected = selectedAssetId === candidate.asset_id;
            const willRetain = intendedRetainedCandidates.some(
              (item) => item.asset_id === candidate.asset_id,
            );
            const candidateStatus = selected
              ? 'Selected'
              : willRetain
                ? 'Saved as an alternative'
                : 'Saved for comparison';
            const visualKey = candidateVisualKey(candidate);
            const candidateDisabled = busy;
            return (
              <View
                key={candidate.asset_id}
                style={[styles.candidateCard, selected && styles.candidateCardSelected]}>
                {candidate.image_url === null ? (
                  <View style={styles.imageFallback}><Text style={styles.imageFallbackText}>Preview unavailable</Text></View>
                ) : (
                  <StudioReviewImage
                    accessibilityLabel={`Design ${index + 1} preview`}
                    inspectionLabel={`Design ${index + 1}`}
                    source={{ uri: candidate.image_url }}
                    onLoad={() => visualReview.markReady(visualKey)}
                    onError={() => visualReview.markFailed(visualKey)}
                    style={styles.candidateImage}
                  />
                )}
                <Pressable
                  accessibilityRole="radio"
                  accessibilityState={{ checked: selected, disabled: candidateDisabled }}
                  accessibilityLabel={`Design ${index + 1}`}
                  accessibilityHint={candidateStatus}
                  disabled={candidateDisabled}
                  style={styles.candidateSelect}
                  onPress={() => {
                    if (candidateDisabled) return;
                    setSelectedAssetId(candidate.asset_id);
                  }}>
                  <View style={styles.candidateCopy}>
                    <Text style={styles.candidateTitle}>Design {index + 1}</Text>
                    <Text style={styles.candidateMeta}>{candidateStatus}</Text>
                  </View>
                </Pressable>
              </View>
            );
          })}
        </View>
        {!decisionVisualsReady && selectedAssetId !== null && (
          <Text style={styles.reviewReadiness}>
            {selectedVisualFailed
              ? 'The selected design could not be displayed. Choose another design or try loading it again before continuing.'
              : 'Wait for the selected design to finish loading before continuing.'}
          </Text>
        )}
        {error !== null && <Text style={styles.error}>{error}</Text>}
        <View style={styles.footerActions}>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ disabled: busy }}
            disabled={busy}
            style={[styles.secondaryButton, busy && styles.buttonDisabled]}
            onPress={leaveReviewAndStartAnother}>
            <Text style={styles.secondaryButtonText}>Start over</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ disabled: busy || !decisionVisualsReady }}
            style={[styles.primaryButton, (busy || !decisionVisualsReady) && styles.buttonDisabled]}
            disabled={busy || !decisionVisualsReady}
            onPress={() => void continueWithSelection()}>
            <Text style={styles.primaryButtonText}>{busy
              ? 'Saving…'
              : `Continue with Design ${candidates.findIndex((candidate) => candidate.asset_id === selectedAssetId) + 1}`}</Text>
          </Pressable>
        </View>
      </ScrollView>
    );
  }

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.content}>
      <Text style={styles.eyebrow}>CREATE</Text>
      <Text style={styles.title}>How would you like to begin?</Text>
      <Text style={styles.body}>
        Describe the jewelry you want, or upload your own drawing. Both create real visual designs you can compare.
      </Text>
      <View style={styles.modeRow}>
        <Pressable
          accessibilityRole="radio"
          accessibilityLabel="Describe a design"
          accessibilityState={{ checked: createMode === 'prompt' }}
          onPress={() => chooseMode('prompt')}
          style={[styles.modeCard, createMode === 'prompt' && styles.modeCardSelected]}>
          <Text style={styles.modeTitle}>Describe a design</Text>
          <Text style={styles.modeHelp}>Write what you want to create.</Text>
        </Pressable>
        <Pressable
          accessibilityRole="radio"
          accessibilityLabel="Upload a drawing"
          accessibilityState={{ checked: createMode === 'drawing' }}
          onPress={() => chooseMode('drawing')}
          style={[styles.modeCard, createMode === 'drawing' && styles.modeCardSelected]}>
          <Text style={styles.modeTitle}>Upload a drawing</Text>
          <Text style={styles.modeHelp}>Turn your sketch into visual designs.</Text>
        </Pressable>
      </View>

      {createMode === 'prompt' ? (
        <>
          <Text style={styles.inputLabel}>Describe your jewelry</Text>
          <TextInput
            accessibilityLabel="Design description"
            placeholder="An oval aquamarine ring in white gold with a sculptural split shank…"
            placeholderTextColor={theme.faint}
            multiline
            value={promptText}
            onChangeText={(nextSentence) => updateDraft((current) => ({
              ...current,
              mode: 'prompt',
              sentence: nextSentence,
              promptText: nextSentence,
            }))}
            style={styles.prompt}
          />
        </>
      ) : (
        <>
          <View style={styles.masterSourceCard}>
            {masterReference !== null && (
              <StudioReviewImage
                accessibilityLabel="Drawing preview"
                inspectionLabel={`Uploaded drawing · ${masterReference.label}`}
                source={{ uri: referencePreviewUri(masterReference) }}
                onLoad={() => visualReview.markReady(referenceVisualKey(masterReference))}
                onError={() => visualReview.markFailed(referenceVisualKey(masterReference))}
                style={styles.referenceThumbnail}
              />
            )}
            <View style={styles.referenceCopy}>
              <Text style={styles.referenceTitle}>Your drawing</Text>
              <Text style={styles.referenceHelp}>{masterReference?.label
                ?? 'JPG, PNG, or WEBP. Facetta will preserve its visible form.'}</Text>
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={masterReference === null ? 'Choose a drawing' : 'Replace drawing'}
              style={styles.addSourceButton}
              onPress={() => requestReference('master_geometry')}>
              <Text style={styles.addSourceButtonText}>{masterReference === null ? 'Choose drawing' : 'Replace'}</Text>
            </Pressable>
          </View>
          <Text style={styles.inputLabel}>Optional notes</Text>
          <TextInput
            accessibilityLabel="Drawing notes"
            placeholder="For example: make the setting lighter while keeping the silhouette."
            placeholderTextColor={theme.faint}
            multiline
            value={drawingNotes}
            onChangeText={(nextSentence) => updateDraft((current) => ({
              ...current,
              mode: 'drawing',
              sentence: nextSentence,
              drawingNotes: nextSentence,
            }))}
            style={styles.promptCompact}
          />
        </>
      )}

      <Text style={styles.sectionTitle}>How many designs would you like to compare?</Text>
      <Text style={styles.sectionHelp}>
        Each is a different design for the same idea. Choose 1 for speed, or 2–4 to compare.
      </Text>
      <View style={styles.countRow}>
        {([1, 2, 3, 4] as const).map((count) => (
          <Pressable
            key={count}
            accessibilityRole="radio"
            accessibilityLabel={`${count} design${count === 1 ? '' : 's'}`}
            accessibilityState={{ checked: candidateCount === count }}
            style={[styles.countChip, candidateCount === count && styles.countChipSelected]}
            onPress={() => updateDraft((current) => ({
              ...current,
              candidateCount: count,
            }))}>
            <Text style={[styles.countText, candidateCount === count && styles.countTextSelected]}>{count}</Text>
          </Pressable>
        ))}
      </View>

      {activeReferences.length > 0 && !referenceVisualsReady && (
        <Text style={styles.reviewReadiness}>{referenceVisualFailed
          ? 'Your drawing preview could not be shown. Replace or remove it before generating designs.'
          : 'Checking your drawing before generation…'}</Text>
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
        <Text style={styles.primaryButtonText}>{busy ? 'Generating designs…' : `Generate ${candidateCount} design${candidateCount === 1 ? '' : 's'}`}</Text>
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
  modeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 22 },
  modeCard: { flexGrow: 1, flexBasis: 220, minHeight: 88, borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, padding: 16, justifyContent: 'center' },
  modeCardSelected: { borderColor: '#6f52d9', borderWidth: 2, backgroundColor: '#f7f4ff' },
  modeTitle: { color: theme.ink, fontSize: 15, fontWeight: '800' },
  modeHelp: { color: theme.faint, fontSize: 11, lineHeight: 16, marginTop: 5 },
  inputLabel: { color: theme.ink, fontSize: 13, fontWeight: '700', marginTop: 22 },
  prompt: { minHeight: 112, borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, color: theme.ink, fontSize: 16, lineHeight: 23, padding: 16, marginTop: 22, textAlignVertical: 'top' },
  promptCompact: { minHeight: 88, borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, color: theme.ink, fontSize: 15, lineHeight: 22, padding: 16, marginTop: 8, textAlignVertical: 'top' },
  sectionTitle: { color: theme.ink, fontSize: 14, fontWeight: '700', marginTop: 22 },
  sectionHelp: { color: theme.faint, fontSize: 11, lineHeight: 16, marginTop: 4 },
  countRow: { flexDirection: 'row', gap: 8, marginTop: 10 },
  countChip: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center', borderRadius: radius.pill, borderWidth: 1, borderColor: theme.line, backgroundColor: theme.card },
  countChipSelected: { backgroundColor: '#6f52d9', borderColor: '#6f52d9' },
  countText: { color: theme.faint, fontWeight: '700' },
  countTextSelected: { color: '#ffffff' },
  masterSourceCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, padding: 14, marginTop: 14, flexDirection: 'row', alignItems: 'center', gap: 12 },
  addSourceButton: { minHeight: 44, justifyContent: 'center', borderRadius: radius.pill, backgroundColor: '#eee9ff', paddingHorizontal: 14, paddingVertical: 9 },
  addSourceButtonText: { color: '#5c3fc0', fontSize: 11, fontWeight: '800' },
  referenceThumbnail: { width: 52, height: 52, borderRadius: radius.sm, backgroundColor: theme.line },
  referenceCopy: { flex: 1 },
  referenceTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  referenceHelp: { color: theme.faint, fontSize: 10, lineHeight: 15, marginTop: 3 },
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
  candidateSelect: { width: '100%' },
  candidateImage: { width: '100%', aspectRatio: 1, backgroundColor: '#ebe7ef' },
  imageFallback: { width: '100%', aspectRatio: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#ebe7ef' },
  imageFallbackText: { color: theme.faint, fontSize: 11 },
  reviewReadiness: { color: '#745513', fontSize: 11, lineHeight: 17, marginTop: 12 },
  candidateCopy: { padding: 12 },
  candidateTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  candidateMeta: { color: theme.faint, fontSize: 10, marginTop: 3 },
  footerActions: { gap: 0 },
});
