import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View,
} from 'react-native';

import { Button, ChipRow, Field, Notice } from '../components';
import { radius, theme } from '../theme';
import type {
  ComponentCatalog, ComponentCatalogOption, ComponentCatalogPath,
  ConfirmedMarkupAnnotation, JsonObject, JsonValue, ProjectDetail, StudioComponentTargeting,
  StudioFactPath,
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
    'getProject' | 'prepareStudioComponentMap' | 'reviseStudioFacts'>>;

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
  initialAdvancedFactsOpen?: boolean;
  onReviewStartingDesign?: () => void;
  onApplied: (project: ProjectDetail) => void;
  onVariationCreated?: (project: ProjectDetail) => void;
  imageRequestHeaders?: Readonly<Record<string, string>>;
  resumeReviewJobId?: string;
  reviewSourceIsActive?: boolean;
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
  { path: 'metal.color', label: 'Metal color', kind: 'choice', group: 'identity', choices: ['yellow', 'rose', 'white'] },
  { path: 'metal.finish', label: 'Metal finish', kind: 'choice', group: 'identity', choices: ['polished', 'satin', 'brushed', 'matte'] },
  { path: 'metal.karat', label: 'Gold karat', kind: 'integer', group: 'identity' },
  { path: 'stone.species', label: 'Stone species', kind: 'text', group: 'stone' },
  { path: 'stone.cut', label: 'Stone cut', kind: 'text', group: 'stone' },
  { path: 'stone.color.trade', label: 'Stone trade color', kind: 'text', group: 'stone' },
  { path: 'stone.color.gia', label: 'Stone graded color', kind: 'text', group: 'stone' },
  { path: 'stone.carat', label: 'Stone weight', kind: 'number', group: 'stone', unit: 'ct' },
  { path: 'stone.dimensions_mm.length', label: 'Stone length', kind: 'number', group: 'dimensions', unit: 'mm' },
  { path: 'stone.dimensions_mm.width', label: 'Stone width', kind: 'number', group: 'dimensions', unit: 'mm' },
  { path: 'stone.dimensions_mm.depth', label: 'Stone depth', kind: 'number', group: 'dimensions', unit: 'mm' },
  { path: 'setting.style', label: 'Setting style', kind: 'choice', group: 'setting', choices: ['prong', 'bezel', 'halo', 'pave', 'channel'] },
  { path: 'setting.prong_count', label: 'Prong count', kind: 'integer', group: 'setting' },
  { path: 'band.profile', label: 'Band profile', kind: 'choice', group: 'construction', choices: ['half_round', 'flat', 'knife_edge', 'comfort_fit'] },
  { path: 'band.width_mm', label: 'Band width', kind: 'number', group: 'dimensions', unit: 'mm' },
  { path: 'band.thickness_mm', label: 'Band thickness', kind: 'number', group: 'dimensions', unit: 'mm' },
  { path: 'ring_size.system', label: 'Ring size system', kind: 'choice', group: 'identity', choices: ['US', 'UK', 'EU', 'JP', 'HK'] },
  { path: 'ring_size.value', label: 'Ring size', kind: 'text', group: 'identity' },
] as const;

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

