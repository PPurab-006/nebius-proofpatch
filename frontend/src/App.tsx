import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { supabase, isSupabaseConfigured } from './supabaseClient';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
if (API_BASE_URL) {
  axios.defaults.baseURL = API_BASE_URL;
}

// Attach Supabase access token to all outgoing requests if active
axios.interceptors.request.use(async (config) => {
  if (supabase) {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (session?.access_token) {
        config.headers = config.headers || {};
        config.headers.Authorization = `Bearer ${session.access_token}`;
      }
    } catch (err) {
      console.error('Error attaching auth token to request:', err);
    }
  }
  return config;
});

import {
  Bug,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  AlertCircle,
  Terminal,
  FileCode,
  Download,
  RefreshCw,
  Sliders,
  Shield,
  Copy,
  Check,
  ChevronRight,
  Menu,
  X,
  Folder,
  Upload,
  Cpu,
  Layers,
  FileText,
  History,
  RotateCcw,
  Sparkles,
  GitPullRequest,
  GitBranch,
  ExternalLink,
  Lock,
  Search,
  Key,
  User,
  LogIn,
  LogOut,
  Mail
} from 'lucide-react';

const Github = ({ className = "w-4 h-4" }: { className?: string }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
    <path d="M9 18c-4.51 2-5-2-7-2" />
  </svg>
);

interface HealthStatus {
  status: string;
  message: string;
  nebius_configured: boolean;
  supabase_configured?: boolean;
  model: string;
}

interface DiagnosisData {
  diagnosis: string;
  evidence: string;
  files_to_modify: string[];
  proposed_fix_description: string;
  regression_risks?: string;
}

export interface RepoFinding {
  id: string;
  title: string;
  category: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
  confidence: 'high' | 'medium' | 'low';
  impact?: string;
  risk?: string;
  files: string[];
  line_numbers?: number[];
  evidence: string;
  explanation: string;
  action?: string;
  proposed_fix: string;
}

export interface ProjectProfile {
  languages: string[];
  manifests: string[];
  detected_test_command: string | null;
  source_files_count: number;
  readme_summary: string;
}

interface DiagnosisResponse {
  status: string;
  workspace_id?: string;
  mode?: 'targeted' | 'bug_discovery' | 'improvement';
  profile?: ProjectProfile;
  findings?: RepoFinding[];
  investigation?: {
    summary: string;
    findings: RepoFinding[];
  };
  reproduction?: {
    success: boolean;
    stdout: string;
    stderr: string;
    returncode: number;
  };
  diagnosis: DiagnosisData;
}

interface RepairResponse {
  status: string;
  workspace_id?: string;
  message?: string;
  patch: string;
  patch_applied?: boolean;
  verification_status?: string;
  verification_details?: {
    success: boolean;
    stdout: string;
    stderr: string;
    returncode: number;
  };
}

interface GitHubUser {
  login: string;
  name?: string;
  avatar_url?: string;
  html_url?: string;
  scopes?: string[];
}

interface GitHubRepo {
  id: number;
  name: string;
  full_name: string;
  owner: string;
  private: boolean;
  html_url: string;
  description: string;
  default_branch: string;
  updated_at: string;
  permissions?: { push: boolean; pull: boolean };
}

interface GitHubBranch {
  name: string;
  commit_sha?: string;
  protected?: boolean;
}

interface GitHubStatus {
  connected: boolean;
  configured: boolean;
  oauth_available?: boolean;
  user: GitHubUser | null;
  auth_type: string;
  error?: string;
}

interface PublishReadiness {
  ready: boolean;
  verification_status: string;
  diverged: boolean;
  starting_commit_sha?: string;
  remote_commit_sha?: string;
  owner?: string;
  repo?: string;
  target_branch?: string;
  published_pr?: any;
  reason?: string;
}

