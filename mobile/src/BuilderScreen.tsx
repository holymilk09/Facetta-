import React, { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Api } from './api';
import { Button, ChipRow, Field, Notice, Section } from './components';
import { SheetView } from './SheetView';
import { theme } from './theme';

const SETTING_STYLES = ['4_prong_basket', '6_prong_basket'] as const;
const METALS = ['gold', 'platinum', 'silver'] as const;
const KARATS = [9, 14, 18, 22] as const;
const METAL_COLORS = ['yellow', 'white', 'rose'] as const;
const FINISHES = ['high_polish', 'satin', 'matte'] as const;
const BAND_PROFILES = ['half_round', 'flat', 'knife_edge'] as const;

// typical length/width and depth/width proportions per cut, used to derive
// plausible mm from carat in Basic mode (carat = L*W*D*SG*factor/200)
const CUT_RATIOS: Record<string, { lw: number; dw: number }> = {
  round_brilliant: { lw: 1.0, dw: 0.61 },
  oval_brilliant: { lw: 1.35, dw: 0.64 },
  pear: { lw: 1.5, dw: 0.62 },
  marquise: { lw: 1.9, dw: 0.6 },
  princess: { lw: 1.0, dw: 0.7 },
  cushion: { lw: 1.1, dw: 0.66 },
  emerald_cut: { lw: 1.4, dw: 0.65 },
};

export interface EditingTarget {
  designId: string;
  version: number;
}

