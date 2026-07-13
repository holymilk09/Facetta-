import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View,
} from 'react-native';
import { AuthenticatedImage as Image } from '../AuthenticatedImage';

import { Button, ChipRow, Field, Notice } from '../components';
import { radius, theme } from '../theme';
import type {
  ComponentCatalog, ComponentCatalogOption, ComponentCatalogPath,
  ConfirmedMarkupAnnotation, JsonObject, JsonValue, ProjectDetail, StudioFactPath,
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

const REFINE_CREDITS_PER_OUTPUT = getStudioAction('refine').creditEstimate ?? 0;

const PATHS: readonly { id: ComponentCatalogPath; label: string; help: string }[] = [
  { id: 'metal.color', label: 'Metal color', help: 'Change only the visible metal color.' },
  { id: 'metal.material', label: 'Metal material', help: 'Explore a different material while preserving form.' },
  { id: 'stone.color', label: 'Stone color', help: 'Change the selected stone color only.' },
  { id: 'stone.cut', label: 'Stone cut', help: 'Preview a controlled cut change.' },
  { id: 'setting.style', label: 'Setting', help: 'Preview a supported setting construction.' },
  { id: 'chain.style', label: 'Chain', help: 'Preview a supported chain direction.' },
] as const;

export type StudioRefineApi = Pick<StudioGateway, 'getComponentCatalog' | 'readMarkup'>
  & Partial<Pick<StudioGateway, 'getProject' | 'reviseStudioFacts'>>;

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
  onApplied: (project: ProjectDetail) => void;
  onVariationCreated?: (project: ProjectDetail) => void;
  imageRequestHeaders?: Readonly<Record<string, string>>;
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
  onApplied, onVariationCreated,
  imageRequestHeaders,
}: StudioRefineWorkspaceProps) {
  const exactLineage = hasExactSpecification(lineage) ? lineage : null;
  const exactSpecification = exactLineage !== null;
  const [mode, setMode] = useState<'component' | 'instruction' | 'annotation' | 'facts'>(
    exactSpecification && initialAdvancedFactsOpen ? 'facts'
      : exactSpecification ? 'component' : 'instruction',
  );
  const [path, setPath] = useState<ComponentCatalogPath>('metal.color');
  const [catalog, setCatalog] = useState<ComponentCatalog | null>(null);
  const [optionId, setOptionId] = useState<string | null>(null);
  const [preview, setPreview] = useState<{
    candidate: PreviewCandidate;
    kind: 'catalog' | 'markup' | 'visual';
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
  const [sourceReady, setSourceReady] = useState(false);
  const decisionInFlight = useRef(false);

  useEffect(() => {
    setSourceReady(false);
  }, [sourceImageUrl, lineage?.sourceAssetId]);

  useEffect(() => {
    let current = true;
    if (!exactSpecification) {
      setLoading(false);
      setCatalog(null);
      setOptionId(null);
      return () => { current = false; };
    }
    setLoading(true);
    setCatalog(null);
    setOptionId(null);
    setPreview(null);
    setError(null);
    void api.getComponentCatalog(path).then((result) => {
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
  }, [api, exactSpecification, path, lineage?.sourceAssetId]);

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
    void gateway.resumeRefine(lineage, createdBy).then((result) => {
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
    exactLineage?.sourceDesignVersion]);

  useEffect(() => {
    setSnapshot((current) => ({ ...current, source_uri: sourceImageUrl ?? '' }));
  }, [sourceImageUrl]);

  const selected = useMemo(() => catalog?.options.find((option) => option.id === optionId) ?? null,
    [catalog, optionId]);
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
    if (lineage === null || busy) return;
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
      if (selected === null) { setBusy(false); return; }
      const result = await gateway.previewCatalogRefine({
        ...exactLineage, createdBy, componentPath: path, optionId: selected.id,
      });
      setBusy(false);
      if (result.error !== null) { setError(designerErrorMessage(result.error, 'refine')); return; }
      setPreview({ candidate: result.data.candidate, kind: 'catalog' });
      return;
    }
    let annotation: ConfirmedMarkupAnnotation = {
      region_description: 'entire visible jewelry presentation',
      change_instruction: instruction.trim(),
      impact: 'visual_only' as const,
      target_section: null, target_ref: null, index: null,
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
    if (preview === null || busy || decisionInFlight.current || preview.candidate.verdict === 'reject') return;
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
    if (preview === null || busy || decisionInFlight.current) return;
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
        {understoodAs !== null && <Notice kind="info" text={understoodAs} />}
        <View style={styles.compareRow}>
          {sourceImageUrl !== null && (
            <View style={styles.comparePane}>
              <Text style={styles.compareLabel}>SOURCE</Text>
              <Image
                accessibilityLabel="Exact source revision"
                source={{ uri: sourceImageUrl }}
                imageRequestHeaders={imageRequestHeaders}
                onLoad={() => setSourceReady(true)}
                onError={() => setSourceReady(false)}
                style={styles.preview}
              />
            </View>
          )}
          <View style={styles.comparePane}>
            <Text style={styles.compareLabel}>PREVIEW</Text>
            <Image accessibilityLabel="Temporary refinement preview" source={{ uri: preview.candidate.assetUrl }} imageRequestHeaders={imageRequestHeaders} style={styles.preview} />
          </View>
        </View>
        {!sourceReady && (
          <Notice
            kind="error"
            text={sourceImageUrl === null
              ? 'The exact source revision is unavailable. Reopen the design before accepting this preview.'
              : 'Wait for the exact source revision to load before accepting this preview.'}
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
                disabled={busy || variationName.trim().length === 0 || rejected || !sourceReady}
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
              disabled={busy || rejected || !sourceReady}
              onPress={() => { setNamingVariation(true); setError(null); }}
            />
          )}
          <Button title={busy ? 'Working…' : 'Apply as new revision'} disabled={busy || rejected || !sourceReady} onPress={() => { void apply(); }} />
        </View>
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
      <Text style={styles.eyebrow}>REFINE</Text>
      <Text style={styles.title}>Change one thing. Keep the rest.</Text>
      <Text style={styles.body}>Choose how to target one change. Every route creates a temporary candidate before anything enters design history.</Text>

      {resuming && <Notice kind="info" text="Checking for a pending preview from this exact revision…" />}

      <View style={styles.modeRow}>
        {([
          ['component', 'Component', 'Choose a controlled material or construction option.'],
          ['instruction', 'Describe', 'Describe an appearance-only change in plain language.'],
          ['annotation', 'Mark up', 'Draw directly on the exact active image.'],
        ] as const).map(([id, label, detail]) => {
          const unavailable = id === 'component' && !exactSpecification;
          return (
            <Pressable
              key={id}
              accessibilityLabel={`${label} refine mode`}
              accessibilityRole="button"
              accessibilityState={{ disabled: unavailable, selected: mode === id }}
              disabled={unavailable}
              onPress={() => {
                setMode(id);
                setAdvancedFactsOpen(false);
                setFactReview(null);
                setError(null);
              }}
              style={[styles.modeCard, mode === id && styles.selectedCard, unavailable && styles.disabledCard]}>
              <Text style={styles.pathTitle}>{label}</Text>
              <Text style={styles.pathHelp}>{unavailable
                ? 'Confirm design facts before making structural component changes.'
                : detail}</Text>
            </Pressable>
          );
        })}
      </View>

      {exactSpecification && typeof api.reviseStudioFacts === 'function' && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Advanced design facts"
          accessibilityState={{ expanded: advancedFactsOpen }}
          onPress={() => {
            const opening = !advancedFactsOpen;
            setAdvancedFactsOpen(opening);
            setMode(opening ? 'facts' : 'component');
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

      {!exactSpecification && (
        <Notice kind="info" text="Design facts are not confirmed yet. You can refine appearance or a marked region; component and construction changes unlock after those facts are reviewed." />
      )}

      {mode === 'component' && <>
        <Text style={styles.sectionTitle}>1 · Component</Text>
        <View style={styles.pathGrid}>
          {PATHS.map((item) => (
            <Pressable key={item.id} onPress={() => setPath(item.id)} style={[styles.pathCard, path === item.id && styles.selectedCard]}>
              <Text style={styles.pathTitle}>{item.label}</Text>
              <Text style={styles.pathHelp}>{item.help}</Text>
            </Pressable>
          ))}
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
        : `1 requested output × ${REFINE_CREDITS_PER_OUTPUT} credits = estimated ${REFINE_CREDITS_PER_OUTPUT} credits`}</Text>
      {mode !== 'facts' ? (
        <Button title={busy ? 'Creating preview…' : 'Preview change'} disabled={busy
          || (mode === 'component' && selected === null)
          || (mode === 'instruction' && !instruction.trim())
          || (mode === 'annotation' && (sourceImageUrl === null || snapshot.annotations.length === 0))}
          onPress={() => { void makePreview(); }} />
      ) : factReview === null && (
        <Button title="Review fact changes" disabled={busy || factsLoading || editableFacts.length === 0}
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
