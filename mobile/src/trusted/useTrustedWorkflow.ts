import { useCallback, useEffect, useReducer, useRef } from 'react';
import type { TrustedApiClient } from './client';
import type { AnnotationCanvasSnapshot } from './AnnotationCanvas';
import {
  clearTrustedProjectId,
  loadTrustedProjectId,
  saveTrustedProjectId,
} from './feature';
import type {
  ApiError,
  AssetSummary,
  BeautyRenderRequest,
  ChecklistResponseRequest,
  CreateProjectFromBriefRequest,
  CreateProjectFromDrawingRequest,
  CreateProjectFromImageRequest,
  CreateProjectFromPromptRequest,
  JsonObject,
  LineArtSourceSelection,
  MarkupImpact,
  LineArtView,
  ProductPhotoRequest,
  ProjectDetail,
  WorkflowPhase,
} from './types';
import {
  canSelectPhase,
  initialTrustedWorkflowState,
  trustedWorkflowReducer,
  type TrustedWorkflowState,
} from './workflowState';

export interface MarkupConfirmation {
  target_region?: string;
  requested_change?: string;
  impact?: MarkupImpact;
  target_spec_reference?: string | null;
  target_section?: string | null;
  target_index?: number | null;
  target_component_id?: string | null;
  target_element_id?: string | null;
  form_view?: 'front' | 'side' | 'top' | 'three_quarter';
  mask_base64?: string | null;
}

export interface TrustedWorkflowOptions {
  designer: string;
  initialProjectId?: string | null;
  restoreLastProject?: boolean;
  enabled?: boolean;
}

export interface TrustedWorkflowController {
  state: TrustedWorkflowState;
  createFromBrief: (request: Omit<CreateProjectFromBriefRequest, 'owner'>) => Promise<void>;
  createFromPrompt: (request: Omit<CreateProjectFromPromptRequest, 'owner'>) => Promise<void>;
  createFromDrawing: (request: Omit<CreateProjectFromDrawingRequest, 'owner'>) => Promise<void>;
  createFromImage: (request: Omit<CreateProjectFromImageRequest, 'owner'>) => Promise<void>;
  openProject: (projectId: string) => Promise<void>;
  refreshProject: () => Promise<void>;
  selectPhase: (phase: WorkflowPhase) => void;
  readMarkup: (
    markedImage: string | AnnotationCanvasSnapshot,
    assetId?: string,
  ) => Promise<void>;
  confirmMarkup: (confirmation?: MarkupConfirmation) => Promise<void>;
  applyConfirmedMarkup: () => Promise<void>;
  createBeautyRender: (
    instruction?: BeautyRenderRequest['instruction'],
  ) => Promise<void>;
  createProductPhoto: (
    request: Omit<
      ProductPhotoRequest,
      'created_by' | 'expected_asset_id' | 'expected_design_version'
    >,
  ) => Promise<void>;
  createLineArt: (
    view: LineArtView,
    sourceSelection?: LineArtSourceSelection,
  ) => Promise<void>;
  colorizeLineArt: (lineArtAssetId: string) => Promise<void>;
  regenerateWarningCandidate: () => Promise<void>;
  acceptWarningCandidate: () => Promise<void>;
  discardWarningCandidate: () => void;
  discardMarkup: () => void;
  startApproval: () => Promise<void>;
  loadApproval: () => Promise<void>;
  respondToApproval: (
    request: Omit<ChecklistResponseRequest, 'created_by'>,
  ) => Promise<void>;
  loadFactoryPack: () => Promise<void>;
  clearError: () => void;
  clearWorkspace: () => void;
  canAcceptWarningCandidate: boolean;
}

function localError(
  code: string,
  message: string,
  category: ApiError['category'] = 'validation',
): ApiError {
  return {
    code,
    message,
    category,
    status: 0,
    retryable: false,
  };
}

function activeAssetId(state: TrustedWorkflowState): string | null {
  return state.project?.active_asset_id
    ?? state.project?.active_revision?.asset_id
    ?? null;
}

export function selectBeautyRenderSource(project: ProjectDetail): AssetSummary | null {
  const version = project.active_design_version;
  const active = project.active_revision
    ?? project.assets.find((asset) => asset.asset_id === project.active_asset_id)
    ?? null;
  if (version === null || active === null || active.design_version !== version
    || active.root_id !== project.root_id) return null;
  const assetsById = new Map<string, AssetSummary>();
  for (const asset of [
    ...project.assets,
    ...project.revisions.map((revision) => revision.asset),
    ...project.derived_assets,
    active,
  ]) assetsById.set(asset.asset_id, asset);
  const isAncestor = (ancestorId: string, descendantId: string): boolean => {
    const visited = new Set<string>();
    let currentId: string | null = descendantId;
    while (currentId !== null && !visited.has(currentId)) {
      if (currentId === ancestorId) return true;
      visited.add(currentId);
      currentId = assetsById.get(currentId)?.parent_asset_id ?? null;
    }
    return false;
  };
  const sharesActiveLineage = (candidate: AssetSummary): boolean =>
    isAncestor(candidate.asset_id, active.asset_id)
    || isAncestor(active.asset_id, candidate.asset_id);
  const confirmedColoredLineArt = project.derived_assets
    .filter((asset) => asset.capability === 'COLORED_LINE_ART'
      && asset.design_version === version
      && asset.root_id === project.root_id
      && sharesActiveLineage(asset))
    .at(-1) ?? null;
  if (confirmedColoredLineArt !== null) return confirmedColoredLineArt;
  return active.capability === 'IMPORTED_REFERENCE' ? active : null;
}

