import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View,
} from 'react-native';
import { AuthenticatedImage as Image } from '../AuthenticatedImage';

import { Button, Field, Notice } from '../components';
import { radius, theme } from '../theme';
import type { TrustedApiClient } from '../trusted/client';
import type {
  ComponentCatalog, ComponentCatalogOption, ComponentCatalogPath,
  ConfirmedMarkupAnnotation, ProjectDetail,
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

const PATHS: readonly { id: ComponentCatalogPath; label: string; help: string }[] = [
  { id: 'metal.color', label: 'Metal color', help: 'Change only the visible metal color.' },
  { id: 'metal.material', label: 'Metal material', help: 'Explore a different material while preserving form.' },
  { id: 'stone.color', label: 'Stone color', help: 'Change the selected stone color only.' },
  { id: 'stone.cut', label: 'Stone cut', help: 'Preview a controlled cut change.' },
  { id: 'setting.style', label: 'Setting', help: 'Preview a supported setting construction.' },
  { id: 'chain.style', label: 'Chain', help: 'Preview a supported chain direction.' },
] as const;

export type StudioRefineApi = Pick<TrustedApiClient, 'getComponentCatalog' | 'readMarkup'>;

export interface StudioRefineWorkspaceProps {
  api: StudioRefineApi;
  gateway: Pick<StudioGateway,
    | 'previewCatalogRefine' | 'applyCatalogRefine' | 'discardCatalogRefine'
    | 'previewMarkupRefine' | 'applyMarkupRefine' | 'discardMarkupRefine'
    | 'previewVisualRefine' | 'applyVisualRefine' | 'discardVisualRefine'>;
  lineage: ExactStudioLineage | StudioVisualLineage | null;
  createdBy: string;
  sourceImageUrl?: string | null;
  onApplied: (project: ProjectDetail) => void;
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

export function StudioRefineWorkspace({
  api, gateway, lineage, createdBy, sourceImageUrl = null, onApplied, imageRequestHeaders,
}: StudioRefineWorkspaceProps) {
  const exactLineage = hasExactSpecification(lineage) ? lineage : null;
  const exactSpecification = exactLineage !== null;
  const [mode, setMode] = useState<'component' | 'instruction' | 'annotation'>(
    exactSpecification ? 'component' : 'instruction',
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    setSnapshot((current) => ({ ...current, source_uri: sourceImageUrl ?? '' }));
  }, [sourceImageUrl]);

  const selected = useMemo(() => catalog?.options.find((option) => option.id === optionId) ?? null,
    [catalog, optionId]);

  const makePreview = async (): Promise<void> => {
    if (lineage === null || busy) return;
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
    if (preview === null || busy || preview.candidate.verdict === 'reject') return;
    setBusy(true);
    setError(null);
    const result = preview.kind === 'catalog'
      ? await gateway.applyCatalogRefine({ candidateId: preview.candidate.id, createdBy })
      : preview.kind === 'markup'
        ? await gateway.applyMarkupRefine({ candidateId: preview.candidate.id, createdBy })
        : await gateway.applyVisualRefine({ candidateId: preview.candidate.id, createdBy });
    setBusy(false);
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
    if (preview === null || busy) return;
    setBusy(true);
    setError(null);
    const result = preview.kind === 'catalog'
      ? await gateway.discardCatalogRefine({ candidateId: preview.candidate.id, createdBy })
      : preview.kind === 'markup'
        ? await gateway.discardMarkupRefine({ candidateId: preview.candidate.id, createdBy })
        : await gateway.discardVisualRefine({ candidateId: preview.candidate.id, createdBy });
    setBusy(false);
    if (result.error !== null) {
      setError(designerErrorMessage(result.error, 'refine'));
      return;
    }
    setPreview(null);
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
    return (
      <ScrollView contentContainerStyle={styles.workspace}>
        <Text style={styles.eyebrow}>REVIEW PREVIEW</Text>
        <Text style={styles.title}>Nothing has changed yet.</Text>
        <Text style={styles.body}>
          Compare this temporary candidate with the selected source revision. Apply will append a new revision;
          discard will leave history untouched.
        </Text>
        {understoodAs !== null && <Notice kind="info" text={understoodAs} />}
        <View style={styles.compareRow}>
          {sourceImageUrl !== null && (
            <View style={styles.comparePane}>
              <Text style={styles.compareLabel}>SOURCE</Text>
              <Image accessibilityLabel="Exact source revision" source={{ uri: sourceImageUrl }} imageRequestHeaders={imageRequestHeaders} style={styles.preview} />
            </View>
          )}
          <View style={styles.comparePane}>
            <Text style={styles.compareLabel}>PREVIEW</Text>
            <Image accessibilityLabel="Temporary refinement preview" source={{ uri: preview.candidate.assetUrl }} imageRequestHeaders={imageRequestHeaders} style={styles.preview} />
          </View>
        </View>
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
        <View style={styles.actions}>
          <Button title={busy ? 'Working…' : 'Discard'} kind="ghost" disabled={busy} onPress={() => { void discard(); }} />
          <Button title={busy ? 'Working…' : 'Apply as new revision'} disabled={busy || rejected} onPress={() => { void apply(); }} />
        </View>
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
      <Text style={styles.eyebrow}>REFINE</Text>
      <Text style={styles.title}>Change one thing. Keep the rest.</Text>
      <Text style={styles.body}>Choose how to target one change. Every route creates a temporary candidate before anything enters design history.</Text>

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
              onPress={() => { setMode(id); setError(null); }}
              style={[styles.modeCard, mode === id && styles.selectedCard, unavailable && styles.disabledCard]}>
              <Text style={styles.pathTitle}>{label}</Text>
              <Text style={styles.pathHelp}>{unavailable
                ? 'Confirm design facts before making structural component changes.'
                : detail}</Text>
            </Pressable>
          );
        })}
      </View>

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
      {error !== null && <Notice kind="error" text={error} />}
      <Button title={busy ? 'Creating preview…' : 'Preview change'} disabled={busy
        || (mode === 'component' && selected === null)
        || (mode === 'instruction' && !instruction.trim())
        || (mode === 'annotation' && (sourceImageUrl === null || snapshot.annotations.length === 0))}
        onPress={() => { void makePreview(); }} />
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
  disabledCard: { opacity: 0.48 },
  pathCard: { width: 180, borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 12, backgroundColor: theme.card },
  selectedCard: { borderColor: theme.accent, borderWidth: 2 },
  pathTitle: { color: theme.ink, fontWeight: '700', marginBottom: 4 },
  pathHelp: { color: theme.faint, fontSize: 12, lineHeight: 17 },
  optionList: { gap: 8 },
  optionCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 13, backgroundColor: theme.card },
  optionTitle: { color: theme.ink, fontWeight: '700', fontSize: 15 },
  optionDetail: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 4 },
  compareRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  comparePane: { flexGrow: 1, flexBasis: 280, gap: 6 },
  compareLabel: { color: theme.faint, fontSize: 10, fontWeight: '800', letterSpacing: 1.2 },
  preview: { width: '100%', aspectRatio: 1.25, borderRadius: radius.lg, backgroundColor: theme.line },
  reviewCard: { borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 14, backgroundColor: theme.card, gap: 8 },
  reviewTitle: { color: theme.ink, fontWeight: '800', fontSize: 16 },
  checkRow: { flexDirection: 'row', gap: 10, alignItems: 'flex-start' },
  checkVerdict: { color: theme.ok, width: 145, fontSize: 10, lineHeight: 14, fontWeight: '800', textTransform: 'uppercase' },
  reject: { color: theme.danger },
  checkCopy: { flex: 1 },
  checkLabel: { color: theme.ink, fontWeight: '600' },
  checkDetail: { color: theme.faint, fontSize: 12, marginTop: 2 },
  actions: { flexDirection: 'row', flexWrap: 'wrap' },
});
