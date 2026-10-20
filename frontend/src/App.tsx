import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { AlertCircle, CheckCircle, Code, Play, Bug, FileText, XCircle, Upload, Download, RefreshCw } from 'lucide-react';

interface HealthStatus {
  status: string;
  message: string;
  nebius_configured: boolean;
  model: string;
}

interface Diagnosis {
  status: string;
  workspace_id?: string;
  reproduction?: any;
  diagnosis: {
    diagnosis: string;
    evidence: string;
    files_to_modify: string[];
    proposed_fix_description: string;
    regression_risks?: string;
  };
}

interface Repair {
  status: string;
  workspace_id?: string;
  message?: string;
  patch: string;
  verification_status?: string;
  verification_details?: any;
}

function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);

  const [inputType, setInputType] = useState<'git' | 'zip' | 'benchmark'>('git');
  const [repoUrl, setRepoUrl] = useState('');
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);

  const [issueDescription, setIssueDescription] = useState('');
  const [testCommand, setTestCommand] = useState('');
  
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [repair, setRepair] = useState<Repair | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    axios.get('/api/health').then(res => setHealth(res.data)).catch(console.error);
  }, []);

  const loadBenchmark = (type: 'simple_bug' | 'edge_case') => {
    if (type === 'simple_bug') {
      setRepoUrl('file:///app/benchmark_fixtures/simple_bug');
      setIssueDescription('test_subtract fails because it adds instead of subtracting');
      setTestCommand('pytest test_math_utils.py');
    } else {
      setRepoUrl('file:///app/benchmark_fixtures/edge_case');
      setIssueDescription('truncate_text truncates at 9 chars instead of 10 when max_length is 10');
      setTestCommand('pytest test_text_utils.py');
    }
    setWorkspaceId(null);
    setZipFile(null);
    setDiagnosis(null);
    setRepair(null);
  };

  const handleZipUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setZipFile(file);
      setLoading(true);
      setError('');
      try {
        const formData = new FormData();
        formData.append('file', file);
        const response = await axios.post('/api/upload', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });
        setWorkspaceId(response.data.workspace_id);
      } catch (err: any) {
        setError(err.response?.data?.detail || err.message);
        setZipFile(null);
      } finally {
        setLoading(false);
      }
    }
  };

  const handleDiagnose = async () => {
    setLoading(true);
    setError('');
    try {
      const payload: any = {
        issue_description: issueDescription,
        test_command: testCommand || undefined
      };

      if (workspaceId) {
        payload.workspace_id = workspaceId;
      } else {
        payload.repo_url = repoUrl;
      }

      const response = await axios.post('/api/diagnose', payload);
      setDiagnosis(response.data);
      if (response.data.workspace_id) {
        setWorkspaceId(response.data.workspace_id);
      }
      setRepair(null);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRepair = async () => {
    if (!diagnosis) return;
    setLoading(true);
    setError('');
    try {
      const payload: any = {
        issue_description: issueDescription,
        diagnosis_context: diagnosis.diagnosis,
        test_command: testCommand || undefined
      };

      if (workspaceId) {
        payload.workspace_id = workspaceId;
      } else {
        payload.repo_url = repoUrl;
      }

      const response = await axios.post('/api/repair', payload);
      setRepair(response.data);
      if (response.data.workspace_id) {
        setWorkspaceId(response.data.workspace_id);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRollback = async () => {
    if (!workspaceId) return;
    setLoading(true);
    setError('');
    try {
      await axios.post('/api/rollback', { workspace_id: workspaceId });
      setRepair(null); // Clear repair state since we rolled back
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  const resetSession = () => {
    if (workspaceId) {
      axios.delete(`/api/workspace/${workspaceId}`).catch(console.error);
    }
    setWorkspaceId(null);
    setRepoUrl('');
    setIssueDescription('');
    setTestCommand('');
    setDiagnosis(null);
    setRepair(null);
    setZipFile(null);
    setError('');
  };

  const downloadPatch = () => {
    if (!repair?.patch) return;
    const blob = new Blob([repair.patch], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'repair.patch';
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadReport = () => {
    if (!diagnosis || !repair) return;
    const report = `# ProofPatch Repair Report

## Project Identification
**Workspace ID:** \`${workspaceId}\`
**Repository/Source:** \`${repoUrl || 'ZIP Upload'}\`

## Problem Description
${issueDescription}
**Test Command:** \`${testCommand || 'None'}\`

## Diagnosis
**Root Cause:** ${diagnosis.diagnosis.diagnosis}
**Evidence:**
> ${diagnosis.diagnosis.evidence}
**Regression Risks:** ${diagnosis.diagnosis.regression_risks || 'None specified'}

## Applied Patch
\`\`\`diff
${repair.patch}
\`\`\`

## Verification Certification
**Status:** ${repair.verification_status || repair.status}
${repair.verification_details ? `
### Test Output
**Exit Code:** ${repair.verification_details.returncode}
**Stdout:**
\`\`\`
${repair.verification_details.stdout}
\`\`\`
**Stderr:**
\`\`\`
${repair.verification_details.stderr}
\`\`\`
` : ''}
`;
    const blob = new Blob([report], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'repair_report.md';
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadJson = () => {
    const data = {
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
    a.download = 'session_audit.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen p-8 max-w-6xl mx-auto space-y-8">
      <header className="flex items-center justify-between border-b border-slate-700 pb-4">
        <div className="flex items-center space-x-4">
          <Bug className="w-8 h-8 text-indigo-400" />
          <h1 className="text-3xl font-bold">ProofPatch Workbench</h1>
        </div>
        <div className="flex items-center gap-4">
          {health && !health.nebius_configured && (
            <div className="bg-amber-900/50 text-amber-400 px-3 py-1 rounded-full text-xs font-bold border border-amber-500 flex items-center gap-2">
              <AlertCircle className="w-4 h-4" /> DEMO / MOCK MODE
            </div>
          )}
          {health && (
            <div className="text-xs text-slate-400 bg-slate-800 px-3 py-1 rounded-full border border-slate-700">
              {health.model}
            </div>
          )}
          <button onClick={resetSession} className="text-slate-400 hover:text-white flex items-center gap-1 text-sm bg-slate-800 px-3 py-1 rounded border border-slate-700 transition-colors">
            <RefreshCw className="w-4 h-4" /> New Session
          </button>
        </div>
      </header>

      {error && (
        <div className="bg-red-900/50 border border-red-500 text-red-200 p-4 rounded flex items-center space-x-2">
          <AlertCircle className="w-5 h-5" />
          <span>{error}</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="space-y-6">
          <div className="bg-slate-800 p-6 rounded-lg border border-slate-700 space-y-4">
            <h2 className="text-xl font-semibold flex items-center gap-2">
              <FileText className="w-5 h-5 text-slate-400" /> 
              Project Ingestion
            </h2>
            
            <div className="flex gap-2 border-b border-slate-700 pb-2">
              <button
                onClick={() => setInputType('git')}
                className={`px-3 py-1 text-sm rounded-t ${inputType === 'git' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
              >
                Git URL
              </button>
              <button
                onClick={() => setInputType('zip')}
                className={`px-3 py-1 text-sm rounded-t ${inputType === 'zip' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
              >
                ZIP Upload
              </button>
              <button
                onClick={() => setInputType('benchmark')}
                className={`px-3 py-1 text-sm rounded-t ${inputType === 'benchmark' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
              >
                Benchmarks
              </button>
            </div>
            
            {inputType === 'git' && (
              <div>
                <label className="block text-sm font-medium text-slate-400 mb-1">Git Repository URL</label>
                <input
                  type="text"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  disabled={!!workspaceId}
                  placeholder="https://github.com/user/repo.git"
                  className="w-full bg-slate-900 border border-slate-600 rounded p-2 text-slate-200 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none disabled:opacity-50"
                />
              </div>
            )}

            {inputType === 'zip' && (
              <div>
                <label className="block text-sm font-medium text-slate-400 mb-1">Upload ZIP Archive</label>
                <div className="flex items-center gap-4">
                  <label className="flex items-center gap-2 bg-slate-700 hover:bg-slate-600 cursor-pointer px-4 py-2 rounded text-sm transition-colors disabled:opacity-50">
                    <Upload className="w-4 h-4" /> Choose File
                    <input type="file" accept=".zip" className="hidden" onChange={handleZipUpload} disabled={!!workspaceId} />
                  </label>
                  {zipFile && <span className="text-sm text-emerald-400 flex items-center gap-1"><CheckCircle className="w-4 h-4" /> {zipFile.name} uploaded</span>}
                  {workspaceId && !zipFile && <span className="text-sm text-emerald-400 flex items-center gap-1"><CheckCircle className="w-4 h-4" /> Workspace Ready</span>}
                </div>
              </div>
            )}

            {inputType === 'benchmark' && (
              <div className="flex gap-2">
                 <button onClick={() => loadBenchmark('simple_bug')} disabled={!!workspaceId} className="bg-slate-700 hover:bg-slate-600 px-3 py-2 rounded text-sm disabled:opacity-50">Load simple_bug</button>
                 <button onClick={() => loadBenchmark('edge_case')} disabled={!!workspaceId} className="bg-slate-700 hover:bg-slate-600 px-3 py-2 rounded text-sm disabled:opacity-50">Load edge_case</button>
              </div>
            )}

            <div className="pt-2">
              <label className="block text-sm font-medium text-slate-400 mb-1">Issue Description / Trace</label>
              <textarea 
                value={issueDescription}
                onChange={(e) => setIssueDescription(e.target.value)}
                placeholder="Describe the bug or paste the stack trace..."
                className="w-full bg-slate-900 border border-slate-600 rounded p-2 text-slate-200 h-32 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">Reproduction Test Command (Optional)</label>
              <input 
                type="text" 
                value={testCommand}
                onChange={(e) => setTestCommand(e.target.value)}
                placeholder="pytest tests/test_bug.py"
                className="w-full bg-slate-900 border border-slate-600 rounded p-2 text-slate-200 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
              />
            </div>

            <button 
              onClick={handleDiagnose}
              disabled={loading || (!repoUrl && !workspaceId) || !issueDescription}
              className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-700 text-white font-medium py-2 px-4 rounded transition-colors flex items-center justify-center gap-2"
            >
              {loading && !diagnosis ? 'Analyzing...' : 'Diagnose Issue'}
            </button>
          </div>

          {diagnosis && (
            <div className="bg-slate-800 p-6 rounded-lg border border-slate-700 space-y-4 shadow-xl">
              <h2 className="text-xl font-semibold flex items-center gap-2 text-indigo-400">
                <AlertCircle className="w-5 h-5" /> 
                Diagnosis
              </h2>
              <div className="space-y-3 text-slate-300">
                <div>
                  <strong className="block text-slate-400 text-sm">Root Cause:</strong>
                  <p className="mt-1">{diagnosis.diagnosis.diagnosis}</p>
                </div>
                <div>
                  <strong className="block text-slate-400 text-sm">Evidence:</strong>
                  <p className="mt-1 italic border-l-2 border-slate-600 pl-3 py-1 bg-slate-900/50">{diagnosis.diagnosis.evidence}</p>
                </div>
                <div>
                  <strong className="block text-slate-400 text-sm">Files to modify:</strong>
                  <div className="flex flex-wrap gap-2 mt-1">
                    {diagnosis.diagnosis.files_to_modify.map((f, i) => (
                      <span key={i} className="bg-slate-900 px-2 py-1 rounded text-xs font-mono text-indigo-300">{f}</span>
                    ))}
                  </div>
                </div>
                {diagnosis.diagnosis.regression_risks && (
                  <div>
                    <strong className="block text-amber-400/80 text-sm">Regression Risks:</strong>
                    <p className="mt-1 text-sm text-amber-200/70">{diagnosis.diagnosis.regression_risks}</p>
                  </div>
                )}
                
                <button 
                  onClick={handleRepair}
                  disabled={loading}
                  className="w-full mt-4 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-700 text-white font-medium py-2 px-4 rounded transition-colors flex items-center justify-center gap-2"
                >
                  {loading && diagnosis && !repair ? 'Generating Repair...' : 'Apply Patch'}
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="space-y-6">
          {repair && (
            <div className="bg-slate-800 p-6 rounded-lg border border-slate-700 space-y-4 h-full flex flex-col shadow-xl">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-semibold flex items-center gap-2">
                  <Code className="w-5 h-5 text-slate-400" /> 
                  Proposed Patch
                </h2>
                <div className={`px-3 py-1 rounded-full text-sm font-bold flex items-center gap-1 ${
                  repair.verification_status === 'FIX VERIFIED' ? 'bg-emerald-900/50 text-emerald-400 border border-emerald-500' :
                  repair.verification_status === 'FIX PARTIALLY VERIFIED' ? 'bg-emerald-900/50 text-emerald-400 border border-emerald-500' :
                  repair.status === 'error' || repair.verification_status === 'APPLY FAILED' ? 'bg-red-900/50 text-red-400 border border-red-500' :
                  repair.verification_status === 'FIX FAILED' ? 'bg-red-900/50 text-red-400 border border-red-500' :
                  'bg-yellow-900/50 text-yellow-400 border border-yellow-500'
                }`}>
                  {repair.verification_status === 'FIX VERIFIED' ? <CheckCircle className="w-4 h-4" /> : 
                   repair.verification_status === 'FIX PARTIALLY VERIFIED' ? <CheckCircle className="w-4 h-4" /> :
                   repair.status === 'error' || repair.verification_status === 'APPLY FAILED' ? <XCircle className="w-4 h-4" /> :
                   <AlertCircle className="w-4 h-4" />}
                  {repair.verification_status || (repair.status === 'error' ? 'APPLY FAILED' : 'UNVERIFIED')}
                </div>
              </div>

              <div className="flex gap-2">
                <button onClick={handleRollback} disabled={loading} className="text-xs bg-slate-700 hover:bg-slate-600 px-3 py-1 rounded transition-colors disabled:opacity-50">
                  Discard / Rollback Patch
                </button>
              </div>

              {repair.status === 'error' && repair.message && (
                <div className="bg-red-900/30 border border-red-800 text-red-300 p-3 rounded text-sm mb-2">
                  {repair.message}
                </div>
              )}

              <div className="flex-1 bg-slate-900 rounded p-4 overflow-auto font-mono text-sm border border-slate-700">
                {repair.patch.split('\n').map((line, i) => (
                  <div key={i} className={`${line.startsWith('+') ? 'text-emerald-400 bg-emerald-900/20' : line.startsWith('-') ? 'text-red-400 bg-red-900/20' : 'text-slate-300'}`}>
                    {line}
                  </div>
                ))}
              </div>

              {repair.verification_details && (
                <div className="mt-4">
                  <div className="flex justify-between items-center mb-2">
                    <h3 className="text-sm font-medium text-slate-400 flex items-center gap-1">
                      <Play className="w-4 h-4" /> Test Output
                    </h3>
                    <span className="text-xs font-mono text-slate-500">Exit code: {repair.verification_details.returncode}</span>
                  </div>
                  <div className="bg-black rounded p-3 overflow-auto max-h-48 font-mono text-xs text-slate-400">
                    <pre>{repair.verification_details.stdout}</pre>
                    {repair.verification_details.stderr && (
                      <pre className="text-red-400 mt-2">{repair.verification_details.stderr}</pre>
                    )}
                  </div>
                </div>
              )}

              <div className="border-t border-slate-700 pt-4 mt-auto">
                <h3 className="text-sm font-medium text-slate-400 mb-2 flex items-center gap-1">
                  <Download className="w-4 h-4" /> Exports
                </h3>
                <div className="flex gap-2 flex-wrap">
                  <button onClick={downloadPatch} className="text-xs bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded transition-colors flex items-center gap-1">
                    <Code className="w-3 h-3" /> .patch
                  </button>
                  <button onClick={downloadReport} className="text-xs bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded transition-colors flex items-center gap-1">
                    <FileText className="w-3 h-3" /> report.md
                  </button>
                  <button onClick={downloadJson} className="text-xs bg-slate-700 hover:bg-slate-600 px-3 py-1.5 rounded transition-colors flex items-center gap-1">
                    <FileText className="w-3 h-3" /> session.json
                  </button>
                </div>
              </div>
            </div>
          )}
          
          {!repair && !diagnosis && (
            <div className="bg-slate-800/50 p-6 rounded-lg border border-slate-700 border-dashed h-full flex items-center justify-center text-slate-500 text-center">
              <div>
                <Bug className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>Select an ingestion method and provide an issue description to begin analysis.</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
