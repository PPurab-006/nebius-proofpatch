import { useState } from 'react';
import axios from 'axios';
import { AlertCircle, CheckCircle, Code, Play, Bug, FileText, XCircle } from 'lucide-react';

interface Diagnosis {
  status: string;
  workspace_id?: string;
  reproduction?: any;
  diagnosis: {
    diagnosis: string;
    evidence: string;
    files_to_modify: string[];
    proposed_fix_description: string;
  };
}

interface Repair {
  status: string;
  message?: string;
  patch: string;
  verification_status?: string;
  verification_details?: any;
}

function App() {
  const [repoUrl, setRepoUrl] = useState('');
  const [issueDescription, setIssueDescription] = useState('');
  const [testCommand, setTestCommand] = useState('');
  
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [repair, setRepair] = useState<Repair | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleDiagnose = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await axios.post('/api/diagnose', {
        repo_url: repoUrl,
        issue_description: issueDescription,
        test_command: testCommand || undefined
      });
      setDiagnosis(response.data);
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
      const response = await axios.post('/api/repair', {
        repo_url: repoUrl,
        issue_description: issueDescription,
        diagnosis_context: diagnosis.diagnosis,
        test_command: testCommand || undefined
      });
      setRepair(response.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen p-8 max-w-6xl mx-auto space-y-8">
      <header className="flex items-center space-x-4 border-b border-slate-700 pb-4">
        <Bug className="w-8 h-8 text-indigo-400" />
        <h1 className="text-3xl font-bold">ProofPatch Workbench</h1>
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
              Project Input
            </h2>
            
            <div>
              <label className="block text-sm font-medium text-slate-400 mb-1">Git Repository URL</label>
              <input 
                type="text" 
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                placeholder="https://github.com/user/repo.git"
                className="w-full bg-slate-900 border border-slate-600 rounded p-2 text-slate-200 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 outline-none"
              />
            </div>
            
            <div>
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
              disabled={loading || !repoUrl || !issueDescription}
              className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-700 text-white font-medium py-2 px-4 rounded transition-colors flex items-center justify-center gap-2"
            >
              {loading && !diagnosis ? 'Analyzing...' : 'Diagnose Issue'}
            </button>
          </div>

          {diagnosis && (
            <div className="bg-slate-800 p-6 rounded-lg border border-slate-700 space-y-4">
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
                  <p className="mt-1 italic border-l-2 border-slate-600 pl-3">{diagnosis.diagnosis.evidence}</p>
                </div>
                <div>
                  <strong className="block text-slate-400 text-sm">Files to modify:</strong>
                  <div className="flex flex-wrap gap-2 mt-1">
                    {diagnosis.diagnosis.files_to_modify.map((f, i) => (
                      <span key={i} className="bg-slate-900 px-2 py-1 rounded text-xs font-mono text-indigo-300">{f}</span>
                    ))}
                  </div>
                </div>
                
                <button 
                  onClick={handleRepair}
                  disabled={loading}
                  className="w-full mt-4 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-700 text-white font-medium py-2 px-4 rounded transition-colors flex items-center justify-center gap-2"
                >
                  {loading && diagnosis && !repair ? 'Generating Repair...' : 'Propose & Verify Repair'}
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="space-y-6">
          {repair && (
            <div className="bg-slate-800 p-6 rounded-lg border border-slate-700 space-y-4 h-full flex flex-col">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-semibold flex items-center gap-2">
                  <Code className="w-5 h-5 text-slate-400" /> 
                  Proposed Patch
                </h2>
                <div className={`px-3 py-1 rounded-full text-sm font-bold flex items-center gap-1 ${
                  repair.verification_status === 'FIX VERIFIED' ? 'bg-emerald-900/50 text-emerald-400 border border-emerald-500' :
                  repair.status === 'error' ? 'bg-red-900/50 text-red-400 border border-red-500' :
                  repair.verification_status === 'FIX FAILED' ? 'bg-red-900/50 text-red-400 border border-red-500' :
                  'bg-yellow-900/50 text-yellow-400 border border-yellow-500'
                }`}>
                  {repair.verification_status === 'FIX VERIFIED' ? <CheckCircle className="w-4 h-4" /> : 
                   repair.status === 'error' ? <XCircle className="w-4 h-4" /> : 
                   <AlertCircle className="w-4 h-4" />}
                  {repair.status === 'error' ? 'APPLY FAILED' : (repair.verification_status || 'UNVERIFIED')}
                </div>
              </div>

              {repair.status === 'error' && repair.message && (
                <div className="bg-red-900/30 border border-red-800 text-red-300 p-3 rounded text-sm mb-2">
                  {repair.message}
                </div>
              )}

              <div className="flex-1 bg-slate-900 rounded p-4 overflow-auto font-mono text-sm border border-slate-700">
                <pre className="text-slate-300">{repair.patch}</pre>
              </div>

              {repair.verification_details && (
                <div className="mt-4">
                  <h3 className="text-sm font-medium text-slate-400 mb-2 flex items-center gap-1">
                    <Play className="w-4 h-4" /> Test Output
                  </h3>
                  <div className="bg-black rounded p-3 overflow-auto max-h-48 font-mono text-xs text-slate-400">
                    <pre>{repair.verification_details.stdout}</pre>
                    {repair.verification_details.stderr && (
                      <pre className="text-red-400 mt-2">{repair.verification_details.stderr}</pre>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
          
          {!repair && !diagnosis && (
            <div className="bg-slate-800/50 p-6 rounded-lg border border-slate-700 border-dashed h-full flex items-center justify-center text-slate-500 text-center">
              <div>
                <Bug className="w-12 h-12 mx-auto mb-4 opacity-50" />
                <p>Provide a repository and issue description to begin analysis.</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
