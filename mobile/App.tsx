import { StatusBar } from 'expo-status-bar';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator, Pressable, SafeAreaView, ScrollView, StyleSheet, Text,
  useWindowDimensions, View,
} from 'react-native';
import { DEFAULT_API_URL } from './src/config';
import { AuthenticatedImage as Image, AuthenticatedImageProvider } from './src/AuthenticatedImage';
import {
  clearSession, hasOnboarded, loadAuthenticatedSession, markOnboarded,
  restoreAuthenticatedSession, saveSession, sessionAccessToken, Session,
  signOutAuthenticatedSession, subscribeToAuthStateChange,
} from './src/auth';
import { LoginScreen, PasswordRecoveryScreen } from './src/LoginScreen';
import { OnboardingScreen } from './src/OnboardingScreen';
import { getStudioAction, getStudioRailActions, getVisibleStudioActions } from './src/studio/actions';
import {
  StudioActionContext, StudioActionId, StudioWorkspaceActionId,
} from './src/studio/contracts';
import { StudioCollectionsWorkspace } from './src/studio/StudioCollectionsWorkspace';
import { StudioCreateWorkspace } from './src/studio/StudioCreateWorkspace';
import { StudioConfirmWorkspace } from './src/studio/StudioConfirmWorkspace';
import { pickExpoStudioCreateReference } from './src/studio/expoReferencePicker';
import { StudioRefineWorkspace } from './src/studio/StudioRefineWorkspace';
import { StudioViewsWorkspace } from './src/studio/StudioViewsWorkspace';
import { StudioPresentWorkspace } from './src/studio/StudioPresentWorkspace';
import { StudioVaryWorkspace } from './src/studio/StudioVaryWorkspace';
import {
  deliverAuthenticatedProtectedFile, StudioFactoryWorkspace,
  StudioProtectedFileRequest,
} from './src/studio/StudioFactoryWorkspace';
import { StudioActivityWorkspace } from './src/studio/StudioActivityWorkspace';
import {
  createStudioGatewayFromOptions, ExactStudioLineage, StudioReviewJobEnvelope,
  StudioVisualLineage,
} from './src/studio/gateway';
import { radius, shadows, theme } from './src/theme';
import type { ProjectDetail } from './src/trusted/types';
import { WorkflowShowcase } from './src/WorkflowShowcase';
import { designerErrorMessage } from './src/studio/designerErrorMessage';

type Tab = 'studio' | 'collections' | 'activity' | 'learn';
type StudioView = 'home' | 'action';
type Stage = 'onboarding' | 'tour' | 'booting' | 'login' | 'recovery' | 'app';
type SavedFamiliesState = 'unknown' | 'available' | 'empty' | 'unavailable';
type ProjectHydrationDestination = 'collections' | 'create' | 'refine' | 'views' | 'present'
  | 'specifications';

function assertNeverStudioAction(actionId: never): never {
  throw new Error(`Unhandled Studio action workspace: ${String(actionId)}`);
}

interface ProjectHydrationRequest {
  projectId: string;
  destination: ProjectHydrationDestination;
  expectedAssetId?: string;
  studioJobId?: string;
  reviewJobId?: string;
}

interface CreateReviewState {
  project: ProjectDetail;
  studioJobId: string;
}

const designImage = require('./assets/studio-asymmetric-paraiba-ring-v1.png');

function StudioCard({
  image, imageLabel, eyebrow, title, body, accent, wide, onPress,
}: {
  image: any;
  imageLabel: string;
  eyebrow: string;
  title: string;
  body: string;
  accent: string;
  wide?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable style={[styles.studioCard, wide && styles.studioCardWide]} onPress={onPress}>
      <View style={styles.studioImage}>
        <Image accessibilityLabel={imageLabel} source={image} style={styles.studioArtwork} resizeMode="cover" />
        <View style={styles.studioShade} />
        <View style={styles.studioCardCopy}>
          <View style={[styles.studioEyebrow, { backgroundColor: accent }]}>
            <Text style={styles.studioEyebrowText}>{eyebrow}</Text>
          </View>
          <Text style={styles.studioTitle}>{title}</Text>
          <Text style={styles.studioBody}>{body}</Text>
        </View>
        <View style={[styles.studioLaunch, { borderColor: accent }]}>
          <Text style={[styles.studioLaunchText, { color: accent }]}>↗</Text>
        </View>
      </View>
    </Pressable>
  );
}