export function BuilderScreen({
  api,
  designer,
  editing,
  initialSpec,
  onSaved,
}: {
  api: Api;
  designer: string;
  editing: EditingTarget | null;
  initialSpec: any | null;
  onSaved: (designId: string) => void;
}) {
  const [stones, setStones] = useState<any[]>([]);
  const [species, setSpecies] = useState<string | null>(null);
  const [options, setOptions] = useState<any | null>(null);
  const [mode, setMode] = useState<'basic' | 'pro'>('basic');

  const [cut, setCut] = useState<string | null>(null);
  const [trade, setTrade] = useState<string | null>(null);
  const [claritySystem, setClaritySystem] = useState<string | null>(null);
  const [grade, setGrade] = useState<string | null>(null);
  const [carat, setCarat] = useState('1.0');
  const [dims, setDims] = useState({ length: '', width: '', depth: '' });
  const [origin, setOrigin] = useState('');

  const [settingStyle, setSettingStyle] = useState<string>('4_prong_basket');
  const [prongTip, setProngTip] = useState('0.9');
  const [gallery, setGallery] = useState('4.5');
  const [metal, setMetal] = useState<string>('gold');
  const [karat, setKarat] = useState<number>(18);
  const [metalColor, setMetalColor] = useState<string>('yellow');
  const [finish, setFinish] = useState<string>('high_polish');
  const [bandProfile, setBandProfile] = useState<string>('half_round');
  const [bandWidth, setBandWidth] = useState('1.8');
  const [bandThickness, setBandThickness] = useState('1.6');
  const [ringSize, setRingSize] = useState('6.5');
  const [notes, setNotes] = useState('');
  const [prose, setProse] = useState('');

  const [notice, setNotice] = useState<{ kind: 'ok' | 'error' | 'info'; text: string } | null>(null);
  const [issues, setIssues] = useState<any[]>([]);
  const [sheetSvg, setSheetSvg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.stones().then((r) => r.ok && setStones(r.body.stones));
  }, [api.baseUrl]);

  useEffect(() => {
    if (initialSpec) applySpec(initialSpec);
  }, [initialSpec]);

  const selectSpecies = async (id: string) => {
    setSpecies(id);
    setOptions(null);
    setTrade(null);
    setGrade(null);
    const r = await api.stoneOptions(id);
    if (!r.ok) return;
    if (r.body.parameter_set !== 'gemstone') {
      setNotice({
        kind: 'info',
        text: `${r.body.display} uses its own parameter set (${r.body.parameter_set}) — builder support coming with its template.`,
      });
      setOptions(null);
      return;
    }
    setOptions(r.body);
    setClaritySystem(r.body.clarity.systems[0]);
    if (!cut || !r.body.cuts.some((c: any) => c.id === cut)) setCut('round_brilliant');
  };

  const applySpec = async (spec: any) => {
    await selectSpecies(spec.stone.species);
    setMode(spec.mode ?? 'pro');
    setCut(spec.stone.cut);
    setTrade(spec.stone.color.trade);
    setClaritySystem(spec.stone.clarity.system);
    setGrade(spec.stone.clarity.grade);
    setCarat(String(spec.stone.carat));
    setDims({
      length: String(spec.stone.dimensions_mm.length),
      width: String(spec.stone.dimensions_mm.width),
      depth: String(spec.stone.dimensions_mm.depth),
    });
    setOrigin(spec.stone.origin ?? '');
    setSettingStyle(spec.setting.style);
    setProngTip(String(spec.setting.prong_tip_mm ?? 0.9));
    setGallery(String(spec.setting.gallery_height_mm ?? 4.5));
    setMetal(spec.metal.material);
    setKarat(spec.metal.karat ?? 18);
    setMetalColor(spec.metal.color ?? 'yellow');
    setFinish(spec.metal.finish ?? 'high_polish');
    if (spec.band) {
      setBandProfile(spec.band.profile);
      setBandWidth(String(spec.band.width_mm));
      setBandThickness(String(spec.band.thickness_mm));
    }
    if (spec.ring_size) setRingSize(String(spec.ring_size.value));
    setNotes(spec.notes_to_factory ?? '');
  };

  const deriveDims = (): { length: number; width: number; depth: number } | null => {
    if (!options || !cut) return null;
    const cutInfo = options.cuts.find((c: any) => c.id === cut);
    const ratios = CUT_RATIOS[cut] ?? { lw: 1.3, dw: 0.64 };
    const ct = parseFloat(carat);
    if (!cutInfo || !ct) return null;
    const width = Math.cbrt((200 * ct) / (ratios.lw * ratios.dw * options.sg * cutInfo.shape_factor));
    const round = (v: number) => Math.round(v * 10) / 10;
    return { length: round(width * ratios.lw), width: round(width), depth: round(width * ratios.dw) };
  };

  const buildSpec = () => {
    const dimensions =
      mode === 'pro' && dims.length && dims.width && dims.depth
        ? {
            length: parseFloat(dims.length),
            width: parseFloat(dims.width),
            depth: parseFloat(dims.depth),
          }
        : deriveDims();
    return {
      schema_version: 1,
      design_id: editing?.designId ?? 'dsn_pending',
      version: 1,
      created_by: designer,
      created_at: new Date().toISOString(),
      jewelry_type: 'ring',
      template: 'solitaire_prong',
      mode,
      stone: {
        species,
        cut,
        carat: parseFloat(carat),
        dimensions_mm: dimensions,
        color: {
          trade,
          gia: options?.colors.find((c: any) => c.term === trade)?.gia ?? '',
        },
        clarity: { system: claritySystem, grade },
        origin: mode === 'pro' && origin ? origin : null,
        phenomena: [],
      },
      setting: {
        style: settingStyle,
        prong_count: settingStyle.startsWith('6') ? 6 : 4,
        prong_tip_mm: parseFloat(prongTip),
        gallery_height_mm: parseFloat(gallery),
      },
      metal: {
        material: metal,
        karat: metal === 'gold' ? karat : null,
        color: metal === 'gold' ? metalColor : 'white',
        finish,
      },
      band: {
        profile: bandProfile,
        width_mm: parseFloat(bandWidth),
        thickness_mm: parseFloat(bandThickness),
      },
      ring_size: { system: 'US', value: parseFloat(ringSize) },
      side_stones: [],
      notes_to_factory: notes || null,
    };
  };

  const showIssues = (body: any) => {
    const detail = body?.detail;
    if (Array.isArray(detail)) {
      setIssues(detail);
      setNotice({ kind: 'error', text: `${detail.length} issue(s) — see below` });
    } else {
      setIssues([]);
      setNotice({ kind: 'error', text: String(detail ?? 'request failed') });
    }
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setNotice(null);
    setIssues([]);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const validate = () =>
    run(async () => {
      const r = await api.validateSpec(buildSpec());
      if (r.ok) {
        setNotice({ kind: 'ok', text: 'Spec is valid — physically possible and fully in vocabulary.' });
        const inner = r.body?.ring_size?.inner_diameter_mm;
        if (inner) setNotice({ kind: 'ok', text: `Spec is valid. Inner diameter ${inner} mm derived from US ${ringSize}.` });
      } else showIssues(r.body);
    });

  const preview = () =>
    run(async () => {
      const r = await api.sheetPreview(buildSpec());
      if (r.ok) {
        setSheetSvg(r.body);
        setNotice({ kind: 'ok', text: 'Sheet rendered from the validated spec.' });
      } else showIssues(r.body);
    });

  const save = () =>
    run(async () => {
      const spec = buildSpec();
      const r = editing
        ? await api.createVersion(editing.designId, designer, spec)
        : await api.createDesign(designer, spec);
      if (r.ok) {
        setNotice({
          kind: 'ok',
          text: `Saved ${r.body.design_id} v${r.body.version} (immutable).`,
        });
        onSaved(r.body.design_id);
      } else showIssues(r.body);
    });

  const compileProse = () =>
    run(async () => {
      const r = await api.fromProse(prose, designer);
      if (r.ok) {
        await applySpec(r.body);
        setNotice({ kind: 'ok', text: 'Prose compiled into a validated spec — review and save.' });
      } else showIssues(r.body);
    });

  const gemstoneStones = stones.filter((s) => s.parameter_set === 'gemstone');
  const organicStones = stones.filter((s) => s.parameter_set !== 'gemstone');

  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
      {editing && (
        <Notice kind="info" text={`Editing ${editing.designId} — saving creates version ${editing.version + 1} (v${editing.version} stays untouched).`} />
      )}

      <Section title="Stone">
        <ChipRow
          label="Species"
          options={gemstoneStones.map((s) => s.id)}
          value={species}
          onSelect={selectSpecies}
          render={(id) => gemstoneStones.find((s) => s.id === id)?.display ?? id}
        />
        {organicStones.length > 0 && (
          <Text style={styles.hint}>
            {organicStones.map((s) => s.display).join(' and ')} carry their own parameter sets — coming with their templates.
          </Text>
        )}
        {options && (
          <>
            <ChipRow
              label="Cut"
              options={options.cuts.map((c: any) => c.id)}
              value={cut}
              onSelect={setCut}
              render={(id) => options.cuts.find((c: any) => c.id === id)?.name ?? id}
            />
            {options.colors.length > 0 ? (
              <ChipRow
                label="Color (trade term — GIA translation stored alongside)"
                options={options.colors.map((c: any) => c.term)}
                value={trade}
                onSelect={setTrade}
              />
            ) : (
              <Field label="Color (GIA description)" value={trade ?? ''} onChange={setTrade} />
            )}
            <ChipRow
              label={`Clarity (${claritySystem ?? ''})`}
              options={(options.clarity.grades[claritySystem ?? ''] ?? []).map((g: any) => g.grade)}
              value={grade}
              onSelect={setGrade}
            />
            {options.clarity.systems.length > 1 && (
              <ChipRow
                label="Clarity system"
                options={options.clarity.systems}
                value={claritySystem}
                onSelect={(s) => {
                  setClaritySystem(s);
                  setGrade(null);
                }}
              />
            )}
            <Field label="Carat" value={carat} onChange={setCarat} numeric />
            {mode === 'pro' && (
              <>
                <View style={styles.row}>
                  <View style={styles.rowItem}>
                    <Field label="Length mm" value={dims.length} onChange={(v) => setDims({ ...dims, length: v })} numeric />
                  </View>
                  <View style={styles.rowItem}>
                    <Field label="Width mm" value={dims.width} onChange={(v) => setDims({ ...dims, width: v })} numeric />
                  </View>
                  <View style={styles.rowItem}>
                    <Field label="Depth mm" value={dims.depth} onChange={(v) => setDims({ ...dims, depth: v })} numeric />
                  </View>
                </View>
                <Button
                  title="Derive mm from carat"
                  kind="ghost"
                  onPress={() => {
                    const d = deriveDims();
                    if (d) setDims({ length: String(d.length), width: String(d.width), depth: String(d.depth) });
                  }}
                />
                <Field label="Origin" value={origin} onChange={setOrigin} placeholder="e.g. Sri Lanka" />
              </>
            )}
          </>
        )}
      </Section>

      <Section title="Setting & Metal">
        <ChipRow label="Setting" options={SETTING_STYLES as unknown as string[]} value={settingStyle} onSelect={setSettingStyle} render={(s) => s.replace(/_/g, ' ')} />
        <ChipRow label="Metal" options={METALS as unknown as string[]} value={metal} onSelect={setMetal} />
        {metal === 'gold' && (
          <>
            <ChipRow label="Karat" options={KARATS as unknown as number[]} value={karat} onSelect={setKarat} render={(k) => `${k}k`} />
            <ChipRow label="Color" options={METAL_COLORS as unknown as string[]} value={metalColor} onSelect={setMetalColor} />
          </>
        )}
        {mode === 'pro' && (
          <>
            <ChipRow label="Finish" options={FINISHES as unknown as string[]} value={finish} onSelect={setFinish} render={(f) => f.replace(/_/g, ' ')} />
            <View style={styles.row}>
              <View style={styles.rowItem}>
                <Field label="Prong tip mm" value={prongTip} onChange={setProngTip} numeric />
              </View>
              <View style={styles.rowItem}>
                <Field label="Gallery mm" value={gallery} onChange={setGallery} numeric />
              </View>
            </View>
          </>
        )}
      </Section>

      <Section title="Band & Size">
        <ChipRow label="Profile" options={BAND_PROFILES as unknown as string[]} value={bandProfile} onSelect={setBandProfile} render={(p) => p.replace(/_/g, ' ')} />
        {mode === 'pro' && (
          <View style={styles.row}>
            <View style={styles.rowItem}>
              <Field label="Band width mm" value={bandWidth} onChange={setBandWidth} numeric />
            </View>
            <View style={styles.rowItem}>
              <Field label="Thickness mm" value={bandThickness} onChange={setBandThickness} numeric />
            </View>
          </View>
        )}
        <Field label="Ring size (US)" value={ringSize} onChange={setRingSize} numeric />
        {mode === 'pro' && (
          <Field label="Notes to factory" value={notes} onChange={setNotes} multiline />
        )}
      </Section>

      <Section title="Describe it instead (Claude)">
        <Field
          label="Prose"
          value={prose}
          onChange={setProse}
          multiline
          placeholder="A two carat royal blue oval sapphire in 18k yellow gold, size 6.5…"
        />
        <Button title="Compile prose → spec" kind="ghost" onPress={compileProse} disabled={busy || !prose} />
      </Section>

      <ChipRow options={['basic', 'pro'] as const} value={mode} onSelect={setMode} render={(m) => (m === 'basic' ? 'Basic mode' : 'Pro mode')} />

      <View style={styles.actions}>
        <Button title="Validate" onPress={validate} disabled={busy || !species || !trade || !grade} />
        <Button title="Preview sheet" onPress={preview} disabled={busy || !species || !trade || !grade} />
        <Button title={editing ? 'Save new version' : 'Save design'} onPress={save} disabled={busy || !species || !trade || !grade} />
      </View>

      {notice && <Notice kind={notice.kind} text={notice.text} />}
      {issues.map((issue, i) => (
        <Notice
          key={i}
          kind="error"
          text={`${(issue.loc ?? []).join('.')}: ${issue.msg}${
            issue.valid_options ? ` — valid: ${issue.valid_options.join(', ')}` : ''
          }${issue.expected ? ` — expected: ${JSON.stringify(issue.expected)}` : ''}`}
        />
      ))}
      {sheetSvg && <SheetView svg={sheetSvg} />}
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1 },
  content: { padding: 12 },
  row: { flexDirection: 'row', gap: 8 },
  rowItem: { flex: 1 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 4 },
  hint: { fontSize: 11, color: theme.faint, marginBottom: 8, fontStyle: 'italic' },
});
