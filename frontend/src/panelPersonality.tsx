import React, { useState, useEffect, useRef } from 'react';

export interface IdleGreeting {
  title: string;
  subtitle: string;
}

export const IDLE_GREETINGS: IdleGreeting[] = [
  {
    title: "Back at it again?",
    subtitle: "Select a repository, upload an archive, or load a benchmark to begin.",
  },
  {
    title: "What are we fixing today?",
    subtitle: "Supply a codebase and an issue to start empirical diagnosis.",
  },
  {
    title: "Ready when you are.",
    subtitle: "Workspace standing by for repository ingestion.",
  },
  {
    title: "Another day, another bug.",
    subtitle: "Configure your repository on the left to start the repair engine.",
  },
  {
    title: "Let's see what needs fixing.",
    subtitle: "Isolated sandbox ready for code analysis and patch verification.",
  },
  {
    title: "The code isn't going to debug itself.",
    subtitle: "Provide a repository target to initiate investigation.",
  },
  {
    title: "Quiet in the workshop.",
    subtitle: "Select a codebase to begin autonomous inspection.",
  },
];

export function getRandomIdleGreeting(currentTitle?: string): IdleGreeting {
  const candidates = currentTitle
    ? IDLE_GREETINGS.filter((g) => g.title !== currentTitle)
    : IDLE_GREETINGS;
  const index = Math.floor(Math.random() * candidates.length);
  return candidates[index];
}

export type ProcessingStage =
  | 'ingestion'
  | 'inspection'
  | 'diagnosis'
  | 'patch_generation'
  | 'applying'
  | 'test_execution'
  | 'verification'
  | 'rollback'
  | 'general';

export const STAGE_PHRASES: Record<ProcessingStage, string[]> = {
  ingestion: [
    "Getting acquainted with the codebase...",
    "Untangling the project directory...",
    "Unpacking the repository artifacts...",
    "Surveying the architectural landscape...",
    "Reading the manifest with mild suspicion...",
    "Scanning for architectural surprises...",
    "Greeting the repository warmly...",
    "Rearranging the digital furniture...",
    "Consulting the bug-shaped shadows...",
  ],
  inspection: [
    "Poking around the suspicious bits...",
    "Auditing the file hierarchy...",
    "Cataloging the dependencies...",
    "Interrogating the semicolons...",
    "Checking whether that was intentional...",
    "Giving the suspicious bits a second look...",
    "Mapping out the blast radius...",
    "Counting the edge cases...",
    "Questioning life choices...",
  ],
  diagnosis: [
    "Pondering the root cause...",
    "Interrogating the stack trace...",
    "Asking the stack trace nicely...",
    "Ruminating on the runtime anomalies...",
    "Pondering the cosmic significance of a missing bracket...",
    "Discombobulating the problem...",
    "Having a long think about this...",
    "Wondering who wrote this function...",
    "Contemplating a particularly odd variable...",
    "Questioning life choices...",
  ],
  patch_generation: [
    "Negotiating with the diff...",
    "Synthesizing a surgical correction...",
    "Carefully aligning the indentation...",
    "Drafting a rather precise amendment...",
    "Mumbling to the code generator...",
    "Deliberating on the cleanest change...",
    "Whispering corrections into the syntax tree...",
    "Untangling a rather peculiar knot...",
    "Mumbling to the code...",
  ],
  applying: [
    "Carefully rearranging the code...",
    "Applying the amendments to disk...",
    "Threading the needle on line numbers...",
    "Inserting the fix without disturbing the surroundings...",
    "Updating the workspace files...",
    "Tidying up the patched files...",
    "Rearranging the digital furniture...",
  ],
  test_execution: [
    "Persuading the tests to cooperate...",
    "Asking the test runner for its opinion...",
    "Awaiting the verdict of the test suite...",
    "Asking the tests to substantiate their claims...",
    "Holding our breath while tests execute...",
    "Listening closely to standard output...",
    "Consulting the department of peculiar exceptions...",
    "Questioning life choices...",
  ],
  verification: [
    "Checking the bolts twice...",
    "Cross-checking the suspicious bits...",
    "Certifying the patch with exit code zero...",
    "Ensuring no new chaos was introduced...",
    "Examining the evidence with undue seriousness...",
    "Double-checking the empirical proof...",
    "Having a long think about this...",
  ],
  rollback: [
    "Putting things back where they belong...",
    "Restoring the pre-repair checkpoint...",
    "Undoing the recent excitement...",
    "Returning the workspace to safety...",
    "Politely wiping the slate clean...",
  ],
  general: [
    "Mumbling to the code...",
    "Questioning life choices...",
    "Pondering the peculiarities...",
    "Discombobulating the problem...",
    "Consulting the bug-shaped shadows...",
    "Rearranging the digital furniture...",
    "Contemplating a particularly odd variable...",
    "Having a long think about this...",
    "Examining the evidence with undue seriousness...",
    "Counting the edge cases...",
  ],
};

