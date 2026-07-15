import React, {
  type Dispatch, type SetStateAction, useCallback, useEffect, useMemo, useRef, useState,
} from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from 'react-native';

import type {
  StudioCreativeDirectionReviewRequest, StudioGateway, StudioGatewayError,
} from './gateway';
import type {
  AssetSummary, CreativeDirectionReviewDraft, CreativeIntentRequest, CreativeSourceKind,
  ProjectDetail,
} from '../trusted/types';
import { radius, theme } from '../theme';
import { designerErrorMessage } from './designerErrorMessage';
import {
  getStudioWorkspaceControls, STUDIO_CREATE_REFERENCE_CONTROLS,
  type CreateReferenceRole,
} from './workspaceControls';
import { useVisualReviewReadiness } from './useVisualReviewReadiness';
import { StudioReviewImage } from './StudioReviewImage';
import { StudioComparisonInspector } from './StudioComparisonInspector';

export { STUDIO_CREATE_REFERENCE_CONTROLS } from './workspaceControls';
export type { CreateReferenceRole } from './workspaceControls';

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

export interface StudioCreateGuidance {
  metalColor: 'auto' | 'yellow' | 'white' | 'rose' | 'mixed';
  colorAccent: 'auto' | 'colorless' | 'blue' | 'green' | 'pink_red' | 'warm' | 'multicolor';
  surfaceFinish: 'auto' | 'polished' | 'satin_brushed' | 'hammered' | 'frosted' | 'organic' | 'mixed';
  visualMood: 'auto' | 'minimal' | 'romantic' | 'organic' | 'heritage' | 'sculptural' | 'playful';
}

export const EMPTY_STUDIO_CREATE_GUIDANCE: StudioCreateGuidance = {
  metalColor: 'auto',
  colorAccent: 'auto',
  surfaceFinish: 'auto',
  visualMood: 'auto',
};

const guidanceChoices = {
  metalColor: {
    title: 'Metal color',
    help: null,
    choices: [
      ['auto', 'Facetta decides'], ['yellow', 'Yellow gold'], ['white', 'White metal'],
      ['rose', 'Rose gold'], ['mixed', 'Mixed metal'],
    ],
  },
  colorAccent: {
    title: 'Color accents',
    help: 'For stones, enamel, or other accents.',
    choices: [
      ['auto', 'Facetta decides'], ['colorless', 'Colorless'], ['blue', 'Blue'],
      ['green', 'Green'], ['pink_red', 'Pink & red'], ['warm', 'Warm tones'],
      ['multicolor', 'Multicolor'],
    ],
  },
  surfaceFinish: {
    title: 'Surface & finish',
    help: null,
    choices: [
      ['auto', 'Facetta decides'], ['polished', 'High polish'],
      ['satin_brushed', 'Satin / brushed'], ['hammered', 'Hammered'],
      ['frosted', 'Frosted'], ['organic', 'Organic texture'], ['mixed', 'Mixed finish'],
    ],
  },
  visualMood: {
    title: 'Visual mood',
    help: 'Choose the feeling you want the design to express. This guides restraint, ornament, and presentation—not logos or another brand’s jewelry shapes.',
    choices: [
      ['auto', 'Facetta decides'], ['minimal', 'Minimal'], ['romantic', 'Romantic'],
      ['organic', 'Organic'], ['heritage', 'Heritage'], ['sculptural', 'Sculptural'],
      ['playful', 'Playful'],
    ],
  },
} as const;

const guidanceLabels: Record<string, string> = Object.fromEntries(
  (Object.values(guidanceChoices) as readonly {
    choices: readonly (readonly [string, string])[];
  }[]).flatMap(({ choices }) => choices),
);

const toCreativeIntent = (guidance: StudioCreateGuidance): CreativeIntentRequest | undefined => {
  const intent: CreativeIntentRequest = {};
  if (guidance.metalColor !== 'auto') intent.metal_color = guidance.metalColor;
  if (guidance.colorAccent !== 'auto') intent.color_accent = guidance.colorAccent;
  if (guidance.surfaceFinish !== 'auto') intent.surface_finish = guidance.surfaceFinish;
  if (guidance.visualMood !== 'auto') intent.visual_mood = guidance.visualMood;
  return Object.keys(intent).length === 0 ? undefined : intent;
};

const selectedGuidanceLabels = (guidance: StudioCreateGuidance): string[] => (
  Object.values(guidance)
    .filter((value) => value !== 'auto')
    .map((value) => guidanceLabels[value] ?? value)
);

const imageReferencePresentation: Record<SecondaryCreateReferenceRole, {
  label: string; help: string; action: string;
}> = {
  material_style: {
    label: 'Material & finish image',
    help: 'Use its metal color, stone palette, texture, or finish—not its jewelry shape.',
    action: 'Choose material or finish image',
  },
  construction_detail: {
    label: 'Specific jewelry detail image',
    help: 'A close-up of a setting, gallery, clasp, hinge, chain link, engraving, or edge treatment. It guides appearance only; engineering is reviewed later.',
    action: 'Choose detail image',
  },
  brand_direction: {
    label: 'Visual mood image',
    help: 'A moodboard, artwork, interior, packaging, or campaign image. Use its atmosphere—not logos or another jewelry design.',
    action: 'Choose mood image',
  },
};

const outputChoiceCopy: Record<StudioCreateCandidateCount, {
  title: string; detail: string; example: string;
}> = {
  1: {
    title: '1 · Focus',
    detail: 'One strong interpretation',
    example: 'Best when you want one focused proposal, not a range.',
  },
  2: {
    title: '2 · Compare',
    detail: 'Two distinct approaches · Recommended',
    example: 'Possible contrast: a restrained reading and a more sculptural reading of the same brief.',
  },
  3: {
    title: '3 · Explore',
    detail: 'A broader range',
    example: 'May explore different silhouettes, stone emphasis, or moods.',
  },
  4: {
    title: '4 · Explore wider',
    detail: 'The most variety',
    example: 'May span the widest mix of form, setting, surface, and mood.',
  },
};

/**
 * The complete pre-generation Create setup. The master reference owns its
 * explicit sourceKind so source truth cannot drift from a parallel field.
 */
export interface StudioCreateDraft {
  sentence: string;
  references: readonly StudioCreateReference[];
  guidance: StudioCreateGuidance;
  candidateCount: StudioCreateCandidateCount;
}

export const EMPTY_STUDIO_CREATE_DRAFT: StudioCreateDraft = {
  sentence: '',
  references: [],
  guidance: EMPTY_STUDIO_CREATE_GUIDANCE,
  candidateCount: 2,
};

export interface StudioCreateGenerationSuccess {
  owner: string;
  projectId: string;
  submittedDraft: StudioCreateDraft;
}

export type StudioCreateReviewPersistenceState = 'saved' | 'saving' | 'error';