export function StudioRefineWorkspace({
  api, gateway, lineage, createdBy, sourceImageUrl = null, initialAdvancedFactsOpen = false,
  onReviewStartingDesign, onApplied, onVariationCreated,
  imageRequestHeaders, resumeReviewJobId, reviewSourceIsActive = true,
}: StudioRefineWorkspaceProps) {
  const exactLineage = hasExactSpecification(lineage) ? lineage : null;
  const exactSpecification = exactLineage !== null;
  const [mode, setMode] = useState<'component' | 'instruction' | 'annotation' | 'facts'>(
    exactSpecification && initialAdvancedFactsOpen ? 'facts' : 'instruction',
  );
  const [path, setPath] = useState<ComponentCatalogPath>('metal.color');
  const [catalog, setCatalog] = useState<ComponentCatalog | null>(null);
  const [targeting, setTargeting] = useState<StudioComponentTargeting | null>(null);
  const [targetingLoading, setTargetingLoading] = useState(exactSpecification);
  const [targetingError, setTargetingError] = useState<string | null>(null);
  const [optionId, setOptionId] = useState<string | null>(null);
  const [preview, setPreview] = useState<{
    candidate: PreviewCandidate;
    kind: 'catalog' | 'markup' | 'visual';
    executionMode?: 'instant' | 'provider';
    estimatedCredits?: number;
  } | null>(null);
  const [instruction, setInstruction] = useState('');
  const [understoodAs, setUnderstoodAs] = useState<string | null>(null);
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
  const [factProject, setFactProject] = useState<ProjectDetail | null>(null);
  const [factDraft, setFactDraft] = useState<Partial<Record<StudioFactPath, string>>>({});
  const [factsLoading, setFactsLoading] = useState(false);
  const [advancedFactsOpen, setAdvancedFactsOpen] = useState(
    exactSpecification && initialAdvancedFactsOpen,
  );
  const [activeFactGroup, setActiveFactGroup] = useState<FactGroupId>('identity');
  const [factReview, setFactReview] = useState<readonly FactChangeReview[] | null>(null);
  const decisionInFlight = useRef(false);
  const annotationSourceAssetId = useRef<string | null>(lineage?.sourceAssetId ?? null);
  const visualReviewScope = `${lineage?.sourceAssetId ?? 'none'}:${sourceImageUrl ?? 'missing'}:${preview?.candidate.id ?? 'no-preview'}:${preview?.candidate.assetUrl ?? 'missing'}`;
  const visualReview = useVisualReviewReadiness(visualReviewScope);
  const sourceVisualKey = sourceImageUrl === null || sourceImageUrl === undefined
    ? null : `refine-source:${lineage?.sourceAssetId ?? 'none'}:${sourceImageUrl}`;
  const candidateVisualKey = preview === null
    ? null : `refine-candidate:${preview.candidate.id}:${preview.candidate.assetUrl}`;
  const comparisonVisualKeys = [sourceVisualKey, candidateVisualKey] as const;
  const comparisonReady = visualReview.allReady(comparisonVisualKeys);
  const exactStoneSpecies = useMemo(() => {
    const spec = factProject?.spec;
    if (spec === null || spec === undefined) return null;
    const species = factValue(spec, 'stone.species');
    if (typeof species !== 'string' || species.trim().length === 0) return null;
    return species.trim();
  }, [factProject]);

  useEffect(() => {
    let current = true;
    setTargeting(null);
    setTargetingError(null);
    if (exactLineage === null) {
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
  }, [api, exactSpecification, lineage?.sourceAssetId]);

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
    if (lineage === null || typeof gateway.resumeRefine !== 'function') {
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
    exactLineage?.sourceDesignVersion, resumeReviewJobId]);

  useEffect(() => {
    const nextSourceAssetId = lineage?.sourceAssetId ?? null;
    const sourceRevisionChanged = annotationSourceAssetId.current !== nextSourceAssetId;
    annotationSourceAssetId.current = nextSourceAssetId;
    setSnapshot((current) => ({
      ...current,
      source_uri: sourceImageUrl ?? '',
      annotations: sourceRevisionChanged ? [] : current.annotations,
    }));
  }, [lineage?.sourceAssetId, sourceImageUrl]);

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
      && factValue(spec, definition.path) !== null);
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
      if (raw.length === 0) return { changes: [], error: `${definition.label} cannot be empty.` };
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
    if (mode === 'facts') { reviewFacts(); return; }
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
      setBusy(false);
      if (result.error !== null) { setError(designerErrorMessage(result.error, 'refine')); return; }
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
        setBusy(false); setError('Mark one region before creating a preview.'); return;
      }
      const read = await api.readMarkup(lineage.sourceAssetId, {
        markup_snapshot: snapshot, created_by: createdBy,
      });
      if (read.error !== null) { setBusy(false); setError(designerErrorMessage(read.error, 'refine')); return; }
      if (exactLineage !== null
          && read.data.expected_design_version !== exactLineage.sourceDesignVersion) {
        setBusy(false); setError('The annotation was interpreted against a different revision. Reopen the design.'); return;
      }
      const interpretation = read.data.interpretation;
      if (!exactSpecification && interpretation.impact !== 'visual_only') {
        setBusy(false);
        setError('This mark changes jewelry structure or construction. Confirm design facts before previewing it.');
        return;
      }
      annotation = {
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
      };
      markupAssetId = read.data.markup_asset_id;
      setUnderstoodAs(interpretation.understood_as);
    } else if (!instruction.trim()) {
      setBusy(false); return;
    }
    const result = exactLineage !== null
      ? await gateway.previewMarkupRefine({
          ...exactLineage, createdBy, annotation, markupAssetId,
        })
      : await gateway.previewVisualRefine(mode === 'annotation'
        ? {
            ...lineage,
            createdBy,
            instruction: annotation.change_instruction,
            scope: 'marked_region',
            markupAssetId: markupAssetId ?? '',
          }
        : {
            ...lineage,
            createdBy,
            instruction: annotation.change_instruction,
            scope: 'appearance',
          });
    setBusy(false);
    if (result.error !== null) { setError(designerErrorMessage(result.error, 'refine')); return; }
    setPreview({
      candidate: result.data.candidate,
      kind: exactLineage !== null ? 'markup' : 'visual',
    });
  };

  const apply = async (): Promise<void> => {
    if (preview === null || busy || decisionInFlight.current
      || preview.candidate.verdict === 'reject' || !reviewSourceIsActive
      || !comparisonReady) return;
    decisionInFlight.current = true;
    setBusy(true);
    setError(null);
    const result = preview.kind === 'catalog'
      ? await gateway.applyCatalogRefine({ candidateId: preview.candidate.id, createdBy })
      : preview.kind === 'markup'
        ? await gateway.applyMarkupRefine({ candidateId: preview.candidate.id, createdBy })
        : await gateway.applyVisualRefine({ candidateId: preview.candidate.id, createdBy });
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
    setPreview(null);
    onApplied(result.data.project);
  };

  const discard = async (): Promise<void> => {
    if (preview === null || busy || decisionInFlight.current) return;
    decisionInFlight.current = true;
    setBusy(true);
    setError(null);
    const result = preview.kind === 'catalog'
      ? await gateway.discardCatalogRefine({ candidateId: preview.candidate.id, createdBy })
      : preview.kind === 'markup'
        ? await gateway.discardMarkupRefine({ candidateId: preview.candidate.id, createdBy })
        : await gateway.discardVisualRefine({ candidateId: preview.candidate.id, createdBy });
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
    setBusy(false);
    decisionInFlight.current = false;
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'refine'));
      return;
    }
    setPreview(null);
    setNamingVariation(false);
    setVariationName('');
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

  if (preview !== null) {
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
      <Text style={styles.eyebrow}>REFINE</Text>
      <Text style={styles.title}>Change one thing. Keep the rest.</Text>
      <Text style={styles.body}>Choose how to target one change. Every change creates a temporary candidate before anything enters design history.</Text>

      {!reviewSourceIsActive && <Notice kind="info" text="This Activity result was created from an earlier revision. Review the existing preview below; creating or applying another change from this source is unavailable." />}

      {resuming && <Notice kind="info" text="Checking for a pending preview from this exact revision…" />}

      <View style={styles.modeRow}>
        {([
          ['component', 'Component', 'Choose a controlled material or construction option.'],
          ['instruction', 'Describe', 'Describe an appearance-only change in plain language.'],
          ['annotation', 'Mark up', 'Draw directly on the exact active image.'],
        ] as const).filter(([id]) => id !== 'component' || componentAvailable)
          .map(([id, label, detail]) => (
            <Pressable
              key={id}
              accessibilityLabel={`${label} refine mode`}
              accessibilityRole="button"
              accessibilityState={{ selected: mode === id }}
              onPress={() => {
                setMode(id);
                setAdvancedFactsOpen(false);
                setFactReview(null);
                setError(null);
              }}
              style={[styles.modeCard, mode === id && styles.selectedCard]}>
              <Text style={styles.pathTitle}>{label}</Text>
              <Text style={styles.pathHelp}>{detail}</Text>
            </Pressable>
          ))}
      </View>

      {exactSpecification && typeof api.reviseStudioFacts === 'function' && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Advanced design facts"
          accessibilityState={{ expanded: advancedFactsOpen }}
          onPress={() => {
            const opening = !advancedFactsOpen;
            setAdvancedFactsOpen(opening);
            setMode(opening ? 'facts' : 'instruction');
            setFactReview(null);
            setError(null);
          }}
          style={[styles.advancedDisclosure, advancedFactsOpen && styles.advancedDisclosureOpen]}>
          <View style={styles.advancedDisclosureCopy}>
            <Text style={styles.advancedDisclosureTitle}>Advanced design facts</Text>
            <Text style={styles.pathHelp}>Correct recorded specifications without changing image pixels.</Text>
          </View>
          <Text style={styles.disclosureGlyph}>{advancedFactsOpen ? '−' : '+'}</Text>
        </Pressable>
      )}

      {!exactSpecification && onReviewStartingDesign !== undefined && (
        <View style={styles.startingFactsCard}>
          <View style={styles.startingFactsCopy}>
            <Text style={styles.advancedDisclosureTitle}>Unlock precise ring edits</Text>
            <Text style={styles.pathHelp}>For a ring direction, review the image-derived starting facts before changing components or construction. Estimates stay clearly separate from facts you confirm. Technical views become available after those facts are recorded; you can keep refining or presenting without them.</Text>
          </View>
          <Button title="Review starting design" kind="ghost" onPress={onReviewStartingDesign} />
        </View>
      )}

      {targetingError !== null && <Notice kind="error" text={targetingError} />}
      {exactSpecification && !targetingLoading && targetingError === null
        && readyPaths.length === 0 && (
        <Notice kind="info" text="This revision has no precisely mapped component regions yet. Describe an appearance change or use Mark up; Facetta will not guess component geometry." />
      )}

      {mode === 'component' && <>
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

      {mode === 'instruction' && <>
        <Field label="Appearance change" value={instruction} onChange={setInstruction} multiline
          placeholder="Make the presentation softer and more luminous while keeping every jewelry detail fixed…" />
        <Notice kind="info" text={exactSpecification
          ? 'Plain-language mode changes presentation only. Use Component or Mark up for structure, stones, settings, or materials.'
          : 'Plain-language mode changes appearance only. Structural, stone, setting, and construction changes stay locked until design facts are confirmed.'} />
      </>}

      {mode === 'annotation' && (sourceImageUrl === null ? (
        <Notice kind="error" text="The exact active image is unavailable for annotation. Reopen the design or use Describe." />
      ) : <>
        <AnnotationCanvas sourceUri={sourceImageUrl} value={snapshot} onChange={setSnapshot} drawingEnabled />
        <Text style={styles.pathHelp}>Mark one region and add text or an arrow describing one change. Facetta will show its interpretation before Apply.</Text>
      </>)}
      {mode === 'facts' && <>
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
                const options = definition.choices?.includes(value)
                  ? definition.choices
                  : [value, ...(definition.choices ?? [])].filter(Boolean);
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
      <Text style={styles.creditEstimate}>{mode === 'facts'
        ? '0 credits · specification revision only'
        : mode === 'component' && catalogPreviewMode === 'instant'
          ? 'Quick preview · 0 credits'
          : `1 requested output × ${REFINE_CREDITS_PER_OUTPUT} credits = estimated ${REFINE_CREDITS_PER_OUTPUT} credits`}</Text>
      {mode !== 'facts' ? (
        <Button title={busy ? 'Creating preview…' : 'Preview change'} disabled={busy || !reviewSourceIsActive
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
  advancedDisclosure: {
    borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 13,
    backgroundColor: theme.paper, flexDirection: 'row', alignItems: 'center', gap: 12,
  },
  advancedDisclosureOpen: { borderColor: theme.accent, backgroundColor: theme.card },
  advancedDisclosureCopy: { flex: 1 },
  advancedDisclosureTitle: { color: theme.ink, fontWeight: '700', fontSize: 14, marginBottom: 3 },
  startingFactsCard: {
    borderWidth: 1, borderColor: theme.accent, borderRadius: radius.md, padding: 13,
    backgroundColor: theme.card, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 12,
  },
  startingFactsCopy: { flexGrow: 1, flexShrink: 1, flexBasis: 360 },
  disclosureGlyph: { color: theme.accent, fontSize: 22, fontWeight: '500' },
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
