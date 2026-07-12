import React, { useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';

import { ChipRow, Notice } from '../components';
import { theme } from '../theme';
import { componentCatalogPathsForSpec } from './ComponentCatalogPanel';
import type { TrustedApiClient } from './client';
import type {
  ComponentCatalog,
  ComponentCatalogOption,
  ComponentCatalogPath,
  JsonObject,
  JsonValue,
  StoneVocabularyEntry,
  StoneVocabularyOptions,
} from './types';

export type MeasurementBasis = 'designer_confirmed' | 'estimated_from_reference';

const PATH_TOKEN = /([^[.\]]+)|\[(\d+)\]/g;

const pathTokens = (path: string): Array<string | number> => {
  const tokens: Array<string | number> = [];
  for (const match of path.matchAll(PATH_TOKEN)) {
    tokens.push(match[2] === undefined ? match[1]! : Number(match[2]));
  }
  return tokens;
};

const cloneObject = (value: JsonObject): JsonObject =>
  JSON.parse(JSON.stringify(value)) as JsonObject;

const objectValue = (value: JsonValue | undefined): JsonObject | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value : null;

const valueAtPath = (spec: JsonObject, path: string): JsonValue | undefined => {
  let current: JsonValue = spec;
  for (const token of pathTokens(path)) {
    if (typeof token === 'number') {
      if (!Array.isArray(current)) return undefined;
      current = current[token] as JsonValue;
    } else {
      const record = objectValue(current);
      if (record === null) return undefined;
      current = record[token] as JsonValue;
    }
    if (current === undefined) return undefined;
  }
  return current;
};

const sameJsonValue = (
  left: JsonValue | undefined,
  right: JsonValue,
): boolean => (right === null && left === undefined)
  || left !== undefined && JSON.stringify(left) === JSON.stringify(right);

const optionIsCurrent = (
  spec: JsonObject,
  option: ComponentCatalogOption,
): boolean => {
  const fields = Object.entries(option.factory_fields);
  return fields.length > 0 && fields.every(([path, value]) => (
    sameJsonValue(valueAtPath(spec, path), value)
  ));
};

const setAtPath = (spec: JsonObject, path: string, value: JsonValue): void => {
  const tokens = pathTokens(path);
  let current: JsonValue = spec;
  tokens.forEach((token, index) => {
    const final = index === tokens.length - 1;
    if (typeof token === 'number') {
      if (!Array.isArray(current)) throw new Error(`invalid array path: ${path}`);
      if (final) {
        current[token] = value;
        return;
      }
      current = current[token] as JsonValue;
      return;
    }
    const record = objectValue(current);
    if (record === null) throw new Error(`invalid object path: ${path}`);
    if (final) {
      record[token] = value;
      return;
    }
    current = record[token] as JsonValue;
  });
};

export const isFactoryDimensionPath = (path: string): boolean => {
  const leaf = path.split('.').at(-1) ?? '';
  return path.includes('dimensions_mm.')
    || leaf.endsWith('_mm')
    || path === 'ring_size.value';
};

/** Apply one typed fact while preserving every unrelated/unknown spec field. */
export function applyFactoryFactChange(
  spec: JsonObject,
  path: string,
  value: JsonValue,
  basis: MeasurementBasis = 'designer_confirmed',
): JsonObject {
  const next = cloneObject(spec);
  setAtPath(next, path, value);
  if (!isFactoryDimensionPath(path)) return next;

  const existing = objectValue(next.dimension_provenance);
  const provenance: JsonObject = existing === null ? {} : { ...existing };
  provenance[path] = basis === 'designer_confirmed'
    ? {
        status: 'designer_confirmed',
        method: 'designer_input',
        source: 'trusted factory-fact editor',
        confidence: 1,
        note: 'Designer supplied or measured this value.',
      }
    : {
        status: 'estimated_from_reference',
        method: 'nominal_reference',
        source: 'designer-confirmed reference estimate',
        confidence: null,
        note: 'Prototype estimate; verify before manufacturing.',
      };
  next.dimension_provenance = provenance;
  return next;
}

function StringFact({
  label,
  path,
  spec,
  onChange,
  basis,
}: {
  label: string;
  path: string;
  spec: JsonObject;
  onChange: (spec: JsonObject) => void;
  basis: MeasurementBasis;
}) {
  const value = valueAtPath(spec, path);
  if (typeof value !== 'string' && value !== null) return null;
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        style={styles.input}
        value={value ?? ''}
        onChangeText={(next) => onChange(
          applyFactoryFactChange(spec, path, next, basis),
        )}
      />
    </View>
  );
}

