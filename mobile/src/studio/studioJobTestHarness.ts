import type {
  ApiResult,
  CreateStudioJobRequest,
  StudioJobRecord,
  TransitionStudioJobRequest,
} from '../trusted/types';

const ok = <T>(data: T, status = 200): ApiResult<T> => ({ data, error: null, status });

/** Minimal durable Activity fake for gateway contract tests. */
export function createStudioJobTestHarness(jobId = 'studio_job_test') {
  let created: CreateStudioJobRequest | null = null;
  const transitions: TransitionStudioJobRequest[] = [];

  const record = (
    request: CreateStudioJobRequest,
    status: StudioJobRecord['status'],
    progress: number,
    transition?: TransitionStudioJobRequest,
  ): StudioJobRecord => {
    const completedOutputs = transition?.completed_outputs ?? 0;
    return {
      job_id: jobId,
      owner: request.owner,
      action_id: request.action_id,
      lane: request.lane,
      status,
      progress,
      active_design_id: transition?.active_design_id ?? request.active_design_id ?? null,
      source_revision_id: transition?.source_revision_id ?? request.source_revision_id ?? null,
      error_code: transition?.error_code ?? null,
      created_at: '2026-07-12T00:00:00Z',
      updated_at: '2026-07-12T00:00:01Z',
      billing: {
        requested_outputs: request.requested_outputs,
        credits_per_output: request.credits_per_output,
        estimated_credits: request.requested_outputs * request.credits_per_output,
        completed_outputs: completedOutputs,
        charged_outputs: completedOutputs,
        charged_credits: completedOutputs * request.credits_per_output,
        policy: 'Only accepted requested outputs are charged.',
      },
    };
  };

  return {
    jobId,
    transitions,
    client: {
      createStudioJob: async (request: CreateStudioJobRequest) => {
        created = request;
        return ok(record(request, 'queued', 0), 201);
      },
      transitionStudioJob: async (_jobId: string, request: TransitionStudioJobRequest) => {
        if (created === null) throw new Error('Studio job was not created.');
        transitions.push(request);
        return ok(record(created, request.status, request.progress, request));
      },
    },
  };
}
