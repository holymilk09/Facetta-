/// <reference types="jest" />

import {
  buildChainTargetData,
  chainConstructionForStyle,
  EMPTY_CHAIN_TARGET_DRAFT,
  type ChainTargetDraft,
} from './ChainTargetEditor';

const draft = (overrides: Partial<ChainTargetDraft> = {}): ChainTargetDraft => ({
  ...EMPTY_CHAIN_TARGET_DRAFT,
  chainWidth: '2.2',
  profileThickness: '0.7',
  endRingOuterDiameter: '3.8',
  linkThickness: '0.4',
  standardLength: '4.1',
  standardInsideLength: '3.2',
  standardInsideWidth: '1.4',
  longLength: '7.2',
  longInsideLength: '6.3',
  longInsideWidth: '1.4',
  strandWireDiameter: '0.25',
  strandCount: '8',
  plateThickness: '0.18',
  productionReference: 'TARGET-CHAIN-001',
  ...overrides,
});

describe('chain target manufacturing form', () => {
  test('maps only released chain styles to their physical construction family', () => {
    expect(chainConstructionForStyle('cable')).toBe('open_link');
    expect(chainConstructionForStyle('curb')).toBe('open_link');
    expect(chainConstructionForStyle('figaro')).toBe('open_link');
    expect(chainConstructionForStyle('box')).toBe('open_link');
    expect(chainConstructionForStyle('rope')).toBe('stranded');
    expect(chainConstructionForStyle('wheat')).toBe('stranded');
    expect(chainConstructionForStyle('singapore')).toBe('stranded');
    expect(chainConstructionForStyle('snake')).toBe('smooth_plate');
    expect(chainConstructionForStyle('invented')).toBeNull();
  });

  test('builds a complete curb target without inheriting any source SKU', () => {
    expect(buildChainTargetData('curb', draft())).toEqual({
      geometry: {
        construction: 'open_link',
        chain_width_mm: 2.2,
        profile_thickness_mm: 0.7,
        end_ring_outer_diameter_mm: 3.8,
        link_thickness_mm: 0.4,
        links_soldered: true,
        links: [{
          role: 'standard',
          length_mm: 4.1,
          inside_length_mm: 3.2,
          inside_width_mm: 1.4,
        }],
      },
      production: {
        mode: 'stock',
        reference_kind: 'supplier_sku',
        reference: 'TARGET-CHAIN-001',
      },
    });
  });

  test('requires the long repeat for Figaro and supports custom authority', () => {
    expect(buildChainTargetData('figaro', draft({ longLength: '' }))).toBeNull();
    const target = buildChainTargetData('figaro', draft({
      productionMode: 'custom',
      customReferenceKind: 'cad_asset',
      productionReference: 'cad_target_figaro_v4',
    }));
    expect(target?.geometry.construction).toBe('open_link');
    expect(target?.geometry.construction === 'open_link'
      ? target.geometry.links.map((link) => link.role) : []).toEqual(['standard', 'long']);
    expect(target?.production).toEqual({
      mode: 'custom',
      reference_kind: 'cad_asset',
      reference: 'cad_target_figaro_v4',
    });
  });

  test('builds category-specific stranded and plate geometry', () => {
    expect(buildChainTargetData('rope', draft())?.geometry).toMatchObject({
      construction: 'stranded',
      strand_wire_diameter_mm: 0.25,
      strand_count: 8,
    });
    expect(buildChainTargetData('snake', draft())?.geometry).toMatchObject({
      construction: 'smooth_plate',
      plate_thickness_mm: 0.18,
    });
  });

  test('never upgrades incomplete, nonnumeric, or fractional-count input', () => {
    expect(buildChainTargetData('curb', draft({ productionReference: '' }))).toBeNull();
    expect(buildChainTargetData('curb', draft({ chainWidth: 'wide' }))).toBeNull();
    expect(buildChainTargetData('rope', draft({ strandCount: '7.5' }))).toBeNull();
    expect(buildChainTargetData('rope', draft({ strandWireDiameter: '-0.2' }))).toBeNull();
  });
});
