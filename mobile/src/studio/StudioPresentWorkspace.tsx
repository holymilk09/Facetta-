import React, {
  useEffect, useMemo, useRef, useState,
} from 'react';
import {
  Pressable, ScrollView, StyleSheet, Text, View,
} from 'react-native';
import { AuthenticatedImage as Image } from '../AuthenticatedImage';

import { Button, ChipRow, Field, Notice } from '../components';
import { radius, theme } from '../theme';
import type {
  BeautyRenderResult, MarketingPackFailure, MarketingPackResult, ProductPhotoFraming, ProductPhotoPreset,
  PreSpecPresentationResult, ProductPhotoResult, ProjectDetail,
} from '../trusted/types';
import { getStudioAction } from './actions';
import type {
  ExactStudioLineage, StudioExactPresentationPreview, StudioGateway, StudioGatewayError,
  StudioVisualLineage,
} from './gateway';
import { designerReviewState } from './designerReviewLanguage';
import { STUDIO_PRESENT_CONTROLS } from './workspaceControls';

export { STUDIO_PRESENT_CONTROLS } from './workspaceControls';

const PRESETS: readonly ProductPhotoPreset[] = [
  'catalog_white', 'luxury_studio', 'dark_editorial', 'macro_detail',
] as const;
const FRAMINGS: readonly ProductPhotoFraming[] = ['source', 'square', 'portrait'] as const;
const PRESENT_CREDITS = getStudioAction('present').creditEstimate ?? 0;

const designerPresentationError = (error: StudioGatewayError): string => {
  if (error.category === 'conflict') {
    return 'This preview belongs to an earlier design revision. Generate it again from the selected revision.';
  }
  if (error.category === 'network') {
    return 'Facetta could not reach the image service. Check your connection and try again.';
  }
  if (error.category === 'quality') {
    return 'This image did not preserve the selected design closely enough. Try a new direction.';
  }
  if (error.category === 'validation') {
    return 'This presentation preview is no longer available. Generate a new preview from the selected revision.';
  }
  return 'Facetta could not finish this presentation action. Please try again.';
};

export const designerPresentationFailure = (failure: MarketingPackFailure): string => {
  const category = failure.error_category.toLowerCase();
  if (category === 'quality' || category === 'evaluation') {
    return 'This output did not preserve the selected design closely enough. Nothing was saved or charged.';
  }
  if (category === 'provider' || category === 'network' || category === 'unavailable') {
    return 'Facetta could not finish this output. Nothing was saved or charged; try it again.';
  }
  return 'Facetta could not verify this output, so nothing was saved or charged.';
};

const presetLabel = (preset: ProductPhotoPreset): string => ({
  catalog_white: 'Catalog white',
  luxury_studio: 'Luxury studio',
  dark_editorial: 'Dark editorial',
  macro_detail: 'Macro detail',
})[preset];

const framingLabel = (framing: ProductPhotoFraming): string => ({
  source: 'Keep source', square: 'Square', portrait: '4:5 portrait',
})[framing];

type Destination = 'client' | 'marketing';
type ClientFormat = 'beauty' | 'product';

interface PresentationCard {
  id: string;
  title: string;
  imageUrl: string | null;
  detail: string;
  status: 'saved' | 'review';
  candidateId: string | null;
  preSpec: boolean;
}

export interface StudioPresentWorkspaceProps {
  gateway: Pick<StudioGateway,
    | 'createBeautyPresentation'
    | 'createProductPresentation'
    | 'createMarketingPresentation'
    | 'acceptPresentationCandidate'
    | 'discardPresentationCandidate'
    | 'createPreSpecPresentation'
    | 'resumePreSpecPresentations'
    | 'resumeExactPresentations'
    | 'acceptPreSpecPresentation'
    | 'discardPreSpecPresentation'> & Partial<Pick<StudioGateway, 'assetImageUrl'>>;
  lineage: ExactStudioLineage | StudioVisualLineage | null;
  createdBy: string;
  onProjectUpdated?: (project: ProjectDetail) => void;
  /** Optional host navigation shown after at least one presentation is saved. */
  onOpenCollections?: () => void;
  imageRequestHeaders?: Readonly<Record<string, string>>;
  resumeReviewJobId?: string;
  reviewSourceIsActive?: boolean;
}

