import { StatusBar } from 'expo-status-bar';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator, Pressable, SafeAreaView, ScrollView, StyleSheet, Text,
  useWindowDimensions, View,
} from 'react-native';
import { DEFAULT_API_URL } from './src/api';
import { AuthenticatedImage as Image, AuthenticatedImageProvider } from './src/AuthenticatedImage';
import {
  clearSession, hasOnboarded, loadAuthenticatedSession, markOnboarded,
  restoreAuthenticatedSession, saveSession, sessionAccessToken, Session,
  signOutAuthenticatedSession, subscribeToAuthStateChange,
} from './src/auth';
import { LoginScreen, PasswordRecoveryScreen } from './src/LoginScreen';
import { OnboardingScreen } from './src/OnboardingScreen';
import { getStudioAction, getStudioRailActions, getVisibleStudioActions } from './src/studio/actions';
import { StudioActionContext, StudioActionId } from './src/studio/contracts';
import { StudioCollectionsWorkspace } from './src/studio/StudioCollectionsWorkspace';
import { StudioCreateWorkspace } from './src/studio/StudioCreateWorkspace';
import { StudioConfirmWorkspace } from './src/studio/StudioConfirmWorkspace';
import { pickExpoStudioCreateReference } from './src/studio/expoReferencePicker';
import { StudioRefineWorkspace } from './src/studio/StudioRefineWorkspace';
import { StudioViewsWorkspace } from './src/studio/StudioViewsWorkspace';
import { StudioPresentWorkspace } from './src/studio/StudioPresentWorkspace';
import { StudioVaryWorkspace } from './src/studio/StudioVaryWorkspace';
import { StudioFactoryWorkspace } from './src/studio/StudioFactoryWorkspace';
import { StudioActivityWorkspace } from './src/studio/StudioActivityWorkspace';
import {
  createStudioGatewayFromOptions, ExactStudioLineage, StudioVisualLineage,
} from './src/studio/gateway';
import { radius, shadows, theme } from './src/theme';
import { createTrustedApiClient } from './src/trusted/client';
import type { ProjectDetail } from './src/trusted/types';
import { WorkflowShowcase } from './src/WorkflowShowcase';