export function determineProcessingStage(
  pipelineStep: number,
  loadingMessage: string,
  batchRepairing?: boolean
): { stage: ProcessingStage; technicalStatus: string } {
  const msg = (loadingMessage || '').toLowerCase();

  if (msg.includes('rollback') || msg.includes('reset')) {
    return {
      stage: 'rollback',
      technicalStatus: loadingMessage || 'Restoring workspace checkpoint',
    };
  }

  if (
    msg.includes('cloning') ||
    msg.includes('preparing') ||
    msg.includes('archive') ||
    msg.includes('upload') ||
    msg.includes('ingest') ||
    pipelineStep === 1
  ) {
    return {
      stage: 'ingestion',
      technicalStatus: loadingMessage || 'Repository ingestion in progress',
    };
  }

  if (msg.includes('inspect') || msg.includes('profile')) {
    return {
      stage: 'inspection',
      technicalStatus: loadingMessage || 'Inspecting repository architecture',
    };
  }

  if (msg.includes('reproduc') || (msg.includes('test') && !msg.includes('verif') && pipelineStep <= 2)) {
    return {
      stage: 'test_execution',
      technicalStatus: loadingMessage || 'Executing reproduction tests',
    };
  }

  if (msg.includes('diagnos') || msg.includes('investigat') || pipelineStep === 2) {
    return {
      stage: 'diagnosis',
      technicalStatus: loadingMessage || 'Diagnosis in progress',
    };
  }

  if (msg.includes('synthesiz') || pipelineStep === 3) {
    return {
      stage: 'patch_generation',
      technicalStatus: loadingMessage || 'Synthesizing targeted patch',
    };
  }

  if (msg.includes('applying') || pipelineStep === 4) {
    return {
      stage: 'applying',
      technicalStatus: loadingMessage || 'Applying changes to workspace',
    };
  }

  if (pipelineStep === 5 || msg.includes('verif')) {
    if (msg.includes('test')) {
      return {
        stage: 'test_execution',
        technicalStatus: loadingMessage || 'Running verification tests',
      };
    }
    return {
      stage: 'verification',
      technicalStatus: loadingMessage || 'Verifying repair in sandbox',
    };
  }

  if (batchRepairing || msg.includes('batch')) {
    return {
      stage: 'patch_generation',
      technicalStatus: loadingMessage || 'Batch repair in progress',
    };
  }

  return {
    stage: 'general',
    technicalStatus: loadingMessage || 'Operation in progress',
  };
}

export function useMutteringPhrase(active: boolean, stage: ProcessingStage) {
  const getPool = (s: ProcessingStage) => STAGE_PHRASES[s] || STAGE_PHRASES.general;

  const [phrase, setPhrase] = useState(() => {
    const pool = getPool(stage);
    return pool[Math.floor(Math.random() * pool.length)];
  });
  const [fading, setFading] = useState(false);

  const stageRef = useRef(stage);
  const phraseRef = useRef(phrase);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fadeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    stageRef.current = stage;
  }, [stage]);

  useEffect(() => {
    phraseRef.current = phrase;
  }, [phrase]);

  useEffect(() => {
    if (!active) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      if (fadeTimeoutRef.current) {
        clearTimeout(fadeTimeoutRef.current);
        fadeTimeoutRef.current = null;
      }
      setFading(false);
      return;
    }

    // Set initial phrase for the new active operation if current phrase is not in pool
    const pool = getPool(stageRef.current);
    if (!pool.includes(phraseRef.current)) {
      const candidates = pool.filter((p) => p !== phraseRef.current);
      const chosen = candidates[Math.floor(Math.random() * candidates.length)] || pool[0];
      setPhrase(chosen);
      phraseRef.current = chosen;
    }

    const checkReducedMotion = () =>
      typeof window !== 'undefined' &&
      window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    intervalRef.current = setInterval(() => {
      const currentPool = getPool(stageRef.current);
      const candidates = currentPool.filter((p) => p !== phraseRef.current);
      const nextPhrase =
        candidates[Math.floor(Math.random() * candidates.length)] || currentPool[0];

      if (checkReducedMotion()) {
        setPhrase(nextPhrase);
      } else {
        setFading(true);
        fadeTimeoutRef.current = setTimeout(() => {
          setPhrase(nextPhrase);
          setFading(false);
        }, 200);
      }
    }, 4000);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      if (fadeTimeoutRef.current) {
        clearTimeout(fadeTimeoutRef.current);
        fadeTimeoutRef.current = null;
      }
    };
  }, [active]);

  return { phrase, fading };
}

