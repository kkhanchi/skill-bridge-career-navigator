"""Skill-Bridge Career Navigator — Streamlit Application.

Phase 6 refactor. The app has two modes controlled by the
``SKILL_BRIDGE_OFFLINE`` env var:

- **Online mode (default).** Talks to the deployed REST API via
  :class:`ApiClient`. Requires login; all profile/gap/roadmap state
  is persisted server-side, visible across sessions.

- **Offline mode** (``SKILL_BRIDGE_OFFLINE=1``). Falls back to the
  Phase 0–5 direct-core-import path so the UI runs with zero infra —
  valuable for laptop demos and CI-less reviewers. State is
  in-memory only.

The offline path is the R9 Option B decision recorded in ADR-020:
shims stay at near-zero cost, offline demo has real portfolio
value. Online mode is the default because that's the production
deploy.

Design reference: ``.kiro/specs/phase-6-streamlit-integration/design.md``.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import streamlit as st

# Ensure the skill-bridge directory is on the path for the offline
# shim imports — the online path only needs api_client which is a
# sibling module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OFFLINE = os.environ.get("SKILL_BRIDGE_OFFLINE") == "1"

# ---------------------------------------------------------------------------
# Page config (shared between modes)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Skill-Bridge Career Navigator",
    page_icon="🎯",
    layout="wide",
)
st.title("🎯 Skill-Bridge Career Navigator")
st.caption("Bridge the gap between your skills and your dream role")


# ===========================================================================
# OFFLINE MODE — Phase 0–5 direct-core-import path, preserved verbatim.
# Guarded by SKILL_BRIDGE_OFFLINE=1 so local demos work without the API.
# ===========================================================================

if OFFLINE:
    from ai_engine import get_categorizer
    from gap_analyzer import analyze_gap
    from job_catalog import load_jobs, search_jobs
    from profile_manager import create_profile, load_profile, save_profile, update_profile
    from profile_printer import format_profile
    from resume_parser import load_taxonomy, parse_resume
    from roadmap_generator import (
        _load_resources,
        generate_roadmap,
        mark_completed,
        recalculate_match,
    )

    st.info(
        "🔌 Offline mode: using in-memory storage, no API calls. "
        "Unset SKILL_BRIDGE_OFFLINE to connect to the deployed API."
    )

    # --- Load static data ---
    @st.cache_data
    def cached_taxonomy() -> list[str]:
        return load_taxonomy(
            os.path.join(os.path.dirname(__file__), "data", "skill_taxonomy.json")
        )

    @st.cache_data
    def cached_jobs() -> Any:
        try:
            return load_jobs(os.path.join(os.path.dirname(__file__), "data", "jobs.json"))
        except FileNotFoundError:
            return None

    @st.cache_data
    def cached_resources() -> Any:
        return _load_resources(
            os.path.join(os.path.dirname(__file__), "data", "learning_resources.json")
        )

    taxonomy = cached_taxonomy()
    all_jobs = cached_jobs()
    all_resources = cached_resources()

    # Section 1: Profile Creation & Resume Parsing ---------------------------
    st.header("📝 Your Profile")

    if all_jobs is None:
        st.error("Job data is currently unavailable. Please contact support.")

    with st.expander("📄 Paste Resume Text (optional)", expanded=False):
        resume_text = st.text_area("Paste your resume here:", height=150, key="resume_input")
        if st.button("Extract Skills"):
            extracted = parse_resume(resume_text, taxonomy)
            if extracted:
                st.session_state["extracted_skills"] = extracted
                st.success(f"Extracted {len(extracted)} skills: {', '.join(extracted)}")
            else:
                st.warning("No skills could be extracted. Please enter your skills manually.")

    with st.form("profile_form"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Name", value=st.session_state.get("profile_name", ""))
            experience = st.number_input("Years of Experience", min_value=0, max_value=50, value=0)
        with col2:
            education = st.selectbox(
                "Education Level",
                ["High School", "Associate", "Bachelor's", "Master's", "PhD"],
            )
            target_role = st.text_input(
                "Target Job Role",
                value=st.session_state.get("profile_target", ""),
            )
        default_skills = st.session_state.get("extracted_skills", [])
        skills_input = st.multiselect(
            "Your Skills",
            options=taxonomy,
            default=[s for s in default_skills if s in taxonomy],
            help="Select from taxonomy or type to search",
        )
        submitted = st.form_submit_button("Create / Update Profile")
        if submitted:
            try:
                profile, notification = create_profile(
                    name, skills_input, experience, education, target_role
                )
                save_profile(profile)
                st.session_state["profile_name"] = name
                st.session_state["profile_target"] = target_role
                if notification:
                    st.info(notification)
                st.success(f"Profile created with {len(profile.skills)} skills!")
            except ValueError as e:
                st.error(str(e))

    profile = load_profile()
    if profile:
        with st.expander("👤 Current Profile", expanded=True):
            col1, col2, col3 = st.columns(3)
            col1.metric("Skills", len(profile.skills))
            col2.metric("Experience", f"{profile.experience_years} yrs")
            col3.metric("Target", profile.target_role)
            st.write("**Skills:**", ", ".join(profile.skills))
            with st.expander("📋 Full Profile Summary", expanded=False):
                st.code(format_profile(profile), language=None)

    # Section 2: Job Catalog & Gap Analysis ----------------------------------
    if profile and all_jobs is not None:
        st.header("🔍 Job Catalog & Gap Analysis")

        col1, col2 = st.columns(2)
        with col1:
            keyword_filter = st.text_input("Search by job title keyword", key="kw_filter")
        with col2:
            skill_filter = st.selectbox(
                "Filter by required skill", [""] + taxonomy, key="sk_filter"
            )
        filtered_jobs = search_jobs(all_jobs, keyword=keyword_filter, skill=skill_filter)
        if filtered_jobs:
            job_titles = [f"{j.title} ({j.experience_level})" for j in filtered_jobs]
            selected_idx = st.selectbox(
                "Select a job to analyze",
                range(len(job_titles)),
                format_func=lambda i: job_titles[i],
            )
            selected_job = filtered_jobs[selected_idx]

            with st.expander("📋 Job Details", expanded=False):
                st.write(f"**{selected_job.title}** — {selected_job.experience_level}")
                st.write(selected_job.description)
                st.write(f"**Required:** {', '.join(selected_job.required_skills)}")
                st.write(f"**Preferred:** {', '.join(selected_job.preferred_skills)}")

            if st.button("🔎 Run Gap Analysis"):
                gap = analyze_gap(profile, selected_job)
                st.session_state["gap_result"] = gap
                st.session_state["selected_job"] = selected_job
                st.session_state["prev_match"] = gap.match_percentage
                categorizer = get_categorizer()
                cat_result = categorizer.categorize(
                    gap.missing_required + gap.missing_preferred,
                    gap.matched_required + gap.matched_preferred,
                )
                st.session_state["categorization"] = cat_result

        if "gap_result" in st.session_state:
            gap = st.session_state["gap_result"]
            cat = st.session_state.get("categorization")
            st.subheader("📊 Gap Analysis Results")
            col1, col2, col3 = st.columns(3)
            col1.metric("Match", f"{gap.match_percentage}%")
            col2.metric("Missing Required", len(gap.missing_required))
            col3.metric("Missing Preferred", len(gap.missing_preferred))
            if gap.match_percentage == 100 and not gap.missing_required:
                st.success("🎉 You meet all required skills for this role!")
            col1, col2 = st.columns(2)
            with col1:
                st.write("✅ **Matched Required:**", ", ".join(gap.matched_required) or "None")
                st.write("✅ **Matched Preferred:**", ", ".join(gap.matched_preferred) or "None")
            with col2:
                st.write("❌ **Missing Required:**", ", ".join(gap.missing_required) or "None")
                st.write("⚠️ **Missing Preferred:**", ", ".join(gap.missing_preferred) or "None")
            if cat:
                st.subheader("🤖 AI Skill Categorization")
                if cat.is_fallback:
                    st.info("AI categorization unavailable — showing raw results")
                st.write(cat.summary)
                if cat.groups:
                    for category, skills in cat.groups.items():
                        st.write(f"**{category}:** {', '.join(skills)}")

    # Section 3: Learning Roadmap & Profile Updates --------------------------
    if "gap_result" in st.session_state and profile:
        gap = st.session_state["gap_result"]
        selected_job = st.session_state.get("selected_job")
        if gap.missing_required or gap.missing_preferred:
            st.header("🗺️ Learning Roadmap")
            if "roadmap" not in st.session_state or st.session_state.get("roadmap_stale", False):
                roadmap = generate_roadmap(gap, all_resources)
                st.session_state["roadmap"] = roadmap
                st.session_state["roadmap_stale"] = False
            roadmap = st.session_state["roadmap"]
            for phase in roadmap.phases:
                if phase.resources:
                    st.subheader(f"📅 {phase.label}")
                    for i, r in enumerate(phase.resources):
                        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                        status = "✅" if r.completed else "⬜"
                        col1.write(f"{status} **{r.name}** ({r.skill})")
                        col2.write(f"📚 {r.resource_type}")
                        col3.write(f"⏱️ {r.estimated_hours}h")
                        if not r.completed:
                            btn_key = f"complete_{phase.label}_{i}"
                            if col4.button("Mark Done", key=btn_key):
                                roadmap = mark_completed(roadmap, r.name)
                                st.session_state["roadmap"] = roadmap
                                if selected_job:
                                    new_match = recalculate_match(
                                        profile, selected_job, roadmap
                                    )
                                    st.session_state["gap_result"].match_percentage = new_match
                                st.rerun()
                        else:
                            col4.write("Done")
            if selected_job:
                current_match = recalculate_match(profile, selected_job, roadmap)
                prev_match = st.session_state.get("prev_match", current_match)
                if current_match != prev_match:
                    st.metric(
                        "Updated Match",
                        f"{current_match}%",
                        delta=f"+{current_match - prev_match}%",
                    )

        st.header("🔄 Update Your Profile")
        with st.form("update_form"):
            new_skills = st.multiselect(
                "Add Skills",
                options=[s for s in taxonomy if s not in profile.skills],
                key="add_skills_select",
            )
            remove_skills = st.multiselect(
                "Remove Skills", options=profile.skills, key="remove_skills_select"
            )
            update_submitted = st.form_submit_button("Update & Re-Analyze")
            if update_submitted and (new_skills or remove_skills):
                try:
                    updated = update_profile(
                        profile, added_skills=new_skills, removed_skills=remove_skills
                    )
                    save_profile(updated)
                    if selected_job:
                        old_match = gap.match_percentage
                        new_gap = analyze_gap(updated, selected_job)
                        st.session_state["gap_result"] = new_gap
                        st.session_state["roadmap_stale"] = True
                        categorizer = get_categorizer()
                        cat_result = categorizer.categorize(
                            new_gap.missing_required + new_gap.missing_preferred,
                            new_gap.matched_required + new_gap.matched_preferred,
                        )
                        st.session_state["categorization"] = cat_result
                        st.success(
                            f"Profile updated! Match: {old_match}% → "
                            f"{new_gap.match_percentage}%"
                        )
                    else:
                        st.success("Profile updated!")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    # Stop execution; online-mode code below this block is not reached in
    # offline mode (offline code runs top-to-bottom and returns at the
    # module level when Streamlit finishes the rerun).
    st.stop()


# ===========================================================================
# ONLINE MODE — Phase 6 integration path. Talks HTTP to the deployed API.
# ===========================================================================

from api_client import (  # noqa: E402  — optional-import pattern for SKILL_BRIDGE_OFFLINE
    ApiClient,
    ApiClientError,
    ApiConnectionError,
    ApiError,
    ApiServerError,
    AuthExpiredError,
    RateLimitedError,
)

# Session-state keys managed by the online path. Documented here so
# any future rerun-sensitive code knows the contract at a glance
# (design §Data Models / Streamlit session state keys).
_SESSION_KEYS = {
    "api_client",  # ApiClient instance (created once per session)
    "access_token",  # JWT access (rotated on refresh)
    "refresh_token",  # JWT refresh (rotated on refresh)
    "current_user",  # dict from /auth/me or login response
    "profile",  # current ProfileResponse dict
    "gap_result",  # current AnalysisResponse dict
    "selected_job",  # current JobResponse dict
    "roadmap",  # current RoadmapResponse dict
    "extracted_skills",  # list[str] from /resume/parse
}


# ---------------------------------------------------------------------------
# Client bootstrap — runs at the top of every rerun
# ---------------------------------------------------------------------------


def get_or_create_client() -> ApiClient:
    """Return a session-scoped :class:`ApiClient`, creating it if needed.

    Streamlit re-executes this module top-to-bottom on every
    interaction. The ApiClient instance lives in session state so it
    survives reruns; tokens sit in separate session keys and are
    re-attached here because the UI may have mutated them in the
    previous rerun (login, logout, reactive refresh).

    Satisfies R1.6 (client doesn't touch session_state directly) and
    R5.5 (session keys use the exact documented names).
    """
    if "api_client" not in st.session_state:
        st.session_state["api_client"] = ApiClient()
    client = st.session_state["api_client"]
    client.set_tokens(
        st.session_state.get("access_token"),
        st.session_state.get("refresh_token"),
    )
    return client


def _persist_tokens(client: ApiClient) -> None:
    """Pull the client's possibly-rotated tokens back into session_state.

    Called after any authed call that might have refreshed tokens via
    the reactive-refresh path in :meth:`ApiClient._request`. Keeps
    session_state the source of truth for the NEXT rerun while the
    current rerun holds the fresh pair in the client instance.
    """
    access, refresh = client.tokens
    if access is not None:
        st.session_state["access_token"] = access
    if refresh is not None:
        st.session_state["refresh_token"] = refresh


def _handle_logout(client: ApiClient) -> None:
    """Best-effort server-side revocation + unconditional local clear.

    Satisfies R5.6 + R5.7 (logout idempotency, property P2). Any
    ApiError raised by the server call is swallowed — the UI does
    NOT want a 10-second hang on a dead API when the user is trying
    to sign out. The 2-second timeout matches the design decision
    in ADR-020.
    """
    try:
        client.logout(timeout=2.0)
    except ApiError:
        pass
    # Unconditional local clear; dict.pop(..., None) is a no-op when
    # the key is absent, so this is safe to call repeatedly.
    for key in ("access_token", "refresh_token", "current_user"):
        st.session_state.pop(key, None)


# ---------------------------------------------------------------------------
# Auth sidebar
# ---------------------------------------------------------------------------


def render_auth_sidebar(client: ApiClient) -> None:
    """Render the login/register tabs OR the logged-in summary.

    Split out as an in-file helper because Streamlit discourages
    multi-file UI modules for apps of this size. Four helpers below
    do the actual work; this function only dispatches on logged-in
    state.
    """
    with st.sidebar:
        if st.session_state.get("current_user"):
            _render_logged_in(client)
        else:
            _render_auth_forms(client)


def _render_logged_in(client: ApiClient) -> None:
    user = st.session_state["current_user"]
    st.write(f"Logged in as **{user['email']}**")
    if st.button("Logout"):
        _handle_logout(client)
        st.rerun()


def _render_auth_forms(client: ApiClient) -> None:
    tab_login, tab_register = st.tabs(["Login", "Register"])
    with tab_login:
        _login_form(client)
    with tab_register:
        _register_form(client)


def _login_form(client: ApiClient) -> None:
    with st.form("login_form"):
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("Login")
        if not submitted:
            return
        try:
            with st.spinner("Waking up the API (free-tier cold start, ~30s)…"):
                result = client.login(email, password)
        except RateLimitedError as e:
            _render_rate_limit(e)
            return
        except ApiClientError as e:
            st.error(e.message)
            return
        except ApiServerError:
            st.error("Server error — please try again in a moment.")
            return
        except ApiConnectionError:
            st.error(
                "Can't reach the API. Check your connection or retry in a minute "
                "(free-tier cold start)."
            )
            return
        st.session_state["access_token"] = result["access"]
        st.session_state["refresh_token"] = result["refresh"]
        st.session_state["current_user"] = result["user"]
        st.rerun()


def _register_form(client: ApiClient) -> None:
    with st.form("register_form"):
        email = st.text_input("Email", key="register_email")
        password = st.text_input(
            "Password",
            type="password",
            key="register_password",
            help="Minimum 12 characters.",
        )
        submitted = st.form_submit_button("Register")
        if not submitted:
            return
        try:
            with st.spinner("Waking up the API (free-tier cold start, ~30s)…"):
                result = client.register(email, password)
        except RateLimitedError as e:
            _render_rate_limit(e)
            return
        except ApiClientError as e:
            st.error(e.message)
            return
        except ApiServerError:
            st.error("Server error — please try again in a moment.")
            return
        except ApiConnectionError:
            st.error(
                "Can't reach the API. Check your connection or retry in a minute "
                "(free-tier cold start)."
            )
            return
        st.session_state["access_token"] = result["access"]
        st.session_state["refresh_token"] = result["refresh"]
        st.session_state["current_user"] = result["user"]
        st.rerun()


def _render_rate_limit(exc: RateLimitedError) -> None:
    """Render a RateLimitedError with the retry-after window, if available."""
    if exc.retry_after:
        st.error(f"{exc.message} Retry after {exc.retry_after}s.")
    else:
        st.error(exc.message)


def _render_api_error(exc: ApiError) -> bool:
    """Render a generic :class:`ApiError` at Streamlit level.

    Returns ``True`` if the error forced a logout (so the caller
    can ``st.rerun()``), ``False`` otherwise. Mirrors the full
    R7.7 mapping table.
    """
    if isinstance(exc, AuthExpiredError):
        st.warning("Your session expired. Please log in again.")
        for key in ("access_token", "refresh_token", "current_user"):
            st.session_state.pop(key, None)
        return True
    if isinstance(exc, RateLimitedError):
        _render_rate_limit(exc)
    elif isinstance(exc, ApiClientError):
        st.error(exc.message)
    elif isinstance(exc, ApiServerError):
        st.error("Server error — please try again in a moment.")
    elif isinstance(exc, ApiConnectionError):
        st.error(
            "Can't reach the API. Check your connection or retry in a minute "
            "(free-tier cold start)."
        )
    return False


# ---------------------------------------------------------------------------
# Main online-mode entrypoint
# ---------------------------------------------------------------------------


client = get_or_create_client()
render_auth_sidebar(client)

if not st.session_state.get("current_user"):
    st.info("Please log in or register via the sidebar to continue.")
    st.stop()


# Helpers to load the taxonomy statically — we keep the skill-taxonomy
# JSON on the filesystem for the multiselect widget. Phase 1's API
# doesn't expose it as a public endpoint, and shipping the JSON in
# the Streamlit repo is fine for a catalog that changes rarely.
@st.cache_data
def _load_taxonomy_json() -> list[str]:
    """Load the skill taxonomy for the multiselect widget."""
    import json

    path = os.path.join(os.path.dirname(__file__), "data", "skill_taxonomy.json")
    try:
        with open(path) as f:
            return list(json.load(f))
    except FileNotFoundError:
        return []


taxonomy = _load_taxonomy_json()


# ---------------------------------------------------------------------------
# Section 1: Resume paste + profile form
# ---------------------------------------------------------------------------

st.header("📝 Your Profile")

with st.expander("📄 Paste Resume Text (optional)", expanded=False):
    resume_text = st.text_area("Paste your resume here:", height=150, key="resume_input")
    if st.button("Extract Skills"):
        try:
            result = client.parse_resume(resume_text or "")
        except ApiError as exc:
            if _render_api_error(exc):
                st.rerun()
        else:
            extracted = result.get("skills", [])
            st.session_state["extracted_skills"] = extracted
            if extracted:
                st.success(f"Extracted {len(extracted)} skills: {', '.join(extracted)}")
            else:
                st.warning("No skills could be extracted. Please enter your skills manually.")


def _profile_create_or_update() -> None:
    """Render the profile form. Wrapped so error boundary is explicit."""
    existing: dict[str, Any] | None = st.session_state.get("profile")

    with st.form("profile_form"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input(
                "Name",
                value=(existing or {}).get("name", ""),
            )
            experience = st.number_input(
                "Years of Experience",
                min_value=0,
                max_value=50,
                value=(existing or {}).get("experience_years", 0),
            )
        with col2:
            edu_options = ["High School", "Associate", "Bachelor's", "Master's", "PhD"]
            edu_default = (existing or {}).get("education", "Bachelor's")
            education = st.selectbox(
                "Education Level",
                edu_options,
                index=edu_options.index(edu_default) if edu_default in edu_options else 2,
            )
            target_role = st.text_input(
                "Target Job Role",
                value=(existing or {}).get("target_role", ""),
            )

        default_skills = existing["skills"] if existing else st.session_state.get(
            "extracted_skills", []
        )
        skills_input = st.multiselect(
            "Your Skills",
            options=taxonomy,
            default=[s for s in default_skills if s in taxonomy],
            help="Select from taxonomy or type to search",
        )
        submitted = st.form_submit_button("Create / Update Profile")

        if not submitted:
            return

        payload = {
            "name": name,
            "skills": skills_input,
            "experience_years": int(experience),
            "education": education,
            "target_role": target_role,
        }
        try:
            if existing:
                # Partial update: diff the skills list into added/removed.
                # The API supports direct field overrides too, so this
                # is the simplest shape for the Streamlit form.
                before = set(existing["skills"])
                after = set(skills_input)
                patch: dict[str, Any] = {
                    "name": name,
                    "experience_years": int(experience),
                    "education": education,
                    "target_role": target_role,
                    "added_skills": sorted(after - before),
                    "removed_skills": sorted(before - after),
                }
                saved = client.update_profile(existing["id"], patch)
            else:
                saved = client.create_profile(payload)
        except ApiError as exc:
            if _render_api_error(exc):
                st.rerun()
            return
        finally:
            _persist_tokens(client)

        st.session_state["profile"] = saved
        # Invalidate downstream state that depends on the profile.
        st.session_state.pop("gap_result", None)
        st.session_state.pop("roadmap", None)
        st.success(f"Profile saved with {len(saved['skills'])} skills.")
        st.rerun()


_profile_create_or_update()


# Current profile summary
profile_state: dict[str, Any] | None = st.session_state.get("profile")
if profile_state:
    with st.expander("👤 Current Profile", expanded=True):
        col1, col2, col3 = st.columns(3)
        col1.metric("Skills", len(profile_state["skills"]))
        col2.metric("Experience", f"{profile_state['experience_years']} yrs")
        col3.metric("Target", profile_state["target_role"])
        st.write("**Skills:**", ", ".join(profile_state["skills"]))


# ---------------------------------------------------------------------------
# Section 2: Job catalog + gap analysis
# ---------------------------------------------------------------------------


def _render_jobs_and_analysis(profile: dict[str, Any]) -> None:
    st.header("🔍 Job Catalog & Gap Analysis")

    col1, col2 = st.columns(2)
    with col1:
        keyword_filter = st.text_input("Search by job title keyword", key="kw_filter")
    with col2:
        skill_filter = st.selectbox(
            "Filter by required skill", [""] + taxonomy, key="sk_filter"
        )

    try:
        jobs_resp = client.list_jobs(
            keyword=keyword_filter or None,
            skill=skill_filter or None,
        )
    except ApiError as exc:
        if _render_api_error(exc):
            st.rerun()
        return
    finally:
        _persist_tokens(client)

    filtered_jobs = jobs_resp.get("items", [])
    if not filtered_jobs:
        st.info("No jobs match the current filters.")
        return

    job_titles = [f"{j['title']} ({j['experience_level']})" for j in filtered_jobs]
    selected_idx = st.selectbox(
        "Select a job to analyze",
        range(len(job_titles)),
        format_func=lambda i: job_titles[i],
    )
    selected_job = filtered_jobs[selected_idx]

    with st.expander("📋 Job Details", expanded=False):
        st.write(f"**{selected_job['title']}** — {selected_job['experience_level']}")
        st.write(selected_job["description"])
        st.write(f"**Required:** {', '.join(selected_job['required_skills'])}")
        st.write(f"**Preferred:** {', '.join(selected_job['preferred_skills'])}")

    if st.button("🔎 Run Gap Analysis"):
        try:
            analysis = client.create_analysis(profile["id"], selected_job["id"])
        except ApiError as exc:
            if _render_api_error(exc):
                st.rerun()
            return
        finally:
            _persist_tokens(client)

        st.session_state["gap_result"] = analysis
        st.session_state["selected_job"] = selected_job
        # Bust any prior roadmap so the UI re-creates against the new
        # analysis. Phase 1's analyses are immutable, so a new gap
        # means a new roadmap.
        st.session_state.pop("roadmap", None)
        st.rerun()

    # Display gap results if cached.
    analysis = st.session_state.get("gap_result")
    if analysis:
        gap = analysis["gap"]
        cat = analysis.get("categorization")
        st.subheader("📊 Gap Analysis Results")
        col1, col2, col3 = st.columns(3)
        col1.metric("Match", f"{gap['match_percentage']}%")
        col2.metric("Missing Required", len(gap["missing_required"]))
        col3.metric("Missing Preferred", len(gap["missing_preferred"]))
        if gap["match_percentage"] == 100 and not gap["missing_required"]:
            st.success("🎉 You meet all required skills for this role!")

        col1, col2 = st.columns(2)
        with col1:
            st.write("✅ **Matched Required:**", ", ".join(gap["matched_required"]) or "None")
            st.write("✅ **Matched Preferred:**", ", ".join(gap["matched_preferred"]) or "None")
        with col2:
            st.write("❌ **Missing Required:**", ", ".join(gap["missing_required"]) or "None")
            st.write("⚠️ **Missing Preferred:**", ", ".join(gap["missing_preferred"]) or "None")

        if cat:
            st.subheader("🤖 AI Skill Categorization")
            if cat.get("is_fallback"):
                st.info("AI categorization unavailable — showing raw results")
            st.write(cat.get("summary", ""))
            for category, skills in (cat.get("groups") or {}).items():
                st.write(f"**{category}:** {', '.join(skills)}")


if profile_state:
    _render_jobs_and_analysis(profile_state)


# ---------------------------------------------------------------------------
# Section 3: Learning roadmap
# ---------------------------------------------------------------------------


def _render_roadmap(profile: dict[str, Any]) -> None:
    analysis = st.session_state.get("gap_result")
    if not analysis:
        return

    gap = analysis["gap"]
    if not (gap["missing_required"] or gap["missing_preferred"]):
        return

    st.header("🗺️ Learning Roadmap")

    # Lazily create the roadmap for this analysis.
    if "roadmap" not in st.session_state:
        try:
            roadmap = client.create_roadmap(analysis["id"])
        except ApiError as exc:
            if _render_api_error(exc):
                st.rerun()
            return
        finally:
            _persist_tokens(client)
        st.session_state["roadmap"] = roadmap

    roadmap = st.session_state["roadmap"]

    for phase in roadmap["phases"]:
        if not phase["resources"]:
            continue
        st.subheader(f"📅 {phase['label']}")
        for i, res in enumerate(phase["resources"]):
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            status_icon = "✅" if res["completed"] else "⬜"
            col1.write(f"{status_icon} **{res['name']}** ({res['skill']})")
            col2.write(f"📚 {res['resource_type']}")
            col3.write(f"⏱️ {res['estimated_hours']}h")
            if res["completed"]:
                col4.write("Done")
            else:
                btn_key = f"complete_{phase['label']}_{i}"
                if col4.button("Mark Done", key=btn_key):
                    try:
                        updated = client.update_roadmap_resource(
                            roadmap["id"],
                            res["id"],
                            completed=True,
                        )
                    except ApiError as exc:
                        if _render_api_error(exc):
                            st.rerun()
                        return
                    finally:
                        _persist_tokens(client)
                    st.session_state["roadmap"] = updated
                    st.rerun()


if profile_state:
    _render_roadmap(profile_state)
