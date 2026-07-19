import React, {
  type Dispatch, type SetStateAction, useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, useWindowDimensions, View,
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
export type StudioBalanceChoice = 'symmetrical' | 'asymmetrical';

export type StudioMetalChoice =
  | 'yellow_gold' | 'white_gold' | 'rose_gold' | 'platinum' | 'sterling_silver';
export type StudioFinishChoice =
  | 'high_polish' | 'satin' | 'brushed' | 'hammered';
export type StudioPaletteChoice =
  | 'warm_neutral' | 'cool_minimal' | 'soft_pastel' | 'rich_jewel' | 'high_contrast';
export type StudioBrandMoodChoice =
  | 'quiet_luxury' | 'sculptural_modern' | 'romantic_heirloom'
  | 'art_deco' | 'organic' | 'bold_editorial';

export interface StudioCreateGuidance {
  material?: {
    metal?: StudioMetalChoice;
    finish?: StudioFinishChoice;
    palette?: StudioPaletteChoice;
    note?: string;
  };
  detail?: { note?: string };
  brand?: { mood?: StudioBrandMoodChoice; note?: string };
}

/**
 * The complete pre-generation Create setup. The master reference owns its
 * explicit sourceKind so source truth cannot drift from a parallel field.
 */
export interface StudioCreateDraft {
  sentence: string;
  references: readonly StudioCreateReference[];
  candidateCount: StudioCreateCandidateCount;
  /** Defaults to symmetrical for text-only creation; visual sources remain authoritative. */
  balance?: StudioBalanceChoice;
  /** Optional designer choices. Images remain separately role-labeled references. */
  guidance?: StudioCreateGuidance;
}

export const EMPTY_STUDIO_CREATE_DRAFT: StudioCreateDraft = {
  sentence: '',
  references: [],
  candidateCount: 1,
  balance: 'symmetrical',
};

/**
 * Keep designer-facing balance language separate from the internal quality
 * contract. Text-only creation makes the selected intent explicit, while an
 * uploaded design always owns its visible left/right relationship.
 */
export const composeCreateBalanceInstruction = (
  base: string,
  balance: StudioBalanceChoice,
  sourceAuthoritative: boolean,
): string => {
  if (sourceAuthoritative) {
    return `${base}\n\nDESIGN BALANCE: Preserve the source balance. Follow the uploaded design's visible left and right relationship, whether symmetrical or intentionally asymmetrical; the visual source is authoritative.`;
  }
  if (balance === 'asymmetrical') {
    return `${base}\n\nDESIGN BALANCE: Intentionally asymmetrical. Allow deliberate left and right differences requested by the designer.`;
  }
  return `${base}\n\nDESIGN BALANCE: Symmetrical. Mirror corresponding left and right design elements, including motif sequence, materials, pavé coverage, stones, spacing, scale, and connections.`;
};

const METAL_CHOICES = [
  ['yellow_gold', 'Yellow gold'],
  ['white_gold', 'White gold'],
  ['rose_gold', 'Rose gold'],
  ['platinum', 'Platinum'],
  ['sterling_silver', 'Sterling silver'],
] as const satisfies readonly (readonly [StudioMetalChoice, string])[];

const FINISH_CHOICES = [
  ['high_polish', 'High polish'],
  ['satin', 'Satin'],
  ['brushed', 'Brushed'],
  ['hammered', 'Hammered'],
] as const satisfies readonly (readonly [StudioFinishChoice, string])[];

const PALETTE_CHOICES = [
  ['warm_neutral', 'Warm neutral'],
  ['cool_minimal', 'Cool minimal'],
  ['soft_pastel', 'Soft pastel'],
  ['rich_jewel', 'Rich jewel tones'],
  ['high_contrast', 'High contrast'],
] as const satisfies readonly (readonly [StudioPaletteChoice, string])[];

const BRAND_MOOD_CHOICES = [
  ['quiet_luxury', 'Quiet luxury'],
  ['sculptural_modern', 'Sculptural modern'],
  ['romantic_heirloom', 'Romantic heirloom'],
  ['art_deco', 'Art Deco'],
  ['organic', 'Organic'],
  ['bold_editorial', 'Bold editorial'],
] as const satisfies readonly (readonly [StudioBrandMoodChoice, string])[];

const choiceLabel = <T extends string>(
  choices: readonly (readonly [T, string])[], value: T | undefined,
): string | null => choices.find(([id]) => id === value)?.[1] ?? null;

const cleanGuidanceNote = (note: string | undefined): string | null => {
  const cleaned = note?.trim();
  return cleaned ? cleaned : null;
};

/**
 * Manual guidance is compiled into the provider instruction, while uploaded
 * images keep their separate role-labeled reference contract. The wording is
 * deliberately non-authoritative so style and brand cannot redefine geometry.
 */
export const composeCreateInstruction = (
  base: string, guidance: StudioCreateGuidance | undefined,
): string => {
  if (guidance === undefined) return base;
  const materialParts = [
    choiceLabel(METAL_CHOICES, guidance.material?.metal),
    choiceLabel(FINISH_CHOICES, guidance.material?.finish),
    choiceLabel(PALETTE_CHOICES, guidance.material?.palette),
    cleanGuidanceNote(guidance.material?.note),
  ].filter((item): item is string => item !== null);
  const detailNote = cleanGuidanceNote(guidance.detail?.note);
  const brandParts = [
    choiceLabel(BRAND_MOOD_CHOICES, guidance.brand?.mood),
    cleanGuidanceNote(guidance.brand?.note),
  ].filter((item): item is string => item !== null);
  const lines = [
    ...(materialParts.length === 0 ? [] : [
      `MATERIAL & FINISH (appearance only; keep geometry): ${materialParts.join('; ')}`,
    ]),
    ...(detailNote === null ? [] : [
      `DETAIL (visual only; not a production fact): ${detailNote}`,
    ]),
    ...(brandParts.length === 0 ? [] : [
      `BRAND MOOD (visual language only; no copied branding or geometry): ${brandParts.join('; ')}`,
    ]),
  ];
  return lines.length === 0
    ? base
    : `${base}\n\nOPTIONAL DESIGNER GUIDANCE:\n${lines.join('\n')}`;
};

/**
 * Clear consumed inputs after generation without making the review rail
 * contradict the result set that is still on canvas. A truly fresh request is
 * reset to EMPTY_STUDIO_CREATE_DRAFT when the review is cleared.
 */
export const draftAfterGeneration = (
  current: StudioCreateDraft,
  submitted: StudioCreateDraft,
): StudioCreateDraft => (
  current === submitted
    ? { ...EMPTY_STUDIO_CREATE_DRAFT, candidateCount: submitted.candidateCount }
    : current
);

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
  /** Commits the selected direction and returns to Studio without opening Refine. */
  onSaveForLater?: (selection: StudioCreateSelection) => void;
  /** Commits the selected direction and opens Refine. */
  onSave: (selection: StudioCreateSelection) => void;
}

