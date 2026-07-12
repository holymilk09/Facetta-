import React, { useMemo, useState } from 'react';
import {
  Image, Pressable, ScrollView, StyleSheet, Text, View,
} from 'react-native';

import { Button, ChipRow, Field, Notice } from '../components';
import { radius, theme } from '../theme';
import type {
  BeautyRenderResult, MarketingPackResult, ProductPhotoFraming, ProductPhotoPreset,
  ProductPhotoResult, ProjectDetail,
} from '../trusted/types';
import { getStudioAction } from './actions';
import type { ExactStudioLineage, StudioGateway } from './gateway';

const PRESETS: readonly ProductPhotoPreset[] = [
  'catalog_white', 'luxury_studio', 'dark_editorial', 'macro_detail',
] as const;
const FRAMINGS: readonly ProductPhotoFraming[] = ['source', 'square', 'portrait'] as const;
const PRESENT_CREDITS = getStudioAction('present').creditEstimate ?? 0;

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
}

export interface StudioPresentWorkspaceProps {
  gateway: Pick<StudioGateway,
    'createBeautyPresentation' | 'createProductPresentation' | 'createMarketingPresentation'>;
  lineage: ExactStudioLineage | null;
  createdBy: string;
  onProjectUpdated?: (project: ProjectDetail) => void;
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
    detail: `Saved presentation · quality ${result.qa.verdict}`,
    status: 'saved',
  };
  return {
    id: result.warning_candidate.candidate_id ?? result.image_run_id,
    title: 'Beauty render needs review',
    imageUrl: result.warning_candidate.preview_url,
    detail: `Temporary candidate · quality ${result.quality_report.verdict}`,
    status: 'review',
  };
}

function productCard(result: ProductPhotoResult): PresentationCard {
  if (result.status === 'accepted') return {
    id: result.asset_id,
    title: presetLabel(result.presentation.preset),
    imageUrl: assetUrl(result.project, result.asset_id),
    detail: `Saved presentation · ${framingLabel(result.presentation.framing)} · quality ${result.qa.verdict}`,
    status: 'saved',
  };
  return {
    id: result.warning_candidate.candidate_id ?? result.image_run_id,
    title: `${presetLabel(result.presentation.preset)} needs review`,
    imageUrl: result.warning_candidate.preview_url,
    detail: `Temporary candidate · ${framingLabel(result.presentation.framing)} · quality ${result.quality_report.verdict}`,
    status: 'review',
  };
}

function marketingCards(result: MarketingPackResult): PresentationCard[] {
  return result.candidates.map((candidate) => ({
    id: candidate.candidate_id,
    title: presetLabel(candidate.preset),
    imageUrl: candidate.preview_url,
    detail: `Temporary candidate · ${framingLabel(candidate.framing)} · quality ${candidate.qa.verdict}`,
    status: 'review',
  }));
}

