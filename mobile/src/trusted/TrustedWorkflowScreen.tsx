import React, { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';
import { AuthenticatedImage as Image } from '../AuthenticatedImage';
import { Button, ChipRow, Field, Notice, Section } from '../components';
import { theme } from '../theme';
import {
  AnnotationCanvas,
  type AnnotationCanvasSnapshot,
} from './AnnotationCanvas';
import type { TrustedApiClient } from './client';
import { ComponentCatalogPanel } from './ComponentCatalogPanel';
import { DraftFactorySheetPreview } from './DraftFactorySheetPreview';
import { FactoryFactEditor } from './FactoryFactEditor';
import { TRUSTED_WORKSPACE_ENABLED } from './feature';
import {
  changedSourceCoverageResolutions,
  sourceCoverageAllowsCreation,
  SourceCoverageCorrectionPanel,
  sourceCoverageDrafts,
  sourceCoverageDraftsValid,
  type SourceCoverageCorrectionDraft,
  type SourceCoverageCorrectionDrafts,
} from './SourceCoverageCorrectionPanel';
import { StudioHistoryPanel } from './StudioHistoryPanel';
import type {
  JsonObject,
  JsonValue,
  LineArtView,
  MarkupImpact,
  MarketingPackResult,
  ProductPhotoFraming,
  ProductPhotoPreset,
  ProjectComment,
  SourceCoverageResolutionResult,
  WorkflowPhase,
} from './types';
import {
  selectBeautyRenderSource,
  useTrustedWorkflow,
} from './useTrustedWorkflow';
import { canSelectPhase } from './workflowState';

const PHASES: readonly WorkflowPhase[] = ['create', 'refine', 'approve', 'factory'];
const PRODUCT_PHOTO_PRESETS: readonly ProductPhotoPreset[] = [
  'catalog_white', 'luxury_studio', 'dark_editorial', 'macro_detail',
];
const PRODUCT_PHOTO_FRAMINGS: readonly ProductPhotoFraming[] = [
  'portrait', 'square', 'source',
];
const LINE_ART_VIEWS: readonly LineArtView[] = ['front', 'three_quarter', 'side'];
type StudioDestination = 'library' | 'client' | 'marketing';

export interface TrustedWorkflowScreenProps {
  api: TrustedApiClient;
  designer: string;
  initialProjectId?: string | null;
  enabled?: boolean;
  onOpenAdvancedSpecifications?: (designId: string, version: number) => void;
  /** Test/preview seam; production uses the live window width. */
  viewportWidth?: number;
}

const isJsonValue = (value: unknown): value is JsonValue => {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJsonValue);
  if (typeof value !== 'object') return false;
  return Object.values(value).every(isJsonValue);
};

function parseSpec(value: string): JsonObject | null {
  try {
    const parsed: unknown = JSON.parse(value);
    if (parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)
      && isJsonValue(parsed)) {
      return parsed as JsonObject;
    }
  } catch {
    // The screen displays a precise correction below.
  }
  return null;
}

const phaseLabel = (phase: WorkflowPhase): string => {
  switch (phase) {
    case 'create': return 'Create';
    case 'refine': return 'Explore';
    case 'approve': return 'Review';
    case 'factory': return 'Factory handoff';
  }
};

const phaseHeading = (phase: WorkflowPhase): { title: string; body: string } => {
  switch (phase) {
    case 'create':
      return {
        title: 'Start a new direction',
        body: 'Describe an idea or begin from an image. Details can come later.',
      };
    case 'refine':
      return {
        title: 'Choose a direction to develop',
        body: 'Keep it for inspiration, add it to a collection, create client or marketing visuals, or confirm it later for production.',
      };
    case 'approve':
      return {
        title: 'Review and organize this design',
        body: 'Approve a revision, keep exploring, or prepare a presentation for someone else.',
      };
    case 'factory':
      return {
        title: 'Optional factory handoff',
        body: 'Only use this destination when this specific revision is ready for production review.',
      };
  }
};

function WorkspaceDisclosure({
  title,
  subtitle,
  open,
  onPress,
  children,
}: {
  title: string;
  subtitle: string;
  open: boolean;
  onPress: () => void;
  children: React.ReactNode;
}) {
  return (
    <View style={styles.disclosureCard}>
      <Pressable style={styles.disclosureHeader} onPress={onPress}>
        <View style={styles.disclosureCopy}>
          <Text style={styles.disclosureTitle}>{title}</Text>
          <Text style={styles.disclosureSubtitle}>{subtitle}</Text>
        </View>
        <Text style={styles.disclosureIcon}>{open ? '−' : '+'}</Text>
      </Pressable>
      {open && <View style={styles.disclosureBody}>{children}</View>}
    </View>
  );
}

const valueLabel = (value: JsonValue): string => {
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
};

