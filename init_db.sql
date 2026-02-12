-- init_db.sql
-- Auto-generated from current database schema (public) via pg_dump --schema-only
-- Includes tables, sequences, defaults, constraints, indexes, views, functions (if any)
-- NOTE: This file may contain non-idempotent DDL (CREATE TABLE, CREATE SEQUENCE, etc.).
-- The deploy-time init script (init.py) should execute it statement-by-statement and skip "already exists" errors.

--
-- PostgreSQL database dump
--

\restrict SI5hJyXLpUejae5Eoxl6PLSus3ZQdEc2zn2tIraijcjAcnQJbn0hExHTinfNX7s

-- Dumped from database version 16.11 (Debian 16.11-1.pgdg13+1)
-- Dumped by pg_dump version 16.11 (Debian 16.11-1.pgdg13+1)

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

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: user_visit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_visit_log (
    id integer NOT NULL,
    ip character varying(64) NOT NULL,
    user_agent character varying(512) NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: user_visit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_visit_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_visit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_visit_log_id_seq OWNED BY public.user_visit_log.id;


--
-- Name: user_visit_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_visit_log ALTER COLUMN id SET DEFAULT nextval('public.user_visit_log_id_seq'::regclass);


--
-- Name: user_visit_log user_visit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_visit_log
    ADD CONSTRAINT user_visit_log_pkey PRIMARY KEY (id);


--
-- PostgreSQL database dump complete
--

\unrestrict SI5hJyXLpUejae5Eoxl6PLSus3ZQdEc2zn2tIraijcjAcnQJbn0hExHTinfNX7s

