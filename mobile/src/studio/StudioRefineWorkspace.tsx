import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text,
  useWindowDimensions, View,
} from 'react-native';

import { Button, ChipRow, Field, Notice } from '../components';
import { radius, theme } from '../theme';
import type {
  ComponentCatalog, ComponentCatalogOption, ComponentCatalogPath,
  ConfirmedMarkupAnnotation, JsonObject, JsonValue, MarkupReadResponse, ProjectDetail,
  StudioComponentTargeting, StudioContinuationPrompt, StudioFactPath,
} from '../trusted/types';
import {
  ANNOTATION_SNAPSHOT_SCHEMA_VERSION,
  AnnotationCanvas,
  type AnnotationCanvasSnapshot,
} from '../trusted/AnnotationCanvas';
import type { ExactStudioLineage, StudioGateway, StudioVisualLineage } from './gateway';
import type { PreviewCandidate } from './contracts';
import {
  designerCheckDetail, designerCheckLabel, designerReviewState,
} from './designerReviewLanguage';
import { designerErrorMessage } from './designerErrorMessage';
import { getStudioAction } from './actions';
import { useVisualReviewReadiness } from './useVisualReviewReadiness';
import { StudioComparisonInspector } from './StudioComparisonInspector';
import { StudioReviewImage } from './StudioReviewImage';
import { StudioDestinationChooser } from './StudioDestinationChooser';
import type { StudioDestinationContext, StudioDestinationId } from './destinations';
import {
  StudioCanvasEditPanel,
  type StudioCanvasEditMode,
  type StudioCanvasEditRequest,
  type StudioCanvasEditWorkingState,
} from './StudioCanvasEditPanel';
import { StudioPromptHistory } from './StudioPromptHistory';

const REFINE_CREDITS_PER_OUTPUT = getStudioAction('refine').creditEstimate ?? 0;

const PATHS: readonly { id: ComponentCatalogPath; label: string; help: string }[] = [
  { id: 'metal.color', label: 'Metal color', help: 'Change only the visible metal color.' },
  { id: 'metal.material', label: 'Metal material', help: 'Explore a different material while preserving form.' },
  { id: 'stone.color', label: 'Stone color', help: 'Change the selected stone color only.' },
  { id: 'stone.cut', label: 'Stone cut', help: 'Preview a controlled cut change.' },
  { id: 'setting.style', label: 'Setting', help: 'Preview a supported setting construction.' },
  { id: 'chain.style', label: 'Chain', help: 'Preview a supported chain direction.' },
] as const;

export type StudioRefineApi = Pick<StudioGateway,
  'getComponentCatalog' | 'getStudioComponentTargeting' | 'readMarkup'>
  & Partial<Pick<StudioGateway,
    'getProject' | 'getStudioContinuationPrompts'
    | 'prepareStudioComponentMap' | 'reviseStudioFacts'>>;

export type StudioRefineWorkspaceMode = 'refine' | 'specifications';

export interface StudioRefineDraft {
  instruction: string;
  snapshot: AnnotationCanvasSnapshot;
  canvasMode: StudioCanvasEditMode;
  variationName: string;
}

export interface StudioRefineWorkspaceProps {
  api: StudioRefineApi;
  gateway: Pick<StudioGateway,
    | 'previewCatalogRefine' | 'applyCatalogRefine' | 'discardCatalogRefine'
    | 'previewMarkupRefine' | 'applyMarkupRefine' | 'discardMarkupRefine'
    | 'previewVisualRefine' | 'applyVisualRefine' | 'discardVisualRefine'>
    & Partial<Pick<StudioGateway,
      'resumeRefine' | 'saveCatalogPreviewAsVariation' | 'saveMarkupPreviewAsVariation'
      | 'saveVisualPreviewAsVariation'>>;
  lineage: ExactStudioLineage | StudioVisualLineage | null;
  project?: ProjectDetail | null;
  createdBy: string;
  sourceImageUrl?: string | null;
  workspaceMode?: StudioRefineWorkspaceMode;
  onReviewStartingDesign?: () => void;
  onApplied: (project: ProjectDetail) => void;
  onVariationCreated?: (project: ProjectDetail) => void;
  onStartNewDesign?: () => void;
  destinationContext?: StudioDestinationContext;
  onSelectDestination?: (destinationId: StudioDestinationId) => void;
  imageRequestHeaders?: Readonly<Record<string, string>>;
  resumeReviewJobId?: string;
  reviewSourceIsActive?: boolean;
  /** Lineage-scoped unsaved work owned by the app shell so navigation cannot erase it. */
  draft?: StudioRefineDraft;
  onDraftChange?: (draft: StudioRefineDraft) => void;
}

interface AcceptedRefineOutcome {
  kind: 'revision' | 'variation';
  lineageKey: string;
  revision: number | null;
  variationName: string | null;
}

function projectLineageKey(project: ProjectDetail): string | null {
  if (project.active_asset_id === null) return null;
  return `${project.root_id}:${project.active_asset_id}:${project.active_design_version ?? 'visual'}`;
}

function activeRevisionNumber(project: ProjectDetail): number | null {
  if (project.active_asset_id === null) return null;
  if (project.active_revision?.asset_id === project.active_asset_id) {
    return project.active_revision.revision;
  }
  return project.revisions.find(
    (revision) => revision.asset.asset_id === project.active_asset_id,
  )?.asset.revision ?? null;
}

function optionDetail(option: ComponentCatalogOption): string {
  const frozen = option.frozen_facts.length > 0
    ? `Preserves ${option.frozen_facts.join(', ')}.`
    : 'All unrelated visible design facts remain frozen.';
  return `${option.isolation_target}. ${frozen}`;
}

function hasExactSpecification(
  lineage: ExactStudioLineage | StudioVisualLineage | null,
): lineage is ExactStudioLineage {
  return lineage !== null && 'sourceDesignVersion' in lineage;
}

type FactKind = 'text' | 'number' | 'integer' | 'choice';
type FactGroupId = 'identity' | 'stone' | 'setting' | 'dimensions' | 'construction';
interface FactDefinition {
  path: StudioFactPath;
  label: string;
  kind: FactKind;
  group: FactGroupId;
  unit?: string;
  choices?: readonly string[];
  allowWhenUnset?: boolean;
}

const FACT_GROUPS: readonly { id: FactGroupId; label: string; help: string }[] = [
  { id: 'identity', label: 'Identity', help: 'Metal identity, finish, and ring size.' },
  { id: 'stone', label: 'Stone', help: 'Gem identity, cut, color, and weight.' },
  { id: 'setting', label: 'Setting', help: 'How the stone is held.' },
  { id: 'dimensions', label: 'Dimensions', help: 'Recorded stone and band measurements.' },
  { id: 'construction', label: 'Construction', help: 'Band profile and construction form.' },
] as const;

const FACTS: readonly FactDefinition[] = [
  { path: 'metal.material', label: 'Metal material', kind: 'choice', group: 'identity', choices: ['gold', 'platinum', 'silver'] },
  { path: 'metal.color', label: 'Metal color', kind: 'choice', group: 'identity', choices: ['yellow', 'rose', 'white'], allowWhenUnset: true },
  { path: 'metal.finish', label: 'Metal finish', kind: 'choice', group: 'identity', choices: ['polished', 'satin', 'brushed', 'matte'] },
  { path: 'metal.karat', label: 'Gold karat', kind: 'integer', group: 'identity', allowWhenUnset: true },
  { path: 'stone.species', label: 'Stone species', kind: 'text', group: 'stone' },
  { path: 'stone.cut', label: 'Stone cut', kind: 'text', group: 'stone' },
  { path: 'stone.color.trade', label: 'Stone trade color', kind: 'text', group: 'stone' },
  { path: 'stone.color.gia', label: 'Stone graded color', kind: 'text', group: 'stone' },
  { path: 'stone.carat', label: 'Stone weight', kind: 'number', group: 'stone', unit: 'ct' },
  { path: 'stone.dimensions_mm.length', label: 'Stone length', kind: 'number', group: 'dimensions', unit: 'mm' },
  { path: 'stone.dimensions_mm.width', label: 'Stone width', kind: 'number', group: 'dimensions', unit: 'mm' },
  { path: 'stone.dimensions_mm.depth', label: 'Stone depth', kind: 'number', group: 'dimensions', unit: 'mm' },
  { path: 'setting.style', label: 'Setting style', kind: 'choice', group: 'setting', choices: ['4_prong_basket', '6_prong_basket', 'bezel', 'semi_bezel'] },
  { path: 'setting.prong_count', label: 'Prong count', kind: 'integer', group: 'setting' },
  { path: 'setting.prong_tip_mm', label: 'Prong-tip gauge', kind: 'number', group: 'setting', unit: 'mm', allowWhenUnset: true },
  { path: 'band.profile', label: 'Band profile', kind: 'choice', group: 'construction', choices: ['half_round', 'flat', 'knife_edge', 'comfort_fit'] },
  { path: 'band.width_mm', label: 'Band width', kind: 'number', group: 'dimensions', unit: 'mm' },
  { path: 'band.thickness_mm', label: 'Band thickness', kind: 'number', group: 'dimensions', unit: 'mm' },
  { path: 'ring_size.system', label: 'Ring size system', kind: 'choice', group: 'identity', choices: ['US', 'UK', 'EU', 'JP', 'HK'] },
  { path: 'ring_size.value', label: 'Ring size', kind: 'text', group: 'identity' },
] as const;

const settingChoicesForCut = (cut: string): readonly string[] => {
  if (cut === 'round_brilliant' || cut === 'oval_brilliant') {
    return ['4_prong_basket', '6_prong_basket', 'bezel', 'semi_bezel'];
  }
  if (cut === 'emerald_cut' || cut === 'cushion') {
    return ['4_prong_basket', 'bezel', 'semi_bezel'];
  }
  return [];
};

interface FactChangeReview {
  definition: FactDefinition;
  original: JsonValue;
  value: JsonValue;
}

function factValue(spec: JsonObject, path: StudioFactPath): JsonValue | undefined {
  let current: JsonValue = spec;
  for (const key of path.split('.')) {
    if (current === null || Array.isArray(current) || typeof current !== 'object'
        || !(key in current)) return undefined;
    current = current[key] as JsonValue;
  }
  return current;
}

