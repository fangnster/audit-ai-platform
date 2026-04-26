--
-- PostgreSQL database dump
--

\restrict beWmCia2cFgeetSzqD4s84vno41sIKAJlvhuxC7aVIhErhBYwNSGLOyFV0HPGyh

-- Dumped from database version 16.13 (Debian 16.13-1.pgdg12+1)
-- Dumped by pg_dump version 16.13 (Debian 16.13-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: agenttaskstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agenttaskstatus AS ENUM (
    'queued',
    'processing',
    'completed',
    'failed',
    'cancelled'
);


--
-- Name: agenttasktype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.agenttasktype AS ENUM (
    'draft_generate',
    'rewrite_section',
    'fact_extract',
    'fact_fix',
    'rfi_generate'
);


--
-- Name: casememberrole; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.casememberrole AS ENUM (
    'lead_lawyer',
    'associate',
    'client'
);


--
-- Name: casestatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.casestatus AS ENUM (
    'intake',
    'fact_extraction',
    'drafting',
    'review',
    'submitted'
);


--
-- Name: casetype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.casetype AS ENUM (
    'EB1A',
    'EB1B',
    'NIW',
    'O1A',
    'EB2',
    'EB3',
    'H1B'
);


--
-- Name: doctype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.doctype AS ENUM (
    'evidence',
    'award',
    'patent',
    'publication',
    'citation',
    'employment',
    'media',
    'membership',
    'reference_letter',
    'petition_letter',
    'rfi',
    'other',
    'rfi_response',
    'client_upload'
);


--
-- Name: factstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.factstatus AS ENUM (
    'extracted',
    'lawyer_approved',
    'client_confirmed',
    'disputed'
);


--
-- Name: knowledgetype; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.knowledgetype AS ENUM (
    'prompt_template',
    'document_template',
    'sample_document'
);


--
-- Name: memberrole; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.memberrole AS ENUM (
    'firm_admin',
    'lead_lawyer',
    'associate'
);


--
-- Name: orgplan; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.orgplan AS ENUM (
    'free',
    'pro',
    'enterprise'
);


--
-- Name: parsestatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.parsestatus AS ENUM (
    'pending',
    'parsing',
    'parsed',
    'failed'
);


--
-- Name: sectionstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.sectionstatus AS ENUM (
    'draft',
    'approved',
    'locked'
);


--
-- Name: uploaderrole; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.uploaderrole AS ENUM (
    'lawyer',
    'client',
    'agent'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    task_type character varying(50) NOT NULL,
    input_params jsonb DEFAULT '{}'::jsonb,
    output_result jsonb DEFAULT '{}'::jsonb,
    status public.agenttaskstatus DEFAULT 'queued'::public.agenttaskstatus,
    priority integer DEFAULT 3,
    llm_model character varying(100) DEFAULT 'claude'::character varying,
    token_usage integer DEFAULT 0,
    latency_ms integer DEFAULT 0,
    error_message character varying(1000),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: case_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_members (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role public.casememberrole NOT NULL,
    permissions jsonb DEFAULT '{}'::jsonb
);


--
-- Name: cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cases (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    title character varying(500) NOT NULL,
    case_type public.casetype NOT NULL,
    status public.casestatus DEFAULT 'intake'::public.casestatus,
    lead_lawyer_id uuid NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_deleted boolean DEFAULT false NOT NULL
);


--
-- Name: client_tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.client_tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    task_type character varying(50) NOT NULL,
    created_by_role character varying(20) NOT NULL,
    created_by_id uuid NOT NULL,
    approved_by_id uuid,
    title character varying(500) NOT NULL,
    description text DEFAULT ''::text,
    legal_rationale text DEFAULT ''::text,
    status character varying(50) DEFAULT 'pending'::character varying,
    due_date date,
    attachments jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_deleted boolean DEFAULT false NOT NULL
);


--
-- Name: document_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_categories (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid,
    name character varying(100) NOT NULL,
    display_name character varying(255) NOT NULL,
    icon character varying(100) DEFAULT 'file'::character varying,
    sort_order integer DEFAULT 0,
    is_system boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: document_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_versions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    document_id uuid NOT NULL,
    version_number integer NOT NULL,
    content_snapshot text,
    editor_role character varying(50) NOT NULL,
    editor_id uuid NOT NULL,
    change_summary character varying(500),
    diff_data jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documents (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    category_id uuid,
    filename character varying(500) NOT NULL,
    original_filename character varying(500) NOT NULL,
    doc_type public.doctype NOT NULL,
    storage_path character varying(1000) NOT NULL,
    file_size integer DEFAULT 0,
    mime_type character varying(200) DEFAULT 'application/octet-stream'::character varying,
    uploader_id uuid NOT NULL,
    uploader_role public.uploaderrole NOT NULL,
    parse_status public.parsestatus,
    extracted_metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_deleted boolean DEFAULT false NOT NULL
);


--
-- Name: draft_revisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.draft_revisions (
    id uuid NOT NULL,
    section_id uuid NOT NULL,
    case_id uuid NOT NULL,
    revision_number integer NOT NULL,
    section_title character varying(500) NOT NULL,
    content_snapshot text DEFAULT ''::text NOT NULL,
    editor_role character varying(50) NOT NULL,
    editor_id uuid,
    change_summary character varying(500) DEFAULT ''::character varying NOT NULL,
    revision_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: draft_sections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.draft_sections (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    document_id uuid,
    section_order integer NOT NULL,
    section_title character varying(500) NOT NULL,
    content text DEFAULT ''::text,
    criterion character varying(50),
    status public.sectionstatus,
    pending_slots jsonb DEFAULT '{}'::jsonb,
    version character varying(10) DEFAULT 'a'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_deleted boolean DEFAULT false NOT NULL
);


--
-- Name: fact_collaborations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fact_collaborations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    fact_id uuid NOT NULL,
    user_id uuid NOT NULL,
    action character varying(50) NOT NULL,
    comment text,
    before_value jsonb DEFAULT '{}'::jsonb,
    after_value jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: facts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    case_id uuid NOT NULL,
    source_document_id uuid,
    category character varying(100) NOT NULL,
    content text NOT NULL,
    structured_data jsonb DEFAULT '{}'::jsonb,
    status public.factstatus,
    confidence_score double precision DEFAULT 1.0,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_deleted boolean DEFAULT false NOT NULL
);


--
-- Name: knowledge_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_items (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    user_id uuid NOT NULL,
    title character varying(500) NOT NULL,
    content text DEFAULT ''::text NOT NULL,
    item_type character varying(50) NOT NULL,
    tags jsonb DEFAULT '[]'::jsonb,
    is_deleted boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: org_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.org_members (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    user_id uuid NOT NULL,
    team_id uuid,
    role public.memberrole NOT NULL,
    permissions jsonb DEFAULT '{}'::jsonb,
    joined_at timestamp with time zone DEFAULT now()
);


--
-- Name: organizations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organizations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(255) NOT NULL,
    slug character varying(100) NOT NULL,
    settings jsonb DEFAULT '{}'::jsonb,
    plan public.orgplan DEFAULT 'free'::public.orgplan,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: teams; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.teams (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    org_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: user_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    case_id uuid NOT NULL,
    page_context character varying(500) DEFAULT ''::character varying,
    draft_state jsonb DEFAULT '{}'::jsonb,
    ui_state jsonb DEFAULT '{}'::jsonb,
    last_active_at timestamp with time zone DEFAULT now(),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    is_active boolean DEFAULT true,
    profile jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: agent_tasks agent_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tasks
    ADD CONSTRAINT agent_tasks_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: case_members case_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_members
    ADD CONSTRAINT case_members_pkey PRIMARY KEY (id);


--
-- Name: cases cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_pkey PRIMARY KEY (id);


--
-- Name: client_tasks client_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.client_tasks
    ADD CONSTRAINT client_tasks_pkey PRIMARY KEY (id);


--
-- Name: document_categories document_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_categories
    ADD CONSTRAINT document_categories_pkey PRIMARY KEY (id);


--
-- Name: document_versions document_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_pkey PRIMARY KEY (id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: draft_revisions draft_revisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft_revisions
    ADD CONSTRAINT draft_revisions_pkey PRIMARY KEY (id);


--
-- Name: draft_sections draft_sections_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft_sections
    ADD CONSTRAINT draft_sections_pkey PRIMARY KEY (id);


--
-- Name: fact_collaborations fact_collaborations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_collaborations
    ADD CONSTRAINT fact_collaborations_pkey PRIMARY KEY (id);


--
-- Name: facts facts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT facts_pkey PRIMARY KEY (id);


--
-- Name: knowledge_items knowledge_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_pkey PRIMARY KEY (id);


--
-- Name: org_members org_members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_members
    ADD CONSTRAINT org_members_pkey PRIMARY KEY (id);


--
-- Name: organizations organizations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);


--
-- Name: organizations organizations_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organizations
    ADD CONSTRAINT organizations_slug_key UNIQUE (slug);


--
-- Name: teams teams_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT teams_pkey PRIMARY KEY (id);


--
-- Name: user_sessions user_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_pkey PRIMARY KEY (id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: idx_agent_tasks_case_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_tasks_case_created ON public.agent_tasks USING btree (case_id, created_at DESC);


--
-- Name: idx_agent_tasks_case_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_agent_tasks_case_updated ON public.agent_tasks USING btree (case_id, updated_at DESC);


--
-- Name: idx_case_members_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_members_case ON public.case_members USING btree (case_id);


--
-- Name: idx_case_members_user_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_case_members_user_case ON public.case_members USING btree (user_id, case_id);


--
-- Name: idx_cases_deleted_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_deleted_created ON public.cases USING btree (is_deleted, created_at DESC);


--
-- Name: idx_cases_deleted_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_deleted_updated ON public.cases USING btree (is_deleted, updated_at DESC);


--
-- Name: idx_cases_lawyer; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_lawyer ON public.cases USING btree (lead_lawyer_id, status);


--
-- Name: idx_cases_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cases_org ON public.cases USING btree (org_id);


--
-- Name: idx_client_tasks_case_deleted; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_client_tasks_case_deleted ON public.client_tasks USING btree (case_id, is_deleted);


--
-- Name: idx_client_tasks_case_deleted_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_client_tasks_case_deleted_updated ON public.client_tasks USING btree (case_id, is_deleted, updated_at DESC);


--
-- Name: idx_doc_versions_doc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_doc_versions_doc ON public.document_versions USING btree (document_id, version_number);


--
-- Name: idx_documents_case_deleted_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_case_deleted_created ON public.documents USING btree (case_id, is_deleted, created_at DESC);


--
-- Name: idx_documents_case_deleted_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_case_deleted_updated ON public.documents USING btree (case_id, is_deleted, updated_at DESC);


--
-- Name: idx_documents_case_deleted_type_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_case_deleted_type_created ON public.documents USING btree (case_id, is_deleted, doc_type, created_at DESC);


--
-- Name: idx_documents_case_deleted_uploader_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_documents_case_deleted_uploader_created ON public.documents USING btree (case_id, is_deleted, uploader_role, created_at DESC);


--
-- Name: idx_draft_revisions_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_draft_revisions_case ON public.draft_revisions USING btree (case_id);


--
-- Name: idx_draft_revisions_case_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_draft_revisions_case_created ON public.draft_revisions USING btree (case_id, created_at DESC);


--
-- Name: idx_draft_revisions_section; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_draft_revisions_section ON public.draft_revisions USING btree (section_id, revision_number);


--
-- Name: idx_draft_sections_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_draft_sections_case ON public.draft_sections USING btree (case_id, section_order);


--
-- Name: idx_draft_sections_case_deleted_version_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_draft_sections_case_deleted_version_order ON public.draft_sections USING btree (case_id, is_deleted, version, section_order);


--
-- Name: idx_draft_sections_case_deleted_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_draft_sections_case_deleted_updated ON public.draft_sections USING btree (case_id, is_deleted, updated_at DESC);


--
-- Name: idx_fact_collaborations_fact; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_fact_collaborations_fact ON public.fact_collaborations USING btree (fact_id);


--
-- Name: idx_facts_case_deleted_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_facts_case_deleted_created ON public.facts USING btree (case_id, is_deleted, created_at DESC);


--
-- Name: idx_facts_case_deleted_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_facts_case_deleted_updated ON public.facts USING btree (case_id, is_deleted, updated_at DESC);


--
-- Name: idx_facts_case_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_facts_case_status ON public.facts USING btree (case_id, status);


--
-- Name: idx_facts_source_document_deleted_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_facts_source_document_deleted_created ON public.facts USING btree (source_document_id, is_deleted, created_at DESC);


--
-- Name: idx_knowledge_deleted; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_deleted ON public.knowledge_items USING btree (is_deleted);


--
-- Name: idx_knowledge_items_org_deleted_type_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_items_org_deleted_type_updated ON public.knowledge_items USING btree (org_id, is_deleted, item_type, updated_at DESC);


--
-- Name: idx_knowledge_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_org ON public.knowledge_items USING btree (org_id);


--
-- Name: idx_knowledge_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_knowledge_user ON public.knowledge_items USING btree (user_id);


--
-- Name: idx_org_members_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_members_org ON public.org_members USING btree (org_id);


--
-- Name: idx_org_members_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_org_members_user ON public.org_members USING btree (user_id);


--
-- Name: idx_teams_org; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_teams_org ON public.teams USING btree (org_id);


--
-- Name: idx_user_sessions_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_sessions_user ON public.user_sessions USING btree (user_id, case_id);


--
-- Name: agent_tasks agent_tasks_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_tasks
    ADD CONSTRAINT agent_tasks_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: case_members case_members_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_members
    ADD CONSTRAINT case_members_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: case_members case_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_members
    ADD CONSTRAINT case_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: cases cases_lead_lawyer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_lead_lawyer_id_fkey FOREIGN KEY (lead_lawyer_id) REFERENCES public.users(id);


--
-- Name: cases cases_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: client_tasks client_tasks_approved_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.client_tasks
    ADD CONSTRAINT client_tasks_approved_by_id_fkey FOREIGN KEY (approved_by_id) REFERENCES public.users(id);


--
-- Name: client_tasks client_tasks_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.client_tasks
    ADD CONSTRAINT client_tasks_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: client_tasks client_tasks_created_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.client_tasks
    ADD CONSTRAINT client_tasks_created_by_id_fkey FOREIGN KEY (created_by_id) REFERENCES public.users(id);


--
-- Name: document_categories document_categories_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_categories
    ADD CONSTRAINT document_categories_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: document_versions document_versions_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE;


--
-- Name: document_versions document_versions_editor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_editor_id_fkey FOREIGN KEY (editor_id) REFERENCES public.users(id);


--
-- Name: documents documents_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: documents documents_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.document_categories(id) ON DELETE SET NULL;


--
-- Name: documents documents_uploader_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_uploader_id_fkey FOREIGN KEY (uploader_id) REFERENCES public.users(id);


--
-- Name: draft_revisions draft_revisions_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft_revisions
    ADD CONSTRAINT draft_revisions_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: draft_revisions draft_revisions_editor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft_revisions
    ADD CONSTRAINT draft_revisions_editor_id_fkey FOREIGN KEY (editor_id) REFERENCES public.users(id);


--
-- Name: draft_revisions draft_revisions_section_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft_revisions
    ADD CONSTRAINT draft_revisions_section_id_fkey FOREIGN KEY (section_id) REFERENCES public.draft_sections(id) ON DELETE CASCADE;


--
-- Name: draft_sections draft_sections_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft_sections
    ADD CONSTRAINT draft_sections_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: draft_sections draft_sections_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.draft_sections
    ADD CONSTRAINT draft_sections_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE SET NULL;


--
-- Name: fact_collaborations fact_collaborations_fact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_collaborations
    ADD CONSTRAINT fact_collaborations_fact_id_fkey FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE CASCADE;


--
-- Name: fact_collaborations fact_collaborations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_collaborations
    ADD CONSTRAINT fact_collaborations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: facts facts_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT facts_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: facts facts_source_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT facts_source_document_id_fkey FOREIGN KEY (source_document_id) REFERENCES public.documents(id) ON DELETE SET NULL;


--
-- Name: knowledge_items knowledge_items_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: knowledge_items knowledge_items_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_items
    ADD CONSTRAINT knowledge_items_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: org_members org_members_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_members
    ADD CONSTRAINT org_members_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: org_members org_members_team_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_members
    ADD CONSTRAINT org_members_team_id_fkey FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE SET NULL;


--
-- Name: org_members org_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.org_members
    ADD CONSTRAINT org_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: teams teams_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT teams_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organizations(id) ON DELETE CASCADE;


--
-- Name: user_sessions user_sessions_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id) ON DELETE CASCADE;


--
-- Name: user_sessions user_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_sessions
    ADD CONSTRAINT user_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict beWmCia2cFgeetSzqD4s84vno41sIKAJlvhuxC7aVIhErhBYwNSGLOyFV0HPGyh