const labelForRole = (role: CreateReferenceRole) => (
  STUDIO_CREATE_REFERENCE_CONTROLS.find((item) => item.role === role)?.label ?? role
);

const UPLOAD_ONLY_INSTRUCTIONS: Readonly<Record<CreativeSourceKind, string>> = {
  drawing: 'Turn this drawing into a polished jewelry render while preserving its visible silhouette, proportions, stone layout, and construction.',
  photograph: 'Create a polished jewelry render from this photograph while preserving the visible piece, proportions, stone layout, materials, and construction.',
  finished_render: 'Create a polished jewelry direction from this finished render while preserving its visible silhouette, proportions, stone layout, materials, and construction.',
};

const UPLOAD_ONLY_HELP: Readonly<Record<CreativeSourceKind, string>> = {
  drawing: 'A sentence is optional. Facetta will interpret the drawing as polished jewelry while preserving its recognizable design intent.',
  photograph: 'A sentence is optional. Facetta will preserve the photographed piece and turn it into a polished design render.',
  finished_render: 'A sentence is optional. Facetta will preserve the finished render as the starting design.',
};

/**
 * An upload can define the design without requiring the designer to write a
 * sentence. Keep that path explicit and source-aware rather than silently
 * falling through to a generic transport default.
 */
export const uploadOnlyInstruction = (sourceKind: CreativeSourceKind): string => (
  UPLOAD_ONLY_INSTRUCTIONS[sourceKind]
);

const referencePreviewUri = (reference: StudioCreateReference): string => (
  `data:${reference.mediaType};base64,${reference.imageBase64}`
);

const MAX_RETAINED_VARIATIONS = 3;

type CandidateView = 'primary' | 'three_quarter';

const candidateView = (candidate: AssetSummary, view: CandidateView) => {
  const explicit = candidate.views?.find((item) => item.view === view);
  if (explicit !== undefined) return explicit;
  if (view === 'primary' && candidate.image_url !== null) {
    return {
      asset_id: candidate.asset_id,
      view: 'primary' as const,
      media_type: candidate.media_type,
      sha256: '',
      image_url: candidate.image_url,
    };
  }
  return null;
};