type Tab = 'studio' | 'collections' | 'activity' | 'learn';
type StudioView = 'home' | 'action';
type Stage = 'onboarding' | 'tour' | 'booting' | 'login' | 'recovery' | 'app';

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
  const [selectedActionId, setSelectedActionId] = useState<StudioActionId>('create');
  const [showMoreActions, setShowMoreActions] = useState(false);
  const apiUrl = DEFAULT_API_URL;
  const [designer, setDesigner] = useState(session?.designerId ?? '');
  const [showUtilityMenu, setShowUtilityMenu] = useState(false);
  const [studioProject, setStudioProject] = useState<ProjectDetail | null>(null);
  const [selectedCreativeAssetId, setSelectedCreativeAssetId] = useState<string | null>(null);
  const clearAuthenticatedUi = useCallback(() => {
    clearSession();
    setSession(null);
    setDesigner('');
    setStudioProject(null);
    setSelectedCreativeAssetId(null);
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

  const trustedApi = useMemo(
    () => createTrustedApiClient({
      baseUrl: apiUrl.replace(/\/$/, ''),
      getAccessToken: () => sessionAccessToken(session),
      requireAccessToken: true,
      onAuthenticationFailure: expireAuthenticatedSession,
    }),
    [apiUrl, expireAuthenticatedSession, session],
  );
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
    const candidateId = studioProject.selected_candidate_asset_id ?? selectedCreativeAssetId;
    if (candidateId === null || candidateId === undefined) return null;
    const candidate = studioProject.assets.find((asset) => asset.asset_id === candidateId);
    if (candidate?.capability !== 'CREATIVE_RENDER') return null;
    return { projectId: studioProject.root_id, sourceAssetId: candidateId };
  }, [selectedCreativeAssetId, studioProject]);
  const actionContext = useMemo<StudioActionContext>(() => ({
    activeDesignId,
    activeRevisionId: studioProject?.active_asset_id ?? selectedCreativeAssetId,
    hasExactSpecification: exactStudioLineage !== null,
    hasSelectedPreSpecVisual: confirmStudioLineage !== null && exactStudioLineage === null,
    // Factory stays absent from ordinary Studio work. The backend project
    // decision is the only signal that can reveal this optional destination;
    // job creation rechecks the exact revision and eligibility server-side.
    factoryEnabled: studioProject?.factory_ready === true,
    factoryEligible: studioProject?.factory_ready === true,
  }), [activeDesignId, confirmStudioLineage, exactStudioLineage, selectedCreativeAssetId, studioProject]);
  const hasActiveRevision = Boolean(actionContext.activeDesignId && actionContext.activeRevisionId);
  const studioActions = getStudioRailActions(actionContext);
  const moreActions = getVisibleStudioActions(actionContext, 'more');
  const isStudioHome = tab === 'studio' && studioView === 'home';

  const openStudioAction = (actionId: StudioActionId) => {
    if (actionId === 'more') {
      setShowMoreActions((visible) => !visible);
      return;
    }
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
              throw new Error('This sign-in method is not connected to Facetta’s authenticated API yet.');
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
    <SafeAreaView style={[styles.root, isStudioHome && styles.rootDark]}>
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
      {tab === 'studio' && studioView === 'action' && (
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
            <View style={styles.actionContextCopy}>
              <Text style={styles.actionContextEyebrow}>STUDIO</Text>
              <Text style={styles.actionContextBody}>{getStudioAction(selectedActionId).description}</Text>
            </View>
            <Pressable onPress={() => setStudioView('home')}>
              <Text style={styles.actionContextClose}>Close</Text>
            </Pressable>
          </View>
          {selectedActionId === 'create' ? (
            <StudioCreateWorkspace
              gateway={studioGateway}
              owner={designer}
              onRequestReference={pickExpoStudioCreateReference}
              onSave={(selection) => {
                setStudioProject(selection.project);
                setSelectedCreativeAssetId(selection.selectedAssetId);
                openStudioAction('refine');
              }}
            />
          ) : selectedActionId === 'refine' ? (
            <StudioRefineWorkspace
              api={trustedApi}
              gateway={studioGateway}
              lineage={exactStudioLineage ?? visualStudioLineage}
              createdBy={designer}
              sourceImageUrl={studioProject?.active_revision?.image_url ?? null}
              onApplied={(project) => {
                setStudioProject(project);
                setSelectedCreativeAssetId(project.active_asset_id);
              }}
              onVariationCreated={(project) => {
                setStudioProject(project);
                setSelectedCreativeAssetId(project.active_asset_id);
              }}
              imageRequestHeaders={authenticatedImageHeaders}
            />
          ) : selectedActionId === 'views' ? (
            <StudioViewsWorkspace
              gateway={studioGateway}
              lineage={exactStudioLineage}
              createdBy={designer}
              onSaved={setStudioProject}
              imageRequestHeaders={authenticatedImageHeaders}
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
              lineage={exactStudioLineage ?? visualStudioLineage}
              createdBy={designer}
              onProjectUpdated={setStudioProject}
              imageRequestHeaders={authenticatedImageHeaders}
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
              api={trustedApi}
              lineage={exactStudioLineage}
              createdBy={designer}
            />
          ) : (
            <View style={styles.workspaceNotice}>
              <Text style={styles.workspaceNoticeTitle}>{getStudioAction(selectedActionId).label}</Text>
              <Text style={styles.workspaceNoticeBody}>
                This destination will use the exact active revision. It is hidden from production use until its preview-and-accept contract is complete.
              </Text>
            </View>
          )}
        </View>
      )}
      {tab === 'collections' && (
        <StudioCollectionsWorkspace
          api={trustedApi}
          project={studioProject}
          createdBy={designer}
          onOpenProject={(projectId) => {
            void trustedApi.getProject(projectId).then((result) => {
              if (result.error === null) {
                setStudioProject(result.data);
                setSelectedCreativeAssetId(result.data.active_asset_id);
              }
            });
          }}
          onProjectChanged={(project) => {
            setStudioProject(project);
            setSelectedCreativeAssetId(project.active_asset_id);
          }}
          onVariationCreated={(project) => {
            setStudioProject(project);
            setSelectedCreativeAssetId(project.active_asset_id);
          }}
        />
      )}
      {tab === 'activity' && (
        <StudioActivityWorkspace
          api={trustedApi}
          owner={designer}
          onOpenReview={(job) => {
            if (job.active_design_id === null || job.source_revision_id === null) return;
            void trustedApi.getProject(job.active_design_id).then((result) => {
              if (result.error !== null) return;
              setStudioProject(result.data);
              setSelectedCreativeAssetId(result.data.active_asset_id);
              if (result.data.active_asset_id === job.source_revision_id) {
                openStudioAction('refine');
              } else {
                setTab('collections');
              }
            });
          }}
          onOpenDesign={(projectId) => {
            void trustedApi.getProject(projectId).then((result) => {
              if (result.error === null) {
                setStudioProject(result.data);
                setSelectedCreativeAssetId(result.data.active_asset_id);
                setTab('collections');
              }
            });
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

      <View style={[styles.bottomNav, isStudioHome && styles.bottomNavDark, shadows.soft]}>
        {([
          ['studio', '✦', 'Studio'],
          ['collections', '◇', 'Collections'],
          ['activity', '↻', 'Activity'],
          ['learn', '○', 'Learn'],
        ] as const).map(([destination, icon, label]) => (
          <Pressable
            key={destination}
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
    justifyContent: 'space-between',
    borderBottomWidth: 1,
    borderBottomColor: theme.line,
    backgroundColor: theme.card,
    paddingHorizontal: 18,
    paddingVertical: 10,
  },
  actionContextCopy: { flex: 1, paddingRight: 14 },
  actionContextEyebrow: { color: '#6f52d9', fontSize: 9, fontWeight: '800', letterSpacing: 1.1 },
  actionContextBody: { color: theme.faint, fontSize: 11, lineHeight: 16, marginTop: 3 },
  actionContextClose: { color: theme.ink, fontSize: 12, fontWeight: '600' },
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