export function TrustedWorkflowScreen({
  api,
  designer,
  initialProjectId = null,
  enabled = TRUSTED_WORKSPACE_ENABLED,
  onOpenAdvancedSpecifications,
  viewportWidth,
}: TrustedWorkflowScreenProps) {
  const { width } = useWindowDimensions();
  const isWide = (viewportWidth ?? width) >= 760;
  const workflow = useTrustedWorkflow(api, {
    designer,
    initialProjectId,
    enabled,
  });
  const { state } = workflow;

  const [createMode, setCreateMode] = useState<
    'prompt' | 'brief' | 'drawing' | 'reference'
  >('prompt');
  const [creativePrompt, setCreativePrompt] = useState('');
  const [brief, setBrief] = useState('');
  const [title, setTitle] = useState('');
  const [collection, setCollection] = useState('');
  const [referenceBase64, setReferenceBase64] = useState('');
  const [referenceKind, setReferenceKind] = useState<'finished_photo' | 'design_plate'>('finished_photo');
  const [referenceMediaType, setReferenceMediaType] = useState('image/png');
  const [referenceNotes, setReferenceNotes] = useState('');
  const [creativeDirection, setCreativeDirection] = useState(
    'Create a polished fine-jewelry beauty render faithful to every visible design element in this source.',
  );
  const [creativeVariationCount, setCreativeVariationCount] = useState<1 | 2 | 3 | 4>(1);
  const [referenceScaleAnchor, setReferenceScaleAnchor] = useState('');
  const [plateUncertainties, setPlateUncertainties] = useState<string[]>([]);
  const [confirmedSpec, setConfirmedSpec] = useState('');
  const [extractingReference, setExtractingReference] = useState(false);
  const [sourceCoverage, setSourceCoverage] = useState<
    SourceCoverageResolutionResult | null
  >(null);
  const [coverageDrafts, setCoverageDrafts] = useState<
    SourceCoverageCorrectionDrafts
  >({});
  const [coverageBusy, setCoverageBusy] = useState<'apply' | 'audit' | null>(null);
  const [referenceSpecChangedAfterAudit, setReferenceSpecChangedAfterAudit] = useState(false);
  const [projectToOpen, setProjectToOpen] = useState('');
  const [markupSnapshot, setMarkupSnapshot] = useState<AnnotationCanvasSnapshot | null>(null);
  const [confirmedRegion, setConfirmedRegion] = useState('');
  const [confirmedChange, setConfirmedChange] = useState('');
  const [confirmedImpact, setConfirmedImpact] = useState<MarkupImpact>('specification');
  const [approvalNotes, setApprovalNotes] = useState<Record<string, string>>({});
  const [localNotice, setLocalNotice] = useState<string | null>(null);
  const [localInfo, setLocalInfo] = useState<string | null>(null);
  const [showCandidateNotes, setShowCandidateNotes] = useState(false);
  const [showCandidateFacts, setShowCandidateFacts] = useState(false);
  const [showEvidenceDetails, setShowEvidenceDetails] = useState(false);
  const [showRevisionHistory, setShowRevisionHistory] = useState(false);
  const [activeDestination, setActiveDestination] = useState<StudioDestination>('library');
  const [comments, setComments] = useState<ProjectComment[]>([]);
  const [commentBody, setCommentBody] = useState('');
  const [commentsBusy, setCommentsBusy] = useState(false);
  const [beautyRenderDirection, setBeautyRenderDirection] = useState('');
  const [productPhotoPreset, setProductPhotoPreset] = useState<ProductPhotoPreset>('catalog_white');
  const [productPhotoFraming, setProductPhotoFraming] = useState<ProductPhotoFraming>('portrait');
  const [productPhotoDirection, setProductPhotoDirection] = useState('');
  const [marketingPresets, setMarketingPresets] = useState<ProductPhotoPreset[]>([
    'catalog_white',
  ]);
  const [marketingPack, setMarketingPack] = useState<MarketingPackResult | null>(null);
  const [marketingBusy, setMarketingBusy] = useState(false);
  const [lineArtView, setLineArtView] = useState<LineArtView>('three_quarter');
  const [creativeCandidateId, setCreativeCandidateId] = useState<string | null>(null);
  const [creativeDraftNotes, setCreativeDraftNotes] = useState('');
  const [creativeDraftSpec, setCreativeDraftSpec] = useState('');
  const [creativeDraftCoverage, setCreativeDraftCoverage] = useState<
    SourceCoverageResolutionResult | null
  >(null);
  const [creativeDraftSpecChangedAfterAudit, setCreativeDraftSpecChangedAfterAudit] = (
    useState(false)
  );
  const [creativeCoverageDrafts, setCreativeCoverageDrafts] = useState<
    SourceCoverageCorrectionDrafts
  >({});
  const [creativeConfirmations, setCreativeConfirmations] = useState<
    Record<string, { basis: 'visible_source' | 'designer_defined_target'; description: string }>
  >({});
  const [creativeDraftBusy, setCreativeDraftBusy] = useState(false);
  const referenceDraftSequenceRef = useRef(0);

  useEffect(() => {
    const interpretation = state.pending_markup?.interpretation;
    if (interpretation === undefined) return;
    setConfirmedRegion(interpretation.target_region);
    setConfirmedChange(interpretation.requested_change);
    setConfirmedImpact(interpretation.impact);
  }, [state.pending_markup?.interpretation]);

  useEffect(() => {
    setComments([]);
    setCommentBody('');
    setMarkupSnapshot(null);
    setShowCandidateNotes(false);
    setShowCandidateFacts(false);
    setShowEvidenceDetails(false);
    setShowRevisionHistory(false);
    setActiveDestination('library');
  }, [state.project?.id]);

  useEffect(() => {
    setCreativeCandidateId(null);
    setCreativeDraftSpec('');
    setCreativeDraftCoverage(null);
    setCreativeDraftSpecChangedAfterAudit(false);
    setCreativeCoverageDrafts({});
    setCreativeConfirmations({});
    setCreativeDraftBusy(false);
    setMarketingPack(null);
    setMarketingBusy(false);
  }, [state.project?.id]);

  useEffect(() => {
    setMarkupSnapshot(null);
  }, [state.project?.active_asset_id]);

  if (!enabled) {
    return (
      <View style={styles.disabledWrap}>
        <Section title="Trusted workspace">
          <Notice
            kind="info"
            text="The internal trusted workflow is disabled. Set EXPO_PUBLIC_TRUSTED_WORKSPACE=true after acceptance testing."
          />
        </Section>
      </View>
    );
  }

  const clearReferenceCoverage = (): void => {
    setPlateUncertainties([]);
    setSourceCoverage(null);
    setCoverageDrafts({});
    setCoverageBusy(null);
    setReferenceSpecChangedAfterAudit(false);
  };

  const changeReferenceImage = (value: string): void => {
    referenceDraftSequenceRef.current += 1;
    setReferenceBase64(value);
    setConfirmedSpec('');
    clearReferenceCoverage();
  };

  const changeReferenceKind = (
    value: 'finished_photo' | 'design_plate',
  ): void => {
    referenceDraftSequenceRef.current += 1;
    setReferenceKind(value);
    setConfirmedSpec('');
    clearReferenceCoverage();
  };

  const changeConfirmedSpec = (value: string): void => {
    referenceDraftSequenceRef.current += 1;
    setConfirmedSpec(value);
    if (sourceCoverage !== null) {
      setReferenceSpecChangedAfterAudit(true);
    }
  };

  const changeCoverageDraft = (
    componentId: string,
    draft: SourceCoverageCorrectionDraft,
  ): void => {
    setCoverageDrafts((current) => ({ ...current, [componentId]: draft }));
  };

  const createProject = async (): Promise<void> => {
    setLocalNotice(null);
    setLocalInfo(null);
    if (createMode === 'prompt') {
      await workflow.createFromPrompt({
        prompt: creativePrompt,
        variation_count: creativeVariationCount,
        title: title.trim() || 'Jewelry concept exploration',
        ...(collection.trim() ? { collection: collection.trim() } : {}),
      });
      return;
    }
    if (createMode === 'brief') {
      await workflow.createFromBrief({
        brief,
        ...(title.trim() ? { title: title.trim() } : {}),
        ...(collection.trim() ? { collection: collection.trim() } : {}),
      });
      return;
    }
    if (createMode === 'drawing') {
      await workflow.createFromDrawing({
        image_base64: referenceBase64,
        media_type: referenceMediaType === 'image/jpeg'
          || referenceMediaType === 'image/webp'
          ? referenceMediaType
          : 'image/png',
        instruction: creativeDirection,
        variation_count: creativeVariationCount,
        title: title.trim() || 'Creative jewelry study',
        ...(collection.trim() ? { collection: collection.trim() } : {}),
      });
      return;
    }
    if (!sourceCoverageAllowsCreation(sourceCoverage, referenceSpecChangedAfterAudit)) {
      setLocalNotice(
        'Resolve every visible reference component and complete a passing independent source audit before creating this project.',
      );
      return;
    }
    const spec = parseSpec(confirmedSpec);
    if (spec === null) {
      setLocalNotice('The confirmed specification must be a valid JSON object.');
      return;
    }
    await workflow.createFromImage({
      image_base64: referenceBase64,
      ...(referenceKind === 'finished_photo' ? { media_type: referenceMediaType } : {}),
      confirmed_spec: spec,
      title: title.trim() || 'Confirmed reference ring',
      ...(collection.trim() ? { collection: collection.trim() } : {}),
    });
  };

  const extractReferenceDraft = async (): Promise<void> => {
    setLocalNotice(null);
    setLocalInfo(null);
    if (!referenceBase64.trim()) {
      setLocalNotice('Add the reference image before extracting its draft specification.');
      return;
    }
    setExtractingReference(true);
    setPlateUncertainties([]);
    const requestSequence = ++referenceDraftSequenceRef.current;
    if (referenceKind === 'design_plate') {
      const result = await api.extractPlateDraft({
        image_base64: referenceBase64.trim(),
        scale_anchor: referenceScaleAnchor.trim(),
        notes: referenceNotes.trim(),
        created_by: designer,
      });
      setExtractingReference(false);
      if (requestSequence !== referenceDraftSequenceRef.current) return;
      if (result.error !== null) {
        setLocalNotice(result.error.message);
        return;
      }
      setConfirmedSpec(JSON.stringify(result.data.spec, null, 2));
      setPlateUncertainties(result.data.uncertainties);
      setSourceCoverage(result.data.source_coverage);
      setCoverageDrafts(sourceCoverageDrafts(result.data.source_coverage.components));
      setReferenceSpecChangedAfterAudit(false);
      const coverage = result.data.source_coverage_audit;
      setLocalInfo(
        coverage.status === 'pass'
          ? 'Design plate read and independently cross-audited. Review the preserved groups and confirm the specification before creating the project.'
          : `Design plate read. ${coverage.blocker_count} source-coverage blocker${coverage.blocker_count === 1 ? '' : 's'} remain; resolve every uncertainty before factory release.`,
      );
      return;
    }
    const mediaType = referenceMediaType === 'image/png'
      || referenceMediaType === 'image/jpeg'
      || referenceMediaType === 'image/webp'
      ? referenceMediaType
      : null;
    if (mediaType === null) {
      setExtractingReference(false);
      setLocalNotice('Reference media type must be image/png, image/jpeg, or image/webp.');
      return;
    }
    const result = await api.extractImageDraft({
      image_base64: referenceBase64.trim(),
      media_type: mediaType,
      notes: referenceNotes.trim(),
      created_by: designer,
    });
    setExtractingReference(false);
    if (requestSequence !== referenceDraftSequenceRef.current) return;
    if (result.error !== null) {
      setLocalNotice(result.error.message);
      return;
    }
    setConfirmedSpec(JSON.stringify(result.data.spec, null, 2));
    setSourceCoverage(result.data.source_coverage);
    setCoverageDrafts(sourceCoverageDrafts(result.data.source_coverage.components));
    setReferenceSpecChangedAfterAudit(false);
    setLocalInfo(
      result.data.source_coverage.audit.status === 'pass'
        ? 'Finished reference read and independently cross-audited. Review every visible component and confirm estimated dimensions before creating the project.'
        : `${result.data.source_coverage.blockers.length} source-coverage blocker${result.data.source_coverage.blockers.length === 1 ? '' : 's'} remain in the finished reference. Correct the mappings and re-run the independent audit.`,
    );
  };

  const resolveReferenceSourceCoverage = async (
    runIndependentAudit: boolean,
  ): Promise<void> => {
    setLocalNotice(null);
    setLocalInfo(null);
    const spec = parseSpec(confirmedSpec);
    if (spec === null || sourceCoverage === null) {
      setLocalNotice('Extract and retain a valid reference draft before resolving source coverage.');
      return;
    }
    if (runIndependentAudit && !referenceBase64.trim()) {
      setLocalNotice('The original reference image is required to re-run its independent source audit.');
      return;
    }
    const resolutions = runIndependentAudit
      ? []
      : changedSourceCoverageResolutions(sourceCoverage, coverageDrafts);
    if (!runIndependentAudit) {
      if (!sourceCoverageDraftsValid(sourceCoverage, coverageDrafts)) {
        setLocalNotice('Each component needs at least one existing path or a specific unresolved note.');
        return;
      }
      if (resolutions.length === 0) {
        setLocalNotice('Change at least one component decision before applying the batch.');
        return;
      }
    }
    setCoverageBusy(runIndependentAudit ? 'audit' : 'apply');
    const requestSequence = ++referenceDraftSequenceRef.current;
    const result = await api.resolveSourceCoverage({
      spec,
      source_image_base64: runIndependentAudit ? referenceBase64.trim() : null,
      resolutions,
      created_by: designer,
      run_independent_audit: runIndependentAudit,
    });
    setCoverageBusy(null);
    if (requestSequence !== referenceDraftSequenceRef.current) return;
    if (result.error !== null) {
      setLocalNotice(result.error.message);
      return;
    }
    setConfirmedSpec(JSON.stringify(result.data.spec, null, 2));
    setSourceCoverage(result.data);
    setCoverageDrafts(sourceCoverageDrafts(result.data.components));
    setReferenceSpecChangedAfterAudit(false);
    if (result.data.audit.status === 'pass' && result.data.blockers.length === 0) {
      setLocalInfo(
        'Every stable source component passed independent accounting. Review and confirm physical measurements separately before creating the project.',
      );
    } else if (result.data.audit.status === 'unavailable'
      || result.data.audit.status === 'invalid') {
      setLocalInfo(
        'The independent source audit did not complete. The corrected draft is preserved, but project creation remains blocked.',
      );
    } else {
      setLocalInfo(
        `${result.data.blockers.length} source-coverage blocker${result.data.blockers.length === 1 ? '' : 's'} remain. Correct the mapped components and re-run the independent audit.`,
      );
    }
  };

  const loadProjectComments = async (): Promise<void> => {
    const designId = state.project?.design_id;
    if (designId === null || designId === undefined) return;
    setCommentsBusy(true);
    const result = await api.listProjectComments(designId);
    setCommentsBusy(false);
    if (result.error !== null) {
      setLocalNotice(result.error.message);
      return;
    }
    setComments(result.data);
  };

  const postProjectComment = async (): Promise<void> => {
    const designId = state.project?.design_id;
    if (designId === null || designId === undefined || !commentBody.trim()) return;
    setCommentsBusy(true);
    const result = await api.postProjectComment(designId, {
      author: designer,
      body: commentBody.trim(),
      version: state.project?.active_design_version ?? null,
    });
    setCommentsBusy(false);
    if (result.error !== null) {
      setLocalNotice(result.error.message);
      return;
    }
    setComments((current) => [...current, result.data]);
    setCommentBody('');
  };

  const toggleMarketingPreset = (preset: ProductPhotoPreset): void => {
    setMarketingPresets((current) => current.includes(preset)
      ? current.filter((item) => item !== preset)
      : [...current, preset]);
  };

  const createMarketingPack = async (): Promise<void> => {
    const project = state.project;
    if (project === null || project.active_asset_id === null
      || project.active_design_version === null || marketingPresets.length === 0) return;
    setMarketingBusy(true);
    setLocalNotice(null);
    const result = await api.createMarketingPack(project.id, {
      created_by: designer,
      expected_asset_id: project.active_asset_id,
      expected_design_version: project.active_design_version,
      presets: marketingPresets,
      framing: productPhotoFraming,
      custom_instruction: productPhotoDirection.trim(),
    });
    setMarketingBusy(false);
    if (result.error !== null) {
      setLocalNotice(result.error.message);
      return;
    }
    setMarketingPack(result.data);
    setLocalInfo(
      `${result.data.candidate_count}/${result.data.requested_count} presentation candidate${result.data.candidate_count === 1 ? '' : 's'} ready for explicit review. The active design and approval did not change.`,
    );
  };

  const acceptMarketingCandidate = async (
    candidate: MarketingPackResult['candidates'][number],
  ): Promise<void> => {
    const version = state.project?.active_design_version;
    if (version === null || version === undefined) return;
    setMarketingBusy(true);
    const result = await api.acceptWarningCandidate(
      candidate.image_run_id,
      candidate.candidate_id,
      version,
      designer,
    );
    if (result.error !== null) {
      setMarketingBusy(false);
      setLocalNotice(result.error.message);
      return;
    }
    await api.recordImageRunFeedback(
      candidate.image_run_id,
      'accepted',
      designer,
    );
    setMarketingPack((current) => current === null ? null : ({
      ...current,
      candidate_count: Math.max(0, current.candidate_count - 1),
      candidates: current.candidates.filter(
        (item) => item.candidate_id !== candidate.candidate_id,
      ),
    }));
    setMarketingBusy(false);
    await workflow.refreshProject();
    setLocalInfo(
      'Marketing image saved as a derived presentation asset. The active design revision, specification, approval, and factory readiness remain unchanged.',
    );
  };

  const extractCreativeCandidateDraft = async (
    candidateId: string,
  ): Promise<void> => {
    if (state.project === null || state.project.design_id !== null) return;
    setLocalNotice(null);
    setLocalInfo(null);
    setCreativeCandidateId(candidateId);
    setCreativeDraftBusy(true);
    const result = await api.extractCreativeCandidateDraft(
      state.project.id,
      candidateId,
      {
        notes: creativeDraftNotes.trim(),
        created_by: designer,
        run_independent_audit: true,
      },
    );
    setCreativeDraftBusy(false);
    if (result.error !== null) {
      setLocalNotice(result.error.message);
      return;
    }
    setCreativeDraftSpec(JSON.stringify(result.data.spec, null, 2));
    setCreativeDraftCoverage(result.data.source_coverage);
    setCreativeDraftSpecChangedAfterAudit(false);
    setCreativeCoverageDrafts(sourceCoverageDrafts(
      result.data.source_coverage.components,
    ));
    setCreativeConfirmations({});
    setLocalInfo(
      result.data.source_coverage.factory_ready
        ? 'Candidate draft passed independent source accounting. Review every fact before promotion.'
        : `${result.data.source_coverage.blockers.length} source-evidence blocker${result.data.source_coverage.blockers.length === 1 ? '' : 's'} remain. This candidate cannot become factory authority yet.`,
    );
  };

  const resolveCreativeCandidateCoverage = async (
    runIndependentAudit: boolean,
  ): Promise<void> => {
    if (state.project === null || creativeCandidateId === null
      || creativeDraftCoverage === null) return;
    const spec = parseSpec(creativeDraftSpec);
    if (spec === null) {
      setLocalNotice('The selected candidate specification must be valid JSON.');
      return;
    }
    const resolutions = runIndependentAudit
      ? []
      : changedSourceCoverageResolutions(
        creativeDraftCoverage,
        creativeCoverageDrafts,
      );
    if (!runIndependentAudit
      && !sourceCoverageDraftsValid(
        creativeDraftCoverage,
        creativeCoverageDrafts,
      )) {
      setLocalNotice('Each candidate component needs a valid mapping or a specific unresolved note.');
      return;
    }
    setCreativeDraftBusy(true);
    const result = await api.resolveCreativeCandidateCoverage(
      state.project.id,
      creativeCandidateId,
      {
        spec,
        resolutions,
        created_by: designer,
        run_independent_audit: runIndependentAudit,
      },
    );
    setCreativeDraftBusy(false);
    if (result.error !== null) {
      setLocalNotice(result.error.message);
      return;
    }
    setCreativeDraftSpec(JSON.stringify(result.data.spec, null, 2));
    setCreativeDraftCoverage(result.data);
    if (runIndependentAudit) setCreativeDraftSpecChangedAfterAudit(false);
    setCreativeCoverageDrafts(sourceCoverageDrafts(result.data.components));
    setLocalInfo(result.data.factory_ready
      ? 'Candidate source accounting is complete. Review the draft and promote only if every fact is correct.'
      : `${result.data.blockers.length} candidate source blocker${result.data.blockers.length === 1 ? '' : 's'} remain.`);
  };

  const confirmCreativeCandidateCoverage = async (): Promise<void> => {
    if (state.project === null || creativeCandidateId === null) return;
    const spec = parseSpec(creativeDraftSpec);
    if (spec === null) {
      setLocalNotice('The selected candidate specification must be valid JSON.');
      return;
    }
    const componentIds = creativeDraftCoverage?.blockers
      .filter((blocker) => blocker.code === 'source_component_audit_inconclusive')
      .map((blocker) => blocker.component_id) ?? [];
    const confirmations = componentIds.map((componentId) => ({
      component_id: componentId,
      basis: creativeConfirmations[componentId]?.basis ?? 'visible_source' as const,
      confirmed_description: creativeConfirmations[componentId]?.description.trim() ?? '',
    }));
    if (confirmations.length === 0
      || confirmations.some((confirmation) => !confirmation.confirmed_description)) {
      setLocalNotice('Write a specific designer confirmation for every inconclusive component.');
      return;
    }
    setCreativeDraftBusy(true);
    const result = await api.confirmCreativeCandidateCoverage(
      state.project.id,
      creativeCandidateId,
      { spec, confirmations, created_by: designer },
    );
    setCreativeDraftBusy(false);
    if (result.error !== null) {
      setLocalNotice(result.error.message);
      return;
    }
    setCreativeDraftSpec(JSON.stringify(result.data.spec, null, 2));
    setCreativeDraftCoverage(result.data);
    setCreativeCoverageDrafts(sourceCoverageDrafts(result.data.components));
    setLocalInfo(result.data.factory_ready
      ? 'Designer confirmations are bound to this exact candidate and specification.'
      : `${result.data.blockers.length} source blocker${result.data.blockers.length === 1 ? '' : 's'} remain.`);
  };

  const explainStudioConfirmMigration = (): void => {
    setLocalNotice(
      'This legacy draft cannot create Design v1 because its corrected specification is not bound to the new confirmation record. Open Studio, select this visual, and choose Confirm. Your legacy draft has not been saved as design truth.',
    );
  };

  const active = state.project?.active_revision;
  const activeImageUrl = active?.image_url
    ?? (state.project?.active_asset_id
      ? api.assetImageUrl(state.project.active_asset_id)
      : null);
  const beautyRenderSource = state.project === null
    ? null
    : selectBeautyRenderSource(state.project);
  const approval = state.approval ?? state.project?.approval ?? null;
  const confirmedLineArt = state.project?.derived_assets
    .filter((asset) => asset.capability === 'LINE_ART')
    .at(-1) ?? null;
  const coloredLineArt = state.project?.derived_assets
    .filter((asset) => asset.capability === 'COLORED_LINE_ART')
    .at(-1) ?? null;

  const currentHeading = phaseHeading(state.phase);
  const workflowHeader = (
    <View style={styles.workflowHeader}>
      <Text style={styles.workspaceEyebrow}>FACETTA STUDIO</Text>
      <Text style={styles.workspaceTitle}>{currentHeading.title}</Text>
      <Text style={styles.workspaceBody}>{currentHeading.body}</Text>
      <View style={styles.phaseNav}>
        {PHASES.filter((phase) => phase !== 'factory').map((phase) => {
          const disabled = !canSelectPhase(state, phase);
          return (
            <Pressable
              key={phase}
              disabled={disabled}
              onPress={() => workflow.selectPhase(phase)}
              style={[
                styles.phaseButton,
                state.phase === phase && styles.phaseButtonActive,
                disabled && styles.phaseButtonDisabled,
              ]}>
              <Text style={[
                styles.phaseText,
                state.phase === phase && styles.phaseTextActive,
              ]}>
                {phaseLabel(phase)}
              </Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );

  const createPanel = (
    <>
      {!isWide && (
        <Notice
          kind="info"
          text="Mobile is review-only in this milestone. Open an existing project here; create and annotate on desktop or tablet."
        />
      )}
      <Section title="Recover a project">
        <Field
          label="Project ID"
          value={projectToOpen}
          onChange={setProjectToOpen}
          placeholder="project or root id"
        />
        <Button
          title="Open project"
          kind="ghost"
          disabled={!projectToOpen.trim() || state.busy !== null}
          onPress={() => void workflow.openProject(projectToOpen)}
        />
      </Section>
      {isWide && (
        <Section title="Create a jewelry project">
          <ChipRow
            label="Starting point"
            options={['prompt', 'drawing', 'brief', 'reference'] as const}
            value={createMode}
            onSelect={setCreateMode}
            render={(mode) => mode === 'prompt'
              ? 'Describe an idea'
              : mode === 'drawing'
                ? 'Drawing / image first'
                : mode === 'brief'
                  ? 'Structured ring brief'
                  : 'Factory-spec reference'}
          />
          {createMode === 'prompt' ? (
            <>
              <Notice
                kind="info"
                text="Describe any jewelry idea in your own words. Facetta creates visual directions first without pretending they are measurements or factory specifications. More candidates cost more image-generation attempts."
              />
              <Field
                label="Designer direction"
                value={creativePrompt}
                onChange={setCreativePrompt}
                multiline
                placeholder="A platinum floral lariat necklace with emerald leaves, delicate articulated stems, and an asymmetric drop…"
              />
              <ChipRow
                label="Visual directions"
                options={[1, 2, 3, 4] as const}
                value={creativeVariationCount}
                onSelect={setCreativeVariationCount}
                render={(count) => `${count} candidate${count === 1 ? '' : 's'}`}
              />
            </>
          ) : createMode === 'brief' ? (
            <Field
              label="Structured ring brief"
              value={brief}
              onChange={setBrief}
              multiline
              placeholder="An oval sapphire solitaire in 18k yellow gold…"
            />
          ) : createMode === 'drawing' ? (
            <>
              <Notice
                kind="info"
                text="Facetta will attempt the strongest faithful render it can from any valid drawing or jewelry image. It does not grade the source or invent factory measurements. You can request up to four distinct candidates; each adds image-generation cost."
              />
              <Field
                label="Drawing or jewelry image (base64 from the upload adapter)"
                value={referenceBase64}
                onChange={changeReferenceImage}
                multiline
                placeholder="Add the uploaded source image bytes."
              />
              <Field
                label="Media type"
                value={referenceMediaType}
                onChange={setReferenceMediaType}
              />
              <Field
                label="Designer direction"
                value={creativeDirection}
                onChange={setCreativeDirection}
                multiline
                placeholder="Keep the exact silhouette and stone layout; render in polished rose gold on a clean studio background."
              />
              <ChipRow
                label="Render candidates"
                options={[1, 2, 3, 4] as const}
                value={creativeVariationCount}
                onSelect={setCreativeVariationCount}
                render={(count) => `${count} candidate${count === 1 ? '' : 's'}`}
              />
            </>
          ) : (
            <>
              <Field
                label="Reference image (base64 from the upload/canvas adapter)"
                value={referenceBase64}
                onChange={changeReferenceImage}
                multiline
                placeholder="Paste the uploaded image bytes from the canvas adapter."
              />
              <ChipRow
                label="Reference kind"
                options={['finished_photo', 'design_plate'] as const}
                value={referenceKind}
                onSelect={changeReferenceKind}
                render={(kind) => kind === 'design_plate'
                  ? 'Hand drawing / design plate'
                  : 'Finished jewelry photo'}
              />
              {referenceKind === 'finished_photo' ? (
                <Field
                  label="Media type"
                  value={referenceMediaType}
                  onChange={setReferenceMediaType}
                />
              ) : (
                <Field
                  label="Known scale anchor"
                  value={referenceScaleAnchor}
                  onChange={setReferenceScaleAnchor}
                  placeholder="Optional, e.g. center stone width 8 mm"
                />
              )}
              <Field
                label="Known measurements or correction notes"
                value={referenceNotes}
                onChange={setReferenceNotes}
                multiline
                placeholder="Optional known ring size, stone dimensions, metal, or setting facts."
              />
              <Button
                title={extractingReference
                  ? 'Extracting a draft specification…'
                  : 'Extract draft from reference'}
                kind="ghost"
                disabled={!referenceBase64.trim() || extractingReference
                  || coverageBusy !== null || state.busy !== null}
                onPress={() => void extractReferenceDraft()}
              />
              {parseSpec(confirmedSpec) !== null && (
                <FactoryFactEditor
                  spec={parseSpec(confirmedSpec)!}
                  client={api}
                  onChange={(spec) => changeConfirmedSpec(
                    JSON.stringify(spec, null, 2),
                  )}
                />
              )}
              <Field
                label="Advanced specification JSON"
                value={confirmedSpec}
                onChange={changeConfirmedSpec}
                multiline
                placeholder="Advanced specification record; the image is saved only after validation."
              />
              {sourceCoverage !== null && (
                <SourceCoverageCorrectionPanel
                  coverage={sourceCoverage}
                  drafts={coverageDrafts}
                  busy={coverageBusy}
                  specChangedAfterAudit={referenceSpecChangedAfterAudit}
                  onDraftChange={changeCoverageDraft}
                  onApply={() => void resolveReferenceSourceCoverage(false)}
                  onAudit={() => void resolveReferenceSourceCoverage(true)}
                />
              )}
              {sourceCoverage === null && (
                <Notice
                  kind="info"
                  text="Extract the reference before project creation. Facetta will inventory each visible component and keep unresolved source details explicit."
                />
              )}
              {plateUncertainties.map((uncertainty) => (
                <Text key={uncertainty} style={styles.warningText}>• {uncertainty}</Text>
              ))}
            </>
          )}
          <Field label="Project title" value={title} onChange={setTitle} />
          <Field label="Collection" value={collection} onChange={setCollection} />
          <Button
            title={state.busy === 'create' ? 'Creating trusted record…' : 'Create project'}
            disabled={state.busy !== null || coverageBusy !== null
              || (createMode === 'prompt' && !creativePrompt.trim())
              || (createMode === 'brief' && !brief.trim())
              || ((createMode === 'drawing' || createMode === 'reference')
                && !referenceBase64.trim())
              || (createMode === 'drawing' && !creativeDirection.trim())
              || (createMode === 'reference'
                && !sourceCoverageAllowsCreation(
                  sourceCoverage,
                  referenceSpecChangedAfterAudit,
                ))}
            onPress={() => void createProject()}
          />
        </Section>
      )}
    </>
  );

  const interpretationPanel = state.pending_markup && (
    <Section title={state.pending_markup.confirmed ? 'Confirmed change' : 'Confirm Facetta’s understanding'}>
      {state.pending_markup.requires_reconfirmation && (
        <Notice
          kind="info"
          text="The project changed while this request was open. The interpretation was preserved, but it must be reconfirmed against the refreshed version."
        />
      )}
      <Field label="Target region" value={confirmedRegion} onChange={setConfirmedRegion} />
      <Field
        label="Requested change"
        value={confirmedChange}
        onChange={setConfirmedChange}
        multiline
      />
      <ChipRow
        label="Record impact — locked by the interpreted change"
        options={[confirmedImpact]}
        value={confirmedImpact}
        onSelect={setConfirmedImpact}
        render={(impact) => impact === 'specification'
          ? 'Image + specification'
          : 'Presentation only'}
      />
      {confirmedImpact === 'specification' && (
        <Notice
          kind="info"
          text="Geometry, stone, setting, metal, and dimensional changes cannot be forced through as image-only edits."
        />
      )}
      <Text style={styles.meta}>
        Frozen: {state.pending_markup.interpretation.frozen_elements.join(', ') || 'all unmarked elements'}
      </Text>
      <View style={styles.actionRow}>
        <Button
          title="Confirm understanding"
          disabled={!confirmedRegion.trim() || !confirmedChange.trim() || state.busy !== null}
          onPress={() => workflow.confirmMarkup({
            target_region: confirmedRegion,
            requested_change: confirmedChange,
            impact: confirmedImpact,
          })}
        />
        <Button title="Discard" kind="ghost" onPress={workflow.discardMarkup} />
      </View>
      {state.pending_markup.confirmed && !isWide && (
        <Notice
          kind="info"
          text="This interpretation is ready for review. Apply the revision from a desktop or tablet workspace."
        />
      )}
      {state.pending_markup.confirmed && isWide && (
        <Button
          title={state.busy === 'apply_markup' ? 'Validating the revision…' : 'Apply one confirmed change'}
          disabled={state.busy !== null || state.pending_markup.requires_reconfirmation}
          onPress={() => void workflow.applyConfirmedMarkup()}
        />
      )}
    </Section>
  );

  const warningPanel = state.warning_candidate && (
    <Section title={state.project === null
      ? 'Creation candidate needs designer review'
      : 'Candidate needs designer review'}>
      <Notice kind="info" text={state.warning_candidate.qa.summary} />
      {state.warning_candidate.preview_url && (
        <Image
          source={{ uri: state.warning_candidate.preview_url }}
          style={styles.warningPreview}
          resizeMode="contain"
        />
      )}
      {state.warning_candidate.qa.warnings.map((warning) => (
        <Text key={warning} style={styles.warningText}>• {warning}</Text>
      ))}
      <Text style={styles.meta}>
        {state.project === null
          ? 'This temporary candidate has not created a project or specification record.'
          : 'This temporary candidate is not the active asset and has not changed the specification.'}
      </Text>
      {!isWide && (
        <Notice
          kind="info"
          text="Review is available here. Accept or regenerate this candidate from a desktop or tablet workspace."
        />
      )}
      <View style={styles.actionRow}>
        {isWide && workflow.canAcceptWarningCandidate && (
          <Button title="Accept after review" onPress={() => void workflow.acceptWarningCandidate()} />
        )}
        {isWide && (
          <Button
            title="Regenerate"
            kind="ghost"
            disabled={state.busy !== null}
            onPress={() => void workflow.regenerateWarningCandidate()}
          />
        )}
        <Button title="Discard" kind="ghost" onPress={workflow.discardWarningCandidate} />
      </View>
    </Section>
  );

  const commentsPanel = state.project?.design_id && (
    <Section title="Project comments">
      <Text style={styles.meta}>
        Comments attach to this design and record the active spec version when posted.
      </Text>
      {comments.map((comment) => (
        <View key={comment.id} style={styles.commentRow}>
          <Text style={styles.commentAuthor}>
            {comment.author_label ?? comment.author} · spec {comment.version ?? 'general'}
          </Text>
          <Text style={styles.bodyCopy}>{comment.body}</Text>
        </View>
      ))}
      <Field
        label="Comment"
        value={commentBody}
        onChange={setCommentBody}
        multiline
        placeholder="Record a review note or question without changing the design."
      />
      <View style={styles.actionRow}>
        <Button
          title={commentsBusy ? 'Loading comments…' : 'Load comments'}
          kind="ghost"
          disabled={commentsBusy}
          onPress={() => void loadProjectComments()}
        />
        <Button
          title="Post comment"
          disabled={commentsBusy || !commentBody.trim()}
          onPress={() => void postProjectComment()}
        />
      </View>
    </Section>
  );

  const refinePanel = state.project && (
    <>
      {state.project.design_id === null && (
        <Section title="Choose a creative candidate">
          <Text style={styles.guidanceCopy}>
            Concepts are visual explorations, not factory records. Choose the direction you want to keep; exact facts stay optional until you need a trusted specification or factory handoff.
          </Text>
          <Notice
            kind="info"
            text="Every concept is already saved in your Studio library. You can return to it later; no production step is required."
          />
          <View style={styles.creativeGrid}>
            {state.project.revisions.map((revision) => (
              <View
                key={revision.asset.asset_id}
                style={[
                  styles.creativeCard,
                  (creativeCandidateId === revision.asset.asset_id
                    || (creativeCandidateId === null
                      && state.project!.active_asset_id === revision.asset.asset_id))
                    && styles.creativeCardSelected,
                ]}>
                {state.project!.revisions.length > 1 && revision.asset.image_url && (
                  <Image
                    source={{ uri: revision.asset.image_url }}
                    style={styles.creativeImage}
                    resizeMode="contain"
                  />
                )}
                <View style={styles.candidateRow}>
                  <View style={styles.revisionCopy}>
                    <Text style={styles.revisionTitle}>Direction {revision.revision}</Text>
                    <Text style={styles.meta}>Visual concept · editable after confirmation</Text>
                  </View>
                  {(creativeCandidateId === revision.asset.asset_id
                    || (creativeCandidateId === null
                      && state.project!.active_asset_id === revision.asset.asset_id)) && (
                    <Text style={styles.directionBadge}>CURRENT</Text>
                  )}
                </View>
                {creativeDraftCoverage === null && (
                  <Button
                    title={creativeDraftBusy
                      && creativeCandidateId === revision.asset.asset_id
                      ? 'Reading the design…'
                      : 'Use this direction'}
                    disabled={creativeDraftBusy || state.busy !== null}
                    onPress={() => void extractCreativeCandidateDraft(
                      revision.asset.asset_id,
                    )}
                  />
                )}
              </View>
            ))}
          </View>

          {creativeDraftCoverage === null && (
            <WorkspaceDisclosure
              title="Add exact details"
              subtitle="Optional stone, count, metal, size, or construction notes"
              open={showCandidateNotes}
              onPress={() => setShowCandidateNotes(!showCandidateNotes)}>
              <Field
                label="What must Facetta preserve?"
                value={creativeDraftNotes}
                onChange={setCreativeDraftNotes}
                multiline
                placeholder="Known stone species, exact count, metal, dimensions, ring size, or construction intent…"
              />
            </WorkspaceDisclosure>
          )}

          {creativeDraftCoverage !== null && (
            <View style={styles.nextStepCard}>
              <Text style={styles.nextStepEyebrow}>NEXT STEP</Text>
              <Text style={styles.nextStepTitle}>Facetta read this concept</Text>
              <Text style={styles.guidanceCopy}>
                {creativeDraftCoverage.blockers.length > 0
                  ? `${creativeDraftCoverage.blockers.length} details still need review. This legacy draft cannot create Design v1; the concept itself remains saved.`
                  : 'Review this legacy summary for reference. To create Design v1, continue in Studio Confirm. Corrections made here are not transferred silently.'}
              </Text>
              <Button
                title={showCandidateFacts ? 'Hide design details' : 'Review design details'}
                kind="ghost"
                onPress={() => setShowCandidateFacts(!showCandidateFacts)}
              />
            </View>
          )}

          {creativeDraftCoverage !== null && showCandidateFacts && (
            <View style={styles.candidateFacts}>
              {parseSpec(creativeDraftSpec) !== null && (
                <FactoryFactEditor
                  spec={parseSpec(creativeDraftSpec)!}
                  client={api}
                  onChange={(spec) => {
                    setCreativeDraftSpec(JSON.stringify(spec, null, 2));
                    setCreativeDraftSpecChangedAfterAudit(true);
                  }}
                />
              )}
              <WorkspaceDisclosure
                title="Evidence and factory readiness"
                subtitle="Technical mappings, estimates, audit details, and the draft sheet"
                open={showEvidenceDetails}
                onPress={() => setShowEvidenceDetails(!showEvidenceDetails)}>
                {parseSpec(creativeDraftSpec) !== null && (
                  <DraftFactorySheetPreview
                    spec={parseSpec(creativeDraftSpec)!}
                    client={api}
                  />
                )}
                <Field
                  label="Advanced candidate specification JSON"
                  value={creativeDraftSpec}
                  onChange={(value) => {
                    setCreativeDraftSpec(value);
                    setCreativeDraftSpecChangedAfterAudit(true);
                  }}
                  multiline
                />
                <SourceCoverageCorrectionPanel
                  coverage={creativeDraftCoverage}
                  drafts={creativeCoverageDrafts}
                  busy={creativeDraftBusy ? 'audit' : null}
                  specChangedAfterAudit={creativeDraftSpecChangedAfterAudit}
                  onDraftChange={(componentId, draft) => setCreativeCoverageDrafts(
                    (current) => ({ ...current, [componentId]: draft }),
                  )}
                  onApply={() => void resolveCreativeCandidateCoverage(false)}
                  onAudit={() => void resolveCreativeCandidateCoverage(true)}
                />
                {creativeDraftCoverage.blockers
                  .filter((blocker) => (
                    blocker.code === 'source_component_audit_inconclusive'
                  ))
                  .map((blocker) => {
                    const confirmation = creativeConfirmations[blocker.component_id]
                      ?? { basis: 'visible_source' as const, description: '' };
                    return (
                      <View
                        key={`confirm:${blocker.component_id}`}
                        style={styles.approvalItem}>
                        <Text style={styles.approvalLabel}>{blocker.component_id}</Text>
                        <Text style={styles.bodyCopy}>{blocker.message}</Text>
                        <ChipRow
                          label="Confirmation basis"
                          options={['visible_source', 'designer_defined_target'] as const}
                          value={confirmation.basis}
                          onSelect={(basis) => setCreativeConfirmations((current) => ({
                            ...current,
                            [blocker.component_id]: { ...confirmation, basis },
                          }))}
                          render={(basis) => basis === 'visible_source'
                            ? 'Visible in candidate'
                            : 'Designer-defined target'}
                        />
                        <Field
                          label="Exact designer confirmation"
                          value={confirmation.description}
                          onChange={(description) => setCreativeConfirmations((current) => ({
                            ...current,
                            [blocker.component_id]: { ...confirmation, description },
                          }))}
                          multiline
                          placeholder="State the exact visible count/fact, or clearly define the intended manufacturing target."
                        />
                      </View>
                    );
                  })}
                {creativeDraftCoverage.blockers.some((blocker) => (
                  blocker.code === 'source_component_audit_inconclusive'
                )) && (
                  <Button
                    title="Save designer confirmations"
                    kind="ghost"
                    disabled={creativeDraftBusy}
                    onPress={() => void confirmCreativeCandidateCoverage()}
                  />
                )}
              </WorkspaceDisclosure>
              <Button
                title="How to continue in Studio"
                disabled={state.busy !== null || creativeCandidateId === null}
                onPress={explainStudioConfirmMigration}
              />
            </View>
          )}
        </Section>
      )}
      {state.project.design_id !== null && (
        <Section title="Choose what happens next">
          <Text style={styles.bodyCopy}>
            This design is safely kept in your Studio library. Pick an optional outcome for this session; you can switch at any time without changing the design itself.
          </Text>
          <ChipRow
            label="This design is for"
            options={['library', 'client', 'marketing'] as const}
            value={activeDestination}
            onSelect={setActiveDestination}
            render={(destination) => ({
              library: 'My library',
              client: 'Client presentation',
              marketing: 'Marketing images',
            })[destination]}
          />
          {activeDestination === 'library' && (
            <View style={styles.destinationSummary}>
              <Text style={styles.destinationTitle}>Keep exploring on your terms</Text>
              <Text style={styles.meta}>
                Your active revision, notes, and history are saved. Make a change, create a variation, or simply come back later.
              </Text>
            </View>
          )}
          {activeDestination === 'client' && (
            <View style={styles.destinationSummary}>
              <Text style={styles.destinationTitle}>Prepare a polished presentation</Text>
              <Text style={styles.meta}>
                Create a beauty render or a single product image while the confirmed design facts stay frozen.
              </Text>
            </View>
          )}
          {activeDestination === 'marketing' && (
            <View style={styles.destinationSummary}>
              <Text style={styles.destinationTitle}>Build images for a collection or campaign</Text>
              <Text style={styles.meta}>
                Generate review-only ecommerce directions from this exact design, then save only the images you want to keep.
              </Text>
            </View>
          )}
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ disabled: !canSelectPhase(state, 'factory') }}
            disabled={!canSelectPhase(state, 'factory')}
            onPress={() => workflow.selectPhase('factory')}
            style={[
              styles.factoryDestination,
              !canSelectPhase(state, 'factory') && styles.factoryDestinationDisabled,
            ]}>
            <Text style={styles.factoryDestinationTitle}>Need to make this piece?</Text>
            <Text style={styles.factoryDestinationText}>
              {canSelectPhase(state, 'factory')
                ? 'Optional factory handoff →'
                : 'Factory handoff unlocks only after exact revision approval'}
            </Text>
          </Pressable>
        </Section>
      )}
      {isWide && activeDestination === 'client' && beautyRenderSource !== null
        && state.pending_markup === null && state.warning_candidate === null && (
        <Section title={beautyRenderSource.capability === 'COLORED_LINE_ART'
          ? 'Create a beauty render from confirmed colored line art'
          : 'Create a beauty render from this confirmed reference'}>
          <Text style={styles.bodyCopy}>
            {beautyRenderSource.capability === 'COLORED_LINE_ART'
              ? 'Use the exact confirmed drawing geometry and validated specification to create a polished jewelry image. Unconfirmed line art is never eligible.'
              : 'Turn the imported design into a polished jewelry image while preserving its confirmed stones, setting, proportions, metal, and specification.'}
          </Text>
          <Text style={styles.meta}>
            Exact render source: {beautyRenderSource.asset_id} · spec {beautyRenderSource.design_version}
          </Text>
          <Field
            label="Optional presentation direction"
            value={beautyRenderDirection}
            onChange={setBeautyRenderDirection}
            multiline
            placeholder="Neutral three-quarter studio view, soft shadow, clean background…"
          />
          <Button
            title={state.busy === 'beauty_render'
              ? 'Rendering and checking the confirmed design…'
              : 'Create QA-checked beauty render'}
            disabled={state.busy !== null}
            onPress={() => void workflow.createBeautyRender(beautyRenderDirection.trim())}
          />
        </Section>
      )}
      {isWide && (activeDestination === 'client' || activeDestination === 'marketing')
        && state.project.design_id !== null
        && state.pending_markup === null && state.warning_candidate === null && (
        <Section title="Create product photography">
          <Text style={styles.bodyCopy}>
            Restage the active ring for ecommerce while Facetta freezes its stones, setting, proportions, and specification.
          </Text>
          <ChipRow
            label="Photography preset"
            options={PRODUCT_PHOTO_PRESETS}
            value={productPhotoPreset}
            onSelect={setProductPhotoPreset}
            render={(preset) => ({
              catalog_white: 'Catalog white',
              luxury_studio: 'Luxury studio',
              dark_editorial: 'Dark editorial',
              macro_detail: 'Macro detail',
            })[preset]}
          />
          <ChipRow
            label="Framing"
            options={PRODUCT_PHOTO_FRAMINGS}
            value={productPhotoFraming}
            onSelect={setProductPhotoFraming}
            render={(framing) => framing === 'source'
              ? 'Keep source'
              : framing === 'square' ? 'Square' : '4:5 portrait'}
          />
          <Field
            label="Optional art direction"
            value={productPhotoDirection}
            onChange={setProductPhotoDirection}
            multiline
            placeholder="Softer shadow, more breathing room, slightly warmer background…"
          />
          <Button
            title={state.busy === 'product_photo'
              ? 'Checking product photograph…'
              : 'Create QA-checked product photo'}
            disabled={state.busy !== null}
            onPress={() => void workflow.createProductPhoto({
              preset: productPhotoPreset,
              framing: productPhotoFraming,
              custom_instruction: productPhotoDirection.trim(),
            })}
          />
        </Section>
      )}
      {isWide && activeDestination === 'marketing' && state.project.design_id !== null
        && state.project.active_asset_id !== null
        && state.project.active_design_version !== null
        && state.pending_markup === null && state.warning_candidate === null && (
        <Section title="Create an ecommerce image set">
          <Text style={styles.bodyCopy}>
            Generate several presentation directions from the same exact design. Each selected scene can use up to three provider attempts, so more scenes cost more. Every result remains review-only until you save it.
          </Text>
          <View style={styles.presetGrid}>
            {PRODUCT_PHOTO_PRESETS.map((preset) => {
              const selected = marketingPresets.includes(preset);
              const label = ({
                catalog_white: 'Catalog white',
                luxury_studio: 'Luxury studio',
                dark_editorial: 'Dark editorial',
                macro_detail: 'Macro detail',
              })[preset];
              return (
                <Pressable
                  key={preset}
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: selected }}
                  onPress={() => toggleMarketingPreset(preset)}
                  style={[styles.presetChoice, selected && styles.presetChoiceSelected]}>
                  <Text style={selected ? styles.presetChoiceTextSelected : styles.meta}>
                    {selected ? '✓ ' : ''}{label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
          <Text style={styles.meta}>
            Maximum attempts for this request: {marketingPresets.length * 3}
          </Text>
          <Button
            title={marketingBusy ? 'Creating and checking image set…' : 'Generate review candidates'}
            disabled={marketingBusy || marketingPresets.length === 0}
            onPress={() => void createMarketingPack()}
          />
          {marketingPack?.failures.map((failure) => (
            <Notice
              key={`${failure.preset}:${failure.code}`}
              kind="error"
              text={`${failure.preset.replace(/_/g, ' ')} failed: ${failure.detail}`}
            />
          ))}
          {marketingPack?.candidates.map((candidate) => (
            <View key={candidate.candidate_id} style={styles.creativeCard}>
              <Image
                source={{ uri: candidate.preview_url }}
                style={styles.creativeImage}
                resizeMode="contain"
              />
              <Text style={styles.revisionTitle}>
                {candidate.preset.replace(/_/g, ' ')} · {candidate.framing}
              </Text>
              <Text style={styles.meta}>
                QA {candidate.qa.verdict.toUpperCase()} · designer review required
              </Text>
              <Button
                title="Save as marketing asset"
                kind="ghost"
                disabled={marketingBusy}
                onPress={() => void acceptMarketingCandidate(candidate)}
              />
            </View>
          ))}
        </Section>
      )}
      {isWide && state.project.design_id !== null
        && state.pending_markup === null && state.warning_candidate === null && (
        <Section title="Mark one change">
          {activeImageUrl === null ? (
            <Notice kind="error" text="This project has no active image to annotate." />
          ) : (
            <AnnotationCanvas
              key={state.project.active_asset_id ?? activeImageUrl}
              sourceUri={activeImageUrl}
              onChange={setMarkupSnapshot}
              drawingEnabled={state.busy === null}
              imageAspectRatio={1}
            />
          )}
          <Button
            title={state.busy === 'read_markup' ? 'Reading marks…' : 'Read without changing the project'}
            disabled={markupSnapshot === null || markupSnapshot.annotations.length === 0
              || state.busy !== null}
            onPress={() => {
              if (markupSnapshot !== null) void workflow.readMarkup(markupSnapshot);
            }}
          />
        </Section>
      )}
      {state.project.spec !== null && state.project.spec !== undefined
        && state.pending_markup === null && state.warning_candidate === null && (
        <Section title="Change a known component">
          <ComponentCatalogPanel
            client={api}
            project={state.project}
            spec={state.project.spec}
            createdBy={designer}
            mobileReviewOnly={!isWide}
            onApplied={(result) => {
              if (result.status === 'accepted') void workflow.refreshProject();
            }}
            onProjectChanged={() => { void workflow.refreshProject(); }}
            onVariationCreated={(variation) => { void workflow.openProject(variation.id); }}
          />
        </Section>
      )}
      {isWide && state.project.design_id !== null
        && state.pending_markup === null && state.warning_candidate === null && (
        <Section title="Line art → confirmed geometry → color">
          <Text style={styles.bodyCopy}>
            Generate geometry-only line art from the active revision. It stays temporary until you confirm it; color then comes only from the validated specification.
          </Text>
          <ChipRow
            label="Line-art view"
            options={LINE_ART_VIEWS}
            value={lineArtView}
            onSelect={setLineArtView}
            render={(view) => view === 'three_quarter'
              ? 'Three-quarter'
              : view === 'front' ? 'Front' : 'Side'}
          />
          <Button
            title={state.busy === 'line_art'
              ? 'Checking drawing geometry…'
              : 'Generate line art for confirmation'}
            disabled={state.busy !== null}
            onPress={() => void workflow.createLineArt(lineArtView)}
          />
          {confirmedLineArt && (
            <View style={styles.drawingStage}>
              <Text style={styles.approved}>Geometry confirmed</Text>
              {confirmedLineArt.image_url && (
                <Image
                  source={{ uri: confirmedLineArt.image_url }}
                  style={styles.warningPreview}
                  resizeMode="contain"
                />
              )}
              <Button
                title="Color from confirmed specification"
                disabled={state.busy !== null}
                onPress={() => void workflow.colorizeLineArt(confirmedLineArt.asset_id)}
              />
            </View>
          )}
          {coloredLineArt && (
            <Text style={styles.meta}>
              Spec-colored drawing saved as a derived project artifact; the active design revision and spec did not change.
            </Text>
          )}
        </Section>
      )}
      {interpretationPanel}
      {warningPanel}
      <WorkspaceDisclosure
        title="History"
        subtitle={`${state.project.revisions.length} saved revision${state.project.revisions.length === 1 ? '' : 's'} · nothing is overwritten`}
        open={showRevisionHistory}
        onPress={() => setShowRevisionHistory(!showRevisionHistory)}>
        <StudioHistoryPanel
          client={api}
          project={state.project}
          createdBy={designer}
          onOpenProject={(projectId) => { void workflow.openProject(projectId); }}
          onProjectChanged={(project) => { void workflow.openProject(project.id); }}
        />
        {state.last_revision && state.last_revision.spec_change.map((change) => (
          <Text key={change.path} style={styles.diffText}>
            {change.label ?? change.path}: {valueLabel(change.before)} → {valueLabel(change.after)}
          </Text>
        ))}
        <View style={styles.actionRow}>
          <Button title="Refresh record" kind="ghost" onPress={() => void workflow.refreshProject()} />
          {state.project.design_id && state.project.active_design_version
            && onOpenAdvancedSpecifications && (
            <Button
              title="Advanced specifications"
              kind="ghost"
              onPress={() => onOpenAdvancedSpecifications(
                state.project!.design_id!,
                state.project!.active_design_version!,
              )}
            />
          )}
        </View>
      </WorkspaceDisclosure>
      {commentsPanel}
    </>
  );

  const approvalPanel = state.project && (
    <>
    <Section title="Approve this exact revision">
      {approval === null ? (
        <>
          <Text style={styles.bodyCopy}>
            Generate fact checks from the specification linked to the active image.
          </Text>
          <Button
            title="Start approval checklist"
            disabled={state.busy !== null}
            onPress={() => void workflow.startApproval()}
          />
        </>
      ) : (
        <>
          <Text style={styles.bodyCopy}>
            {approval.approved_count}/{approval.total} facts approved · design spec {approval.design_version ?? 'legacy'}
          </Text>
          {approval.items.map((item) => {
            const answer = approval.answers[item.key];
            const note = approvalNotes[item.key] ?? '';
            return (
              <View key={item.key} style={styles.approvalItem}>
                <Text style={styles.approvalLabel}>{item.label}</Text>
                <Text style={styles.approvalFact}>{item.fact}</Text>
                {answer && (
                  <Text style={answer.approved ? styles.approved : styles.declined}>
                    {answer.approved ? 'Approved' : `Revision requested: ${answer.note ?? ''}`}
                  </Text>
                )}
                <Field
                  label="Change note (required for No)"
                  value={note}
                  onChange={(next) => setApprovalNotes((current) => ({
                    ...current,
                    [item.key]: next,
                  }))}
                  placeholder="What should change?"
                />
                <View style={styles.actionRow}>
                  <Button
                    title="Yes"
                    disabled={state.busy !== null}
                    onPress={() => void workflow.respondToApproval({
                      item_key: item.key,
                      approved: true,
                    })}
                  />
                  <Button
                    title="No — request revision"
                    kind="ghost"
                    disabled={!note.trim() || state.busy !== null}
                    onPress={() => void workflow.respondToApproval({
                      item_key: item.key,
                      approved: false,
                      note,
                      interpret: true,
                    })}
                  />
                </View>
              </View>
            );
          })}
          {approval.all_approved && (
            <Notice
              kind="ok"
              text={approval.pinned
                ? 'All facts approved and this exact revision is pinned.'
                : 'All facts approved. Waiting for the exact revision to be pinned.'}
            />
          )}
        </>
      )}
    </Section>
    {commentsPanel}
    </>
  );

  const factoryPanel = state.project && (
    <Section title="Pinned factory truth">
      {!state.project.factory_ready ? (
        <>
          <Notice
            kind="info"
            text={state.project.factory_blockers.length > 0
              ? 'The exact revision can be visually approved, but these source or form definitions still block manufacturing release.'
              : 'The factory bundle unlocks only after every checklist fact is approved and the exact image/spec pair is pinned.'}
          />
          {state.project.factory_blockers.map((blocker) => (
            <View key={`${blocker.code}:${blocker.subject_id}`} style={styles.artifactRow}>
              <Text style={styles.artifactName}>{blocker.label}</Text>
              <Text style={styles.bodyCopy}>{blocker.detail}</Text>
              <Text style={styles.meta}>Required: {blocker.required_resolution}</Text>
            </View>
          ))}
        </>
      ) : (
        <>
          <Button
            title={state.busy === 'factory_pack' ? 'Verifying pack…' : 'Load verified factory pack'}
            disabled={state.busy !== null}
            onPress={() => void workflow.loadFactoryPack()}
          />
          {state.factory_pack && (
            <>
              <Text style={styles.bodyCopy}>
                Design {state.factory_pack.design_id} · spec {state.factory_pack.design_version}
              </Text>
              {state.factory_pack.dimensions.has_estimates && (
                <Notice
                  kind="info"
                  text={state.factory_pack.dimensions.disclaimer
                    || 'ESTIMATED dimensions are reference values, not measurements. Verify or adjust them before production.'}
                />
              )}
              {state.factory_pack.dimensions.estimated_fields.map((field) => (
                <Text key={field.field_path} style={styles.meta}>
                  ESTIMATE · {field.field_path} · {String(field.value)} {field.unit}
                </Text>
              ))}
              {state.factory_pack.artifacts.map((artifact) => (
                <View key={artifact.name} style={styles.artifactRow}>
                  <Text style={styles.artifactName}>{artifact.name}</Text>
                  <Text style={styles.meta}>
                    {artifact.authoritative ? 'Authoritative' : 'Discussion reference'} · {artifact.sha256.slice(0, 12)}
                  </Text>
                </View>
              ))}
              <Button
                title="Open factory pack"
                onPress={() => void Linking.openURL(
                  state.factory_pack!.bundle_url
                    || api.factoryPackZipUrl(state.project!.id),
                )}
              />
            </>
          )}
        </>
      )}
    </Section>
  );

  const currentPanel = state.phase === 'create'
    ? createPanel
    : state.phase === 'refine'
      ? refinePanel
      : state.phase === 'approve'
        ? approvalPanel
        : factoryPanel;

  const canvas = state.project && (
    <View style={styles.canvasColumn}>
      <Section title={state.project.design_id === null ? 'Selected direction' : state.project.title}>
        <View style={styles.canvas}>
          {activeImageUrl ? (
            <Image source={{ uri: activeImageUrl }} style={styles.heroImage} resizeMode="contain" />
          ) : (
            <Text style={styles.emptyCanvas}>The active image is unavailable.</Text>
          )}
        </View>
        <View style={styles.projectMetaRow}>
          <Text style={styles.projectState}>
            {state.project.design_id === null ? 'Concept exploration' : 'Editable design'}
          </Text>
          <Text style={styles.meta}>
            Revision {active?.revision ?? state.project.primary_revision_count}
          </Text>
        </View>
      </Section>
    </View>
  );

  return (
    <ScrollView contentContainerStyle={styles.content}>
      {workflowHeader}
      {state.error && (
        <Pressable onPress={workflow.clearError}>
          <Notice kind="error" text={state.error.message} />
        </Pressable>
      )}
      {(localNotice || localInfo || (
        state.notice && !state.notice.includes('source-evidence blocker')
      )) && (
        <Notice
          kind={localNotice ? 'error' : 'ok'}
          text={localNotice ?? localInfo ?? state.notice ?? ''}
        />
      )}
      {state.busy !== null && (
        <View style={styles.busyRow}>
          <ActivityIndicator color={theme.accent} />
          <Text style={styles.meta}>
            {state.busy === 'beauty_render'
              ? 'Building and checking a polished render from the confirmed design…'
              : 'Working on the trusted record…'}
          </Text>
        </View>
      )}
      {isWide && state.project !== null ? (
        <View style={styles.wideLayout}>
          {canvas}
          <View style={styles.inspector}>{currentPanel}</View>
        </View>
      ) : (
        <>
          {canvas}
          {currentPanel}
        </>
      )}
      {state.project === null && warningPanel}
      {state.project && (
        <Button title="Close project" kind="ghost" onPress={workflow.clearWorkspace} />
      )}
      <View style={styles.bottomSpace} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  disabledWrap: { padding: 12 },
  content: { padding: 12, maxWidth: 1440, width: '100%', alignSelf: 'center' },
  workflowHeader: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: 18,
    backgroundColor: theme.card,
    padding: 16,
    marginBottom: 12,
  },
  workspaceEyebrow: {
    color: theme.accent,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1.5,
    marginBottom: 6,
  },
  workspaceTitle: { color: theme.ink, fontFamily: theme.serif, fontSize: 23 },
  workspaceBody: { color: theme.faint, fontSize: 13, lineHeight: 19, marginTop: 5 },
  phaseNav: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 14,
  },
  phaseButton: {
    paddingHorizontal: 11,
    paddingVertical: 7,
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: 999,
    backgroundColor: theme.paper,
  },
  phaseButtonActive: { borderColor: theme.ink, backgroundColor: theme.ink },
  phaseButtonDisabled: { opacity: 0.3 },
  phaseText: { color: theme.faint, fontSize: 12 },
  phaseTextActive: { color: theme.paper, fontWeight: '700' },
  factoryDestination: {
    marginTop: 14,
    borderWidth: 1,
    borderColor: theme.gold,
    borderRadius: 10,
    padding: 12,
    backgroundColor: theme.goldSoft,
  },
  factoryDestinationDisabled: { opacity: 0.55 },
  factoryDestinationTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  factoryDestinationText: { color: theme.accent, fontSize: 12, marginTop: 3 },
  destinationSummary: {
    borderLeftWidth: 2,
    borderLeftColor: theme.accent,
    paddingLeft: 10,
    marginTop: 3,
  },
  destinationTitle: { color: theme.ink, fontSize: 13, fontWeight: '700', marginBottom: 3 },
  wideLayout: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
  canvasColumn: { flex: 1.45, minWidth: 0 },
  inspector: { flex: 0.9, minWidth: 340, maxWidth: 500 },
  canvas: {
    minHeight: 340,
    backgroundColor: theme.paper,
    borderColor: theme.line,
    borderWidth: 1,
    borderRadius: 12,
    overflow: 'hidden',
    alignItems: 'center',
    justifyContent: 'center',
  },
  heroImage: { width: '100%', height: 410 },
  emptyCanvas: { color: theme.faint, fontStyle: 'italic' },
  warningPreview: { height: 220, width: '100%', backgroundColor: theme.paper },
  guidanceCopy: { color: theme.ink, fontSize: 14, lineHeight: 21, marginBottom: 12 },
  creativeGrid: { gap: 10, marginVertical: 8 },
  creativeCard: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: 14,
    padding: 10,
    gap: 8,
    backgroundColor: theme.paper,
  },
  creativeCardSelected: { borderColor: theme.accent, borderWidth: 2 },
  creativeImage: { width: '100%', height: 170, backgroundColor: theme.paper },
  candidateRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  directionBadge: { color: theme.ok, fontSize: 9, letterSpacing: 1.1, fontWeight: '700' },
  nextStepCard: {
    borderWidth: 1,
    borderColor: theme.gold,
    borderRadius: 15,
    backgroundColor: theme.goldSoft,
    padding: 14,
    marginTop: 12,
  },
  nextStepEyebrow: {
    color: theme.accent,
    fontSize: 9,
    fontWeight: '700',
    letterSpacing: 1.3,
    marginBottom: 5,
  },
  nextStepTitle: { color: theme.ink, fontFamily: theme.serif, fontSize: 18, marginBottom: 6 },
  candidateFacts: { marginTop: 12 },
  disclosureCard: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: 14,
    backgroundColor: theme.card,
    marginTop: 10,
    marginBottom: 10,
    overflow: 'hidden',
  },
  disclosureHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 13,
  },
  disclosureCopy: { flex: 1, paddingRight: 12 },
  disclosureTitle: { color: theme.ink, fontSize: 14, fontWeight: '600' },
  disclosureSubtitle: { color: theme.faint, fontSize: 11, lineHeight: 16, marginTop: 2 },
  disclosureIcon: { color: theme.accent, fontSize: 22, lineHeight: 24 },
  disclosureBody: { borderTopWidth: 1, borderTopColor: theme.line, padding: 12 },
  presetGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 7, marginBottom: 8 },
  presetChoice: {
    borderWidth: 1,
    borderColor: theme.line,
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  presetChoiceSelected: { borderColor: theme.accent, backgroundColor: theme.goldSoft },
  presetChoiceTextSelected: { color: theme.accent, fontSize: 12 },
  projectMetaRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 8,
    gap: 8,
  },
  projectState: {
    color: theme.ink,
    fontSize: 12,
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  provenance: { color: theme.faint, fontSize: 11, marginTop: 4 },
  busyRow: { flexDirection: 'row', gap: 8, alignItems: 'center', marginBottom: 8 },
  actionRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center' },
  meta: { color: theme.faint, fontSize: 12 },
  bodyCopy: { color: theme.ink, fontSize: 13, marginBottom: 10, lineHeight: 19 },
  warningText: { color: theme.danger, fontSize: 12, marginBottom: 4 },
  revisionRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 9,
    borderBottomWidth: 1,
    borderBottomColor: theme.line,
  },
  revisionCopy: { flex: 1 },
  revisionTitle: { color: theme.ink, fontFamily: theme.serif, fontSize: 14 },
  qaBadge: { fontSize: 10, letterSpacing: 1, paddingHorizontal: 7, paddingVertical: 3 },
  qaPass: { color: theme.ok },
  qaWarn: { color: theme.danger },
  diffText: { color: theme.ink, fontSize: 12, marginTop: 7 },
  approvalItem: {
    borderTopWidth: 1,
    borderTopColor: theme.line,
    paddingTop: 10,
    marginTop: 8,
  },
  approvalLabel: { color: theme.ink, fontFamily: theme.serif, fontSize: 14 },
  approvalFact: { color: theme.ink, fontSize: 12, marginVertical: 4 },
  approved: { color: theme.ok, fontSize: 12, marginBottom: 6 },
  declined: { color: theme.danger, fontSize: 12, marginBottom: 6 },
  drawingStage: { marginTop: 10, gap: 8 },
  artifactRow: {
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: theme.line,
  },
  artifactName: { color: theme.ink, fontSize: 13 },
  commentRow: {
    borderTopWidth: 1,
    borderTopColor: theme.line,
    paddingTop: 8,
    marginTop: 8,
  },
  commentAuthor: { color: theme.faint, fontSize: 11, marginBottom: 3 },
  bottomSpace: { height: 48 },
});