export interface StudioCreateWorkspaceProps {
  gateway: Pick<StudioGateway,
    'createFromPrompt' | 'createFromDrawing' | 'completeCreativeDirectionReview'
  > & Partial<Pick<StudioGateway, 'loadCreateReviewDraft' | 'saveCreateReviewDraft'>>;
  owner: string;
  /** Controlled draft used by App so setup survives workspace navigation. */
  draft?: StudioCreateDraft;
  onDraftChange?: Dispatch<SetStateAction<StudioCreateDraft>>;
  /** Called only after a request returns reviewable directions. */
  onGenerationSucceeded?: (success: StudioCreateGenerationSuccess) => void;
  /** Lets the shell prevent unmount while the latest review intent is not durable. */
  onReviewDraftStateChange?: (state: StudioCreateReviewPersistenceState) => void;
  initialSentence?: string;
  initialReferences?: readonly StudioCreateReference[];
  /** Durable review state reopened from a reviewing Create Activity job. */
  resumeProject?: ProjectDetail | null;
  resumeStudioJobId?: string | null;
  /** Mutable review intent is durable but never part of immutable design history. */
  resumeReviewDraft?: CreativeDirectionReviewDraft | null;
  onRequestReference?: (
    role: CreateReferenceRole,
  ) => StudioCreateReference | null | Promise<StudioCreateReference | null>;
  onSave: (selection: StudioCreateSelection) => void;
}

const referencePreviewUri = (reference: StudioCreateReference): string => (
  `data:${reference.mediaType};base64,${reference.imageBase64}`
);

const MAX_RETAINED_VARIATIONS = 3;
const MAX_VARIATION_LABEL_LENGTH = 120;