export default function App() {
  const [authLifecycleEnabled, setAuthLifecycleEnabled] = useState(() => hasOnboarded());
  const [session, setSession] = useState<Session | null>(() => loadAuthenticatedSession());
  const [stage, setStage] = useState<Stage>(() => authLifecycleEnabled ? 'booting' : 'onboarding');
  const [tab, setTab] = useState<Tab>('studio');
  const [studioView, setStudioView] = useState<StudioView>('home');
  const [selectedActionId, setSelectedActionId] = useState<StudioWorkspaceActionId>('create');
  const [showMoreActions, setShowMoreActions] = useState(false);
  const apiUrl = DEFAULT_API_URL;
  const [designer, setDesigner] = useState(session?.designerId ?? '');
  const [showUtilityMenu, setShowUtilityMenu] = useState(false);
  const [factoryEntitled, setFactoryEntitled] = useState(false);
  const [savedFamiliesState, setSavedFamiliesState] = useState<SavedFamiliesState>('unknown');
  const [studioProject, setStudioProject] = useState<ProjectDetail | null>(null);
  const [selectedCreativeAssetId, setSelectedCreativeAssetId] = useState<string | null>(null);
  const [createReview, setCreateReview] = useState<CreateReviewState | null>(null);
  const [activityReview, setActivityReview] = useState<StudioReviewJobEnvelope | null>(null);
  const [projectHydration, setProjectHydration] = useState<{
    request: ProjectHydrationRequest;
    loading: boolean;
    error: string | null;
  } | null>(null);
  // Opening a family variation or Activity item is a designer selection. If a
  // slower, earlier request finishes after a newer selection, it must not
  // replace the latest project or surface an error for work the designer no
  // longer intends to open.
  const projectHydrationRequestId = useRef(0);
  const clearAuthenticatedUi = useCallback(() => {
    projectHydrationRequestId.current += 1;
    setProjectHydration(null);
    clearSession();
    setSession(null);
    setDesigner('');
    setStudioProject(null);
    setSelectedCreativeAssetId(null);
    setCreateReview(null);
    setActivityReview(null);
    setFactoryEntitled(false);
    setSavedFamiliesState('unknown');
    setStage('login');
  }, []);
  const expireAuthenticatedSession = useCallback(() => {
    clearAuthenticatedUi();
    void signOutAuthenticatedSession();
  }, [clearAuthenticatedUi]);
  const adoptAuthenticatedSession = useCallback((next: Session) => {
    saveSession(next);
    setSession(next);
    setDesigner(next.designerId);
    setStage('app');
  }, []);

  useEffect(() => {
    if (!authLifecycleEnabled) return () => {};
    let mounted = true;
    const unsubscribe = subscribeToAuthStateChange((event, next) => {
      if (!mounted || event === 'INITIAL_SESSION') return;
      if (next === null) {
        clearAuthenticatedUi();
      } else if (event === 'PASSWORD_RECOVERY') {
        saveSession(next);
        setSession(next);
        setDesigner(next.designerId);
        setStage('recovery');
      } else {
        adoptAuthenticatedSession(next);
      }
    });
    void restoreAuthenticatedSession().then((next) => {
      if (!mounted) return;
      if (next === null) clearAuthenticatedUi();
      else adoptAuthenticatedSession(next);
    });
    return () => {
      mounted = false;
      unsubscribe();
    };
  }, [adoptAuthenticatedSession, authLifecycleEnabled, clearAuthenticatedUi]);

  const studioGateway = useMemo(
    () => createStudioGatewayFromOptions(
      {
        baseUrl: apiUrl.replace(/\/$/, ''),
        getAccessToken: () => sessionAccessToken(session),
        requireAccessToken: true,
        onAuthenticationFailure: expireAuthenticatedSession,
      },
      { trackJobs: true },
    ),
    [apiUrl, expireAuthenticatedSession, session],
  );
  useEffect(() => {
    let active = true;
    setFactoryEntitled(false);
    if (sessionAccessToken(session) === null) return () => { active = false; };
    void studioGateway.getFactoryEntitlement().then((result) => {
      if (active) setFactoryEntitled(result.error === null && result.data === true);
    });
    return () => { active = false; };
  }, [session, studioGateway]);
  useEffect(() => {
    let active = true;
    setSavedFamiliesState('unknown');
    if (sessionAccessToken(session) === null || designer.trim() === '') {
      return () => { active = false; };
    }
    if (studioProject !== null) {
      setSavedFamiliesState('available');
      return () => { active = false; };
    }
    void studioGateway.listDesignFamilies(designer).then((result) => {
      if (!active) return;
      setSavedFamiliesState(result.error === null
        ? result.data.families.length > 0 ? 'available' : 'empty'
        : 'unavailable');
    }).catch(() => {
      if (active) setSavedFamiliesState('unavailable');
    });
    return () => { active = false; };
  }, [designer, session, studioGateway, studioProject]);
  const { width } = useWindowDimensions();
  const authenticatedImageHeaders = useMemo(() => {
    const token = sessionAccessToken(session);
    return token === null ? undefined : { Authorization: `Bearer ${token}` };
  }, [session]);
  const isWide = width >= 900; // tablet / desktop: two-pane layouts
  const activeDesignId = studioProject?.root_id ?? null;
  const exactStudioLineage = useMemo<ExactStudioLineage | null>(() => {
    if (studioProject?.active_asset_id === null || studioProject?.active_asset_id === undefined
      || studioProject.active_design_version === null) return null;
    return {
      projectId: studioProject.root_id,
      sourceAssetId: studioProject.active_asset_id,
      sourceDesignVersion: studioProject.active_design_version,
    };
  }, [studioProject]);
  const visualStudioLineage = useMemo<StudioVisualLineage | null>(() => {
    if (studioProject?.active_asset_id === null || studioProject?.active_asset_id === undefined) {
      return null;
    }
    return {
      projectId: studioProject.root_id,
      sourceAssetId: studioProject.active_asset_id,
    };
  }, [studioProject]);
  const confirmStudioLineage = useMemo<StudioVisualLineage | null>(() => {
    if (studioProject === null || studioProject.design_id !== null) return null;
    if (studioProject.confirmable_pre_spec !== true) return null;
    // Confirmation must follow the current canonical pre-spec visual. A
    // refined child replaces the originally selected creative direction as the
    // active revision, so falling back to selected_candidate_asset_id here
    // would either hide the action or review stale pixels.
    const activeAssetId = studioProject.active_asset_id;
    if (activeAssetId === null) return null;
    const activeAsset = studioProject.assets.find((asset) => asset.asset_id === activeAssetId)
      ?? studioProject.active_revision;
    if (activeAsset === null || activeAsset.asset_id !== activeAssetId) return null;
    if (!(['CREATIVE_RENDER', 'GLOBAL_RESTYLE', 'LOCALIZED_EDIT'] as const).includes(
      activeAsset.capability as 'CREATIVE_RENDER' | 'GLOBAL_RESTYLE' | 'LOCALIZED_EDIT',
    )) return null;
    if (activeAsset.design_version !== null) return null;
    return { projectId: studioProject.root_id, sourceAssetId: activeAssetId };
  }, [studioProject]);
  const isCreatingNewDesign = tab === 'studio'
    && studioView === 'action'
    && selectedActionId === 'create';
  const factoryReadinessAvailable = exactStudioLineage !== null
    && factoryEntitled
    && studioProject?.spec?.jewelry_type === 'ring';
  const actionContext = useMemo<StudioActionContext>(() => ({
    activeDesignId,
    activeRevisionId: studioProject?.active_asset_id ?? selectedCreativeAssetId,
    hasExactSpecification: exactStudioLineage !== null,
    hasSelectedPreSpecVisual: confirmStudioLineage !== null && exactStudioLineage === null,
    // Opening readiness is separate from pack authority. The optional
    // workspace appears only for an entitled exact ring revision; its pack
    // action and the backend still require this revision to be factory_ready.
    factoryReadinessAvailable,
  }), [activeDesignId, confirmStudioLineage, exactStudioLineage,
    factoryReadinessAvailable, selectedCreativeAssetId, studioProject]);
  const hasActiveRevision = Boolean(actionContext.activeDesignId && actionContext.activeRevisionId);
  const actionSourceRevision = useMemo(() => {
    if (studioProject === null || isCreatingNewDesign) return null;
    const reviewSourceAssetId = activityReview !== null
      && activityReview.job.action_id === selectedActionId
      ? activityReview.lineage.sourceAssetId
      : null;
    const sourceAssetId = reviewSourceAssetId ?? studioProject.active_asset_id;
    if (sourceAssetId === null) return null;
    return [
      studioProject.active_revision,
      ...studioProject.revisions.map((revision) => revision.asset),
      ...studioProject.assets,
      ...(studioProject.creative_candidates ?? []),
    ].find((asset) => asset?.asset_id === sourceAssetId) ?? null;
  }, [activityReview, isCreatingNewDesign, selectedActionId, studioProject]);
  const actionSourceImageUrl = activityReview !== null
    && activityReview.job.action_id === selectedActionId
    ? activityReview.sourceImageUrl ?? actionSourceRevision?.image_url ?? null
    : actionSourceRevision?.image_url ?? null;
  const actionSourceIsCurrent = actionSourceRevision !== null
    && actionSourceRevision.asset_id === studioProject?.active_asset_id;
  const studioActions = getStudioRailActions(actionContext);
  const moreActions = getVisibleStudioActions(actionContext, 'more');
  const isStudioHome = tab === 'studio' && studioView === 'home';

  const hydrateProject = useCallback(async (request: ProjectHydrationRequest) => {
    const requestId = projectHydrationRequestId.current + 1;
    projectHydrationRequestId.current = requestId;
    const isCurrentRequest = (): boolean => projectHydrationRequestId.current === requestId;
    setProjectHydration({ request, loading: true, error: null });
    if (request.reviewJobId !== undefined
      && ['refine', 'views', 'present'].includes(request.destination)) {
      const review = await studioGateway.resumeReviewJob(request.reviewJobId, designer);
      if (!isCurrentRequest()) return;
      if (review.error !== null) {
        setProjectHydration({
          request,
          loading: false,
          error: designerErrorMessage(review.error, 'collections'),
        });
        return;
      }
      setStudioProject(review.data.project);
      setSelectedCreativeAssetId(review.data.project.active_asset_id);
      setActivityReview(review.data);
      setProjectHydration(null);
      openStudioAction(request.destination as 'refine' | 'views' | 'present', false, true);
      return;
    }
    const result = await studioGateway.getProject(request.projectId);
    if (!isCurrentRequest()) return;
    if (result.error !== null) {
      setProjectHydration({
        request,
        loading: false,
        error: designerErrorMessage(result.error, 'collections'),
      });
      return;
    }
    if (result.data.root_id !== request.projectId
      || (request.expectedAssetId !== undefined
        && result.data.active_asset_id !== request.expectedAssetId)) {
      setProjectHydration({
        request,
        loading: false,
        error: 'Facetta could not verify the opened design. Your current selection is unchanged.',
      });
      return;
    }
    if (request.destination === 'create') {
      if (request.studioJobId === undefined) {
        setProjectHydration({
          request,
          loading: false,
          error: 'Facetta could not verify the Create review in Activity. Your saved directions are unchanged.',
        });
        return;
      }
      setCreateReview({ project: result.data, studioJobId: request.studioJobId });
      setProjectHydration(null);
      openStudioAction('create', true);
      return;
    }
    setStudioProject(result.data);
    setSelectedCreativeAssetId(result.data.active_asset_id);
    setProjectHydration(null);
    if (request.destination === 'collections') {
      setTab('collections');
      return;
    }
    openStudioAction(request.destination);
  }, [designer, studioGateway]);

  const deliverProtectedFile = useCallback(async (
    request: StudioProtectedFileRequest,
  ): Promise<void> => deliverAuthenticatedProtectedFile(request, {
    apiUrl,
    accessToken: sessionAccessToken(session),
  }), [apiUrl, session]);

  const openStudioAction = (
    actionId: StudioActionId,
    preserveCreateReview = false,
    preserveActivityReview = false,
  ) => {
    if (actionId === 'more') {
      setShowMoreActions((visible) => !visible);
      return;
    }
    if (!preserveCreateReview) setCreateReview(null);
    if (!preserveActivityReview) setActivityReview(null);
    setSelectedActionId(actionId);
    setShowMoreActions(false);
    setStudioView('action');
    setTab('studio');
  };

  if (stage === 'onboarding') {
    return (
      <SafeAreaView style={styles.root}>
        <StatusBar style="dark" />
        <OnboardingScreen
          onDone={() => {
            markOnboarded();
            setAuthLifecycleEnabled(true);
            setStage('booting');
          }}
        />
      </SafeAreaView>
    );
  }

  if (stage === 'tour') {
    return (
      <SafeAreaView style={styles.root}>
        <StatusBar style="dark" />
        <WorkflowShowcase onDone={() => setStage('login')} />
      </SafeAreaView>
    );
  }

  if (stage === 'booting') {
    return (
      <SafeAreaView style={[styles.root, styles.booting]}>
        <StatusBar style="dark" />
        <ActivityIndicator color={theme.accent} />
        <Text style={styles.bootingText}>Checking your Facetta session…</Text>
      </SafeAreaView>
    );
  }

  if (stage === 'login') {
    return (
      <SafeAreaView style={styles.root}>
        <StatusBar style="dark" />
        <LoginScreen
          onSignIn={(s) => {
            if (sessionAccessToken(s) === null) {
              throw new Error('This sign-in method is not available yet. Please choose another option.');
            }
            adoptAuthenticatedSession(s);
          }}
          onShowTour={() => setStage('tour')}
        />
      </SafeAreaView>
    );
  }

  if (stage === 'recovery') {
    return (
      <SafeAreaView style={styles.root}>
        <StatusBar style="dark" />
        <PasswordRecoveryScreen onComplete={() => setStage('app')} />
      </SafeAreaView>
    );
  }

  return (
    <AuthenticatedImageProvider headers={authenticatedImageHeaders} allowedOrigin={apiUrl}>
    <SafeAreaView
      testID="authenticated-shell"
      style={[styles.root, styles.authenticatedShell, isStudioHome && styles.rootDark]}>
      <StatusBar style={isStudioHome ? 'light' : 'dark'} />
      <View style={[styles.header, isStudioHome && styles.headerDark]}>
        <View>
          <Text style={[styles.logo, isStudioHome && styles.logoDark]}>FACETTA</Text>
          <Text style={[styles.screenTitle, isStudioHome && styles.screenTitleDark]}>
            {tab === 'studio'
              ? studioView === 'home' ? 'Studio' : getStudioAction(selectedActionId).label
              : tab === 'collections'
                ? 'Collections'
                : tab === 'activity'
                  ? 'Activity'
                  : tab === 'learn'
                    ? 'Learn'
                    : 'Shared design'}
          </Text>
        </View>
        <Pressable
          accessibilityLabel="Account and settings"
          style={[styles.utilityButton, isStudioHome && styles.utilityButtonDark]}
          onPress={() => setShowUtilityMenu(!showUtilityMenu)}>
          <Text style={[styles.utilityIcon, isStudioHome && styles.utilityIconDark]}>•••</Text>
        </Pressable>
      </View>
      {showUtilityMenu && (
        <View style={[styles.utilityMenu, shadows.lifted]}>
          {session && <Text style={styles.sessionEmail}>{session.email}</Text>}
          <Pressable
            style={styles.utilityRow}
            onPress={() => {
              void signOutAuthenticatedSession().finally(clearAuthenticatedUi);
            }}>
            <Text style={[styles.utilityRowText, { color: theme.danger }]}>Sign out</Text>
          </Pressable>
        </View>
      )}
      <View
        testID="authenticated-workspace-surface"
        style={[styles.workspaceSurface, isStudioHome && styles.workspaceSurfaceDark]}>
      {projectHydration !== null && (
        <View style={styles.hydrationBanner}>
          {projectHydration.loading ? (
            <>
              <ActivityIndicator color={theme.accent} />
              <Text style={styles.hydrationText}>Opening the selected design…</Text>
            </>
          ) : (
            <>
              <Text style={styles.hydrationError}>{projectHydration.error}</Text>
              <Pressable
                accessibilityRole="button"
                onPress={() => { void hydrateProject(projectHydration.request); }}>
                <Text style={styles.hydrationRetry}>Retry</Text>
              </Pressable>
            </>
          )}
        </View>
      )}
      {tab === 'studio' && studioView === 'action' && !isCreatingNewDesign && (
        <View style={[styles.actionRail, isStudioHome && styles.actionRailDark]}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.actionRailContent}>
            {studioActions.map((action) => (
              <Pressable
                key={action.id}
                accessibilityRole="button"
                accessibilityLabel={action.label}
                onPress={() => openStudioAction(action.id)}
                style={[
                  styles.actionChip,
                  isStudioHome && styles.actionChipDark,
                  studioView === 'action' && selectedActionId === action.id && styles.actionChipActive,
                ]}>
                <Text style={[
                  styles.actionChipText,
                  isStudioHome && styles.actionChipTextDark,
                  studioView === 'action' && selectedActionId === action.id && styles.actionChipTextActive,
                ]}>{action.shortLabel}</Text>
              </Pressable>
            ))}
          </ScrollView>
          {showMoreActions && (
            <View style={[styles.moreMenu, shadows.lifted]}>
              {moreActions.map((action) => (
                <Pressable key={action.id} style={styles.moreMenuRow} onPress={() => openStudioAction(action.id)}>
                  <Text style={styles.moreMenuTitle}>{action.shortLabel}</Text>
                  <Text style={styles.moreMenuBody}>{action.description}</Text>
                </Pressable>
              ))}
            </View>
          )}
        </View>
      )}

      {isStudioHome && (
        <ScrollView
          style={styles.dashboard}
          contentContainerStyle={styles.dashboardContent}
          showsVerticalScrollIndicator={false}>
          <View style={styles.dashboardIntro}>
            <View style={styles.livePill}><Text style={styles.livePillText}>✦ FOR DESIGNERS & BRANDS</Text></View>
            <Text style={styles.dashboardTitle}>Turn imagination into something real.</Text>
            <Text style={styles.dashboardBody}>
              Design, refine, visualize, and organize every direction in one precise creative system.
            </Text>
          </View>

          {hasActiveRevision && (
            <StudioCard
              image={studioProject?.active_revision?.image_url
                ? { uri: studioProject.active_revision.image_url }
                : designImage}
              imageLabel="Current design cover"
              eyebrow="CURRENT DESIGN"
              title={studioProject?.title ?? 'Resume your design'}
              body="Continue from the current saved revision. Every Studio action will use this exact starting point."
              accent="#8de2c2"
              wide
              onPress={() => openStudioAction('refine')}
            />
          )}
          {!hasActiveRevision && savedFamiliesState === 'available' && (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Continue saved work"
              style={styles.savedWorkCard}
              onPress={() => setTab('collections')}>
              <View style={styles.savedWorkCopy}>
                <Text style={styles.savedWorkEyebrow}>SAVED WORK</Text>
                <Text style={styles.savedWorkTitle}>Continue saved work</Text>
                <Text style={styles.savedWorkBody}>Open Collections to continue a design family or revision.</Text>
              </View>
              <Text style={styles.savedWorkArrow}>→</Text>
            </Pressable>
          )}
          <StudioCard
            image={designImage}
            imageLabel="New design inspiration"
            eyebrow="NEW DESIGN"
            title="Start from an idea or reference"
            body="Begin with a sentence, drawing, photograph, render, or master-geometry image."
            accent="#b9a6ff"
            wide
            onPress={() => openStudioAction('create')}
          />

        </ScrollView>
      )}

      {tab === 'studio' && studioView === 'action' && (
        <View style={styles.actionWorkspace}>
          <View style={styles.actionContextBanner}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Back to Studio"
              style={styles.actionContextBack}
              onPress={() => setStudioView('home')}>
              <Text style={styles.actionContextBackText}>← Studio</Text>
            </Pressable>
            {!isCreatingNewDesign && studioProject !== null && actionSourceRevision !== null && (
              <View testID="active-design-context" style={styles.actionDesignContext}>
                {actionSourceImageUrl !== null ? (
                  <Image
                    accessibilityLabel={`${studioProject.title} revision thumbnail`}
                    source={{ uri: actionSourceImageUrl }}
                    style={styles.actionRevisionThumbnail}
                    resizeMode="cover"
                  />
                ) : (
                  <View style={[styles.actionRevisionThumbnail, styles.actionRevisionPlaceholder]}>
                    <Text style={styles.actionRevisionPlaceholderText}>
                      {actionSourceRevision.revision ?? '•'}
                    </Text>
                  </View>
                )}
                <View style={styles.actionDesignCopy}>
                  <Text numberOfLines={1} style={styles.actionDesignTitle}>{studioProject.title}</Text>
                  <Text numberOfLines={1} style={styles.actionRevisionLabel}>
                    {actionSourceIsCurrent ? 'Current saved revision' : 'Review source'}
                    {actionSourceRevision.revision === null
                      ? ''
                      : ` · Revision ${actionSourceRevision.revision}`}
                  </Text>
                </View>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Open revision history"
                  style={styles.actionHistoryButton}
                  onPress={() => setTab('collections')}>
                  <Text style={styles.actionHistoryButtonText}>History</Text>
                </Pressable>
              </View>
            )}
          </View>
          {selectedActionId === 'create' ? (
            <StudioCreateWorkspace
              key={createReview === null
                ? 'new-create'
                : `resume-create:${createReview.project.root_id}:${createReview.studioJobId}`}
              gateway={studioGateway}
              owner={designer}
              resumeProject={createReview?.project ?? null}
              resumeStudioJobId={createReview?.studioJobId ?? null}
              onRequestReference={pickExpoStudioCreateReference}
              onSave={(selection) => {
                setCreateReview(null);
                setStudioProject(selection.project);
                setSelectedCreativeAssetId(selection.selectedAssetId);
                openStudioAction('refine');
              }}
            />
          ) : selectedActionId === 'refine' || selectedActionId === 'specifications' ? (
            <StudioRefineWorkspace
              key={activityReview === null ? selectedActionId : `${selectedActionId}:${activityReview.job.job_id}`}
              api={studioGateway}
              gateway={studioGateway}
              lineage={activityReview?.job.action_id === 'refine'
                ? activityReview.lineage : exactStudioLineage ?? visualStudioLineage}
              createdBy={designer}
              sourceImageUrl={activityReview?.job.action_id === 'refine'
                ? activityReview.sourceImageUrl : studioProject?.active_revision?.image_url ?? null}
              resumeReviewJobId={activityReview?.job.action_id === 'refine'
                ? activityReview.job.job_id : undefined}
              reviewSourceIsActive={activityReview?.job.action_id === 'refine'
                ? activityReview.sourceIsActive : true}
              initialAdvancedFactsOpen={selectedActionId === 'specifications'}
              onReviewStartingDesign={confirmStudioLineage !== null
                ? () => openStudioAction('confirm')
                : undefined}
              onApplied={(project) => {
                setActivityReview(null);
                setStudioProject(project);
                setSelectedCreativeAssetId(project.active_asset_id);
              }}
              onVariationCreated={(project) => {
                setActivityReview(null);
                setStudioProject(project);
                setSelectedCreativeAssetId(project.active_asset_id);
              }}
              onOpenCollections={() => setTab('collections')}
              onPresent={() => openStudioAction('present')}
              imageRequestHeaders={authenticatedImageHeaders}
            />
          ) : selectedActionId === 'views' ? (
            <StudioViewsWorkspace
              gateway={studioGateway}
              lineage={activityReview?.job.action_id === 'views'
                && 'sourceDesignVersion' in activityReview.lineage
                ? activityReview.lineage : exactStudioLineage}
              createdBy={designer}
              onSaved={(project) => {
                setActivityReview(null);
                setStudioProject(project);
              }}
              onOpenCollections={() => setTab('collections')}
              imageRequestHeaders={authenticatedImageHeaders}
              resumeReviewJobId={activityReview?.job.action_id === 'views'
                ? activityReview.job.job_id : undefined}
              reviewSourceIsActive={activityReview?.job.action_id === 'views'
                ? activityReview.sourceIsActive : true}
            />
          ) : selectedActionId === 'confirm' ? (
            <StudioConfirmWorkspace
              gateway={studioGateway}
              lineage={confirmStudioLineage}
              createdBy={designer}
              onSaved={(receipt) => {
                setStudioProject(receipt.project);
                setSelectedCreativeAssetId(receipt.project.active_asset_id);
                openStudioAction('refine');
              }}
            />
          ) : selectedActionId === 'present' ? (
            <StudioPresentWorkspace
              gateway={studioGateway}
              lineage={activityReview?.job.action_id === 'present'
                ? activityReview.lineage : exactStudioLineage ?? visualStudioLineage}
              createdBy={designer}
              onProjectUpdated={(project) => {
                setActivityReview(null);
                setStudioProject(project);
              }}
              onOpenCollections={() => setTab('collections')}
              imageRequestHeaders={authenticatedImageHeaders}
              resumeReviewJobId={activityReview?.job.action_id === 'present'
                ? activityReview.job.job_id : undefined}
              reviewSourceIsActive={activityReview?.job.action_id === 'present'
                ? activityReview.sourceIsActive : true}
            />
          ) : selectedActionId === 'vary' ? (
            <StudioVaryWorkspace
              gateway={studioGateway}
              lineage={visualStudioLineage === null ? null : {
                ...visualStudioLineage,
                sourceDesignVersion: exactStudioLineage?.sourceDesignVersion ?? null,
              }}
              createdBy={designer}
              onCreated={(project) => {
                setStudioProject(project);
                setSelectedCreativeAssetId(project.active_asset_id);
              }}
              onContinueRefining={() => openStudioAction('refine')}
              onOpenCollections={() => setTab('collections')}
            />
          ) : selectedActionId === 'factory' ? (
            <StudioFactoryWorkspace
              api={studioGateway}
              lineage={exactStudioLineage}
              createdBy={designer}
              deliverProtectedFile={deliverProtectedFile}
              onProjectUpdated={setStudioProject}
            />
          ) : assertNeverStudioAction(selectedActionId)}
        </View>
      )}
      {tab === 'collections' && (
        <StudioCollectionsWorkspace
          api={studioGateway}
          project={studioProject}
          createdBy={designer}
          deliverProtectedFile={deliverProtectedFile}
          onOpenProject={(projectId) => {
            void hydrateProject({ projectId, destination: 'collections' });
          }}
          onProjectChanged={(project) => {
            setStudioProject(project);
            setSelectedCreativeAssetId(project.active_asset_id);
          }}
          onStartDesign={() => openStudioAction('create')}
          onVaryCurrent={() => openStudioAction('vary')}
          onContinueRefining={() => openStudioAction('refine')}
          onPresentCurrent={() => openStudioAction('present')}
          onPrepareFactoryCurrent={getStudioAction('factory').isAvailable(actionContext)
            ? () => openStudioAction('factory')
            : undefined}
        />
      )}
      {tab === 'activity' && (
        <StudioActivityWorkspace
          api={studioGateway}
          owner={designer}
          onOpenReview={(job) => {
            if (job.active_design_id === null) return;
            if (job.action_id === 'create') {
              void hydrateProject({
                projectId: job.active_design_id,
                destination: 'create',
                studioJobId: job.job_id,
              });
              return;
            }
            if (job.source_revision_id === null) return;
            if (!(['refine', 'views', 'present'] as const).includes(
              job.action_id as 'refine' | 'views' | 'present',
            )) return;
            void hydrateProject({
              projectId: job.active_design_id,
              destination: job.action_id as 'refine' | 'views' | 'present',
              reviewJobId: job.job_id,
            });
          }}
          onOpenDesign={(projectId) => {
            void hydrateProject({ projectId, destination: 'collections' });
          }}
        />
      )}

      {tab === 'learn' && (
        <ScrollView style={styles.workspacePage} contentContainerStyle={styles.workspacePageContent}>
          <Text style={styles.workspaceEyebrow}>FACETTA ACADEMY</Text>
          <Text style={styles.workspaceTitle}>Learn the workflow, when you need it.</Text>
          <Text style={styles.workspaceBody}>
            Short, action-specific guidance keeps education available without crowding the Studio canvas.
          </Text>
          {[
            ['Start from a useful source', 'Begin with a sentence or add one master-geometry image from a sketch, photograph, or render.'],
            ['Refine without design drift', 'Target one region and keep the saved revision unchanged until you accept a preview.'],
            ['Make a confident decision', 'Compare the exact source and preview, then apply, branch, or discard without losing history.'],
          ].map(([title, body]) => (
            <View key={title} style={styles.learnCard}>
              <Text style={styles.learnCardTitle}>{title}</Text>
              <Text style={styles.learnCardBody}>{body}</Text>
            </View>
          ))}
        </ScrollView>
      )}
      </View>

      <View style={[styles.bottomNav, isStudioHome && styles.bottomNavDark, shadows.soft]}>
        {([
          ['studio', '✦', 'Studio'],
          ['collections', '◇', 'Collections'],
          ['activity', '↻', 'Activity'],
          ['learn', '○', 'Learn'],
        ] as const).map(([destination, icon, label]) => (
          <Pressable
            key={destination}
            accessibilityRole="tab"
            accessibilityLabel={label}
            accessibilityState={{ selected: tab === destination }}
            style={styles.navItem}
            onPress={() => {
              setTab(destination);
              if (destination === 'studio') setStudioView('home');
            }}>
            <Text style={[
              styles.navIcon,
              isStudioHome && styles.navIconDark,
              tab === destination && styles.navActive,
              isStudioHome && destination === 'studio' && styles.navActiveDark,
            ]}>{icon}</Text>
            <Text style={[
              styles.navLabel,
              isStudioHome && styles.navLabelDark,
              tab === destination && styles.navActive,
              isStudioHome && destination === 'studio' && styles.navActiveDark,
            ]}>{label}</Text>
          </Pressable>
        ))}
      </View>
    </SafeAreaView>
    </AuthenticatedImageProvider>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.paper },
  authenticatedShell: { width: '100%', minHeight: '100%' },
  workspaceSurface: { flex: 1, backgroundColor: theme.paper },
  workspaceSurfaceDark: { backgroundColor: '#15121c' },
  booting: { alignItems: 'center', justifyContent: 'center', gap: 12 },
  bootingText: { color: theme.faint, fontSize: 13 },
  rootDark: { backgroundColor: '#15121c' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingTop: 12,
    paddingBottom: 10,
    paddingHorizontal: 20,
    borderBottomWidth: 1,
    borderBottomColor: theme.line,
  },
  headerDark: { backgroundColor: '#15121c', borderBottomColor: '#332b40' },
  logo: { fontFamily: theme.serif, fontSize: 14, letterSpacing: 4, color: theme.ink },
  logoDark: { color: '#cbbcff' },
  screenTitle: { fontFamily: theme.serif, fontSize: 21, color: theme.ink, marginTop: 3 },
  screenTitleDark: { color: '#ffffff' },
  utilityButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: theme.card,
    borderWidth: 1,
    borderColor: theme.line,
  },
  utilityButtonDark: { backgroundColor: '#221d2b', borderColor: '#41364f' },
  utilityIcon: { color: theme.ink, fontSize: 16, letterSpacing: 1 },
  utilityIconDark: { color: '#ffffff' },
  utilityMenu: {
    position: 'absolute',
    zIndex: 20,
    top: 68,
    right: 16,
    width: 210,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: theme.line,
    backgroundColor: theme.card,
    padding: 10,
  },
  sessionEmail: { fontSize: 11, color: theme.faint, paddingHorizontal: 10, paddingVertical: 8 },
  utilityRow: { paddingHorizontal: 10, paddingVertical: 11, borderTopWidth: 1, borderTopColor: theme.line },
  utilityRowText: { fontSize: 14, color: theme.ink },
  hydrationBanner: {
    flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 18,
    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.line,
    backgroundColor: theme.card,
  },
  hydrationText: { color: theme.faint, fontSize: 12 },
  hydrationError: { flex: 1, color: theme.danger, fontSize: 12, lineHeight: 17 },
  hydrationRetry: { color: theme.accent, fontSize: 12, fontWeight: '800' },
  actionRail: {
    zIndex: 10,
    borderBottomWidth: 1,
    borderBottomColor: theme.line,
    backgroundColor: theme.paper,
    paddingVertical: 8,
  },
  actionRailDark: { backgroundColor: '#15121c', borderBottomColor: '#332b40' },
  actionRailContent: { gap: 7, paddingHorizontal: 16 },
  actionChip: {
    minWidth: 72,
    alignItems: 'center',
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: theme.line,
    backgroundColor: theme.card,
    paddingHorizontal: 13,
    paddingVertical: 8,
  },
  actionChipDark: { backgroundColor: '#221d2b', borderColor: '#41364f' },
  actionChipActive: { backgroundColor: '#6f52d9', borderColor: '#896ff0' },
  actionChipText: { color: theme.faint, fontSize: 11, fontWeight: '600' },
  actionChipTextDark: { color: '#c8bdcf' },
  actionChipTextActive: { color: '#ffffff' },
  moreMenu: {
    position: 'absolute',
    zIndex: 30,
    top: 52,
    right: 16,
    width: 260,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: theme.line,
    backgroundColor: theme.card,
    padding: 10,
  },
  moreMenuRow: { padding: 10 },
  moreMenuTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  moreMenuBody: { color: theme.faint, fontSize: 11, lineHeight: 16, marginTop: 3 },
  moreMenuEmpty: { color: theme.faint, fontSize: 11, lineHeight: 17, padding: 8 },
  actionWorkspace: { flex: 1 },
  actionContextBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    borderBottomWidth: 1,
    borderBottomColor: theme.line,
    backgroundColor: theme.card,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  actionContextBack: {
    paddingVertical: 9,
    paddingRight: 12,
    borderRightWidth: 1,
    borderRightColor: theme.line,
  },
  actionContextBackText: { color: theme.ink, fontSize: 12, fontWeight: '700' },
  actionDesignContext: {
    flex: 1,
    minWidth: 0,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  actionRevisionThumbnail: {
    width: 42,
    height: 42,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: theme.line,
    backgroundColor: theme.blush,
  },
  actionRevisionPlaceholder: { alignItems: 'center', justifyContent: 'center' },
  actionRevisionPlaceholderText: {
    color: theme.accent,
    fontFamily: theme.serif,
    fontSize: 15,
    fontWeight: '700',
  },
  actionDesignCopy: { flex: 1, minWidth: 0 },
  actionDesignTitle: { color: theme.ink, fontSize: 13, fontWeight: '700' },
  actionRevisionLabel: { color: theme.faint, fontSize: 10, marginTop: 3 },
  actionHistoryButton: {
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: theme.line,
    backgroundColor: theme.paper,
    paddingHorizontal: 11,
    paddingVertical: 7,
  },
  actionHistoryButtonText: { color: theme.ink, fontSize: 10, fontWeight: '700' },
  dashboard: { flex: 1, backgroundColor: '#15121c' },
  dashboardContent: {
    width: '100%',
    maxWidth: 860,
    alignSelf: 'center',
    paddingHorizontal: 16,
    paddingTop: 18,
    paddingBottom: 34,
  },
  dashboardIntro: { marginBottom: 20, maxWidth: 520 },
  livePill: {
    alignSelf: 'flex-start',
    borderRadius: radius.pill,
    backgroundColor: 'rgba(185,166,255,0.13)',
    borderWidth: 1,
    borderColor: 'rgba(185,166,255,0.42)',
    paddingHorizontal: 11,
    paddingVertical: 6,
    marginBottom: 12,
  },
  livePillText: { fontSize: 10, letterSpacing: 1.4, fontWeight: '700', color: '#d4c8ff' },
  dashboardTitle: { fontFamily: theme.serif, fontSize: 31, lineHeight: 36, color: '#ffffff', maxWidth: 360 },
  dashboardBody: { fontSize: 13, lineHeight: 20, color: '#aaa2b5', marginTop: 10, maxWidth: 380 },
  savedWorkCard: {
    width: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: '#41364f',
    backgroundColor: '#221d2b',
    paddingHorizontal: 18,
    paddingVertical: 16,
    marginBottom: 12,
  },
  savedWorkCopy: { flex: 1, paddingRight: 16 },
  savedWorkEyebrow: { color: '#b9a6ff', fontSize: 9, fontWeight: '800', letterSpacing: 1.2 },
  savedWorkTitle: { color: '#ffffff', fontSize: 17, fontWeight: '700', marginTop: 4 },
  savedWorkBody: { color: '#aaa2b5', fontSize: 12, lineHeight: 18, marginTop: 4 },
  savedWorkArrow: { color: '#b9a6ff', fontSize: 22, fontWeight: '600' },
  studioCard: {
    width: '48.5%',
    aspectRatio: 0.92,
    borderRadius: radius.lg,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: '#3d334a',
    backgroundColor: '#211b2a',
  },
  studioCardWide: { width: '100%', aspectRatio: 1.65 },
  studioImage: { flex: 1, justifyContent: 'flex-end', overflow: 'hidden' },
  studioArtwork: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    width: '100%',
    height: '100%',
  },
  studioShade: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    backgroundColor: 'rgba(20,14,27,0.38)',
  },
  studioCardCopy: { padding: 15, paddingRight: 44 },
  studioEyebrow: {
    alignSelf: 'flex-start',
    borderRadius: radius.pill,
    paddingHorizontal: 8,
    paddingVertical: 4,
    marginBottom: 7,
  },
  studioEyebrowText: { fontSize: 8, letterSpacing: 0.8, fontWeight: '800', color: '#111115' },
  studioTitle: { fontFamily: theme.serif, fontSize: 18, color: '#ffffff' },
  studioBody: { fontSize: 10, lineHeight: 14, color: '#e2dce7', marginTop: 5 },
  studioLaunch: {
    position: 'absolute',
    right: 12,
    bottom: 13,
    width: 31,
    height: 31,
    borderRadius: 16,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(24,17,31,0.78)',
  },
  studioLaunchText: { fontSize: 17, lineHeight: 18 },
  capabilityStrip: {
    marginTop: 22,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: '#382e45',
    backgroundColor: '#1d1824',
    padding: 15,
  },
  capabilityStripTitle: { fontFamily: theme.serif, fontSize: 16, color: '#ffffff', marginBottom: 11 },
  capabilityChips: { flexDirection: 'row', flexWrap: 'wrap', gap: 7 },
  capabilityChip: {
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: '#463a55',
    backgroundColor: '#282131',
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  capabilityChipText: { fontSize: 10, color: '#c9c0d2' },
  workspacePage: { flex: 1, backgroundColor: theme.paper },
  workspacePageContent: {
    width: '100%',
    maxWidth: 760,
    alignSelf: 'center',
    paddingHorizontal: 20,
    paddingTop: 30,
    paddingBottom: 50,
  },
  workspaceEyebrow: { color: '#6f52d9', fontSize: 10, fontWeight: '800', letterSpacing: 1.3 },
  workspaceTitle: { color: theme.ink, fontFamily: theme.serif, fontSize: 29, lineHeight: 36, marginTop: 9, maxWidth: 500 },
  workspaceBody: { color: theme.faint, fontSize: 14, lineHeight: 21, marginTop: 10, maxWidth: 540 },
  workspaceNotice: {
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: theme.line,
    backgroundColor: theme.card,
    padding: 20,
    marginTop: 28,
  },
  workspaceNoticeTitle: { color: theme.ink, fontSize: 15, fontWeight: '700' },
  workspaceNoticeBody: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 6 },
  learnCard: {
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: theme.line,
    backgroundColor: theme.card,
    padding: 18,
    marginTop: 12,
  },
  learnCardTitle: { color: theme.ink, fontFamily: theme.serif, fontSize: 17 },
  learnCardBody: { color: theme.faint, fontSize: 12, lineHeight: 18, marginTop: 6 },
  bottomNav: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    alignItems: 'center',
    backgroundColor: theme.card,
    borderTopWidth: 1,
    borderTopColor: theme.line,
    paddingTop: 8,
    paddingBottom: 10,
    paddingHorizontal: 16,
  },
  bottomNavDark: { backgroundColor: '#1b1722', borderTopColor: '#382e45' },
  navItem: { minWidth: 68, alignItems: 'center', gap: 2 },
  navIcon: { fontSize: 20, lineHeight: 23, color: theme.faint },
  navIconDark: { color: '#746a80' },
  navLabel: { fontSize: 11, color: theme.faint },
  navLabelDark: { color: '#746a80' },
  navActive: { color: theme.ink, fontWeight: '600' },
  navActiveDark: { color: '#cbbcff' },
});
