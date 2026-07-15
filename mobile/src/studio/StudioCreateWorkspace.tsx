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
import { StudioComparisonInspector } from './StudioComparisonInspector';

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
}

export type StudioCreateCandidateCount = 1 | 2 | 3 | 4;

/**
 * The complete pre-generation Create setup. The master reference owns its
 * explicit sourceKind so source truth cannot drift from a parallel field.
 */
export interface StudioCreateDraft {
  sentence: string;
  references: readonly StudioCreateReference[];
  candidateCount: StudioCreateCandidateCount;
}

export const EMPTY_STUDIO_CREATE_DRAFT: StudioCreateDraft = {
  sentence: '',
  references: [],
  candidateCount: 2,
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

const labelForRole = (role: CreateReferenceRole) => (
  STUDIO_CREATE_REFERENCE_CONTROLS.find((item) => item.role === role)?.label ?? role
);

const referencePreviewUri = (reference: StudioCreateReference): string => (
  `data:${reference.mediaType};base64,${reference.imageBase64}`
);

const MAX_RETAINED_VARIATIONS = 3;

const candidateVisualKey = (candidate: AssetSummary): string | null => (
  candidate.image_url === null
    ? null
    : `create-candidate:${candidate.asset_id}:${candidate.image_url}`
);

const sourceVisualKey = (source: AssetSummary | null): string | null => (
  source?.image_url == null
    ? null
    : `create-source:${source.asset_id}:${source.image_url}`
);

const SOURCE_KIND_LABELS: Readonly<Record<CreativeSourceKind, string>> = {
  drawing: 'Drawing',
  photograph: 'Photograph',
  finished_render: 'Finished render',
};

/**
 * Resolve the geometry source that a candidate was derived from. The selected
 * crop is the most faithful comparison authority; a role-labeled reference
 * board is advisory and must never be presented as the master geometry.
 */
export function creativeReviewSource(
  project: ProjectDetail,
  candidate: AssetSummary | null,
): AssetSummary | null {
  if (candidate === null) return null;
  const parent = candidate.parent_asset_id === null
    ? null
    : project.assets.find((asset) => asset.asset_id === candidate.parent_asset_id) ?? null;
  if (parent?.capability === 'CREATIVE_SOURCE_REGION') return parent;
  if (parent?.capability === 'CREATIVE_SOURCE') return parent;
  return project.assets.find((asset) => asset.capability === 'CREATIVE_SOURCE_REGION')
    ?? project.assets.find((asset) => asset.capability === 'CREATIVE_SOURCE')
    ?? null;
}

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
  const [setupOpen, setSetupOpen] = useState(
    (controlledDraft?.references.length ?? initialReferences.length) > 0,
  );
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
      .filter((candidate) => (
        candidate.asset_id !== selectedAssetId
        && visualReview.isReady(candidateVisualKey(candidate))
      ))
      .slice(0, MAX_RETAINED_VARIATIONS)
  ), [candidates, selectedAssetId, visualReview.isReady]);
  const selectedCandidate = candidates.find(
    (candidate) => candidate.asset_id === selectedAssetId,
  ) ?? null;
  const selectedVisualKey = selectedCandidate === null ? null : candidateVisualKey(selectedCandidate);
  const reviewSource = project === null ? null : creativeReviewSource(project, selectedCandidate);
  const reviewSourceVisualKey = sourceVisualKey(reviewSource);
  const requiredDecisionVisualKeys = reviewSource === null
    ? [selectedVisualKey]
    : [reviewSourceVisualKey, selectedVisualKey];
  const decisionVisualsReady = selectedAssetId !== null
    && selectedCandidate !== null
    && visualReview.allReady(requiredDecisionVisualKeys);
  const selectedVisualFailed = selectedAssetId !== null
    && visualReview.anyFailed([selectedVisualKey]);
  const sourceVisualFailed = reviewSource !== null
    && visualReview.anyFailed([reviewSourceVisualKey]);
  const masterReference = references.find((reference) => reference.role === 'master_geometry') ?? null;
  const sourceKind: CreativeSourceKind | null = masterReference?.sourceKind ?? null;
  const secondaryReferences = references.filter(
    (reference): reference is StudioCreateReference & { role: SecondaryCreateReferenceRole } => (
      reference.role !== 'master_geometry'
    ),
  );
  const referenceVisualKeys = references.map(referenceVisualKey);
  const referenceVisualsReady = referenceVisualKeys.length === 0
    || visualReview.allReady(referenceVisualKeys);
  const referenceVisualFailed = visualReview.anyFailed(referenceVisualKeys);
  const canCreate = !busy && (sentence.trim().length > 0 || masterReference !== null)
    && (masterReference === null || sourceKind !== null)
    && referenceVisualsReady;

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
        references: [
          ...current.references.filter((item) => item.role !== role),
          { ...reference, role },
        ],
      }));
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
    const submittedSecondary = submittedReferences.filter(
      (reference): reference is StudioCreateReference & { role: SecondaryCreateReferenceRole } => (
        reference.role !== 'master_geometry'
      ),
    );
    const submittedSourceKind = submittedMaster?.sourceKind ?? null;
    const prompt = submittedDraft.sentence.trim();
    if ((!prompt && submittedMaster === null) || busy) return;
    const requestId = generationRequestIdRef.current + 1;
    generationRequestIdRef.current = requestId;
    const requestOwner = owner;
    setBusy(true);
    setError(null);
    setProject(null);
    setSelectedAssetId(null);
    setSelectionStudioJobId(null);
    const sourceTitle = prompt || submittedMaster?.label || 'Untitled reference study';
    const title = sourceTitle.length > 64 ? `${sourceTitle.slice(0, 61)}…` : sourceTitle;
    const result = submittedMaster === null
      ? await gateway.createFromPrompt({
          prompt,
          ...(submittedSecondary.length === 0 ? {} : {
            references: submittedSecondary.map((reference) => ({
              role: reference.role,
              image_base64: reference.imageBase64,
              media_type: reference.mediaType,
            })),
          }),
          variation_count: submittedDraft.candidateCount,
          owner: requestOwner,
          title,
        })
      : await gateway.createFromDrawing({
          image_base64: submittedMaster.imageBase64,
          source_kind: submittedSourceKind!,
          media_type: submittedMaster.mediaType,
          ...(prompt.length === 0 ? {} : { instruction: prompt }),
          references: submittedSecondary.map((reference) => ({
            role: reference.role,
            image_base64: reference.imageBase64,
            media_type: reference.mediaType,
          })),
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
        label: `Direction ${index + 1}`,
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
    setSetupOpen(false);
    setProject(null);
    setSelectedAssetId(null);
    setSelectionStudioJobId(null);
  };

  if (project !== null) {
    return (
      <ScrollView style={styles.root} contentContainerStyle={styles.content}>
        <Text style={styles.eyebrow}>CHOOSE A DIRECTION</Text>
        <Text style={styles.title}>Choose a direction to continue</Text>
        <Text style={styles.body}>
          These are visual directions—not measurements or production instructions.
        </Text>
        <Text style={styles.retainedCopy}>
          Choose what to refine now. Up to three other directions you preview will be organized as variations, and the full generated set stays preserved in this review.
        </Text>
        {reviewSource !== null && selectedCandidate !== null && (
          <View style={styles.sourceComparisonBlock}>
            <Text style={styles.comparisonEyebrow}>SOURCE FIDELITY CHECK</Text>
            <Text style={styles.comparisonTitle}>Compare before choosing</Text>
            <Text style={styles.comparisonHelp}>
              Check silhouette, proportions, setting, and construction against the uploaded source. Supporting style references are advisory only.
            </Text>
            {reviewSource.image_url !== null && selectedCandidate.image_url !== null ? (
              <StudioComparisonInspector
                before={{
                  label: reviewSource.source_kind === undefined
                    || reviewSource.source_kind === null
                    ? 'Uploaded visual'
                    : SOURCE_KIND_LABELS[reviewSource.source_kind],
                  roleLabel: 'Starting source',
                  accessibilityLabel: 'Create starting source',
                  source: { uri: reviewSource.image_url },
                  onLoad: () => visualReview.markReady(reviewSourceVisualKey),
                  onError: () => visualReview.markFailed(reviewSourceVisualKey),
                }}
                after={{
                  label: `Direction ${candidates.findIndex((candidate) => candidate.asset_id === selectedAssetId) + 1}`,
                  roleLabel: 'Selected direction',
                  accessibilityLabel: 'Create selected direction comparison',
                  source: { uri: selectedCandidate.image_url },
                  onLoad: () => visualReview.markReady(selectedVisualKey),
                  onError: () => visualReview.markFailed(selectedVisualKey),
                }}
                compactHeight={240}
                inspectionTitle="Compare source fidelity"
                inspectionHelp="Inspect the uploaded geometry source and selected visual direction at matching areas before creating the first immutable revision."
              />
            ) : (
              <View style={styles.sourceUnavailable}>
                <Text style={styles.sourceUnavailableText}>
                  The starting source is recorded, but its comparison image is unavailable. Reopen this review from Activity or try again before choosing.
                </Text>
              </View>
            )}
          </View>
        )}
        <View style={styles.candidateGrid}>
          {candidates.map((candidate, index) => {
            const selected = selectedAssetId === candidate.asset_id;
            const willRetain = intendedRetainedCandidates.some(
              (item) => item.asset_id === candidate.asset_id,
            );
            const candidateStatus = selected
              ? 'Selected to refine'
              : willRetain
                ? 'Will save as a variation'
                : 'Preserved in review set';
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
                    accessibilityLabel={`Direction ${index + 1} preview`}
                    inspectionLabel={`Direction ${index + 1}`}
                    source={{ uri: candidate.image_url }}
                    onLoad={() => visualReview.markReady(visualKey)}
                    onError={() => visualReview.markFailed(visualKey)}
                    style={styles.candidateImage}
                  />
                )}
                <Pressable
                  accessibilityRole="radio"
                  accessibilityState={{ checked: selected, disabled: candidateDisabled }}
                  accessibilityLabel={`Direction ${index + 1}`}
                  accessibilityHint={candidateStatus}
                  disabled={candidateDisabled}
                  style={styles.candidateSelect}
                  onPress={() => {
                    if (candidateDisabled) return;
                    setSelectedAssetId(candidate.asset_id);
                  }}>
                  <View style={styles.candidateCopy}>
                    <Text style={styles.candidateTitle}>Direction {index + 1}</Text>
                    <Text style={styles.candidateMeta}>{candidateStatus}</Text>
                  </View>
                </Pressable>
              </View>
            );
          })}
        </View>
        {!decisionVisualsReady && selectedAssetId !== null && (
          <Text style={styles.reviewReadiness}>
            {sourceVisualFailed
              ? 'The starting source could not be displayed. Reopen this review from Activity or try loading it again before continuing.'
              : selectedVisualFailed
              ? 'The selected direction could not be displayed. Choose another direction or try loading it again before continuing.'
              : reviewSource !== null
                ? 'Wait for both the starting source and selected direction to finish loading before continuing.'
                : 'Wait for the selected direction to finish loading before continuing.'}
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
            <Text style={styles.secondaryButtonText}>Leave in Activity &amp; start another</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ disabled: busy || !decisionVisualsReady }}
            style={[styles.primaryButton, (busy || !decisionVisualsReady) && styles.buttonDisabled]}
            disabled={busy || !decisionVisualsReady}
            onPress={() => void continueWithSelection()}>
            <Text style={styles.primaryButtonText}>{busy
              ? 'Saving directions…'
              : `Continue with Direction ${candidates.findIndex((candidate) => candidate.asset_id === selectedAssetId) + 1}`}</Text>
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
        onChangeText={(nextSentence) => updateDraft((current) => ({
          ...current,
          sentence: nextSentence,
        }))}
        style={styles.prompt}
      />

      <View style={styles.masterSourceCard}>
        {masterReference !== null && (
          <StudioReviewImage
            accessibilityLabel="Visual source preview"
            inspectionLabel={`Master geometry · ${masterReference.label}`}
            source={{ uri: referencePreviewUri(masterReference) }}
            onLoad={() => visualReview.markReady(referenceVisualKey(masterReference))}
            onError={() => visualReview.markFailed(referenceVisualKey(masterReference))}
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
              onPress={() => updateDraft((current) => ({
                ...current,
                references: current.references.filter(
                  (item) => item.role !== 'master_geometry',
                ),
              }))}>
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
                onPress={() => updateDraft((current) => ({
                  ...current,
                  references: current.references.map((reference) => (
                    reference.role === 'master_geometry'
                      ? { ...reference, sourceKind: kind }
                      : reference
                  )),
                }))}>
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
            {candidateCount} direction{candidateCount === 1 ? '' : 's'} · {secondaryReferences.length === 0
              ? 'No supporting references'
              : `${secondaryReferences.length} supporting reference${secondaryReferences.length === 1 ? '' : 's'}`}
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
                onPress={() => updateDraft((current) => ({
                  ...current,
                  candidateCount: count,
                }))}>
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
              const advisoryInputReady = sentence.trim().length > 0 || masterReference !== null;
              return (
                <View key={role} style={styles.referenceRow}>
                  {reference !== undefined && (
                    <StudioReviewImage
                      accessibilityLabel={`${label} reference preview`}
                      inspectionLabel={`${label} · ${reference.label}`}
                      source={{ uri: referencePreviewUri(reference) }}
                      onLoad={() => visualReview.markReady(referenceVisualKey(reference))}
                      onError={() => visualReview.markFailed(referenceVisualKey(reference))}
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
                      accessibilityHint={!advisoryInputReady
                        ? 'Add a design sentence or visual source before adding this supporting reference.'
                        : help}
                      accessibilityState={{ disabled: !advisoryInputReady }}
                      disabled={!advisoryInputReady}
                      style={[
                        styles.referenceButton,
                        !advisoryInputReady && styles.buttonDisabled,
                      ]}
                      onPress={() => requestReference(role)}>
                      <Text style={styles.referenceButtonText}>
                        {!advisoryInputReady ? 'Add an idea first' : 'Add'}
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
                        onPress={() => updateDraft((current) => ({
                          ...current,
                          references: current.references.filter((item) => item.id !== reference.id),
                        }))}>
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

      {masterReference === null
        && secondaryReferences.length > 0
        && sentence.trim().length === 0 && (
        <View style={styles.limitNotice}>
          <Text style={styles.limitTitle}>Add a design idea</Text>
          <Text style={styles.limitBody}>
            Supporting references can guide material, construction, or brand direction after you add a design sentence or one visual source. They do not define the jewelry on their own.
          </Text>
        </View>
      )}

      {references.length > 0 && !referenceVisualsReady && (
        <Text style={styles.reviewReadiness}>{referenceVisualFailed
          ? 'A reference preview could not be shown. Replace or remove it before creating directions.'
          : 'Checking attached references before creation…'}</Text>
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
  candidateSelect: { width: '100%' },
  candidateImage: { width: '100%', aspectRatio: 1, backgroundColor: '#ebe7ef' },
  imageFallback: { width: '100%', aspectRatio: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#ebe7ef' },
  imageFallbackText: { color: theme.faint, fontSize: 11 },
  sourceComparisonBlock: { marginTop: 20 },
  comparisonEyebrow: { color: '#6f52d9', fontSize: 10, fontWeight: '800', letterSpacing: 1.2 },
  comparisonTitle: { color: theme.ink, fontSize: 17, fontWeight: '800', marginTop: 5 },
  comparisonHelp: { color: theme.faint, fontSize: 11, lineHeight: 17, marginTop: 5, marginBottom: 10 },
  sourceUnavailable: { borderWidth: 1, borderColor: '#c99f48', borderRadius: radius.md, backgroundColor: '#fff9e9', padding: 13 },
  sourceUnavailableText: { color: '#745513', fontSize: 11, lineHeight: 17 },
  reviewReadiness: { color: '#745513', fontSize: 11, lineHeight: 17, marginTop: 12 },
  candidateCopy: { padding: 12 },
  candidateTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  candidateMeta: { color: theme.faint, fontSize: 10, marginTop: 3 },
  footerActions: { gap: 0 },
});
