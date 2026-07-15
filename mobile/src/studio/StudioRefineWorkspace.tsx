import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View,
} from 'react-native';

import { Button, ChipRow, Field, Notice } from '../components';
import { radius, theme } from '../theme';
import type {
  ComponentCatalog, ComponentCatalogOption, ComponentCatalogPath,
  ConfirmedMarkupAnnotation, JsonObject, JsonValue, MarkupInterpretation, ProjectDetail,
  StudioComponentTargeting,
  StudioFactPath,
} from '../trusted/types';
import {
  ANNOTATION_SNAPSHOT_SCHEMA_VERSION,
  AnnotationCanvas,
  type AnnotationCanvasSnapshot,
} from '../trusted/AnnotationCanvas';
import type {
  ExactStudioLineage, RefineReviewIntent, StudioGateway, StudioVisualLineage,
} from './gateway';
import type { PreviewCandidate } from './contracts';
import {
  designerCheckDetail, designerCheckLabel, designerReviewState,
} from './designerReviewLanguage';
import { designerErrorMessage } from './designerErrorMessage';
import { useVisualReviewReadiness } from './useVisualReviewReadiness';
import { StudioComparisonInspector } from './StudioComparisonInspector';
import { StudioReviewImage } from './StudioReviewImage';
import { StudioDestinationChooser } from './StudioDestinationChooser';
import type { StudioDestinationContext, StudioDestinationId } from './destinations';
import {
  candidateCatalogPaths, routeRefineInstruction,
} from './refineIntentRouter';
import { getStudioWorkspaceControls } from './workspaceControls';

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
    | 'confirmMarkupInterpretation' | 'getProject' | 'prepareStudioComponentMap'
    | 'reviseStudioFacts'>>;

export type StudioRefineWorkspaceMode = 'refine' | 'specifications';

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
  createdBy: string;
  sourceImageUrl?: string | null;
  workspaceMode?: StudioRefineWorkspaceMode;
  onReviewStartingDesign?: (pendingInstruction: string) => void;
  onApplied: (project: ProjectDetail) => void;
  onVariationCreated?: (project: ProjectDetail) => void;
  destinationContext?: StudioDestinationContext;
  onSelectDestination?: (destinationId: StudioDestinationId) => void;
  imageRequestHeaders?: Readonly<Record<string, string>>;
  resumeReviewJobId?: string;
  reviewSourceIsActive?: boolean;
  initialInstruction?: string;
}

interface AcceptedRefineOutcome {
  kind: 'revision' | 'variation';
  lineageKey: string;
  revision: number | null;
  variationName: string | null;
}