function assetUrl(project: ProjectDetail, assetId: string): string | null {
  return [...project.derived_assets, ...project.assets]
    .find((asset) => asset.asset_id === assetId)?.image_url ?? null;
}

function beautyCard(result: BeautyRenderResult): PresentationCard {
  if (result.status === 'accepted') return {
    id: result.asset_id,
    title: 'Client beauty render',
    imageUrl: assetUrl(result.project, result.asset_id),
    detail: `Saved presentation · ${designerReviewState(result.qa.verdict)}`,
    status: 'saved',
    candidateId: null,
    preSpec: false,
  };
  return {
    id: result.warning_candidate.candidate_id ?? result.image_run_id,
    title: 'Beauty render needs review',
    imageUrl: result.warning_candidate.preview_url,
    detail: `Not saved yet · ${designerReviewState(result.quality_report.verdict)}`,
    status: 'review',
    candidateId: result.warning_candidate.candidate_id,
    preSpec: false,
  };
}

function productCard(result: ProductPhotoResult): PresentationCard {
  if (result.status === 'accepted') return {
    id: result.asset_id,
    title: presetLabel(result.presentation.preset),
    imageUrl: assetUrl(result.project, result.asset_id),
    detail: `Saved presentation · ${framingLabel(result.presentation.framing)} · ${designerReviewState(result.qa.verdict)}`,
    status: 'saved',
    candidateId: null,
    preSpec: false,
  };
  return {
    id: result.warning_candidate.candidate_id ?? result.image_run_id,
    title: `${presetLabel(result.presentation.preset)} needs review`,
    imageUrl: result.warning_candidate.preview_url,
    detail: `Not saved yet · ${framingLabel(result.presentation.framing)} · ${designerReviewState(result.quality_report.verdict)}`,
    status: 'review',
    candidateId: result.warning_candidate.candidate_id,
    preSpec: false,
  };
}

function marketingCards(result: MarketingPackResult): PresentationCard[] {
  return result.candidates.map((candidate) => ({
    id: candidate.candidate_id,
    title: presetLabel(candidate.preset),
    imageUrl: candidate.preview_url,
    detail: `Not saved yet · ${framingLabel(candidate.framing)} · ${designerReviewState(candidate.qa.verdict)}`,
    status: 'review',
    candidateId: candidate.candidate_id,
    preSpec: false,
  }));
}

function preSpecCard(result: PreSpecPresentationResult): PresentationCard {
  const candidate = result.candidate;
  return {
    id: candidate.candidate_id,
    title: candidate.capability === 'CLIENT_BEAUTY_RENDER'
      ? 'Client beauty render' : presetLabel(candidate.preset),
    imageUrl: candidate.preview_url,
    detail: `Not saved yet · ${framingLabel(candidate.framing)} · ${designerReviewState(candidate.qa.verdict)}`,
    status: 'review',
    candidateId: candidate.candidate_id,
    preSpec: true,
  };
}

function exactResumeCard(result: StudioExactPresentationPreview): PresentationCard {
  const candidate = result.candidate;
  return {
    id: candidate.candidate_id,
    title: candidate.capability === 'CLIENT_BEAUTY_RENDER'
      ? 'Client beauty render' : presetLabel(candidate.preset),
    imageUrl: candidate.preview_url,
    detail: `Not saved yet · ${framingLabel(candidate.framing)} · ${designerReviewState(candidate.qa.verdict)}`,
    status: 'review',
    candidateId: candidate.candidate_id,
    preSpec: false,
  };
}

