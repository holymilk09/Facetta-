import type {
  StudioAuthority, StudioContextRequirement, StudioOutputType,
} from './contracts';
import { getStudioAction } from './actions';

export const STUDIO_DESTINATION_IDS = [
  'library', 'client', 'marketing', 'factory',
] as const;

export type StudioDestinationId = typeof STUDIO_DESTINATION_IDS[number];

export interface StudioDestinationContext {
  activeProjectId: string | null;
  activeRevisionId: string | null;
  hasExactSpecification: boolean;
  factoryEnabled: boolean;
  factoryEligible: boolean;
}

export interface StudioDestinationDefinition {
  id: StudioDestinationId;
  label: string;
  description: string;
  contextRequirements: readonly StudioContextRequirement[];
  executionMode: 'instant_navigation' | 'candidate_job' | 'terminal_job';
  outputType: StudioOutputType;
  creditsPerOutput: number;
  authority: StudioAuthority;
  createsJob: boolean;
  isAvailable: (context: StudioDestinationContext) => boolean;
}

const hasSavedRevision = (context: StudioDestinationContext): boolean => (
  Boolean(context.activeProjectId) && Boolean(context.activeRevisionId)
);

const presentAction = getStudioAction('present');
const factoryAction = getStudioAction('factory');

const jobPolicy = (action: typeof presentAction | typeof factoryAction) => ({
  contextRequirements: action.contextRequirements,
  executionMode: action.executionMode as 'candidate_job' | 'terminal_job',
  outputType: action.outputType,
  creditsPerOutput: action.creditEstimate ?? 0,
  authority: action.authority ?? 'visual_preview',
  createsJob: action.createsJob,
});

/**
 * Product destinations are deliberately separate from Studio actions.
 * Library navigates to already-persisted design truth; it never copies an
 * asset, advances history, or creates a billable generation job.
 */
export const STUDIO_DESTINATIONS: readonly StudioDestinationDefinition[] = [
  {
    id: 'library',
    label: 'Library',
    description: 'View this saved revision with its family, variations, and history.',
    contextRequirements: ['active_project', 'active_revision'],
    executionMode: 'instant_navigation',
    outputType: 'none',
    creditsPerOutput: 0,
    authority: 'design_record',
    createsJob: false,
    isAvailable: hasSavedRevision,
  },
  {
    ...jobPolicy(presentAction),
    id: 'client',
    label: 'Client',
    description: 'Prepare one polished image for review or presentation.',
    isAvailable: hasSavedRevision,
  },
  {
    ...jobPolicy(presentAction),
    id: 'marketing',
    label: 'Marketing',
    description: 'Prepare a small reviewable ecommerce image set.',
    isAvailable: hasSavedRevision,
  },
  {
    ...jobPolicy(factoryAction),
    id: 'factory',
    label: 'Factory',
    description: 'Prepare an eligible exact revision for optional manufacturer review.',
    isAvailable: (context) => (
      hasSavedRevision(context)
      && context.hasExactSpecification
      && context.factoryEnabled
      && context.factoryEligible
    ),
  },
] as const;

export function getStudioDestination(
  id: StudioDestinationId,
): StudioDestinationDefinition {
  const destination = STUDIO_DESTINATIONS.find((candidate) => candidate.id === id);
  if (destination === undefined) throw new Error(`Unknown Studio destination: ${id}`);
  return destination;
}