export function StudioPresentWorkspace({
  gateway, lineage, createdBy, onProjectUpdated,
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
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [cards, setCards] = useState<readonly PresentationCard[]>([]);
  const [failures, setFailures] = useState<readonly string[]>([]);

  const outputCount = destination === 'marketing' ? marketingPresets.length : 1;
  const creditEstimate = outputCount * PRESENT_CREDITS;
  const requestLabel = destination === 'marketing'
    ? `Generate ${outputCount} review candidate${outputCount === 1 ? '' : 's'}`
    : clientFormat === 'beauty' ? 'Create client beauty render' : 'Create client product photo';
  const exactRevision = useMemo(() => lineage === null ? null
    : `Revision ${lineage.sourceDesignVersion} · ${lineage.sourceAssetId}`, [lineage]);

  const togglePreset = (value: ProductPhotoPreset): void => {
    setMarketingPresets((current) => current.includes(value)
      ? current.filter((item) => item !== value) : [...current, value]);
  };

  const generate = async (): Promise<void> => {
    if (lineage === null || busy || outputCount === 0) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    setCards([]);
    setFailures([]);
    if (destination === 'client' && clientFormat === 'beauty') {
      const result = await gateway.createBeautyPresentation(lineage.projectId, {
        created_by: createdBy,
        expected_asset_id: lineage.sourceAssetId,
        source_asset_id: lineage.sourceAssetId,
        expected_design_version: lineage.sourceDesignVersion,
        ...(direction.trim() ? { instruction: direction.trim() } : {}),
        presentation_only: true,
      });
      setBusy(false);
      if (result.error !== null) return setError(result.error.message);
      setCards([beautyCard(result.data)]);
      if (result.data.status === 'accepted') onProjectUpdated?.(result.data.project);
      setInfo(result.data.status === 'accepted'
        ? 'Presentation saved. Your active design revision was not replaced.'
        : 'This result needs review and has not been saved as a presentation.');
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
      setBusy(false);
      if (result.error !== null) return setError(result.error.message);
      setCards([productCard(result.data)]);
      if (result.data.status === 'accepted') onProjectUpdated?.(result.data.project);
      setInfo(result.data.status === 'accepted'
        ? 'Presentation saved. Your active design revision was not replaced.'
        : 'This result needs review and has not been saved as a presentation.');
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
    setBusy(false);
    if (result.error !== null) return setError(result.error.message);
    setCards(marketingCards(result.data));
    setFailures(result.data.failures.map((failure) => `${presetLabel(failure.preset)}: ${failure.detail}`));
    setInfo(`${result.data.candidate_count} of ${result.data.requested_count} requested outputs are ready for review. Nothing changed your design revision.`);
  };

  if (lineage === null) return (
    <View style={styles.empty}>
      <Text style={styles.title}>Choose a saved direction first</Text>
      <Text style={styles.body}>Present always starts from one exact immutable revision.</Text>
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

      <Text style={styles.sectionTitle}>1 · Destination</Text>
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

      <Field label="Optional art direction" value={direction} onChange={setDirection} multiline
        placeholder="Soft daylight, generous negative space, understated styling…" />

      <View style={styles.costCard}>
        <Text style={styles.costTitle}>{outputCount} requested output{outputCount === 1 ? '' : 's'} · estimated {creditEstimate} credits</Text>
        <Text style={styles.costCopy}>Estimate: {PRESENT_CREDITS} credits per requested output. Internal retries and failed quality checks add 0 credits.</Text>
      </View>
      {error !== null && <Notice kind="error" text={error} />}
      <Button title={busy ? 'Generating and checking…' : requestLabel}
        disabled={busy || outputCount === 0} onPress={() => { void generate(); }} />

      {info !== null && <Notice kind="info" text={info} />}
      {failures.map((failure) => <Notice key={failure} kind="error" text={failure} />)}
      {cards.length > 0 && <View style={styles.results}>
        <Text style={styles.sectionTitle}>Results</Text>
        {cards.map((card) => <View key={card.id} style={styles.resultCard}>
          {card.imageUrl !== null && <Image accessibilityLabel={card.title} source={{ uri: card.imageUrl }} style={styles.preview} />}
          <View style={styles.resultCopy}>
            <Text style={styles.resultTitle}>{card.title}</Text>
            <Text style={styles.cardCopy}>{card.detail}</Text>
            {card.status === 'review' && <Text style={styles.reviewLabel}>Review-only · not part of canonical design history</Text>}
          </View>
        </View>)}
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
  resultCard: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, borderWidth: 1, borderColor: theme.line, borderRadius: radius.md, padding: 10, backgroundColor: theme.card },
  preview: { width: 190, aspectRatio: 1, borderRadius: radius.sm, backgroundColor: theme.line },
  resultCopy: { flex: 1, minWidth: 180, justifyContent: 'center' },
  resultTitle: { color: theme.ink, fontSize: 15, fontWeight: '800', marginBottom: 4 },
  reviewLabel: { color: theme.accent, fontSize: 11, fontWeight: '700', marginTop: 8 },
});