interface PendingAnnotationInterpretation {
  interpretationId: string;
  markupAssetId: string;
  expectedDesignVersion: number | null;
  interpretation: MarkupInterpretation;
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

function fallbackIntentLabel(value: string): string {
  const words = value.replaceAll('_', ' ').trim().toLowerCase();
  return words.length === 0 ? value : `${words[0].toUpperCase()}${words.slice(1)}`;
}

function refineIntentCopy(intent: RefineReviewIntent): {
  summary: string;
  detail: string | null;
  boundary: string;
} {
  if (intent.kind === 'component') {
    const component = intent.componentLabel
      ?? PATHS.find((candidate) => candidate.id === intent.componentPath)?.label
      ?? fallbackIntentLabel(intent.componentPath);
    const option = intent.optionLabel ?? fallbackIntentLabel(intent.optionId);
    return {
      summary: `${component} → ${option}`,
      detail: null,
      boundary: `Only ${component.toLowerCase()} may change. Inspect every other component, proportion, and material for unintended drift.`,
    };
  }
  if (intent.kind === 'describe') {
    return {
      summary: intent.instruction,
      detail: 'Appearance-only change',
      boundary: 'The requested appearance may change. Geometry, setting, proportions, and construction should remain unchanged.',
    };
  }
  const impact = intent.impact === 'specification'
    ? 'Structure or construction may change in this region'
    : intent.impact === 'visual_only'
      ? 'Appearance-only change in this region'
      : 'Change limited to this marked region';
  return {
    summary: intent.requestedChange,
    detail: `Region: ${intent.regionDescription} · ${impact}`,
    boundary: 'Only the marked region and requested detail may change. Inspect everything outside it for unintended drift.',
  };
}

export function StudioRefineWorkspace({
  api, gateway, lineage, createdBy, sourceImageUrl = null, workspaceMode = 'refine',
  onReviewStartingDesign, onApplied, onVariationCreated, destinationContext,
  onSelectDestination,
  imageRequestHeaders, resumeReviewJobId, reviewSourceIsActive = true,
  initialInstruction = '',
}: StudioRefineWorkspaceProps) {
  const refineControls = useMemo(() => getStudioWorkspaceControls('refine'), []);
  const refineInstructionLabel = refineControls.fields[0]!.label;
  const refineCreditsPerOutput = refineControls.creditsPerOutput;
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
    intent: RefineReviewIntent;
    executionMode?: 'instant' | 'provider';
    estimatedCredits?: number;
  } | null>(null);
  const [instruction, setInstruction] = useState(initialInstruction);
  const [understoodAs, setUnderstoodAs] = useState<string | null>(null);
  const [pendingAnnotation, setPendingAnnotation] = useState<PendingAnnotationInterpretation | null>(
    null,
  );
  const [routingGuidance, setRoutingGuidance] = useState<string | null>(null);
  const [startingFactsRequired, setStartingFactsRequired] = useState(false);
  const [annotationPrefill, setAnnotationPrefill] = useState('');
  const [snapshot, setSnapshot] = useState<AnnotationCanvasSnapshot>({
    schema_version: ANNOTATION_SNAPSHOT_SCHEMA_VERSION,
    coordinate_space: 'normalized_image',
    source_uri: sourceImageUrl ?? '',
    annotations: [],
  });
  const [loading, setLoading] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [namingVariation, setNamingVariation] = useState(false);
  const [variationName, setVariationName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [acceptedOutcome, setAcceptedOutcome] = useState<AcceptedRefineOutcome | null>(null);
  const [factProject, setFactProject] = useState<ProjectDetail | null>(null);
  const [factDraft, setFactDraft] = useState<Partial<Record<StudioFactPath, string>>>({});
  const [factsLoading, setFactsLoading] = useState(false);
  const [activeFactGroup, setActiveFactGroup] = useState<FactGroupId>('identity');
  const [factReview, setFactReview] = useState<readonly FactChangeReview[] | null>(null);
  const decisionInFlight = useRef(false);
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
    setUnderstoodAs(null);
    setPendingAnnotation(null);
    setRoutingGuidance(null);
    setStartingFactsRequired(false);
    setAnnotationPrefill('');
    setNamingVariation(false);
    setVariationName('');
    setSnapshot((current) => ({ ...current, annotations: [] }));
  };
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
        setTargetingError('Precise component targeting is not available for this revision. Describe an appearance change or use Mark up instead.');
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
        setPreview({
          candidate: result.data.candidate,
          kind: result.data.kind,
          intent: result.data.intent,
        });
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
      ...current,
      source_uri: sourceImageUrl ?? '',
      annotations: sourceRevisionChanged ? [] : current.annotations,
    }));
    if (!sourceRevisionChanged) return;
    // A designer's instruction and any pending decision belong to the exact source
    // revision on which they were authored. Never silently rebind them to another design.
    decisionInFlight.current = false;
    setBusy(false);
    setOptionId(null);
    setInstruction('');
    setUnderstoodAs(null);
    setPendingAnnotation(null);
    setRoutingGuidance(null);
    setStartingFactsRequired(false);
    setAnnotationPrefill('');
    setPreview(null);
    setNamingVariation(false);
    setVariationName('');
    setFactReview(null);
    setError(null);
  }, [lineageKey, sourceImageUrl]);

  useEffect(() => {
    setAcceptedOutcome((current) => (
      current === null || current.lineageKey === lineageKey ? current : null
    ));
  }, [lineageKey]);

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
    if (mode !== 'annotation') setUnderstoodAs(null);
    setRoutingGuidance(null);
    setStartingFactsRequired(false);
    let routedCatalog: {
      catalog: ComponentCatalog;
      option: ComponentCatalogOption;
      path: ComponentCatalogPath;
    } | null = null;
    let routedInstruction = instruction.trim();
    if (mode === 'instruction') {
      if (routedInstruction.length === 0) { setBusy(false); return; }
      const likelyPaths = candidateCatalogPaths(routedInstruction);
      if (exactSpecification && likelyPaths.length > 0 && targetingLoading) {
        setBusy(false);
        setRoutingGuidance('Facetta is checking the precise options for this revision. Try Preview change again in a moment; nothing has been generated or charged.');
        return;
      }
      const readyLikelyPaths = exactSpecification
        ? likelyPaths.filter((candidatePath) => targeting?.catalog_paths.some((candidate) => (
            candidate.component_path === candidatePath && candidate.status === 'ready'
          )) ?? false)
        : [];
      const routedCatalogs: ComponentCatalog[] = [];
      for (const candidatePath of readyLikelyPaths) {
        if (candidatePath === 'stone.color' && exactStoneSpecies === null) continue;
        const catalogResult = candidatePath === 'stone.color'
          ? await api.getComponentCatalog(candidatePath, { stoneSpecies: exactStoneSpecies! })
          : await api.getComponentCatalog(candidatePath);
        if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
        if (catalogResult.error !== null) {
          setBusy(false);
          setError('Facetta could not load the authorized choices for that change. Nothing was generated or charged. Try again or mark the exact region.');
          return;
        }
        routedCatalogs.push(catalogResult.data);
      }
      const route = routeRefineInstruction({
        instruction: routedInstruction,
        exactSpecification,
        targeting,
        catalogs: routedCatalogs,
      });
      if (route.kind === 'starting_facts_required') {
        setBusy(false);
        setStartingFactsRequired(true);
        setRoutingGuidance('This request changes jewelry material or structure. Review the starting design facts first so Facetta can protect the exact geometry. Your sentence will remain here.');
        return;
      }
      if (route.kind === 'markup_required') {
        setBusy(false);
        setAnnotationPrefill(route.instruction);
        setMode('annotation');
        setRoutingGuidance(route.reason === 'localized'
          ? 'Tap the exact region you mean. Your sentence is ready as a text mark, and nothing has been generated or charged.'
          : 'This change needs an exact region so Facetta does not guess. Tap the jewelry once to place your sentence, then preview it.');
        return;
      }
      if (route.kind === 'component_choice') {
        const nextPath = route.candidatePaths[0];
        if (nextPath === undefined) {
          setBusy(false);
          setError('That controlled change is not mapped on this revision. Mark the exact region instead; Facetta will not guess.');
          return;
        }
        const nextCatalog = routedCatalogs.find(
          (candidate) => candidate.component_path === nextPath,
        ) ?? null;
        setBusy(false);
        setPath(nextPath);
        setCatalog(nextCatalog);
        setOptionId(nextCatalog?.options[0]?.id ?? null);
        setMode('component');
        setRoutingGuidance('Facetta recognized a controlled component change. Choose the exact authorized direction below; no preview has been generated or charged yet.');
        return;
      }
      if (route.kind === 'catalog') {
        routedCatalog = {
          catalog: route.catalog, option: route.option, path: route.componentPath,
        };
        routedInstruction = route.instruction;
      } else {
        routedInstruction = route.instruction;
      }
    }
    if (mode === 'component' || routedCatalog !== null) {
      if (!exactSpecification) {
        setBusy(false);
        setError('Confirm design facts before making structural component changes.');
        return;
      }
      if (routedCatalog === null && !selectedPathReady) {
        setBusy(false);
        setError('Precise targeting is not available for this component on the selected revision.');
        return;
      }
      const requestedPath = routedCatalog?.path ?? path;
      const requestedOption = routedCatalog?.option ?? selected;
      const requestedCatalog = routedCatalog?.catalog ?? catalog;
      if (requestedOption === null) { setBusy(false); return; }
      const executionMode = requestedPath === 'metal.color'
        && targeting?.jewelry_type === 'ring'
        && requestedCatalog?.component_path === requestedPath
        && requestedCatalog.preview_execution_modes.includes('instant')
        ? 'instant' as const
        : 'provider' as const;
      const result = await gateway.previewCatalogRefine({
        ...exactLineage, createdBy, componentPath: requestedPath, optionId: requestedOption.id,
        executionMode,
      });
      if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
      setBusy(false);
      if (result.error !== null) { setError(designerErrorMessage(result.error, 'refine')); return; }
      setPreview({
        candidate: result.data.candidate,
        kind: 'catalog',
        intent: {
          kind: 'component',
          componentPath: result.data.componentPath,
          optionId: result.data.optionId,
          componentLabel: PATHS.find((candidate) => candidate.id === result.data.componentPath)?.label,
          optionLabel: requestedOption.display,
          requestedChange: `${result.data.componentPath} → ${result.data.optionId}`,
        },
        executionMode: result.data.executionMode,
        estimatedCredits: result.data.estimatedCredits,
      });
      return;
    }
    let annotation: ConfirmedMarkupAnnotation = {
      region_description: 'entire visible jewelry presentation',
      change_instruction: routedInstruction,
      impact: 'visual_only' as const,
      target_section: null, target_ref: null, index: null,
      target_component_id: null,
      target_element_id: null, form_view: 'three_quarter' as const,
      mask_base64: null,
    };
    let markupAssetId: string | null = null;
    let confirmedInterpretationId: string | undefined;
    if (mode === 'annotation') {
      if (snapshot.annotations.length !== 1) {
        setBusy(false);
        setError(snapshot.annotations.length === 0
          ? 'Mark one region before reviewing the interpretation.'
          : 'Review one marked change at a time so Facetta never drops or merges your intent.');
        return;
      }
      if (pendingAnnotation === null) {
        const read = await api.readMarkup(lineage.sourceAssetId, {
          markup_snapshot: snapshot, created_by: createdBy,
        });
        if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
        if (read.error !== null) {
          setBusy(false); setError(designerErrorMessage(read.error, 'refine')); return;
        }
        if (exactLineage !== null
            && read.data.expected_design_version !== exactLineage.sourceDesignVersion) {
          setBusy(false);
          setError('The annotation was interpreted against a different revision. Reopen the design.');
          return;
        }
        const interpretation = read.data.interpretation;
        if (!exactSpecification && interpretation.impact !== 'visual_only') {
          setBusy(false);
          setError('This mark changes jewelry structure or construction. Confirm design facts before previewing it.');
          return;
        }
        if (read.data.markup_asset_id === null) {
          setBusy(false);
          setError('Facetta could not bind this mark to the exact source image. Edit the mark and try again.');
          return;
        }
        setPendingAnnotation({
          interpretationId: read.data.interpretation_id,
          markupAssetId: read.data.markup_asset_id,
          expectedDesignVersion: read.data.expected_design_version,
          interpretation,
        });
        setUnderstoodAs(interpretation.understood_as);
        setBusy(false);
        return;
      }
      if (typeof api.confirmMarkupInterpretation !== 'function') {
        setBusy(false);
        setError('Interpretation confirmation is unavailable. Nothing was generated or charged.');
        return;
      }
      const confirmed = await api.confirmMarkupInterpretation(
        lineage.sourceAssetId,
        pendingAnnotation.interpretationId,
        { created_by: createdBy },
      );
      if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
      if (confirmed.error !== null) {
        setBusy(false);
        setError(designerErrorMessage(confirmed.error, 'refine'));
        return;
      }
      if (confirmed.data.confirmed_interpretation_id !== pendingAnnotation.interpretationId
          || confirmed.data.markup_asset_id !== pendingAnnotation.markupAssetId
          || confirmed.data.expected_design_version !== pendingAnnotation.expectedDesignVersion
          || (exactLineage !== null
            && confirmed.data.expected_design_version !== exactLineage.sourceDesignVersion)) {
        setBusy(false);
        setPendingAnnotation(null);
        setUnderstoodAs(null);
        setError('The confirmed interpretation no longer matches this exact revision. Review the marks again.');
        return;
      }
      annotation = confirmed.data.annotation;
      markupAssetId = confirmed.data.markup_asset_id;
      confirmedInterpretationId = confirmed.data.confirmed_interpretation_id;
      setUnderstoodAs(pendingAnnotation.interpretation.understood_as);
    } else if (!instruction.trim()) {
      setBusy(false); return;
    }
    const result = exactLineage !== null
      ? await gateway.previewMarkupRefine({
          ...exactLineage, createdBy, annotation, markupAssetId, confirmedInterpretationId,
        })
      : await gateway.previewVisualRefine(mode === 'annotation'
        ? {
            ...lineage,
            createdBy,
            instruction: annotation.change_instruction,
            scope: 'marked_region',
            markupAssetId: markupAssetId ?? '',
            confirmedInterpretationId: confirmedInterpretationId ?? '',
          }
        : {
            ...lineage,
            createdBy,
            instruction: annotation.change_instruction,
            scope: 'appearance',
          });
    if (!lineageRequestIsCurrent(requestedLineageKey, requestedLineageEpoch)) return;
    setBusy(false);
    if (result.error !== null) { setError(designerErrorMessage(result.error, 'refine')); return; }
    setPreview({
      candidate: result.data.candidate,
      kind: exactLineage !== null ? 'markup' : 'visual',
      intent: mode === 'annotation'
        ? {
            kind: 'markup',
            requestedChange: annotation.change_instruction,
            regionDescription: annotation.region_description,
            impact: annotation.impact,
          }
        : {
            kind: 'describe',
            instruction: annotation.change_instruction,
            scope: 'appearance',
          },
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

  if (workspaceMode === 'refine' && preview !== null) {
    const rejected = preview.candidate.verdict === 'reject';
    const intentCopy = refineIntentCopy(preview.intent);
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
              : `Standard preview · estimated ${preview.estimatedCredits ?? refineCreditsPerOutput} credits if you Apply or Save as Variation`}
          />
        )}
        {understoodAs !== null && <Notice kind="info" text={understoodAs} />}
        <View accessibilityRole="summary" style={styles.intentCard}>
          <Text style={styles.intentEyebrow}>REQUESTED CHANGE</Text>
          <Text style={styles.intentSummary}>{intentCopy.summary}</Text>
          {intentCopy.detail !== null && (
            <Text style={styles.intentDetail}>{intentCopy.detail}</Text>
          )}
          <Text style={styles.intentBoundary}>{intentCopy.boundary}</Text>
        </View>
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

  if (workspaceMode === 'refine' && acceptedOutcome !== null) {
    return (
      <ScrollView contentContainerStyle={styles.workspace}>
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
              title="Refine another change"
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
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
      <Text style={styles.eyebrow}>{workspaceMode === 'specifications'
        ? 'SPECIFICATIONS' : 'REFINE'}</Text>
      <Text style={styles.title}>{workspaceMode === 'specifications'
        ? 'Correct the recorded facts for this revision.'
        : 'Change one thing. Keep the rest.'}</Text>
      <Text style={styles.body}>{workspaceMode === 'specifications'
        ? 'Review only the facts that need correction. Saving appends an immutable specification revision without changing image pixels.'
        : 'Describe one change. Facetta routes it to the safest precise tool, then creates a temporary candidate before anything enters design history.'}</Text>

      {!reviewSourceIsActive && <Notice kind="info" text="This Activity result was created from an earlier revision. Review the existing preview below; creating or applying another change from this source is unavailable." />}

      {workspaceMode === 'refine' && resuming && <Notice kind="info" text="Checking for a pending preview from this exact revision…" />}

      {workspaceMode === 'refine' && <>
        <View>
          <Field
            label={refineInstructionLabel}
            value={instruction}
            onChange={(next) => {
              setInstruction(next);
              setMode('instruction');
              setPendingAnnotation(null);
              setUnderstoodAs(null);
              setRoutingGuidance(null);
              setStartingFactsRequired(false);
              setError(null);
            }}
            multiline
            placeholder="Make the presentation softer, use rose gold, or widen the band…"
          />
        </View>
        <Text style={styles.advancedDisclosureTitle}>Target it more precisely</Text>
        <View style={styles.modeRow}>
        {([
          ['component', 'Choose component', 'Use a controlled material or construction option.'],
          ['annotation', 'Mark exact region', 'Draw directly on the exact active image.'],
        ] as const).filter(([id]) => id !== 'component' || componentAvailable)
          .map(([id, label, detail]) => (
            <Pressable
              key={id}
              accessibilityLabel={id === 'component'
                ? 'Component refine mode' : 'Mark up refine mode'}
              accessibilityRole="button"
              accessibilityState={{ selected: mode === id }}
              onPress={() => {
                const switchingMode = mode !== id;
                setMode(id);
                if (switchingMode) {
                  setPendingAnnotation(null);
                  setUnderstoodAs(null);
                }
                if (id === 'annotation') setAnnotationPrefill(instruction);
                setFactReview(null);
                setRoutingGuidance(null);
                setStartingFactsRequired(false);
                setError(null);
              }}
              style={[styles.modeCard, mode === id && styles.selectedCard]}>
              <Text style={styles.pathTitle}>{label}</Text>
              <Text style={styles.pathHelp}>{detail}</Text>
            </Pressable>
          ))}
        </View>
      </>}

      {workspaceMode === 'refine' && routingGuidance !== null && (
        <Notice kind="info" text={routingGuidance} />
      )}

      {workspaceMode === 'refine'
        && startingFactsRequired
        && !exactSpecification && onReviewStartingDesign !== undefined && (
        <View style={styles.startingFactsCard}>
          <View style={styles.startingFactsCopy}>
            <Text style={styles.advancedDisclosureTitle}>Unlock precise ring edits</Text>
            <Text style={styles.pathHelp}>For a ring direction, review the image-derived starting facts before changing components or construction. Estimates stay clearly separate from facts you confirm. Technical views become available after those facts are recorded; you can keep refining or presenting without them.</Text>
          </View>
          <Button title="Review starting design" kind="ghost" onPress={() => onReviewStartingDesign(instruction)} />
        </View>
      )}

      {workspaceMode === 'refine'
        && targetingError !== null && <Notice kind="error" text={targetingError} />}
      {workspaceMode === 'refine'
        && exactSpecification && !targetingLoading && targetingError === null
        && readyPaths.length === 0 && (
        <Notice kind="info" text="This revision has no precisely mapped component regions yet. Describe an appearance change or use Mark up; Facetta will not guess component geometry." />
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
                  ? 'This design is not ready for that precise component change yet. Use Describe or Mark up so Facetta can keep the rest unchanged.'
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

      {workspaceMode === 'refine' && mode === 'instruction' && (
        <Notice kind="info" text="Facetta routes material and structural requests to controlled tools before generation. Only presentation changes proceed directly." />
      )}

      {workspaceMode === 'refine' && mode === 'annotation' && (sourceImageUrl === null ? (
        <Notice kind="error" text="The exact active image is unavailable for annotation. Reopen the design or use Describe." />
      ) : pendingAnnotation === null ? <>
        <AnnotationCanvas
          key={`refine-annotation:${lineageKey}:${annotationPrefill}`}
          sourceUri={sourceImageUrl}
          value={snapshot}
          onChange={(next) => {
            setSnapshot(next);
            setPendingAnnotation(null);
            setUnderstoodAs(null);
            setError(null);
          }}
          drawingEnabled
          initialTool={annotationPrefill.length > 0 ? 'text' : 'rectangle'}
          initialTextDraft={annotationPrefill}
        />
        <Text style={styles.pathHelp}>Mark one region and describe one change. Facetta will show what it understood before any preview is generated.</Text>
      </> : <View accessibilityRole="summary" style={styles.factReviewCard}>
        <Text style={styles.reviewTitle}>Confirm Facetta’s understanding</Text>
        <Text style={styles.pathHelp}>Reviewing this interpretation generated no image and used 0 credits.</Text>
        <View style={styles.factReviewRow}>
          <Text style={styles.factReviewLabel}>Change</Text>
          <Text style={styles.factReviewValue}>{pendingAnnotation.interpretation.requested_change}</Text>
        </View>
        <View style={styles.factReviewRow}>
          <Text style={styles.factReviewLabel}>Target</Text>
          <Text style={styles.factReviewValue}>{pendingAnnotation.interpretation.target_region}</Text>
        </View>
        <View style={styles.factReviewRow}>
          <Text style={styles.factReviewLabel}>Impact</Text>
          <Text style={styles.factReviewValue}>{pendingAnnotation.interpretation.impact === 'visual_only'
            ? 'Presentation only'
            : 'Image + design facts'}</Text>
        </View>
        <View style={styles.factReviewRow}>
          <Text style={styles.factReviewLabel}>Kept unchanged</Text>
          <Text style={styles.factReviewValue}>{pendingAnnotation.interpretation.frozen_elements.length > 0
            ? pendingAnnotation.interpretation.frozen_elements.join(', ')
            : 'Everything outside the marked region'}</Text>
        </View>
        <View style={styles.actions}>
          <Button
            title="Edit marks"
            kind="ghost"
            disabled={busy}
            onPress={() => {
              setPendingAnnotation(null);
              setUnderstoodAs(null);
              setError(null);
            }}
          />
        </View>
      </View>)}
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
        : mode === 'annotation' && pendingAnnotation === null
          ? `Interpretation review · 0 credits. Preview estimated ${refineCreditsPerOutput} credits after confirmation.`
        : mode === 'component' && catalogPreviewMode === 'instant'
          ? 'Quick preview · 0 credits'
          : `1 requested output × ${refineCreditsPerOutput} credits = estimated ${refineControls.estimateCredits(1)} credits`}</Text>
      {workspaceMode === 'refine' ? (
        <Button title={mode === 'annotation'
          ? pendingAnnotation === null
            ? busy ? 'Reading marks…' : 'Review interpretation · 0 credits'
            : busy ? 'Creating preview…' : `Confirm & create preview · ${refineCreditsPerOutput} credits`
          : busy ? 'Creating preview…' : 'Preview change'} disabled={busy || !reviewSourceIsActive
          || (mode === 'component' && (selected === null || !selectedPathReady))
          || (mode === 'instruction' && !instruction.trim())
          || (mode === 'annotation' && (sourceImageUrl === null || snapshot.annotations.length === 0))}
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
  empty: { padding: 28, alignItems: 'center', gap: 8 },
  eyebrow: { color: theme.accent, fontSize: 11, fontWeight: '800', letterSpacing: 2 },
  title: { color: theme.ink, fontFamily: theme.serif, fontSize: 28, lineHeight: 34 },
  body: { color: theme.faint, fontSize: 14, lineHeight: 21, maxWidth: 680 },
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
  creditEstimate: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 6 },
  compareRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  comparePane: { flexGrow: 1, flexBasis: 280, gap: 6 },
  compareLabel: { color: theme.faint, fontSize: 10, fontWeight: '800', letterSpacing: 1.2 },
  preview: { width: '100%', aspectRatio: 1.25, borderRadius: radius.lg, backgroundColor: theme.line },
  reviewCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 14, backgroundColor: theme.card, gap: 8 },
  intentCard: {
    borderWidth: 1, borderColor: theme.accent, borderRadius: radius.md,
    padding: 14, backgroundColor: theme.card, gap: 5,
  },
  intentEyebrow: { color: theme.accent, fontSize: 10, fontWeight: '800', letterSpacing: 1.3 },
  intentSummary: { color: theme.ink, fontSize: 17, fontWeight: '800', lineHeight: 23 },
  intentDetail: { color: theme.ink, fontSize: 12, lineHeight: 18 },
  intentBoundary: { color: theme.faint, fontSize: 12, lineHeight: 18 },
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
