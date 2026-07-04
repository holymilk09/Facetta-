import React, { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { Api } from './api';
import {
  BRACELET_KINDS, CATEGORIES, CATEGORY_CUTS, Category, DEFAULTS, RING_TEMPLATES,
} from './categories';
import { Button, ChipRow, Field, Notice, Section } from './components';
import { SheetView } from './SheetView';
import { theme } from './theme';

const SETTING_STYLES = ['4_prong_basket', '6_prong_basket'] as const;
const METALS = ['gold', 'platinum', 'silver'] as const;
const KARATS = [9, 14, 18, 22] as const;
const METAL_COLORS = ['yellow', 'white', 'rose'] as const;
const FINISHES = ['high_polish', 'satin', 'matte'] as const;
const BAND_PROFILES = ['half_round', 'flat', 'knife_edge'] as const;

const CUT_RATIOS: Record<string, { lw: number; dw: number }> = {
  round_brilliant: { lw: 1.0, dw: 0.61 },
  oval_brilliant: { lw: 1.35, dw: 0.64 },
  pear: { lw: 1.5, dw: 0.62 },
  marquise: { lw: 1.9, dw: 0.6 },
  princess: { lw: 1.0, dw: 0.7 },
  asscher: { lw: 1.0, dw: 0.68 },
  radiant: { lw: 1.2, dw: 0.67 },
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
  isWide,
}: {
  api: Api;
  designer: string;
  editing: EditingTarget | null;
  initialSpec: any | null;
  onSaved: (designId: string) => void;
  isWide: boolean;
}) {
  const [category, setCategory] = useState<Category>('ring');
  const [stones, setStones] = useState<any[]>([]);
  const [findings, setFindings] = useState<any | null>(null);
  const [species, setSpecies] = useState<string | null>('sapphire');
  const [options, setOptions] = useState<any | null>(null);
  const [mode, setMode] = useState<'basic' | 'pro'>('basic');

  // stone
  const [cut, setCut] = useState<string | null>('oval_brilliant');
  const [trade, setTrade] = useState<string | null>(null);
  const [claritySystem, setClaritySystem] = useState<string | null>(null);
  const [grade, setGrade] = useState<string | null>(null);
  const [carat, setCarat] = useState('2.0');
  const [dims, setDims] = useState({ length: '', width: '', depth: '' });
  const [origin, setOrigin] = useState('');

  // ring
  const [ringTemplate, setRingTemplate] = useState<string>('solitaire_prong');
  const [haloCount, setHaloCount] = useState('8');
  const [haloSize, setHaloSize] = useState('4.1');
  const [settingStyle, setSettingStyle] = useState<string>('4_prong_basket');
  const [prongTip, setProngTip] = useState('0.9');
  const [gallery, setGallery] = useState('4.5');
  const [bandProfile, setBandProfile] = useState<string>('half_round');
  const [bandWidth, setBandWidth] = useState('1.8');
  const [bandThickness, setBandThickness] = useState('1.6');
  const [ringSize, setRingSize] = useState('6.5');

  // metal
  const [metal, setMetal] = useState<string>('gold');
  const [karat, setKarat] = useState<number>(18);
  const [metalColor, setMetalColor] = useState<string>('yellow');
  const [finish, setFinish] = useState<string>('high_polish');

  // bracelet / cuff / link
  const [braceletKind, setBraceletKind] = useState<string>('love_bangle');
  const [innerLength, setInnerLength] = useState('56');
  const [innerWidth, setInnerWidth] = useState('46');
  const [brWidth, setBrWidth] = useState('6.1');
  const [brThickness, setBrThickness] = useState('2.6');
  const [gapWidth, setGapWidth] = useState('25');
  const [linkCount, setLinkCount] = useState('14');
  const [stationCount, setStationCount] = useState('8');

  // pendant / necklace
  const [bailInner, setBailInner] = useState('3.5');
  const [bailHeight, setBailHeight] = useState('5.5');
  const [surroundCount, setSurroundCount] = useState('12');
  const [surroundSize, setSurroundSize] = useState('2.3');
  const [dropStone, setDropStone] = useState(true);
  const [dropSize, setDropSize] = useState('5.5');
  const [chainOn, setChainOn] = useState(false);
  const [chainStyle, setChainStyle] = useState('cable');
  const [chainLength, setChainLength] = useState('450');
  const [clasp, setClasp] = useState('lobster');

  // loose stone / gem ID
  const [tablePct, setTablePct] = useState('57');
  const [depthPct, setDepthPct] = useState('');
  const [girdle, setGirdle] = useState('medium');
  const [inscription, setInscription] = useState('');

  const [notes, setNotes] = useState('');
  const [collection, setCollection] = useState('');
  const [collections, setCollections] = useState<string[]>([]);
  const [newCollection, setNewCollection] = useState(false);
  const [ratioLock, setRatioLock] = useState(true);
  const [savedStones, setSavedStones] = useState<any[]>([]);
  const [lighting, setLighting] = useState('studio');
  const [wornOn, setWornOn] = useState('product');
  const [renderStyle, setRenderStyle] = useState('photo');
  const [printGuide, setPrintGuide] = useState<'with guide' | 'clean (for photos)'>('with guide');
  const [platePaper, setPlatePaper] = useState('ivory');
  const [centerMount, setCenterMount] = useState('default');
  const [surroundMount, setSurroundMount] = useState('default');
  const [dropMount, setDropMount] = useState('default');
  const [stationMount, setStationMount] = useState('default');
  const [mockup, setMockup] = useState<any | null>(null);
  const [prose, setProse] = useState('');
  const [notice, setNotice] = useState<{ kind: 'ok' | 'error' | 'info'; text: string } | null>(null);
  const [issues, setIssues] = useState<any[]>([]);
  const [sheetSvg, setSheetSvg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.stones().then((r) => r.ok && setStones(r.body.stones));
    api.findings().then((r) => r.ok && setFindings(r.body));
    api.listStones(designer).then((r) => r.ok && setSavedStones(r.body.stones));
    refreshCollections();
    selectSpecies(DEFAULTS[category].species);
  }, [api.baseUrl, designer]);

  const refreshCollections = () =>
    api.listDesigns().then((r) => {
      if (!r.ok) return;
      const names = r.body.designs
        .map((d: any) => d.collection)
        .filter(Boolean) as string[];
      setCollections([...new Set(names)].sort((a, b) => a.localeCompare(b)));
    });

  useEffect(() => {
    if (initialSpec) applySpec(initialSpec);
  }, [initialSpec]);

  const pickCategory = (c: Category) => {
    setCategory(c);
    setSheetSvg(null);
    setIssues([]);
    setNotice(null);
    setWornOn('product'); // placements are per-type; never carry one across
    setMockup(null);
    const d = DEFAULTS[c];
    setCarat(d.carat);
    setCut(d.cut);
    setDims({ length: '', width: '', depth: '' });
    if (species !== d.species) selectSpecies(d.species);
  };

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
      return;
    }
    setOptions(r.body);
    setClaritySystem(r.body.clarity.systems[0]);
  };

  const applySpec = async (spec: any) => {
    const cat: Category =
      spec.jewelry_type === 'bracelet' ? 'bracelet'
      : spec.jewelry_type === 'pendant' || spec.jewelry_type === 'necklace' ? 'pendant'
      : spec.jewelry_type === 'loose_stone' ? 'loose'
      : 'ring';
    setCategory(cat);
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
    if (spec.setting) {
      setSettingStyle(spec.setting.style);
      setProngTip(String(spec.setting.prong_tip_mm ?? 0.9));
      setGallery(String(spec.setting.gallery_height_mm ?? 4.5));
    }
    if (spec.metal) {
      setMetal(spec.metal.material);
      setKarat(spec.metal.karat ?? 18);
      setMetalColor(spec.metal.color ?? 'yellow');
      setFinish(spec.metal.finish ?? 'high_polish');
    }
    if (spec.band) {
      setBandProfile(spec.band.profile);
      setBandWidth(String(spec.band.width_mm));
      setBandThickness(String(spec.band.thickness_mm));
    }
    if (spec.ring_size) setRingSize(String(spec.ring_size.value));
    if (cat === 'ring') setRingTemplate(spec.template);
    if (spec.bracelet) {
      setBraceletKind(spec.template);
      setInnerLength(String(spec.bracelet.inner_length_mm));
      setInnerWidth(String(spec.bracelet.inner_width_mm));
      setBrWidth(String(spec.bracelet.width_mm));
      setBrThickness(String(spec.bracelet.thickness_mm));
      if (spec.bracelet.gap_width_mm) setGapWidth(String(spec.bracelet.gap_width_mm));
      if (spec.bracelet.link_count) setLinkCount(String(spec.bracelet.link_count));
      setStationCount(String(spec.stone.count ?? 1));
    }
    if (spec.pendant) {
      setBailInner(String(spec.pendant.bail_inner_diameter_mm));
      setBailHeight(String(spec.pendant.bail_height_mm));
    }
    if (spec.chain) {
      setChainOn(true);
      setChainStyle(spec.chain.style);
      setChainLength(String(spec.chain.length_mm));
      setClasp(spec.chain.clasp);
    }
    if (spec.stone.table_pct) setTablePct(String(spec.stone.table_pct));
    if (spec.stone.depth_pct) setDepthPct(String(spec.stone.depth_pct));
    if (spec.stone.girdle) setGirdle(spec.stone.girdle);
    if (spec.stone.inscription) setInscription(spec.stone.inscription);
    setNotes(spec.notes_to_factory ?? '');
  };

  const deriveDimsFor = (cutId: string | null, ct: number, sg?: number, factor?: number) => {
    if (!options || !cutId) return null;
    const cutInfo = options.cuts.find((c: any) => c.id === cutId);
    const ratios = CUT_RATIOS[cutId] ?? { lw: 1.3, dw: 0.64 };
    if (!cutInfo || !ct) return null;
    const width = Math.cbrt(
      (200 * ct) / (ratios.lw * ratios.dw * (sg ?? options.sg) * (factor ?? cutInfo.shape_factor)),
    );
    const round = (v: number) => Math.round(v * 10) / 10;
    return { length: round(width * ratios.lw), width: round(width), depth: round(width * ratios.dw) };
  };

  const deriveDims = () => deriveDimsFor(cut, parseFloat(carat));

  // proportional resize: edit any one dimension and the other two follow the
  // cut's aspect ratios; the carat re-estimates from the density model, so a
  // resize is one edit, never a rebuild
  const onDimChange = (key: 'length' | 'width' | 'depth', v: string) => {
    const n = parseFloat(v);
    if (!ratioLock || !isFinite(n) || n <= 0) {
      setDims({ ...dims, [key]: v });
      return;
    }
    const { lw, dw } = CUT_RATIOS[cut ?? ''] ?? { lw: 1.3, dw: 0.64 };
    const width = key === 'length' ? n / lw : key === 'width' ? n : n / dw;
    const r = (x: number) => String(Math.round(x * 100) / 100);
    const scaled = {
      length: key === 'length' ? v : r(width * lw),
      width: key === 'width' ? v : r(width),
      depth: key === 'depth' ? v : r(width * dw),
    };
    setDims(scaled);
    const cutInfo = options?.cuts.find((c: any) => c.id === cut);
    if (cutInfo && options?.sg) {
      const ct =
        (parseFloat(scaled.length) * parseFloat(scaled.width) * parseFloat(scaled.depth) *
          options.sg * cutInfo.shape_factor) / 200;
      if (isFinite(ct) && ct > 0) setCarat(String(Math.round(ct * 100) / 100));
    }
  };

  const buildStone = () => {
    const dimensions =
      mode === 'pro' && dims.length && dims.width && dims.depth
        ? { length: parseFloat(dims.length), width: parseFloat(dims.width), depth: parseFloat(dims.depth) }
        : deriveDims();
    const stone: any = {
      species,
      cut,
      carat: parseFloat(carat),
      dimensions_mm: dimensions,
      color: { trade, gia: options?.colors.find((c: any) => c.term === trade)?.gia ?? '' },
      // design-first: clarity omitted means "finest available, sourced on approval"
      clarity: grade ? { system: claritySystem, grade } : null,
      origin: mode === 'pro' && origin ? origin : null,
      phenomena: [],
    };
    if (category === 'loose') {
      if (tablePct) stone.table_pct = parseFloat(tablePct);
      if (dimensions) stone.depth_pct = Math.round((dimensions.depth / dimensions.width) * 1000) / 10;
      if (girdle) stone.girdle = girdle;
      if (inscription) stone.inscription = inscription;
    }
    if (category === 'bracelet') {
      stone.count = parseInt(stationCount || '1', 10);
      stone.position = 'stations';
      if (stationMount !== 'default') stone.mount = stationMount;
    } else if (category !== 'loose' && centerMount !== 'default') {
      stone.mount = centerMount;
    }
    return stone;
  };

  // 0.25 ct round melee ~ pi-free approximation via the density formula
  const meleeStone = (sizeMm: number, count: number, position: string) => {
    const depth = Math.round(sizeMm * 0.61 * 10) / 10;
    const ct = Math.round(sizeMm * sizeMm * depth * 3.52 * 0.36 / 200 * 100) / 100;
    return {
      species: 'diamond',
      cut: 'round_brilliant',
      carat: Math.max(0.01, ct),
      dimensions_mm: { length: sizeMm, width: sizeMm, depth },
      color: { trade: 'F', gia: 'colorless' },
      clarity: { system: 'gia_diamond', grade: 'VS2' },
      count,
      position,
      phenomena: [],
      ...(surroundMount !== 'default' ? { mount: surroundMount } : {}),
    };
  };

  const buildSpec = () => {
    const base: any = {
      schema_version: 1,
      design_id: editing?.designId ?? 'dsn_pending',
      version: 1,
      created_by: designer,
      created_at: new Date().toISOString(),
      mode,
      stone: buildStone(),
      side_stones: [],
      notes_to_factory: notes || null,
    };
    // alloy logic: parameters that don't apply to a metal are omitted, never
    // defaulted — silver/platinum carry no karat and no color choice
    const metalSection = {
      material: metal,
      karat: metalRules.karats.length ? karat : null,
      color: metalRules.colors.length ? metalColor : null,
      finish,
    };
    if (category === 'ring') {
      base.jewelry_type = 'ring';
      base.template = ringTemplate;
      base.setting = {
        style: settingStyle,
        prong_count: settingStyle.startsWith('6') ? 6 : 4,
        prong_tip_mm: parseFloat(prongTip),
        gallery_height_mm: parseFloat(gallery),
      };
      base.metal = metalSection;
      base.band = {
        profile: bandProfile,
        width_mm: parseFloat(bandWidth),
        thickness_mm: parseFloat(bandThickness),
      };
      base.ring_size = { system: 'US', value: parseFloat(ringSize) };
      if (ringTemplate === 'halo_prong') {
        base.side_stones = [meleeStone(parseFloat(haloSize), parseInt(haloCount, 10), 'halo')];
      }
    } else if (category === 'bracelet') {
      base.jewelry_type = 'bracelet';
      base.template = braceletKind;
      base.setting = { style: 'flush_set' };
      base.metal = metalSection;
      base.bracelet = {
        inner_length_mm: parseFloat(innerLength),
        inner_width_mm: parseFloat(innerWidth),
        width_mm: parseFloat(brWidth),
        thickness_mm: parseFloat(brThickness),
        ...(braceletKind === 'cuff' ? { gap_width_mm: parseFloat(gapWidth) } : {}),
        ...(braceletKind === 'link_bracelet' ? { link_count: parseInt(linkCount, 10) } : {}),
      };
    } else if (category === 'pendant') {
      base.jewelry_type = chainOn ? 'necklace' : 'pendant';
      base.template = 'cluster_pendant';
      base.setting = { style: 'prong_cluster', prong_count: 4, prong_tip_mm: 0.8 };
      base.metal = metalSection;
      base.pendant = {
        bail_inner_diameter_mm: parseFloat(bailInner),
        bail_height_mm: parseFloat(bailHeight),
      };
      base.side_stones = [
        meleeStone(parseFloat(surroundSize), parseInt(surroundCount, 10), 'surround'),
      ];
      if (dropStone) {
        const size = parseFloat(dropSize);
        const depth = Math.round(size * 0.61 * 10) / 10;
        const ct = Math.round(size * size * depth * 4.0 * 0.36 / 200 * 100) / 100;
        base.side_stones.push({
          species: 'sapphire',
          cut: 'round_brilliant',
          carat: ct,
          dimensions_mm: { length: size, width: size, depth },
          color: { trade: 'Royal Blue', gia: 'vivid violetish blue, tone 6, saturation 6' },
          clarity: { system: 'gia_type_ii', grade: 'VS' },
          count: 1,
          position: 'under_center',
          phenomena: [],
          ...(dropMount !== 'default' ? { mount: dropMount } : {}),
        });
      }
      if (chainOn) {
        base.chain = { style: chainStyle, length_mm: parseFloat(chainLength), clasp };
      }
    } else {
      base.jewelry_type = 'loose_stone';
      base.template = 'loose_stone';
    }
    return base;
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
      if (r.ok) setNotice({ kind: 'ok', text: 'Spec is valid — physically possible and fully in vocabulary.' });
      else showIssues(r.body);
    });

  const preview = () =>
    run(async () => {
      const r = await api.sheetPreview(buildSpec());
      if (r.ok) {
        setSheetSvg(r.body);
        setNotice({ kind: 'ok', text: 'Sheet rendered from the validated spec.' });
      } else showIssues(r.body);
    });

  const prototype = () =>
    run(async () => {
      const r = await api.prototypePreview(buildSpec());
      if (r.ok) {
        setSheetSvg(r.body);
        setNotice({ kind: 'ok', text: 'Colored prototype — hues straight from the vocabulary.' });
      } else showIssues(r.body);
    });

  const trueSize = () =>
    run(async () => {
      const r = await api.trueSizePreview(buildSpec(), printGuide === 'with guide');
      if (r.ok) {
        setSheetSvg(r.body);
        setNotice({
          kind: 'ok',
          text:
            'True-size sheet (1:1) — looks tiny on screen because it IS the real size. ' +
            'Print at 100%, check the 100 mm rule, then lay the piece on the outlines.' +
            (printGuide === 'clean (for photos)'
              ? ' Clean page: no wording near the piece.'
              : ''),
        });
      } else showIssues(r.body);
    });

  const plate = () =>
    run(async () => {
      const r = await api.platePreview(buildSpec(), platePaper);
      if (r.ok) {
        setSheetSvg(r.body);
        setNotice({
          kind: 'ok',
          text: 'Presentation plate — the sketch look, but every count and measurement drawn from the spec.',
        });
      } else showIssues(r.body);
    });

  const save = () =>
    run(async () => {
      const spec = buildSpec();
      const r = editing
        ? await api.createVersion(editing.designId, designer, spec, collection.trim() || undefined)
        : await api.createDesign(designer, spec, collection.trim() || undefined);
      if (r.ok) {
        setNotice({ kind: 'ok', text: `Saved ${r.body.design_id} v${r.body.version} (immutable).` });
        setNewCollection(false);
        refreshCollections(); // a freshly named collection becomes a chip
        onSaved(r.body.design_id);
      } else showIssues(r.body);
    });

  const refreshStones = () =>
    api.listStones(designer).then((r) => r.ok && setSavedStones(r.body.stones));

  const saveStoneToLibrary = () =>
    run(async () => {
      const stone = buildStone();
      const label = `${stone.carat} ct ${stone.species}, ${String(stone.cut).replace(/_/g, ' ')}`;
      const r = await api.saveStone(designer, label, stone);
      if (r.ok) {
        setNotice({ kind: 'ok', text: `Stone filed in your library as "${label}".` });
        refreshStones();
      } else showIssues(r.body);
    });

  const applySavedStone = (stoneId: string) => {
    const row = savedStones.find((s) => s.stone_id === stoneId);
    if (!row) return;
    const st = row.stone;
    if (st.species !== species) selectSpecies(st.species);
    setCut(st.cut);
    setCarat(String(st.carat));
    if (st.dimensions_mm) {
      setDims({
        length: String(st.dimensions_mm.length),
        width: String(st.dimensions_mm.width),
        depth: String(st.dimensions_mm.depth),
      });
    }
    if (st.color?.trade) setTrade(st.color.trade);
    setNotice({ kind: 'info', text: `Using "${row.label}" — only the mounting will adapt; the piece stays as designed.` });
  };

  const compileMockup = () =>
    run(async () => {
      const r = await api.renderRequest(buildSpec(), lighting, wornOn, renderStyle);
      if (r.ok) {
        setMockup(r.body);
        setNotice({
          kind: 'ok',
          text: `Mockup request compiled — seed ${r.body.seed} is locked to this geometry; re-run after any color/metal change and the composition stays identical.`,
        });
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

  // alloy rules from the metals vocabulary (empty list = parameter not applicable)
  const metalRules = findings?.metals?.find((m: any) => m.id === metal) ?? {
    karats: metal === 'gold' ? [9, 14, 18, 22, 24] : [],
    colors: metal === 'gold' ? ['yellow', 'white', 'rose'] : [],
  };

  const gemstoneStones = stones.filter((s) => s.parameter_set === 'gemstone');
  const allowedCuts = CATEGORY_CUTS[category];
  const cuts = options
    ? options.cuts.filter((c: any) => !allowedCuts || allowedCuts.includes(c.id))
    : [];
  const ready = !!(species && trade);

  // mounts that can physically hold a stone in this role, from the vocabulary
  const mountOptions = (role: string) => [
    'default',
    ...((findings?.setting_techniques ?? [])
      .filter((t: any) => t.holds.includes(role))
      .map((t: any) => t.id)),
  ];

  const form = (
    <>
      {editing && (
        <Notice kind="info" text={`Editing ${editing.designId} — saving creates version ${editing.version + 1} (v${editing.version} stays untouched).`} />
      )}
      <ChipRow
        label="Piece"
        options={CATEGORIES.map((c) => c.id)}
        value={category}
        onSelect={(c) => pickCategory(c as Category)}
        render={(id) => CATEGORIES.find((c) => c.id === id)?.label ?? id}
      />
      {category === 'ring' && (
        <ChipRow
          label="Template"
          options={RING_TEMPLATES.map((t) => t.id) as unknown as string[]}
          value={ringTemplate}
          onSelect={setRingTemplate}
          render={(id) => RING_TEMPLATES.find((t) => t.id === id)?.label ?? id}
        />
      )}
      {category === 'bracelet' && (
        <ChipRow
          label="Kind"
          options={BRACELET_KINDS.map((t) => t.id) as unknown as string[]}
          value={braceletKind}
          onSelect={setBraceletKind}
          render={(id) => BRACELET_KINDS.find((t) => t.id === id)?.label ?? id}
        />
      )}

      <Section title={category === 'bracelet' ? 'Station stone' : 'Stone'}>
        {savedStones.length > 0 && (
          <ChipRow
            label="From your stone library — mounting adapts, the piece never rescales"
            options={savedStones.map((s: any) => s.stone_id) as string[]}
            value={null}
            onSelect={applySavedStone}
            render={(id) => savedStones.find((s: any) => s.stone_id === id)?.label ?? String(id)}
          />
        )}
        <ChipRow
          label="Species"
          options={gemstoneStones.map((s) => s.id)}
          value={species}
          onSelect={selectSpecies}
          render={(id) => gemstoneStones.find((s) => s.id === id)?.display ?? id}
        />
        {options && (
          <>
            <ChipRow
              label="Cut"
              options={cuts.map((c: any) => c.id)}
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
              label={`Clarity — optional, blank = finest available (${claritySystem ?? ''})`}
              options={(options.clarity.grades[claritySystem ?? ''] ?? []).map((g: any) => g.grade)}
              value={grade}
              onSelect={(g) => setGrade(grade === g ? null : g)}
            />
            <Field label="Carat (per stone)" value={carat} onChange={setCarat} numeric />
            {mode === 'pro' && (
              <>
                <ChipRow
                  label="Resize"
                  options={['proportional', 'free'] as const}
                  value={ratioLock ? 'proportional' : 'free'}
                  onSelect={(v) => setRatioLock(v === 'proportional')}
                  render={(v) =>
                    v === 'proportional' ? 'Proportional — carat follows' : 'Free — each axis alone'
                  }
                />
                <View style={styles.row}>
                  <View style={styles.rowItem}>
                    <Field label="Length mm" value={dims.length} onChange={(v) => onDimChange('length', v)} numeric />
                  </View>
                  <View style={styles.rowItem}>
                    <Field label="Width mm" value={dims.width} onChange={(v) => onDimChange('width', v)} numeric />
                  </View>
                  <View style={styles.rowItem}>
                    <Field label="Depth mm" value={dims.depth} onChange={(v) => onDimChange('depth', v)} numeric />
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

      {category === 'ring' && (
        <>
          {ringTemplate === 'halo_prong' && (
            <Section title="Halo melee">
              <View style={styles.row}>
                <View style={styles.rowItem}>
                  <Field label="Count" value={haloCount} onChange={setHaloCount} numeric />
                </View>
                <View style={styles.rowItem}>
                  <Field label="Stone ⌀ mm" value={haloSize} onChange={setHaloSize} numeric />
                </View>
              </View>
              <Text style={styles.hint}>The validator rejects counts that cannot physically fit around the center.</Text>
            </Section>
          )}
          <Section title="Setting & Band">
            <ChipRow label="Setting" options={SETTING_STYLES as unknown as string[]} value={settingStyle} onSelect={setSettingStyle} render={(s) => s.replace(/_/g, ' ')} />
            <ChipRow label="Profile" options={BAND_PROFILES as unknown as string[]} value={bandProfile} onSelect={setBandProfile} render={(p) => p.replace(/_/g, ' ')} />
            {mode === 'pro' && (
              <View style={styles.row}>
                <View style={styles.rowItem}>
                  <Field label="Band width mm" value={bandWidth} onChange={setBandWidth} numeric />
                </View>
                <View style={styles.rowItem}>
                  <Field label="Thickness mm" value={bandThickness} onChange={setBandThickness} numeric />
                </View>
                <View style={styles.rowItem}>
                  <Field label="Prong tip mm" value={prongTip} onChange={setProngTip} numeric />
                </View>
              </View>
            )}
            <Field label="Ring size (US)" value={ringSize} onChange={setRingSize} numeric />
          </Section>
        </>
      )}

      {category === 'bracelet' && (
        <Section title="Bracelet geometry">
          <View style={styles.row}>
            <View style={styles.rowItem}>
              <Field label="Inner X mm" value={innerLength} onChange={setInnerLength} numeric />
            </View>
            <View style={styles.rowItem}>
              <Field label="Inner Y mm" value={innerWidth} onChange={setInnerWidth} numeric />
            </View>
          </View>
          <View style={styles.row}>
            <View style={styles.rowItem}>
              <Field label="Band width mm" value={brWidth} onChange={setBrWidth} numeric />
            </View>
            <View style={styles.rowItem}>
              <Field label="Thickness mm" value={brThickness} onChange={setBrThickness} numeric />
            </View>
          </View>
          {braceletKind === 'cuff' && (
            <Field label="Gap width mm (wrist opening)" value={gapWidth} onChange={setGapWidth} numeric />
          )}
          {braceletKind === 'link_bracelet' && (
            <Field label="Link count" value={linkCount} onChange={setLinkCount} numeric />
          )}
          <Field label="Station stones (count)" value={stationCount} onChange={setStationCount} numeric />
        </Section>
      )}

      {category === 'pendant' && (
        <>
          <Section title="Pendant assembly">
            <View style={styles.row}>
              <View style={styles.rowItem}>
                <Field label="Bail inner ⌀ mm" value={bailInner} onChange={setBailInner} numeric />
              </View>
              <View style={styles.rowItem}>
                <Field label="Bail height mm" value={bailHeight} onChange={setBailHeight} numeric />
              </View>
            </View>
            <View style={styles.row}>
              <View style={styles.rowItem}>
                <Field label="Surround count" value={surroundCount} onChange={setSurroundCount} numeric />
              </View>
              <View style={styles.rowItem}>
                <Field label="Surround ⌀ mm" value={surroundSize} onChange={setSurroundSize} numeric />
              </View>
            </View>
            <ChipRow
              label="Drop stone under center"
              options={['sapphire drop', 'none']}
              value={dropStone ? 'sapphire drop' : 'none'}
              onSelect={(v) => setDropStone(v === 'sapphire drop')}
            />
            {dropStone && <Field label="Drop stone ⌀ mm" value={dropSize} onChange={setDropSize} numeric />}
            <Text style={styles.hint}>Total drop from the top of the bail is derived and dimensioned automatically.</Text>
          </Section>
          <Section title="Chain (makes it a necklace)">
            <ChipRow
              label="Chain"
              options={['pendant only', 'with chain']}
              value={chainOn ? 'with chain' : 'pendant only'}
              onSelect={(v) => setChainOn(v === 'with chain')}
            />
            {chainOn && findings && (
              <>
                <ChipRow
                  label="Style"
                  options={findings.chain_styles.map((c: any) => c.id)}
                  value={chainStyle}
                  onSelect={setChainStyle}
                  render={(id) => findings.chain_styles.find((c: any) => c.id === id)?.display ?? id}
                />
                <ChipRow
                  label="Clasp"
                  options={findings.clasp_types.map((c: any) => c.id)}
                  value={clasp}
                  onSelect={setClasp}
                  render={(id) => findings.clasp_types.find((c: any) => c.id === id)?.display ?? id}
                />
                <Field label="Length mm" value={chainLength} onChange={setChainLength} numeric />
              </>
            )}
          </Section>
        </>
      )}

      {category === 'loose' && (
        <Section title="Gem ID">
          <View style={styles.row}>
            <View style={styles.rowItem}>
              <Field label="Table %" value={tablePct} onChange={setTablePct} numeric />
            </View>
            <View style={styles.rowItem}>
              <Field label="Depth % (auto from mm)" value={depthPct} onChange={setDepthPct} numeric placeholder="derived" />
            </View>
          </View>
          {findings && (
            <ChipRow
              label="Girdle"
              options={findings.girdle_thickness_scale}
              value={girdle}
              onSelect={setGirdle}
              render={(g: string) => g.replace(/_/g, ' ')}
            />
          )}
          <Field label="Laser inscription" value={inscription} onChange={setInscription} placeholder="e.g. FCT-2141Z" />
        </Section>
      )}

      {category !== 'loose' && (
        <Section title="Metal">
          <ChipRow label="Metal" options={METALS as unknown as string[]} value={metal} onSelect={setMetal} />
          <ChipRow
            label="Karat"
            options={KARATS as unknown as number[]}
            value={karat}
            onSelect={setKarat}
            render={(k) => `${k}k`}
            disabled={!metalRules.karats.length}
            disabledNote={`${metal} is not karated`}
          />
          <ChipRow
            label="Color"
            options={METAL_COLORS as unknown as string[]}
            value={metalColor}
            onSelect={setMetalColor}
            disabled={!metalRules.colors.length}
            disabledNote={`${metal} has one natural color`}
          />
          {mode === 'pro' && (
            <ChipRow label="Finish" options={FINISHES as unknown as string[]} value={finish} onSelect={setFinish} render={(f) => f.replace(/_/g, ' ')} />
          )}
          {mode === 'pro' && <Field label="Notes to factory" value={notes} onChange={setNotes} multiline />}
        </Section>
      )}

      <Section title="Mockup — bring it to life">
        <ChipRow
          label="Style"
          options={['photo', 'atelier_sketch'] as const}
          value={renderStyle}
          onSelect={(s) => {
            setRenderStyle(s);
            if (s === 'atelier_sketch') setWornOn('product');
          }}
          render={(s) => (s === 'photo' ? 'Photoreal' : 'Atelier sketch')}
        />
        <ChipRow
          label="Lighting"
          options={['studio', 'natural', 'outdoor', 'editorial'] as const}
          value={lighting}
          onSelect={setLighting}
          disabled={renderStyle === 'atelier_sketch'}
          disabledNote="sketches carry their own paper-and-pencil look"
        />
        <ChipRow
          label="Worn on"
          options={
            (category === 'ring'
              ? ['product', 'finger']
              : category === 'bracelet'
                ? ['product', 'wrist']
                : category === 'pendant'
                  ? ['product', 'neck']
                  : ['product']) as string[]
          }
          value={wornOn}
          onSelect={setWornOn}
          render={(w) => (w === 'product' ? 'product only' : `on a ${w}`)}
        />
        <Button
          title="Compile mockup request"
          kind="ghost"
          onPress={compileMockup}
          disabled={busy || !ready}
        />
        {mockup && (
          <Text style={styles.mockupText}>
            seed {mockup.seed} · {mockup.scene.lighting} · {mockup.scene.worn_on}
            {'\n\n'}
            {mockup.prompt}
          </Text>
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

      {collections.length > 0 && !newCollection ? (
        <ChipRow
          label="Collection — group saves for yourself or per client (optional)"
          options={['none', ...collections, '+ new']}
          value={collection || 'none'}
          onSelect={(v) => {
            if (v === '+ new') {
              setCollection('');
              setNewCollection(true);
            } else setCollection(v === 'none' ? '' : v);
          }}
        />
      ) : (
        <>
          <Field
            label="Collection — group saves for yourself or per client (optional)"
            value={collection}
            onChange={setCollection}
            placeholder="e.g. Client — Sarah K"
          />
          {collections.length > 0 && (
            <Button
              title="Pick an existing collection instead"
              kind="ghost"
              onPress={() => {
                setCollection('');
                setNewCollection(false);
              }}
            />
          )}
        </>
      )}

      {category !== 'loose' && findings?.setting_techniques && (
        <>
          {(category === 'ring' || category === 'pendant') && (
            <ChipRow
              label="Center stone mount"
              options={mountOptions('center')}
              value={centerMount}
              onSelect={setCenterMount}
            />
          )}
          {(category === 'pendant' || (category === 'ring' && ringTemplate === 'halo_prong')) && (
            <ChipRow
              label="Surround / halo mount"
              options={mountOptions('side')}
              value={surroundMount}
              onSelect={setSurroundMount}
            />
          )}
          {category === 'pendant' && dropStone && (
            <ChipRow
              label="Drop mount"
              options={mountOptions('drop')}
              value={dropMount}
              onSelect={setDropMount}
            />
          )}
          {category === 'bracelet' && (
            <ChipRow
              label="Station mount"
              options={mountOptions('station')}
              value={stationMount}
              onSelect={setStationMount}
            />
          )}
        </>
      )}

      <ChipRow
        label="Plate paper — what the presentation plate is drawn on"
        options={['ivory', 'white', 'grey', 'midnight', 'black', 'blush']}
        value={platePaper}
        onSelect={setPlatePaper}
      />

      <ChipRow
        label="1:1 print sheet — on screen everything stays enlarged; printed at 100% it is true to size"
        options={['with guide', 'clean (for photos)'] as const}
        value={printGuide}
        onSelect={setPrintGuide}
      />

      <View style={styles.actions}>
        <Button title="Validate" onPress={validate} disabled={busy || !ready} />
        <Button title="Save stone to library" kind="ghost" onPress={saveStoneToLibrary} disabled={busy || !ready} />
        <Button title="Preview sheet" onPress={preview} disabled={busy || !ready} />
        <Button title="Color prototype" onPress={prototype} disabled={busy || !ready} />
        <Button title="True size (print 1:1)" kind="ghost" onPress={trueSize} disabled={busy || !ready} />
        <Button title="Presentation plate" kind="ghost" onPress={plate} disabled={busy || !ready} />
        <Button title={editing ? 'Save new version' : 'Save design'} onPress={save} disabled={busy || !ready} />
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
      {!isWide && sheetSvg && <SheetView svg={sheetSvg} />}
      <View style={{ height: 40 }} />
    </>
  );

  if (!isWide) {
    return <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>{form}</ScrollView>;
  }
  return (
    <View style={styles.wide}>
      <ScrollView style={styles.wideForm} contentContainerStyle={styles.content}>{form}</ScrollView>
      <View style={styles.widePreview}>
        <Text style={styles.previewTitle}>LIVE SHEET</Text>
        {sheetSvg ? (
          <SheetView svg={sheetSvg} />
        ) : (
          <Text style={styles.hint}>Tap “Preview sheet” to render the technical sheet here.</Text>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  scroll: { flex: 1 },
  content: { padding: 12 },
  row: { flexDirection: 'row', gap: 8 },
  rowItem: { flex: 1 },
  actions: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 4 },
  hint: { fontSize: 11, color: theme.faint, marginBottom: 8, fontStyle: 'italic' },
  mockupText: { fontSize: 12, color: theme.ink, marginTop: 8, lineHeight: 17 },
  wide: { flex: 1, flexDirection: 'row' },
  wideForm: { flex: 1.05, borderRightWidth: 1, borderRightColor: theme.line },
  widePreview: { flex: 1, padding: 14 },
  previewTitle: {
    fontFamily: theme.serif,
    fontSize: 13,
    letterSpacing: 1.5,
    color: theme.faint,
    marginBottom: 8,
  },
});