function factText(value: JsonValue): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}

function friendlyFactOption(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function confirmedAnnotationsFromRead(
  reading: MarkupReadResponse,
): ConfirmedMarkupAnnotation[] {
  return (reading.interpretations ?? [reading.interpretation]).map((interpretation) => ({
    region_description: interpretation.target_region,
    change_instruction: interpretation.requested_change,
    impact: interpretation.impact,
    target_section: interpretation.target_section,
    target_ref: interpretation.target_spec_reference,
    index: interpretation.target_index,
    target_component_id: interpretation.target_component_id,
    target_element_id: interpretation.target_element_id,
    form_view: 'three_quarter',
    mask_base64: null,
  }));
}

export function StudioRefineWorkspace({
  api, gateway, lineage, project = null, createdBy, sourceImageUrl = null, workspaceMode = 'refine',
  onReviewStartingDesign, onApplied, onVariationCreated, destinationContext,
  onSelectDestination, onStartNewDesign,
  imageRequestHeaders, resumeReviewJobId, reviewSourceIsActive = true,
  draft, onDraftChange,
}: StudioRefineWorkspaceProps) {
  const exactLineage = hasExactSpecification(lineage) ? lineage : null;
  const exactSpecification = exactLineage !== null;
  const [mode, setMode] = useState<'component' | 'instruction' | 'annotation' | 'facts'>(
    exactSpecification && workspaceMode === 'specifications' ? 'facts' : 'instruction',
  );
  const [path, setPath] = useState<ComponentCatalogPath>('metal.color');
  const [catalog, setCatalog] = useState<ComponentCatalog | null>(null);
  const [targeting, setTargeting] = useState<StudioComponentTargeting | null>(null);
  const [targetingLoading, setTargetingLoading] = useState(
    exactSpecification && workspaceMode === 'refine',
  );
  const [targetingError, setTargetingError] = useState<string | null>(null);
  const [optionId, setOptionId] = useState<string | null>(null);
  const [preview, setPreview] = useState<{
    candidate: PreviewCandidate;
    kind: 'catalog' | 'markup' | 'visual';
    executionMode?: 'instant' | 'provider';
    estimatedCredits?: number;
  } | null>(null);
  const [instruction, setInstruction] = useState(draft?.instruction ?? '');
  const [previewPrompt, setPreviewPrompt] = useState<string | null>(null);
  const [understoodAs, setUnderstoodAs] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<AnnotationCanvasSnapshot>(draft?.snapshot ?? {
    schema_version: ANNOTATION_SNAPSHOT_SCHEMA_VERSION,
    coordinate_space: 'normalized_image',
    source_uri: sourceImageUrl ?? '',
    annotations: [],
  });
  const [loading, setLoading] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [namingVariation, setNamingVariation] = useState(
    (draft?.variationName.trim().length ?? 0) > 0,
  );
  const [variationName, setVariationName] = useState(draft?.variationName ?? '');
  const [error, setError] = useState<string | null>(null);
  const [showEditHelp, setShowEditHelp] = useState(false);
  const [acceptedOutcome, setAcceptedOutcome] = useState<AcceptedRefineOutcome | null>(null);
  const [continuationPrompts, setContinuationPrompts] = useState<
    readonly StudioContinuationPrompt[] | null
  >(null);
  const [factProject, setFactProject] = useState<ProjectDetail | null>(null);
  const [factDraft, setFactDraft] = useState<Partial<Record<StudioFactPath, string>>>({});
  const [factsLoading, setFactsLoading] = useState(false);
  const [activeFactGroup, setActiveFactGroup] = useState<FactGroupId>('identity');
  const [factReview, setFactReview] = useState<readonly FactChangeReview[] | null>(null);
  const [canvasMode, setCanvasMode] = useState<StudioCanvasEditMode>(draft?.canvasMode ?? 'describe');
  const [canvasWorking, setCanvasWorking] = useState<StudioCanvasEditWorkingState>(null);
  const { width } = useWindowDimensions();
  const isWideCanvas = Platform.OS === 'web' && width >= 1000;
  const decisionInFlight = useRef(false);
  const onDraftChangeRef = useRef(onDraftChange);
  onDraftChangeRef.current = onDraftChange;
  const everyMarkCarriesInstruction = snapshot.annotations.length > 0
    && snapshot.annotations.every((annotation) => (
      (annotation.instruction
        ?? (annotation.type === 'text' ? annotation.text : '')).trim().length > 0
    ));
  const lineageKey = lineage === null
    ? 'none'
    : `${lineage.projectId}:${lineage.sourceAssetId}:${hasExactSpecification(lineage)
      ? lineage.sourceDesignVersion
      : 'visual'}`;
  const lineageKeyRef = useRef(lineageKey);
  const lineageEpochRef = useRef(0);
  const draftLineageKey = useRef(lineageKey);
  lineageKeyRef.current = lineageKey;
  const lineageRequestIsCurrent = (requestedKey: string, requestedEpoch: number): boolean => (
    lineageKeyRef.current === requestedKey && lineageEpochRef.current === requestedEpoch
  );
  const visualReviewScope = `${lineage?.sourceAssetId ?? 'none'}:${sourceImageUrl ?? 'missing'}:${preview?.candidate.id ?? 'no-preview'}:${preview?.candidate.assetUrl ?? 'missing'}`;
  const visualReview = useVisualReviewReadiness(visualReviewScope);
  const sourceVisualKey = sourceImageUrl === null || sourceImageUrl === undefined
    ? null : `refine-source:${lineage?.sourceAssetId ?? 'none'}:${sourceImageUrl}`;
  const candidateVisualKey = preview === null
    ? null : `refine-candidate:${preview.candidate.id}:${preview.candidate.assetUrl}`;
  const comparisonVisualKeys = [sourceVisualKey, candidateVisualKey] as const;
  const comparisonReady = visualReview.allReady(comparisonVisualKeys);
  const resetAcceptedDraft = (): void => {
    setMode('instruction');
    setOptionId(null);
    setInstruction('');
    setPreviewPrompt(null);
    setUnderstoodAs(null);
    setNamingVariation(false);
    setVariationName('');
    setSnapshot((current) => ({ ...current, annotations: [] }));
  };

  useEffect(() => {
    onDraftChangeRef.current?.({ instruction, snapshot, canvasMode, variationName });
  }, [canvasMode, instruction, snapshot, variationName]);
  const exactStoneSpecies = useMemo(() => {
    const spec = factProject?.spec;
    if (spec === null || spec === undefined) return null;
    const species = factValue(spec, 'stone.species');
    if (typeof species !== 'string' || species.trim().length === 0) return null;
    return species.trim();
  }, [factProject]);

  useEffect(() => {
    lineageEpochRef.current += 1;
    const mountedEpoch = lineageEpochRef.current;
    return () => {
      // Invalidate work from both an earlier context and an unmounted workspace.
      if (lineageEpochRef.current === mountedEpoch) lineageEpochRef.current += 1;
    };
  }, [lineageKey]);

  useEffect(() => {
    let current = true;
    setTargeting(null);
    setTargetingError(null);
    if (workspaceMode !== 'refine' || exactLineage === null) {
      setTargetingLoading(false);
      return () => { current = false; };
    }
    setTargetingLoading(true);
    const loadTargeting = async () => {
      const sourceAssetId = exactLineage.sourceAssetId;
      let result = await api.getStudioComponentTargeting(sourceAssetId);
      if (!current) return;
      const canPrepare = result.error === null
        && result.data.asset_id === sourceAssetId
        && result.data.jewelry_type === 'ring'
        && result.data.component_map.scope === 'ring_v1'
        && result.data.catalog_paths.length > 0
        && result.data.catalog_paths.every((candidate) => (
          candidate.status === 'unmapped'
          && candidate.reason_code === 'component_map_not_found'
        ))
        && typeof api.prepareStudioComponentMap === 'function';
      if (canPrepare) result = await api.prepareStudioComponentMap!(sourceAssetId);
      if (!current) return;
      setTargetingLoading(false);
      if (result.error !== null) {
        setTargetingError('Precise component targeting is not available for this revision. Describe the changes or use Annotate image instead.');
        return;
      }
      if (result.data.asset_id !== sourceAssetId) {
        setTargetingError('Component targeting belongs to a different revision. Reopen the latest design before refining it.');
        return;
      }
      setTargeting(result.data);
    };
    void loadTargeting();
    return () => { current = false; };
  }, [api, exactSpecification, lineage?.sourceAssetId, workspaceMode]);

  const targetability = targeting?.catalog_paths.find(
    (candidate) => candidate.component_path === path,
  ) ?? null;
  const readyPaths = useMemo(() => targeting?.catalog_paths.filter(
    (candidate) => candidate.status === 'ready'
      && (candidate.component_path !== 'stone.color' || exactStoneSpecies !== null),
  ) ?? [], [exactStoneSpecies, targeting]);
  const componentAvailable = exactSpecification && !targetingLoading && readyPaths.length > 0;
  const selectedPathReady = targetability?.status === 'ready'
    && (path !== 'stone.color' || exactStoneSpecies !== null);

  useEffect(() => {
    if (targetingLoading || targeting === null || selectedPathReady || readyPaths.length === 0) return;
    setPath(readyPaths[0].component_path);
  }, [readyPaths, selectedPathReady, targeting, targetingLoading]);

  useEffect(() => {
    if (mode === 'component' && !targetingLoading && !componentAvailable) setMode('instruction');
  }, [componentAvailable, mode, targetingLoading]);

  useEffect(() => {
    let current = true;
    if (mode !== 'component') return () => { current = false; };
    if (!exactSpecification || targetingLoading || !selectedPathReady) {
      setLoading(false);
      setCatalog(null);
      setOptionId(null);
      return () => { current = false; };
    }
    setLoading(true);
    setCatalog(null);
    setOptionId(null);
    setError(null);
    let request;
    if (path === 'stone.color') {
      if (exactStoneSpecies === null) {
        setLoading(false);
        return () => { current = false; };
      }
      request = api.getComponentCatalog(path, { stoneSpecies: exactStoneSpecies });
    } else {
      request = api.getComponentCatalog(path);
    }
    void request.then((result) => {
      if (!current) return;
      setLoading(false);
      if (result.error !== null) {
        setError(designerErrorMessage(result.error, 'refine'));
        return;
      }
      setCatalog(result.data);
      setOptionId(result.data.options[0]?.id ?? null);
    });
    return () => { current = false; };
  }, [api, exactSpecification, exactStoneSpecies, mode, path, lineage?.sourceAssetId,
    selectedPathReady, targetingLoading]);

  useEffect(() => {
    if (!exactSpecification && mode === 'component') setMode('instruction');
  }, [exactSpecification, mode]);

  useEffect(() => {
    let current = true;
    setFactProject(null);
    setFactDraft({});
    setFactReview(null);
    if (exactLineage === null || typeof api.getProject !== 'function') {
      setFactsLoading(false);
      return () => { current = false; };
    }
    setFactsLoading(true);
    void api.getProject(exactLineage.projectId).then((result) => {
      if (!current) return;
      setFactsLoading(false);
      if (result.error !== null) {
        setError(designerErrorMessage(result.error, 'refine'));
        return;
      }
      if (
        result.data.active_asset_id !== exactLineage.sourceAssetId
        || result.data.active_design_version !== exactLineage.sourceDesignVersion
        || result.data.spec === null || result.data.spec === undefined
      ) {
        setError('This design changed before its facts could be loaded. Reopen the latest revision.');
        return;
      }
      setFactProject(result.data);
      const draft: Partial<Record<StudioFactPath, string>> = {};
      FACTS.forEach((definition) => {
        const value = factValue(result.data.spec as JsonObject, definition.path);
        if (value !== undefined && value !== null) draft[definition.path] = factText(value);
      });
      setFactDraft(draft);
    });
    return () => { current = false; };
  }, [api, exactLineage?.projectId, exactLineage?.sourceAssetId,
    exactLineage?.sourceDesignVersion]);

  useEffect(() => {
    let current = true;
    setPreview(null);
    setUnderstoodAs(null);
    if (workspaceMode !== 'refine'
      || lineage === null || typeof gateway.resumeRefine !== 'function') {
      setResuming(false);
      return () => { current = false; };
    }
    setResuming(true);
    const resumed = resumeReviewJobId === undefined
      ? gateway.resumeRefine(lineage, createdBy)
      : gateway.resumeRefine(lineage, createdBy, resumeReviewJobId);
    void resumed.then((result) => {
      if (!current) return;
      setResuming(false);
      if (result.error !== null) {
        setError(designerErrorMessage(result.error, 'refine'));
        return;
      }
      if (result.data !== null) {
        setPreview({ candidate: result.data.candidate, kind: result.data.kind });
        setUnderstoodAs(result.data.understoodAs);
      }
    });
    return () => { current = false; };
  }, [createdBy, gateway, lineage?.projectId, lineage?.sourceAssetId,
    exactLineage?.sourceDesignVersion, resumeReviewJobId, workspaceMode]);

  useEffect(() => {
    const sourceRevisionChanged = draftLineageKey.current !== lineageKey;
    draftLineageKey.current = lineageKey;
    setSnapshot((current) => ({
      ...(sourceRevisionChanged && draft !== undefined ? draft.snapshot : current),
      source_uri: sourceImageUrl ?? '',
      annotations: sourceRevisionChanged
        ? draft?.snapshot.annotations ?? []
        : current.annotations,
    }));
    if (!sourceRevisionChanged) return;
    // A designer's instruction and any pending decision belong to the exact source
    // revision on which they were authored. Never silently rebind them to another design.
    decisionInFlight.current = false;
    setBusy(false);
    setOptionId(null);
    setInstruction(draft?.instruction ?? '');
    setPreviewPrompt(null);
    setUnderstoodAs(null);
    setPreview(null);
    setCanvasMode(draft?.canvasMode ?? 'describe');
    setNamingVariation((draft?.variationName.trim().length ?? 0) > 0);
    setVariationName(draft?.variationName ?? '');
    setFactReview(null);
    setError(null);
  }, [lineageKey, sourceImageUrl]);

  useEffect(() => {
    setAcceptedOutcome((current) => (
      current === null || current.lineageKey === lineageKey ? current : null
    ));
  }, [lineageKey]);

  useEffect(() => {
    let current = true;
    if (lineage === null || typeof api.getStudioContinuationPrompts !== 'function') {
      setContinuationPrompts(null);
      return () => { current = false; };
    }
    void api.getStudioContinuationPrompts(lineage.projectId).then((result) => {
      if (!current) return;
      setContinuationPrompts(result.error === null ? result.data.prompts : null);
    });
    return () => { current = false; };
  }, [
    api,
    acceptedOutcome?.lineageKey,
    lineage?.projectId,
    preview?.candidate.id,
    preview?.candidate.status,
    project?.active_asset_id,
  ]);

  const selected = useMemo(() => catalog?.options.find((option) => option.id === optionId) ?? null,
    [catalog, optionId]);
  const catalogPreviewMode = path === 'metal.color'
    && targeting?.jewelry_type === 'ring'
    && catalog?.component_path === path
    && catalog.preview_execution_modes.includes('instant')
    ? 'instant' as const
    : 'provider' as const;
  const editableFacts = useMemo(() => {
    const spec = factProject?.spec;
    if (spec === null || spec === undefined) return [];
    return FACTS.filter((definition) => factValue(spec, definition.path) !== undefined
      && (factValue(spec, definition.path) !== null || definition.allowWhenUnset));
  }, [factProject]);

  const groupedEditableFacts = useMemo(() => Object.fromEntries(
    FACT_GROUPS.map((group) => [
      group.id, editableFacts.filter((definition) => definition.group === group.id),
    ]),
  ) as Record<FactGroupId, FactDefinition[]>, [editableFacts]);

  const collectFactChanges = (): { changes: FactChangeReview[]; error: string | null } => {
    if (factProject?.spec === null || factProject?.spec === undefined) {
      return { changes: [], error: 'Design facts are still loading. Try again in a moment.' };
    }
    const changes: FactChangeReview[] = [];
    for (const definition of editableFacts) {
      const original = factValue(factProject.spec, definition.path);
      const raw = factDraft[definition.path]?.trim() ?? '';
      if (raw.length === 0) {
        const selectedMaterial = factDraft['metal.material']
          ?? factText(factValue(factProject.spec, 'metal.material') ?? '');
        const selectedSetting = factDraft['setting.style']
          ?? factText(factValue(factProject.spec, 'setting.style') ?? '');
        const requiredDependency = (
          (definition.path === 'metal.karat' || definition.path === 'metal.color')
            && selectedMaterial === 'gold'
        ) || (
          definition.path === 'setting.prong_tip_mm'
            && ['4_prong_basket', '6_prong_basket'].includes(selectedSetting)
        );
        if (definition.allowWhenUnset && !requiredDependency) continue;
        return { changes: [], error: `${definition.label} cannot be empty.` };
      }
      let value: JsonValue = raw;
      if (definition.kind === 'number' || definition.kind === 'integer') {
        const parsed = Number(raw);
        if (!Number.isFinite(parsed) || parsed <= 0
            || (definition.kind === 'integer' && !Number.isInteger(parsed))) {
          return {
            changes: [],
            error: `${definition.label} must be a valid positive ${definition.kind === 'integer' ? 'whole number' : 'number'}.`,
          };
        }
        value = parsed;
      } else if (definition.path === 'ring_size.value') {
        const system = factDraft['ring_size.system'] ?? factText(
          factValue(factProject.spec, 'ring_size.system') ?? '',
        );
        if (system !== 'UK') {
          const parsed = Number(raw);
          if (!Number.isFinite(parsed) || parsed <= 0) {
            return {
              changes: [],
              error: 'Ring size must be a positive number for the selected sizing system.',
            };
          }
          value = parsed;
        }
      }
      if (JSON.stringify(value) !== JSON.stringify(original)) {
        changes.push({ definition, original: original ?? null, value });
      }
    }
    if (changes.length === 0) {
      return { changes: [], error: 'Nothing changed. Edit at least one design fact before reviewing.' };
    }
    if (changes.length > 12) {
      return { changes: [], error: 'Review up to 12 fact changes at a time.' };
    }
    return { changes, error: null };
  };

  const reviewFacts = (): void => {
    const result = collectFactChanges();
    if (result.error !== null) {
      setError(result.error);
      setFactReview(null);
      return;
    }
    setError(null);
    setFactReview(result.changes);
  };

  const saveFacts = async (): Promise<void> => {
    if (
      exactLineage === null || factProject?.spec === null || factProject?.spec === undefined
      || typeof api.reviseStudioFacts !== 'function' || busy || decisionInFlight.current
    ) return;
    const requestedLineageKey = lineageKey;
    const requestedLineageEpoch = lineageEpochRef.current;
    const reviewed = collectFactChanges();
    if (reviewed.error !== null || factReview === null) {
      setError(reviewed.error ?? 'Review the changed facts before saving.');
      setFactReview(null);
      return;
    }
    const changes = reviewed.changes.map(({ definition, value }) => ({
      path: definition.path, value,
    }));
    decisionInFlight.current = true;
    setBusy(true);
    setError(null);
    const result = await api.reviseStudioFacts(exactLineage.projectId, {
      expected_active_asset_id: exactLineage.sourceAssetId,
      expected_design_version: exactLineage.sourceDesignVersion,
      created_by: createdBy,
      changes,
    });
    if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
    decisionInFlight.current = false;
    setBusy(false);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'refine'));
      return;
    }
    onApplied(result.data.project_detail);
  };

  const makePreview = async (): Promise<void> => {
    if (lineage === null || busy || !reviewSourceIsActive) return;
    setAcceptedOutcome(null);
    if (mode === 'facts') { reviewFacts(); return; }
    const requestedLineageKey = lineageKey;
    const requestedLineageEpoch = lineageEpochRef.current;
    setBusy(true);
    setError(null);
    setUnderstoodAs(null);
    if (mode === 'component') {
      if (!exactSpecification) {
        setBusy(false);
        setError('Confirm design facts before making structural component changes.');
        return;
      }
      if (!selectedPathReady) {
        setBusy(false);
        setError('Precise targeting is not available for this component on the selected revision.');
        return;
      }
      if (selected === null) { setBusy(false); return; }
      const result = await gateway.previewCatalogRefine({
        ...exactLineage, createdBy, componentPath: path, optionId: selected.id,
        executionMode: catalogPreviewMode,
      });
      if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
      setBusy(false);
      if (result.error !== null) { setError(designerErrorMessage(result.error, 'refine')); return; }
      setPreviewPrompt(`Change ${path.replaceAll('.', ' ')} to ${selected.display}.`);
      setPreview({
        candidate: result.data.candidate,
        kind: 'catalog',
        executionMode: result.data.executionMode,
        estimatedCredits: result.data.estimatedCredits,
      });
      return;
    }
    let annotation: ConfirmedMarkupAnnotation = {
      region_description: 'entire visible jewelry presentation',
      change_instruction: instruction.trim(),
      impact: 'visual_only' as const,
      target_section: null, target_ref: null, index: null,
      target_component_id: null,
      target_element_id: null, form_view: 'three_quarter' as const,
      mask_base64: null,
    };
    let markupAssetId: string | null = null;
    if (mode === 'annotation') {
      if (snapshot.annotations.length === 0) {
        setBusy(false); setError('Mark at least one area before creating a preview.'); return;
      }
      if (!instruction.trim() && !everyMarkCarriesInstruction) {
        setBusy(false);
        setError('Describe what should change in the marked areas, or place a Text instruction at every marked location.');
        return;
      }
      const read = await api.readMarkup(lineage.sourceAssetId, {
        markup_snapshot: snapshot,
        ...(instruction.trim() ? { instruction: instruction.trim() } : {}),
        created_by: createdBy,
      });
      if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
      if (read.error !== null) { setBusy(false); setError(designerErrorMessage(read.error, 'refine')); return; }
      if (exactLineage !== null
          && read.data.expected_design_version !== exactLineage.sourceDesignVersion) {
        setBusy(false); setError('The annotation was interpreted against a different revision. Reopen the design.'); return;
      }
      const confirmedAnnotations = confirmedAnnotationsFromRead(read.data);
      if (confirmedAnnotations.length === 0) {
        setBusy(false);
        setError('Facetta could not match the marks to editable jewelry regions. Adjust the marks and try again.');
        return;
      }
      if (!exactSpecification && confirmedAnnotations.some(
        ({ impact }) => impact !== 'visual_only',
      )) {
        setBusy(false);
        setError('This mark changes jewelry structure or construction. Confirm design facts before previewing it.');
        return;
      }
      [annotation] = confirmedAnnotations;
      markupAssetId = read.data.markup_asset_id;
      setUnderstoodAs(read.data.interpretation.understood_as);
      const result = exactLineage !== null
        ? await gateway.previewMarkupRefine({
            ...exactLineage, createdBy, annotation, annotations: confirmedAnnotations,
            markupAssetId,
          })
        : await gateway.previewVisualRefine({
            ...lineage,
            createdBy,
            instruction: instruction.trim() || 'Apply every placed text instruction.',
            rawUserInstruction: instruction.trim() || confirmedAnnotations
              .map((item) => item.change_instruction)
              .join(' '),
            inputMode: 'point',
            annotations: confirmedAnnotations.map((item) => ({
              region_description: item.region_description,
              change_instruction: item.change_instruction,
            })),
            scope: 'marked_region',
            markupAssetId: markupAssetId ?? '',
          });
      if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
      setBusy(false);
      if (result.error !== null) { setError(designerErrorMessage(result.error, 'refine')); return; }
      setPreviewPrompt(instruction.trim() || confirmedAnnotations
        .map((item) => item.change_instruction)
        .join(' '));
      setPreview({
        candidate: result.data.candidate,
        kind: exactLineage !== null ? 'markup' : 'visual',
      });
      return;
    } else if (!instruction.trim()) {
      setBusy(false); return;
    }
    const result = exactLineage !== null
      ? await gateway.previewMarkupRefine({
          ...exactLineage, createdBy, annotation, markupAssetId,
        })
      : await gateway.previewVisualRefine({
          ...lineage,
          createdBy,
          instruction: annotation.change_instruction,
          rawUserInstruction: instruction.trim(),
          inputMode: 'describe',
          scope: 'appearance',
        });
    if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
    setBusy(false);
    if (result.error !== null) { setError(designerErrorMessage(result.error, 'refine')); return; }
    setPreviewPrompt(instruction.trim());
    setPreview({
      candidate: result.data.candidate,
      kind: exactLineage !== null ? 'markup' : 'visual',
    });
  };

  const makeCanvasPreview = async (request: StudioCanvasEditRequest): Promise<void> => {
    if (lineage === null || busy || !reviewSourceIsActive) return;
    const requestedLineageKey = lineageKey;
    const requestedLineageEpoch = lineageEpochRef.current;
    const typedInstruction = request.instruction.trim();
    const designerInstruction = request.mode === 'symmetry'
      ? 'Make the corresponding left and right jewelry elements symmetrical.'
      : typedInstruction;
    if (!typedInstruction
        && !(request.mode === 'point' && everyMarkCarriesInstruction)) return;

    setAcceptedOutcome(null);
    setCanvasWorking('preview');
    setBusy(true);
    setError(null);
    setUnderstoodAs(null);

    let annotation: ConfirmedMarkupAnnotation = {
      region_description: 'entire visible jewelry presentation',
      change_instruction: typedInstruction,
      impact: 'visual_only',
      target_section: null,
      target_ref: null,
      index: null,
      target_component_id: null,
      target_element_id: null,
      form_view: 'three_quarter',
      mask_base64: null,
    };
    let markupAssetId: string | null = null;

    if (request.mode === 'point') {
      if (snapshot.annotations.length === 0) {
        setBusy(false);
        setCanvasWorking(null);
        setError('Mark at least one area before creating a preview.');
        return;
      }
      const read = await api.readMarkup(lineage.sourceAssetId, {
        markup_snapshot: snapshot,
        ...(typedInstruction ? { instruction: typedInstruction } : {}),
        created_by: createdBy,
      });
      if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
      if (read.error !== null) {
        setBusy(false);
        setCanvasWorking(null);
        setError(designerErrorMessage(read.error, 'refine'));
        return;
      }
      if (exactLineage !== null
          && read.data.expected_design_version !== exactLineage.sourceDesignVersion) {
        setBusy(false);
        setCanvasWorking(null);
        setError('The mark belongs to a different revision. Reopen the current design and mark it again.');
        return;
      }
      const confirmedAnnotations = confirmedAnnotationsFromRead(read.data);
      if (confirmedAnnotations.length === 0) {
        setBusy(false);
        setCanvasWorking(null);
        setError('Facetta could not match the marks to editable jewelry regions. Adjust the marks and try again.');
        return;
      }
      [annotation] = confirmedAnnotations;
      markupAssetId = read.data.markup_asset_id;
      setUnderstoodAs(read.data.interpretation.understood_as);
      const result = exactLineage !== null
        ? await gateway.previewMarkupRefine({
            ...exactLineage,
            createdBy,
            annotation,
            annotations: confirmedAnnotations,
            markupAssetId,
          })
        : await gateway.previewVisualRefine({
            ...lineage,
            createdBy,
            instruction: typedInstruction,
            rawUserInstruction: designerInstruction || confirmedAnnotations
              .map((item) => item.change_instruction)
              .join(' '),
            inputMode: 'point',
            annotations: confirmedAnnotations.map((item) => ({
              region_description: item.region_description,
              change_instruction: item.change_instruction,
            })),
            scope: 'marked_region',
            markupAssetId: markupAssetId ?? '',
          });
      if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
      setBusy(false);
      setCanvasWorking(null);
      if (result.error !== null) {
        setError(designerErrorMessage(result.error, 'refine'));
        return;
      }
      setPreviewPrompt(typedInstruction || 'Changes described on the marked areas.');
      setPreview({
        candidate: result.data.candidate,
        kind: exactLineage !== null ? 'markup' : 'visual',
      });
      return;
    } else {
      const freeze = request.mode === 'angle'
        ? ' Change only the camera viewpoint. Keep the exact jewelry geometry, stone count, settings, metal, finish, scale, lighting family, and background fixed.'
        : request.mode === 'background'
          ? ' Change only the background and its natural contact shadow. Keep the exact jewelry, camera viewpoint, crop, scale, stones, settings, metal, and finish fixed.'
          : request.mode === 'symmetry'
            ? ' This is an intentional bilateral symmetry repair. Change only the corresponding left and right elements needed to match the requested pattern. Keep the center element and every unmentioned jewelry and presentation detail fixed.'
          : ' Make only the requested changes. Keep every unmentioned design, material, camera, and background detail fixed.';
      annotation = { ...annotation, change_instruction: `${typedInstruction}${freeze}` };
    }

    const result = exactLineage !== null
      ? await gateway.previewMarkupRefine({
          ...exactLineage,
          createdBy,
          annotation,
          markupAssetId,
        })
      : await gateway.previewVisualRefine({
          ...lineage,
          createdBy,
          instruction: annotation.change_instruction,
          rawUserInstruction: designerInstruction,
          inputMode: request.mode,
          scope: 'appearance',
        });

    if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
    setBusy(false);
    setCanvasWorking(null);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'refine'));
      return;
    }
    setPreviewPrompt(designerInstruction);
    setPreview({
      candidate: result.data.candidate,
      kind: exactLineage !== null ? 'markup' : 'visual',
    });
  };

  const apply = async (): Promise<void> => {
    if (preview === null || busy || decisionInFlight.current
      || preview.candidate.verdict === 'reject' || !reviewSourceIsActive
      || !comparisonReady) return;
    const requestedLineageKey = lineageKey;
    const requestedLineageEpoch = lineageEpochRef.current;
    decisionInFlight.current = true;
    setBusy(true);
    setError(null);
    const result = preview.kind === 'catalog'
      ? await gateway.applyCatalogRefine({ candidateId: preview.candidate.id, createdBy })
      : preview.kind === 'markup'
        ? await gateway.applyMarkupRefine({ candidateId: preview.candidate.id, createdBy })
        : await gateway.applyVisualRefine({ candidateId: preview.candidate.id, createdBy });
    if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
    setBusy(false);
    decisionInFlight.current = false;
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'refine'));
      return;
    }
    if (result.data.project === null) {
      setError('The accepted preview did not return a saved revision. Nothing was changed.');
      return;
    }
    const acceptedLineageKey = projectLineageKey(result.data.project);
    if (acceptedLineageKey !== null) {
      setAcceptedOutcome({
        kind: 'revision',
        lineageKey: acceptedLineageKey,
        revision: activeRevisionNumber(result.data.project),
        variationName: null,
      });
    }
    setPreview(null);
    resetAcceptedDraft();
    onApplied(result.data.project);
  };

  const discard = async (): Promise<void> => {
    if (preview === null || busy || decisionInFlight.current) return;
    const requestedLineageKey = lineageKey;
    const requestedLineageEpoch = lineageEpochRef.current;
    decisionInFlight.current = true;
    setBusy(true);
    setError(null);
    const result = preview.kind === 'catalog'
      ? await gateway.discardCatalogRefine({ candidateId: preview.candidate.id, createdBy })
      : preview.kind === 'markup'
        ? await gateway.discardMarkupRefine({ candidateId: preview.candidate.id, createdBy })
        : await gateway.discardVisualRefine({ candidateId: preview.candidate.id, createdBy });
    if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
    setBusy(false);
    decisionInFlight.current = false;
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'refine'));
      return;
    }
    setPreview(null);
    setPreviewPrompt(null);
    setNamingVariation(false);
    setVariationName('');
  };

  const saveAsVariation = async (): Promise<void> => {
    if (preview === null || busy || decisionInFlight.current
      || preview.candidate.verdict === 'reject' || !comparisonReady) return;
    const requestedLineageKey = lineageKey;
    const requestedLineageEpoch = lineageEpochRef.current;
    const label = variationName.trim();
    if (label.length === 0) {
      setError('Give this variation a short name before saving it.');
      return;
    }
    setBusy(true);
    setError(null);
    const saveCatalog = gateway.saveCatalogPreviewAsVariation;
    const saveMarkup = gateway.saveMarkupPreviewAsVariation;
    const saveVisual = gateway.saveVisualPreviewAsVariation;
    if ((preview.kind === 'catalog' && saveCatalog === undefined)
        || (preview.kind === 'markup' && saveMarkup === undefined)
        || (preview.kind === 'visual' && saveVisual === undefined)) {
      setError('Saving this preview as a variation is temporarily unavailable.');
      return;
    }
    decisionInFlight.current = true;
    const result = preview.kind === 'catalog'
      ? await saveCatalog!({
          candidateId: preview.candidate.id, createdBy, label,
        })
      : preview.kind === 'markup'
        ? await saveMarkup!({
            candidateId: preview.candidate.id, createdBy, label,
          })
      : await saveVisual!({
          candidateId: preview.candidate.id, createdBy, label,
        });
    if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
    setBusy(false);
    decisionInFlight.current = false;
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'refine'));
      return;
    }
    const acceptedLineageKey = projectLineageKey(result.data.project);
    if (acceptedLineageKey !== null) {
      setAcceptedOutcome({
        kind: 'variation',
        lineageKey: acceptedLineageKey,
        revision: activeRevisionNumber(result.data.project),
        variationName: label,
      });
    }
    setPreview(null);
    resetAcceptedDraft();
    onVariationCreated?.(result.data.project);
  };

  const applyCanvasPreview = async (): Promise<void> => {
    setCanvasWorking('apply');
    try {
      await apply();
    } finally {
      setCanvasWorking(null);
    }
  };

  const discardCanvasPreview = async (): Promise<void> => {
    setCanvasWorking('discard');
    try {
      await discard();
    } finally {
      setCanvasWorking(null);
    }
  };

  if (lineage === null) {
    return (
      <View style={styles.empty}>
        <Text style={styles.title}>Choose a saved direction first</Text>
        <Text style={styles.body}>Refine always starts from one saved revision.</Text>
      </View>
    );
  }

  if (workspaceMode === 'specifications' && exactLineage === null) {
    return (
      <View style={styles.empty}>
        <Text style={styles.title}>Choose an exact saved revision first</Text>
        <Text style={styles.body}>Specifications can only update recorded facts on an exact revision.</Text>
      </View>
    );
  }

  if (workspaceMode === 'refine' && isWideCanvas) {
    const sourceUnavailable = sourceImageUrl === null;
    const editDisabled = !reviewSourceIsActive || sourceUnavailable;
    const applyDisabled = preview !== null && (
      preview.candidate.verdict === 'reject' || !reviewSourceIsActive || !comparisonReady
    );
    const applyDisabledReason = preview?.candidate.verdict === 'reject'
      ? 'This preview did not pass Facetta review. Discard it and adjust the request.'
      : !reviewSourceIsActive
        ? 'This preview came from an older revision and cannot be applied to the current design.'
        : preview !== null && !comparisonReady
          ? 'Wait until both the source and preview images are ready before applying.'
          : null;
    const variationSupported = preview !== null && (preview.kind === 'catalog'
      ? gateway.saveCatalogPreviewAsVariation !== undefined
      : preview.kind === 'markup'
        ? gateway.saveMarkupPreviewAsVariation !== undefined
        : gateway.saveVisualPreviewAsVariation !== undefined);
    const previewSummary = preview === null ? null : {
      title: 'Compare it with the source',
      summary: understoodAs
        ?? 'This is a temporary image-model result. Apply only after the jewelry outside your request still matches.',
    };
    return (
      <View style={styles.canvasWorkspace}>
        <ScrollView
          testID="refine-web-canvas"
          style={styles.canvasStage}
          contentContainerStyle={styles.canvasStageContent}>
          <View style={styles.canvasHeader}>
            <Text style={styles.eyebrow}>{preview === null ? 'DESIGN CANVAS' : 'TEMPORARY PREVIEW'}</Text>
            <Text style={styles.canvasHeading}>{preview === null
              ? 'Edit beside the design.'
              : 'Check the change before it enters history.'}</Text>
            <Text style={styles.canvasSubheading}>{preview === null
              ? 'Mark one or several areas, describe the changes, or choose a quick action. The source stays visible while you work.'
              : 'The source remains unchanged until you choose Apply.'}</Text>
          </View>

          {preview !== null && sourceImageUrl !== null ? (
            <StudioComparisonInspector
              before={{
                label: 'Selected saved direction',
                roleLabel: 'Source',
                accessibilityLabel: 'Selected source design',
                source: { uri: sourceImageUrl },
                imageRequestHeaders,
                onLoad: () => visualReview.markReady(sourceVisualKey),
                onError: () => visualReview.markFailed(sourceVisualKey),
              }}
              after={{
                label: 'Temporary change',
                roleLabel: 'Preview',
                accessibilityLabel: 'Temporary edited design preview',
                source: { uri: preview.candidate.assetUrl },
                imageRequestHeaders,
                onLoad: () => visualReview.markReady(candidateVisualKey),
                onError: () => visualReview.markFailed(candidateVisualKey),
              }}
              compactHeight={520}
              inspectionTitle="Compare source and temporary change"
              inspectionHelp="Inspect the marked areas and confirm the rest of the jewelry has not drifted."
              testID="canvas-edit-comparison"
            />
          ) : sourceImageUrl === null ? (
            <View style={styles.canvasUnavailable}>
              <Text style={styles.reviewTitle}>The selected image is unavailable.</Text>
              <Text style={styles.pathHelp}>Reopen the design from Collections before editing it.</Text>
            </View>
          ) : canvasMode === 'point' ? (
            <View style={styles.annotationStage}>
              <AnnotationCanvas
                sourceUri={sourceImageUrl}
                value={snapshot}
                onChange={setSnapshot}
                drawingEnabled
                initialTool="text"
              />
              <Text style={styles.annotationHelp}>
                Point or draw around every relevant area. Use the panel to describe the changes that belong there.
              </Text>
            </View>
          ) : (
            <StudioReviewImage
              accessibilityLabel="Selected design to edit"
              inspectionLabel="Selected design"
              source={{ uri: sourceImageUrl }}
              imageRequestHeaders={imageRequestHeaders}
              onLoad={() => visualReview.markReady(sourceVisualKey)}
              onError={() => visualReview.markFailed(sourceVisualKey)}
              style={styles.canvasSourceImage}
            />
          )}

          {acceptedOutcome !== null && (
            <View accessibilityRole="summary" style={styles.acceptedOutcomeCard}>
              <Text style={styles.acceptedOutcomeEyebrow}>SAVED</Text>
              <Text style={styles.acceptedOutcomeTitle}>{acceptedOutcome.revision === null
                ? 'Saved as a new immutable revision.'
                : `Saved as Revision ${acceptedOutcome.revision}.`}</Text>
              <Text style={styles.acceptedOutcomeBody}>
                The previous revision remains available in Collections. You can continue editing this new revision here.
              </Text>
            </View>
          )}
        </ScrollView>

        <ScrollView
          testID="refine-web-tools"
          style={styles.canvasToolRail}
          contentContainerStyle={styles.canvasToolRailContent}>
          <StudioPromptHistory
            project={project}
            continuationPrompts={continuationPrompts}
            previewPrompt={preview === null ? null : previewPrompt}
            onStartNewDesign={onStartNewDesign}
            onReusePrompt={(prompt) => {
              setMode('instruction');
              setInstruction(prompt);
              setPreview(null);
              setPreviewPrompt(null);
              setUnderstoodAs(null);
              setError(null);
            }}
            compact
          />
          <StudioCanvasEditPanel
            annotation={{
              markCount: snapshot.annotations.length,
              everyMarkCarriesInstruction,
              label: snapshot.annotations.length === 0
                ? 'No area marked yet'
                : `${snapshot.annotations.length} mark${snapshot.annotations.length === 1 ? '' : 's'} ready`,
            }}
            preview={previewSummary}
            working={canvasWorking}
            disabled={editDisabled}
            disabledReason={!reviewSourceIsActive
              ? 'This preview came from an older revision. Reopen the current design before making another change.'
              : sourceUnavailable ? 'The selected source image is unavailable.' : null}
            applyDisabled={applyDisabled}
            applyDisabledReason={applyDisabledReason}
            error={error}
            creditEstimate={REFINE_CREDITS_PER_OUTPUT}
            instructionValue={instruction}
            modeValue={canvasMode}
            onInstructionChange={setInstruction}
            onModeChange={(nextMode) => {
              setCanvasMode(nextMode);
              setMode(nextMode === 'point' ? 'annotation' : 'instruction');
              setError(null);
            }}
            onRequestAnnotation={() => {
              setCanvasMode('point');
              setMode('annotation');
              setError(null);
            }}
            onClearAnnotation={() => setSnapshot((current) => ({
              ...current,
              annotations: [],
            }))}
            onPreviewChange={(request) => { void makeCanvasPreview(request); }}
            onApplyPreview={() => { void applyCanvasPreview(); }}
            onSaveAsVariationPreview={variationSupported ? () => {
              setNamingVariation(true);
              setError(null);
            } : undefined}
            onDiscardPreview={() => { void discardCanvasPreview(); }}
          />
          {preview !== null && namingVariation && variationSupported && (
            <View style={styles.variationCard}>
              <Field
                label="Variation name"
                value={variationName}
                onChange={setVariationName}
                placeholder="e.g. Rose gold halo"
              />
              <Text style={styles.checkDetail}>
                This creates a sibling direction. The selected source revision and its history stay unchanged.
              </Text>
              <View style={styles.actions}>
                <Button
                  title="Cancel"
                  kind="ghost"
                  disabled={busy}
                  onPress={() => {
                    setNamingVariation(false);
                    setVariationName('');
                    setError(null);
                  }}
                />
                <Button
                  title={busy ? 'Saving…' : 'Save named variation'}
                  disabled={busy || variationName.trim().length === 0
                    || preview.candidate.verdict === 'reject' || !comparisonReady}
                  onPress={() => { void saveAsVariation(); }}
                />
              </View>
            </View>
          )}
          <View style={styles.canvasAdvancedNote}>
            <Text style={styles.pathTitle}>Need precision controls?</Text>
            <Text style={styles.pathHelp}>
              Component maps and advanced specifications remain available from More after you establish the visual direction.
            </Text>
          </View>
        </ScrollView>
      </View>
    );
  }

  if (workspaceMode === 'refine' && preview !== null) {
    const rejected = preview.candidate.verdict === 'reject';
    const variationSupported = preview.kind === 'catalog'
      ? gateway.saveCatalogPreviewAsVariation !== undefined
      : preview.kind === 'markup'
        ? gateway.saveMarkupPreviewAsVariation !== undefined
        : gateway.saveVisualPreviewAsVariation !== undefined;
    return (
      <ScrollView contentContainerStyle={styles.workspace}>
        <Text style={styles.eyebrow}>REVIEW PREVIEW</Text>
        <Text style={styles.title}>Nothing has changed yet.</Text>
        <Text style={styles.body}>
          Compare this temporary candidate with the selected source revision. Apply will append a new revision;
          save as variation will start a sibling direction; discard will leave history untouched.
        </Text>
        {preview.kind === 'catalog' && preview.executionMode !== undefined && (
          <Notice
            kind="info"
            text={preview.executionMode === 'instant'
              ? 'Quick preview · 0 credits'
              : `Standard preview · estimated ${preview.estimatedCredits ?? REFINE_CREDITS_PER_OUTPUT} credits if you Apply or Save as Variation`}
          />
        )}
        {understoodAs !== null && <Notice kind="info" text={understoodAs} />}
        {!reviewSourceIsActive && (
          <Notice kind="info" text="This result was created from an earlier revision. Apply is unavailable. You can save it as a new variation or discard it without changing the current design." />
        )}
        {sourceImageUrl !== null ? (
          <StudioComparisonInspector
            before={{
              label: exactLineage === null
                ? 'Selected saved direction'
                : 'Exact selected revision',
              roleLabel: 'Source',
              accessibilityLabel: 'Exact source revision',
              source: { uri: sourceImageUrl },
              imageRequestHeaders,
              onLoad: () => visualReview.markReady(sourceVisualKey),
              onError: () => visualReview.markFailed(sourceVisualKey),
            }}
            after={{
              label: 'Temporary refinement candidate',
              roleLabel: 'Preview',
              accessibilityLabel: 'Temporary refinement preview',
              source: { uri: preview.candidate.assetUrl },
              imageRequestHeaders,
              onLoad: () => visualReview.markReady(candidateVisualKey),
              onError: () => visualReview.markFailed(candidateVisualKey),
            }}
            inspectionTitle="Inspect source and temporary preview"
            inspectionHelp="Compare matching jewelry regions for geometry, setting, proportion, material, and unintended drift before deciding."
            testID="refine-comparison-inspector"
          />
        ) : (
          <View style={styles.compareRow}>
            <View style={styles.comparePane}>
              <Text style={styles.compareLabel}>PREVIEW</Text>
              <StudioReviewImage
                accessibilityLabel="Temporary refinement preview"
                inspectionLabel="Temporary refinement candidate"
                source={{ uri: preview.candidate.assetUrl }}
                imageRequestHeaders={imageRequestHeaders}
                onLoad={() => visualReview.markReady(candidateVisualKey)}
                onError={() => visualReview.markFailed(candidateVisualKey)}
                style={styles.preview}
              />
            </View>
          </View>
        )}
        {!comparisonReady && (
          <Notice
            kind="error"
            text={visualReview.anyFailed(comparisonVisualKeys)
              ? 'The exact source or preview could not be displayed. Reopen the design or generate this preview again before accepting it.'
              : 'Wait for the exact source and preview to finish loading before accepting this result.'}
          />
        )}
        <View style={styles.reviewCard}>
          <Text style={styles.reviewTitle}>{rejected ? 'Not safe to apply' : 'Ready for your decision'}</Text>
          {preview.candidate.checks.map((check) => (
            <View key={check.id} style={styles.checkRow}>
              <Text style={[styles.checkVerdict, check.verdict === 'reject' && styles.reject]}>
                {designerReviewState(check.verdict)}
              </Text>
              <View style={styles.checkCopy}>
                <Text style={styles.checkLabel}>{designerCheckLabel(check)}</Text>
                <Text style={styles.checkDetail}>{designerCheckDetail(check)}</Text>
              </View>
            </View>
          ))}
        </View>
        {error !== null && <Notice kind="error" text={error} />}
        {namingVariation && variationSupported && (
          <View style={styles.variationCard}>
            <Field
              label="Variation name"
              value={variationName}
              onChange={setVariationName}
              placeholder="e.g. Rose gold halo"
            />
            <Text style={styles.checkDetail}>
              This saves the preview into a new sibling project. The source revision stays unchanged.
            </Text>
            <View style={styles.actions}>
              <Button
                title="Cancel"
                kind="ghost"
                disabled={busy}
                onPress={() => { setNamingVariation(false); setVariationName(''); setError(null); }}
              />
              <Button
                title={busy ? 'Saving…' : 'Save named variation'}
                disabled={busy || variationName.trim().length === 0 || rejected || !comparisonReady}
                onPress={() => { void saveAsVariation(); }}
              />
            </View>
          </View>
        )}
        <View style={styles.actions}>
          <Button title={busy ? 'Working…' : 'Discard'} kind="ghost" disabled={busy} onPress={() => { void discard(); }} />
          {variationSupported && !namingVariation && (
            <Button
              title="Save as Variation"
              kind="ghost"
              disabled={busy || rejected || !comparisonReady}
              onPress={() => { setNamingVariation(true); setError(null); }}
            />
          )}
          <Button title={busy ? 'Working…' : 'Apply as new revision'} disabled={busy || rejected || !comparisonReady || !reviewSourceIsActive} onPress={() => { void apply(); }} />
        </View>
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
      {workspaceMode === 'refine' && acceptedOutcome !== null && (
        <View accessibilityRole="summary" style={styles.acceptedOutcomeCard}>
          <Text style={styles.acceptedOutcomeEyebrow}>SAVED</Text>
          <Text style={styles.acceptedOutcomeTitle}>{acceptedOutcome.kind === 'variation'
            ? `Variation “${acceptedOutcome.variationName}” is ready.`
            : acceptedOutcome.revision === null
              ? 'Saved as a new immutable revision.'
              : `Saved as Revision ${acceptedOutcome.revision}.`}</Text>
          <Text style={styles.acceptedOutcomeBody}>{acceptedOutcome.kind === 'variation'
            ? 'The source revision is unchanged. You are now working in this named sibling with its own immutable history.'
            : 'The accepted preview is now the active immutable revision. The earlier revision remains in Collections.'}</Text>
          <View style={styles.acceptedOutcomeActions}>
            <Button
              title="Continue refining"
              kind="ghost"
              onPress={() => setAcceptedOutcome(null)}
            />
          </View>
          {destinationContext !== undefined && onSelectDestination !== undefined && (
            <StudioDestinationChooser
              context={destinationContext}
              onSelect={onSelectDestination}
            />
          )}
        </View>
      )}
      <Text style={styles.eyebrow}>{workspaceMode === 'specifications'
        ? 'SPECIFICATIONS' : 'REFINE'}</Text>
      <Text style={styles.title}>{workspaceMode === 'specifications'
        ? 'Correct the recorded facts for this revision.'
        : 'Show Facetta what you want to change.'}</Text>
      <Text style={styles.body}>{workspaceMode === 'specifications'
        ? 'Review only the facts that need correction. Saving appends an immutable specification revision without changing image pixels.'
        : 'Describe everything you want to change. For precise edits, mark every relevant area on the selected design and add the instructions that belong to those marks. You will review a temporary preview before anything is saved.'}</Text>

      {!reviewSourceIsActive && <Notice kind="info" text="This Activity result was created from an earlier revision. Review the existing preview below; creating or applying another change from this source is unavailable." />}

      {workspaceMode === 'refine' && resuming && <Notice kind="info" text="Checking for a pending preview from this exact revision…" />}

      {workspaceMode === 'refine' && (
        <View testID="refine-active-design" style={styles.activeDesignCard}>
          <View style={styles.activeDesignHeader}>
            <View style={styles.activeDesignCopy}>
              <Text style={styles.activeDesignEyebrow}>SELECTED DESIGN</Text>
              <Text style={styles.activeDesignTitle}>{mode === 'annotation'
                ? 'Mark the areas you want to edit'
                : 'This is the design you are editing'}</Text>
            </View>
            {mode === 'annotation' && (
              <Text style={styles.markCount}>{snapshot.annotations.length === 0
                ? 'No marks yet'
                : `${snapshot.annotations.length} mark${snapshot.annotations.length === 1 ? '' : 's'}`}</Text>
            )}
          </View>
          {sourceImageUrl === null ? (
            <Notice kind="error" text="The selected design image is unavailable. Reopen it from Collections before refining." />
          ) : mode === 'annotation' ? (
            <AnnotationCanvas
              sourceUri={sourceImageUrl}
              value={snapshot}
              onChange={setSnapshot}
              drawingEnabled
              initialTool="text"
              testID="refine-annotation-canvas"
            />
          ) : (
            <StudioReviewImage
              accessibilityLabel="Selected design being refined"
              inspectionLabel="Selected design"
              source={{ uri: sourceImageUrl }}
              imageRequestHeaders={imageRequestHeaders}
              style={styles.activeDesignImage}
            />
          )}
          <Text style={styles.activeDesignHelp}>{mode === 'annotation'
            ? 'Use Arrow, Circle, Rectangle, Freehand, or Text. You can add multiple marks, then describe all of the requested changes below.'
            : 'Describe all requested changes below, or choose Annotate image to point, circle, draw, or place notes directly on this jewelry.'}</Text>
        </View>
      )}

      {workspaceMode === 'refine' && (
        <StudioPromptHistory
          project={project}
          continuationPrompts={continuationPrompts}
          previewPrompt={preview === null ? null : previewPrompt}
          onStartNewDesign={onStartNewDesign}
          onReusePrompt={(prompt) => {
            setMode('instruction');
            setInstruction(prompt);
            setPreview(null);
            setPreviewPrompt(null);
            setUnderstoodAs(null);
            setError(null);
          }}
        />
      )}

      {workspaceMode === 'refine' && <View style={styles.modeRow}>
        {([
          ['component', 'Component', 'Choose a controlled material or construction option.'],
          ['instruction', 'Describe changes', 'Write all requested changes in plain language.'],
          ['annotation', 'Annotate image', 'Point, circle, draw, or add notes on the selected design.'],
        ] as const).filter(([id]) => id !== 'component' || componentAvailable)
          .map(([id, label, detail]) => (
            <Pressable
              key={id}
              accessibilityLabel={id === 'annotation' ? 'Mark up refine mode'
                : id === 'instruction' ? 'Describe refine mode' : `${label} refine mode`}
              accessibilityRole="button"
              accessibilityState={{ selected: mode === id }}
              onPress={() => {
                setMode(id);
                setFactReview(null);
                setError(null);
              }}
              style={[styles.modeCard, mode === id && styles.selectedCard]}>
              <Text style={styles.pathTitle}>{label}</Text>
              <Text style={styles.pathHelp}>{detail}</Text>
            </Pressable>
          ))}
      </View>}

      {workspaceMode === 'refine'
        && targetingError !== null && <Notice kind="error" text={targetingError} />}
      {workspaceMode === 'refine'
        && exactSpecification && !targetingLoading && targetingError === null
        && readyPaths.length === 0 && (
        <Notice kind="info" text="This revision has no precisely mapped component regions yet. Describe the changes or use Annotate image; Facetta will not guess component geometry." />
      )}

      {workspaceMode === 'refine' && mode === 'component' && <>
        <Text style={styles.sectionTitle}>1 · Component</Text>
        <View style={styles.pathGrid}>
          {PATHS.map((item) => {
            const capability = targeting?.catalog_paths.find(
              (candidate) => candidate.component_path === item.id,
            ) ?? null;
            const missingStoneSpecies = item.id === 'stone.color' && exactStoneSpecies === null;
            const unavailable = capability?.status !== 'ready' || missingStoneSpecies;
            const help = capability?.status === 'ready' && missingStoneSpecies
              ? 'Record the exact stone species in Advanced design facts before choosing a color.'
              : capability?.status === 'ready' ? item.help
              : capability?.status === 'unmapped'
                ? 'Precise targeting has not been mapped for this revision.'
                : capability?.status === 'unresolved'
                  ? 'This design is not ready for that precise component edit yet. Use Describe changes or Annotate image so Facetta can preserve unmentioned areas.'
                  : 'Precise component targeting is not released for this category.';
            return (
              <Pressable
                key={item.id}
                accessibilityLabel={`${item.label} component path`}
                accessibilityRole="button"
                accessibilityState={{ disabled: unavailable, selected: path === item.id }}
                disabled={unavailable}
                onPress={() => setPath(item.id)}
                style={[styles.pathCard, path === item.id && styles.selectedCard,
                  unavailable && styles.disabledCard]}>
                <Text style={styles.pathTitle}>{item.label}</Text>
                <Text style={styles.pathHelp}>{help}</Text>
              </Pressable>
            );
          })}
        </View>
        <Text style={styles.sectionTitle}>2 · Direction</Text>
        {loading ? <ActivityIndicator color={theme.accent} /> : (
          <View style={styles.optionList}>
            {catalog?.options.map((option) => (
              <Pressable key={option.id} onPress={() => setOptionId(option.id)} style={[styles.optionCard, optionId === option.id && styles.selectedCard]}>
                <Text style={styles.optionTitle}>{option.display}</Text>
                <Text style={styles.optionDetail}>{optionDetail(option)}</Text>
              </Pressable>
            ))}
          </View>
        )}
      </>}

      {workspaceMode === 'refine' && mode === 'instruction' && <>
        <Field label="Describe the changes" value={instruction} onChange={setInstruction} multiline
          placeholder="For example: Make the center stone oval, use finer prongs, and narrow both shoulders. Preserve everything I did not mention." />
        <View style={styles.editHelpRow}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="How Facetta protects unmentioned areas"
            accessibilityState={{ expanded: showEditHelp }}
            onPress={() => setShowEditHelp((visible) => !visible)}
            style={styles.editHelpButton}>
            <Text style={styles.editHelpIcon}>?</Text>
          </Pressable>
        </View>
        {showEditHelp && <Notice kind="info" text={exactSpecification
          ? 'Facetta interprets the complete request and preserves unmentioned areas. Use Annotate image when a change belongs to a specific part of the jewelry.'
          : 'Facetta interprets the complete visual request and preserves unmentioned areas. Save starting design facts only when you need production-specific component or construction control.'} />}
      </>}

      {workspaceMode === 'refine' && mode === 'annotation' && (sourceImageUrl === null ? (
        <Notice kind="error" text="The exact active image is unavailable for annotation. Reopen the design or use Describe changes." />
      ) : <>
        <Field
          label="Instructions for the marked areas"
          value={instruction}
          onChange={setInstruction}
          multiline
          placeholder="For example: Make both circled shoulders narrower, replace the marked prongs with finer claws, and keep every unmarked area unchanged."
        />
        <Text style={styles.pathHelp}>Each mark establishes where to edit; these instructions explain what to change. Facetta will show its interpretation before Apply.</Text>
      </>)}
      {workspaceMode === 'specifications' && mode === 'facts' && <>
        <Notice kind="info" text="Fact corrections cost 0 credits. Image pixels stay unchanged while Facetta appends a new immutable specification revision." />
        {factsLoading ? <ActivityIndicator color={theme.accent} /> : editableFacts.length === 0 ? (
          <Notice kind="error" text="No designer-editable facts are available on this exact revision." />
        ) : factReview !== null ? (
          <View style={styles.factReviewCard}>
            <Text style={styles.reviewTitle}>Review only what changed</Text>
            <Text style={styles.pathHelp}>Saving appends a new immutable specification revision. The image remains unchanged.</Text>
            {factReview.map(({ definition, original, value }) => (
              <View key={definition.path} style={styles.factReviewRow}>
                <Text style={styles.factReviewLabel}>{definition.label}</Text>
                <Text style={styles.factReviewValue}>
                  {friendlyFactOption(String(original))} → {friendlyFactOption(String(value))}
                  {definition.unit ? ` ${definition.unit}` : ''}
                </Text>
              </View>
            ))}
            <View style={styles.actions}>
              <Button
                title="Back to edit"
                kind="ghost"
                disabled={busy}
                onPress={() => { setFactReview(null); setError(null); }}
              />
              <Button
                title={busy ? 'Saving facts…' : 'Save fact revision'}
                disabled={busy}
                onPress={() => { void saveFacts(); }}
              />
            </View>
          </View>
        ) : (<>
          <View style={styles.factGroupList}>
            {FACT_GROUPS.map((group) => {
              const groupFacts = groupedEditableFacts[group.id];
              if (groupFacts.length === 0) return null;
              const expanded = activeFactGroup === group.id;
              return (
                <Pressable
                  key={group.id}
                  accessibilityRole="button"
                  accessibilityLabel={`${group.label} fact group`}
                  accessibilityState={{ expanded }}
                  onPress={() => { setActiveFactGroup(group.id); setError(null); }}
                  style={[styles.factGroupButton, expanded && styles.selectedCard]}>
                  <View style={styles.advancedDisclosureCopy}>
                    <Text style={styles.pathTitle}>{group.label}</Text>
                    <Text style={styles.pathHelp}>{group.help}</Text>
                  </View>
                  <Text style={styles.factCount}>{groupFacts.length}</Text>
                </Pressable>
              );
            })}
          </View>
          <View style={styles.factGrid}>
            {groupedEditableFacts[activeFactGroup].map((definition) => {
              const value = factDraft[definition.path] ?? '';
              if (definition.kind === 'choice') {
                const controlledChoices = definition.path === 'setting.style'
                  ? settingChoicesForCut(factDraft['stone.cut'] ?? factText(
                    factValue(factProject?.spec as JsonObject, 'stone.cut') ?? '',
                  ))
                  : definition.choices;
                const options = controlledChoices?.includes(value)
                  ? controlledChoices
                  : [value, ...(controlledChoices ?? [])].filter(Boolean);
                return (
                  <ChipRow
                    key={definition.path}
                    label={definition.label}
                    options={options}
                    value={value}
                    render={friendlyFactOption}
                    onSelect={(next) => {
                      setError(null);
                      setFactReview(null);
                      setFactDraft((current) => ({ ...current, [definition.path]: next }));
                    }}
                  />
                );
              }
              return (
                <View key={definition.path} style={styles.factField}>
                  <Field
                    label={`${definition.label}${definition.unit ? ` (${definition.unit})` : ''}`}
                    value={value}
                    numeric={definition.kind === 'number' || definition.kind === 'integer'}
                    onChange={(next) => {
                      setError(null);
                      setFactReview(null);
                      setFactDraft((current) => ({ ...current, [definition.path]: next }));
                    }}
                  />
                </View>
              );
            })}
          </View>
        </>)}
      </>}
      {error !== null && <Notice kind="error" text={error} />}
      <Text style={styles.creditEstimate}>{workspaceMode === 'specifications'
        ? '0 credits · specification revision only'
        : mode === 'component' && catalogPreviewMode === 'instant'
          ? 'Quick preview · 0 credits'
          : `1 requested output × ${REFINE_CREDITS_PER_OUTPUT} credits = estimated ${REFINE_CREDITS_PER_OUTPUT} credits`}</Text>
      {workspaceMode === 'refine' ? (
        <Button title={busy ? 'Creating preview…' : 'Preview changes'} disabled={busy || !reviewSourceIsActive
          || (mode === 'component' && (selected === null || !selectedPathReady))
          || (mode === 'instruction' && !instruction.trim())
          || (mode === 'annotation' && (sourceImageUrl === null
            || snapshot.annotations.length === 0
            || (!instruction.trim() && !everyMarkCarriesInstruction)))}
          onPress={() => { void makePreview(); }} />
      ) : factReview === null && (
        <Button title="Review fact changes" disabled={busy || !reviewSourceIsActive || factsLoading || editableFacts.length === 0}
          onPress={() => { void makePreview(); }} />
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  workspace: { padding: 22, paddingBottom: 120, gap: 12 },
  canvasWorkspace: {
    flex: 1,
    minHeight: 0,
    flexDirection: 'row',
    backgroundColor: '#f4f1eb',
  },
  canvasStage: { flex: 1, minWidth: 0 },
  canvasStageContent: {
    width: '100%',
    maxWidth: 1120,
    minHeight: '100%',
    alignSelf: 'center',
    padding: 28,
    gap: 18,
  },
  canvasHeader: { maxWidth: 720 },
  canvasHeading: {
    color: theme.ink,
    fontFamily: theme.serif,
    fontSize: 30,
    lineHeight: 37,
    marginTop: 7,
  },
  canvasSubheading: { color: theme.faint, fontSize: 13, lineHeight: 19, marginTop: 5 },
  canvasSourceImage: {
    width: '100%',
    maxWidth: 760,
    aspectRatio: 1,
    alignSelf: 'center',
    borderRadius: radius.lg,
    backgroundColor: theme.card,
  },
  annotationStage: {
    width: '100%',
    maxWidth: 820,
    alignSelf: 'center',
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.lg,
    backgroundColor: theme.card,
    padding: 14,
    gap: 10,
  },
  annotationHelp: { color: theme.faint, fontSize: 12, lineHeight: 18 },
  canvasUnavailable: {
    minHeight: 420,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderStyle: 'dashed',
    borderColor: theme.line,
    borderRadius: radius.lg,
    backgroundColor: theme.card,
    padding: 28,
  },
  canvasToolRail: {
    width: 360,
    flexGrow: 0,
    flexShrink: 0,
    borderLeftWidth: 1,
    borderLeftColor: theme.line,
    backgroundColor: theme.paper,
  },
  canvasToolRailContent: { padding: 20, paddingBottom: 100, gap: 14 },
  canvasAdvancedNote: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: radius.md,
    backgroundColor: theme.card,
    padding: 14,
  },
  empty: { padding: 28, alignItems: 'center', gap: 8 },
  eyebrow: { color: theme.accent, fontSize: 11, fontWeight: '800', letterSpacing: 2 },
  title: { color: theme.ink, fontFamily: theme.serif, fontSize: 28, lineHeight: 34 },
  body: { color: theme.faint, fontSize: 14, lineHeight: 21, maxWidth: 680 },
  activeDesignCard: {
    backgroundColor: theme.card,
    borderColor: theme.line,
    borderRadius: radius.lg,
    borderWidth: 1,
    gap: 10,
    overflow: 'hidden',
    padding: 12,
  },
  activeDesignHeader: {
    alignItems: 'flex-start',
    flexDirection: 'row',
    gap: 10,
    justifyContent: 'space-between',
  },
  activeDesignCopy: { flex: 1 },
  activeDesignEyebrow: {
    color: theme.accent,
    fontSize: 10,
    fontWeight: '800',
    letterSpacing: 1.4,
  },
  activeDesignTitle: { color: theme.ink, fontSize: 17, fontWeight: '800', marginTop: 3 },
  activeDesignImage: {
    aspectRatio: 1,
    backgroundColor: '#f1efe9',
    borderRadius: radius.md,
    width: '100%',
  },
  activeDesignHelp: { color: theme.faint, fontSize: 12, lineHeight: 18 },
  markCount: {
    backgroundColor: theme.blush,
    borderRadius: 999,
    color: theme.accent,
    fontSize: 11,
    fontWeight: '800',
    overflow: 'hidden',
    paddingHorizontal: 9,
    paddingVertical: 5,
  },
  sectionTitle: { color: theme.ink, fontSize: 12, fontWeight: '800', letterSpacing: 1.4, marginTop: 12 },
  pathGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  modeRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8 },
  modeCard: { width: 210, borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 12, backgroundColor: theme.card },
  acceptedOutcomeCard: {
    backgroundColor: '#f1fbf6', borderColor: '#8ed8b6', borderRadius: radius.lg,
    borderWidth: 1, gap: 8, marginBottom: 8, padding: 16,
  },
  acceptedOutcomeEyebrow: {
    color: '#287556', fontSize: 10, fontWeight: '800', letterSpacing: 1.4,
  },
  acceptedOutcomeTitle: { color: theme.ink, fontSize: 18, fontWeight: '800' },
  acceptedOutcomeBody: { color: theme.faint, fontSize: 13, lineHeight: 19, maxWidth: 640 },
  acceptedOutcomeActions: { alignItems: 'flex-start', flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  advancedDisclosureCopy: { flex: 1 },
  advancedDisclosureTitle: { color: theme.ink, fontWeight: '700', fontSize: 14, marginBottom: 3 },
  startingFactsCard: {
    borderWidth: 1, borderColor: theme.accent, borderRadius: radius.md, padding: 13,
    backgroundColor: theme.card, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12,
  },
  startingFactsCopy: { flexGrow: 1, flexShrink: 1, flexBasis: 360 },
  disabledCard: { opacity: 0.48 },
  pathCard: { width: 180, borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 12, backgroundColor: theme.card },
  selectedCard: { borderColor: theme.accent, borderWidth: 2 },
  pathTitle: { color: theme.ink, fontWeight: '700', marginBottom: 4 },
  pathHelp: { color: theme.faint, fontSize: 12, lineHeight: 17 },
  optionList: { gap: 8 },
  optionCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 13, backgroundColor: theme.card },
  optionTitle: { color: theme.ink, fontWeight: '700', fontSize: 15 },
  optionDetail: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 4 },
  editHelpRow: { alignItems: 'flex-end', marginTop: -4 },
  editHelpButton: {
    width: 44, height: 44, alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: theme.line, borderRadius: 22, backgroundColor: theme.card,
  },
  editHelpIcon: { color: theme.ink, fontSize: 18, fontWeight: '800' },
  creditEstimate: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 6 },
  compareRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  comparePane: { flexGrow: 1, flexBasis: 280, gap: 6 },
  compareLabel: { color: theme.faint, fontSize: 10, fontWeight: '800', letterSpacing: 1.2 },
  preview: { width: '100%', aspectRatio: 1.25, borderRadius: radius.lg, backgroundColor: theme.line },
  reviewCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 14, backgroundColor: theme.card, gap: 8 },
  variationCard: { borderWidth: 1, borderColor: theme.accent, borderRadius: radius.md, padding: 14, backgroundColor: theme.card, gap: 8 },
  reviewTitle: { color: theme.ink, fontWeight: '800', fontSize: 16 },
  checkRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  checkVerdict: { color: theme.ok, width: 145, fontSize: 10, lineHeight: 14, fontWeight: '800', textTransform: 'uppercase' },
  reject: { color: theme.danger },
  checkCopy: { flex: 1 },
  checkLabel: { color: theme.ink, fontWeight: '600' },
  checkDetail: { color: theme.faint, fontSize: 12, marginTop: 2 },
  actions: { flexDirection: 'row', flexWrap: 'wrap' },
  factGroupList: { gap: 8 },
  factGroupButton: {
    borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 12,
    backgroundColor: theme.card, flexDirection: 'row', alignItems: 'center', gap: 12,
  },
  factCount: {
    color: theme.accent, backgroundColor: theme.blush, borderRadius: 999,
    minWidth: 28, paddingHorizontal: 8, paddingVertical: 5, textAlign: 'center', fontWeight: '800',
  },
  factGrid: { gap: 12 },
  factField: { maxWidth: 420 },
  factReviewCard: {
    borderWidth: 1, borderColor: theme.accent, borderRadius: radius.md,
    padding: 14, backgroundColor: theme.card, gap: 10,
  },
  factReviewRow: { borderTopWidth: 1, borderTopColor: theme.line, paddingTop: 9, gap: 3 },
  factReviewLabel: { color: theme.faint, fontSize: 11, fontWeight: '700' },
  factReviewValue: { color: theme.ink, fontSize: 14, fontWeight: '600' },
});