/**
 * Behavior-only controller for the trusted workspace. Presentation is kept in
 * a separate screen so the parallel redesign can replace it without rewriting
 * request, recovery, or concurrency rules.
 */
export function useTrustedWorkflow(
  api: TrustedApiClient,
  options: TrustedWorkflowOptions,
): TrustedWorkflowController {
  const [state, dispatch] = useReducer(trustedWorkflowReducer, initialTrustedWorkflowState);
  const stateRef = useRef(state);
  const restoredRef = useRef(false);
  const loadSequenceRef = useRef(0);
  const retryVariantRef = useRef(0);
  const briefRequestRef = useRef<
    Omit<CreateProjectFromBriefRequest, 'owner'> | null
  >(null);
  const beautyRenderInstructionRef = useRef<string | null>(null);
  const productPhotoRequestRef = useRef<
    Omit<
      ProductPhotoRequest,
      'created_by' | 'expected_asset_id' | 'expected_design_version'
    > | null
  >(null);
  const lineArtViewRef = useRef<LineArtView | null>(null);
  const lineArtSourceSelectionRef = useRef<LineArtSourceSelection | null>(null);
  const colorizeLineArtAssetRef = useRef<string | null>(null);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const loadProject = useCallback(async (
    projectId: string,
    source: 'open' | 'refresh',
    silent = false,
  ): Promise<void> => {
    const cleanId = projectId.trim();
    if (!cleanId) {
      dispatch({
        type: 'operation_failed',
        operation: source === 'open' ? 'restore' : 'refresh',
        error: localError('PROJECT_ID_REQUIRED', 'Choose a project to open.'),
      });
      return;
    }
    const operation = source === 'open' ? 'restore' : 'refresh';
    if (!silent) dispatch({ type: 'operation_started', operation });
    const sequence = ++loadSequenceRef.current;
    const result = await api.getProject(cleanId);
    if (sequence !== loadSequenceRef.current) return;
    if (result.error !== null) {
      if (!silent) dispatch({ type: 'operation_failed', operation, error: result.error });
      return;
    }
    saveTrustedProjectId(result.data.id);
    dispatch({ type: 'project_loaded', project: result.data, source });
  }, [api]);

  const openProject = useCallback(async (projectId: string): Promise<void> => {
    await loadProject(projectId, 'open');
  }, [loadProject]);

  useEffect(() => {
    if (restoredRef.current || options.enabled === false) return;
    restoredRef.current = true;
    const recover = options.initialProjectId
      ?? (options.restoreLastProject === false ? null : loadTrustedProjectId());
    if (recover !== null) void openProject(recover);
  }, [openProject, options.enabled, options.initialProjectId, options.restoreLastProject]);

  const createFromBrief = useCallback(async (
    request: Omit<CreateProjectFromBriefRequest, 'owner'>,
  ): Promise<void> => {
    if (!request.brief.trim()) {
      dispatch({
        type: 'operation_failed',
        operation: 'create',
        error: localError('BRIEF_REQUIRED', 'Describe the ring before creating it.'),
      });
      return;
    }
    dispatch({ type: 'operation_started', operation: 'create' });
    briefRequestRef.current = request;
    const result = await api.createProjectFromBrief({
      ...request,
      brief: request.brief.trim(),
      owner: options.designer,
    });
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'create', error: result.error });
      return;
    }
    if ('warning_candidate' in result.data) {
      dispatch({
        type: 'creation_warning_received',
        warning: result.data.warning_candidate,
      });
      return;
    }
    retryVariantRef.current = 0;
    saveTrustedProjectId(result.data.id);
    dispatch({ type: 'project_loaded', project: result.data, source: 'create' });
  }, [api, options.designer]);

  const createFromImage = useCallback(async (
    request: Omit<CreateProjectFromImageRequest, 'owner'>,
  ): Promise<void> => {
    if (!request.image_base64.trim()) {
      dispatch({
        type: 'operation_failed',
        operation: 'create',
        error: localError('IMAGE_REQUIRED', 'Add the confirmed reference image.'),
      });
      return;
    }
    dispatch({ type: 'operation_started', operation: 'create' });
    const result = await api.createProjectFromImage({
      ...request,
      image_base64: request.image_base64.trim(),
      owner: options.designer,
    });
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'create', error: result.error });
      return;
    }
    retryVariantRef.current = 0;
    saveTrustedProjectId(result.data.id);
    dispatch({ type: 'project_loaded', project: result.data, source: 'create' });
  }, [api, options.designer]);

  const createFromPrompt = useCallback(async (
    request: Omit<CreateProjectFromPromptRequest, 'owner'>,
  ): Promise<void> => {
    if (!request.prompt.trim()) {
      dispatch({
        type: 'operation_failed',
        operation: 'create',
        error: localError(
          'CREATIVE_PROMPT_REQUIRED',
          'Describe the jewelry idea you want Facetta to visualize.',
        ),
      });
      return;
    }
    dispatch({ type: 'operation_started', operation: 'create' });
    const result = await api.createProjectFromPrompt({
      ...request,
      prompt: request.prompt.trim(),
      owner: options.designer,
    });
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'create', error: result.error });
      return;
    }
    retryVariantRef.current = 0;
    saveTrustedProjectId(result.data.id);
    dispatch({ type: 'project_loaded', project: result.data, source: 'create' });
  }, [api, options.designer]);

  const createFromDrawing = useCallback(async (
    request: Omit<CreateProjectFromDrawingRequest, 'owner'>,
  ): Promise<void> => {
    if (!request.image_base64.trim()) {
      dispatch({
        type: 'operation_failed',
        operation: 'create',
        error: localError('IMAGE_REQUIRED', 'Add the drawing or jewelry reference.'),
      });
      return;
    }
    if (!request.instruction?.trim()) {
      dispatch({
        type: 'operation_failed',
        operation: 'create',
        error: localError(
          'CREATIVE_DIRECTION_REQUIRED',
          'Describe the finish or presentation you want from this source.',
        ),
      });
      return;
    }
    dispatch({ type: 'operation_started', operation: 'create' });
    const result = await api.createProjectFromDrawing({
      ...request,
      image_base64: request.image_base64.trim(),
      instruction: request.instruction.trim(),
      ...(request.source_region_description === undefined
        ? {}
        : { source_region_description: request.source_region_description.trim() }),
      ...(request.source_region === undefined
        ? {}
        : { source_region: { ...request.source_region } }),
      owner: options.designer,
    });
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'create', error: result.error });
      return;
    }
    retryVariantRef.current = 0;
    saveTrustedProjectId(result.data.id);
    dispatch({ type: 'project_loaded', project: result.data, source: 'create' });
  }, [api, options.designer]);

  const refreshProject = useCallback(async (): Promise<void> => {
    const projectId = stateRef.current.project_id;
    if (projectId === null) return;
    await loadProject(projectId, 'refresh');
  }, [loadProject]);

  const refreshAfterStale = useCallback(async (): Promise<void> => {
    const projectId = stateRef.current.project_id;
    if (projectId === null) return;
    await loadProject(projectId, 'refresh', true);
  }, [loadProject]);

  const selectPhase = useCallback((phase: WorkflowPhase): void => {
    if (canSelectPhase(stateRef.current, phase)) {
      dispatch({ type: 'phase_selected', phase });
    }
  }, []);

  const readMarkup = useCallback(async (
    markedImage: string | AnnotationCanvasSnapshot,
    requestedAssetId?: string,
  ): Promise<void> => {
    const current = stateRef.current;
    if (current.pending_markup !== null || current.warning_candidate !== null) {
      dispatch({
        type: 'operation_failed',
        operation: 'read_markup',
        error: localError(
          'ANNOTATION_ALREADY_OPEN',
          'Finish or discard the current annotation before reading another.',
          'conflict',
        ),
      });
      return;
    }
    const assetId = requestedAssetId ?? activeAssetId(current);
    if (assetId === null) {
      dispatch({
        type: 'operation_failed',
        operation: 'read_markup',
        error: localError('ACTIVE_ASSET_REQUIRED', 'This project has no active image to mark.'),
      });
      return;
    }
    const hasMarkup = typeof markedImage === 'string'
      ? markedImage.trim().length > 0
      : markedImage.annotations.length > 0;
    if (!hasMarkup) {
      dispatch({
        type: 'operation_failed',
        operation: 'read_markup',
        error: localError('MARKUP_REQUIRED', 'Draw or write on the image before reading it.'),
      });
      return;
    }
    dispatch({ type: 'operation_started', operation: 'read_markup' });
    const result = await api.readMarkup(assetId, {
      ...(typeof markedImage === 'string'
        ? { marked_image_base64: markedImage.trim() }
        : { markup_snapshot: markedImage }),
      created_by: options.designer,
    });
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'read_markup', error: result.error });
      return;
    }
    dispatch({ type: 'markup_interpreted', base_asset_id: assetId, response: result.data });
  }, [api, options.designer]);

  const confirmMarkup = useCallback(async (
    confirmation: MarkupConfirmation = {},
  ): Promise<void> => {
    const current = stateRef.current;
    const pending = current.pending_markup;
    const designVersion = current.project?.active_design_version;
    if (pending === null || designVersion === null || designVersion === undefined) {
      dispatch({
        type: 'operation_failed',
        operation: 'read_markup',
        error: localError(
          'CONFIRMATION_UNAVAILABLE',
          'Refresh the project and read the annotation before confirming it.',
          'conflict',
        ),
      });
      return;
    }
    const source = pending.interpretation;
    const region = confirmation.target_region?.trim() || source.target_region;
    const change = confirmation.requested_change?.trim() || source.requested_change;
    const impact = confirmation.impact ?? source.impact;
    if (!region || !change) {
      dispatch({
        type: 'operation_failed',
        operation: 'read_markup',
        error: localError('CONFIRMATION_INCOMPLETE', 'Confirm both the region and requested change.'),
      });
      return;
    }
    if (source.impact === 'specification' && impact !== 'specification') {
      dispatch({
        type: 'operation_failed',
        operation: 'read_markup',
        error: localError(
          'SPEC_SYNC_REQUIRED',
          'This changes a manufacturing fact, so the image and specification must move together.',
        ),
      });
      return;
    }
    const targetSection = confirmation.target_section === undefined
      ? source.target_section
      : confirmation.target_section;
    const targetReference = confirmation.target_spec_reference === undefined
      ? source.target_spec_reference
      : confirmation.target_spec_reference;
    const targetElementId = confirmation.target_element_id === undefined
      ? source.target_element_id
      : confirmation.target_element_id;
    const targetComponentId = confirmation.target_component_id === undefined
      ? source.target_component_id
      : confirmation.target_component_id;
    if (impact === 'specification' && targetSection === null
      && targetReference === null && targetElementId === null) {
      dispatch({
        type: 'operation_failed',
        operation: 'read_markup',
        error: localError(
          'SPEC_TARGET_REQUIRED',
          'Facetta must identify the exact specification section before applying this manufacturing change.',
        ),
      });
      return;
    }
    const targetIndex = confirmation.target_index === undefined
      ? source.target_index : confirmation.target_index;
    const changesInterpretation = region !== source.target_region
      || change !== source.requested_change
      || impact !== source.impact
      || targetSection !== source.target_section
      || targetReference !== source.target_spec_reference
      || targetIndex !== source.target_index
      || targetComponentId !== source.target_component_id
      || targetElementId !== source.target_element_id
      || (confirmation.form_view !== undefined && confirmation.form_view !== 'three_quarter')
      || (confirmation.mask_base64 !== undefined && confirmation.mask_base64 !== null);
    if (changesInterpretation) {
      dispatch({
        type: 'operation_failed',
        operation: 'read_markup',
        error: localError(
          'MARKUP_REINTERPRETATION_REQUIRED',
          'Edit the marks and read them again so the confirmed target remains bound to exact image evidence.',
          'conflict',
        ),
      });
      return;
    }
    dispatch({ type: 'operation_started', operation: 'read_markup' });
    const result = await api.confirmMarkupInterpretation(
      pending.base_asset_id,
      pending.interpretation_id,
      { created_by: options.designer },
    );
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'read_markup', error: result.error });
      return;
    }
    if (result.data.confirmed_interpretation_id !== pending.interpretation_id
        || result.data.markup_asset_id !== pending.markup_asset_id
        || result.data.expected_design_version !== designVersion) {
      dispatch({
        type: 'operation_failed',
        operation: 'read_markup',
        error: localError(
          'MARKUP_CONFIRMATION_MISMATCH',
          'The confirmed interpretation no longer matches this exact revision. Read the marks again.',
          'conflict',
        ),
      });
      return;
    }
    dispatch({
      type: 'markup_confirmed',
      annotation: result.data.annotation,
      confirmed_interpretation_id: result.data.confirmed_interpretation_id,
      expected_design_version: designVersion,
    });
  }, [api, options.designer]);

  const runConfirmedMarkup = useCallback(async (variant: number): Promise<void> => {
    const current = stateRef.current;
    const pending = current.pending_markup;
    if (pending?.confirmed === null || pending?.confirmed === undefined
      || pending.confirmed_interpretation_id === null
      || pending.expected_design_version === null) {
      dispatch({
        type: 'operation_failed',
        operation: 'apply_markup',
        error: localError(
          'ANNOTATION_CONFIRMATION_REQUIRED',
          'Confirm Facetta’s interpretation before applying the change.',
          'conflict',
        ),
      });
      return;
    }
    dispatch({ type: 'operation_started', operation: 'apply_markup' });
    const result = await api.applyMarkup(pending.base_asset_id, {
      annotation: pending.confirmed,
      markup_asset_id: pending.markup_asset_id,
      confirmed_interpretation_id: pending.confirmed_interpretation_id,
      expected_design_version: pending.expected_design_version,
      created_by: options.designer,
      variant,
    });
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'apply_markup', error: result.error });
      if (result.error.category === 'stale_version') await refreshAfterStale();
      return;
    }
    if (result.data.qa.verdict === 'fail') {
      dispatch({
        type: 'operation_failed',
        operation: 'apply_markup',
        error: localError(
          'IMAGE_QUALITY_FAILED',
          result.data.qa.summary || 'The candidate failed jewelry image checks.',
          'quality',
        ),
      });
      return;
    }
    dispatch({ type: 'markup_applied', response: result.data });
    if (result.data.qa.verdict === 'pass') {
      retryVariantRef.current = 0;
      const projectId = stateRef.current.project_id;
      if (projectId !== null) await loadProject(projectId, 'refresh', true);
    }
  }, [api, loadProject, options.designer, refreshAfterStale]);

  const applyConfirmedMarkup = useCallback(async (): Promise<void> => {
    await runConfirmedMarkup(retryVariantRef.current);
  }, [runConfirmedMarkup]);

  const runBeautyRender = useCallback(async (
    instruction: string,
    variant: number,
    allowOpenWarning = false,
  ): Promise<void> => {
    const current = stateRef.current;
    const project = current.project;
    const active = project?.active_revision
      ?? project?.assets.find((asset) => asset.asset_id === project.active_asset_id)
      ?? null;
    const source = project === null ? null : selectBeautyRenderSource(project);
    const designVersion = project?.active_design_version;
    if (project === null || active === null || source === null
      || designVersion === null || designVersion === undefined) {
      dispatch({
        type: 'operation_failed',
        operation: 'beauty_render',
        error: localError(
          'CONFIRMED_REFERENCE_REQUIRED',
          'Open an exact designer-confirmed imported reference or confirmed colored line-art source before creating its beauty render.',
          'conflict',
        ),
      });
      return;
    }
    if (current.pending_markup !== null
      || (current.warning_candidate !== null && !allowOpenWarning)) {
      dispatch({
        type: 'operation_failed',
        operation: 'beauty_render',
        error: localError(
          'REVIEW_ALREADY_OPEN',
          'Finish or discard the current annotation or candidate first.',
          'conflict',
        ),
      });
      return;
    }
    const normalizedInstruction = instruction.trim()
      || 'Create a beauty render faithful to the current designer-confirmed specification and preserve the imported design identity.';
    beautyRenderInstructionRef.current = normalizedInstruction;
    dispatch({ type: 'operation_started', operation: 'beauty_render' });
    const result = await api.createBeautyRender(project.id, {
      created_by: options.designer,
      expected_asset_id: active.asset_id,
      source_asset_id: source.asset_id,
      expected_design_version: designVersion,
      instruction: normalizedInstruction,
      variant,
    });
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'beauty_render', error: result.error });
      if (result.error.category === 'stale_version') await refreshAfterStale();
      return;
    }
    if (result.data.status === 'review_required') {
      dispatch({
        type: 'beauty_render_warning_received',
        warning: {
          ...result.data.warning_candidate,
          requested_change: normalizedInstruction,
        },
      });
      return;
    }
    retryVariantRef.current = 0;
    beautyRenderInstructionRef.current = null;
    saveTrustedProjectId(result.data.project.id);
    dispatch({ type: 'project_loaded', project: result.data.project, source: 'refresh' });
  }, [api, options.designer, refreshAfterStale]);

  const createBeautyRender = useCallback(async (
    instruction = '',
  ): Promise<void> => {
    retryVariantRef.current = 0;
    await runBeautyRender(instruction, 0);
  }, [runBeautyRender]);

  const runProductPhoto = useCallback(async (
    request: Omit<
      ProductPhotoRequest,
      'created_by' | 'expected_asset_id' | 'expected_design_version'
    >,
    variant: number,
    allowOpenWarning = false,
  ): Promise<void> => {
    const current = stateRef.current;
    const project = current.project;
    const assetId = activeAssetId(current);
    const designVersion = project?.active_design_version;
    if (project === null || assetId === null || designVersion === null
      || designVersion === undefined) {
      dispatch({
        type: 'operation_failed',
        operation: 'product_photo',
        error: localError(
          'ACTIVE_REVISION_REQUIRED',
          'Open a project with an exact image/spec revision before creating product photography.',
          'conflict',
        ),
      });
      return;
    }
    if (current.pending_markup !== null
      || (current.warning_candidate !== null && !allowOpenWarning)) {
      dispatch({
        type: 'operation_failed',
        operation: 'product_photo',
        error: localError(
          'REVIEW_ALREADY_OPEN',
          'Finish or discard the current annotation or candidate first.',
          'conflict',
        ),
      });
      return;
    }
    dispatch({ type: 'operation_started', operation: 'product_photo' });
    productPhotoRequestRef.current = request;
    const result = await api.createProductPhoto(project.id, {
      ...request,
      created_by: options.designer,
      expected_asset_id: assetId,
      expected_design_version: designVersion,
      variant,
    });
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'product_photo', error: result.error });
      if (result.error.category === 'stale_version') await refreshAfterStale();
      return;
    }
    if (result.data.status === 'review_required') {
      dispatch({
        type: 'product_photo_warning_received',
        warning: result.data.warning_candidate,
      });
      return;
    }
    retryVariantRef.current = 0;
    productPhotoRequestRef.current = null;
    saveTrustedProjectId(result.data.project.id);
    dispatch({ type: 'project_loaded', project: result.data.project, source: 'refresh' });
  }, [api, options.designer, refreshAfterStale]);

  const createProductPhoto = useCallback(async (
    request: Omit<
      ProductPhotoRequest,
      'created_by' | 'expected_asset_id' | 'expected_design_version'
    >,
  ): Promise<void> => {
    retryVariantRef.current = request.variant ?? 0;
    await runProductPhoto(request, retryVariantRef.current);
  }, [runProductPhoto]);

  const runLineArt = useCallback(async (
    view: LineArtView,
    sourceSelection: LineArtSourceSelection | undefined,
    variant: number,
    allowOpenWarning = false,
  ): Promise<void> => {
    const current = stateRef.current;
    const project = current.project;
    const assetId = activeAssetId(current);
    const designVersion = project?.active_design_version;
    if (project === null || assetId === null || designVersion === null
      || designVersion === undefined) {
      dispatch({
        type: 'operation_failed', operation: 'line_art',
        error: localError('ACTIVE_REVISION_REQUIRED',
          'Open an exact image/spec revision before creating line art.', 'conflict'),
      });
      return;
    }
    if (current.pending_markup !== null
      || (current.warning_candidate !== null && !allowOpenWarning)) {
      dispatch({
        type: 'operation_failed', operation: 'line_art',
        error: localError('REVIEW_ALREADY_OPEN',
          'Finish or discard the current annotation or candidate first.', 'conflict'),
      });
      return;
    }
    dispatch({ type: 'operation_started', operation: 'line_art' });
    lineArtViewRef.current = view;
    lineArtSourceSelectionRef.current = sourceSelection === undefined
      ? null
      : {
          ...(sourceSelection.source_region_description === undefined
            ? {}
            : { source_region_description: sourceSelection.source_region_description }),
          ...(sourceSelection.source_region === undefined
            ? {}
            : { source_region: { ...sourceSelection.source_region } }),
        };
    const result = await api.createLineArt(project.id, {
      created_by: options.designer,
      expected_asset_id: assetId,
      expected_design_version: designVersion,
      view,
      ...lineArtSourceSelectionRef.current,
      variant,
    });
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'line_art', error: result.error });
      if (result.error.category === 'stale_version') await refreshAfterStale();
      return;
    }
    dispatch({ type: 'drawing_confirmation_received', candidate: result.data.candidate });
  }, [api, options.designer, refreshAfterStale]);

  const createLineArt = useCallback(async (
    view: LineArtView,
    sourceSelection?: LineArtSourceSelection,
  ): Promise<void> => {
    retryVariantRef.current = 0;
    await runLineArt(view, sourceSelection, 0);
  }, [runLineArt]);

  const runColorizeLineArt = useCallback(async (
    lineArtAssetId: string,
    variant: number,
    allowOpenWarning = false,
  ): Promise<void> => {
    const current = stateRef.current;
    const project = current.project;
    const assetId = activeAssetId(current);
    const designVersion = project?.active_design_version;
    if (project === null || assetId === null || designVersion === null
      || designVersion === undefined) return;
    if (current.pending_markup !== null
      || (current.warning_candidate !== null && !allowOpenWarning)) {
      dispatch({
        type: 'operation_failed', operation: 'line_art',
        error: localError('REVIEW_ALREADY_OPEN',
          'Finish or discard the current annotation or candidate first.', 'conflict'),
      });
      return;
    }
    dispatch({ type: 'operation_started', operation: 'line_art' });
    colorizeLineArtAssetRef.current = lineArtAssetId;
    const result = await api.colorizeLineArt(project.id, lineArtAssetId, {
      created_by: options.designer,
      expected_asset_id: assetId,
      expected_design_version: designVersion,
      variant,
    });
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'line_art', error: result.error });
      if (result.error.category === 'stale_version') await refreshAfterStale();
      return;
    }
    if (result.data.status === 'review_required') {
      dispatch({ type: 'drawing_confirmation_received', candidate: result.data.candidate });
      return;
    }
    colorizeLineArtAssetRef.current = null;
    saveTrustedProjectId(result.data.project.id);
    dispatch({ type: 'project_loaded', project: result.data.project, source: 'refresh' });
  }, [api, options.designer, refreshAfterStale]);

  const colorizeLineArt = useCallback(async (lineArtAssetId: string): Promise<void> => {
    retryVariantRef.current = 0;
    await runColorizeLineArt(lineArtAssetId, 0);
  }, [runColorizeLineArt]);

  const regenerateWarningCandidate = useCallback(async (): Promise<void> => {
    const warning = stateRef.current.warning_candidate;
    if (warning === null) return;
    await api.recordImageRunFeedback(
      warning.run_id,
      'regenerated',
      options.designer,
    );
    retryVariantRef.current += 1;
    if (stateRef.current.project === null) {
      const request = briefRequestRef.current;
      if (request === null) return;
      await createFromBrief({
        ...request,
        variant: retryVariantRef.current,
      });
      return;
    }
    if (warning.operation === 'SPEC_RENDER'
      && beautyRenderInstructionRef.current !== null) {
      const instruction = beautyRenderInstructionRef.current;
      dispatch({ type: 'warning_discarded' });
      await runBeautyRender(instruction, retryVariantRef.current, true);
      return;
    }
    if (warning.operation === 'VISUAL_ONLY_EDIT'
      && stateRef.current.pending_markup === null
      && productPhotoRequestRef.current !== null) {
      const request = productPhotoRequestRef.current;
      dispatch({ type: 'warning_discarded' });
      await runProductPhoto({ ...request, variant: retryVariantRef.current },
        retryVariantRef.current, true);
      return;
    }
    if (warning.asset_capability === 'LINE_ART' && lineArtViewRef.current !== null) {
      dispatch({ type: 'warning_discarded' });
      await runLineArt(
        lineArtViewRef.current,
        lineArtSourceSelectionRef.current ?? undefined,
        retryVariantRef.current,
        true,
      );
      return;
    }
    if (warning.asset_capability === 'COLORED_LINE_ART'
      && colorizeLineArtAssetRef.current !== null) {
      dispatch({ type: 'warning_discarded' });
      await runColorizeLineArt(
        colorizeLineArtAssetRef.current, retryVariantRef.current, true);
      return;
    }
    await runConfirmedMarkup(retryVariantRef.current);
  }, [
    api, createFromBrief, options.designer, runColorizeLineArt,
    runBeautyRender, runConfirmedMarkup, runLineArt, runProductPhoto,
  ]);

  const acceptWarningCandidate = useCallback(async (): Promise<void> => {
    const current = stateRef.current;
    if (current.warning_candidate === null) return;
    const candidateId = current.warning_candidate.candidate_id;
    const reviewOperation = current.warning_candidate.operation === 'SPEC_RENDER'
      ? 'beauty_render'
      : 'apply_markup';
    if (candidateId === null) {
      dispatch({
        type: 'operation_failed',
        operation: reviewOperation,
        error: localError(
          'WARNING_PROMOTION_UNAVAILABLE',
          'This temporary candidate has no reviewable specification binding. Regenerate or discard it.',
          'conflict',
        ),
      });
      return;
    }
    dispatch({ type: 'operation_started', operation: reviewOperation });
    if (current.project === null) {
      const result = await api.acceptBriefWarningCandidate(
        candidateId,
        options.designer,
      );
      if (result.error !== null) {
        dispatch({
          type: 'operation_failed',
          operation: reviewOperation,
          error: result.error,
        });
        return;
      }
      await api.recordImageRunFeedback(
        current.warning_candidate.run_id,
        'accepted',
        options.designer,
      );
      if ('warning_candidate' in result.data) {
        dispatch({
          type: 'creation_warning_received',
          warning: result.data.warning_candidate,
        });
        return;
      }
      retryVariantRef.current = 0;
      saveTrustedProjectId(result.data.id);
      dispatch({ type: 'project_loaded', project: result.data, source: 'create' });
      return;
    }
    const expectedVersion = current.project.active_design_version;
    if (expectedVersion === null) {
      dispatch({
        type: 'operation_failed',
        operation: reviewOperation,
        error: localError(
          'WARNING_PROMOTION_UNAVAILABLE',
          'This candidate has no exact specification version. Regenerate or discard it.',
          'conflict',
        ),
      });
      return;
    }
    const result = await api.acceptWarningCandidate(
      current.warning_candidate.run_id,
      candidateId,
      expectedVersion,
      options.designer,
    );
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: reviewOperation, error: result.error });
      return;
    }
    await api.recordImageRunFeedback(
      current.warning_candidate.run_id,
      'accepted',
      options.designer,
    );
    if (current.warning_candidate.operation === 'VISUAL_ONLY_EDIT'
      && current.pending_markup === null) {
      productPhotoRequestRef.current = null;
    }
    if (current.warning_candidate.operation === 'SPEC_RENDER') {
      beautyRenderInstructionRef.current = null;
    }
    if (current.warning_candidate.asset_capability === 'LINE_ART') {
      lineArtViewRef.current = null;
      lineArtSourceSelectionRef.current = null;
    }
    if (current.warning_candidate.asset_capability === 'COLORED_LINE_ART') {
      colorizeLineArtAssetRef.current = null;
    }
    dispatch({ type: 'warning_discarded' });
    saveTrustedProjectId(result.data.id);
    dispatch({ type: 'project_loaded', project: result.data, source: 'refresh' });
  }, [api, options.designer]);

  const discardWarningCandidate = useCallback((): void => {
    const warning = stateRef.current.warning_candidate;
    if (warning !== null) {
      void api.recordImageRunFeedback(
        warning.run_id,
        'rejected',
        options.designer,
      );
    }
    if (warning?.operation === 'VISUAL_ONLY_EDIT'
      && stateRef.current.pending_markup === null) {
      productPhotoRequestRef.current = null;
    }
    if (warning?.operation === 'SPEC_RENDER') beautyRenderInstructionRef.current = null;
    if (warning?.asset_capability === 'LINE_ART') {
      lineArtViewRef.current = null;
      lineArtSourceSelectionRef.current = null;
    }
    if (warning?.asset_capability === 'COLORED_LINE_ART') {
      colorizeLineArtAssetRef.current = null;
    }
    dispatch({ type: 'warning_discarded' });
  }, [api, options.designer]);

  const discardMarkup = useCallback((): void => {
    retryVariantRef.current = 0;
    dispatch({ type: 'markup_discarded' });
  }, []);

  const loadApprovalForAsset = useCallback(async (assetId: string): Promise<void> => {
    dispatch({ type: 'operation_started', operation: 'approval' });
    const result = await api.getChecklist(assetId);
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'approval', error: result.error });
      return;
    }
    dispatch({ type: 'approval_loaded', approval: result.data });
  }, [api]);

  const startApproval = useCallback(async (): Promise<void> => {
    const assetId = activeAssetId(stateRef.current);
    if (assetId === null) return;
    dispatch({ type: 'operation_started', operation: 'approval' });
    const result = await api.createChecklist(assetId, { created_by: options.designer });
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'approval', error: result.error });
      return;
    }
    dispatch({ type: 'approval_loaded', approval: result.data });
  }, [api, options.designer]);

  const loadApproval = useCallback(async (): Promise<void> => {
    const assetId = activeAssetId(stateRef.current);
    if (assetId !== null) await loadApprovalForAsset(assetId);
  }, [loadApprovalForAsset]);

  const respondToApproval = useCallback(async (
    request: Omit<ChecklistResponseRequest, 'created_by'>,
  ): Promise<void> => {
    const assetId = activeAssetId(stateRef.current);
    if (assetId === null) return;
    if (!request.approved && !request.note?.trim()) {
      dispatch({
        type: 'operation_failed',
        operation: 'approval',
        error: localError('CHANGE_NOTE_REQUIRED', 'A “No” answer needs the requested change.'),
      });
      return;
    }
    dispatch({ type: 'operation_started', operation: 'approval' });
    const result = await api.respondChecklist(assetId, {
      ...request,
      note: request.note?.trim(),
      created_by: options.designer,
    });
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'approval', error: result.error });
      return;
    }
    const refreshed = await api.getChecklist(assetId);
    if (refreshed.error !== null) {
      dispatch({ type: 'approval_loaded', approval: result.data });
      return;
    }
    dispatch({ type: 'approval_loaded', approval: refreshed.data });
    const projectId = stateRef.current.project_id;
    if (projectId !== null) await loadProject(projectId, 'refresh', true);
  }, [api, loadProject, options.designer]);

  const loadFactoryPack = useCallback(async (): Promise<void> => {
    const current = stateRef.current;
    if (current.project_id === null || current.project?.factory_ready !== true) {
      dispatch({
        type: 'operation_failed',
        operation: 'factory_pack',
        error: localError(
          'FACTORY_APPROVAL_REQUIRED',
          'Approve every fact and pin this exact revision before generating the factory pack.',
          'conflict',
        ),
      });
      return;
    }
    dispatch({ type: 'operation_started', operation: 'factory_pack' });
    const result = await api.getFactoryPack(current.project_id);
    if (result.error !== null) {
      dispatch({ type: 'operation_failed', operation: 'factory_pack', error: result.error });
      return;
    }
    dispatch({ type: 'factory_pack_loaded', manifest: result.data });
  }, [api]);

  const clearError = useCallback((): void => dispatch({ type: 'error_cleared' }), []);

  const clearWorkspace = useCallback((): void => {
    loadSequenceRef.current += 1;
    retryVariantRef.current = 0;
    beautyRenderInstructionRef.current = null;
    lineArtViewRef.current = null;
    lineArtSourceSelectionRef.current = null;
    clearTrustedProjectId();
    dispatch({ type: 'workspace_cleared' });
  }, []);

  return {
    state,
    createFromBrief,
    createFromPrompt,
    createFromDrawing,
    createFromImage,
    openProject,
    refreshProject,
    selectPhase,
    readMarkup,
    confirmMarkup,
    applyConfirmedMarkup,
    createBeautyRender,
    createProductPhoto,
    createLineArt,
    colorizeLineArt,
    regenerateWarningCandidate,
    acceptWarningCandidate,
    discardWarningCandidate,
    discardMarkup,
    startApproval,
    loadApproval,
    respondToApproval,
    loadFactoryPack,
    clearError,
    clearWorkspace,
    canAcceptWarningCandidate: state.warning_candidate !== null
      && state.warning_candidate.candidate_id !== null,
  };
}