function NumericFact({
  label,
  path,
  spec,
  onChange,
  basis,
  integer = false,
}: {
  label: string;
  path: string;
  spec: JsonObject;
  onChange: (spec: JsonObject) => void;
  basis: MeasurementBasis;
  integer?: boolean;
}) {
  const value = valueAtPath(spec, path);
  const [draft, setDraft] = useState(
    typeof value === 'number' ? String(value) : '',
  );
  useEffect(() => {
    setDraft(typeof value === 'number' ? String(value) : '');
  }, [value]);
  if (typeof value !== 'number' && value !== null) return null;
  const commit = (): void => {
    const parsed = Number(draft);
    if (!Number.isFinite(parsed) || integer && !Number.isInteger(parsed)) {
      setDraft(typeof value === 'number' ? String(value) : '');
      return;
    }
    onChange(applyFactoryFactChange(spec, path, parsed, basis));
  };
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        style={styles.input}
        value={draft}
        onChangeText={setDraft}
        onBlur={commit}
        onSubmitEditing={commit}
        keyboardType="decimal-pad"
      />
    </View>
  );
}

function ScalarFact({
  label,
  path,
  spec,
  onChange,
  basis,
}: {
  label: string;
  path: string;
  spec: JsonObject;
  onChange: (spec: JsonObject) => void;
  basis: MeasurementBasis;
}) {
  const value = valueAtPath(spec, path);
  const [draft, setDraft] = useState(
    typeof value === 'string' || typeof value === 'number' ? String(value) : '',
  );
  useEffect(() => {
    setDraft(
      typeof value === 'string' || typeof value === 'number' ? String(value) : '',
    );
  }, [value]);
  if (typeof value !== 'string' && typeof value !== 'number' && value !== null) {
    return null;
  }
  const commit = (): void => {
    if (!draft.trim()) return;
    const numeric = Number(draft);
    const next: JsonValue = Number.isFinite(numeric) ? numeric : draft.trim();
    onChange(applyFactoryFactChange(spec, path, next, basis));
  };
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        style={styles.input}
        value={draft}
        onChangeText={setDraft}
        onBlur={commit}
        onSubmitEditing={commit}
      />
    </View>
  );
}

function FactGrid({ children }: { children: React.ReactNode }) {
  return <View style={styles.grid}>{children}</View>;
}