interface SessionRecord {
  id: string;
  workspaceId: string;
  timestamp: string;
  repoUrl: string;
  issueDescription: string;
  verificationStatus: string;
  diagnosis?: DiagnosisData;
  repair?: RepairResponse;
  prUrl?: string;
  prNumber?: number;
  branch?: string;
}

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [rollbackModalOpen, setRollbackModalOpen] = useState(false);
  const [copiedWsId, setCopiedWsId] = useState(false);

  // Ingestion inputs
  const [inputType, setInputType] = useState<'github' | 'git' | 'zip' | 'benchmark'>('github');
  const [repoUrl, setRepoUrl] = useState('');
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [issueDescription, setIssueDescription] = useState('');
  const [testCommand, setTestCommand] = useState('');

  // GitHub integration states
  const [ghStatus, setGhStatus] = useState<GitHubStatus>({
    connected: false,
    configured: false,
    user: null,
    auth_type: 'none'
  });
  const [ghConnectModalOpen, setGhConnectModalOpen] = useState(false);
  const [ghTokenInput, setGhTokenInput] = useState('');
  const [ghConnecting, setGhConnecting] = useState(false);
  const [ghConnectError, setGhConnectError] = useState('');

  // GitHub repository selection states
  const [ghRepos, setGhRepos] = useState<GitHubRepo[]>([]);
  const [ghReposLoading, setGhReposLoading] = useState(false);
  const [ghSearchQuery, setGhSearchQuery] = useState('');
  const [selectedRepo, setSelectedRepo] = useState<GitHubRepo | null>(null);
  const [ghBranches, setGhBranches] = useState<GitHubBranch[]>([]);
  const [ghBranchesLoading, setGhBranchesLoading] = useState(false);
  const [selectedBranch, setSelectedBranch] = useState<string>('main');
  const [ghWorkspaceInfo, setGhWorkspaceInfo] = useState<{
    owner: string;
    repo: string;
    branch: string;
    commitSha: string;
  } | null>(null);

  // GitHub Pull Request publication states
  const [publishModalOpen, setPublishModalOpen] = useState(false);
  const [publishTitle, setPublishTitle] = useState('');
  const [publishNotes, setPublishNotes] = useState('');
  const [publishReadiness, setPublishReadiness] = useState<PublishReadiness | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState<{
    pr_url: string;
    pr_number: number;
    branch: string;
    commit_sha: string;
    note?: string;
  } | null>(null);
  const [publishError, setPublishError] = useState('');

  // Execution states
  const [requestMode, setRequestMode] = useState<'auto' | 'targeted' | 'bug_discovery' | 'improvement'>('auto');
  const [selectedFinding, setSelectedFinding] = useState<RepoFinding | null>(null);
  const [rightPanelView, setRightPanelView] = useState<'findings' | 'patch'>('findings');
  const [retryCount, setRetryCount] = useState<number>(0);
  const [diagnosis, setDiagnosis] = useState<DiagnosisResponse | null>(null);
  const [repair, setRepair] = useState<RepairResponse | null>(null);
  const [pipelineStep, setPipelineStep] = useState<number>(0);
  // 0 = idle, 1 = repo prep, 2 = diagnosing, 3 = generating patch, 4 = applying, 5 = verifying, 6 = complete
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState('');
  const [error, setError] = useState('');

  // Supabase User Authentication States
  const [user, setUser] = useState<{ id: string; email?: string; avatar_url?: string } | null>(null);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authMode, setAuthMode] = useState<'signin' | 'signup' | 'magic'>('signin');
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState('');
  const [authSuccessMsg, setAuthSuccessMsg] = useState('');

  // Session history
  const [recentSessions, setRecentSessions] = useState<SessionRecord[]>(() => {
    try {
      const saved = localStorage.getItem('patchworks_sessions');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  const fetchPersistentHistory = async () => {
    try {
      const res = await axios.get('/api/history');
      if (res.data?.sessions && Array.isArray(res.data.sessions)) {
        const mapped: SessionRecord[] = res.data.sessions.map((row: any) => ({
          id: row.id,
          workspaceId: row.workspace_id || row.id,
          timestamp: row.created_at ? new Date(row.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Recent',
          repoUrl: row.repo_url,
          issueDescription: row.issue_description,
          verificationStatus: row.verification_status || 'DIAGNOSED',
          diagnosis: row.diagnosis,
          repair: row.patch
            ? {
                status: row.status || 'success',
                patch: row.patch,
                verification_status: row.verification_status || 'VERIFIED',
                verification_details: row.verification_details,
              }
            : undefined,
          prUrl: row.pr_url,
          prNumber: row.pr_number,
          branch: row.branch,
        }));
        setRecentSessions(mapped);
      }
    } catch (e) {
      console.error('Failed to fetch persistent history:', e);
    }
  };

  const handleSupabaseGitHubLogin = async () => {
    if (!supabase) return;
    setAuthLoading(true);
    setAuthError('');
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'github',
        options: {
          redirectTo: window.location.origin,
        },
      });
      if (error) throw error;
    } catch (err: any) {
      setAuthError(err.message || 'GitHub OAuth initiation failed');
      setAuthLoading(false);
    }
  };

  const handleEmailSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!supabase) return;
    setAuthLoading(true);
    setAuthError('');
    try {
      const { error } = await supabase.auth.signInWithPassword({
        email: authEmail.trim(),
        password: authPassword,
      });
      if (error) throw error;
      setAuthModalOpen(false);
    } catch (err: any) {
      setAuthError(err.message || 'Failed to sign in');
    } finally {
      setAuthLoading(false);
    }
  };

  const handleEmailSignUp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!supabase) return;
    setAuthLoading(true);
    setAuthError('');
    try {
      const { data, error } = await supabase.auth.signUp({
        email: authEmail.trim(),
        password: authPassword,
      });
      if (error) throw error;
      if (data.session) {
        setAuthModalOpen(false);
      } else {
        setAuthSuccessMsg('Sign-up confirmation sent! Please check your inbox.');
      }
    } catch (err: any) {
      setAuthError(err.message || 'Failed to sign up');
    } finally {
      setAuthLoading(false);
    }
  };

  const handleMagicLink = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!supabase) return;
    setAuthLoading(true);
    setAuthError('');
    try {
      const { error } = await supabase.auth.signInWithOtp({
        email: authEmail.trim(),
        options: {
          emailRedirectTo: window.location.origin,
        },
      });
      if (error) throw error;
      setAuthSuccessMsg('Magic link sent to your email!');
    } catch (err: any) {
      setAuthError(err.message || 'Failed to send magic link');
    } finally {
      setAuthLoading(false);
    }
  };

  const handleSignOut = async () => {
    if (!supabase) return;
    try {
      await supabase.auth.signOut();
      setUser(null);
      try {
        const saved = localStorage.getItem('patchworks_sessions');
        setRecentSessions(saved ? JSON.parse(saved) : []);
      } catch {
        setRecentSessions([]);
      }
      fetchGitHubStatus();
    } catch (err) {
      console.error('Error signing out:', err);
    }
  };

  useEffect(() => {
    fetchHealth();
    fetchGitHubStatus();

    const params = new URLSearchParams(window.location.search);
    if (params.get('github_connected') === 'true') {
      window.history.replaceState({}, '', window.location.pathname);
      fetchGitHubStatus();
    }

    if (supabase) {
      supabase.auth.getSession().then(({ data: { session } }) => {
        if (session?.user) {
          setUser({
            id: session.user.id,
            email: session.user.email,
            avatar_url: session.user.user_metadata?.avatar_url,
          });
          fetchPersistentHistory();
        }
      });

      const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
        if (session?.user) {
          setUser({
            id: session.user.id,
            email: session.user.email,
            avatar_url: session.user.user_metadata?.avatar_url,
          });
          fetchGitHubStatus();
          fetchPersistentHistory();
        } else {
          setUser(null);
          fetchGitHubStatus();
          try {
            const saved = localStorage.getItem('patchworks_sessions');
            setRecentSessions(saved ? JSON.parse(saved) : []);
          } catch {
            setRecentSessions([]);
          }
        }
      });

      return () => {
        subscription.unsubscribe();
      };
    }
  }, []);

  const fetchHealth = () => {
    axios
      .get('/api/health')
      .then((res) => setHealth(res.data))
      .catch((err) => {
        setError(`Failed to reach Patchworks API: ${err.message}`);
      });
  };

  const fetchGitHubStatus = async () => {
    try {
      const res = await axios.get('/api/github/status');
      setGhStatus(res.data);
      if (res.data.connected) {
        fetchGitHubRepos();
      }
    } catch (err: any) {
      console.error('Failed to fetch GitHub status:', err);
    }
  };

  const fetchGitHubRepos = async (query?: string) => {
    setGhReposLoading(true);
    try {
      const params: any = {};
      if (query && query.trim()) params.q = query.trim();
      const res = await axios.get('/api/github/repos', { params });
      setGhRepos(res.data.repos || []);
    } catch (err: any) {
      console.error('Failed to fetch repos:', err);
    } finally {
      setGhReposLoading(false);
    }
  };

  const handleSelectRepo = async (repo: GitHubRepo) => {
    setSelectedRepo(repo);
    setSelectedBranch(repo.default_branch || 'main');
    setRepoUrl(`https://github.com/${repo.full_name}`);
    setGhBranchesLoading(true);
    try {
      const res = await axios.get(`/api/github/repos/${repo.owner}/${repo.name}/branches`);
      setGhBranches(res.data.branches || []);
    } catch (err) {
      console.error('Failed to fetch branches:', err);
      setGhBranches([]);
    } finally {
      setGhBranchesLoading(false);
    }
  };

  const handleCloneGitHubRepo = async () => {
    if (!selectedRepo) return;
    setLoading(true);
    setLoadingMessage(`Cloning ${selectedRepo.full_name} (${selectedBranch}) into isolated sandbox workspace...`);
    setError('');
    try {
      const res = await axios.post('/api/github/workspace', {
        owner: selectedRepo.owner,
        repo: selectedRepo.name,
        branch: selectedBranch
      });
      setWorkspaceId(res.data.workspace_id);
      setGhWorkspaceInfo({
        owner: selectedRepo.owner,
        repo: selectedRepo.name,
        branch: selectedBranch,
        commitSha: res.data.starting_commit_sha
      });
      setPipelineStep(1);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
      setLoadingMessage('');
    }
  };

  const handleGitHubConnect = async () => {
    if (!ghTokenInput.trim()) {
      setGhConnectError('Please enter a GitHub personal access token.');
      return;
    }
    setGhConnecting(true);
    setGhConnectError('');
    try {
      const res = await axios.post('/api/github/connect', { token: ghTokenInput.trim() });
      setGhStatus({
        connected: true,
        configured: true,
        user: res.data.user,
        auth_type: 'pat'
      });
      setGhTokenInput('');
      setGhConnectModalOpen(false);
      fetchGitHubRepos();
    } catch (err: any) {
      setGhConnectError(err.response?.data?.detail || err.message);
    } finally {
      setGhConnecting(false);
    }
  };

  const handleGitHubDisconnect = async () => {
    try {
      await axios.post('/api/github/disconnect');
      setGhStatus({ connected: false, configured: false, user: null, auth_type: 'none' });
      setGhRepos([]);
      setSelectedRepo(null);
      setGhBranches([]);
      setGhWorkspaceInfo(null);
    } catch (err: any) {
      console.error('Failed to disconnect GitHub:', err);
    }
  };

  const checkPublishReadiness = async (wsId?: string) => {
    const targetWsId = wsId || workspaceId;
    if (!targetWsId) return;
    try {
      const res = await axios.get(`/api/github/publish/readiness?workspace_id=${targetWsId}`);
      setPublishReadiness(res.data);
    } catch (err) {
      console.error('Failed to check publish readiness:', err);
    }
  };

  const handlePublishPR = async () => {
    if (!workspaceId) return;
    setPublishing(true);
    setPublishError('');
    try {
      const payload = {
        workspace_id: workspaceId,
        title: publishTitle.trim() || issueDescription.slice(0, 70) || 'Fix bug autonomously with Patchworks',
        custom_notes: publishNotes.trim() || undefined
      };
      const res = await axios.post('/api/github/publish', payload);
      setPublishResult(res.data);
      setPublishModalOpen(false);
      
      // Update session record
      setRecentSessions((prev) =>
        prev.map((s) =>
          s.workspaceId === workspaceId
            ? {
                ...s,
                prUrl: res.data.pr_url,
                prNumber: res.data.pr_number,
                branch: res.data.branch
              }
            : s
        )
      );
      checkPublishReadiness(workspaceId);
    } catch (err: any) {
      setPublishError(err.response?.data?.detail || err.message);
    } finally {
      setPublishing(false);
    }
  };

  const saveSession = (
    wsId: string,
    diag?: DiagnosisData,
    rep?: RepairResponse,
    prData?: { prUrl?: string; prNumber?: number; branch?: string }
  ) => {
    const record: SessionRecord = {
      id: Date.now().toString(),
      workspaceId: wsId,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      repoUrl: ghWorkspaceInfo
        ? `${ghWorkspaceInfo.owner}/${ghWorkspaceInfo.repo}`
        : repoUrl || (zipFile ? zipFile.name : 'Benchmark'),
      issueDescription: issueDescription.slice(0, 60),
      verificationStatus: rep?.verification_status || 'DIAGNOSED',
      diagnosis: diag,
      repair: rep,
      prUrl: prData?.prUrl || publishResult?.pr_url,
      prNumber: prData?.prNumber || publishResult?.pr_number,
      branch: prData?.branch || publishResult?.branch
    };

    setRecentSessions((prev) => {
      const updated = [record, ...prev.filter((s) => s.workspaceId !== wsId)].slice(0, 10);
      try {
        localStorage.setItem('patchworks_sessions', JSON.stringify(updated));
      } catch (e) {
        console.error('Failed to save sessions:', e);
      }
      return updated;
    });

    if (user) {
      axios.post('/api/history', {
        workspace_id: wsId,
        repo_url: record.repoUrl,
        issue_description: issueDescription || 'Investigation session',
        mode: requestMode,
        status: 'completed',
        diagnosis: diag as any,
        findings: diagnosis?.findings as any,
        patch: rep?.patch,
        verification_status: record.verificationStatus,
        verification_details: rep?.verification_details as any,
        pr_url: record.prUrl,
        pr_number: record.prNumber,
        branch: record.branch,
      }).catch((e) => console.warn('Could not persist session to backend history:', e));
    }
  };

  const deleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setRecentSessions((prev) => {
      const updated = prev.filter((s) => s.id !== sessionId && s.workspaceId !== sessionId);
      try {
        localStorage.setItem('patchworks_sessions', JSON.stringify(updated));
      } catch {}
      return updated;
    });
    if (user) {
      try {
        await axios.delete(`/api/history/${sessionId}`);
      } catch (err) {
        console.warn('Failed to delete session from server:', err);
      }
    }
  };

  const clearSessions = async () => {
    const toDelete = [...recentSessions];
    setRecentSessions([]);
    try {
      localStorage.removeItem('patchworks_sessions');
    } catch {}
    if (user) {
      for (const s of toDelete) {
        try {
          await axios.delete(`/api/history/${s.id}`);
        } catch {}
      }
    }
  };

  const loadBenchmark = async (type: 'simple_bug' | 'edge_case') => {
    // If an existing workspace is open, clean it up
    if (workspaceId) {
      axios.delete(`/api/workspace/${workspaceId}`).catch(console.error);
    }

    setInputType('benchmark');
    setSelectedRepo(null);
    setGhWorkspaceInfo(null);
    setPublishReadiness(null);
    setPublishResult(null);
    setPublishError('');
    setZipFile(null);
    setDiagnosis(null);
    setRepair(null);
    setError('');

    const formattedRepoUrl = `benchmark://${type}`;
    setRepoUrl(formattedRepoUrl);

    if (type === 'simple_bug') {
      setIssueDescription('test_subtract in math_utils.py fails because it adds (a + b) instead of subtracting (a - b).');
      setTestCommand('pytest test_math_utils.py');
    } else {
      setIssueDescription('truncate in text_utils.py has an off-by-one boundary check: truncates when len(text) == max_length instead of exceeding it.');
      setTestCommand('pytest test_text_utils.py');
    }

    setLoading(true);
    setLoadingMessage(`Initializing isolated sandbox workspace for '${type}' benchmark...`);
    try {
      const res = await axios.post('/api/benchmark/workspace', { fixture: type });
      setWorkspaceId(res.data.workspace_id);
      setPipelineStep(1);
    } catch (err: any) {
      console.warn('Direct benchmark workspace creation deferred:', err);
      setWorkspaceId(null);
      setPipelineStep(0);
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
      setLoadingMessage('');
    }
  };

  const handleZipUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setZipFile(file);
      setLoading(true);
      setLoadingMessage('Uploading and safely extracting repository archive...');
      setError('');
      try {
        const formData = new FormData();
        formData.append('file', file);
        const response = await axios.post('/api/upload', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });
        setWorkspaceId(response.data.workspace_id);
        setPipelineStep(1);
      } catch (err: any) {
        setError(err.response?.data?.detail || err.message);
        setZipFile(null);
      } finally {
        setLoading(false);
        setLoadingMessage('');
      }
    }
  };

  const handleDiagnose = async () => {
    setLoading(true);
    let initialLoadingMsg = 'Synthesizing defect diagnosis with Nebius inference engine...';
    if (requestMode === 'improvement') {
      initialLoadingMsg = 'Auditing repository and generating improvement recommendations...';
    } else if (requestMode === 'bug_discovery') {
      initialLoadingMsg = 'Scanning repository for latent bugs and correctness defects...';
    } else {
      const lower = (issueDescription || '').toLowerCase();
      if (lower.includes('improv') || lower.includes('enhanc') || lower.includes('better') || lower.includes('review') || lower.includes('audit')) {
        initialLoadingMsg = 'Auditing repository and generating improvement recommendations with Nebius...';
      } else if (lower.includes('scan') || lower.includes('find') || lower.includes('latent') || lower.includes('vulnerab') || lower.includes('security')) {
        initialLoadingMsg = 'Scanning repository for latent defects with Nebius inference engine...';
      } else {
        initialLoadingMsg = 'Investigating repository and synthesizing findings with Nebius...';
      }
    }
    setLoadingMessage(initialLoadingMsg);
    setPipelineStep(2);
    setError('');
    try {
      const payload: any = {
        issue_description: issueDescription,
        test_command: testCommand ? testCommand.trim() : undefined,
        mode: requestMode !== 'auto' ? requestMode : undefined
      };

      if (workspaceId) {
        payload.workspace_id = workspaceId;
      } else {
        payload.repo_url = repoUrl.trim();
      }

      const response = await axios.post('/api/diagnose', payload);
      setDiagnosis(response.data);
      if (response.data.workspace_id) {
        setWorkspaceId(response.data.workspace_id);
      }
      if (!testCommand && response.data.profile?.detected_test_command) {
        setTestCommand(response.data.profile.detected_test_command);
      }
      setRepair(null);
      setSelectedFinding(null);
      setRightPanelView(response.data.findings?.length ? 'findings' : 'patch');
      setPipelineStep(3);
      setRetryCount(0);
      saveSession(response.data.workspace_id, response.data.diagnosis);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message);
      setPipelineStep(0);
    } finally {
      setLoading(false);
      setLoadingMessage('');
    }
  };

  const handleRepair = async () => {
    if (!diagnosis) return;
    setLoading(true);
    setLoadingMessage('Generating minimal unified diff patch and executing sandbox verification...');
    setPipelineStep(4);
    setError('');
    try {
      const payload: any = {
        issue_description: issueDescription,
        diagnosis_context: diagnosis.diagnosis,
        selected_finding: selectedFinding || undefined,
        test_command: testCommand ? testCommand.trim() : undefined
      };

      if (workspaceId) {
        payload.workspace_id = workspaceId;
      } else {
        payload.repo_url = repoUrl.trim();
      }

      setPipelineStep(5);
      const response = await axios.post('/api/repair', payload);
      setRepair(response.data);
      setRightPanelView('patch');
      const targetWs = response.data.workspace_id || workspaceId || '';
      if (response.data.workspace_id) {
        setWorkspaceId(response.data.workspace_id);
      }
      setPipelineStep(6);
      setRetryCount(0);
      saveSession(targetWs, diagnosis.diagnosis, response.data);
      if (ghWorkspaceInfo || inputType === 'github') {
        checkPublishReadiness(targetWs);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message);
      setPipelineStep(3);
    } finally {
      setLoading(false);
      setLoadingMessage('');
    }
  };

  const handleRepairFinding = async (finding: RepoFinding) => {
    setSelectedFinding(finding);
    setLoading(true);
    setLoadingMessage(`Synthesizing patch for finding [${finding.id}: ${finding.title}]...`);
    setPipelineStep(4);
    setError('');
    try {
      const payload: any = {
        workspace_id: workspaceId,
        issue_description: issueDescription,
        selected_finding: finding,
        test_command: testCommand ? testCommand.trim() : undefined
      };
      if (!workspaceId && repoUrl) {
        payload.repo_url = repoUrl.trim();
      }

      setPipelineStep(5);
      setLoadingMessage('Applying patch and verifying in isolated sandbox...');
      const response = await axios.post('/api/repair', payload);
      setRepair(response.data);
      setRightPanelView('patch');
      const targetWs = response.data.workspace_id || workspaceId || '';
      if (response.data.workspace_id) {
        setWorkspaceId(response.data.workspace_id);
      }
      setPipelineStep(6);
      setRetryCount(0);
      if (diagnosis) {
        saveSession(targetWs, diagnosis.diagnosis, response.data);
      }
      if (ghWorkspaceInfo || inputType === 'github') {
        checkPublishReadiness(targetWs);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message);
      setPipelineStep(3);
    } finally {
      setLoading(false);
      setLoadingMessage('');
    }
  };

  const handleFullPipeline = async () => {
    // For broad requests, execute diagnosis/investigation and present findings for selection
    if (requestMode === 'bug_discovery' || requestMode === 'improvement') {
      await handleDiagnose();
      return;
    }

    setLoading(true);
    setLoadingMessage('Executing full autonomous pipeline: Diagnose -> Synthesize -> Verify...');
    setPipelineStep(2);
    setError('');
    try {
      // Step 1: Diagnose
      const diagPayload: any = {
        issue_description: issueDescription,
        test_command: testCommand ? testCommand.trim() : undefined,
        mode: requestMode !== 'auto' ? requestMode : undefined
      };
      if (workspaceId) {
        diagPayload.workspace_id = workspaceId;
      } else {
        diagPayload.repo_url = repoUrl.trim();
      }

      const diagRes = await axios.post('/api/diagnose', diagPayload);
      setDiagnosis(diagRes.data);
      const currentWsId = diagRes.data.workspace_id;
      if (currentWsId) {
        setWorkspaceId(currentWsId);
      }
      if (!testCommand && diagRes.data.profile?.detected_test_command) {
        setTestCommand(diagRes.data.profile.detected_test_command);
      }

      // If the model or classifier treated it as open-ended investigation, pause to let user choose finding
      if (diagRes.data.mode !== 'targeted' && diagRes.data.findings?.length) {
        setRightPanelView('findings');
        setPipelineStep(3);
        setRetryCount(0);
        saveSession(currentWsId, diagRes.data.diagnosis);
        return;
      }

      // Step 2: Repair & Verify
      setPipelineStep(4);
      setLoadingMessage('Applying generated patch and executing empirical test verification...');
      const repairPayload: any = {
        workspace_id: currentWsId,
        issue_description: issueDescription,
        diagnosis_context: diagRes.data.diagnosis,
        test_command: testCommand ? testCommand.trim() : undefined
      };

      setPipelineStep(5);
      const repairRes = await axios.post('/api/repair', repairPayload);
      setRepair(repairRes.data);
      setRightPanelView('patch');
      setPipelineStep(6);
      setRetryCount(0);
      saveSession(currentWsId, diagRes.data.diagnosis, repairRes.data);
      if (ghWorkspaceInfo || inputType === 'github') {
        checkPublishReadiness(currentWsId);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message);
      setPipelineStep(0);
    } finally {
      setLoading(false);
      setLoadingMessage('');
    }
  };

  const handleRetry = async () => {
    if (retryCount >= 2) return;
    setRetryCount((prev) => prev + 1);
    if (pipelineStep <= 2) {
      await handleDiagnose();
    } else {
      if (selectedFinding) {
        await handleRepairFinding(selectedFinding);
      } else {
        await handleRepair();
      }
    }
  };

  const handleRollback = async () => {
    if (!workspaceId) return;
    setLoading(true);
    setLoadingMessage('Reverting workspace to HEAD via hard reset...');
    setError('');
    try {
      await axios.post('/api/rollback', { workspace_id: workspaceId });
      setRepair(null);
      setPublishResult(null);
      setPublishReadiness(null);
      setPipelineStep(3);
      setRollbackModalOpen(false);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
      setLoadingMessage('');
    }
  };

  const resetSession = () => {
    if (workspaceId) {
      axios.delete(`/api/workspace/${workspaceId}`).catch(console.error);
    }
    setWorkspaceId(null);
    setRepoUrl('');
    setZipFile(null);
    setSelectedRepo(null);
    setGhWorkspaceInfo(null);
    setPublishReadiness(null);
    setPublishResult(null);
    setPublishError('');
    setIssueDescription('');
    setTestCommand('');
    setDiagnosis(null);
    setRepair(null);
    setPipelineStep(0);
    setError('');
  };

  const copyWorkspaceId = () => {
    if (!workspaceId) return;
    navigator.clipboard.writeText(workspaceId);
    setCopiedWsId(true);
    setTimeout(() => setCopiedWsId(false), 2000);
  };

  const downloadPatch = () => {
    if (!repair?.patch) return;
    const blob = new Blob([repair.patch], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `patch_${workspaceId?.slice(0, 8) || 'repair'}.patch`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadReport = () => {
    if (!diagnosis || !repair) return;
    const report = `# Patchworks Repair & Verification Certificate

> Official Autonomous Code-Repair Audit Report
> Target Engine: Nebius AI Cloud / Token Factory (${health?.model || 'nvidia/Nemotron-3_5-Lightning'})

---

## 1. Session Identification
- **Workspace ID:** \`${workspaceId}\`
- **Target Repository:** \`${repoUrl || (zipFile ? zipFile.name : 'Uploaded Workspace')}\`
- **Verification Status:** **\`${repair.verification_status || repair.status}\`**
- **Patch Applied:** \`${repair.patch_applied ? 'YES' : 'NO'}\`

---

## 2. Problem Specification
${issueDescription}

**Reproduction Command:** \`${testCommand || 'None provided'}\`

---

## 3. Autonomous Diagnosis
- **Root Cause:** ${diagnosis.diagnosis.diagnosis}
- **Evidence:**
\`\`\`
${diagnosis.diagnosis.evidence}
\`\`\`
- **Files Targeted:** ${diagnosis.diagnosis.files_to_modify.join(', ') || 'None identified'}
- **Regression Risks:** ${diagnosis.diagnosis.regression_risks || 'None specified'}

---

## 4. Applied Patch (Unified Diff)
\`\`\`diff
${repair.patch}
\`\`\`

---

## 5. Sandbox Verification Output
${
  repair.verification_details
    ? `
- **Exit Code:** \`${repair.verification_details.returncode}\`
- **Success:** \`${repair.verification_details.success}\`

### Stdout:
\`\`\`
${repair.verification_details.stdout}
\`\`\`

${
  repair.verification_details.stderr
    ? `### Stderr:\n\`\`\`\n${repair.verification_details.stderr}\n\`\`\``
    : ''
}
`
    : '_No test command executed._'
}

---
*Generated autonomously by Patchworks.*
`;
    const blob = new Blob([report], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `audit_report_${workspaceId?.slice(0, 8) || 'repair'}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadJson = () => {
    const data = {
      product: 'Patchworks',
      workspaceId,
      repoUrl,
      issueDescription,
      testCommand,
      diagnosis: diagnosis?.diagnosis,
      repair: repair
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `session_${workspaceId?.slice(0, 8) || 'audit'}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex h-screen bg-[#050505] text-[#F4F5F0] overflow-hidden selection:bg-[#B7FF3C] selection:text-[#050505]">
      {/* Sidebar */}
      <aside
        className={`${
          sidebarOpen ? 'w-72' : 'w-16'
        } transition-all duration-200 border-r border-[#242820] bg-[#0B0D0A] flex flex-col justify-between z-20 shrink-0`}
      >
        <div className="flex flex-col h-full overflow-hidden">
          {/* Logo Header */}
          <div className="p-4 border-b border-[#242820] flex items-center justify-between">
            {sidebarOpen ? (
              <div className="flex items-center gap-2">
                <img
                  src="/patchworks-horizontal.png"
                  alt="Patchworks"
                  className="h-7 w-auto object-contain drop-shadow-[0_0_12px_rgba(183,255,60,0.18)]"
                />
              </div>
            ) : (
              <div className="mx-auto flex items-center justify-center">
                <img
                  src="/patchworks-icon.png"
                  alt="Patchworks"
                  className="w-7 h-7 object-contain drop-shadow-[0_0_8px_rgba(183,255,60,0.25)]"
                />
              </div>
            )}
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="text-[#969B90] hover:text-[#B7FF3C] p-1 rounded hover:bg-[#11140F] transition-colors"
              title={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
            >
              {sidebarOpen ? <ChevronRight className="w-4 h-4 rotate-180" /> : <Menu className="w-4 h-4" />}
            </button>
          </div>

          {/* New Repair Action */}
          <div className="p-3">
            <button
              onClick={resetSession}
              className={`w-full flex items-center justify-center gap-2 py-2 px-3 rounded text-xs font-semibold uppercase tracking-wider transition-all ${
                sidebarOpen
                  ? 'bg-[#B7FF3C] text-[#050505] hover:bg-[#D4FF8A] glow-lime-sm'
                  : 'bg-[#B7FF3C] text-[#050505] p-2'
              }`}
              title="Start a new clean repair session"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              {sidebarOpen && <span>New Repair</span>}
            </button>
          </div>

          {/* Benchmarks Section */}
          {sidebarOpen && (
            <div className="px-3 py-2 border-t border-[#242820]">
              <span className="text-[10px] font-mono uppercase tracking-wider text-[#969B90] px-1 flex items-center gap-1.5 mb-2">
                <Layers className="w-3 h-3 text-[#B7FF3C]" />
                Benchmarks
              </span>
              <div className="space-y-1">
                <button
                  onClick={() => loadBenchmark('simple_bug')}
                  className="w-full text-left text-xs px-2.5 py-1.5 rounded bg-[#11140F] hover:bg-[#191D16] border border-[#242820] hover:border-[#B7FF3C]/50 text-[#F4F5F0] transition-colors flex items-center justify-between group"
                >
                  <span className="font-mono text-[11px] truncate">simple_bug</span>
                  <span className="text-[10px] text-[#969B90] group-hover:text-[#B7FF3C] font-mono">math</span>
                </button>
                <button
                  onClick={() => loadBenchmark('edge_case')}
                  className="w-full text-left text-xs px-2.5 py-1.5 rounded bg-[#11140F] hover:bg-[#191D16] border border-[#242820] hover:border-[#B7FF3C]/50 text-[#F4F5F0] transition-colors flex items-center justify-between group"
                >
                  <span className="font-mono text-[11px] truncate">edge_case</span>
                  <span className="text-[10px] text-[#969B90] group-hover:text-[#B7FF3C] font-mono">boundary</span>
                </button>
              </div>
            </div>
          )}

          {/* Recent Sessions */}
          {sidebarOpen && (
            <div className="flex-1 overflow-y-auto px-3 py-2 border-t border-[#242820]">
              <div className="flex items-center justify-between mb-2 px-1">
                <span className="text-[10px] font-mono uppercase tracking-wider text-[#969B90] flex items-center gap-1.5">
                  <History className="w-3 h-3 text-[#B7FF3C]" />
                  Session Audit
                </span>
                {recentSessions.length > 0 && (
                  <button
                    onClick={clearSessions}
                    className="text-[10px] text-[#969B90] hover:text-[#FF5C68] transition-colors"
                    title={user ? "Clear sessions from database and view" : "Clear local sessions"}
                  >
                    Clear
                  </button>
                )}
              </div>

              {recentSessions.length === 0 ? (
                <p className="text-[11px] text-[#969B90]/60 italic px-1 py-2">No recent sessions.</p>
              ) : (
                <div className="space-y-1.5">
                  {recentSessions.map((s) => (
                    <div
                      key={s.id}
                      onClick={() => {
                        setWorkspaceId(s.workspaceId);
                        if (s.diagnosis) setDiagnosis({ status: 'success', workspace_id: s.workspaceId, diagnosis: s.diagnosis });
                        if (s.repair) setRepair(s.repair);
                      }}
                      className="p-2 rounded bg-[#11140F] border border-[#242820] hover:border-[#B7FF3C]/40 cursor-pointer transition-colors group"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-mono text-[10px] text-[#B7FF3C]">{s.workspaceId.slice(0, 8)}</span>
                        <div className="flex items-center gap-1.5">
                          <span className="text-[9px] text-[#969B90]">{s.timestamp}</span>
                          <button
                            onClick={(e) => deleteSession(s.id, e)}
                            className="text-[#969B90] hover:text-[#FF5C68] p-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity"
                            title="Delete session"
                          >
                            <X className="w-2.5 h-2.5" />
                          </button>
                        </div>
                      </div>
                      <p className="text-[11px] text-[#F4F5F0] truncate">{s.issueDescription}</p>
                      <div className="mt-1 flex items-center justify-between">
                        <span
                          className={`text-[9px] font-mono px-1 rounded ${
                            s.verificationStatus === 'FIX VERIFIED'
                              ? 'bg-[#B7FF3C]/20 text-[#B7FF3C]'
                              : s.verificationStatus === 'FIX FAILED'
                              ? 'bg-[#FF5C68]/20 text-[#FF5C68]'
                              : 'bg-[#242820] text-[#969B90]'
                          }`}
                        >
                          {s.verificationStatus}
                        </span>
                        {s.prUrl && (
                          <a
                            href={s.prUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="text-[9px] font-mono text-[#B7FF3C] hover:underline flex items-center gap-0.5"
                            title={s.prUrl}
                          >
                            <GitPullRequest className="w-2.5 h-2.5" />
                            <span>PR #{s.prNumber || ''}</span>
                          </a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Model Status & Settings */}
          <div className="p-3 border-t border-[#242820] bg-[#080A07]">
            {sidebarOpen ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs font-mono">
                  <span className="text-[#969B90] flex items-center gap-1.5">
                    <Cpu className="w-3.5 h-3.5 text-[#B7FF3C]" />
                    Engine
                  </span>
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded font-mono font-bold ${
                      health?.nebius_configured
                        ? 'bg-[#B7FF3C]/10 text-[#B7FF3C] border border-[#B7FF3C]/30'
                        : 'bg-[#F4BF50]/10 text-[#F4BF50] border border-[#F4BF50]/30'
                    }`}
                  >
                    {health?.nebius_configured ? 'NEBIUS LIVE' : 'MOCK MODE'}
                  </span>
                </div>
                <div className="text-[10px] text-[#969B90] font-mono truncate">
                  {health?.model || 'nvidia/Nemotron-3_5-Lightning'}
                </div>
                <button
                  onClick={() => setSettingsOpen(true)}
                  className="w-full flex items-center justify-center gap-1.5 py-1 px-2 rounded bg-[#11140F] hover:bg-[#191D16] border border-[#242820] text-[11px] text-[#969B90] hover:text-[#F4F5F0] transition-colors"
                >
                  <Sliders className="w-3 h-3" />
                  Engine Settings
                </button>
              </div>
            ) : (
              <button
                onClick={() => setSettingsOpen(true)}
                className="w-full flex justify-center text-[#969B90] hover:text-[#B7FF3C] py-2"
                title="Settings"
              >
                <Sliders className="w-4 h-4" />
              </button>
            )}
          </div>
        </div>
      </aside>

      {/* Main Workbench Area */}
      <main className="flex-1 flex flex-col min-w-0 bg-[#050505] overflow-y-auto">
        {/* Top Header */}
        <header className="h-14 border-b border-[#242820] bg-[#0B0D0A] px-6 flex items-center justify-between shrink-0 sticky top-0 z-10">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs uppercase text-[#969B90]">Workbench</span>
              <span className="text-[#242820]">/</span>
              {workspaceId ? (
                <div className="flex items-center gap-1.5 bg-[#11140F] px-2 py-0.5 rounded border border-[#242820]">
                  <span className="font-mono text-xs text-[#B7FF3C]">{workspaceId}</span>
                  <button onClick={copyWorkspaceId} className="text-[#969B90] hover:text-[#F4F5F0]" title="Copy Workspace ID">
                    {copiedWsId ? <Check className="w-3 h-3 text-[#B7FF3C]" /> : <Copy className="w-3 h-3" />}
                  </button>
                </div>
              ) : (
                <span className="font-mono text-xs text-[#969B90]">Ready</span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Supabase User Account Section */}
            {isSupabaseConfigured && (
              user ? (
                <div className="flex items-center gap-2 bg-[#11140F] border border-[#242820] hover:border-[#B7FF3C]/50 px-2.5 py-1 rounded text-xs font-mono transition-colors">
                  {user.avatar_url ? (
                    <img
                      src={user.avatar_url}
                      alt=""
                      className="w-4 h-4 rounded-full border border-[#242820]"
                    />
                  ) : (
                    <User className="w-3.5 h-3.5 text-[#B7FF3C]" />
                  )}
                  <span className="text-[#F4F5F0] max-w-[120px] truncate" title={user.email || 'Authenticated User'}>
                    {user.email ? user.email.split('@')[0] : 'User'}
                  </span>
                  <button
                    onClick={handleSignOut}
                    className="text-[#969B90] hover:text-[#FF5C68] ml-1 p-0.5 rounded transition-colors"
                    title="Sign Out"
                  >
                    <LogOut className="w-3 h-3" />
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setAuthModalOpen(true)}
                  className="flex items-center gap-1.5 bg-[#11140F] hover:bg-[#191D16] border border-[#242820] hover:border-[#B7FF3C] text-xs font-mono text-[#F4F5F0] hover:text-[#B7FF3C] px-3 py-1 rounded transition-colors"
                  title="Sign in with your Patchworks account to persist connections and history"
                >
                  <LogIn className="w-3.5 h-3.5 text-[#B7FF3C]" />
                  <span>Sign In</span>
                </button>
              )
            )}

            {/* GitHub Account Badge / Button */}
            {ghStatus.connected && ghStatus.user ? (
              <div className="flex items-center gap-2 bg-[#11140F] border border-[#242820] hover:border-[#B7FF3C]/50 px-2.5 py-1 rounded text-xs font-mono transition-colors">
                <Github className="w-3.5 h-3.5 text-[#B7FF3C]" />
                {ghStatus.user.avatar_url && (
                  <img
                    src={ghStatus.user.avatar_url}
                    alt=""
                    className="w-4 h-4 rounded-full border border-[#242820]"
                  />
                )}
                <span className="text-[#F4F5F0]">@{ghStatus.user.login}</span>
                <button
                  onClick={handleGitHubDisconnect}
                  className="text-[#969B90] hover:text-[#FF5C68] ml-1 p-0.5 rounded"
                  title="Disconnect GitHub account"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ) : (
              <button
                onClick={() => setGhConnectModalOpen(true)}
                className="flex items-center gap-1.5 bg-[#11140F] hover:bg-[#191D16] border border-[#242820] hover:border-[#B7FF3C] text-xs font-mono text-[#F4F5F0] hover:text-[#B7FF3C] px-3 py-1 rounded transition-colors"
                title="Connect your GitHub account for repository cloning and pull request creation"
              >
                <Github className="w-3.5 h-3.5 text-[#B7FF3C]" />
                <span>Connect GitHub</span>
              </button>
            )}

            {health && !health.nebius_configured && (
              <div className="flex items-center gap-1.5 bg-[#F4BF50]/10 border border-[#F4BF50]/30 text-[#F4BF50] px-2.5 py-1 rounded text-[11px] font-mono">
                <AlertTriangle className="w-3.5 h-3.5" />
                <span>DEMO / MOCK MODE</span>
              </div>
            )}
            {health?.nebius_configured && (
              <div className="flex items-center gap-1.5 bg-[#B7FF3C]/10 border border-[#B7FF3C]/30 text-[#B7FF3C] px-2.5 py-1 rounded text-[11px] font-mono">
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>NEBIUS INFERENCE ACTIVE</span>
              </div>
            )}
            <button
              onClick={resetSession}
              className="flex items-center gap-1 text-xs text-[#969B90] hover:text-[#F4F5F0] bg-[#11140F] hover:bg-[#191D16] border border-[#242820] px-3 py-1.5 rounded transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Reset</span>
            </button>
          </div>
        </header>

        {/* Global Error Banner */}
        {error && (
          <div className="m-6 mb-0 bg-[#FF5C68]/10 border border-[#FF5C68]/40 text-[#FF5C68] p-3.5 rounded flex items-center justify-between text-xs font-mono">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
            <div className="flex items-center gap-2">
              {retryCount < 2 && (
                <button
                  onClick={handleRetry}
                  disabled={loading}
                  className="px-2.5 py-1 bg-[#11140F] hover:bg-[#191D16] border border-[#FF5C68] text-[#FF5C68] hover:text-white text-[11px] font-mono rounded flex items-center gap-1 transition-colors"
                >
                  <RefreshCw className="w-3 h-3" />
                  <span>Retry ({2 - retryCount} left)</span>
                </button>
              )}
              <button onClick={() => setError('')} className="text-[#FF5C68] hover:text-white p-1">
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* Content Body */}
        <div className="p-6 space-y-6 flex-1">
          {/* Repair Pipeline Stepper */}
          <div className="bg-[#0B0D0A] border border-[#242820] p-4 rounded-lg">
            <div className="flex items-center justify-between text-xs font-mono mb-3">
              <span className="text-[#969B90] uppercase tracking-wider text-[10px] flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5 text-[#B7FF3C]" />
                Verifiable Repair Lifecycle
              </span>
              <span className="text-[11px] text-[#B7FF3C]">
                {pipelineStep === 0 && 'Ready'}
                {pipelineStep === 1 && 'Repository Ingested'}
                {pipelineStep === 2 && 'Diagnosing / Investigating...'}
                {pipelineStep === 3 && (diagnosis?.findings?.length ? 'Findings Ready' : 'Diagnosis Ready')}
                {pipelineStep === 4 && 'Synthesizing Patch...'}
                {pipelineStep === 5 && 'Verifying in Sandbox...'}
                {pipelineStep === 6 && (repair?.verification_status || 'Complete')}
              </span>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-6 gap-2">
              {[
                { num: 1, label: 'Preparation', done: pipelineStep >= 1, active: pipelineStep === 1 },
                { num: 2, label: 'Reproduction', done: pipelineStep >= 2, active: pipelineStep === 2 },
                {
                  num: 3,
                  label:
                    diagnosis?.mode === 'improvement'
                      ? 'Recommendations'
                      : diagnosis?.mode === 'bug_discovery'
                      ? 'Findings Audit'
                      : 'Diagnosis',
                  done: pipelineStep >= 3,
                  active: pipelineStep === 3
                },
                { num: 4, label: 'Synthesis', done: pipelineStep >= 4, active: pipelineStep === 4 },
                { num: 5, label: 'Sandbox Apply', done: pipelineStep >= 5, active: pipelineStep === 5 },
                { num: 6, label: 'Certification', done: pipelineStep >= 6, active: pipelineStep === 6 }
              ].map((step) => (
                <div
                  key={step.num}
                  className={`p-2 rounded border text-center transition-all ${
                    step.active
                      ? 'border-[#B7FF3C] bg-[#11140F] glow-lime-sm'
                      : step.done
                      ? 'border-[#B7FF3C]/40 bg-[#0E120B]'
                      : 'border-[#242820] bg-[#070806] opacity-40'
                  }`}
                >
                  <div
                    className={`text-[10px] font-mono uppercase mb-0.5 ${
                      step.active ? 'text-[#B7FF3C] font-bold' : step.done ? 'text-[#B7FF3C]/80' : 'text-[#969B90]'
                    }`}
                  >
                    Stage 0{step.num}
                  </div>
                  <div className="text-xs font-medium text-[#F4F5F0] truncate">{step.label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Workbench Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left Column: Ingestion & Problem Specification */}
            <div className="lg:col-span-5 space-y-6">
              <div className="bg-[#0B0D0A] border border-[#242820] p-5 rounded-lg space-y-4">
                <div className="flex items-center justify-between border-b border-[#242820] pb-3">
                  <h2 className="text-sm font-semibold uppercase tracking-wider text-[#F4F5F0] flex items-center gap-2">
                    <Folder className="w-4 h-4 text-[#B7FF3C]" />
                    Project Ingestion
                  </h2>
                  <div className="flex bg-[#11140F] p-0.5 rounded border border-[#242820]">
                    {(['github', 'git', 'zip', 'benchmark'] as const).map((type) => (
                      <button
                        key={type}
                        onClick={() => setInputType(type)}
                        disabled={!!workspaceId}
                        className={`px-2.5 py-1 text-xs rounded transition-colors uppercase font-mono ${
                          inputType === type
                            ? 'bg-[#B7FF3C] text-[#050505] font-bold'
                            : 'text-[#969B90] hover:text-[#F4F5F0]'
                        } disabled:opacity-50`}
                      >
                        {type}
                      </button>
                    ))}
                  </div>
                </div>

                {/* GitHub Ingestion Form */}
                {inputType === 'github' && (
                  <div>
                    {!ghStatus.connected ? (
                      <div className="p-4 bg-[#11140F] rounded border border-[#242820] text-center space-y-3">
                        <Github className="w-8 h-8 text-[#B7FF3C] mx-auto opacity-90" />
                        <div className="space-y-1">
                          <h3 className="text-xs font-mono font-bold text-[#F4F5F0] uppercase tracking-wider">
                            GitHub Not Connected
                          </h3>
                          <p className="text-[11px] text-[#969B90] leading-relaxed max-w-xs mx-auto">
                            Connect your GitHub account to browse accessible repositories, clone into an isolated sandbox, and publish verified pull requests.
                          </p>
                        </div>
                        <button
                          onClick={() => setGhConnectModalOpen(true)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#B7FF3C] hover:bg-[#D4FF8A] text-[#050505] text-xs font-mono font-bold transition-colors glow-lime-sm"
                        >
                          <Key className="w-3.5 h-3.5" />
                          <span>Connect Account</span>
                        </button>
                      </div>
                    ) : ghWorkspaceInfo ? (
                      <div className="p-3 bg-[#11140F] rounded border border-[#B7FF3C]/30 space-y-2">
                        <div className="flex items-center justify-between text-xs font-mono">
                          <span className="text-[#B7FF3C] font-bold flex items-center gap-1.5">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            Workspace Isolated
                          </span>
                          <span className="text-[10px] text-[#969B90]">{ghWorkspaceInfo.commitSha.slice(0, 8)}</span>
                        </div>
                        <div className="text-xs font-mono text-[#F4F5F0] space-y-1">
                          <div className="flex justify-between">
                            <span className="text-[#969B90]">Repository:</span>
                            <span className="text-[#F4F5F0]">
                              {ghWorkspaceInfo.owner}/{ghWorkspaceInfo.repo}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-[#969B90]">Target Branch:</span>
                            <span className="text-[#B7FF3C]">{ghWorkspaceInfo.branch}</span>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-3">
                        <div>
                          <label className="block text-xs font-mono uppercase text-[#969B90] mb-1.5 flex items-center justify-between">
                            <span>Target Repository</span>
                            <button
                              onClick={() => fetchGitHubRepos(ghSearchQuery)}
                              disabled={ghReposLoading}
                              className="text-[10px] text-[#B7FF3C] hover:underline flex items-center gap-1"
                            >
                              <RefreshCw className={`w-2.5 h-2.5 ${ghReposLoading ? 'animate-spin' : ''}`} />
                              <span>Refresh</span>
                            </button>
                          </label>
                          <div className="relative mb-2">
                            <input
                              type="text"
                              value={ghSearchQuery}
                              onChange={(e) => {
                                setGhSearchQuery(e.target.value);
                                fetchGitHubRepos(e.target.value);
                              }}
                              placeholder="Search repositories..."
                              className="w-full bg-[#11140F] border border-[#242820] rounded p-2 pl-7 text-xs text-[#F4F5F0] font-mono focus:border-[#B7FF3C] outline-none"
                            />
                            <Search className="w-3.5 h-3.5 text-[#969B90] absolute left-2 top-2.5" />
                          </div>

                          <div className="max-h-36 overflow-y-auto space-y-1 bg-[#080A07] p-1.5 rounded border border-[#242820]">
                            {ghReposLoading && ghRepos.length === 0 ? (
                              <div className="text-center py-4 text-xs font-mono text-[#969B90]">
                                Loading repositories...
                              </div>
                            ) : ghRepos.length === 0 ? (
                              <div className="text-center py-4 text-xs font-mono text-[#969B90]">
                                No repositories found
                              </div>
                            ) : (
                              ghRepos.map((r) => (
                                <div
                                  key={r.id}
                                  onClick={() => handleSelectRepo(r)}
                                  className={`p-2 rounded cursor-pointer transition-colors flex items-center justify-between text-xs font-mono ${
                                    selectedRepo?.id === r.id
                                      ? 'bg-[#191D16] border border-[#B7FF3C] text-[#B7FF3C]'
                                      : 'hover:bg-[#11140F] text-[#F4F5F0]'
                                  }`}
                                >
                                  <div className="flex items-center gap-1.5 truncate">
                                    {r.private ? (
                                      <Lock className="w-3 h-3 text-[#F4BF50] shrink-0" />
                                    ) : (
                                      <Github className="w-3 h-3 text-[#969B90] shrink-0" />
                                    )}
                                    <span className="truncate">{r.full_name}</span>
                                  </div>
                                  <span className="text-[10px] text-[#969B90] shrink-0 ml-2">
                                    {r.default_branch}
                                  </span>
                                </div>
                              ))
                            )}
                          </div>
                        </div>

                        {selectedRepo && (
                          <div className="p-3 bg-[#11140F] rounded border border-[#242820] space-y-2.5">
                            <div className="flex items-center justify-between text-xs font-mono">
                              <span className="text-[#969B90] uppercase flex items-center gap-1">
                                <GitBranch className="w-3.5 h-3.5 text-[#B7FF3C]" />
                                Target Branch
                              </span>
                              <span className="text-[#B7FF3C] truncate">{selectedRepo.full_name}</span>
                            </div>

                            <div className="flex items-center gap-2">
                              <select
                                value={selectedBranch}
                                onChange={(e) => setSelectedBranch(e.target.value)}
                                disabled={ghBranchesLoading}
                                className="flex-1 bg-[#050505] border border-[#242820] rounded p-1.5 text-xs text-[#F4F5F0] font-mono focus:border-[#B7FF3C] outline-none"
                              >
                                {ghBranches.length > 0 ? (
                                  ghBranches.map((b) => (
                                    <option key={b.name} value={b.name}>
                                      {b.name}
                                    </option>
                                  ))
                                ) : (
                                  <option value={selectedRepo.default_branch || 'main'}>
                                    {selectedRepo.default_branch || 'main'}
                                  </option>
                                )}
                              </select>

                              <button
                                onClick={handleCloneGitHubRepo}
                                disabled={loading}
                                className="px-3 py-1.5 rounded bg-[#B7FF3C] hover:bg-[#D4FF8A] text-[#050505] text-xs font-mono font-bold transition-all flex items-center gap-1.5 glow-lime-sm disabled:opacity-50"
                              >
                                <Download className="w-3.5 h-3.5" />
                                <span>Fetch Repo</span>
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Input Ingestion Form */}
                {inputType === 'git' && (
                  <div>
                    <label className="block text-xs font-mono uppercase text-[#969B90] mb-1.5">
                      Git Repository URL (Remote or Local `file://`)
                    </label>
                    <input
                      type="text"
                      value={repoUrl}
                      onChange={(e) => setRepoUrl(e.target.value)}
                      disabled={!!workspaceId || loading}
                      placeholder="https://github.com/org/repo.git or file:///path/to/repo"
                      className="w-full bg-[#11140F] border border-[#242820] rounded p-2.5 text-xs text-[#F4F5F0] font-mono focus:border-[#B7FF3C] focus:ring-1 focus:ring-[#B7FF3C] outline-none disabled:opacity-50 transition-colors"
                    />
                  </div>
                )}

                {inputType === 'zip' && (
                  <div>
                    <label className="block text-xs font-mono uppercase text-[#969B90] mb-1.5">
                      Upload ZIP Archive (ZipSlip protected, max 50MB)
                    </label>
                    <div className="flex items-center gap-3">
                      <label className="flex items-center gap-2 bg-[#11140F] hover:bg-[#191D16] border border-[#242820] hover:border-[#B7FF3C] cursor-pointer px-4 py-2 rounded text-xs transition-colors">
                        <Upload className="w-4 h-4 text-[#B7FF3C]" />
                        <span>Choose Archive</span>
                        <input
                          type="file"
                          accept=".zip"
                          className="hidden"
                          onChange={handleZipUpload}
                          disabled={!!workspaceId || loading}
                        />
                      </label>
                      {zipFile && (
                        <span className="text-xs text-[#B7FF3C] font-mono flex items-center gap-1">
                          <CheckCircle2 className="w-3.5 h-3.5" /> {zipFile.name}
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {inputType === 'benchmark' && (
                  <div>
                    <label className="block text-xs font-mono uppercase text-[#969B90] mb-1.5">
                      Deterministic Hackathon Fixtures
                    </label>
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        onClick={() => loadBenchmark('simple_bug')}
                        disabled={loading}
                        className="p-2.5 rounded bg-[#11140F] hover:bg-[#191D16] border border-[#242820] hover:border-[#B7FF3C] text-left transition-colors disabled:opacity-50"
                      >
                        <div className="font-mono text-xs text-[#B7FF3C] font-semibold">simple_bug</div>
                        <div className="text-[10px] text-[#969B90] mt-0.5">math_utils logic error</div>
                      </button>
                      <button
                        onClick={() => loadBenchmark('edge_case')}
                        disabled={loading}
                        className="p-2.5 rounded bg-[#11140F] hover:bg-[#191D16] border border-[#242820] hover:border-[#B7FF3C] text-left transition-colors disabled:opacity-50"
                      >
                        <div className="font-mono text-xs text-[#B7FF3C] font-semibold">edge_case</div>
                        <div className="text-[10px] text-[#969B90] mt-0.5">text_utils boundary bug</div>
                      </button>
                    </div>
                  </div>
                )}

                {/* Workflow Intent Mode Selector */}
                <div className="space-y-1.5">
                  <label className="block text-xs font-mono uppercase text-[#969B90]">
                    Workflow Intent Mode
                  </label>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5">
                    {[
                      { id: 'auto', label: 'Auto Detect', desc: 'Classify intent' },
                      { id: 'targeted', label: 'Targeted Repair', desc: 'Fix specific bug' },
                      { id: 'bug_discovery', label: 'Find Bugs', desc: 'Audit for flaws' },
                      { id: 'improvement', label: 'Review & Improve', desc: 'Recommendations' }
                    ].map((m) => (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => setRequestMode(m.id as any)}
                        disabled={loading}
                        className={`p-2 rounded border text-left transition-all ${
                          requestMode === m.id
                            ? 'border-[#B7FF3C] bg-[#11140F] text-[#B7FF3C] glow-lime-sm'
                            : 'border-[#242820] bg-[#070806] text-[#969B90] hover:border-[#3A4034]'
                        }`}
                      >
                        <div className="text-xs font-mono font-semibold truncate">{m.label}</div>
                        <div className="text-[10px] text-[#969B90] truncate">{m.desc}</div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Defect or Goal Description */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs font-mono uppercase text-[#969B90]">
                      {requestMode === 'improvement'
                        ? 'Improvement Goals / Review Focus'
                        : requestMode === 'bug_discovery'
                        ? 'Audit Scope / Discovery Request'
                        : 'Defect Description / Stack Trace'}
                    </label>
                    <span className="text-[10px] text-[#969B90] font-mono">{issueDescription.length} chars</span>
                  </div>
                  <textarea
                    value={issueDescription}
                    onChange={(e) => setIssueDescription(e.target.value)}
                    disabled={loading}
                    rows={4}
                    placeholder={
                      requestMode === 'improvement'
                        ? "E.g., Gimme some ways to improve it, optimize performance, refactor modules..."
                        : requestMode === 'bug_discovery'
                        ? "E.g., Audit this repository for correctness flaws, security issues, crash risks..."
                        : requestMode === 'targeted'
                        ? "Describe the failing test, incorrect calculation, or paste exception traces..."
                        : "Describe the issue or goal (e.g., 'gimme some ways to improve it' or 'fix test_subtract in math_utils.py')..."
                    }
                    className="w-full bg-[#11140F] border border-[#242820] rounded p-2.5 text-xs text-[#F4F5F0] font-mono focus:border-[#B7FF3C] focus:ring-1 focus:ring-[#B7FF3C] outline-none transition-colors"
                  />
                </div>

                {/* Test Command */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs font-mono uppercase text-[#969B90]">
                      Verification Test Command
                    </label>
                    {diagnosis?.profile?.detected_test_command && (
                      <span className="text-[10px] text-[#B7FF3C] font-mono">
                        Detected: {diagnosis.profile.detected_test_command}
                      </span>
                    )}
                  </div>
                  <input
                    type="text"
                    value={testCommand}
                    onChange={(e) => setTestCommand(e.target.value)}
                    disabled={loading}
                    placeholder="pytest test_math_utils.py or npm test"
                    className="w-full bg-[#11140F] border border-[#242820] rounded p-2.5 text-xs text-[#F4F5F0] font-mono focus:border-[#B7FF3C] focus:ring-1 focus:ring-[#B7FF3C] outline-none transition-colors"
                  />
                  <span className="text-[10px] text-[#969B90] font-mono mt-1 block">
                    Allowed base binaries: pytest, python, python3, npm, node, cargo, go (subprocess isolated)
                  </span>
                </div>

                {/* Execution Buttons */}
                <div className="pt-2 space-y-2">
                  <button
                    onClick={handleFullPipeline}
                    disabled={loading || (!repoUrl && !workspaceId && !zipFile) || !issueDescription.trim()}
                    className="w-full py-2.5 px-4 rounded bg-[#B7FF3C] hover:bg-[#D4FF8A] disabled:bg-[#242820] disabled:text-[#969B90] text-[#050505] font-semibold text-xs uppercase tracking-wider transition-all flex items-center justify-center gap-2 glow-lime-sm"
                  >
                    {loading ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin text-[#050505]" />
                        <span>{loadingMessage || 'Processing...'}</span>
                      </>
                    ) : (
                      <>
                        <Sparkles className="w-4 h-4" />
                        <span>
                          {requestMode === 'improvement'
                            ? 'Review & Improve Repository'
                            : requestMode === 'bug_discovery'
                            ? 'Audit & Discover Bugs'
                            : 'Execute Autonomous Repair'}
                        </span>
                      </>
                    )}
                  </button>

                  <div className="grid grid-cols-2 gap-2 pt-1">
                    <button
                      onClick={handleDiagnose}
                      disabled={loading || (!repoUrl && !workspaceId && !zipFile) || !issueDescription.trim()}
                      className="py-2 px-3 rounded bg-[#11140F] hover:bg-[#191D16] border border-[#242820] hover:border-[#B7FF3C] disabled:opacity-40 text-xs font-mono text-[#F4F5F0] transition-colors"
                    >
                      {requestMode === 'improvement' || requestMode === 'bug_discovery'
                        ? '1. Investigate Only'
                        : '1. Diagnose Only'}
                    </button>
                    <button
                      onClick={handleRepair}
                      disabled={loading || !diagnosis}
                      className="py-2 px-3 rounded bg-[#11140F] hover:bg-[#191D16] border border-[#242820] hover:border-[#B7FF3C] disabled:opacity-40 text-xs font-mono text-[#B7FF3C] transition-colors"
                    >
                      2. Synthesize & Apply
                    </button>
                  </div>
                </div>
              </div>

              {/* Diagnosis Output Card */}
              {diagnosis && (
                <div className="bg-[#0B0D0A] border border-[#242820] p-5 rounded-lg space-y-3.5">
                  <div className="flex items-center justify-between border-b border-[#242820] pb-2.5">
                    <h3 className="text-xs font-mono uppercase tracking-wider text-[#B7FF3C] flex items-center gap-2">
                      {diagnosis.findings && diagnosis.findings.length > 0 ? (
                        <>
                          <Sparkles className="w-3.5 h-3.5" />
                          Repository Findings ({diagnosis.findings.length})
                        </>
                      ) : (
                        <>
                          <Bug className="w-3.5 h-3.5" />
                          Defect Diagnosis
                        </>
                      )}
                    </h3>
                    <span className="text-[10px] text-[#969B90] font-mono">
                      {diagnosis.findings && diagnosis.findings.length > 0
                        ? `${diagnosis.findings.length} Item(s)`
                        : `${diagnosis.diagnosis.files_to_modify.length} Target File(s)`}
                    </span>
                  </div>

                  <div>
                    <span className="text-[10px] font-mono uppercase text-[#969B90] block mb-1">
                      {diagnosis.findings && diagnosis.findings.length > 0 ? 'Executive Summary' : 'Root Cause'}
                    </span>
                    <p className="text-xs text-[#F4F5F0] leading-relaxed bg-[#11140F] p-2.5 rounded border border-[#242820]">
                      {diagnosis.investigation?.summary || diagnosis.diagnosis.diagnosis}
                    </p>
                  </div>

                  {diagnosis.diagnosis.evidence && (
                    <div>
                      <span className="text-[10px] font-mono uppercase text-[#969B90] block mb-1">Code Evidence</span>
                      <pre className="text-[11px] font-mono bg-[#050505] p-2.5 rounded border border-[#242820] text-[#D4FF8A] overflow-x-auto">
                        {diagnosis.diagnosis.evidence}
                      </pre>
                    </div>
                  )}

                  {diagnosis.diagnosis.files_to_modify.length > 0 && (
                    <div>
                      <span className="text-[10px] font-mono uppercase text-[#969B90] block mb-1">Target Files</span>
                      <div className="flex flex-wrap gap-1.5">
                        {diagnosis.diagnosis.files_to_modify.map((f, i) => (
                          <span
                            key={i}
                            className="bg-[#11140F] text-[#B7FF3C] text-[11px] font-mono px-2 py-0.5 rounded border border-[#242820]"
                          >
                            {f}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {diagnosis.diagnosis.regression_risks && (
                    <div className="bg-[#F4BF50]/10 border border-[#F4BF50]/30 p-2.5 rounded text-xs text-[#F4BF50] space-y-1">
                      <span className="text-[10px] font-mono uppercase font-bold flex items-center gap-1">
                        <AlertTriangle className="w-3 h-3" /> Regression Risk Evaluation
                      </span>
                      <p className="text-[11px] leading-relaxed">{diagnosis.diagnosis.regression_risks}</p>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Right Column: Unified Diff Viewer, Structured Findings & Sandbox Verification */}
            <div className="lg:col-span-7 space-y-6">
              {/* Tab Selector if both findings and repair exist */}
              {repair && diagnosis?.findings && diagnosis.findings.length > 0 && (
                <div className="flex items-center gap-2 bg-[#0B0D0A] p-1.5 rounded-lg border border-[#242820]">
                  <button
                    onClick={() => setRightPanelView('findings')}
                    className={`flex-1 py-1.5 px-3 rounded text-xs font-mono font-semibold transition-all ${
                      rightPanelView === 'findings'
                        ? 'bg-[#B7FF3C] text-[#050505] glow-lime-sm'
                        : 'text-[#969B90] hover:text-[#F4F5F0]'
                    }`}
                  >
                    Audited Findings ({diagnosis.findings.length})
                  </button>
                  <button
                    onClick={() => setRightPanelView('patch')}
                    className={`flex-1 py-1.5 px-3 rounded text-xs font-mono font-semibold transition-all ${
                      rightPanelView === 'patch'
                        ? 'bg-[#B7FF3C] text-[#050505] glow-lime-sm'
                        : 'text-[#969B90] hover:text-[#F4F5F0]'
                    }`}
                  >
                    Generated Patch & Verification
                  </button>
                </div>
              )}

              {repair && (!diagnosis?.findings?.length || rightPanelView === 'patch') ? (
                <div className="bg-[#0B0D0A] border border-[#242820] rounded-lg overflow-hidden flex flex-col h-full space-y-0">
                  {/* Diff Viewer Header */}
                  <div className="p-4 border-b border-[#242820] flex items-center justify-between bg-[#080A07]">
                    <div className="flex items-center gap-3">
                      <FileCode className="w-4 h-4 text-[#B7FF3C]" />
                      <div>
                        <h3 className="text-xs font-mono uppercase tracking-wider text-[#F4F5F0]">
                          Proposed Unified Diff Patch
                        </h3>
                        <span className="text-[10px] text-[#969B90] font-mono">
                          {repair.patch_applied ? 'Applied to Workspace' : 'Not Applied'}
                        </span>
                      </div>
                    </div>

                    {/* Verification Status Badge */}
                    <div
                      className={`px-3 py-1 rounded text-xs font-mono font-bold flex items-center gap-1.5 border ${
                        repair.verification_status === 'FIX VERIFIED'
                          ? 'bg-[#B7FF3C]/10 text-[#B7FF3C] border-[#B7FF3C]'
                          : repair.verification_status === 'FIX FAILED' ||
                            repair.verification_status === 'APPLY FAILED'
                          ? 'bg-[#FF5C68]/10 text-[#FF5C68] border-[#FF5C68]'
                          : repair.verification_status === 'VERIFICATION INCOMPLETE'
                          ? 'bg-[#F4BF50]/10 text-[#F4BF50] border-[#F4BF50]'
                          : 'bg-[#242820] text-[#969B90] border-[#3A4034]'
                      }`}
                    >
                      {repair.verification_status === 'FIX VERIFIED' ? (
                        <CheckCircle2 className="w-3.5 h-3.5" />
                      ) : repair.verification_status === 'FIX FAILED' ||
                        repair.verification_status === 'APPLY FAILED' ? (
                        <XCircle className="w-3.5 h-3.5" />
                      ) : (
                        <AlertTriangle className="w-3.5 h-3.5" />
                      )}
                      <span>{repair.verification_status || 'UNVERIFIED'}</span>
                    </div>
                  </div>

                  {/* Patch Body */}
                  <div className="bg-[#050505] p-4 overflow-x-auto font-mono text-xs max-h-80 border-b border-[#242820]">
                    {repair.patch ? (
                      repair.patch.split('\n').map((line, idx) => {
                        const isAdd = line.startsWith('+') && !line.startsWith('+++');
                        const isDel = line.startsWith('-') && !line.startsWith('---');
                        const isHeader = line.startsWith('@@') || line.startsWith('---') || line.startsWith('+++');
                        return (
                          <div
                            key={idx}
                            className={`px-2 py-0.5 leading-relaxed ${
                              isAdd
                                ? 'diff-add font-medium'
                                : isDel
                                ? 'diff-del font-medium'
                                : isHeader
                                ? 'text-[#969B90] bg-[#11140F]/50'
                                : 'text-[#F4F5F0]/80'
                            }`}
                          >
                            <span className="inline-block w-8 text-[#969B90]/40 select-none text-[10px]">
                              {idx + 1}
                            </span>
                            {line}
                          </div>
                        );
                      })
                    ) : (
                      <p className="text-[#969B90] italic p-4">No patch generated.</p>
                    )}
                  </div>

                  {/* Sandbox Verification Output */}
                  {repair.verification_details && (
                    <div className="p-4 border-b border-[#242820] space-y-2 bg-[#080A07]">
                      <div className="flex items-center justify-between text-xs font-mono">
                        <span className="text-[#969B90] uppercase flex items-center gap-1.5">
                          <Terminal className="w-3.5 h-3.5 text-[#B7FF3C]" />
                          Sandbox Test Execution Output
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            repair.verification_details.returncode === 0
                              ? 'bg-[#B7FF3C]/10 text-[#B7FF3C] border border-[#B7FF3C]/30'
                              : 'bg-[#FF5C68]/10 text-[#FF5C68] border border-[#FF5C68]/30'
                          }`}
                        >
                          Exit Code: {repair.verification_details.returncode}
                        </span>
                      </div>
                      <pre className="bg-[#050505] p-3 rounded border border-[#242820] text-[11px] font-mono text-[#F4F5F0]/90 max-h-48 overflow-y-auto leading-relaxed">
                        {repair.verification_details.stdout}
                        {repair.verification_details.stderr && (
                          <span className="text-[#FF5C68] block mt-2">
                            {repair.verification_details.stderr}
                          </span>
                        )}
                      </pre>
                    </div>
                  )}

                  {/* GitHub Pull Request Publication Section */}
                  <div className="p-4 border-b border-[#242820] space-y-3 bg-[#0B0D0A]">
                    <div className="flex items-center justify-between text-xs font-mono">
                      <span className="text-[#F4F5F0] font-bold uppercase tracking-wider flex items-center gap-1.5">
                        <GitPullRequest className="w-4 h-4 text-[#B7FF3C]" />
                        GitHub Pull Request Automation
                      </span>
                      {ghWorkspaceInfo && (
                        <span className="text-[10px] text-[#969B90]">
                          Target: {ghWorkspaceInfo.owner}/{ghWorkspaceInfo.repo} ({ghWorkspaceInfo.branch})
                        </span>
                      )}
                    </div>

                    {/* PR Result: If already published */}
                    {publishResult ? (
                      <div className="p-3.5 bg-[#B7FF3C]/10 border border-[#B7FF3C] rounded space-y-2.5">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-mono font-bold text-[#B7FF3C] flex items-center gap-1.5">
                            <CheckCircle2 className="w-4 h-4" />
                            Pull Request Opened Successfully
                          </span>
                          <span className="text-[10px] font-mono text-[#969B90]">
                            Commit: {publishResult.commit_sha.slice(0, 8)}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-xs font-mono">
                          <span className="text-[#F4F5F0]">
                            Branch: <code className="text-[#B7FF3C]">{publishResult.branch}</code>
                          </span>
                          <a
                            href={publishResult.pr_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-[#B7FF3C] hover:bg-[#D4FF8A] text-[#050505] font-bold transition-all glow-lime-sm"
                          >
                            <span>View PR #{publishResult.pr_number}</span>
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        </div>
                      </div>
                    ) : ghWorkspaceInfo ? (
                      /* If not published yet, show readiness check */
                      <div className="space-y-2">
                        {repair.verification_status === 'FIX VERIFIED' ? (
                          publishReadiness?.diverged ? (
                            <div className="p-3 bg-[#F4BF50]/10 border border-[#F4BF50]/30 rounded text-xs font-mono text-[#F4BF50] space-y-1">
                              <div className="flex items-center gap-1.5 font-bold">
                                <AlertTriangle className="w-4 h-4" />
                                Remote Branch Diverged
                              </div>
                              <p className="text-[11px] leading-relaxed">
                                The remote target branch <code className="text-[#F4F5F0]">{ghWorkspaceInfo.branch}</code> has new commits on GitHub since this repair started. Publication is halted to prevent overwriting upstream commits.
                              </p>
                            </div>
                          ) : (
                            <div className="p-3 bg-[#11140F] border border-[#B7FF3C]/30 rounded flex items-center justify-between">
                              <div className="space-y-0.5">
                                <span className="text-xs font-mono text-[#B7FF3C] font-bold flex items-center gap-1.5">
                                  <CheckCircle2 className="w-3.5 h-3.5" />
                                  Verification Succeeded &bull; Ready to Publish
                                </span>
                                <p className="text-[11px] text-[#969B90] font-mono">
                                  Empirically certified with exit code 0. Create repair branch & open PR.
                                </p>
                              </div>
                              <button
                                onClick={() => {
                                  setPublishTitle(`fix: ${issueDescription.slice(0, 60)}`);
                                  setPublishModalOpen(true);
                                }}
                                className="px-3.5 py-1.5 rounded bg-[#B7FF3C] hover:bg-[#D4FF8A] text-[#050505] text-xs font-mono font-bold transition-all glow-lime flex items-center gap-1.5 shrink-0"
                              >
                                <GitPullRequest className="w-3.5 h-3.5" />
                                <span>Publish Pull Request</span>
                              </button>
                            </div>
                          )
                        ) : (
                          <div className="p-3 bg-[#FF5C68]/10 border border-[#FF5C68]/30 rounded text-xs font-mono text-[#FF5C68] space-y-1">
                            <div className="flex items-center gap-1.5 font-bold">
                              <AlertTriangle className="w-4 h-4" />
                              Publication Blocked: Fix Not Verified
                            </div>
                            <p className="text-[11px] leading-relaxed text-[#969B90]">
                              Verification status is <code className="text-[#FF5C68]">{repair.verification_status || 'UNVERIFIED'}</code>. Patchworks strictly enforces truthful verification: unverified patches cannot be automatically opened as pull requests. Review sandbox output and retry.
                            </p>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="p-3 bg-[#11140F] border border-[#242820] rounded text-xs font-mono text-[#969B90] flex items-center justify-between">
                        <span>Workspace not linked to a GitHub repository. Use GitHub ingestion to enable 1-click PR publication.</span>
                        {!ghStatus.connected && (
                          <button
                            onClick={() => setGhConnectModalOpen(true)}
                            className="text-[#B7FF3C] hover:underline text-xs shrink-0 ml-2"
                          >
                            Connect GitHub
                          </button>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Actions & Export Toolbar */}
                  <div className="p-4 bg-[#0B0D0A] flex flex-wrap items-center justify-between gap-3">
                    <button
                      onClick={() => setRollbackModalOpen(true)}
                      className="px-3 py-1.5 rounded bg-[#11140F] hover:bg-[#FF5C68]/10 border border-[#242820] hover:border-[#FF5C68] text-xs font-mono text-[#FF5C68] transition-colors flex items-center gap-1.5"
                    >
                      <RotateCcw className="w-3.5 h-3.5" />
                      <span>Rollback Patch</span>
                    </button>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={downloadPatch}
                        className="px-2.5 py-1.5 rounded bg-[#11140F] hover:bg-[#191D16] border border-[#242820] text-xs font-mono text-[#F4F5F0] hover:text-[#B7FF3C] transition-colors flex items-center gap-1"
                      >
                        <Download className="w-3 h-3" />
                        <span>.patch</span>
                      </button>
                      <button
                        onClick={downloadReport}
                        className="px-2.5 py-1.5 rounded bg-[#11140F] hover:bg-[#191D16] border border-[#242820] text-xs font-mono text-[#F4F5F0] hover:text-[#B7FF3C] transition-colors flex items-center gap-1"
                      >
                        <FileText className="w-3 h-3" />
                        <span>report.md</span>
                      </button>
                      <button
                        onClick={downloadJson}
                        className="px-2.5 py-1.5 rounded bg-[#11140F] hover:bg-[#191D16] border border-[#242820] text-xs font-mono text-[#F4F5F0] hover:text-[#B7FF3C] transition-colors flex items-center gap-1"
                      >
                        <Terminal className="w-3 h-3" />
                        <span>session.json</span>
                      </button>
                    </div>
                  </div>
                </div>
              ) : diagnosis?.findings && diagnosis.findings.length > 0 ? (
                /* Structured Findings & Recommendations Panel */
                <div className="bg-[#0B0D0A] border border-[#242820] rounded-lg p-5 space-y-4">
                  {/* Panel Header */}
                  <div className="flex items-center justify-between border-b border-[#242820] pb-3">
                    <div className="flex items-center gap-2">
                      <Sparkles className="w-4 h-4 text-[#B7FF3C]" />
                      <h3 className="text-xs font-mono uppercase tracking-wider text-[#F4F5F0] font-bold">
                        {diagnosis.mode === 'improvement'
                          ? 'Repository Improvement Recommendations'
                          : 'Audited Correctness Findings'}
                      </h3>
                    </div>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#11140F] text-[#B7FF3C] border border-[#242820]">
                      {diagnosis.findings.length} item(s) identified
                    </span>
                  </div>

                  {/* Project Profile Summary Bar */}
                  {diagnosis.profile && (
                    <div className="bg-[#11140F] border border-[#242820] rounded p-3 text-xs font-mono space-y-2">
                      <div className="text-[10px] uppercase text-[#969B90] font-bold">Project Profile</div>
                      <div className="flex flex-wrap gap-2 text-[11px]">
                        <div className="flex items-center gap-1 bg-[#050505] px-2 py-0.5 rounded border border-[#242820]">
                          <span className="text-[#969B90]">Languages:</span>
                          <span className="text-[#B7FF3C]">{diagnosis.profile.languages.join(', ') || 'Unknown'}</span>
                        </div>
                        <div className="flex items-center gap-1 bg-[#050505] px-2 py-0.5 rounded border border-[#242820]">
                          <span className="text-[#969B90]">Manifests:</span>
                          <span className="text-[#F4F5F0]">{diagnosis.profile.manifests.join(', ') || 'None'}</span>
                        </div>
                        {diagnosis.profile.detected_test_command && (
                          <div className="flex items-center gap-1 bg-[#050505] px-2 py-0.5 rounded border border-[#242820]">
                            <span className="text-[#969B90]">Detected Tests:</span>
                            <span className="text-[#D4FF8A]">{diagnosis.profile.detected_test_command}</span>
                          </div>
                        )}
                        <div className="flex items-center gap-1 bg-[#050505] px-2 py-0.5 rounded border border-[#242820]">
                          <span className="text-[#969B90]">Source Files:</span>
                          <span className="text-[#F4F5F0]">{diagnosis.profile.source_files_count}</span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Executive Summary */}
                  <div className="bg-[#11140F] border border-[#242820] rounded p-3 text-xs text-[#F4F5F0] leading-relaxed">
                    <span className="text-[10px] font-mono uppercase text-[#B7FF3C] block mb-1 font-bold">Analysis Summary</span>
                    <p>{diagnosis.investigation?.summary || diagnosis.diagnosis.diagnosis}</p>
                  </div>

                  {/* Findings Cards List */}
                  <div className="space-y-3">
                    {diagnosis.findings.map((finding, idx) => {
                      const isSelected = selectedFinding?.id === finding.id;
                      const isHigh = finding.severity === 'high' || finding.severity === 'critical';
                      const isMed = finding.severity === 'medium';
                      return (
                        <div
                          key={finding.id || idx}
                          className={`border rounded-lg p-4 space-y-3 transition-all ${
                            isSelected
                              ? 'border-[#B7FF3C] bg-[#11140F] glow-lime-sm'
                              : isHigh
                              ? 'border-[#FF5C68]/30 bg-[#0B0D0A] hover:border-[#FF5C68]/60'
                              : isMed
                              ? 'border-[#F4BF50]/30 bg-[#0B0D0A] hover:border-[#F4BF50]/60'
                              : 'border-[#242820] bg-[#0B0D0A] hover:border-[#3A4034]'
                          }`}
                        >
                          {/* Finding Header */}
                          <div className="flex items-start justify-between gap-2">
                            <div>
                              <div className="flex items-center gap-2 mb-1">
                                <span className="text-[10px] font-mono text-[#969B90]">#{finding.id}</span>
                                <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-[#11140F] text-[#B7FF3C] border border-[#242820]">
                                  {finding.category || 'IMPROVEMENT'}
                                </span>
                                <span
                                  className={`text-[10px] font-mono uppercase px-1.5 py-0.5 rounded font-bold border ${
                                    isHigh
                                      ? 'bg-[#FF5C68]/10 text-[#FF5C68] border-[#FF5C68]/30'
                                      : isMed
                                      ? 'bg-[#F4BF50]/10 text-[#F4BF50] border-[#F4BF50]/30'
                                      : 'bg-[#242820] text-[#969B90] border-[#3A4034]'
                                  }`}
                                >
                                  {finding.severity} Severity
                                </span>
                                <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-[#050505] text-[#969B90] border border-[#242820]">
                                  {finding.confidence} Confidence
                                </span>
                              </div>
                              <h4 className="text-xs font-mono font-bold text-[#F4F5F0] leading-snug">{finding.title}</h4>
                            </div>
                          </div>

                          {/* Files & Impact */}
                          <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono text-[#969B90]">
                            <span className="text-[#969B90]">Affected Files:</span>
                            {finding.files?.map((file, fIdx) => (
                              <span key={fIdx} className="bg-[#11140F] text-[#D4FF8A] px-1.5 py-0.5 rounded border border-[#242820]">
                                {file}
                              </span>
                            ))}
                            {finding.risk && (
                              <span className="text-[10px] text-[#969B90] ml-auto">Risk: {finding.risk}</span>
                            )}
                          </div>

                          {/* Explanation */}
                          <p className="text-xs text-[#F4F5F0]/90 leading-relaxed font-sans">{finding.explanation}</p>

                          {/* Evidence */}
                          {finding.evidence && (
                            <div>
                              <span className="text-[10px] font-mono uppercase text-[#969B90] block mb-1">Code Evidence</span>
                              <pre className="text-[11px] font-mono bg-[#050505] p-2.5 rounded border border-[#242820] text-[#D4FF8A] overflow-x-auto whitespace-pre-wrap leading-relaxed">
                                {finding.evidence}
                              </pre>
                            </div>
                          )}

                          {/* Proposed Fix & Action Button */}
                          <div className="pt-2 border-t border-[#242820] space-y-2">
                            <div className="text-[11px] font-mono text-[#F4F5F0]">
                              <span className="text-[#B7FF3C] font-semibold">Recommended Action: </span>
                              {finding.proposed_fix}
                            </div>

                            <button
                              onClick={() => handleRepairFinding(finding)}
                              disabled={loading}
                              className="w-full py-2 px-3 rounded bg-[#B7FF3C] hover:bg-[#D4FF8A] disabled:opacity-40 text-[#050505] text-xs font-mono font-bold transition-all glow-lime-sm flex items-center justify-center gap-1.5"
                            >
                              <Sparkles className="w-3.5 h-3.5" />
                              <span>Synthesize & Apply Scoped Fix for #{finding.id}</span>
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                /* Empty State */
                <div className="h-full border border-[#242820] bg-[#0B0D0A] rounded-lg p-8 flex flex-col items-center justify-center text-center space-y-4 engineering-grid min-h-[420px]">
                  <div className="relative group">
                    <div className="absolute -inset-1.5 rounded-2xl bg-gradient-to-b from-[#B7FF3C]/20 to-transparent blur-md group-hover:from-[#B7FF3C]/35 transition duration-500 opacity-80" />
                    <img
                      src="/patchworks-squircle.png"
                      alt="Patchworks Workbench"
                      className="relative w-16 h-16 rounded-xl object-contain drop-shadow-[0_0_20px_rgba(183,255,60,0.25)]"
                    />
                  </div>
                  <div className="max-w-md space-y-1.5">
                    <h3 className="text-sm font-mono uppercase tracking-wider text-[#F4F5F0] font-bold">
                      Awaiting Code Ingestion
                    </h3>
                    <p className="text-xs text-[#969B90] leading-relaxed">
                      Supply a Git repository URL, upload a ZIP archive, or select a benchmark target to initiate
                      empirical diagnosis and patch generation.
                    </p>
                  </div>
                  <div className="flex gap-2 pt-2">
                    <button
                      onClick={() => loadBenchmark('simple_bug')}
                      className="text-xs font-mono bg-[#11140F] hover:bg-[#191D16] border border-[#242820] hover:border-[#B7FF3C] text-[#B7FF3C] px-3 py-1.5 rounded transition-colors"
                    >
                      Load simple_bug
                    </button>
                    <button
                      onClick={() => loadBenchmark('edge_case')}
                      className="text-xs font-mono bg-[#11140F] hover:bg-[#191D16] border border-[#242820] hover:border-[#B7FF3C] text-[#B7FF3C] px-3 py-1.5 rounded transition-colors"
                    >
                      Load edge_case
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>

      {/* Confirmation Modal for Rollback */}
      {rollbackModalOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-[#0B0D0A] border border-[#242820] p-6 rounded-lg max-w-sm w-full space-y-4 glow-lime-sm">
            <div className="flex items-center gap-3 text-[#FF5C68]">
              <AlertTriangle className="w-5 h-5 shrink-0" />
              <h4 className="text-sm font-mono uppercase font-bold text-[#F4F5F0]">Confirm Rollback</h4>
            </div>
            <p className="text-xs text-[#969B90] leading-relaxed">
              This will execute a hard reset (<code className="text-[#F4F5F0]">git reset --hard HEAD</code>) on the active
              isolated workspace. All uncommitted patch modifications will be discarded.
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setRollbackModalOpen(false)}
                className="px-3 py-1.5 rounded bg-[#11140F] border border-[#242820] text-xs font-mono text-[#969B90] hover:text-[#F4F5F0]"
              >
                Cancel
              </button>
              <button
                onClick={handleRollback}
                className="px-3 py-1.5 rounded bg-[#FF5C68] hover:bg-[#FF5C68]/90 text-[#050505] text-xs font-mono font-bold"
              >
                Discard & Reset
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Settings & Engine Config Drawer */}
      {settingsOpen && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-[#0B0D0A] border border-[#242820] p-6 rounded-lg max-w-md w-full space-y-4">
            <div className="flex items-center justify-between border-b border-[#242820] pb-3">
              <h4 className="text-xs font-mono uppercase tracking-wider text-[#F4F5F0] flex items-center gap-2">
                <img src="/patchworks-icon.png" alt="Patchworks" className="w-4 h-4 object-contain" />
                Patchworks Engine Configuration
              </h4>
              <button onClick={() => setSettingsOpen(false)} className="text-[#969B90] hover:text-[#F4F5F0]">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3 text-xs font-mono">
              <div className="p-3 bg-[#11140F] rounded border border-[#242820] space-y-2">
                <div className="flex justify-between">
                  <span className="text-[#969B90]">Inference Provider:</span>
                  <span className="text-[#F4F5F0]">Nebius AI Cloud</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#969B90]">Model Target:</span>
                  <span className="text-[#B7FF3C]">{health?.model || 'nvidia/Nemotron-3_5-Lightning'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#969B90]">Credentials Status:</span>
                  <span className={health?.nebius_configured ? 'text-[#B7FF3C]' : 'text-[#F4BF50]'}>
                    {health?.nebius_configured ? 'Configured (Live)' : 'Missing (Mock Mode)'}
                  </span>
                </div>
              </div>

              <div className="space-y-1.5 text-[11px] text-[#969B90] leading-relaxed">
                <p>
                  To switch from simulated mock mode to live inference, set <code className="text-[#F4F5F0]">NEBIUS_API_KEY</code> in{' '}
                  <code className="text-[#F4F5F0]">.env</code>:
                </p>
                <pre className="bg-[#050505] p-2.5 rounded border border-[#242820] text-[#D4FF8A] overflow-x-auto">
{`NEBIUS_API_KEY="your-nebius-token"
NEBIUS_BASE_URL="https://api.studio.nebius.ai/v1/"
NEBIUS_MODEL_NAME="nvidia/Nemotron-3_5-Lightning"`}
                </pre>
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setSettingsOpen(false)}
                className="px-4 py-1.5 rounded bg-[#B7FF3C] hover:bg-[#D4FF8A] text-[#050505] text-xs font-mono font-bold"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Explicit User Approval Modal for Pull Request Publication */}
      {publishModalOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-[#0B0D0A] border border-[#242820] p-6 rounded-lg max-w-lg w-full space-y-4 glow-lime-sm">
            <div className="flex items-center justify-between border-b border-[#242820] pb-3">
              <div className="flex items-center gap-2.5 text-[#F4F5F0]">
                <GitPullRequest className="w-5 h-5 text-[#B7FF3C]" />
                <h4 className="text-sm font-mono uppercase font-bold">
                  Review & Publish Pull Request
                </h4>
              </div>
              <button
                onClick={() => setPublishModalOpen(false)}
                disabled={publishing}
                className="text-[#969B90] hover:text-[#F4F5F0]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {publishError && (
              <div className="p-2.5 bg-[#FF5C68]/10 border border-[#FF5C68]/30 rounded text-xs font-mono text-[#FF5C68]">
                {publishError}
              </div>
            )}

            <div className="space-y-3 text-xs font-mono">
              {/* Publication Context Summary */}
              <div className="p-3 bg-[#11140F] rounded border border-[#242820] space-y-2">
                <div className="flex justify-between">
                  <span className="text-[#969B90]">Target Repository:</span>
                  <span className="text-[#F4F5F0]">
                    {ghWorkspaceInfo?.owner}/{ghWorkspaceInfo?.repo}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#969B90]">Target Branch:</span>
                  <span className="text-[#B7FF3C]">{ghWorkspaceInfo?.branch}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#969B90]">Dedicated Fix Branch:</span>
                  <span className="text-[#F4F5F0]">patchworks/fix-{workspaceId?.slice(0, 8)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#969B90]">Verification Status:</span>
                  <span className="text-[#B7FF3C] font-bold">
                    FIX VERIFIED (Exit Code {repair?.verification_details?.returncode ?? 0})
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#969B90]">Inference Mode:</span>
                  <span className={health?.nebius_configured ? 'text-[#B7FF3C]' : 'text-[#F4BF50]'}>
                    {health?.nebius_configured ? 'Live Nebius (Nemotron-70B)' : 'Simulated Mock Mode'}
                  </span>
                </div>
              </div>

              {/* Title Input */}
              <div>
                <label className="block text-xs font-mono uppercase text-[#969B90] mb-1">
                  Pull Request Title
                </label>
                <input
                  type="text"
                  value={publishTitle}
                  onChange={(e) => setPublishTitle(e.target.value)}
                  disabled={publishing}
                  placeholder="fix: autonomous patch repair"
                  className="w-full bg-[#11140F] border border-[#242820] rounded p-2 text-xs text-[#F4F5F0] font-mono focus:border-[#B7FF3C] outline-none"
                />
              </div>

              {/* Additional Review Notes */}
              <div>
                <label className="block text-xs font-mono uppercase text-[#969B90] mb-1">
                  Additional Review Notes (Optional)
                </label>
                <textarea
                  value={publishNotes}
                  onChange={(e) => setPublishNotes(e.target.value)}
                  disabled={publishing}
                  rows={2}
                  placeholder="Add any team context or review guidelines..."
                  className="w-full bg-[#11140F] border border-[#242820] rounded p-2 text-xs text-[#F4F5F0] font-mono focus:border-[#B7FF3C] outline-none"
                />
              </div>

              <div className="p-2.5 bg-[#050505] rounded border border-[#242820] text-[11px] text-[#969B90] leading-relaxed">
                <span className="text-[#B7FF3C] font-bold block mb-0.5">Automated Safeguard Policy:</span>
                Patchworks will commit only modified files to a dedicated repair branch and open an auditable pull request with empirical test logs. It will never force-push, push to protected branches, or automatically merge.
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setPublishModalOpen(false)}
                disabled={publishing}
                className="px-3 py-1.5 rounded bg-[#11140F] border border-[#242820] text-xs font-mono text-[#969B90] hover:text-[#F4F5F0]"
              >
                Cancel
              </button>
              <button
                onClick={handlePublishPR}
                disabled={publishing}
                className="px-4 py-1.5 rounded bg-[#B7FF3C] hover:bg-[#D4FF8A] text-[#050505] text-xs font-mono font-bold transition-all glow-lime flex items-center gap-1.5 disabled:opacity-50"
              >
                {publishing ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Pushing & Opening PR...</span>
                  </>
                ) : (
                  <>
                    <GitPullRequest className="w-3.5 h-3.5" />
                    <span>Confirm & Open Pull Request</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* GitHub Authentication / Connect Modal */}
      {ghConnectModalOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-[#0B0D0A] border border-[#242820] p-6 rounded-lg max-w-md w-full space-y-4 glow-lime-sm">
            <div className="flex items-center justify-between border-b border-[#242820] pb-3">
              <div className="flex items-center gap-2 text-[#F4F5F0]">
                <Github className="w-5 h-5 text-[#B7FF3C]" />
                <h4 className="text-sm font-mono uppercase font-bold">Connect GitHub Account</h4>
              </div>
              <button
                onClick={() => setGhConnectModalOpen(false)}
                disabled={ghConnecting}
                className="text-[#969B90] hover:text-[#F4F5F0]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {ghConnectError && (
              <div className="p-2.5 bg-[#FF5C68]/10 border border-[#FF5C68]/30 rounded text-xs font-mono text-[#FF5C68]">
                {ghConnectError}
              </div>
            )}

            {ghStatus?.oauth_available && (
              <div className="space-y-3 pb-2">
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      const callbackUri = window.location.origin + '/api/github/oauth/callback';
                      const res = await axios.get('/api/github/oauth/url', { params: { redirect_uri: callbackUri } });
                      if (res.data?.url) {
                        window.location.href = res.data.url;
                      }
                    } catch (e: any) {
                      setGhConnectError(e.response?.data?.detail || 'Failed to initiate GitHub OAuth');
                    }
                  }}
                  className="w-full py-2 px-3 rounded bg-[#1A1F14] hover:bg-[#252C1C] border border-[#B7FF3C]/50 text-[#F4F5F0] text-xs font-mono font-bold flex items-center justify-center gap-2 transition-all hover:border-[#B7FF3C]"
                >
                  <Github className="w-4 h-4 text-[#B7FF3C]" />
                  <span>Connect with GitHub OAuth</span>
                </button>
                <div className="relative flex items-center py-1">
                  <div className="flex-grow border-t border-[#242820]"></div>
                  <span className="flex-shrink mx-2 text-[10px] text-[#969B90] uppercase font-mono">or manual token</span>
                  <div className="flex-grow border-t border-[#242820]"></div>
                </div>
              </div>
            )}

            <div className="space-y-3 text-xs font-mono">
              <p className="text-[11px] text-[#969B90] leading-relaxed">
                Authenticate with a GitHub Personal Access Token (classic with <code className="text-[#F4F5F0]">repo</code> scope, or fine-grained with read/write access to <code className="text-[#F4F5F0]">Contents</code> and <code className="text-[#F4F5F0]">Pull Requests</code>).
              </p>

              <div>
                <label className="block text-xs font-mono uppercase text-[#969B90] mb-1">
                  GitHub Personal Access Token (PAT)
                </label>
                <input
                  type="password"
                  value={ghTokenInput}
                  onChange={(e) => setGhTokenInput(e.target.value)}
                  disabled={ghConnecting}
                  placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                  className="w-full bg-[#11140F] border border-[#242820] rounded p-2 text-xs text-[#F4F5F0] font-mono focus:border-[#B7FF3C] outline-none"
                />
              </div>

              <div className="p-2.5 bg-[#050505] rounded border border-[#242820] text-[10px] text-[#969B90] leading-relaxed space-y-1">
                <span className="text-[#B7FF3C] font-semibold block">Security Guarantee:</span>
                Tokens are validated securely on the backend, encrypted at rest, never exposed in client logs or URLs, and never stored in frontend storage.
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setGhConnectModalOpen(false)}
                disabled={ghConnecting}
                className="px-3 py-1.5 rounded bg-[#11140F] border border-[#242820] text-xs font-mono text-[#969B90] hover:text-[#F4F5F0]"
              >
                Cancel
              </button>
              <button
                onClick={handleGitHubConnect}
                disabled={ghConnecting || !ghTokenInput.trim()}
                className="px-4 py-1.5 rounded bg-[#B7FF3C] hover:bg-[#D4FF8A] text-[#050505] text-xs font-mono font-bold transition-all glow-lime flex items-center gap-1.5 disabled:opacity-50"
              >
                {ghConnecting ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>Verifying Credentials...</span>
                  </>
                ) : (
                  <>
                    <Key className="w-3.5 h-3.5" />
                    <span>Connect & Verify</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Supabase User Authentication Modal */}
      {authModalOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-[#0B0D0A] border border-[#242820] p-6 rounded-lg max-w-md w-full space-y-4 glow-lime-sm">
            <div className="flex items-center justify-between border-b border-[#242820] pb-3">
              <div className="flex items-center gap-2.5 text-[#F4F5F0]">
                <img src="/patchworks-icon.png" alt="Patchworks" className="w-5 h-5 object-contain" />
                <h4 className="text-sm font-mono uppercase font-bold">
                  {authMode === 'signup'
                    ? 'Create Patchworks Account'
                    : authMode === 'magic'
                    ? 'Sign In via Magic Link'
                    : 'Sign In to Patchworks'}
                </h4>
              </div>
              <button
                onClick={() => {
                  setAuthModalOpen(false);
                  setAuthError('');
                  setAuthSuccessMsg('');
                }}
                disabled={authLoading}
                className="text-[#969B90] hover:text-[#F4F5F0]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {authError && (
              <div className="p-2.5 bg-[#FF5C68]/10 border border-[#FF5C68]/30 rounded text-xs font-mono text-[#FF5C68]">
                {authError}
              </div>
            )}

            {authSuccessMsg && (
              <div className="p-2.5 bg-[#B7FF3C]/10 border border-[#B7FF3C]/30 rounded text-xs font-mono text-[#B7FF3C]">
                {authSuccessMsg}
              </div>
            )}

            {/* GitHub OAuth Button */}
            <div className="space-y-3 pb-2">
              <button
                type="button"
                onClick={handleSupabaseGitHubLogin}
                disabled={authLoading}
                className="w-full py-2.5 px-3 rounded bg-[#1A1F14] hover:bg-[#252C1C] border border-[#B7FF3C]/50 text-[#F4F5F0] text-xs font-mono font-bold flex items-center justify-center gap-2 transition-all hover:border-[#B7FF3C] disabled:opacity-50"
              >
                <Github className="w-4 h-4 text-[#B7FF3C]" />
                <span>Continue with GitHub</span>
              </button>
              <div className="relative flex items-center py-1">
                <div className="flex-grow border-t border-[#242820]"></div>
                <span className="flex-shrink mx-2 text-[10px] text-[#969B90] uppercase font-mono">or email</span>
                <div className="flex-grow border-t border-[#242820]"></div>
              </div>
            </div>

            {/* Mode Tabs */}
            <div className="flex border-b border-[#242820] gap-4 text-xs font-mono">
              <button
                type="button"
                onClick={() => { setAuthMode('signin'); setAuthError(''); setAuthSuccessMsg(''); }}
                className={`pb-1.5 transition-colors ${authMode === 'signin' ? 'text-[#B7FF3C] border-b-2 border-[#B7FF3C]' : 'text-[#969B90] hover:text-[#F4F5F0]'}`}
              >
                Sign In
              </button>
              <button
                type="button"
                onClick={() => { setAuthMode('signup'); setAuthError(''); setAuthSuccessMsg(''); }}
                className={`pb-1.5 transition-colors ${authMode === 'signup' ? 'text-[#B7FF3C] border-b-2 border-[#B7FF3C]' : 'text-[#969B90] hover:text-[#F4F5F0]'}`}
              >
                Sign Up
              </button>
              <button
                type="button"
                onClick={() => { setAuthMode('magic'); setAuthError(''); setAuthSuccessMsg(''); }}
                className={`pb-1.5 transition-colors flex items-center gap-1 ${authMode === 'magic' ? 'text-[#B7FF3C] border-b-2 border-[#B7FF3C]' : 'text-[#969B90] hover:text-[#F4F5F0]'}`}
              >
                <Mail className="w-3 h-3" />
                <span>Magic Link</span>
              </button>
            </div>

            {/* Email form */}
            <form onSubmit={authMode === 'signup' ? handleEmailSignUp : authMode === 'magic' ? handleMagicLink : handleEmailSignIn} className="space-y-3 text-xs font-mono">
              <div>
                <label className="block text-[11px] font-mono uppercase text-[#969B90] mb-1">Email Address</label>
                <input
                  type="email"
                  required
                  value={authEmail}
                  onChange={(e) => setAuthEmail(e.target.value)}
                  disabled={authLoading}
                  placeholder="developer@example.com"
                  className="w-full bg-[#11140F] border border-[#242820] rounded p-2 text-xs text-[#F4F5F0] font-mono focus:border-[#B7FF3C] outline-none"
                />
              </div>

              {authMode !== 'magic' && (
                <div>
                  <label className="block text-[11px] font-mono uppercase text-[#969B90] mb-1">Password</label>
                  <input
                    type="password"
                    required
                    value={authPassword}
                    onChange={(e) => setAuthPassword(e.target.value)}
                    disabled={authLoading}
                    placeholder="••••••••••••"
                    className="w-full bg-[#11140F] border border-[#242820] rounded p-2 text-xs text-[#F4F5F0] font-mono focus:border-[#B7FF3C] outline-none"
                  />
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setAuthModalOpen(false)}
                  disabled={authLoading}
                  className="px-3 py-1.5 rounded bg-[#11140F] border border-[#242820] text-xs font-mono text-[#969B90] hover:text-[#F4F5F0]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={authLoading || !authEmail.trim()}
                  className="px-4 py-1.5 rounded bg-[#B7FF3C] hover:bg-[#D4FF8A] text-[#050505] text-xs font-mono font-bold transition-all glow-lime flex items-center gap-1.5 disabled:opacity-50"
                >
                  {authLoading ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Processing...</span>
                    </>
                  ) : authMode === 'signup' ? (
                    <span>Create Account</span>
                  ) : authMode === 'magic' ? (
                    <span>Send Magic Link</span>
                  ) : (
                    <span>Sign In</span>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