interface CreateReviewDraftIntent {
  projectId: string;
  studioJobId: string | null;
  owner: string;
  contextSequence: number;
  selectedAssetId: string;
  retainedAssetIds: readonly string[];
  retainedLabelsByAssetId: Readonly<Record<string, string>>;
  retained: readonly { candidateId: string; label: string }[];
}

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
  if (candidate.root_id !== project.root_id) return null;
  const assetsById = new Map(project.assets.map((asset) => [asset.asset_id, asset]));
  const visited = new Set<string>([candidate.asset_id]);
  let current: AssetSummary = candidate;
  while (current.parent_asset_id !== null) {
    if (visited.has(current.parent_asset_id)) return null;
    visited.add(current.parent_asset_id);
    const parent = assetsById.get(current.parent_asset_id);
    if (parent === undefined || parent.root_id !== project.root_id) return null;
    if (parent.capability === 'CREATIVE_SOURCE_REGION') return parent;
    if (parent.capability === 'CREATIVE_SOURCE') return parent;
    if (parent.capability !== 'CREATIVE_REFERENCE_BOARD') return null;
    current = parent;
  }
  return null;
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
  onReviewDraftStateChange,
  initialSentence = '',
  initialReferences = [],
  resumeProject = null,
  resumeStudioJobId = null,
  resumeReviewDraft = null,
  onRequestReference,
  onSave,
}: StudioCreateWorkspaceProps) {
  const createControls = useMemo(() => getStudioWorkspaceControls('create'), []);
  const createBriefLabel = createControls.fields[0]!.label;
  const createCreditsPerOutput = createControls.creditsPerOutput;
  const createOutputChoices = (
    createControls.requestedOutputChoices as readonly StudioCreateCandidateCount[]
  );
  const createReferenceControls = useMemo(() => (
    STUDIO_CREATE_REFERENCE_CONTROLS.map((control) => {
      const field = createControls.fields.find(({ fieldId }) => fieldId === control.fieldId);
      if (field === undefined || field.role !== control.role || field.help === null) {
        throw new Error(`Invalid Create reference control for ${control.fieldId}`);
      }
      return Object.freeze({
        ...control,
        label: field.label,
        help: field.help,
      });
    })
  ), [createControls]);
  const [localDraft, setLocalDraft] = useState<StudioCreateDraft>(() => ({
    sentence: initialSentence,
    references: [...initialReferences],
    guidance: EMPTY_STUDIO_CREATE_GUIDANCE,
    candidateCount: 2,
  }));
  const createDraft = controlledDraft ?? localDraft;
  const { sentence, references, guidance, candidateCount } = createDraft;
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
  const selectionDecisionRef = useRef<StudioCreativeDirectionReviewRequest | null>(null);
  if (ownerRef.current !== owner) {
    ownerRef.current = owner;
    generationRequestIdRef.current += 1;
    referenceRequestIdRef.current += 1;
    selectionRequestIdRef.current += 1;
    selectionDecisionRef.current = null;
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
    (controlledDraft?.references.length ?? initialReferences.length) > 0
      || selectedGuidanceLabels(controlledDraft?.guidance ?? EMPTY_STUDIO_CREATE_GUIDANCE).length > 0,
  );
  const [inspirationImagesOpen, setInspirationImagesOpen] = useState(
    (controlledDraft?.references ?? initialReferences).some(
      (reference) => reference.role !== 'master_geometry',
    ),
  );
  const [project, setProject] = useState<ProjectDetail | null>(resumeProject);
  const resumedCandidates = resumeProject === null ? [] : creativeCandidates(resumeProject);
  const draftMatchesResume = resumeProject !== null
    && resumeStudioJobId !== null
    && resumeReviewDraft?.project_root_id === resumeProject.root_id
    && resumeReviewDraft.studio_job_id === resumeStudioJobId;
  const resumedSelection = draftMatchesResume
    ? resumeReviewDraft.selected_candidate_id
    : resumeProject?.selected_candidate_asset_id;
  const resumedSelectedAssetId = resumedSelection !== null && resumedSelection !== undefined
    && resumedCandidates.some((candidate) => candidate.asset_id === resumedSelection)
    ? resumedSelection
    : resumedCandidates[0]?.asset_id ?? null;
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(
    resumedSelectedAssetId,
  );
  const [selectionStudioJobId, setSelectionStudioJobId] = useState<string | null>(
    resumeStudioJobId,
  );
  const resumedRetained = draftMatchesResume ? resumeReviewDraft.retained.filter((direction) => (
    direction.candidate_id !== resumedSelectedAssetId
    && resumedCandidates.some((candidate) => candidate.asset_id === direction.candidate_id)
  )) : [];
  const [retainedAssetIds, setRetainedAssetIds] = useState<readonly string[]>(
    resumedRetained.map((direction) => direction.candidate_id),
  );
  const [retainedLabelsByAssetId, setRetainedLabelsByAssetId] = useState<
    Readonly<Record<string, string>>
  >(() => Object.fromEntries(resumedRetained.map((direction) => (
    [direction.candidate_id, direction.label]
  ))));
  const reviewDraftVersionRef = useRef(draftMatchesResume ? resumeReviewDraft.version : 0);
  const reviewDraftContextSequenceRef = useRef(0);
  const reviewDraftInitialWriteKeyRef = useRef<string | null>(null);
  const reviewDraftLatestRef = useRef<{
    selectedAssetId: string | null;
    retainedAssetIds: readonly string[];
    retainedLabelsByAssetId: Readonly<Record<string, string>>;
  }>({
    selectedAssetId: resumedSelectedAssetId,
    retainedAssetIds: resumedRetained.map((direction) => direction.candidate_id) as readonly string[],
    retainedLabelsByAssetId: Object.fromEntries(resumedRetained.map((direction) => (
      [direction.candidate_id, direction.label]
    ))) as Readonly<Record<string, string>>,
  });
  const reviewDraftPendingRef = useRef<CreateReviewDraftIntent | null>(null);
  const reviewDraftWriterRunningRef = useRef(false);
  const reviewDraftWriterPromiseRef = useRef<Promise<boolean>>(Promise.resolve(true));
  const reviewDraftWriteFailedRef = useRef(false);
  const reviewDraftLastErrorRef = useRef<StudioGatewayError | null>(null);
  const [reviewDraftSaveState, setReviewDraftSaveState] = useState<
    StudioCreateReviewPersistenceState
  >(
    resumeProject !== null
      && !draftMatchesResume
      && gateway.saveCreateReviewDraft !== undefined
      ? 'saving'
      : 'saved',
  );
  const [directionCompareOpen, setDirectionCompareOpen] = useState(false);
  const [comparisonAssetId, setComparisonAssetId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [commitRetryLocked, setCommitRetryLocked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewDraftRecoveryNotice, setReviewDraftRecoveryNotice] = useState<string | null>(null);

  useEffect(() => {
    onReviewDraftStateChange?.(reviewDraftSaveState);
  }, [onReviewDraftStateChange, reviewDraftSaveState]);

  const candidates = useMemo(() => project === null ? [] : creativeCandidates(project), [project]);
  const visualReview = useVisualReviewReadiness(project?.root_id ?? 'create-setup');
  const referenceVisualKey = (reference: StudioCreateReference): string => (
    `create-reference:${reference.role}:${reference.id}:${reference.mediaType}:${reference.imageBase64}`
  );
  const intendedRetainedCandidates = useMemo(() => (
    candidates
      .filter((candidate) => (
        candidate.asset_id !== selectedAssetId
        && retainedAssetIds.includes(candidate.asset_id)
        && visualReview.isReady(candidateVisualKey(candidate))
      ))
      .slice(0, MAX_RETAINED_VARIATIONS)
  ), [candidates, retainedAssetIds, selectedAssetId, visualReview.isReady]);
  const retainedCount = intendedRetainedCandidates.length;
  const selectedCandidate = candidates.find(
    (candidate) => candidate.asset_id === selectedAssetId,
  ) ?? null;
  const comparisonCandidate = candidates.find(
    (candidate) => candidate.asset_id === comparisonAssetId,
  ) ?? null;
  const selectedVisualKey = selectedCandidate === null ? null : candidateVisualKey(selectedCandidate);
  const comparisonVisualKey = comparisonCandidate === null
    ? null : candidateVisualKey(comparisonCandidate);
  const reviewSource = project === null ? null : creativeReviewSource(project, selectedCandidate);
  const sourceLineageUnavailable = selectedCandidate?.source_kind !== undefined
    && selectedCandidate.source_kind !== null
    && reviewSource === null;
  const reviewSourceVisualKey = sourceVisualKey(reviewSource);
  const requiredDecisionVisualKeys = reviewSource === null
    ? [selectedVisualKey]
    : [reviewSourceVisualKey, selectedVisualKey];
  const decisionVisualsReady = selectedAssetId !== null
    && selectedCandidate !== null
    && !sourceLineageUnavailable
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

  const queueReviewDraftSave = useCallback((
    nextSelectedAssetId: string | null,
    nextRetainedAssetIds: readonly string[],
    nextRetainedLabelsByAssetId: Readonly<Record<string, string>>,
  ): Promise<boolean> => {
    reviewDraftLatestRef.current = {
      selectedAssetId: nextSelectedAssetId,
      retainedAssetIds: nextRetainedAssetIds,
      retainedLabelsByAssetId: nextRetainedLabelsByAssetId,
    };
    if (
      project === null || nextSelectedAssetId === null
      || gateway.saveCreateReviewDraft === undefined
    ) return Promise.resolve(true);

    const retained = candidates
      .filter((candidate) => (
        candidate.asset_id !== nextSelectedAssetId
        && nextRetainedAssetIds.includes(candidate.asset_id)
      ))
      .slice(0, MAX_RETAINED_VARIATIONS)
      .map((candidate) => {
        const index = candidates.findIndex((item) => item.asset_id === candidate.asset_id);
        return {
          candidateId: candidate.asset_id,
          label: nextRetainedLabelsByAssetId[candidate.asset_id]?.trim()
            || `Direction ${index + 1}`,
        };
      });
    const intent: CreateReviewDraftIntent = {
      projectId: project.root_id,
      studioJobId: selectionStudioJobId,
      owner,
      contextSequence: reviewDraftContextSequenceRef.current,
      selectedAssetId: nextSelectedAssetId,
      retainedAssetIds: nextRetainedAssetIds,
      retainedLabelsByAssetId: nextRetainedLabelsByAssetId,
      retained,
    };
    reviewDraftPendingRef.current = intent;
    reviewDraftWriteFailedRef.current = false;
    reviewDraftLastErrorRef.current = null;
    if (mountedRef.current) setReviewDraftRecoveryNotice(null);
    if (mountedRef.current) setReviewDraftSaveState('saving');

    if (reviewDraftWriterRunningRef.current) {
      return reviewDraftWriterPromiseRef.current;
    }

    reviewDraftWriterRunningRef.current = true;
    const writer = async (): Promise<boolean> => {
      let lastContextSequence: number | null = null;
      while (reviewDraftPendingRef.current !== null) {
        const pending = reviewDraftPendingRef.current;
        reviewDraftPendingRef.current = null;
        lastContextSequence = pending.contextSequence;
        const saved = await gateway.saveCreateReviewDraft!({
          projectId: pending.projectId,
          ...(pending.studioJobId === null ? {} : { studioJobId: pending.studioJobId }),
          owner: pending.owner,
          expectedVersion: reviewDraftVersionRef.current,
          selectedCandidateId: pending.selectedAssetId,
          retained: pending.retained,
        });
        const stillCurrent = pending.contextSequence === reviewDraftContextSequenceRef.current
          && ownerRef.current === pending.owner;
        if (saved.error !== null) {
          if (stillCurrent) {
            reviewDraftPendingRef.current = reviewDraftPendingRef.current ?? pending;
            reviewDraftWriteFailedRef.current = true;
            reviewDraftLastErrorRef.current = saved.error;
            if (mountedRef.current) setReviewDraftSaveState('error');
          }
          return false;
        }
        if (stillCurrent) {
          reviewDraftVersionRef.current = saved.data.version;
          reviewDraftLastErrorRef.current = null;
          if (pending.studioJobId === null && mountedRef.current) {
            setSelectionStudioJobId(saved.data.studio_job_id);
          }
        }
      }
      if (lastContextSequence === reviewDraftContextSequenceRef.current) {
        reviewDraftWriteFailedRef.current = false;
        if (mountedRef.current) setReviewDraftSaveState('saved');
      }
      return true;
    };
    reviewDraftWriterPromiseRef.current = writer().finally(() => {
      reviewDraftWriterRunningRef.current = false;
    });
    return reviewDraftWriterPromiseRef.current;
  }, [candidates, gateway, owner, project, selectionStudioJobId]);

  const retryReviewDraftSave = async (): Promise<void> => {
    if (
      reviewDraftLastErrorRef.current?.category === 'conflict'
      && project !== null
      && selectionStudioJobId !== null
      && gateway.loadCreateReviewDraft !== undefined
    ) {
      setReviewDraftSaveState('saving');
      const contextSequence = reviewDraftContextSequenceRef.current;
      const reloaded = await gateway.loadCreateReviewDraft(
        project.root_id, selectionStudioJobId, owner,
      );
      if (!mountedRef.current || contextSequence !== reviewDraftContextSequenceRef.current) return;
      if (reloaded.error !== null || reloaded.data.draft === null) {
        setReviewDraftSaveState('error');
        return;
      }
      const authoritative = reloaded.data.draft;
      const nextRetainedAssetIds = authoritative.retained.map(
        (direction) => direction.candidate_id,
      );
      const nextLabels = Object.fromEntries(authoritative.retained.map((direction) => (
        [direction.candidate_id, direction.label]
      )));
      reviewDraftVersionRef.current = authoritative.version;
      reviewDraftPendingRef.current = null;
      reviewDraftWriteFailedRef.current = false;
      reviewDraftLastErrorRef.current = null;
      reviewDraftLatestRef.current = {
        selectedAssetId: authoritative.selected_candidate_id,
        retainedAssetIds: nextRetainedAssetIds,
        retainedLabelsByAssetId: nextLabels,
      };
      setSelectedAssetId(authoritative.selected_candidate_id);
      setRetainedAssetIds(nextRetainedAssetIds);
      setRetainedLabelsByAssetId(nextLabels);
      if (comparisonAssetId === authoritative.selected_candidate_id) {
        setComparisonAssetId(null);
      }
      setReviewDraftRecoveryNotice(
        'This review changed elsewhere. Facetta reloaded the latest saved choices; review them before continuing.',
      );
      setReviewDraftSaveState('saved');
      return;
    }
    const latest = reviewDraftLatestRef.current;
    reviewDraftPendingRef.current = null;
    await queueReviewDraftSave(
      latest.selectedAssetId,
      latest.retainedAssetIds,
      latest.retainedLabelsByAssetId,
    );
  };

  useEffect(() => {
    if (
      project === null || selectedAssetId === null
      || gateway.saveCreateReviewDraft === undefined
      || reviewDraftVersionRef.current !== 0
    ) return;
    const initialWriteKey = `${owner}:${project.root_id}:${selectionStudioJobId ?? 'tracked'}`;
    if (reviewDraftInitialWriteKeyRef.current === initialWriteKey) return;
    reviewDraftInitialWriteKeyRef.current = initialWriteKey;
    void queueReviewDraftSave(
      selectedAssetId,
      retainedAssetIds,
      retainedLabelsByAssetId,
    );
  }, [gateway.saveCreateReviewDraft, owner, project, queueReviewDraftSave,
    retainedAssetIds, retainedLabelsByAssetId, selectedAssetId, selectionStudioJobId]);

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
    const creativeIntent = toCreativeIntent(submittedDraft.guidance);
    if ((!prompt && submittedMaster === null) || busy) return;
    const requestId = generationRequestIdRef.current + 1;
    generationRequestIdRef.current = requestId;
    const requestOwner = owner;
    reviewDraftContextSequenceRef.current += 1;
    reviewDraftVersionRef.current = 0;
    reviewDraftInitialWriteKeyRef.current = null;
    reviewDraftPendingRef.current = null;
    reviewDraftWriteFailedRef.current = false;
    reviewDraftLastErrorRef.current = null;
    reviewDraftLatestRef.current = {
      selectedAssetId: null, retainedAssetIds: [], retainedLabelsByAssetId: {},
    };
    setReviewDraftSaveState('saved');
    setReviewDraftRecoveryNotice(null);
    setBusy(true);
    setError(null);
    setProject(null);
    setSelectedAssetId(null);
    setSelectionStudioJobId(null);
    setRetainedAssetIds([]);
    setRetainedLabelsByAssetId({});
    setDirectionCompareOpen(false);
    setComparisonAssetId(null);
    selectionDecisionRef.current = null;
    setCommitRetryLocked(false);
    const sourceTitle = prompt || submittedMaster?.label || 'Untitled reference study';
    const title = sourceTitle.length > 64 ? `${sourceTitle.slice(0, 61)}…` : sourceTitle;
    const result = submittedMaster === null
      ? await gateway.createFromPrompt({
          prompt,
          ...(creativeIntent === undefined ? {} : { creative_intent: creativeIntent }),
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
          ...(creativeIntent === undefined ? {} : { creative_intent: creativeIntent }),
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
    setRetainedAssetIds([]);
    setRetainedLabelsByAssetId({});
    setDirectionCompareOpen(false);
    setComparisonAssetId(null);
    reviewDraftLatestRef.current = {
      selectedAssetId: nextCandidates[0].asset_id,
      retainedAssetIds: [],
      retainedLabelsByAssetId: {},
    };
    if (gateway.saveCreateReviewDraft !== undefined) setReviewDraftSaveState('saving');
    selectionDecisionRef.current = null;
    setCommitRetryLocked(false);
    onGenerationSucceeded?.({
      owner: requestOwner,
      projectId: result.data.root_id,
      submittedDraft,
    });
  };

  const continueWithSelection = async (): Promise<void> => {
    if (
      project === null || selectedAssetId === null || busy || !decisionVisualsReady
      || reviewDraftSaveState !== 'saved' || reviewDraftWriteFailedRef.current
    ) return;

    const requestId = selectionRequestIdRef.current + 1;
    selectionRequestIdRef.current = requestId;
    const requestOwner = owner;
    const requestProjectId = project.root_id;
    const requestSelectedAssetId = selectedAssetId;
    setBusy(true);
    setError(null);
    const decision = selectionDecisionRef.current ?? {
      projectId: requestProjectId,
      selectedCandidateId: requestSelectedAssetId,
      retained: intendedRetainedCandidates.map((candidate) => {
        const index = candidates.findIndex((item) => item.asset_id === candidate.asset_id);
        return {
          candidateId: candidate.asset_id,
          label: retainedLabelsByAssetId[candidate.asset_id]?.trim()
            || `Direction ${index + 1}`,
        };
      }),
      createdBy: requestOwner,
      ...(selectionStudioJobId === null ? {} : { studioJobId: selectionStudioJobId }),
    };
    selectionDecisionRef.current = decision;
    const committed = await gateway.completeCreativeDirectionReview(decision);
    if (!mountedRef.current
      || selectionRequestIdRef.current !== requestId
      || ownerRef.current !== requestOwner) return;
    if (committed.error !== null) {
      setBusy(false);
      if (committed.error.retryable) {
        setCommitRetryLocked(true);
      } else {
        selectionDecisionRef.current = null;
        setCommitRetryLocked(false);
      }
      setError(designerErrorMessage(committed.error, 'create'));
      return;
    }

    setBusy(false);
    selectionDecisionRef.current = null;
    setCommitRetryLocked(false);
    setProject(committed.data.project);
    setSelectionStudioJobId(null);
    onSave({
      project: committed.data.project,
      selectedAssetId: requestSelectedAssetId,
    });
  };

  const leaveReviewAndStartAnother = (): void => {
    if (busy || reviewDraftSaveState !== 'saved') return;
    selectionRequestIdRef.current += 1;
    reviewDraftContextSequenceRef.current += 1;
    reviewDraftVersionRef.current = 0;
    reviewDraftInitialWriteKeyRef.current = null;
    reviewDraftPendingRef.current = null;
    reviewDraftWriteFailedRef.current = false;
    reviewDraftLatestRef.current = {
      selectedAssetId: null, retainedAssetIds: [], retainedLabelsByAssetId: {},
    };
    setError(null);
    setSetupOpen(false);
    setInspirationImagesOpen(false);
    setProject(null);
    setSelectedAssetId(null);
    setSelectionStudioJobId(null);
    setRetainedAssetIds([]);
    setRetainedLabelsByAssetId({});
    setDirectionCompareOpen(false);
    setComparisonAssetId(null);
    selectionDecisionRef.current = null;
    setCommitRetryLocked(false);
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
          Choose what to refine now. Keep only the other useful directions you want organized as variations. The full generated set stays preserved in this Activity review.
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
        <View accessibilityRole="radiogroup" style={styles.candidateGrid}>
          {candidates.map((candidate, index) => {
            const selected = selectedAssetId === candidate.asset_id;
            const willRetain = intendedRetainedCandidates.some(
              (item) => item.asset_id === candidate.asset_id,
            );
            const candidateStatus = selected
              ? 'Selected to refine'
              : willRetain
                ? 'Will save as a variation'
                : 'Preserved in Activity review';
            const visualKey = candidateVisualKey(candidate);
            const candidateDisabled = busy || commitRetryLocked;
            const candidateReady = visualReview.isReady(visualKey);
            const candidateFailed = visualReview.anyFailed([visualKey]);
            const retainLimitReached = retainedCount >= MAX_RETAINED_VARIATIONS && !willRetain;
            const retainDisabled = candidateDisabled || selected || !candidateReady
              || retainLimitReached;
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
                    onError={() => {
                      visualReview.markFailed(visualKey);
                      const nextRetainedAssetIds = retainedAssetIds.filter(
                        (assetId) => assetId !== candidate.asset_id,
                      );
                      setRetainedAssetIds(nextRetainedAssetIds);
                      void queueReviewDraftSave(
                        selectedAssetId, nextRetainedAssetIds, retainedLabelsByAssetId,
                      );
                      if (comparisonAssetId === candidate.asset_id) {
                        setComparisonAssetId(null);
                      }
                    }}
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
                    const nextRetainedAssetIds = retainedAssetIds.filter(
                      (assetId) => assetId !== candidate.asset_id,
                    );
                    setRetainedAssetIds(nextRetainedAssetIds);
                    if (comparisonAssetId === candidate.asset_id) {
                      setComparisonAssetId(null);
                    }
                    setSelectedAssetId(candidate.asset_id);
                    void queueReviewDraftSave(
                      candidate.asset_id,
                      nextRetainedAssetIds,
                      retainedLabelsByAssetId,
                    );
                  }}>
                  <View style={styles.candidateCopy}>
                    <Text style={styles.candidateTitle}>Direction {index + 1}</Text>
                    <Text style={styles.candidateMeta}>{candidateStatus}</Text>
                  </View>
                </Pressable>
                {!selected && (
                  <>
                    <Pressable
                      accessibilityRole="checkbox"
                      accessibilityState={{ checked: willRetain, disabled: retainDisabled }}
                      accessibilityLabel={`Keep Direction ${index + 1} as variation`}
                      accessibilityHint={candidateFailed
                        ? 'This preview is unavailable and cannot be kept.'
                        : !candidateReady
                          ? 'Review this preview before keeping it.'
                          : retainLimitReached
                            ? 'You can keep at most three variations.'
                            : willRetain
                              ? 'Remove this direction from saved variations.'
                              : 'Save this useful direction as a variation.'}
                      disabled={retainDisabled}
                      style={[styles.keepVariation, retainDisabled && styles.keepVariationDisabled]}
                      onPress={() => {
                        if (retainDisabled) return;
                        const nextRetainedAssetIds = retainedAssetIds.includes(candidate.asset_id)
                          ? retainedAssetIds.filter((assetId) => assetId !== candidate.asset_id)
                          : [...retainedAssetIds, candidate.asset_id];
                        setRetainedAssetIds(nextRetainedAssetIds);
                        void queueReviewDraftSave(
                          selectedAssetId,
                          nextRetainedAssetIds,
                          retainedLabelsByAssetId,
                        );
                      }}>
                      <View style={[styles.keepBox, willRetain && styles.keepBoxChecked]}>
                        {willRetain && <Text style={styles.keepCheck}>✓</Text>}
                      </View>
                      <Text style={[styles.keepText, willRetain && styles.keepTextChecked]}>
                        {candidateFailed
                          ? 'Preview unavailable'
                          : candidateReady
                            ? 'Keep as variation'
                            : 'Load preview to keep'}
                      </Text>
                    </Pressable>
                    {willRetain && (
                      <View
                        testID={`create-retained-variation-editor-${candidate.asset_id}`}
                        style={styles.variationNameBlock}>
                        <Text style={styles.variationNameLabel}>Name this variation</Text>
                        <TextInput
                          accessibilityLabel={`Variation name for Direction ${index + 1}`}
                          accessibilityHint={`Optional. This name appears in Collections. Leave blank to use Direction ${index + 1}.`}
                          editable={!busy && !commitRetryLocked}
                          maxLength={MAX_VARIATION_LABEL_LENGTH}
                          placeholder="e.g. Rose gold halo"
                          placeholderTextColor={theme.faint}
                          testID={`create-retained-variation-name-${candidate.asset_id}`}
                          value={retainedLabelsByAssetId[candidate.asset_id] ?? ''}
                          onChangeText={(label) => {
                            const nextLabels = {
                              ...retainedLabelsByAssetId,
                              [candidate.asset_id]: label,
                            };
                            setRetainedLabelsByAssetId(nextLabels);
                            void queueReviewDraftSave(
                              selectedAssetId,
                              retainedAssetIds,
                              nextLabels,
                            );
                          }}
                          style={styles.variationNameInput}
                        />
                        <Text style={styles.variationNameHelp}>
                          Optional · shown in Collections. Blank uses Direction {index + 1}.
                        </Text>
                      </View>
                    )}
                  </>
                )}
              </View>
            );
          })}
        </View>
        {candidates.length > 1 && (
          <View style={styles.directionCompareBlock}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Compare directions"
              accessibilityState={{ expanded: directionCompareOpen }}
              testID="create-direction-compare-disclosure"
              onPress={() => setDirectionCompareOpen((current) => !current)}
              style={styles.directionCompareDisclosure}>
              <View style={styles.directionCompareDisclosureCopy}>
                <Text style={styles.directionCompareTitle}>Compare directions</Text>
                <Text style={styles.directionCompareHelp}>
                  Put the selected direction beside one alternative. Comparing does not change what you keep.
                </Text>
              </View>
              <Text style={styles.disclosureGlyph}>{directionCompareOpen ? '−' : '+'}</Text>
            </Pressable>
            {directionCompareOpen && (
              <View testID="create-direction-compare-options">
                <View accessibilityRole="radiogroup" style={styles.directionCompareOptions}>
                  {candidates.filter((candidate) => (
                    candidate.asset_id !== selectedAssetId
                  )).map((candidate) => {
                    const index = candidates.findIndex(
                      (item) => item.asset_id === candidate.asset_id,
                    );
                    const visualKey = candidateVisualKey(candidate);
                    const candidateReady = visualReview.isReady(visualKey);
                    const candidateFailed = visualReview.anyFailed([visualKey]);
                    const checked = candidate.asset_id === comparisonAssetId;
                    const disabled = !candidateReady || candidateFailed;
                    return (
                      <Pressable
                        key={candidate.asset_id}
                        accessibilityRole="radio"
                        accessibilityLabel={`Compare selected direction with Direction ${index + 1}`}
                        accessibilityHint={candidateFailed
                          ? 'This preview is unavailable and cannot be compared.'
                          : candidateReady
                            ? 'Show this alternative beside the selected direction.'
                            : 'Load this preview before comparing it.'}
                        accessibilityState={{ checked, disabled }}
                        disabled={disabled}
                        onPress={() => setComparisonAssetId(candidate.asset_id)}
                        style={[
                          styles.directionCompareOption,
                          checked && styles.directionCompareOptionSelected,
                          disabled && styles.keepVariationDisabled,
                        ]}>
                        <Text style={[
                          styles.directionCompareOptionText,
                          checked && styles.directionCompareOptionTextSelected,
                        ]}>Direction {index + 1}</Text>
                      </Pressable>
                    );
                  })}
                </View>
                {comparisonCandidate !== null
                  && selectedCandidate !== null
                  && selectedCandidate.image_url !== null
                  && comparisonCandidate.image_url !== null && (
                  <View testID="create-direction-comparison">
                    <StudioComparisonInspector
                      before={{
                        label: `Direction ${candidates.findIndex((candidate) => (
                          candidate.asset_id === selectedCandidate.asset_id
                        )) + 1}`,
                        roleLabel: 'Selected direction',
                        accessibilityLabel: 'Create selected direction alternative comparison',
                        source: { uri: selectedCandidate.image_url },
                        onLoad: () => visualReview.markReady(selectedVisualKey),
                        onError: () => visualReview.markFailed(selectedVisualKey),
                      }}
                      after={{
                        label: `Direction ${candidates.findIndex((candidate) => (
                          candidate.asset_id === comparisonCandidate.asset_id
                        )) + 1}`,
                        roleLabel: 'Alternative direction',
                        accessibilityLabel: 'Create alternative direction comparison',
                        source: { uri: comparisonCandidate.image_url },
                        onLoad: () => visualReview.markReady(comparisonVisualKey),
                        onError: () => visualReview.markFailed(comparisonVisualKey),
                      }}
                      compactHeight={240}
                      inspectionTitle="Compare generated directions"
                      inspectionHelp="Inspect silhouette, proportions, setting, materials, and construction before choosing what to refine."
                    />
                  </View>
                )}
              </View>
            )}
          </View>
        )}
        {!decisionVisualsReady && selectedAssetId !== null && (
          <Text style={styles.reviewReadiness}>
            {sourceLineageUnavailable
              ? 'The starting source lineage is unavailable. Reopen this review from Activity before choosing a direction.'
              : sourceVisualFailed
              ? 'The starting source could not be displayed. Reopen this review from Activity or try loading it again before continuing.'
              : selectedVisualFailed
              ? 'The selected direction could not be displayed. Choose another direction or try loading it again before continuing.'
              : reviewSource !== null
                ? 'Wait for both the starting source and selected direction to finish loading before continuing.'
                : 'Wait for the selected direction to finish loading before continuing.'}
          </Text>
        )}
        {error !== null && <Text style={styles.error}>{error}</Text>}
        {reviewDraftRecoveryNotice !== null && (
          <Text accessibilityLiveRegion="polite" style={styles.reviewReadiness}>
            {reviewDraftRecoveryNotice}
          </Text>
        )}
        {reviewDraftSaveState === 'saving' && (
          <Text accessibilityLiveRegion="polite" style={styles.reviewReadiness}>
            Saving this review to Activity…
          </Text>
        )}
        {reviewDraftSaveState === 'error' && (
          <View accessibilityLiveRegion="assertive" style={styles.reviewDraftError}>
            <Text style={styles.error}>
              This review is still open, but its latest choice could not be saved to Activity.
            </Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Retry saving Create review"
              onPress={() => void retryReviewDraftSave()}
              style={styles.retryDraftButton}>
              <Text style={styles.retryDraftButtonText}>Retry saving review</Text>
            </Pressable>
          </View>
        )}
        {commitRetryLocked && (
          <Text style={styles.reviewReadiness}>
            Your reviewed decision is preserved. Retry will submit the same direction and variation names.
          </Text>
        )}
        <View style={styles.footerActions}>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ disabled: busy || reviewDraftSaveState !== 'saved' }}
            disabled={busy || reviewDraftSaveState !== 'saved'}
            style={[
              styles.secondaryButton,
              (busy || reviewDraftSaveState !== 'saved') && styles.buttonDisabled,
            ]}
            onPress={leaveReviewAndStartAnother}>
            <Text style={styles.secondaryButtonText}>Leave in Activity &amp; start another</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{
              disabled: busy || !decisionVisualsReady || reviewDraftSaveState !== 'saved',
            }}
            style={[
              styles.primaryButton,
              (busy || !decisionVisualsReady || reviewDraftSaveState !== 'saved')
                && styles.buttonDisabled,
            ]}
            disabled={busy || !decisionVisualsReady || reviewDraftSaveState !== 'saved'}
            onPress={() => void continueWithSelection()}>
            <Text style={styles.primaryButtonText}>{busy
              ? 'Saving directions…'
              : `Continue with Direction ${candidates.findIndex((candidate) => candidate.asset_id === selectedAssetId) + 1}${retainedCount === 0
                ? ''
                : ` · keep ${retainedCount} variation${retainedCount === 1 ? '' : 's'}`}`}</Text>
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
        accessibilityLabel={createBriefLabel}
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
          <Text style={styles.referenceTitle}>Start from an image (optional)</Text>
          <Text style={styles.referenceHelp}>{masterReference === null
            ? 'Upload one design whose visible form you want to carry forward.'
            : masterReference.label}</Text>
        </View>
        {masterReference === null ? (
          <Pressable
            accessibilityRole="button"
            style={styles.addSourceButton}
            onPress={() => requestReference('master_geometry')}>
            <Text style={styles.addSourceButtonText}>Upload drawing, photo, or render</Text>
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
        accessibilityLabel="Guide the look"
        accessibilityState={{ expanded: setupOpen }}
        onPress={() => setSetupOpen((current) => !current)}
        style={[styles.setupDisclosure, setupOpen && styles.setupDisclosureOpen]}>
        <View style={styles.setupDisclosureCopy}>
          <Text style={styles.setupDisclosureTitle}>Guide the look (optional)</Text>
          <Text style={styles.setupDisclosureSummary}>
            {selectedGuidanceLabels(guidance).length === 0
              ? 'Facetta decides the look'
              : selectedGuidanceLabels(guidance).join(' · ')}
            {secondaryReferences.length === 0
              ? ''
              : ` · ${secondaryReferences.length} inspiration image${secondaryReferences.length === 1 ? '' : 's'}`}
          </Text>
        </View>
        <Text style={styles.disclosureGlyph}>{setupOpen ? '−' : '+'}</Text>
      </Pressable>

      {setupOpen && (
        <View style={styles.setupPanel}>
          <Text style={styles.sectionHelp}>Tap only what matters to you. Leave the rest for Facetta to decide.</Text>
          {(Object.keys(guidanceChoices) as Array<keyof StudioCreateGuidance>).map((key) => {
            const group = guidanceChoices[key];
            return (
              <View key={key} style={styles.guidanceGroup}>
                <Text style={styles.sectionTitle}>{group.title}</Text>
                {group.help !== null && <Text style={styles.sectionHelp}>{group.help}</Text>}
                <View style={styles.choiceRow}>
                  {group.choices.map(([value, label]) => (
                    <Pressable
                      key={value}
                      accessibilityRole="radio"
                      accessibilityLabel={`${group.title}: ${label}`}
                      accessibilityState={{ checked: guidance[key] === value }}
                      onPress={() => updateDraft((current) => ({
                        ...current,
                        guidance: { ...current.guidance, [key]: value },
                      }))}
                      style={[
                        styles.choiceChip,
                        guidance[key] === value && styles.choiceChipSelected,
                      ]}>
                      <Text style={[
                        styles.choiceChipText,
                        guidance[key] === value && styles.choiceChipTextSelected,
                      ]}>{label}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            );
          })}

          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Add inspiration images"
            accessibilityState={{ expanded: inspirationImagesOpen }}
            onPress={() => setInspirationImagesOpen((current) => !current)}
            style={styles.imageDisclosure}>
            <View style={styles.setupDisclosureCopy}>
              <Text style={styles.referenceTitle}>Add inspiration images (optional)</Text>
              <Text style={styles.referenceHelp}>Use a picture only when it explains the look better than words.</Text>
            </View>
            <Text style={styles.disclosureGlyph}>{inspirationImagesOpen ? '−' : '+'}</Text>
          </Pressable>

          {inspirationImagesOpen && (
            <View style={styles.referenceList}>
              {createReferenceControls.filter(
                (control): control is typeof control & { role: SecondaryCreateReferenceRole } => (
                  control.role !== 'master_geometry'
                ),
              ).map(({ role }) => {
                const presentation = imageReferencePresentation[role];
                const reference = references.find((item) => item.role === role);
                const advisoryInputReady = sentence.trim().length > 0 || masterReference !== null;
                return (
                  <View key={role} style={styles.referenceRow}>
                    {reference !== undefined && (
                      <StudioReviewImage
                        accessibilityLabel={`${presentation.label} preview`}
                        inspectionLabel={`${presentation.label} · ${reference.label}`}
                        source={{ uri: referencePreviewUri(reference) }}
                        onLoad={() => visualReview.markReady(referenceVisualKey(reference))}
                        onError={() => visualReview.markFailed(referenceVisualKey(reference))}
                        style={styles.referenceThumbnail}
                      />
                    )}
                    <View style={styles.referenceCopy}>
                      <Text style={styles.referenceTitle}>{presentation.label}</Text>
                      <Text style={styles.referenceHelp}>{reference?.label ?? presentation.help}</Text>
                    </View>
                    {reference === undefined ? (
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel={presentation.action}
                        accessibilityHint={!advisoryInputReady
                          ? 'Add a design sentence or visual source before choosing an inspiration image.'
                          : presentation.help}
                        accessibilityState={{ disabled: !advisoryInputReady }}
                        disabled={!advisoryInputReady}
                        style={[styles.referenceButton, !advisoryInputReady && styles.buttonDisabled]}
                        onPress={() => requestReference(role)}>
                        <Text style={styles.referenceButtonText}>
                          {!advisoryInputReady ? 'Add an idea first' : 'Choose image'}
                        </Text>
                      </Pressable>
                    ) : (
                      <View style={styles.referenceActions}>
                        <Pressable
                          accessibilityRole="button"
                          accessibilityLabel={`Replace ${presentation.label}`}
                          style={styles.referenceButton}
                          onPress={() => requestReference(role)}>
                          <Text style={styles.referenceButtonText}>Replace</Text>
                        </Pressable>
                        <Pressable
                          accessibilityRole="button"
                          accessibilityLabel={`Remove ${presentation.label}`}
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
          )}
        </View>
      )}

      <Text style={styles.sectionTitle}>How many design options?</Text>
      <Text style={styles.sectionHelp}>
        Each option is a different design concept—not another camera angle. You’ll compare them, choose one to refine, and may keep the others as variations.
      </Text>
      <View style={styles.outputGrid}>
        {createOutputChoices.map((count) => (
          <Pressable
            key={count}
            accessibilityRole="radio"
            accessibilityLabel={`${count} design option${count === 1 ? '' : 's'}: ${outputChoiceCopy[count].detail}. ${outputChoiceCopy[count].example}`}
            accessibilityState={{ checked: candidateCount === count }}
            style={[styles.outputCard, candidateCount === count && styles.outputCardSelected]}
            onPress={() => updateDraft((current) => ({ ...current, candidateCount: count }))}>
            <Text style={[styles.outputTitle, candidateCount === count && styles.outputTextSelected]}>
              {outputChoiceCopy[count].title}
            </Text>
            <Text style={[styles.outputDetail, candidateCount === count && styles.outputTextSelected]}>
              {outputChoiceCopy[count].detail}
            </Text>
            <Text style={[styles.outputExample, candidateCount === count && styles.outputTextSelected]}>
              {outputChoiceCopy[count].example}
            </Text>
            <Text style={[styles.outputCredits, candidateCount === count && styles.outputTextSelected]}>
              {createControls.estimateCredits(count)} credits
            </Text>
          </Pressable>
        ))}
      </View>

      {masterReference === null
        && secondaryReferences.length > 0
        && sentence.trim().length === 0 && (
        <View style={styles.limitNotice}>
          <Text style={styles.limitTitle}>Add a design idea</Text>
          <Text style={styles.limitBody}>
            Inspiration images can guide material, a specific jewelry detail, or visual mood after you add a design sentence or one source image. They do not define the jewelry on their own.
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
        {createControls.estimateCredits(candidateCount)} credits total · {createCreditsPerOutput} per delivered option
      </Text>
      <Text style={styles.creditHelp}>You’re charged only for delivered design options.</Text>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled: !canCreate }}
        disabled={!canCreate}
        style={[styles.primaryButton, !canCreate && styles.buttonDisabled]}
        onPress={create}>
        <Text style={styles.primaryButtonText}>{busy ? 'Creating…' : `Create ${candidateCount} design option${candidateCount === 1 ? '' : 's'}`}</Text>
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
  directionCompareBlock: {
    borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg,
    backgroundColor: theme.card, marginTop: 14, overflow: 'hidden',
  },
  directionCompareDisclosure: {
    minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14,
  },
  directionCompareDisclosureCopy: { flex: 1 },
  directionCompareTitle: { color: theme.ink, fontSize: 13, fontWeight: '800' },
  directionCompareHelp: { color: theme.faint, fontSize: 11, lineHeight: 16, marginTop: 3 },
  directionCompareOptions: {
    flexDirection: 'row', flexWrap: 'wrap', gap: 8,
    borderTopWidth: 1, borderTopColor: theme.line, padding: 14,
  },
  directionCompareOption: {
    minHeight: 44, justifyContent: 'center', borderWidth: 1, borderColor: theme.line,
    borderRadius: radius.pill, backgroundColor: theme.paper, paddingHorizontal: 14,
  },
  directionCompareOptionSelected: { borderColor: '#6f52d9', backgroundColor: '#eee9ff' },
  directionCompareOptionText: { color: theme.faint, fontSize: 11, fontWeight: '700' },
  directionCompareOptionTextSelected: { color: '#5c3fc0' },
  reviewDraftError: { marginTop: 10, gap: 8, alignItems: 'flex-start' },
  retryDraftButton: {
    minHeight: 44, justifyContent: 'center', borderWidth: 1, borderColor: '#b83a4b',
    borderRadius: radius.pill, backgroundColor: '#fff5f6', paddingHorizontal: 14,
  },
  retryDraftButtonText: { color: '#9b2437', fontSize: 11, fontWeight: '800' },
  prompt: { minHeight: 112, borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, color: theme.ink, fontSize: 16, lineHeight: 23, padding: 16, marginTop: 22, textAlignVertical: 'top' },
  sectionTitle: { color: theme.ink, fontSize: 14, fontWeight: '700', marginTop: 22 },
  sectionHelp: { color: theme.faint, fontSize: 11, lineHeight: 16, marginTop: 4 },
  choiceRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 7, marginTop: 8 },
  choiceChip: { minHeight: 44, justifyContent: 'center', borderWidth: 1, borderColor: theme.line, borderRadius: radius.pill, backgroundColor: theme.card, paddingHorizontal: 12, paddingVertical: 8 },
  choiceChipSelected: { borderColor: '#6f52d9', backgroundColor: '#eee9ff' },
  choiceChipText: { color: theme.faint, fontSize: 10, fontWeight: '700' },
  choiceChipTextSelected: { color: '#5c3fc0' },
  guidanceGroup: { marginTop: 2 },
  imageDisclosure: { minHeight: 58, flexDirection: 'row', alignItems: 'center', gap: 12, borderWidth: 1, borderColor: theme.line, borderRadius: radius.lg, backgroundColor: theme.card, padding: 14, marginTop: 22 },
  outputGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 10 },
  outputCard: { width: '48%', minHeight: 166, borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, backgroundColor: theme.card, padding: 12, justifyContent: 'space-between' },
  outputCardSelected: { borderColor: '#6f52d9', backgroundColor: '#6f52d9' },
  outputTitle: { color: theme.ink, fontSize: 12, fontWeight: '800' },
  outputDetail: { color: theme.faint, fontSize: 10, lineHeight: 15, marginTop: 5 },
  outputExample: { color: theme.faint, fontSize: 9, lineHeight: 14, marginTop: 6 },
  outputCredits: { color: '#5c3fc0', fontSize: 10, fontWeight: '800', marginTop: 8 },
  outputTextSelected: { color: '#ffffff' },
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
  creditHelp: { color: theme.faint, fontSize: 10, lineHeight: 15, marginTop: 3 },
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
  keepVariation: {
    minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 8,
    borderTopWidth: 1, borderTopColor: theme.line, paddingHorizontal: 12, paddingVertical: 9,
  },
  keepVariationDisabled: { opacity: 0.5 },
  keepBox: {
    width: 18, height: 18, alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: theme.line, borderRadius: 5, backgroundColor: theme.paper,
  },
  keepBoxChecked: { borderColor: '#6f52d9', backgroundColor: '#6f52d9' },
  keepCheck: { color: '#ffffff', fontSize: 11, fontWeight: '900' },
  keepText: { color: theme.faint, fontSize: 10, fontWeight: '700' },
  keepTextChecked: { color: '#5c3fc0' },
  variationNameBlock: {
    borderTopWidth: 1, borderTopColor: theme.line, paddingHorizontal: 12, paddingVertical: 10,
  },
  variationNameLabel: { color: theme.faint, fontSize: 10, fontWeight: '700', marginBottom: 6 },
  variationNameInput: {
    minHeight: 44, borderWidth: 1, borderColor: theme.line, borderRadius: radius.md,
    backgroundColor: theme.paper, color: theme.ink, fontSize: 12, paddingHorizontal: 10,
  },
  variationNameHelp: { color: theme.faint, fontSize: 9, lineHeight: 14, marginTop: 5 },
  footerActions: { gap: 0 },
});