export function StudioPresentWorkspace({
  gateway, lineage, createdBy, onProjectUpdated, onOpenCollections, imageRequestHeaders,
  resumeReviewJobId, reviewSourceIsActive = true,
}: StudioPresentWorkspaceProps) {
  const [destination, setDestination] = useState<Destination>('client');
  const [clientFormat, setClientFormat] = useState<ClientFormat>('beauty');
  const [preset, setPreset] = useState<ProductPhotoPreset>('catalog_white');
  const [framing, setFraming] = useState<ProductPhotoFraming>('square');
  const [marketingPresets, setMarketingPresets] = useState<readonly ProductPhotoPreset[]>([
    'catalog_white', 'luxury_studio',
  ]);
  const [direction, setDirection] = useState('');
  const [busy, setBusy] = useState(false);
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [cards, setCards] = useState<readonly PresentationCard[]>([]);
  const [failures, setFailures] = useState<readonly string[]>([]);
  const lineageKey = lineage === null ? 'none'
    : 'sourceDesignVersion' in lineage
      ? `${lineage.projectId}:${lineage.sourceAssetId}:${lineage.sourceDesignVersion}`
      : `${lineage.projectId}:${lineage.sourceAssetId}:pre-spec`;
  const lineageKeyRef = useRef(lineageKey);
  lineageKeyRef.current = lineageKey;
  const [uiLineageKey, setUiLineageKey] = useState(lineageKey);
  const uiMatchesLineage = uiLineageKey === lineageKey;
  const visibleCards = uiMatchesLineage ? cards : [];
  const visibleFailures = uiMatchesLineage ? failures : [];
  const visibleError = uiMatchesLineage ? error : null;
  const visibleInfo = uiMatchesLineage ? info : null;

  const outputCount = destination === 'marketing' ? marketingPresets.length : 1;
  const creditEstimate = outputCount * PRESENT_CREDITS;
  const requestLabel = destination === 'marketing'
    ? `Generate ${outputCount} presentation preview${outputCount === 1 ? '' : 's'}`
    : clientFormat === 'beauty' ? 'Create client beauty render' : 'Create client product photo';
  const exactRevision = useMemo(() => lineage === null ? null
    : 'sourceDesignVersion' in lineage
      ? `Saved design · facts version ${lineage.sourceDesignVersion}`
      : 'Selected visual direction · specification not confirmed', [lineage]);
  const sourceImageUrl = lineage === null || typeof gateway.assetImageUrl !== 'function'
    ? null : gateway.assetImageUrl(lineage.sourceAssetId);

  useEffect(() => {
    setUiLineageKey(lineageKey);
    setCards([]);
    setFailures([]);
    setInfo(null);
    setError(null);
    setBusy(false);
    setDecidingId(null);
    if (lineage === null) return undefined;
    const requestedLineageKey = lineageKey;
    let active = true;
    if ('sourceDesignVersion' in lineage) {
      if (typeof gateway.resumeExactPresentations !== 'function') return undefined;
      const resumed = resumeReviewJobId === undefined
        ? gateway.resumeExactPresentations(lineage, createdBy)
        : gateway.resumeExactPresentations(lineage, createdBy, resumeReviewJobId);
      void resumed.then((result) => {
        if (!active || lineageKeyRef.current !== requestedLineageKey) return;
        if (result.error !== null) {
          setError(designerPresentationError(result.error));
          return;
        }
        if (result.data.length === 0) return;
        setCards((current) => current.length > 0 ? current : result.data.map(exactResumeCard));
        setInfo((current) => current ?? (
          `${result.data.length} saved preview${result.data.length === 1 ? '' : 's'} resumed for review.`
        ));
      });
    } else {
      if (typeof gateway.resumePreSpecPresentations !== 'function') return undefined;
      const resumed = resumeReviewJobId === undefined
        ? gateway.resumePreSpecPresentations(lineage, createdBy)
        : gateway.resumePreSpecPresentations(lineage, createdBy, resumeReviewJobId);
      void resumed.then((result) => {
        if (!active || lineageKeyRef.current !== requestedLineageKey) return;
        if (result.error !== null) {
          setError(designerPresentationError(result.error));
          return;
        }
        if (result.data.length === 0) return;
        setCards((current) => current.length > 0 ? current : result.data.map(preSpecCard));
        setInfo((current) => current ?? (
          `${result.data.length} saved preview${result.data.length === 1 ? '' : 's'} resumed for review.`
        ));
      });
    }
    return () => { active = false; };
  }, [createdBy, gateway, lineageKey, resumeReviewJobId]);

  const togglePreset = (value: ProductPhotoPreset): void => {
    setMarketingPresets((current) => current.includes(value)
      ? current.filter((item) => item !== value) : [...current, value]);
  };

  const savePresentation = async (card: PresentationCard): Promise<void> => {
    if (card.candidateId === null || decidingId !== null || !reviewSourceIsActive
      || sourceImageUrl === null) return;
    const requestedLineageKey = lineageKey;
    setDecidingId(card.id);
    setError(null);
    const result = await (card.preSpec
      ? gateway.acceptPreSpecPresentation({
        candidateId: card.candidateId, createdBy,
      })
      : gateway.acceptPresentationCandidate({
        candidateId: card.candidateId, createdBy,
      }));
    if (lineageKeyRef.current !== requestedLineageKey) return;
    setDecidingId(null);
    if (result.error !== null) {
      setError(designerPresentationError(result.error));
      return;
    }
    setCards((current) => current.map((item) => item.id === card.id ? {
      ...item,
      status: 'saved',
      candidateId: null,
      detail: item.detail.replace(/^Not saved yet/, 'Saved presentation'),
    } : item));
    setInfo('Presentation saved. Your selected design revision is unchanged.');
    onProjectUpdated?.(result.data.project);
  };

  const discardPresentation = async (card: PresentationCard): Promise<void> => {
    if (card.candidateId === null || decidingId !== null) return;
    const requestedLineageKey = lineageKey;
    setDecidingId(card.id);
    setError(null);
    const result = await (card.preSpec
      ? gateway.discardPreSpecPresentation({
        candidateId: card.candidateId, createdBy,
      })
      : gateway.discardPresentationCandidate({
        candidateId: card.candidateId, createdBy,
      }));
    if (lineageKeyRef.current !== requestedLineageKey) return;
    setDecidingId(null);
    if (result.error !== null) {
      setError(designerPresentationError(result.error));
      return;
    }
    setCards((current) => current.filter((item) => item.id !== card.id));
    setInfo('Presentation discarded. Your selected design revision is unchanged.');
  };

  const generate = async (): Promise<void> => {
    if (lineage === null || busy || outputCount === 0 || !reviewSourceIsActive) return;
    const requestedLineageKey = lineageKey;
    setBusy(true);
    setError(null);
    setInfo(null);
    setCards([]);
    setFailures([]);
    if (!('sourceDesignVersion' in lineage)) {
      if (destination === 'client') {
        const result = await gateway.createPreSpecPresentation(lineage.projectId, {
          created_by: createdBy,
          expected_active_asset_id: lineage.sourceAssetId,
          destination: 'client',
          client_format: clientFormat,
          preset: clientFormat === 'beauty' ? 'luxury_studio' : preset,
          framing,
          ...(direction.trim() ? { custom_instruction: direction.trim() } : {}),
        });
        if (lineageKeyRef.current !== requestedLineageKey) return;
        setBusy(false);
        if (result.error !== null) return setError(designerPresentationError(result.error));
        setCards([preSpecCard(result.data)]);
        setInfo('Preview ready. Save it as client material or discard it; your selected visual is unchanged.');
        return;
      }
      const results = await Promise.all(marketingPresets.map((selectedPreset, index) => (
        gateway.createPreSpecPresentation(lineage.projectId, {
          created_by: createdBy,
          expected_active_asset_id: lineage.sourceAssetId,
          destination: 'marketing',
          client_format: 'product',
          preset: selectedPreset,
          framing,
          ...(direction.trim() ? { custom_instruction: direction.trim() } : {}),
          variant: index,
        })
      )));
      if (lineageKeyRef.current !== requestedLineageKey) return;
      setBusy(false);
      const ready = results.flatMap((result) => result.error === null ? [result.data] : []);
      const failed = results.flatMap((result) => result.error === null
        ? [] : [designerPresentationError(result.error)]);
      setCards(ready.map(preSpecCard));
      setFailures(failed);
      setInfo(`${ready.length} of ${marketingPresets.length} requested outputs are ready for review. Your selected visual is unchanged.`);
      return;
    }
    if (destination === 'client' && clientFormat === 'beauty') {
      const result = await gateway.createBeautyPresentation(lineage.projectId, {
        created_by: createdBy,
        expected_asset_id: lineage.sourceAssetId,
        source_asset_id: lineage.sourceAssetId,
        expected_design_version: lineage.sourceDesignVersion,
        ...(direction.trim() ? { instruction: direction.trim() } : {}),
        presentation_only: true,
      });
      if (lineageKeyRef.current !== requestedLineageKey) return;
      setBusy(false);
      if (result.error !== null) return setError(designerPresentationError(result.error));
      if (result.data.status !== 'review_required') {
        setError('Facetta could not open a safe review preview. Nothing was saved or charged.');
        return;
      }
      setCards([beautyCard(result.data)]);
      setInfo('Preview ready for review. Nothing was saved or charged.');
      return;
    }
    if (destination === 'client') {
      const result = await gateway.createProductPresentation(lineage.projectId, {
        created_by: createdBy,
        expected_asset_id: lineage.sourceAssetId,
        expected_design_version: lineage.sourceDesignVersion,
        preset,
        framing,
        ...(direction.trim() ? { custom_instruction: direction.trim() } : {}),
        presentation_only: true,
      });
      if (lineageKeyRef.current !== requestedLineageKey) return;
      setBusy(false);
      if (result.error !== null) return setError(designerPresentationError(result.error));
      if (result.data.status !== 'review_required') {
        setError('Facetta could not open a safe review preview. Nothing was saved or charged.');
        return;
      }
      setCards([productCard(result.data)]);
      setInfo('Preview ready for review. Nothing was saved or charged.');
      return;
    }
    const result = await gateway.createMarketingPresentation(lineage.projectId, {
      created_by: createdBy,
      expected_asset_id: lineage.sourceAssetId,
      expected_design_version: lineage.sourceDesignVersion,
      presets: [...marketingPresets],
      framing,
      ...(direction.trim() ? { custom_instruction: direction.trim() } : {}),
    });
    if (lineageKeyRef.current !== requestedLineageKey) return;
    setBusy(false);
    if (result.error !== null) return setError(designerPresentationError(result.error));
    setCards(marketingCards(result.data));
    setFailures(result.data.failures.map((failure) => (
      `${presetLabel(failure.preset)}: ${designerPresentationFailure(failure)}`
    )));
    setInfo(`${result.data.candidate_count} of ${result.data.requested_count} requested outputs are ready for review. Nothing changed your design revision.`);
  };

  if (lineage === null) return (
    <View style={styles.empty}>
      <Text style={styles.title}>Choose a saved direction first</Text>
      <Text style={styles.body}>Present always starts from one saved revision.</Text>
    </View>
  );

  return (
    <ScrollView contentContainerStyle={styles.workspace}>
      <Text style={styles.eyebrow}>PRESENT</Text>
      <Text style={styles.title}>Turn this exact design into presentation imagery.</Text>
      <Text style={styles.body}>Choose where the image is going. Facetta keeps the selected design revision fixed and stores presentation imagery separately.</Text>
      <View style={styles.lineageCard}>
        <Text style={styles.lineageLabel}>Exact source</Text>
        <Text style={styles.lineageValue}>{exactRevision}</Text>
      </View>
      {!reviewSourceIsActive && <Notice kind="info" text="This result was created from an earlier revision. Saving or generating from it is unavailable. You can discard the pending result without changing or charging the current design." />}

      <Text style={styles.sectionTitle}>1 · {STUDIO_PRESENT_CONTROLS.destination.label}</Text>
      <View style={styles.destinationRow}>
        {(['client', 'marketing'] as const).map((item) => (
          <Pressable key={item} onPress={() => { setDestination(item); setCards([]); setInfo(null); }}
            style={[styles.destinationCard, destination === item && styles.selectedCard]}>
            <Text style={styles.destinationTitle}>{item === 'client' ? 'Client' : 'Marketing'}</Text>
            <Text style={styles.cardCopy}>{item === 'client'
              ? 'One polished image for a review or presentation.'
              : 'A small, review-only ecommerce image set.'}</Text>
          </Pressable>
        ))}
      </View>

      {destination === 'client' ? (
        <>
          <Text style={styles.sectionTitle}>2 · Output</Text>
          <ChipRow label="Format" options={['beauty', 'product'] as const} value={clientFormat}
            onSelect={setClientFormat} render={(value) => value === 'beauty' ? 'Beauty render' : 'Product photo'} />
          {clientFormat === 'product' && <>
            <ChipRow label="Photography direction" options={PRESETS} value={preset} onSelect={setPreset} render={presetLabel} />
            <ChipRow label="Framing" options={FRAMINGS} value={framing} onSelect={setFraming} render={framingLabel} />
          </>}
        </>
      ) : (
        <>
          <Text style={styles.sectionTitle}>2 · Outputs</Text>
          <Text style={styles.body}>Select only the scenes you need. Every selected scene is a requested output.</Text>
          <View style={styles.presetGrid}>{PRESETS.map((item) => {
            const selected = marketingPresets.includes(item);
            return <Pressable key={item} accessibilityRole="checkbox" accessibilityState={{ checked: selected }}
              onPress={() => togglePreset(item)} style={[styles.presetCard, selected && styles.selectedCard]}>
              <Text style={styles.presetTitle}>{selected ? '✓ ' : ''}{presetLabel(item)}</Text>
            </Pressable>;
          })}</View>
          <ChipRow label="Framing" options={FRAMINGS} value={framing} onSelect={setFraming} render={framingLabel} />
        </>
      )}

      <Field label={STUDIO_PRESENT_CONTROLS.direction.label} value={direction} onChange={setDirection} multiline
        placeholder="Soft daylight, generous negative space, understated styling…" />

      <View style={styles.costCard}>
        <Text style={styles.costTitle}>{outputCount} requested output{outputCount === 1 ? '' : 's'} · estimated {creditEstimate} credits</Text>
        <Text style={styles.costCopy}>Generation creates review previews only. You are charged only for the outputs you explicitly save. Discarded, stale, and unusable results cost 0 credits.</Text>
      </View>
      {visibleError !== null && <Notice kind="error" text={visibleError} />}
      <Button title={busy ? 'Generating and checking…' : requestLabel}
        disabled={busy || outputCount === 0 || !reviewSourceIsActive} onPress={() => { void generate(); }} />

      {visibleInfo !== null && <Notice kind="info" text={visibleInfo} />}
      {visibleCards.some((card) => card.status === 'saved') && onOpenCollections !== undefined && (
        <Button title="Open in Collections" kind="ghost" onPress={onOpenCollections} />
      )}
      {visibleFailures.map((failure) => <Notice key={failure} kind="error" text={failure} />)}
      {visibleCards.length > 0 && <View style={styles.results}>
        <Text style={styles.sectionTitle}>Results</Text>
        <View style={styles.reviewWorkspace}>
          {sourceImageUrl !== null && <View style={styles.sourcePanel}>
            <Text style={styles.comparisonLabel}>Exact source · unchanged</Text>
            <Image accessibilityLabel="Exact source revision" source={{ uri: sourceImageUrl }} imageRequestHeaders={imageRequestHeaders} style={styles.sourcePreview} />
            <Text style={styles.sourceGuidance}>Use this one fixed reference to check the form, setting, and proportions of every output.</Text>
          </View>}
          {sourceImageUrl === null && (
            <Notice
              kind="error"
              text="The exact source cannot be displayed, so these presentations cannot be saved. Reopen the design and compare again."
            />
          )}
          <View style={styles.candidateGrid}>
            {visibleCards.map((card) => <View key={card.id} style={styles.resultCard}>
              {card.imageUrl !== null && <View style={styles.candidateImage}>
                <Text style={styles.comparisonLabel}>{card.status === 'review'
                  ? 'Candidate · review before saving' : 'Saved presentation'}</Text>
                <Image accessibilityLabel={card.title} source={{ uri: card.imageUrl }} imageRequestHeaders={imageRequestHeaders} style={styles.preview} />
              </View>}
              <View style={styles.resultCopy}>
                <Text style={styles.resultTitle}>{card.title}</Text>
                <Text style={styles.cardCopy}>{card.detail}</Text>
                {card.status === 'review' && <>
                  <Text style={styles.reviewLabel}>Not saved · choose what to keep</Text>
                  <View style={styles.decisionRow}>
                    <Button
                      title={decidingId === card.id ? 'Saving…' : 'Save presentation'}
                      disabled={decidingId !== null || !reviewSourceIsActive || sourceImageUrl === null}
                      onPress={() => { void savePresentation(card); }}
                    />
                    <Button
                      title={decidingId === card.id ? 'Working…' : 'Discard'}
                      kind="ghost"
                      disabled={decidingId !== null}
                      onPress={() => { void discardPresentation(card); }}
                    />
                  </View>
                </>}
              </View>
            </View>)}
          </View>
        </View>
      </View>}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  workspace: { padding: 22, paddingBottom: 120, gap: 12 },
  empty: { padding: 28, alignItems: 'center', gap: 8 },
  eyebrow: { color: theme.accent, fontSize: 11, fontWeight: '800', letterSpacing: 2 },
  title: { color: theme.ink, fontFamily: theme.serif, fontSize: 28, lineHeight: 34, maxWidth: 720 },
  body: { color: theme.faint, fontSize: 14, lineHeight: 21, maxWidth: 680 },
  sectionTitle: { color: theme.ink, fontSize: 12, fontWeight: '800', letterSpacing: 1.4, marginTop: 10 },
  lineageCard: { borderLeftWidth: 3, borderLeftColor: theme.gold, backgroundColor: theme.goldSoft, padding: 12, borderRadius: radius.sm },
  lineageLabel: { color: theme.faint, fontSize: 11, fontWeight: '700', textTransform: 'uppercase' },
  lineageValue: { color: theme.ink, fontWeight: '700', marginTop: 3 },
  destinationRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  destinationCard: { width: 240, padding: 14, borderRadius: radius.md, borderWidth: 1, borderColor: theme.line, backgroundColor: theme.card },
  selectedCard: { borderColor: theme.accent, borderWidth: 2 },
  destinationTitle: { color: theme.ink, fontSize: 17, fontWeight: '800', marginBottom: 4 },
  cardCopy: { color: theme.faint, fontSize: 12, lineHeight: 18 },
  presetGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  presetCard: { minWidth: 150, padding: 11, borderRadius: radius.md, borderWidth: 1, borderColor: theme.line, backgroundColor: theme.card },
  presetTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  costCard: { padding: 13, borderRadius: radius.md, backgroundColor: theme.blush, borderWidth: 1, borderColor: theme.line },
  costTitle: { color: theme.ink, fontSize: 14, fontWeight: '800' },
  costCopy: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 4 },
  results: { gap: 10 },
  reviewWorkspace: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'flex-start', gap: 12 },
  sourcePanel: { width: 230, gap: 6, padding: 10, borderWidth: 1, borderColor: theme.gold, borderRadius: radius.md, backgroundColor: theme.goldSoft },
  sourceGuidance: { color: theme.faint, fontSize: 11, lineHeight: 16 },
  sourcePreview: { width: '100%', aspectRatio: 1, borderRadius: radius.sm, backgroundColor: theme.line },
  candidateGrid: { flex: 1, minWidth: 240, flexDirection: 'row', flexWrap: 'wrap', alignItems: 'flex-start', gap: 10 },
  resultCard: { flexGrow: 1, flexBasis: 240, maxWidth: 340, gap: 10, borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 10, backgroundColor: theme.card },
  candidateImage: { gap: 5 },
  comparisonLabel: { color: theme.faint, fontSize: 10, fontWeight: '800', textTransform: 'uppercase' },
  preview: { width: '100%', aspectRatio: 1, borderRadius: radius.sm, backgroundColor: theme.line },
  resultCopy: { minWidth: 180 },
  resultTitle: { color: theme.ink, fontSize: 15, fontWeight: '800', marginBottom: 4 },
  reviewLabel: { color: theme.accent, fontSize: 11, fontWeight: '700', marginTop: 8 },
  decisionRow: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 10 },
});
