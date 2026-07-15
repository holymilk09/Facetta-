import type {
  ComponentCatalog, ComponentCatalogOption, ComponentCatalogPath, StudioComponentTargeting,
} from '../trusted/types';

export type RefineInstructionRoute =
  | { kind: 'appearance'; instruction: string }
  | {
    kind: 'catalog';
    instruction: string;
    componentPath: ComponentCatalogPath;
    option: ComponentCatalogOption;
    catalog: ComponentCatalog;
  }
  | {
    kind: 'component_choice';
    instruction: string;
    candidatePaths: readonly ComponentCatalogPath[];
  }
  | {
    kind: 'markup_required';
    instruction: string;
    reason: 'localized' | 'structural' | 'unsupported_component';
  }
  | {
    kind: 'starting_facts_required';
    instruction: string;
    candidatePaths: readonly ComponentCatalogPath[];
  };

const normalize = (value: string): string => value
  .toLowerCase()
  .replaceAll('_', ' ')
  .replace(/[^a-z0-9]+/g, ' ')
  .trim()
  .replace(/\s+/g, ' ');

const containsPhrase = (haystack: string, needle: string): boolean => {
  const normalizedNeedle = normalize(needle);
  return normalizedNeedle.length > 0
    && ` ${haystack} `.includes(` ${normalizedNeedle} `);
};

const PATH_SIGNALS: Readonly<Record<ComponentCatalogPath, readonly RegExp[]>> = {
  'metal.color': [
    /\b(?:rose|yellow|white)\s+gold\b/i,
    /\bmetal\s+(?:colou?r|tone)\b/i,
  ],
  'metal.material': [
    /\b(?:platinum|sterling\s+silver|silver)\b/i,
    /\bmetal\s+material\b/i,
    /\b(?:change|make|use|switch)(?:\s+the)?\s+metal\b/i,
  ],
  'stone.color': [
    /\b(?:stone|gem|gemstone|diamond|sapphire|ruby|emerald)\s+colou?r\b/i,
    /\bcolou?r(?:\s+of)?(?:\s+the)?\s+(?:stone|gem|gemstone|diamond|sapphire|ruby|emerald)\b/i,
  ],
  'stone.cut': [
    /\b(?:stone|gem|gemstone|diamond)\s+(?:cut|shape)\b/i,
    /\b(?:round|oval|emerald|cushion|pear|marquise|princess|radiant)\s+cut\b/i,
  ],
  'setting.style': [
    /\bsetting(?:\s+style)?\b/i,
    /\b(?:bezel|semi\s+bezel|four\s+prong|six\s+prong|4\s+prong|6\s+prong)\b/i,
  ],
  'chain.style': [/\bchain(?:\s+style)?\b/i],
};

const LOCALIZED_SIGNALS = [
  /\b(?:left|right|upper|lower|top|bottom)\s+(?:side|prong|stone|shoulder|area|part)\b/i,
  /\b(?:this|that|one)\s+(?:side|prong|stone|shoulder|area|part)\b/i,
  /\b(?:here|there|marked|circled|highlighted)\b/i,
] as const;

const STRUCTURAL_SIGNALS = [
  /\b(?:band|shank|gallery|basket|prong|setting|mount|clasp)\b/i,
  /\b(?:wider|narrower|thicker|thinner|larger|smaller|resize|reshape|rebuild)\b/i,
  /\b(?:width|thickness|diameter|proportion|construction)\b/i,
] as const;

export function candidateCatalogPaths(instruction: string): readonly ComponentCatalogPath[] {
  return (Object.entries(PATH_SIGNALS) as [ComponentCatalogPath, readonly RegExp[]][])
    .filter(([, signals]) => signals.some((signal) => signal.test(instruction)))
    .map(([path]) => path);
}

const isReady = (
  targeting: StudioComponentTargeting | null,
  path: ComponentCatalogPath,
): boolean => targeting?.catalog_paths.some((candidate) => (
  candidate.component_path === path && candidate.status === 'ready'
)) ?? false;

export function routeRefineInstruction(input: {
  instruction: string;
  exactSpecification: boolean;
  targeting: StudioComponentTargeting | null;
  catalogs: readonly ComponentCatalog[];
}): RefineInstructionRoute {
  const instruction = input.instruction.trim();
  const normalizedInstruction = normalize(instruction);
  const candidatePaths = candidateCatalogPaths(instruction);
  const localized = LOCALIZED_SIGNALS.some((signal) => signal.test(instruction));
  const structural = STRUCTURAL_SIGNALS.some((signal) => signal.test(instruction));

  if (localized) return { kind: 'markup_required', instruction, reason: 'localized' };
  if (!input.exactSpecification && (candidatePaths.length > 0 || structural)) {
    return { kind: 'starting_facts_required', instruction, candidatePaths };
  }

  const readyPaths = candidatePaths.filter((path) => isReady(input.targeting, path));
  const optionMatches = input.catalogs.flatMap((catalog) => {
    if (!readyPaths.includes(catalog.component_path)) return [];
    return catalog.options
      .filter((option) => containsPhrase(normalizedInstruction, option.display)
        || containsPhrase(normalizedInstruction, option.id))
      .map((option) => ({ catalog, option }));
  });
  if (optionMatches.length === 1) {
    const [{ catalog, option }] = optionMatches;
    return {
      kind: 'catalog',
      instruction,
      componentPath: catalog.component_path,
      option,
      catalog,
    };
  }
  if (optionMatches.length > 1 || readyPaths.length > 0) {
    return { kind: 'component_choice', instruction, candidatePaths: readyPaths };
  }
  if (candidatePaths.length > 0) {
    return { kind: 'markup_required', instruction, reason: 'unsupported_component' };
  }
  if (structural) return { kind: 'markup_required', instruction, reason: 'structural' };
  return { kind: 'appearance', instruction };
}