export const ProcessingRing: React.FC<{ size?: 'normal' | 'large' }> = ({ size = 'normal' }) => {
  const isLarge = size === 'large';
  return (
    <div
      className={`relative shrink-0 flex items-center justify-center ${
        isLarge ? 'w-8 h-8' : 'w-4 h-4'
      }`}
      aria-hidden="true"
    >
      <svg
        className={`${isLarge ? 'w-8 h-8' : 'w-4 h-4'} -rotate-90 motion-reduce:rotate-0`}
        viewBox="0 0 24 24"
      >
        <circle
          cx="12"
          cy="12"
          r="9"
          stroke="#242820"
          strokeWidth="2.5"
          fill="none"
        />
        <circle
          cx="12"
          cy="12"
          r="9"
          stroke="#B7FF3C"
          strokeWidth="2.5"
          strokeDasharray="56.5"
          strokeDashoffset="38"
          strokeLinecap="round"
          fill="none"
          className="origin-center animate-spin motion-reduce:animate-none"
          style={{ animationDuration: '1.2s' }}
        />
      </svg>
    </div>
  );
};

export const IdleWelcomeCard: React.FC<{ greeting: IdleGreeting }> = ({ greeting }) => (
  <div className="h-full border border-[#242820] bg-[#0B0D0A] rounded-lg p-8 flex flex-col items-center justify-center text-center space-y-3 engineering-grid min-h-[460px]">
    <div className="relative group mb-1">
      <img
        src="/patchworks-squircle.png"
        alt="Patchworks"
        className="w-12 h-12 rounded-xl object-contain opacity-75 drop-shadow-[0_0_15px_rgba(183,255,60,0.15)]"
      />
    </div>
    <h3 className="text-base font-mono font-bold text-[#F4F5F0] tracking-tight">
      {greeting.title}
    </h3>
    <p className="text-xs font-mono text-[#969B90] max-w-sm leading-relaxed">
      {greeting.subtitle}
    </p>
  </div>
);

export const ActiveProcessingCard: React.FC<{
  phrase: string;
  fading: boolean;
  technicalStatus: string;
}> = ({ phrase, fading, technicalStatus }) => (
  <div className="h-full border border-[#242820] bg-[#0B0D0A] rounded-lg p-8 flex flex-col items-center justify-center text-center space-y-4 engineering-grid min-h-[460px]">
    <div className="p-3 bg-[#11140F] border border-[#B7FF3C]/30 rounded-full glow-lime-sm">
      <ProcessingRing size="large" />
    </div>
    <div className="space-y-1.5 max-w-md">
      <div
        className={`text-sm font-mono font-bold text-[#B7FF3C] transition-opacity duration-200 min-h-[1.4rem] flex items-center justify-center ${
          fading ? 'opacity-0' : 'opacity-100'
        }`}
      >
        {phrase}
      </div>
      <div className="text-xs font-mono text-[#969B90] tracking-wide">
        {technicalStatus}
      </div>
    </div>
  </div>
);

export const ActiveProcessingBanner: React.FC<{
  phrase: string;
  fading: boolean;
  technicalStatus: string;
}> = ({ phrase, fading, technicalStatus }) => (
  <div className="bg-[#11140F] border border-[#B7FF3C]/35 rounded-lg p-3 flex items-center gap-3 glow-lime-sm mb-4">
    <ProcessingRing size="normal" />
    <div className="space-y-0.5 overflow-hidden">
      <div
        className={`text-xs font-mono font-bold text-[#B7FF3C] transition-opacity duration-200 min-h-[1.1rem] flex items-center ${
          fading ? 'opacity-0' : 'opacity-100'
        }`}
      >
        {phrase}
      </div>
      <div className="text-[11px] font-mono text-[#969B90] truncate">
        {technicalStatus}
      </div>
    </div>
  </div>
);