export function FactoryFactEditor({
  spec,
  onChange,
  client,
}: {
  spec: JsonObject;
  onChange: (spec: JsonObject) => void;
  client?: TrustedApiClient;
}) {
  const [basis, setBasis] = useState<MeasurementBasis>('designer_confirmed');
  const catalogClient = client !== undefined
    && typeof client.getComponentCatalog === 'function'
    && typeof client.selectDraftCatalogOption === 'function'
    ? client : null;
  const stoneClient = client !== undefined
    && typeof client.getStoneVocabulary === 'function'
    && typeof client.getStoneVocabularyOptions === 'function'
    && typeof client.selectDraftStone === 'function'
    ? client : null;
  const catalogPaths = useMemo(
    () => componentCatalogPathsForSpec(spec),
    [spec.jewelry_type],
  );
  const catalogPathKey = catalogPaths.join('|');
  const [catalogs, setCatalogs] = useState<ComponentCatalog[]>([]);
  const [catalogBusy, setCatalogBusy] = useState<ComponentCatalogPath | 'load' | null>(
    null,
  );
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const currentSpecies = valueAtPath(spec, 'stone.species');
  const currentTradeColor = valueAtPath(spec, 'stone.color.trade');
  const [stoneEntries, setStoneEntries] = useState<StoneVocabularyEntry[]>([]);
  const [stoneOptions, setStoneOptions] = useState<StoneVocabularyOptions | null>(null);
  const [targetSpecies, setTargetSpecies] = useState(
    typeof currentSpecies === 'string' ? currentSpecies : '',
  );
  const [stoneBusy, setStoneBusy] = useState(false);
  const [stoneError, setStoneError] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    setCatalogs([]);
    setCatalogError(null);
    if (catalogClient === null || catalogPaths.length === 0) return () => {
      active = false;
    };
    setCatalogBusy('load');
    void Promise.all(catalogPaths.map((path) => (
      catalogClient.getComponentCatalog(path)
    )))
      .then((results) => {
        if (!active) return;
        const failed = results.find((result) => result.error !== null);
        if (failed?.error !== null && failed?.error !== undefined) {
          setCatalogError(failed.error.message);
          return;
        }
        const loaded = results.flatMap((result) => result.data === null
          ? [] : [result.data]);
        if (loaded.length !== catalogPaths.length) {
          setCatalogError('Controlled factory choices could not be loaded completely.');
          return;
        }
        setCatalogs(loaded);
      })
      .catch(() => {
        if (active) setCatalogError('Controlled factory choices are temporarily unavailable.');
      })
      .finally(() => {
        if (active) setCatalogBusy(null);
      });
    return () => {
      active = false;
    };
    // The catalog content depends on category, not mutable draft values.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalogClient, catalogPathKey]);

  useEffect(() => {
    let active = true;
    if (stoneClient === null || typeof currentSpecies !== 'string') return () => {
      active = false;
    };
    setStoneBusy(true);
    setStoneError(null);
    setTargetSpecies(currentSpecies);
    void Promise.all([
      stoneClient.getStoneVocabulary(),
      stoneClient.getStoneVocabularyOptions(currentSpecies),
    ]).then(([entriesResult, optionsResult]) => {
      if (!active) return;
      if (entriesResult.error !== null || optionsResult.error !== null) {
        setStoneError(
          entriesResult.error?.message
          ?? optionsResult.error?.message
          ?? 'Gemstone choices could not be loaded.',
        );
        return;
      }
      setStoneEntries(entriesResult.data.filter(
        (entry) => entry.parameter_set === 'gemstone',
      ));
      setStoneOptions(optionsResult.data);
    }).catch(() => {
      if (active) setStoneError('Gemstone choices are temporarily unavailable.');
    }).finally(() => {
      if (active) setStoneBusy(false);
    });
    return () => {
      active = false;
    };
  }, [stoneClient, currentSpecies]);

  const chooseSpecies = async (species: string): Promise<void> => {
    if (stoneClient === null || species === targetSpecies) return;
    setTargetSpecies(species);
    setStoneOptions(null);
    setStoneBusy(true);
    setStoneError(null);
    const result = await stoneClient.getStoneVocabularyOptions(species);
    setStoneBusy(false);
    if (result.error !== null) {
      setStoneError(result.error.message);
      return;
    }
    setStoneOptions(result.data);
  };

  const chooseTradeColor = async (tradeColor: string): Promise<void> => {
    if (stoneClient === null || !targetSpecies) return;
    if (targetSpecies === currentSpecies && tradeColor === currentTradeColor) return;
    setStoneBusy(true);
    setStoneError(null);
    const result = await stoneClient.selectDraftStone({
      spec,
      species: targetSpecies,
      trade_color: tradeColor,
    });
    setStoneBusy(false);
    if (result.error !== null) {
      setStoneError(result.error.message);
      return;
    }
    onChange(result.data.spec);
  };

  const selectCatalogOption = async (
    catalog: ComponentCatalog,
    option: ComponentCatalogOption,
  ): Promise<void> => {
    if (catalogClient === null || optionIsCurrent(spec, option)) return;
    setCatalogBusy(catalog.component_path);
    setCatalogError(null);
    const result = await catalogClient.selectDraftCatalogOption({
      spec,
      component_path: catalog.component_path,
      option_id: option.id,
    });
    setCatalogBusy(null);
    if (result.error !== null) {
      setCatalogError(result.error.message);
      return;
    }
    onChange(result.data.spec);
  };
  const sideStones = Array.isArray(spec.side_stones) ? spec.side_stones : [];
  const jewelryType = typeof spec.jewelry_type === 'string'
    ? spec.jewelry_type : 'jewelry';
  const fieldProps = { spec, onChange, basis };

  return (
    <View style={styles.wrap}>
      <Text style={styles.heading}>Factory facts</Text>
      <Text style={styles.copy}>
        Confirm the physical record, not merely what looks plausible in the image.
        Every change makes the previous source audit stale until it is re-run.
      </Text>
      <Notice
        kind="info"
        text={`Category: ${jewelryType.replace(/_/g, ' ')}. Dimensions use the basis selected below.`}
      />
      <ChipRow
        label="Dimension basis"
        options={['designer_confirmed', 'estimated_from_reference'] as const}
        value={basis}
        onSelect={setBasis}
        render={(item) => item === 'designer_confirmed'
          ? 'Measured / supplied'
          : 'Reference estimate'}
      />

      {stoneClient !== null && (
        <View style={styles.catalogWrap}>
          <Text style={styles.groupHeading}>Controlled gemstone identity</Text>
          <Text style={styles.copy}>
            Species and trade color come from Facetta’s gemology vocabulary.
            Changing species clears incompatible grading/origin claims and
            recalculates modeled carat at the unchanged dimensions.
          </Text>
          {stoneError !== null && <Notice kind="error" text={stoneError} />}
          <ChipRow
            label="Center gemstone species"
            options={stoneEntries.map((entry) => entry.id)}
            value={targetSpecies || null}
            disabled={stoneBusy}
            disabledNote={stoneBusy ? 'Loading valid colors…' : undefined}
            onSelect={(species) => void chooseSpecies(species)}
            render={(species) => stoneEntries.find(
              (entry) => entry.id === species,
            )?.display ?? species}
          />
          {stoneOptions !== null && stoneOptions.stone === targetSpecies && (
            <ChipRow
              label="Controlled trade color"
              options={stoneOptions.colors.map((color) => color.term)}
              value={targetSpecies === currentSpecies
                && typeof currentTradeColor === 'string'
                ? currentTradeColor : null}
              disabled={stoneBusy}
              disabledNote={stoneBusy ? 'Applying stone facts…' : undefined}
              onSelect={(tradeColor) => void chooseTradeColor(tradeColor)}
            />
          )}
        </View>
      )}

      {catalogClient !== null && catalogPaths.length > 0 && (
        <View style={styles.catalogWrap}>
          <Text style={styles.groupHeading}>Controlled component choices</Text>
          <Text style={styles.copy}>
            These options apply coupled jewelry facts together—for example,
            platinum clears gold karat/color and a bezel clears prong fields.
          </Text>
          {catalogBusy === 'load' && (
            <Text style={styles.copy}>Loading valid choices…</Text>
          )}
          {catalogError !== null && <Notice kind="error" text={catalogError} />}
          {catalogs.map((catalog) => {
            const current = catalog.options.find((option) => optionIsCurrent(spec, option));
            return (
              <View key={catalog.component_path}>
                <ChipRow
                  label={catalog.display}
                  options={catalog.options.map((option) => option.id)}
                  value={current?.id ?? null}
                  disabled={catalogBusy !== null}
                  disabledNote={catalogBusy === catalog.component_path
                    ? 'Applying coupled facts…' : undefined}
                  onSelect={(optionId) => {
                    const option = catalog.options.find((item) => item.id === optionId);
                    if (option !== undefined) {
                      void selectCatalogOption(catalog, option);
                    }
                  }}
                  render={(optionId) => catalog.options.find(
                    (option) => option.id === optionId,
                  )?.display ?? optionId}
                />
              </View>
            );
          })}
        </View>
      )}

      <Text style={styles.groupHeading}>Center stone</Text>
      <FactGrid>
        {stoneClient === null && (
          <StringFact label="Center species" path="stone.species" {...fieldProps} />
        )}
        {(catalogClient === null || !catalogPaths.includes('stone.cut')) && (
          <StringFact label="Cut / shape" path="stone.cut" {...fieldProps} />
        )}
        <NumericFact label="Quantity" path="stone.count" integer {...fieldProps} />
        <NumericFact label="Carat each" path="stone.carat" {...fieldProps} />
        <NumericFact label="Length (mm)" path="stone.dimensions_mm.length" {...fieldProps} />
        <NumericFact label="Width (mm)" path="stone.dimensions_mm.width" {...fieldProps} />
        <NumericFact label="Depth (mm)" path="stone.dimensions_mm.depth" {...fieldProps} />
      </FactGrid>

      {sideStones.map((stone, index) => objectValue(stone) === null ? null : (
        <View key={`side:${index}`}>
          <Text style={styles.groupHeading}>Stone group {index + 1}</Text>
          <FactGrid>
            <StringFact label={`Group ${index + 1} species`} path={`side_stones[${index}].species`} {...fieldProps} />
            <StringFact label={`Group ${index + 1} cut / shape`} path={`side_stones[${index}].cut`} {...fieldProps} />
            <StringFact label={`Group ${index + 1} position / role`} path={`side_stones[${index}].position`} {...fieldProps} />
            <NumericFact label="Quantity" path={`side_stones[${index}].count`} integer {...fieldProps} />
            <NumericFact label="Carat each" path={`side_stones[${index}].carat`} {...fieldProps} />
            <NumericFact label="Length (mm)" path={`side_stones[${index}].dimensions_mm.length`} {...fieldProps} />
            <NumericFact label="Width (mm)" path={`side_stones[${index}].dimensions_mm.width`} {...fieldProps} />
            <NumericFact label="Depth (mm)" path={`side_stones[${index}].dimensions_mm.depth`} {...fieldProps} />
          </FactGrid>
        </View>
      ))}

      <Text style={styles.groupHeading}>Metal and setting</Text>
      <FactGrid>
        {(catalogClient === null || !catalogPaths.includes('metal.material')) && (
          <StringFact label="Metal material" path="metal.material" {...fieldProps} />
        )}
        {(catalogClient === null || !catalogPaths.includes('metal.material')) && (
          <NumericFact label="Gold karat" path="metal.karat" integer {...fieldProps} />
        )}
        {(catalogClient === null || !catalogPaths.includes('metal.color')) && (
          <StringFact label="Metal color" path="metal.color" {...fieldProps} />
        )}
        <StringFact label="Finish" path="metal.finish" {...fieldProps} />
        {(catalogClient === null || !catalogPaths.includes('setting.style')) && (
          <StringFact label="Setting style" path="setting.style" {...fieldProps} />
        )}
        {(catalogClient === null || !catalogPaths.includes('setting.style')) && (
          <NumericFact label="Center prongs" path="setting.prong_count" integer {...fieldProps} />
        )}
        <NumericFact label="Gallery height (mm)" path="setting.gallery_height_mm" {...fieldProps} />
      </FactGrid>

      {jewelryType === 'ring' && (
        <>
          <Text style={styles.groupHeading}>Ring construction</Text>
          <FactGrid>
            <StringFact label="Band profile" path="band.profile" {...fieldProps} />
            <NumericFact label="Band width (mm)" path="band.width_mm" {...fieldProps} />
            <NumericFact label="Band thickness (mm)" path="band.thickness_mm" {...fieldProps} />
            <StringFact label="Ring size system" path="ring_size.system" {...fieldProps} />
            <ScalarFact label="Ring size" path="ring_size.value" {...fieldProps} />
          </FactGrid>
        </>
      )}

      {jewelryType === 'necklace' && (
        <>
          <Text style={styles.groupHeading}>Necklace construction</Text>
          <FactGrid>
            {(catalogClient === null || !catalogPaths.includes('chain.style')) && (
              <StringFact label="Chain style" path="chain.style" {...fieldProps} />
            )}
            <NumericFact label="Chain length (mm)" path="chain.length_mm" {...fieldProps} />
            <StringFact label="Clasp" path="chain.clasp" {...fieldProps} />
            <NumericFact label="Bail opening (mm)" path="pendant.bail_inner_diameter_mm" {...fieldProps} />
            <NumericFact label="Bail height (mm)" path="pendant.bail_height_mm" {...fieldProps} />
            <NumericFact label="Pendant drop (mm)" path="pendant.drop_mm" {...fieldProps} />
          </FactGrid>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
    backgroundColor: theme.paper,
  },
  heading: {
    color: theme.ink,
    fontFamily: theme.serif,
    fontSize: 17,
    marginBottom: 4,
  },
  copy: { color: theme.faint, fontSize: 12, lineHeight: 18, marginBottom: 10 },
  groupHeading: {
    color: theme.ink,
    fontSize: 13,
    fontWeight: '600',
    marginTop: 8,
    marginBottom: 6,
  },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  catalogWrap: {
    borderTopWidth: 1,
    borderTopColor: theme.line,
    marginTop: 4,
    paddingTop: 6,
  },
  field: { minWidth: 145, flexGrow: 1, flexBasis: '30%', marginBottom: 10 },
  label: { fontSize: 12, color: theme.faint, marginBottom: 4 },
  input: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 6,
    fontSize: 14,
    color: theme.ink,
    backgroundColor: theme.card,
  },
});
