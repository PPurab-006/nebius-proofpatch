-- ==============================================================================
-- Patchworks: Supabase Database Schema Migration 001
-- Description: Persistent GitHub Connections and User Repair History with RLS
-- ==============================================================================

-- 1. GitHub Connections Table
-- Stores user-scoped GitHub OAuth and PAT connections with encrypted tokens at rest.
CREATE TABLE IF NOT EXISTS public.github_connections (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    github_user_id TEXT,
    github_login TEXT NOT NULL,
    avatar_url TEXT,
    html_url TEXT,
    encrypted_access_token TEXT NOT NULL,
    scopes TEXT[] DEFAULT '{}'::TEXT[],
    auth_type TEXT NOT NULL DEFAULT 'oauth' CHECK (auth_type IN ('oauth', 'pat')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_github_connections_login ON public.github_connections(github_login);

-- 2. Repair Sessions Table
-- Stores persistent diagnostic investigations, patches, and verification histories.
CREATE TABLE IF NOT EXISTS public.repair_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    workspace_id TEXT,
    repo_url TEXT NOT NULL,
    issue_description TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'targeted',
    status TEXT NOT NULL DEFAULT 'completed',
    diagnosis JSONB DEFAULT '{}'::JSONB,
    findings JSONB DEFAULT '[]'::JSONB,
    patch TEXT,
    verification_status TEXT DEFAULT 'UNVERIFIED',
    verification_details JSONB DEFAULT '{}'::JSONB,
    pr_url TEXT,
    pr_number INTEGER,
    branch TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_repair_sessions_user_id ON public.repair_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_repair_sessions_created_at ON public.repair_sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_repair_sessions_repo_url ON public.repair_sessions(repo_url);

-- 3. Automatic updated_at timestamp trigger
CREATE OR REPLACE FUNCTION public.handle_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = timezone('utc'::text, now());
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_github_connections_updated_at ON public.github_connections;
CREATE TRIGGER set_github_connections_updated_at
    BEFORE UPDATE ON public.github_connections
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_updated_at();

DROP TRIGGER IF EXISTS set_repair_sessions_updated_at ON public.repair_sessions;
CREATE TRIGGER set_repair_sessions_updated_at
    BEFORE UPDATE ON public.repair_sessions
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_updated_at();

-- 4. Enable Row Level Security (RLS)
ALTER TABLE public.github_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.repair_sessions ENABLE ROW LEVEL SECURITY;

-- 5. Strict User-Scoped Policies for github_connections
-- Users can view only their own GitHub connection metadata (frontend queries)
DROP POLICY IF EXISTS "Users can view own github connection" ON public.github_connections;
CREATE POLICY "Users can view own github connection"
    ON public.github_connections
    FOR SELECT
    USING (auth.uid() = user_id);

-- Users can insert their own connection
DROP POLICY IF EXISTS "Users can insert own github connection" ON public.github_connections;
CREATE POLICY "Users can insert own github connection"
    ON public.github_connections
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Users can update their own connection
DROP POLICY IF EXISTS "Users can update own github connection" ON public.github_connections;
CREATE POLICY "Users can update own github connection"
    ON public.github_connections
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Users can delete their own connection
DROP POLICY IF EXISTS "Users can delete own github connection" ON public.github_connections;
CREATE POLICY "Users can delete own github connection"
    ON public.github_connections
    FOR DELETE
    USING (auth.uid() = user_id);

-- 6. Strict User-Scoped Policies for repair_sessions
-- Users can view only their own repair sessions
DROP POLICY IF EXISTS "Users can view own repair sessions" ON public.repair_sessions;
CREATE POLICY "Users can view own repair sessions"
    ON public.repair_sessions
    FOR SELECT
    USING (auth.uid() = user_id);

-- Users can insert their own repair sessions
DROP POLICY IF EXISTS "Users can insert own repair sessions" ON public.repair_sessions;
CREATE POLICY "Users can insert own repair sessions"
    ON public.repair_sessions
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Users can update their own repair sessions
DROP POLICY IF EXISTS "Users can update own repair sessions" ON public.repair_sessions;
CREATE POLICY "Users can update own repair sessions"
    ON public.repair_sessions
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Users can delete their own repair sessions
DROP POLICY IF EXISTS "Users can delete own repair sessions" ON public.repair_sessions;
CREATE POLICY "Users can delete own repair sessions"
    ON public.repair_sessions
    FOR DELETE
    USING (auth.uid() = user_id);
