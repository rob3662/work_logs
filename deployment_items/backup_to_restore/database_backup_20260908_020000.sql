--
-- PostgreSQL database dump
--

\restrict a8i6YZYEUrtJuq0StmjPqCo6hBVtjshzzXePlYeN0Oc8j1QDNwwicPyAFDAUC7y

-- Dumped from database version 16.13 (Debian 16.13-1.pgdg13+1)
-- Dumped by pg_dump version 16.14

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
-- Name: blocked_registration_prefixes; Type: TABLE; Schema: public; Owner: work_logs_user
--

CREATE TABLE public.blocked_registration_prefixes (
    id integer NOT NULL,
    prefix text NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.blocked_registration_prefixes OWNER TO work_logs_user;

--
-- Name: blocked_registration_prefixes_id_seq; Type: SEQUENCE; Schema: public; Owner: work_logs_user
--

CREATE SEQUENCE public.blocked_registration_prefixes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.blocked_registration_prefixes_id_seq OWNER TO work_logs_user;

--
-- Name: blocked_registration_prefixes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: work_logs_user
--

ALTER SEQUENCE public.blocked_registration_prefixes_id_seq OWNED BY public.blocked_registration_prefixes.id;


--
-- Name: security_events; Type: TABLE; Schema: public; Owner: work_logs_user
--

CREATE TABLE public.security_events (
    id integer NOT NULL,
    event_type text NOT NULL,
    user_id integer,
    ip_address text,
    user_agent text,
    details jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.security_events OWNER TO work_logs_user;

--
-- Name: security_events_id_seq; Type: SEQUENCE; Schema: public; Owner: work_logs_user
--

CREATE SEQUENCE public.security_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.security_events_id_seq OWNER TO work_logs_user;

--
-- Name: security_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: work_logs_user
--

ALTER SEQUENCE public.security_events_id_seq OWNED BY public.security_events.id;


--
-- Name: tenant_invites; Type: TABLE; Schema: public; Owner: work_logs_user
--

CREATE TABLE public.tenant_invites (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    email text NOT NULL,
    token_hash text NOT NULL,
    invited_by_user_id integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamp without time zone NOT NULL,
    accepted_at timestamp without time zone,
    revoked_at timestamp without time zone
);


ALTER TABLE public.tenant_invites OWNER TO work_logs_user;

--
-- Name: tenant_invites_id_seq; Type: SEQUENCE; Schema: public; Owner: work_logs_user
--

CREATE SEQUENCE public.tenant_invites_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tenant_invites_id_seq OWNER TO work_logs_user;

--
-- Name: tenant_invites_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: work_logs_user
--

ALTER SEQUENCE public.tenant_invites_id_seq OWNED BY public.tenant_invites.id;


--
-- Name: tenants; Type: TABLE; Schema: public; Owner: work_logs_user
--

CREATE TABLE public.tenants (
    id integer NOT NULL,
    name text DEFAULT 'Default'::text NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    owner_user_id integer
);


ALTER TABLE public.tenants OWNER TO work_logs_user;

--
-- Name: tenants_id_seq; Type: SEQUENCE; Schema: public; Owner: work_logs_user
--

CREATE SEQUENCE public.tenants_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tenants_id_seq OWNER TO work_logs_user;

--
-- Name: tenants_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: work_logs_user
--

ALTER SEQUENCE public.tenants_id_seq OWNED BY public.tenants.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: work_logs_user
--

CREATE TABLE public.users (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    username text NOT NULL,
    email text NOT NULL,
    password_hash text NOT NULL,
    is_admin boolean DEFAULT false,
    email_verified boolean DEFAULT false,
    verification_token text,
    personal_email text,
    personal_email_verified boolean DEFAULT false,
    personal_email_verification_token text,
    password_reset_token text,
    password_reset_expires timestamp without time zone,
    stripe_customer_id text,
    last_login timestamp without time zone,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    is_site_admin boolean DEFAULT false
);


ALTER TABLE public.users OWNER TO work_logs_user;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: work_logs_user
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO work_logs_user;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: work_logs_user
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: work_expense_items; Type: TABLE; Schema: public; Owner: work_logs_user
--

CREATE TABLE public.work_expense_items (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    session_id integer NOT NULL,
    amount numeric(12,2) NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.work_expense_items OWNER TO work_logs_user;

--
-- Name: work_expense_items_id_seq; Type: SEQUENCE; Schema: public; Owner: work_logs_user
--

CREATE SEQUENCE public.work_expense_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.work_expense_items_id_seq OWNER TO work_logs_user;

--
-- Name: work_expense_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: work_logs_user
--

ALTER SEQUENCE public.work_expense_items_id_seq OWNED BY public.work_expense_items.id;


--
-- Name: work_income_items; Type: TABLE; Schema: public; Owner: work_logs_user
--

CREATE TABLE public.work_income_items (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    session_id integer NOT NULL,
    amount numeric(12,2) NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.work_income_items OWNER TO work_logs_user;

--
-- Name: work_income_items_id_seq; Type: SEQUENCE; Schema: public; Owner: work_logs_user
--

CREATE SEQUENCE public.work_income_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.work_income_items_id_seq OWNER TO work_logs_user;

--
-- Name: work_income_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: work_logs_user
--

ALTER SEQUENCE public.work_income_items_id_seq OWNED BY public.work_income_items.id;


--
-- Name: work_sessions; Type: TABLE; Schema: public; Owner: work_logs_user
--

CREATE TABLE public.work_sessions (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    user_id integer NOT NULL,
    project text DEFAULT ''::text NOT NULL,
    work_date date NOT NULL,
    start_time time without time zone NOT NULL,
    end_time time without time zone,
    hours_worked numeric(10,2),
    notes text DEFAULT ''::text NOT NULL,
    income numeric(12,2),
    expenses numeric(12,2),
    ended_by_user_id integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.work_sessions OWNER TO work_logs_user;

--
-- Name: work_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: work_logs_user
--

CREATE SEQUENCE public.work_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.work_sessions_id_seq OWNER TO work_logs_user;

--
-- Name: work_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: work_logs_user
--

ALTER SEQUENCE public.work_sessions_id_seq OWNED BY public.work_sessions.id;


--
-- Name: work_tasks; Type: TABLE; Schema: public; Owner: work_logs_user
--

CREATE TABLE public.work_tasks (
    id integer NOT NULL,
    tenant_id integer NOT NULL,
    session_id integer NOT NULL,
    user_id integer,
    task_text text NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.work_tasks OWNER TO work_logs_user;

--
-- Name: work_tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: work_logs_user
--

CREATE SEQUENCE public.work_tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.work_tasks_id_seq OWNER TO work_logs_user;

--
-- Name: work_tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: work_logs_user
--

ALTER SEQUENCE public.work_tasks_id_seq OWNED BY public.work_tasks.id;


--
-- Name: blocked_registration_prefixes id; Type: DEFAULT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.blocked_registration_prefixes ALTER COLUMN id SET DEFAULT nextval('public.blocked_registration_prefixes_id_seq'::regclass);


--
-- Name: security_events id; Type: DEFAULT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.security_events ALTER COLUMN id SET DEFAULT nextval('public.security_events_id_seq'::regclass);


--
-- Name: tenant_invites id; Type: DEFAULT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.tenant_invites ALTER COLUMN id SET DEFAULT nextval('public.tenant_invites_id_seq'::regclass);


--
-- Name: tenants id; Type: DEFAULT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.tenants ALTER COLUMN id SET DEFAULT nextval('public.tenants_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: work_expense_items id; Type: DEFAULT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_expense_items ALTER COLUMN id SET DEFAULT nextval('public.work_expense_items_id_seq'::regclass);


--
-- Name: work_income_items id; Type: DEFAULT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_income_items ALTER COLUMN id SET DEFAULT nextval('public.work_income_items_id_seq'::regclass);


--
-- Name: work_sessions id; Type: DEFAULT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_sessions ALTER COLUMN id SET DEFAULT nextval('public.work_sessions_id_seq'::regclass);


--
-- Name: work_tasks id; Type: DEFAULT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_tasks ALTER COLUMN id SET DEFAULT nextval('public.work_tasks_id_seq'::regclass);


--
-- Data for Name: blocked_registration_prefixes; Type: TABLE DATA; Schema: public; Owner: work_logs_user
--

COPY public.blocked_registration_prefixes (id, prefix, created_at) FROM stdin;
\.


--
-- Data for Name: security_events; Type: TABLE DATA; Schema: public; Owner: work_logs_user
--

COPY public.security_events (id, event_type, user_id, ip_address, user_agent, details, created_at) FROM stdin;
1	login_failed	\N	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0	{"email": "rob3662@gmail.com", "reason": "user_not_found"}	2026-05-20 20:23:57.294417
2	user_login	1	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0	{}	2026-05-20 20:24:09.858426
3	user_login	1	10.89.0.1	Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.2 Mobile/15E148 Safari/604.1	{}	2026-05-23 13:09:31.685825
4	user_login	1	10.89.0.1	Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.2 Mobile/15E148 Safari/604.1	{}	2026-05-23 19:33:53.777609
5	login_failed	\N	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0	{"email": "rob3662@gmail.com", "reason": "user_not_found"}	2026-07-17 20:23:33.033979
6	login_failed	\N	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0	{"email": "rob3662@gmail.com", "reason": "user_not_found"}	2026-07-17 20:23:42.822167
7	user_login	1	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0	{}	2026-07-17 20:23:56.420428
8	user_logout	1	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0	{}	2026-07-17 20:24:45.446356
9	user_created	2	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0	{"email": "rob3662@gmail.com"}	2026-07-17 20:34:57.452924
10	login_failed	1	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0	{"email": "brakesystemsca@gmail.com", "reason": "invalid_password"}	2026-07-17 20:43:30.975309
11	user_login	1	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0	{}	2026-07-17 20:43:45.382236
12	user_logout	1	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0	{}	2026-07-17 20:43:53.36977
13	user_created	3	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0	{"email": "rob3662@gmail.com"}	2026-07-17 20:48:23.455714
14	email_verified	3	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0	{}	2026-07-17 20:48:45.117758
15	user_login	3	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0	{}	2026-07-17 20:50:06.385992
16	user_login	3	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0	{}	2026-07-18 03:14:51.149247
17	user_login	3	10.89.0.1	Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.2 Mobile/15E148 Safari/604.1	{}	2026-07-19 16:39:11.939766
18	user_login	3	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:153.0) Gecko/20100101 Firefox/153.0	{}	2026-08-12 22:47:13.565966
19	user_login	3	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:153.0) Gecko/20100101 Firefox/153.0	{}	2026-08-21 22:27:43.022627
20	user_login	3	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36	{}	2026-08-21 22:36:49.796476
21	user_login	3	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36	{}	2026-08-29 15:44:45.82878
22	user_login	3	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36	{}	2026-08-30 11:21:22.721947
23	user_login	3	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36	{}	2026-08-31 13:27:35.804051
24	user_login	3	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64; rv:155.0) Gecko/20100101 Firefox/155.0	{}	2026-09-03 23:38:17.137337
25	user_login	3	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36	{}	2026-09-04 17:30:27.715888
26	user_login	3	10.89.0.1	Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36	{}	2026-09-05 18:31:29.506668
\.


--
-- Data for Name: tenant_invites; Type: TABLE DATA; Schema: public; Owner: work_logs_user
--

COPY public.tenant_invites (id, tenant_id, email, token_hash, invited_by_user_id, created_at, expires_at, accepted_at, revoked_at) FROM stdin;
\.


--
-- Data for Name: tenants; Type: TABLE DATA; Schema: public; Owner: work_logs_user
--

COPY public.tenants (id, name, created_at, updated_at, owner_user_id) FROM stdin;
1	Default	2026-05-20 20:20:10.812715	2026-05-20 20:20:10.812715	1
2	Robert's workspace	2026-07-17 20:34:57.355671	2026-07-17 20:34:57.355387	2
3	Robert's workspace	2026-07-17 20:48:23.286812	2026-07-17 20:48:23.286171	3
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: work_logs_user
--

COPY public.users (id, tenant_id, username, email, password_hash, is_admin, email_verified, verification_token, personal_email, personal_email_verified, personal_email_verification_token, password_reset_token, password_reset_expires, stripe_customer_id, last_login, created_at, updated_at, is_site_admin) FROM stdin;
1	1	admin	brakesystemsca@gmail.com	scrypt:32768:8:1$Ntx9jKlWHndqf4VV$d0bbcb21a54ea29c0d14f9dc69379daf58f0cd840c6aedb723c5f335a1b14712fc32d11bff0aebfddc7f260ad228e5c47db8b7ddcfebb0c7bc7cd245d6af425f	t	t	\N	\N	f	\N	\N	\N	\N	2026-07-17 20:43:45.346954	2026-05-20 20:20:10.914515	2026-05-20 20:20:10.914794	t
3	3	Robert	rob3662@gmail.com	scrypt:32768:8:1$zW0EAEF6LuDfs8ok$666b56f215f4176bd36ee8ee2cd3911dd336b884b4f81958a8ea74996d55b5cb2bf4768f6e864180f9ff04d50acae9b612abaa76c8ecbdcce305addd60c86f1d	t	t	\N	\N	f	\N	\N	\N	\N	2026-09-05 18:31:29.493352	2026-07-17 20:48:23.442244	2026-07-17 20:48:23.442623	f
\.


--
-- Data for Name: work_expense_items; Type: TABLE DATA; Schema: public; Owner: work_logs_user
--

COPY public.work_expense_items (id, tenant_id, session_id, amount, description, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: work_income_items; Type: TABLE DATA; Schema: public; Owner: work_logs_user
--

COPY public.work_income_items (id, tenant_id, session_id, amount, description, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: work_sessions; Type: TABLE DATA; Schema: public; Owner: work_logs_user
--

COPY public.work_sessions (id, tenant_id, user_id, project, work_date, start_time, end_time, hours_worked, notes, income, expenses, ended_by_user_id, created_at, updated_at) FROM stdin;
1	3	3	Sub Tracker NL	2026-05-20	20:00:00	22:00:00	2.00		\N	\N	3	2026-07-17 20:50:59.731681	2026-07-17 20:52:02.444103
2	3	3	Sub Tracker NL	2026-06-11	19:30:00	20:30:00	1.00		\N	\N	3	2026-07-17 20:52:49.49899	2026-07-17 20:54:32.306192
3	3	3	Sub Tracker NL	2026-08-12	20:45:00	21:28:00	0.72		\N	\N	3	2026-08-12 22:48:30.220203	2026-08-12 23:58:18.960068
4	3	3	Sub Tracker NL	2026-08-21	19:58:00	21:04:00	1.10		\N	\N	3	2026-08-21 22:28:43.871457	2026-08-21 23:59:26.510393
5	3	3	Sub Tracker NL	2026-08-29	13:14:00	14:27:12	1.22		\N	\N	3	2026-08-29 15:44:56.880657	2026-08-29 18:12:35.413423
6	3	3	Sub Tracker NL	2026-08-29	15:42:00	16:47:00	1.08		\N	\N	3	2026-08-29 18:12:52.908888	2026-08-29 19:17:48.243935
7	3	3	Sub Tracker NL	2026-08-30	08:51:00	10:58:00	2.12	setting up Stripe live account	\N	\N	3	2026-08-30 11:21:51.842076	2026-08-30 13:28:40.457739
8	3	3	Sub Tracker NL	2026-08-31	10:32:00	10:59:00	0.45		\N	\N	3	2026-08-31 13:28:00.921594	2026-08-31 13:36:54.766299
9	3	3	Sub Tracker NL	2026-09-04	15:00:00	15:25:00	0.42		\N	\N	3	2026-09-04 17:30:35.139177	2026-09-04 18:00:48.378666
10	3	3	Sub Tracker NL	2026-09-04	16:57:00	17:01:00	0.07		\N	\N	3	2026-09-04 19:27:45.682242	2026-09-04 19:31:44.945212
11	3	3	Sub Tracker NL	2026-09-05	17:30:00	18:30:00	1.00		\N	\N	3	2026-09-05 18:31:45.505562	2026-09-05 21:01:01.554977
\.


--
-- Data for Name: work_tasks; Type: TABLE DATA; Schema: public; Owner: work_logs_user
--

COPY public.work_tasks (id, tenant_id, session_id, user_id, task_text, created_at, updated_at) FROM stdin;
1	3	1	3	Increased max users that can register	2026-07-17 20:51:19.702966	2026-07-17 20:51:19.702979
2	3	1	3	Fixed database connection issue	2026-07-17 20:51:34.274677	2026-07-17 20:51:34.274692
3	3	1	3	worked on setup script for site containers	2026-07-17 20:51:48.383626	2026-07-17 20:51:48.383638
4	3	2	3	Fixed dashboard summary	2026-07-17 20:53:04.380923	2026-07-17 20:53:04.380937
5	3	2	3	Added yearly summary modal	2026-07-17 20:53:14.079141	2026-07-17 20:53:14.079153
6	3	2	3	moved EI report icon and made ei report modal	2026-07-17 20:53:32.234791	2026-07-17 20:53:32.234805
7	3	2	3	Added job_id column to work_days table in database	2026-07-17 20:53:54.206182	2026-07-17 20:53:54.206194
8	3	2	3	minor changes to ei-guide	2026-07-17 20:54:04.984587	2026-07-17 20:54:04.984601
9	3	2	3	edited mobile layout for calendar, weekly instead of monthly	2026-07-17 20:54:25.799749	2026-07-17 20:54:25.799761
10	3	3	3	updated plans page with pricing and made page public	2026-08-12 23:37:14.699571	2026-08-12 23:37:14.699584
11	3	3	3	deployed update to live site	2026-08-12 23:40:14.609208	2026-08-12 23:40:14.609244
12	3	3	3	Set up environmental variables for Stripe	2026-08-12 23:58:11.227964	2026-08-12 23:58:11.227968
13	3	4	3	created Stripe account	2026-08-21 23:34:07.650213	2026-08-21 23:34:07.650217
14	3	4	3	setting up stripe for subtracker	2026-08-21 23:34:24.506388	2026-08-21 23:34:24.506401
15	3	4	3	testing stripe in sandbox	2026-08-21 23:34:33.347586	2026-08-21 23:34:33.347599
16	3	5	3	created icon and logo for stripe and finished updating the business settings in stripe sandbox	2026-08-29 16:57:03.821018	2026-08-29 16:57:03.821032
17	3	6	3	Add holidays and breaks for 26-27 school year	2026-08-29 18:13:11.715182	2026-08-29 18:13:11.715196
18	3	6	3	added pay days for 26-27 school year	2026-08-29 18:30:43.859291	2026-08-29 18:30:43.859304
19	3	6	3	added in logic to use the last pay schedule if the current one doesn't exist because of an expired contract	2026-08-29 18:47:28.835544	2026-08-29 18:47:28.835556
20	3	6	3	fine tuning stripe webhook actions, testing cancelling subscription by user	2026-08-29 19:17:45.734834	2026-08-29 19:17:45.734839
21	3	7	3	worked on email bugs	2026-08-30 13:26:56.416182	2026-08-30 13:26:56.416195
22	3	7	3	tested daily subscription in sandbox that will trigger the day before the site goes live	2026-08-30 13:27:24.381556	2026-08-30 13:27:24.381569
23	3	7	3	verified .env file for server	2026-08-30 13:27:41.686329	2026-08-30 13:27:41.686342
24	3	7	3	verified stripe webhook actions	2026-08-30 13:28:30.787521	2026-08-30 13:28:30.787535
25	3	8	3	transferred all strip setting to live account	2026-08-31 13:28:19.71208	2026-08-31 13:28:19.712095
26	3	8	3	fixed bug with promo end date and subscriptions	2026-08-31 13:29:07.948024	2026-08-31 13:29:07.948038
27	3	9	3	Archived daily subscription price on Stripe	2026-09-04 17:31:43.970267	2026-09-04 17:31:43.970282
28	3	9	3	got cursor to work on visual upgrades for site	2026-09-04 18:00:36.731867	2026-09-04 18:00:36.73188
29	3	10	3	got cursor to work on secondary visual updates,	2026-09-04 19:31:40.360153	2026-09-04 19:31:40.360164
30	3	11	3	working on pay stub recognition and comparison to work days	2026-09-05 18:32:01.0359	2026-09-05 18:32:01.035913
31	3	11	3	pay stub recognition and updates working and deployed on server	2026-09-05 21:00:38.763822	2026-09-05 21:00:38.763826
\.


--
-- Name: blocked_registration_prefixes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: work_logs_user
--

SELECT pg_catalog.setval('public.blocked_registration_prefixes_id_seq', 1, false);


--
-- Name: security_events_id_seq; Type: SEQUENCE SET; Schema: public; Owner: work_logs_user
--

SELECT pg_catalog.setval('public.security_events_id_seq', 26, true);


--
-- Name: tenant_invites_id_seq; Type: SEQUENCE SET; Schema: public; Owner: work_logs_user
--

SELECT pg_catalog.setval('public.tenant_invites_id_seq', 1, false);


--
-- Name: tenants_id_seq; Type: SEQUENCE SET; Schema: public; Owner: work_logs_user
--

SELECT pg_catalog.setval('public.tenants_id_seq', 3, true);


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: work_logs_user
--

SELECT pg_catalog.setval('public.users_id_seq', 3, true);


--
-- Name: work_expense_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: work_logs_user
--

SELECT pg_catalog.setval('public.work_expense_items_id_seq', 1, false);


--
-- Name: work_income_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: work_logs_user
--

SELECT pg_catalog.setval('public.work_income_items_id_seq', 1, false);


--
-- Name: work_sessions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: work_logs_user
--

SELECT pg_catalog.setval('public.work_sessions_id_seq', 11, true);


--
-- Name: work_tasks_id_seq; Type: SEQUENCE SET; Schema: public; Owner: work_logs_user
--

SELECT pg_catalog.setval('public.work_tasks_id_seq', 31, true);


--
-- Name: blocked_registration_prefixes blocked_registration_prefixes_pkey; Type: CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.blocked_registration_prefixes
    ADD CONSTRAINT blocked_registration_prefixes_pkey PRIMARY KEY (id);


--
-- Name: blocked_registration_prefixes blocked_registration_prefixes_prefix_key; Type: CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.blocked_registration_prefixes
    ADD CONSTRAINT blocked_registration_prefixes_prefix_key UNIQUE (prefix);


--
-- Name: security_events security_events_pkey; Type: CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.security_events
    ADD CONSTRAINT security_events_pkey PRIMARY KEY (id);


--
-- Name: tenant_invites tenant_invites_pkey; Type: CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.tenant_invites
    ADD CONSTRAINT tenant_invites_pkey PRIMARY KEY (id);


--
-- Name: tenant_invites tenant_invites_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.tenant_invites
    ADD CONSTRAINT tenant_invites_token_hash_key UNIQUE (token_hash);


--
-- Name: tenants tenants_pkey; Type: CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.tenants
    ADD CONSTRAINT tenants_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_tenant_id_email_key; Type: CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_tenant_id_email_key UNIQUE (tenant_id, email);


--
-- Name: users users_tenant_id_username_key; Type: CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_tenant_id_username_key UNIQUE (tenant_id, username);


--
-- Name: work_expense_items work_expense_items_pkey; Type: CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_expense_items
    ADD CONSTRAINT work_expense_items_pkey PRIMARY KEY (id);


--
-- Name: work_income_items work_income_items_pkey; Type: CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_income_items
    ADD CONSTRAINT work_income_items_pkey PRIMARY KEY (id);


--
-- Name: work_sessions work_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_sessions
    ADD CONSTRAINT work_sessions_pkey PRIMARY KEY (id);


--
-- Name: work_tasks work_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_tasks
    ADD CONSTRAINT work_tasks_pkey PRIMARY KEY (id);


--
-- Name: idx_tenant_invites_one_pending_per_email; Type: INDEX; Schema: public; Owner: work_logs_user
--

CREATE UNIQUE INDEX idx_tenant_invites_one_pending_per_email ON public.tenant_invites USING btree (tenant_id, lower(TRIM(BOTH FROM email))) WHERE ((accepted_at IS NULL) AND (revoked_at IS NULL));


--
-- Name: idx_tenant_invites_tenant; Type: INDEX; Schema: public; Owner: work_logs_user
--

CREATE INDEX idx_tenant_invites_tenant ON public.tenant_invites USING btree (tenant_id);


--
-- Name: idx_work_expense_items_session; Type: INDEX; Schema: public; Owner: work_logs_user
--

CREATE INDEX idx_work_expense_items_session ON public.work_expense_items USING btree (session_id);


--
-- Name: idx_work_income_items_session; Type: INDEX; Schema: public; Owner: work_logs_user
--

CREATE INDEX idx_work_income_items_session ON public.work_income_items USING btree (session_id);


--
-- Name: idx_work_sessions_tenant_user; Type: INDEX; Schema: public; Owner: work_logs_user
--

CREATE INDEX idx_work_sessions_tenant_user ON public.work_sessions USING btree (tenant_id, user_id);


--
-- Name: idx_work_sessions_tenant_work_date; Type: INDEX; Schema: public; Owner: work_logs_user
--

CREATE INDEX idx_work_sessions_tenant_work_date ON public.work_sessions USING btree (tenant_id, work_date DESC);


--
-- Name: idx_work_tasks_session; Type: INDEX; Schema: public; Owner: work_logs_user
--

CREATE INDEX idx_work_tasks_session ON public.work_tasks USING btree (session_id);


--
-- Name: tenant_invites tenant_invites_invited_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.tenant_invites
    ADD CONSTRAINT tenant_invites_invited_by_user_id_fkey FOREIGN KEY (invited_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: tenant_invites tenant_invites_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.tenant_invites
    ADD CONSTRAINT tenant_invites_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: users users_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: work_expense_items work_expense_items_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_expense_items
    ADD CONSTRAINT work_expense_items_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.work_sessions(id) ON DELETE CASCADE;


--
-- Name: work_expense_items work_expense_items_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_expense_items
    ADD CONSTRAINT work_expense_items_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: work_income_items work_income_items_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_income_items
    ADD CONSTRAINT work_income_items_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.work_sessions(id) ON DELETE CASCADE;


--
-- Name: work_income_items work_income_items_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_income_items
    ADD CONSTRAINT work_income_items_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: work_sessions work_sessions_ended_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_sessions
    ADD CONSTRAINT work_sessions_ended_by_user_id_fkey FOREIGN KEY (ended_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: work_sessions work_sessions_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_sessions
    ADD CONSTRAINT work_sessions_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: work_sessions work_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_sessions
    ADD CONSTRAINT work_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: work_tasks work_tasks_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_tasks
    ADD CONSTRAINT work_tasks_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.work_sessions(id) ON DELETE CASCADE;


--
-- Name: work_tasks work_tasks_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_tasks
    ADD CONSTRAINT work_tasks_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;


--
-- Name: work_tasks work_tasks_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: work_logs_user
--

ALTER TABLE ONLY public.work_tasks
    ADD CONSTRAINT work_tasks_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: pg_database_owner
--

GRANT ALL ON SCHEMA public TO work_logs_user;


--
-- PostgreSQL database dump complete
--

\unrestrict a8i6YZYEUrtJuq0StmjPqCo6hBVtjshzzXePlYeN0Oc8j1QDNwwicPyAFDAUC7y

