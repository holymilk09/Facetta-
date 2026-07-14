import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { AuthenticatedImage as Image } from '../AuthenticatedImage';

import { Button, Field, Notice } from '../components';
import { createClientOperationId } from '../operationId';
import { theme } from '../theme';
import { ChainTargetEditor, type ChainTargetData } from './ChainTargetEditor';
import type { TrustedApiClient } from './client';
import type {
  CatalogPreviewAcceptResult,
  CatalogPreviewResult,
  ComponentCatalog,
  ComponentCatalogOption,
  ComponentCatalogPath,
  JsonObject,
  JsonValue,
  ProjectDetail,
  StoneVocabularyEntry,
} from './types';

const RING_CATALOGS: ComponentCatalogPath[] = [
  'metal.material',
  'metal.color',
  'stone.color',
  'stone.cut',
  'setting.style',
];
const NECKLACE_CATALOGS: ComponentCatalogPath[] = ['chain.style'];
const QUICK_CATALOGS = new Set<ComponentCatalogPath>([
  'chain.style',
  'metal.material',
  'metal.color',
  'stone.color',
]);

const quickSwatch = (optionId: string): string | null => {
  const normalized = optionId.toLowerCase();
  if (normalized.includes('yellow')) return '#D5A924';
  if (normalized.includes('rose') || normalized.includes('pink')) return '#C98282';
  if (normalized.includes('white') || normalized.includes('platinum')) return '#D7DCE2';
  if (normalized.includes('royal_blue') || normalized.includes('kashmir')) return '#1B4EA1';
  if (normalized.includes('cornflower')) return '#6C8CD5';
  if (normalized.includes('pigeon') || normalized.includes('ruby') || normalized.includes('red')) return '#B52235';
  if (normalized.includes('emerald') || normalized.includes('green')) return '#147A5A';
  if (normalized.includes('paraiba') || normalized.includes('lagoon')) return '#2ABDC0';
  if (normalized.includes('diamond')) return '#DDEBFC';
  return null;
};

export function componentCatalogPathsForSpec(spec: JsonObject): ComponentCatalogPath[] {
  if (spec.jewelry_type === 'ring') return [...RING_CATALOGS];
  if (spec.jewelry_type === 'necklace') return [...NECKLACE_CATALOGS];
  return [];
}

function readSpecPath(spec: JsonObject, path: string): JsonValue | undefined {
  let current: JsonValue = spec;
  for (const segment of path.split('.')) {
    if (typeof current !== 'object' || current === null || Array.isArray(current)) {
      return undefined;
    }
    current = current[segment];
    if (current === undefined) return undefined;
  }
  return current;
}

function sameJsonValue(left: JsonValue | undefined, right: JsonValue): boolean {
  return left !== undefined && JSON.stringify(left) === JSON.stringify(right);
}

export interface CatalogFactoryDelta {
  path: string;
  before: JsonValue | undefined;
  after: JsonValue | undefined;
  derived: boolean;
}

export function catalogFactoryDelta(
  spec: JsonObject,
  option: ComponentCatalogOption,
): CatalogFactoryDelta[] {
  const assigned = Object.entries(option.factory_fields).map(([path, after]) => ({
    path,
    before: readSpecPath(spec, path),
    after,
    derived: false,
  }));
  const assignedPaths = new Set(assigned.map((item) => item.path));
  return [
    ...assigned,
    ...option.derived_factory_fields
      .filter((path) => !assignedPaths.has(path))
      .map((path) => ({
        path,
        before: readSpecPath(spec, path),
        after: undefined,
        derived: true,
      })),
  ];
}

function optionIsCurrent(spec: JsonObject, option: ComponentCatalogOption): boolean {
  const assigned = Object.entries(option.factory_fields);
  return assigned.length > 0
    && assigned.every(([path, after]) => sameJsonValue(readSpecPath(spec, path), after));
}