const candidateVisualKey = (
  candidate: AssetSummary, view: CandidateView = 'primary',
): string | null => {
  const visual = candidateView(candidate, view);
  return visual === null
    ? null
    : `create-candidate:${candidate.asset_id}:${visual.view}:${visual.asset_id}:${visual.image_url}`;
};

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
  onSaveForLater,
  onSave,
}: StudioCreateWorkspaceProps) {
  const [localDraft, setLocalDraft] = useState<StudioCreateDraft>(() => ({
    sentence: initialSentence,
    references: [...initialReferences],
    candidateCount: 1,
    balance: 'symmetrical',
  }));
  const createDraft = controlledDraft ?? localDraft;
  const { sentence, references, candidateCount } = createDraft;
  const balance = createDraft.balance ?? 'symmetrical';
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
  const composerScrollRef = useRef<ScrollView | null>(null);
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
  const [guidancePanelOpen, setGuidancePanelOpen] = useState<Readonly<Record<
    SecondaryCreateReferenceRole, boolean
  >>>({
    material_style: false,
    construction_detail: false,
    brand_direction: false,
  });
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
  const [busyMode, setBusyMode] = useState<'create' | 'save' | null>(null);
  const busy = busyMode !== null;
  const [error, setError] = useState<string | null>(null);
  const [discardConfirmationOpen, setDiscardConfirmationOpen] = useState(false);
  const [activeCandidateView, setActiveCandidateView] = useState<CandidateView>('primary');
  const { width } = useWindowDimensions();
  const isWideWorkspace = Platform.OS === 'web' && width >= 1000;

  const candidates = useMemo(() => project === null ? [] : creativeCandidates(project), [project]);
  const hasSharedComparisonViews = candidates.length > 0 && candidates.every((candidate) => (
    candidateView(candidate, 'primary') !== null
    && candidateView(candidate, 'three_quarter') !== null
  ));
  useEffect(() => {
    if (!hasSharedComparisonViews) setActiveCandidateView('primary');
  }, [hasSharedComparisonViews]);
  const partialDirectionMessage = project !== null && candidates.length < candidateCount
    ? `${candidates.length} of ${candidateCount} requested directions ${candidates.length === 1 ? 'is' : 'are'} ready. The other ${candidateCount - candidates.length} failed quality or provider checks and will not be charged.`
    : null;
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
  const decisionVisualsReady = selectedAssetId !== null
    && selectedCandidate !== null
    && visualReview.allReady([selectedVisualKey]);
  const selectedVisualFailed = selectedAssetId !== null
    && visualReview.anyFailed([selectedVisualKey]);
  const masterReference = references.find((reference) => reference.role === 'master_geometry') ?? null;
  const sourceKind: CreativeSourceKind | null = masterReference?.sourceKind ?? null;
  const secondaryReferences = references.filter(
    (reference): reference is StudioCreateReference & { role: SecondaryCreateReferenceRole } => (
      reference.role !== 'master_geometry'
    ),
  );
  const guidance = createDraft.guidance ?? {};
  const manualGuidanceCount = [
    guidance.material?.metal,
    guidance.material?.finish,
    guidance.material?.palette,
    cleanGuidanceNote(guidance.material?.note),
    cleanGuidanceNote(guidance.detail?.note),
    guidance.brand?.mood,
    cleanGuidanceNote(guidance.brand?.note),
  ].filter((item) => item !== undefined && item !== null).length;
  const optionalGuidanceCount = secondaryReferences.length + manualGuidanceCount;
  const balanceSummary = masterReference === null
    ? balance === 'symmetrical' ? 'Symmetrical' : 'Asymmetrical'
    : 'Preserve source balance';
  const optionalGuidanceSummary = `${balanceSummary} · ${optionalGuidanceCount === 0
    ? 'No extra choices'
    : `${optionalGuidanceCount} extra choice${optionalGuidanceCount === 1 ? '' : 's'}`}`;
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

  const updateGuidance = (
    update: (current: StudioCreateGuidance) => StudioCreateGuidance,
  ): void => updateDraft((current) => ({
    ...current,
    guidance: update(current.guidance ?? {}),
  }));

  const toggleMaterialGuidanceChoice = (
    field: 'metal' | 'finish' | 'palette',
    value: StudioMetalChoice | StudioFinishChoice | StudioPaletteChoice,
  ): void => updateGuidance((current) => ({
    ...current,
    material: {
      ...current.material,
      [field]: current.material?.[field] === value ? undefined : value,
    },
  }));

  const toggleBrandMoodChoice = (value: StudioBrandMoodChoice): void => (
    updateGuidance((current) => ({
      ...current,
      brand: {
        ...current.brand,
        mood: current.brand?.mood === value ? undefined : value,
      },
    }))
  );

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
    const providerInstruction = composeCreateInstruction(
      composeCreateBalanceInstruction(
        prompt || (submittedSourceKind === null
        ? ''
        : uploadOnlyInstruction(submittedSourceKind)),
        submittedDraft.balance ?? 'symmetrical',
        submittedMaster !== null,
      ),
      submittedDraft.guidance,
    );
    if ((!prompt && submittedMaster === null) || busy) return;
    const requestId = generationRequestIdRef.current + 1;
    generationRequestIdRef.current = requestId;
    const requestOwner = owner;
    setBusyMode('create');
    setError(null);
    const sourceTitle = prompt || submittedMaster?.label || 'Untitled reference study';
    const title = sourceTitle.length > 64 ? `${sourceTitle.slice(0, 61)}…` : sourceTitle;
    const result = submittedMaster === null
      ? await gateway.createFromPrompt({
          prompt: providerInstruction,
          ...(submittedSecondary.length === 0 ? {} : {
            references: submittedSecondary.map((reference) => ({
              role: reference.role,
              image_base64: reference.imageBase64,
              media_type: reference.mediaType,
            })),
          }),
          variation_count: submittedDraft.candidateCount,
          comparison_views: ['three_quarter'],
          owner: requestOwner,
          title,
        })
      : await gateway.createFromDrawing({
          image_base64: submittedMaster.imageBase64,
          source_kind: submittedSourceKind!,
          media_type: submittedMaster.mediaType,
          instruction: providerInstruction,
          references: submittedSecondary.map((reference) => ({
            role: reference.role,
            image_base64: reference.imageBase64,
            media_type: reference.mediaType,
          })),
          variation_count: submittedDraft.candidateCount,
          comparison_views: ['three_quarter'],
          owner: requestOwner,
          title,
        });
    if (!mountedRef.current
      || generationRequestIdRef.current !== requestId
      || ownerRef.current !== requestOwner) return;
    setBusyMode(null);
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
    composerScrollRef.current?.scrollTo({ y: 0, animated: true });
    onGenerationSucceeded?.({
      owner: requestOwner,
      projectId: result.data.root_id,
      submittedDraft,
    });
  };

  const continueWithSelection = async (destination: 'later' | 'refine'): Promise<void> => {
    if (project === null || selectedAssetId === null || busy || !decisionVisualsReady) return;

    const requestId = selectionRequestIdRef.current + 1;
    selectionRequestIdRef.current = requestId;
    const requestOwner = owner;
    const requestProjectId = project.root_id;
    const requestSelectedAssetId = selectedAssetId;
    setBusyMode('save');
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
      setBusyMode(null);
      setError(designerErrorMessage(committed.error, 'create'));
      return;
    }

    setBusyMode(null);
    setProject(committed.data.project);
    setSelectionStudioJobId(null);
    const selection = {
      project: committed.data.project,
      selectedAssetId: requestSelectedAssetId,
    };
    if (destination === 'later' && onSaveForLater !== undefined) {
      onSaveForLater(selection);
      return;
    }
    onSave(selection);
  };

  const leaveReviewAndStartAnother = (): void => {
    if (busy) return;
    selectionRequestIdRef.current += 1;
    setError(null);
    setSetupOpen(false);
    updateDraft((current) => ({
      ...current,
      candidateCount: 1,
    }));
    setProject(null);
    setSelectedAssetId(null);
    setSelectionStudioJobId(null);
  };

  const discardConfirmation = (
    <Modal
      accessibilityViewIsModal
      animationType="fade"
      onRequestClose={() => setDiscardConfirmationOpen(false)}
      presentationStyle="overFullScreen"
      transparent
      visible={discardConfirmationOpen}>
      <View style={styles.confirmationBackdrop}>
        <View style={styles.confirmationDialog}>
          <Text style={styles.eyebrow}>START OVER</Text>
          <Text style={styles.confirmationTitle}>Clear these results?</Text>
          <Text style={styles.confirmationBody}>
            These directions will leave this canvas, but the generated review stays available in Activity.
          </Text>
          <View style={styles.confirmationActions}>
            <Pressable
              accessibilityRole="button"
              onPress={() => setDiscardConfirmationOpen(false)}
              style={[styles.secondaryButton, styles.confirmationButton]}>
              <Text style={styles.secondaryButtonText}>Keep results</Text>
            </Pressable>
            <Pressable
              accessibilityRole="button"
              onPress={() => {
                setDiscardConfirmationOpen(false);
                leaveReviewAndStartAnother();
              }}
              style={[styles.primaryButton, styles.confirmationButton]}>
              <Text style={styles.primaryButtonText}>Clear canvas</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );

  const comparisonViewControl = hasSharedComparisonViews ? (
    <View style={styles.viewControlRow}>
      <Text style={styles.viewControlLabel}>Compare every direction in the same view</Text>
      <View accessibilityRole="radiogroup" style={styles.viewControlButtons}>
        {([
          ['primary', 'Main view'],
          ['three_quarter', '3/4 view'],
        ] as const).map(([view, label]) => {
          const active = activeCandidateView === view;
          return (
            <Pressable
              key={view}
              accessibilityRole="radio"
              accessibilityLabel={label}
              accessibilityState={{ checked: active, disabled: busy }}
              disabled={busy}
              onPress={() => setActiveCandidateView(view)}
              style={[styles.viewControlButton, active && styles.viewControlButtonActive]}>
              <Text style={[styles.viewControlButtonText,
                active && styles.viewControlButtonTextActive]}>{label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  ) : null;

  if (project !== null && !isWideWorkspace) {
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
        {partialDirectionMessage !== null && (
          <Text style={styles.partialResults}>{partialDirectionMessage}</Text>
        )}
        {comparisonViewControl}
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
            const displayVisual = candidateView(candidate, activeCandidateView);
            const candidateDisabled = busy;
            return (
              <Pressable
                key={candidate.asset_id}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected, disabled: candidateDisabled }}
                accessibilityLabel={`Direction ${index + 1}`}
                accessibilityHint={candidateStatus}
                disabled={candidateDisabled}
                onPress={() => {
                  if (candidateDisabled) return;
                  setSelectedAssetId(candidate.asset_id);
                }}
                style={[styles.candidateCard, selected && styles.candidateCardSelected]}>
                {displayVisual === null ? (
                  <View style={styles.imageFallback}><Text style={styles.imageFallbackText}>Preview unavailable</Text></View>
                ) : (
                  <StudioReviewImage
                    accessibilityLabel={`Direction ${index + 1} preview`}
                    inspectionLabel={`Direction ${index + 1}`}
                    source={{ uri: displayVisual.image_url }}
                    onLoad={() => visualReview.markReady(candidateVisualKey(candidate, activeCandidateView))}
                    onError={() => visualReview.markFailed(candidateVisualKey(candidate, activeCandidateView))}
                    style={styles.candidateImage}
                  />
                )}
                <View style={styles.candidateCopy}>
                  <View style={styles.candidateTitleRow}>
                    <Text style={styles.candidateTitle}>Direction {index + 1}</Text>
                    {selected && (
                      <View style={styles.selectedBadge}>
                        <Text style={styles.selectedBadgeText}>✓ Selected</Text>
                      </View>
                    )}
                  </View>
                  <Text style={styles.candidateMeta}>{candidateStatus}</Text>
                </View>
              </Pressable>
            );
          })}
        </View>
        {!decisionVisualsReady && selectedAssetId !== null && (
          <Text style={styles.reviewReadiness}>
            {selectedVisualFailed
              ? 'The selected direction could not be displayed. Choose another direction or try loading it again before continuing.'
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
            onPress={() => setDiscardConfirmationOpen(true)}>
            <Text style={styles.secondaryButtonText}>Start over</Text>
          </Pressable>
          {onSaveForLater !== undefined && (
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ disabled: busy || !decisionVisualsReady }}
              style={[styles.secondaryButton, (busy || !decisionVisualsReady) && styles.buttonDisabled]}
              disabled={busy || !decisionVisualsReady}
              onPress={() => void continueWithSelection('later')}>
              <Text style={styles.secondaryButtonText}>Save for later</Text>
            </Pressable>
          )}
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ disabled: busy || !decisionVisualsReady }}
            style={[styles.primaryButton, (busy || !decisionVisualsReady) && styles.buttonDisabled]}
            disabled={busy || !decisionVisualsReady}
            onPress={() => void continueWithSelection('refine')}>
            <Text style={styles.primaryButtonText}>{busyMode === 'save'
              ? 'Saving directions…'
              : busyMode === 'create'
                ? 'Creating new directions…'
              : `Save & refine Direction ${candidates.findIndex((candidate) => candidate.asset_id === selectedAssetId) + 1}`}</Text>
          </Pressable>
        </View>
        {discardConfirmation}
      </ScrollView>
    );
  }

  return (
    <View style={[styles.root, isWideWorkspace && styles.wideWorkspace]}>
    <ScrollView
      ref={composerScrollRef}
      testID={isWideWorkspace ? 'create-web-composer' : undefined}
      style={isWideWorkspace ? styles.composerRail : styles.root}
      contentContainerStyle={isWideWorkspace ? styles.composerContent : styles.content}>
      <Text style={styles.eyebrow}>CREATE</Text>
      <Text style={styles.title}>Start your jewelry design</Text>
      <Text style={styles.body}>
        Choose one starting point: describe the piece in a sentence, or upload a visual source for Facetta to interpret.
      </Text>
      <Text style={styles.primaryInputLabel}>Describe it in one sentence</Text>
      <Text style={styles.primaryInputHelp}>A simple idea is enough. You can refine the result after it renders.</Text>
      <TextInput
        accessibilityLabel="Design sentence"
        maxLength={350}
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

      <View accessibilityElementsHidden style={styles.orDivider}>
        <View style={styles.orDividerLine} />
        <Text style={styles.orDividerText}>OR</Text>
        <View style={styles.orDividerLine} />
      </View>

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
          <Text style={styles.referenceTitle}>Upload a visual source</Text>
          <Text style={styles.referenceHelp}>{masterReference === null
            ? 'Rough pencil sketches are welcome. Facetta will interpret your drawing as polished jewelry while preserving its recognizable design intent. Photos and renders work too.'
            : masterReference.label}</Text>
        </View>
        {masterReference === null ? (
          <Pressable
            accessibilityRole="button"
            style={styles.addSourceButton}
            onPress={() => requestReference('master_geometry')}>
            <Text style={styles.addSourceButtonText}>Add a rough sketch, photo, or render</Text>
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
          {sourceKind !== null && sentence.trim().length === 0 && (
            <Text style={styles.sourceKindHelp}>{UPLOAD_ONLY_HELP[sourceKind]}</Text>
          )}
        </View>
      )}

      <View style={styles.outputOptionsCard}>
        <Text style={styles.secondaryEyebrow}>OUTPUT OPTIONS · OPTIONAL</Text>
        <View
          accessibilityRole="radiogroup"
          accessibilityLabel="Number of variations"
          style={styles.variationPicker}>
          <Text style={styles.outputOptionsTitle}>How many variations?</Text>
          <Text style={styles.sectionHelp}>Keep 1 for a single result, or choose up to 4 design alternatives.</Text>
          <View style={styles.countRow}>
            {([1, 2, 3, 4] as const).map((count) => (
              <Pressable
                key={count}
                accessibilityRole="radio"
                accessibilityLabel={`${count} variation${count === 1 ? '' : 's'}`}
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
        </View>
        <Text style={styles.creditEstimate}>
          {CREATE_CREDITS_PER_OUTPUT} credits per variation · {candidateCount} variation{candidateCount === 1 ? '' : 's'} = {candidateCount * CREATE_CREDITS_PER_OUTPUT} credits
        </Text>
      </View>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Optional guidance"
        accessibilityState={{ expanded: setupOpen }}
        onPress={() => setSetupOpen((current) => !current)}
        style={[styles.setupDisclosure, setupOpen && styles.setupDisclosureOpen]}>
        <View style={styles.setupDisclosureCopy}>
          <Text style={styles.setupDisclosureTitle}>Optional guidance</Text>
          <Text style={styles.setupDisclosureSummary}>
            {optionalGuidanceSummary}
          </Text>
        </View>
        <Text style={styles.disclosureGlyph}>{setupOpen ? '−' : '+'}</Text>
      </Pressable>

      {setupOpen && (
        <View style={styles.setupPanel}>
          <Text style={styles.sectionHelp}>
            Tap only what matters. Images are optional and open only when you choose Add image.
          </Text>
          <View style={styles.balanceSection}>
            <Text style={styles.referenceTitle}>Balance</Text>
            {masterReference === null ? (
              <>
                <View
                  accessibilityRole="radiogroup"
                  accessibilityLabel="Design balance"
                  style={styles.guidanceChipRow}>
                  {([
                    ['symmetrical', 'Symmetrical'],
                    ['asymmetrical', 'Asymmetrical'],
                  ] as const).map(([value, label]) => (
                    <Pressable
                      key={value}
                      accessibilityRole="radio"
                      accessibilityLabel={label}
                      accessibilityState={{ checked: balance === value }}
                      onPress={() => updateDraft((current) => ({
                        ...current,
                        balance: value,
                      }))}
                      style={[
                        styles.guidanceChip,
                        balance === value && styles.guidanceChipSelected,
                      ]}>
                      <Text style={[
                        styles.guidanceChipText,
                        balance === value && styles.guidanceChipTextSelected,
                      ]}>{label}</Text>
                    </Pressable>
                  ))}
                </View>
                <Text style={styles.referenceHelp}>
                  Symmetrical mirrors corresponding design and material details from side to side. Choose Asymmetrical only when you want intentional differences.
                </Text>
              </>
            ) : (
              <>
                <Text style={styles.balanceSourceValue}>Preserve source balance</Text>
                <Text style={styles.referenceHelp}>
                  Facetta follows the uploaded design, whether it is symmetrical or intentionally asymmetrical.
                </Text>
              </>
            )}
          </View>
          <View style={styles.referenceList}>
            {STUDIO_CREATE_REFERENCE_CONTROLS.filter(
              ({ role }) => role !== 'master_geometry',
            ).map(({ role: untypedRole, label, help }) => {
              const role = untypedRole as SecondaryCreateReferenceRole;
              const reference = references.find((item) => item.role === role);
              const open = guidancePanelOpen[role];
              const summary = role === 'material_style'
                ? [
                    choiceLabel(METAL_CHOICES, guidance.material?.metal),
                    choiceLabel(FINISH_CHOICES, guidance.material?.finish),
                    choiceLabel(PALETTE_CHOICES, guidance.material?.palette),
                    cleanGuidanceNote(guidance.material?.note),
                    reference?.label,
                  ].filter(Boolean).join(' · ')
                : role === 'construction_detail'
                  ? [cleanGuidanceNote(guidance.detail?.note), reference?.label]
                    .filter(Boolean).join(' · ')
                  : [
                      choiceLabel(BRAND_MOOD_CHOICES, guidance.brand?.mood),
                      cleanGuidanceNote(guidance.brand?.note),
                      reference?.label,
                    ].filter(Boolean).join(' · ');
              return (
                <View key={role} style={styles.guidanceSection}>
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${label} options`}
                    accessibilityState={{ expanded: open }}
                    onPress={() => setGuidancePanelOpen((current) => ({
                      ...current,
                      [role]: !current[role],
                    }))}
                    style={styles.guidanceSectionHeader}>
                    <View style={styles.referenceCopy}>
                      <Text style={styles.referenceTitle}>{label}</Text>
                      <Text style={styles.referenceHelp}>{summary || help}</Text>
                    </View>
                    <Text style={styles.guidanceChevron}>{open ? '−' : '+'}</Text>
                  </Pressable>
                  {open && (
                    <View style={styles.guidanceSectionBody}>
                      {role === 'material_style' && (
                        <>
                          {([
                            ['Metal color & material', METAL_CHOICES, guidance.material?.metal, 'metal'],
                            ['Surface & finish', FINISH_CHOICES, guidance.material?.finish, 'finish'],
                            ['Color palette', PALETTE_CHOICES, guidance.material?.palette, 'palette'],
                          ] as const).map(([groupLabel, choices, selected, field]) => (
                            <View key={field} style={styles.guidanceGroup}>
                              <Text style={styles.guidanceGroupLabel}>{groupLabel}</Text>
                              <View style={styles.guidanceChipRow}>
                                {choices.map(([value, choice]) => (
                                  <Pressable
                                    key={value}
                                    accessibilityRole="checkbox"
                                    accessibilityLabel={`${groupLabel}: ${choice}`}
                                    accessibilityHint="Tap again to remove this optional choice."
                                    accessibilityState={{ checked: selected === value }}
                                    style={[
                                      styles.guidanceChip,
                                      selected === value && styles.guidanceChipSelected,
                                    ]}
                                    onPress={() => toggleMaterialGuidanceChoice(field, value)}>
                                    <Text style={[
                                      styles.guidanceChipText,
                                      selected === value && styles.guidanceChipTextSelected,
                                    ]}>{choice}</Text>
                                  </Pressable>
                                ))}
                              </View>
                            </View>
                          ))}
                          <TextInput
                            accessibilityLabel="Material & finish note"
                            maxLength={100}
                            placeholder="Optional note, e.g. soft champagne gold with restrained shine"
                            placeholderTextColor={theme.faint}
                            value={guidance.material?.note ?? ''}
                            onChangeText={(note) => updateGuidance((current) => ({
                              ...current,
                              material: { ...current.material, note },
                            }))}
                            style={styles.guidanceNote}
                          />
                        </>
                      )}
                      {role === 'construction_detail' && (
                        <>
                          <Text style={styles.guidanceExample}>
                            Examples: finer prongs, an open gallery, a hidden hinge, a low-profile clasp, or rounded link edges.
                          </Text>
                          <TextInput
                            accessibilityLabel="Specific design detail note"
                            maxLength={140}
                            multiline
                            placeholder="Describe the detail you want the image model to consider…"
                            placeholderTextColor={theme.faint}
                            value={guidance.detail?.note ?? ''}
                            onChangeText={(note) => updateGuidance((current) => ({
                              ...current,
                              detail: { ...current.detail, note },
                            }))}
                            style={[styles.guidanceNote, styles.guidanceNoteMultiline]}
                          />
                          <Text style={styles.guidanceBoundary}>
                            Visual guidance only. Facetta will not record this as a production fact.
                          </Text>
                        </>
                      )}
                      {role === 'brand_direction' && (
                        <>
                          <Text style={styles.guidanceExample}>
                            Choose the feeling of the presentation—not another brand’s logo or jewelry shape.
                          </Text>
                          <View style={styles.guidanceChipRow}>
                            {BRAND_MOOD_CHOICES.map(([value, choice]) => (
                              <Pressable
                                key={value}
                                accessibilityRole="checkbox"
                                accessibilityLabel={`Brand mood: ${choice}`}
                                accessibilityHint="Tap again to remove this optional choice."
                                accessibilityState={{ checked: guidance.brand?.mood === value }}
                                style={[
                                  styles.guidanceChip,
                                  guidance.brand?.mood === value && styles.guidanceChipSelected,
                                ]}
                                onPress={() => toggleBrandMoodChoice(value)}>
                                <Text style={[
                                  styles.guidanceChipText,
                                  guidance.brand?.mood === value && styles.guidanceChipTextSelected,
                                ]}>{choice}</Text>
                              </Pressable>
                            ))}
                          </View>
                          <TextInput
                            accessibilityLabel="Brand mood note"
                            maxLength={100}
                            placeholder="Optional note, e.g. calm gallery lighting and generous negative space"
                            placeholderTextColor={theme.faint}
                            value={guidance.brand?.note ?? ''}
                            onChangeText={(note) => updateGuidance((current) => ({
                              ...current,
                              brand: { ...current.brand, note },
                            }))}
                            style={styles.guidanceNote}
                          />
                        </>
                      )}
                      <View style={styles.guidanceImageRow}>
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
                        <View style={styles.guidanceImageCopy}>
                          <Text style={styles.guidanceGroupLabel}>Reference image (optional)</Text>
                          <Text style={styles.referenceHelp}>{reference?.label
                            ?? 'Use only if an image explains this guidance better than the choices above.'}</Text>
                        </View>
                        {reference === undefined ? (
                          <Pressable
                            accessibilityRole="button"
                            accessibilityLabel={`Add image for ${label}`}
                            accessibilityHint={`Opens the image picker. ${help}`}
                            style={styles.referenceButton}
                            onPress={() => requestReference(role)}>
                            <Text style={styles.referenceButtonText}>Add image</Text>
                          </Pressable>
                        ) : (
                          <View style={styles.referenceActions}>
                            <Pressable
                              accessibilityRole="button"
                              accessibilityLabel={`Replace image for ${label}`}
                              style={styles.referenceButton}
                              onPress={() => requestReference(role)}>
                              <Text style={styles.referenceButtonText}>Replace</Text>
                            </Pressable>
                            <Pressable
                              accessibilityRole="button"
                              accessibilityLabel={`Remove image for ${label}`}
                              style={styles.referenceButton}
                              onPress={() => updateDraft((current) => ({
                                ...current,
                                references: current.references.filter(
                                  (item) => item.id !== reference.id,
                                ),
                              }))}>
                              <Text style={styles.referenceButtonText}>Remove</Text>
                            </Pressable>
                          </View>
                        )}
                      </View>
                    </View>
                  )}
                </View>
              );
            })}
          </View>
        </View>
      )}

      {masterReference === null
        && optionalGuidanceCount > 0
        && sentence.trim().length === 0 && (
        <View style={styles.limitNotice}>
          <Text style={styles.limitTitle}>Add a design idea</Text>
          <Text style={styles.limitBody}>
            Optional guidance can shape material, details, or mood after you add a design sentence or one visual source. It does not define the jewelry on its own.
          </Text>
        </View>
      )}

      {references.length > 0 && !referenceVisualsReady && (
        <Text style={styles.reviewReadiness}>{referenceVisualFailed
          ? 'A reference preview could not be shown. Replace or remove it before creating directions.'
          : 'Checking attached references before creation…'}</Text>
      )}

      {error !== null && <Text style={styles.error}>{error}</Text>}
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: !canCreate }}
        disabled={!canCreate}
        style={[styles.primaryButton, !canCreate && styles.buttonDisabled]}
        onPress={create}>
        <Text style={styles.primaryButtonText}>{busyMode === 'create'
          ? 'Generating…'
          : 'Generate'}</Text>
      </Pressable>
    </ScrollView>
    {isWideWorkspace && (
      <ScrollView
        testID="create-web-canvas"
        style={styles.renderCanvas}
        contentContainerStyle={styles.renderCanvasContent}>
        {project === null ? (
          <View style={styles.emptyCanvas}>
            <View style={styles.emptyCanvasMark}><Text style={styles.emptyCanvasMarkText}>✦</Text></View>
            <Text style={styles.canvasEyebrow}>{busyMode === 'create' ? 'GENERATING' : 'DESIGN CANVAS'}</Text>
            <Text style={styles.canvasTitle}>{busyMode === 'create'
              ? candidateCount === 1
                ? 'Generating your design.'
                : `Generating ${candidateCount} variations.`
              : 'Your designs will appear here.'}</Text>
            <Text style={styles.canvasBody}>{busyMode === 'create'
              ? 'Facetta is preparing the requested result.'
              : 'Describe a piece or add a visual source. The prompt stays beside the results so you can keep designing in one session.'}</Text>
          </View>
        ) : (
          <View style={styles.reviewCanvas}>
            <Text style={styles.eyebrow}>CHOOSE A DIRECTION</Text>
            <Text style={styles.title}>Choose a direction to refine—or describe another idea.</Text>
            <Text style={styles.body}>
              Your current results remain visible while the composer stays ready for the next piece or new direction.
            </Text>
            {partialDirectionMessage !== null && (
              <Text style={styles.partialResults}>{partialDirectionMessage}</Text>
            )}
            {comparisonViewControl}
            <View style={[styles.candidateGrid, styles.candidateGridWide]}>
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
                const displayVisual = candidateView(candidate, activeCandidateView);
                return (
                  <Pressable
                    key={candidate.asset_id}
                    accessibilityRole="radio"
                    accessibilityState={{ checked: selected, disabled: busy }}
                    accessibilityLabel={`Direction ${index + 1}`}
                    accessibilityHint={candidateStatus}
                    disabled={busy}
                    onPress={() => {
                      if (busy) return;
                      setSelectedAssetId(candidate.asset_id);
                    }}
                    style={[styles.candidateCard, styles.candidateCardWide,
                      selected && styles.candidateCardSelected]}>
                    {displayVisual === null ? (
                      <View style={styles.imageFallback}>
                        <Text style={styles.imageFallbackText}>Preview unavailable</Text>
                      </View>
                    ) : (
                      <StudioReviewImage
                        accessibilityLabel={`Direction ${index + 1} preview`}
                        inspectionLabel={`Direction ${index + 1}`}
                        source={{ uri: displayVisual.image_url }}
                        onLoad={() => visualReview.markReady(candidateVisualKey(candidate, activeCandidateView))}
                        onError={() => visualReview.markFailed(candidateVisualKey(candidate, activeCandidateView))}
                        style={styles.candidateImage}
                      />
                    )}
                    <View style={styles.candidateCopy}>
                      <View style={styles.candidateTitleRow}>
                        <Text style={styles.candidateTitle}>Direction {index + 1}</Text>
                        {selected && (
                          <View style={styles.selectedBadge}>
                            <Text style={styles.selectedBadgeText}>✓ Selected</Text>
                          </View>
                        )}
                      </View>
                      <Text style={styles.candidateMeta}>{candidateStatus}</Text>
                    </View>
                  </Pressable>
                );
              })}
            </View>
            {!decisionVisualsReady && selectedAssetId !== null && (
              <Text style={styles.reviewReadiness}>
                {selectedVisualFailed
                  ? 'The selected direction could not be displayed. Choose another direction or try loading it again before continuing.'
                  : 'Wait for the selected direction to finish loading before continuing.'}
              </Text>
            )}
            <View style={styles.canvasFooterActions}>
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ disabled: busy }}
                disabled={busy}
                style={[styles.secondaryButton, styles.canvasSecondaryButton,
                  busy && styles.buttonDisabled]}
                onPress={() => setDiscardConfirmationOpen(true)}>
                <Text style={styles.secondaryButtonText}>Clear canvas</Text>
              </Pressable>
              {onSaveForLater !== undefined && (
                <Pressable
                  accessibilityRole="button"
                  accessibilityState={{ disabled: busy || !decisionVisualsReady }}
                  style={[styles.secondaryButton, styles.canvasSaveButton,
                    (busy || !decisionVisualsReady) && styles.buttonDisabled]}
                  disabled={busy || !decisionVisualsReady}
                  onPress={() => void continueWithSelection('later')}>
                  <Text style={styles.secondaryButtonText}>Save for later</Text>
                </Pressable>
              )}
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ disabled: busy || !decisionVisualsReady }}
                style={[styles.primaryButton, styles.canvasPrimaryButton,
                  (busy || !decisionVisualsReady) && styles.buttonDisabled]}
                disabled={busy || !decisionVisualsReady}
                onPress={() => void continueWithSelection('refine')}>
                <Text style={styles.primaryButtonText}>{busyMode === 'save'
                  ? 'Saving direction…'
                  : busyMode === 'create'
                    ? 'Generating…'
                    : `Save & refine Direction ${candidates.findIndex((candidate) => candidate.asset_id === selectedAssetId) + 1}`}</Text>
              </Pressable>
            </View>
            {discardConfirmation}
          </View>
        )}
      </ScrollView>
    )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.paper },
  wideWorkspace: { flexDirection: 'row', minHeight: 0 },
  composerRail: {
    width: 390,
    flexGrow: 0,
    flexShrink: 0,
    backgroundColor: theme.paper,
    borderRightWidth: 1,
    borderRightColor: theme.line,
  },
  composerContent: { width: '100%', padding: 22, paddingBottom: 70 },
  variationPicker: { gap: 8, marginTop: 2 },
  renderCanvas: { flex: 1, backgroundColor: '#f4f1eb' },
  renderCanvasContent: {
    width: '100%',
    maxWidth: 1120,
    minHeight: '100%',
    alignSelf: 'center',
    padding: 28,
  },
  emptyCanvas: {
    flex: 1,
    minHeight: 520,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: '#cec7ba',
    borderRadius: radius.lg,
    backgroundColor: '#faf8f3',
    padding: 48,
  },
  emptyCanvasMark: {
    width: 58,
    height: 58,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 29,
    backgroundColor: '#eee9ff',
    marginBottom: 20,
  },
  emptyCanvasMarkText: { color: '#6f52d9', fontSize: 24 },
  canvasEyebrow: { color: '#6f52d9', fontSize: 10, fontWeight: '800', letterSpacing: 1.4 },
  canvasTitle: {
    color: theme.ink,
    fontFamily: theme.serif,
    fontSize: 32,
    lineHeight: 39,
    marginTop: 10,
    textAlign: 'center',
  },
  canvasBody: {
    color: theme.faint,
    fontSize: 13,
    lineHeight: 20,
    marginTop: 10,
    maxWidth: 480,
    textAlign: 'center',
  },
  reviewCanvas: { width: '100%', maxWidth: 980, alignSelf: 'center' },
  content: { width: '100%', maxWidth: 760, alignSelf: 'center', padding: 20, paddingBottom: 60 },
  eyebrow: { color: '#6f52d9', fontSize: 10, fontWeight: '800', letterSpacing: 1.4 },
  title: { color: theme.ink, fontFamily: theme.serif, fontSize: 30, lineHeight: 37, marginTop: 8 },
  body: { color: theme.faint, fontSize: 14, lineHeight: 21, marginTop: 8, maxWidth: 560 },
  primaryInputLabel: { color: theme.ink, fontSize: 14, fontWeight: '700', marginTop: 22 },
  primaryInputHelp: { color: theme.faint, fontSize: 11, lineHeight: 16, marginTop: 4 },
  retainedCopy: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 10, maxWidth: 560 },
  partialResults: {
    color: theme.ink,
    backgroundColor: theme.goldSoft,
    borderColor: theme.accent,
    borderWidth: 1,
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 14,
    lineHeight: 20,
    fontWeight: '600',
    marginTop: 12,
  },
  prompt: { minHeight: 112, borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, color: theme.ink, fontSize: 16, lineHeight: 23, padding: 16, marginTop: 10, textAlignVertical: 'top' },
  orDivider: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 18 },
  orDividerLine: { flex: 1, height: 1, backgroundColor: theme.line },
  orDividerText: { color: theme.faint, fontSize: 10, fontWeight: '800', letterSpacing: 1.2 },
  outputOptionsCard: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.lg,
    backgroundColor: '#faf8f3',
    padding: 14,
    marginTop: 18,
  },
  secondaryEyebrow: { color: theme.faint, fontSize: 9, fontWeight: '800', letterSpacing: 1.1 },
  outputOptionsTitle: { color: theme.ink, fontSize: 13, fontWeight: '700', marginTop: 6 },
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
  balanceSection: {
    gap: 8,
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.lg,
    backgroundColor: theme.card,
    marginTop: 10,
    padding: 14,
  },
  balanceSourceValue: { color: '#5c3fc0', fontSize: 12, fontWeight: '800' },
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
  guidanceSection: { borderBottomWidth: 1, borderBottomColor: theme.line },
  guidanceSectionHeader: {
    minHeight: 62,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  guidanceChevron: { color: '#6f52d9', fontSize: 20, fontWeight: '600' },
  guidanceSectionBody: {
    gap: 12,
    borderTopWidth: 1,
    borderTopColor: theme.line,
    backgroundColor: '#faf8f3',
    padding: 14,
  },
  guidanceGroup: { gap: 7 },
  guidanceGroupLabel: { color: theme.ink, fontSize: 10, fontWeight: '800' },
  guidanceChipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 7 },
  guidanceChip: {
    minHeight: 40,
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.pill,
    backgroundColor: theme.card,
    paddingHorizontal: 11,
    paddingVertical: 7,
  },
  guidanceChipSelected: { borderColor: '#6f52d9', backgroundColor: '#eee9ff' },
  guidanceChipText: { color: theme.faint, fontSize: 10, fontWeight: '700' },
  guidanceChipTextSelected: { color: '#5c3fc0' },
  guidanceNote: {
    minHeight: 44,
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.md,
    backgroundColor: theme.card,
    color: theme.ink,
    fontSize: 11,
    lineHeight: 16,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  guidanceNoteMultiline: { minHeight: 74, textAlignVertical: 'top' },
  guidanceExample: { color: theme.faint, fontSize: 10, lineHeight: 16 },
  guidanceBoundary: { color: '#745513', fontSize: 9, lineHeight: 14 },
  guidanceImageRow: {
    minHeight: 58,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    borderTopWidth: 1,
    borderTopColor: theme.line,
    paddingTop: 12,
  },
  guidanceImageCopy: { flex: 1 },
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
  candidateGridWide: { gap: 16 },
  candidateCard: { width: '48%', borderRadius: radius.lg, borderWidth: 1, borderColor: theme.line, backgroundColor: theme.card, overflow: 'hidden' },
  candidateCardWide: { width: '48.5%' },
  candidateCardSelected: { borderColor: '#6f52d9', borderWidth: 2 },
  candidateImage: { width: '100%', aspectRatio: 1, backgroundColor: '#ebe7ef' },
  imageFallback: { width: '100%', aspectRatio: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: '#ebe7ef' },
  imageFallbackText: { color: theme.faint, fontSize: 11 },
  reviewReadiness: { color: '#745513', fontSize: 11, lineHeight: 17, marginTop: 12 },
  candidateCopy: { padding: 12 },
  candidateTitleRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8,
  },
  candidateTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  selectedBadge: {
    borderRadius: radius.pill, backgroundColor: '#eee9ff', paddingHorizontal: 8, paddingVertical: 4,
  },
  selectedBadgeText: { color: '#5c3fc3', fontSize: 9, fontWeight: '800' },
  candidateMeta: { color: theme.faint, fontSize: 10, marginTop: 3 },
  viewControlRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
    marginTop: 18,
  },
  viewControlLabel: { color: theme.faint, fontSize: 11, lineHeight: 16 },
  viewControlButtons: { flexDirection: 'row', gap: 6 },
  viewControlButton: {
    minHeight: 36,
    justifyContent: 'center',
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: theme.line,
    paddingHorizontal: 14,
  },
  viewControlButtonActive: { borderColor: '#6f52d9', backgroundColor: '#eee9ff' },
  viewControlButtonText: { color: theme.faint, fontSize: 11, fontWeight: '700' },
  viewControlButtonTextActive: { color: '#5c3fc3' },
  footerActions: { gap: 0 },
  canvasFooterActions: { flexDirection: 'row', gap: 12, marginTop: 6 },
  canvasSecondaryButton: { flex: 0.24 },
  canvasSaveButton: { flex: 0.27 },
  canvasPrimaryButton: { flex: 0.49 },
  confirmationBackdrop: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(17, 16, 21, 0.56)',
    padding: 20,
  },
  confirmationDialog: {
    width: '100%',
    maxWidth: 440,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: theme.line,
    backgroundColor: theme.card,
    padding: 22,
  },
  confirmationTitle: {
    color: theme.ink,
    fontFamily: theme.serif,
    fontSize: 26,
    lineHeight: 32,
    marginTop: 8,
  },
  confirmationBody: { color: theme.faint, fontSize: 13, lineHeight: 20, marginTop: 8 },
  confirmationActions: { flexDirection: 'row', gap: 10, marginTop: 20 },
  confirmationButton: { flex: 1, marginTop: 0 },
});
