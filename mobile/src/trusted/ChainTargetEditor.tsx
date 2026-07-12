import React, { useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { ChipRow, Field, Notice } from '../components';
import { theme } from '../theme';
import type {
  ChainGeometry,
  ChainLinkDimensions,
  ChainProduction,
} from './types';

export type ChainConstruction = ChainGeometry['construction'];

export interface ChainTargetDraft {
  chainWidth: string;
  profileThickness: string;
  endRingOuterDiameter: string;
  linkThickness: string;
  linksSoldered: 'yes' | 'no';
  standardLength: string;
  standardInsideLength: string;
  standardInsideWidth: string;
  longLength: string;
  longInsideLength: string;
  longInsideWidth: string;
  strandWireDiameter: string;
  strandCount: string;
  plateThickness: string;
  productionMode: 'stock' | 'custom';
  stockReferenceKind: 'supplier_sku' | 'approved_sample';
  customReferenceKind: 'dimensioned_drawing' | 'cad_asset';
  productionReference: string;
}

export interface ChainTargetData {
  geometry: ChainGeometry;
  production: ChainProduction;
}

export const EMPTY_CHAIN_TARGET_DRAFT: ChainTargetDraft = {
  chainWidth: '',
  profileThickness: '',
  endRingOuterDiameter: '',
  linkThickness: '',
  linksSoldered: 'yes',
  standardLength: '',
  standardInsideLength: '',
  standardInsideWidth: '',
  longLength: '',
  longInsideLength: '',
  longInsideWidth: '',
  strandWireDiameter: '',
  strandCount: '',
  plateThickness: '',
  productionMode: 'stock',
  stockReferenceKind: 'supplier_sku',
  customReferenceKind: 'dimensioned_drawing',
  productionReference: '',
};

export function chainConstructionForStyle(style: string): ChainConstruction | null {
  if (['cable', 'curb', 'figaro', 'box'].includes(style)) return 'open_link';
  if (['rope', 'wheat', 'singapore'].includes(style)) return 'stranded';
  if (style === 'snake') return 'smooth_plate';
  return null;
}

const positiveNumber = (value: string): number | null => {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
};

const positiveInteger = (value: string): number | null => {
  const parsed = positiveNumber(value);
  return parsed !== null && Number.isInteger(parsed) ? parsed : null;
};

export function buildChainTargetData(
  style: string,
  draft: ChainTargetDraft,
): ChainTargetData | null {
  const construction = chainConstructionForStyle(style);
  const chainWidth = positiveNumber(draft.chainWidth);
  const profileThickness = positiveNumber(draft.profileThickness);
  const endRingOuterDiameter = positiveNumber(draft.endRingOuterDiameter);
  const reference = draft.productionReference.trim();
  if (construction === null || chainWidth === null || profileThickness === null
    || endRingOuterDiameter === null || !reference) return null;

  const production: ChainProduction = draft.productionMode === 'stock'
    ? {
        mode: 'stock',
        reference_kind: draft.stockReferenceKind,
        reference,
      }
    : {
        mode: 'custom',
        reference_kind: draft.customReferenceKind,
        reference,
      };
  const common = {
    chain_width_mm: chainWidth,
    profile_thickness_mm: profileThickness,
    end_ring_outer_diameter_mm: endRingOuterDiameter,
  };

  if (construction === 'open_link') {
    const linkThickness = positiveNumber(draft.linkThickness);
    const standardLength = positiveNumber(draft.standardLength);
    const standardInsideLength = positiveNumber(draft.standardInsideLength);
    const standardInsideWidth = positiveNumber(draft.standardInsideWidth);
    if (linkThickness === null || standardLength === null
      || standardInsideLength === null || standardInsideWidth === null) return null;
    const links: ChainLinkDimensions[] = [{
      role: 'standard',
      length_mm: standardLength,
      inside_length_mm: standardInsideLength,
      inside_width_mm: standardInsideWidth,
    }];
    if (style === 'figaro') {
      const longLength = positiveNumber(draft.longLength);
      const longInsideLength = positiveNumber(draft.longInsideLength);
      const longInsideWidth = positiveNumber(draft.longInsideWidth);
      if (longLength === null || longInsideLength === null
        || longInsideWidth === null) return null;
      links.push({
        role: 'long',
        length_mm: longLength,
        inside_length_mm: longInsideLength,
        inside_width_mm: longInsideWidth,
      });
    }
    return {
      geometry: {
        construction,
        ...common,
        link_thickness_mm: linkThickness,
        links_soldered: draft.linksSoldered === 'yes',
        links,
      },
      production,
    };
  }

  if (construction === 'stranded') {
    const strandWireDiameter = positiveNumber(draft.strandWireDiameter);
    const strandCount = positiveInteger(draft.strandCount);
    if (strandWireDiameter === null || strandCount === null) return null;
    return {
      geometry: {
        construction,
        ...common,
        strand_wire_diameter_mm: strandWireDiameter,
        strand_count: strandCount,
      },
      production,
    };
  }

  const plateThickness = positiveNumber(draft.plateThickness);
  if (plateThickness === null) return null;
  return {
    geometry: {
      construction,
      ...common,
      plate_thickness_mm: plateThickness,
    },
    production,
  };
}

export interface ChainTargetEditorProps {
  style: string;
  onChange: (target: ChainTargetData | null) => void;
}

export function ChainTargetEditor({ style, onChange }: ChainTargetEditorProps) {
  const [draft, setDraft] = useState<ChainTargetDraft>(EMPTY_CHAIN_TARGET_DRAFT);
  const construction = chainConstructionForStyle(style);
  const target = useMemo(() => buildChainTargetData(style, draft), [draft, style]);

  useEffect(() => {
    setDraft(EMPTY_CHAIN_TARGET_DRAFT);
  }, [style]);

  useEffect(() => {
    onChange(target);
  }, [onChange, target]);

  const set = <K extends keyof ChainTargetDraft>(key: K, value: ChainTargetDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  return (
    <View style={styles.wrap}>
      <Text style={styles.heading}>Target chain manufacturing record</Text>
      <Notice
        kind="info"
        text="The chain type tells the image agent what to isolate. Before Apply, confirm the target chain's measured geometry and its exact stock/sample/drawing/CAD reference; Facetta will not reuse the old chain's SKU."
      />
      <Text style={styles.meta}>Construction family: {construction ?? 'unsupported'}</Text>
      <Field label="Finished chain width (mm)" value={draft.chainWidth}
        onChange={(value) => set('chainWidth', value)} numeric placeholder="Target chain width" />
      <Field label="Finished profile thickness (mm)" value={draft.profileThickness}
        onChange={(value) => set('profileThickness', value)} numeric placeholder="Target profile thickness" />
      <Field label="Target end-ring outer diameter (mm)" value={draft.endRingOuterDiameter}
        onChange={(value) => set('endRingOuterDiameter', value)} numeric placeholder="Target end-ring OD" />

      {construction === 'open_link' && (
        <>
          <Field label="Finished link thickness / gauge (mm)" value={draft.linkThickness}
            onChange={(value) => set('linkThickness', value)} numeric placeholder="Target link thickness" />
          <ChipRow label="Links soldered" options={['yes', 'no'] as const}
            value={draft.linksSoldered} onSelect={(value) => set('linksSoldered', value)} />
          <Text style={styles.subheading}>Standard link repeat</Text>
          <Field label="Outside length (mm)" value={draft.standardLength}
            onChange={(value) => set('standardLength', value)} numeric placeholder="Standard outside length" />
          <Field label="Inside length (mm)" value={draft.standardInsideLength}
            onChange={(value) => set('standardInsideLength', value)} numeric placeholder="Standard inside length" />
          <Field label="Inside width (mm)" value={draft.standardInsideWidth}
            onChange={(value) => set('standardInsideWidth', value)} numeric placeholder="Standard inside width" />
          {style === 'figaro' && (
            <>
              <Text style={styles.subheading}>Long Figaro repeat</Text>
              <Field label="Long-link outside length (mm)" value={draft.longLength}
                onChange={(value) => set('longLength', value)} numeric placeholder="Long outside length" />
              <Field label="Long-link inside length (mm)" value={draft.longInsideLength}
                onChange={(value) => set('longInsideLength', value)} numeric placeholder="Long inside length" />
              <Field label="Long-link inside width (mm)" value={draft.longInsideWidth}
                onChange={(value) => set('longInsideWidth', value)} numeric placeholder="Long inside width" />
            </>
          )}
        </>
      )}

      {construction === 'stranded' && (
        <>
          <Field label="Strand wire diameter (mm)" value={draft.strandWireDiameter}
            onChange={(value) => set('strandWireDiameter', value)} numeric placeholder="Target strand wire diameter" />
          <Field label="Strand count" value={draft.strandCount}
            onChange={(value) => set('strandCount', value)} numeric placeholder="Target strand count" />
        </>
      )}

      {construction === 'smooth_plate' && (
        <Field label="Plate thickness (mm)" value={draft.plateThickness}
          onChange={(value) => set('plateThickness', value)} numeric placeholder="Target plate thickness" />
      )}

      <ChipRow label="Production route" options={['stock', 'custom'] as const}
        value={draft.productionMode} onSelect={(value) => set('productionMode', value)} />
      {draft.productionMode === 'stock' ? (
        <ChipRow label="Target stock identity"
          options={['supplier_sku', 'approved_sample'] as const}
          value={draft.stockReferenceKind}
          onSelect={(value) => set('stockReferenceKind', value)}
          render={(value) => value === 'supplier_sku' ? 'Supplier SKU' : 'Approved sample'} />
      ) : (
        <ChipRow label="Target custom authority"
          options={['dimensioned_drawing', 'cad_asset'] as const}
          value={draft.customReferenceKind}
          onSelect={(value) => set('customReferenceKind', value)}
          render={(value) => value === 'dimensioned_drawing' ? 'Dimensioned drawing' : 'CAD asset'} />
      )}
      <Field
        label={draft.productionMode === 'stock'
          ? 'Exact target SKU or approved-sample ID'
          : 'Exact target drawing or CAD asset ID'}
        value={draft.productionReference}
        onChange={(value) => set('productionReference', value)}
        placeholder="Required target-style reference"
      />
      {target === null ? (
        <Notice kind="info" text="Complete every target-chain field before confirming Apply." />
      ) : (
        <Notice kind="ok" text="Target geometry and production reference are complete for validation." />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { borderTopColor: theme.line, borderTopWidth: 1, marginTop: 12, paddingTop: 10 },
  heading: { color: theme.ink, fontSize: 14, fontWeight: '600', marginBottom: 6 },
  subheading: { color: theme.accent, fontSize: 12, fontWeight: '600', marginTop: 6 },
  meta: { color: theme.faint, fontSize: 12, marginBottom: 4 },
});