function displayValue(value: JsonValue | undefined): string {
  if (value === undefined || value === null) return 'Not set';
  if (typeof value === 'string') return value.replace(/_/g, ' ');
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

interface SelectedOption {
  catalog: ComponentCatalog;
  option: ComponentCatalogOption;
}

export interface ComponentCatalogPanelProps {
  client: TrustedApiClient;
  project: ProjectDetail;
  spec: JsonObject;
  createdBy: string;
  mobileReviewOnly?: boolean;
  variant?: number;
  onApplied?: (result: CatalogPreviewAcceptResult) => void;
  onProjectChanged?: (project: ProjectDetail) => void;
  onVariationCreated?: (project: ProjectDetail) => void;
}

export function ComponentCatalogPanel({
  client,
  project,
  spec,
  createdBy,
  mobileReviewOnly,
  variant = 0,
  onApplied,
  onProjectChanged,
  onVariationCreated,
}: ComponentCatalogPanelProps) {
  const { width } = useWindowDimensions();
  const reviewOnly = mobileReviewOnly ?? width < 600;
  const paths = useMemo(() => componentCatalogPathsForSpec(spec), [spec]);
  const pathKey = paths.join('|');
  const [catalogs, setCatalogs] = useState<ComponentCatalog[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<SelectedOption | null>(null);
  const [preview, setPreview] = useState<CatalogPreviewResult | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [acceptBusy, setAcceptBusy] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [chainTarget, setChainTarget] = useState<ChainTargetData | null>(null);
  const [showStructuralChoices, setShowStructuralChoices] = useState(false);
  const [stonePaletteSpecies, setStonePaletteSpecies] = useState<string | null>(() => {
    const activeStoneSpecies = readSpecPath(spec, 'stone.species');
    return typeof activeStoneSpecies === 'string' ? activeStoneSpecies : null;
  });
  const [stoneChoices, setStoneChoices] = useState<StoneVocabularyEntry[]>([]);
  const [showStoneChoices, setShowStoneChoices] = useState(false);
  const [showAllStoneChoices, setShowAllStoneChoices] = useState(false);
  const [stoneSearch, setStoneSearch] = useState('');
  const [variationBusy, setVariationBusy] = useState(false);
  const [variationError, setVariationError] = useState<string | null>(null);
  const variationOperationRef = useRef<{ key: string; id: string } | null>(null);

  useEffect(() => {
    let active = true;
    setSelected(null);
    setPreview(null);
    setPreviewError(null);
    setVariationError(null);
    setChainTarget(null);
    setCatalogs([]);
    setLoadError(null);
    setLoading(false);
    if (paths.length === 0) return () => { active = false; };
    const activeStoneSpecies = readSpecPath(spec, 'stone.species');
    const paletteSpecies = stonePaletteSpecies
      ?? (typeof activeStoneSpecies === 'string' ? activeStoneSpecies : null);
    setLoading(true);
    void Promise.all(paths.map((path) => (
      path === 'stone.color' && paletteSpecies !== null
        ? client.getComponentCatalog(path, { stoneSpecies: paletteSpecies })
        : client.getComponentCatalog(path)
    )))
      .then((responses) => {
        if (!active) return;
        const failed = responses.find((response) => response.error !== null);
        if (failed?.error !== null && failed?.error !== undefined) {
          setLoadError(failed.error.message);
          setCatalogs([]);
          return;
        }
        const loaded = responses.flatMap((response) => response.data === null
          ? [] : [response.data]);
        if (
          loaded.length !== paths.length
          || loaded.some((catalog) => !catalog.applicable_jewelry_types.includes(
            String(spec.jewelry_type),
          ))
        ) {
          setLoadError('The component catalog did not match this jewelry specification.');
          setCatalogs([]);
          return;
        }
        setCatalogs(loaded);
      })
      .catch(() => {
        if (active) setLoadError('The component catalog could not be loaded safely.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
    // pathKey represents the closed path set; spec identity intentionally
    // reloads current-option state when any confirmed fact changes.
  }, [client, pathKey, paths, spec, stonePaletteSpecies]);

  useEffect(() => {
    const activeStoneSpecies = readSpecPath(spec, 'stone.species');
    setStonePaletteSpecies(typeof activeStoneSpecies === 'string' ? activeStoneSpecies : null);
    setShowStoneChoices(false);
    setShowAllStoneChoices(false);
    setStoneSearch('');
  }, [spec]);

  useEffect(() => {
    let active = true;
    if (!paths.includes('stone.color')) return () => { active = false; };
    void client.getStoneVocabulary().then((response) => {
      if (active && response.error === null) setStoneChoices(response.data);
    });
    return () => { active = false; };
  }, [client, pathKey, paths]);

  const selectionCurrent = selected !== null && optionIsCurrent(spec, selected.option);
  const categoryPending = selected?.catalog.image_agent_status
    === 'catalog_ready_category_pending';
  const canPreview = selected !== null && !selectionCurrent
    && !categoryPending && !reviewOnly && !previewBusy && !acceptBusy
    && (selected?.catalog.component_path !== 'chain.style' || chainTarget !== null)
    && project.active_asset_id !== null && project.active_design_version !== null;

  const previewSelection = async (): Promise<void> => {
    if (!canPreview || selected === null || project.active_asset_id === null
      || project.active_design_version === null) return;
    if (preview !== null) await client.discardCatalogPreview(preview.candidate);
    setPreviewBusy(true);
    setPreviewError(null);
    setPreview(null);
    const response = await client.previewCatalogSelection(project.active_asset_id, {
      component_path: selected.catalog.component_path,
      option_id: selected.option.id,
      expected_design_version: project.active_design_version,
      created_by: createdBy,
      variant,
      ...(selected.catalog.component_path === 'stone.color'
        && stonePaletteSpecies !== null
        ? { stone_species: stonePaletteSpecies }
        : {}),
      ...(selected.catalog.component_path === 'chain.style' && chainTarget !== null
        ? {
            chain_geometry: chainTarget.geometry,
            chain_production: chainTarget.production,
          }
        : {}),
    });
    setPreviewBusy(false);
    if (response.error !== null) {
      setPreviewError(response.error.message);
      return;
    }
    setPreview(response.data);
  };

  const acceptPreview = async (): Promise<void> => {
    if (preview === null || acceptBusy) return;
    setAcceptBusy(true);
    setPreviewError(null);
    const response = await client.acceptCatalogPreview(preview.candidate, {
      expected_design_version: preview.design_version,
      created_by: createdBy,
    });
    setAcceptBusy(false);
    if (response.error !== null) {
      setPreviewError(response.error.message);
      return;
    }
    setPreview(null);
    setSelected(null);
    onApplied?.(response.data);
    onProjectChanged?.(response.data.project);
  };

  const discardPreview = async (): Promise<void> => {
    if (preview === null || previewBusy || acceptBusy) return;
    const candidate = preview.candidate;
    setPreview(null);
    setPreviewError(null);
    const response = await client.discardCatalogPreview(candidate);
    if (response.error !== null) setPreviewError(response.error.message);
  };

  const saveAsVariation = async (): Promise<void> => {
    if (selected === null || project.active_asset_id === null || variationBusy || reviewOnly) return;
    const operationKey = [
      project.root_id,
      project.active_asset_id,
      project.active_design_version ?? 'none',
      selected.catalog.component_path,
      selected.option.id,
    ].join(':');
    if (variationOperationRef.current?.key !== operationKey) {
      variationOperationRef.current = {
        key: operationKey,
        id: createClientOperationId('catalog-vary'),
      };
    }
    const operationId = variationOperationRef.current.id;
    if (preview !== null) await client.discardCatalogPreview(preview.candidate);
    setPreview(null);
    setVariationBusy(true);
    setVariationError(null);
    const response = await client.saveAsVariation(project.root_id, {
      created_by: createdBy,
      expected_active_asset_id: project.active_asset_id,
      expected_design_version: project.active_design_version,
      label: `Explore ${selected.option.display}`,
      operation_id: operationId,
    });
    setVariationBusy(false);
    if (response.error !== null) {
      setVariationError(response.error.message);
      return;
    }
    variationOperationRef.current = null;
    onVariationCreated?.(response.data.project);
  };

  const quickCatalogs = catalogs.filter((catalog) => QUICK_CATALOGS.has(catalog.component_path));
  const structuralCatalogs = catalogs.filter((catalog) => !QUICK_CATALOGS.has(catalog.component_path));
  const matchingStoneChoices = stoneChoices.filter((stone) => {
    const query = stoneSearch.trim().toLowerCase();
    return query.length === 0
      || stone.id.toLowerCase().includes(query)
      || stone.display.toLowerCase().includes(query);
  });
  const catalogChoices = (catalog: ComponentCatalog) => (
    <View key={catalog.component_path} style={styles.catalogCard}>
      <View style={styles.catalogHeading}>
        <Text style={styles.catalogTitle}>{catalog.display}</Text>
        {catalog.image_agent_status === 'catalog_ready_category_pending' && (
          <Text style={styles.pending}>Coming soon</Text>
        )}
      </View>
      {catalog.image_agent_status === 'catalog_ready_category_pending' && (
        <Text style={styles.pendingCopy}>
          This choice is saved for review, but protected image editing is not released for this category yet.
        </Text>
      )}
      <View style={styles.optionRow}>
        {catalog.options.map((option) => {
          const isSelected = selected?.catalog.component_path === catalog.component_path
            && selected.option.id === option.id;
          const isCurrent = optionIsCurrent(spec, option);
          const swatch = quickSwatch(option.id);
          return (
            <Pressable
              key={option.id}
              accessibilityRole="radio"
              accessibilityState={{ checked: isSelected }}
              onPress={() => {
                if (preview !== null) void client.discardCatalogPreview(preview.candidate);
                setSelected({ catalog, option });
                setPreview(null);
                setPreviewError(null);
                setVariationError(null);
                setChainTarget(null);
              }}
              style={[styles.option, isSelected && styles.optionSelected]}>
              {swatch !== null && <View style={[styles.swatch, { backgroundColor: swatch }]} />}
              <Text style={[styles.optionText, isSelected && styles.optionTextSelected]}>
                {option.display}{isCurrent ? ' · Current' : ''}
              </Text>
            </Pressable>
          );
        })}
      </View>
      {catalog.component_path === 'stone.color' && stonePaletteSpecies !== null && (
        <View style={styles.paletteContext}>
          <Text style={styles.paletteCopy}>
            Palette for {stonePaletteSpecies.replace(/_/g, ' ')}
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ expanded: showStoneChoices }}
            onPress={() => setShowStoneChoices((current) => !current)}>
            <Text style={styles.paletteAction}>
              {showStoneChoices ? 'Hide stone choices' : 'Choose another stone'}
            </Text>
          </Pressable>
          {showStoneChoices && (
            <>
              {showAllStoneChoices && (
                <Field
                  label="Search stones"
                  value={stoneSearch}
                  onChange={setStoneSearch}
                  placeholder="Sapphire, tourmaline, emerald…"
                />
              )}
              <View style={styles.optionRow}>
                {(showAllStoneChoices ? matchingStoneChoices : stoneChoices.slice(0, 7)).map((stone) => (
                  <Pressable
                    key={stone.id}
                    accessibilityRole="radio"
                    accessibilityState={{ checked: stonePaletteSpecies === stone.id }}
                    onPress={() => setStonePaletteSpecies(stone.id)}
                    style={[
                      styles.option,
                      stonePaletteSpecies === stone.id && styles.optionSelected,
                    ]}>
                    <Text style={[
                      styles.optionText,
                      stonePaletteSpecies === stone.id && styles.optionTextSelected,
                    ]}>{stone.display}</Text>
                  </Pressable>
                ))}
              </View>
              {stoneChoices.length > 7 && (
                <Pressable
                  accessibilityRole="button"
                  onPress={() => {
                    setShowAllStoneChoices((current) => !current);
                    setStoneSearch('');
                  }}>
                  <Text style={styles.paletteAction}>
                    {showAllStoneChoices ? 'Show fewer stones' : 'View all stones'}
                  </Text>
                </Pressable>
              )}
            </>
          )}
        </View>
      )}
    </View>
  );

  return (
    <View style={styles.wrap}>
      <Text style={styles.heading}>Quick configuration</Text>
      <Notice
        kind="info"
        text="Choose one exact change. Facetta isolates that visual region, preserves the rest of the piece, and records the image and design facts together."
      />
      {reviewOnly && (
        <Notice
          kind="info"
          text="Mobile supports reviewing catalog choices and their factory impact. Apply is available from the desktop or tablet editing workspace."
        />
      )}
      {loading && <Text style={styles.meta}>Loading applicable component choices…</Text>}
      {loadError !== null && <Notice kind="error" text={loadError} />}
      {!loading && loadError === null && paths.length === 0 && (
        <Notice
          kind="info"
          text="No trusted component catalog is released for this jewelry category yet."
        />
      )}

      {quickCatalogs.length > 0 && (
        <Text style={styles.groupLabel}>Common material and stone changes</Text>
      )}
      {quickCatalogs.map(catalogChoices)}
      {structuralCatalogs.length > 0 && (
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ expanded: showStructuralChoices }}
          onPress={() => setShowStructuralChoices((current) => !current)}
          style={styles.structuralToggle}>
          <View>
            <Text style={styles.structuralTitle}>Shape, setting, and construction</Text>
            <Text style={styles.structuralCopy}>More involved changes that can affect profiles and proportions</Text>
          </View>
          <Text style={styles.structuralIcon}>{showStructuralChoices ? '−' : '+'}</Text>
        </Pressable>
      )}
      {showStructuralChoices && structuralCatalogs.map(catalogChoices)}

      {selected !== null && (
        <View style={styles.selectionCard}>
          <Text style={styles.selectionTitle}>Review {selected.option.display}</Text>
          <Text style={styles.sectionLabel}>Exact record changes</Text>
          {catalogFactoryDelta(spec, selected.option).map((delta) => (
            <View key={delta.path} style={styles.deltaRow}>
              <Text style={styles.deltaPath}>{delta.path}</Text>
              <Text style={styles.deltaValue}>
                {displayValue(delta.before)} → {delta.derived
                  ? 'Recalculated deterministically from the confirmed measurements'
                  : displayValue(delta.after)}
              </Text>
            </View>
          ))}

          <Text style={styles.sectionLabel}>What Facetta will change</Text>
          <Text style={styles.body}>{selected.option.isolation_target}</Text>

          <Text style={styles.sectionLabel}>How it should look</Text>
          {selected.option.visual_geometry.map((fact) => (
            <Text key={fact} style={styles.bullet}>• {fact}</Text>
          ))}

          <Text style={styles.sectionLabel}>What stays fixed</Text>
          <Text style={styles.body}>{selected.option.frozen_facts.join(', ')}</Text>

          <Text style={styles.sectionLabel}>Before applying</Text>
          {selected.option.selection_requirements.length === 0 ? (
            <Text style={styles.body}>No additional prerequisite beyond the current confirmed specification.</Text>
          ) : selected.option.selection_requirements.map((requirement) => (
            <Text key={requirement} style={styles.bullet}>• {requirement}</Text>
          ))}

          {selected.catalog.component_path === 'chain.style' && !selectionCurrent && (
            <ChainTargetEditor style={selected.option.id} onChange={setChainTarget} />
          )}

          {selectionCurrent && (
            <Notice
              kind="info"
              text="This is already the exact active factory selection, so no new revision is needed."
            />
          )}
          {categoryPending && (
            <Notice
              kind="info"
              text="This component is cataloged, but trusted category-specific image editing is not released yet. Apply remains disabled."
            />
          )}
          <Button
            title={previewBusy ? 'Creating protected preview…' : 'Preview protected change'}
            disabled={!canPreview}
            onPress={() => { void previewSelection(); }}
          />
          <Button
            title={variationBusy ? 'Saving variation…' : 'Save as variation first'}
            kind="ghost"
            disabled={reviewOnly || variationBusy || project.active_asset_id === null}
            onPress={() => { void saveAsVariation(); }}
          />
          {variationError !== null && <Notice kind="error" text={variationError} />}
        </View>
      )}

      {previewError !== null && <Notice kind="error" text={previewError} />}
      {preview !== null && (
        <View style={styles.warningCard}>
          <Notice
            kind={preview.candidate.verdict === 'pass' ? 'ok' : 'info'}
            text={preview.candidate.verdict === 'pass'
              ? 'Preview checks passed. Nothing has changed yet.'
              : 'This preview needs your review. It has not changed the active image or design record.'}
          />
          <Image
            source={{ uri: preview.candidate.preview_url }}
            accessibilityLabel="Temporary catalog preview"
            resizeMode="contain"
            style={styles.preview}
          />
          <Text style={styles.body}>{preview.qa.summary}</Text>
          <Text style={styles.meta}>Temporary preview · expires automatically · no revision created</Text>
          <View style={styles.reviewActions}>
            <Button
              title={acceptBusy ? 'Applying exact preview…' : 'Apply to this variation'}
              disabled={acceptBusy || previewBusy}
              onPress={() => { void acceptPreview(); }}
            />
            <Button
              title="Discard preview"
              kind="ghost"
              disabled={acceptBusy || previewBusy}
              onPress={() => { void discardPreview(); }}
            />
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginTop: 8 },
  heading: {
    color: theme.ink,
    fontFamily: theme.serif,
    fontSize: 15,
    marginBottom: 8,
  },
  meta: { color: theme.faint, fontSize: 12, marginBottom: 8 },
  groupLabel: {
    color: theme.accent,
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
    marginBottom: 7,
  },
  catalogCard: {
    borderColor: theme.line,
    borderWidth: 1,
    borderRadius: 12,
    padding: 10,
    marginBottom: 10,
    backgroundColor: theme.paper,
  },
  catalogHeading: { flexDirection: 'row', justifyContent: 'space-between', gap: 8 },
  catalogTitle: { color: theme.ink, fontSize: 14, fontWeight: '600' },
  pending: { color: theme.accent, fontSize: 11, fontWeight: '700' },
  pendingCopy: { color: theme.faint, fontSize: 12, lineHeight: 17, marginTop: 6 },
  optionRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 8 },
  option: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: 14,
    paddingHorizontal: 10,
    paddingVertical: 6,
    backgroundColor: theme.paper,
    flexDirection: 'row',
    alignItems: 'center',
  },
  optionSelected: { borderColor: theme.ink, backgroundColor: theme.ink },
  optionText: { color: theme.ink, fontSize: 12 },
  optionTextSelected: { color: theme.paper },
  swatch: { width: 12, height: 12, borderRadius: 999, marginRight: 6, borderWidth: 1, borderColor: theme.line },
  paletteContext: { marginTop: 10, borderTopWidth: 1, borderTopColor: theme.line, paddingTop: 8 },
  paletteCopy: { color: theme.faint, fontSize: 11, marginBottom: 5 },
  paletteAction: { color: theme.accent, fontSize: 12, fontWeight: '700', marginTop: 5 },
  structuralToggle: {
    borderColor: theme.line,
    borderWidth: 1,
    borderRadius: 12,
    padding: 11,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 10,
    backgroundColor: theme.paper,
  },
  structuralTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  structuralCopy: { color: theme.faint, fontSize: 11, marginTop: 3 },
  structuralIcon: { color: theme.accent, fontSize: 20, lineHeight: 20 },
  selectionCard: {
    borderColor: theme.gold,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginBottom: 10,
    backgroundColor: theme.blush,
  },
  selectionTitle: { color: theme.ink, fontSize: 15, fontWeight: '600' },
  sectionLabel: {
    color: theme.accent,
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 0.4,
    marginTop: 10,
    marginBottom: 3,
    textTransform: 'uppercase',
  },
  deltaRow: { borderBottomColor: theme.line, borderBottomWidth: 1, paddingVertical: 5 },
  deltaPath: { color: theme.ink, fontSize: 12, fontWeight: '600' },
  deltaValue: { color: theme.ink, fontSize: 12, lineHeight: 17, marginTop: 2 },
  body: { color: theme.ink, fontSize: 12, lineHeight: 18 },
  bullet: { color: theme.ink, fontSize: 12, lineHeight: 18, paddingLeft: 2 },
  confirm: {
    borderColor: theme.ink,
    borderWidth: 1,
    borderRadius: 10,
    padding: 9,
    marginTop: 12,
    marginBottom: 8,
    backgroundColor: theme.paper,
  },
  confirmChecked: { backgroundColor: theme.ink },
  confirmText: { color: theme.ink, fontSize: 12 },
  confirmTextChecked: { color: theme.paper },
  disabled: { opacity: 0.4 },
  warningCard: { marginTop: 4 },
  reviewActions: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 8 },
  preview: { width: '100%', height: 240, backgroundColor: theme.paper, marginBottom: 8 },
});
