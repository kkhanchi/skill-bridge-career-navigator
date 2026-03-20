"""Skill-Bridge Career Navigator — Streamlit Application."""

import sys
import os
import streamlit as st

# Ensure the skill-bridge directory is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import UserProfile, Roadmap
from profile_manager import create_profile, update_profile, save_profile, load_profile
from resume_parser import load_taxonomy, parse_resume
from profile_printer import format_profile
from job_catalog import load_jobs, search_jobs
from gap_analyzer import analyze_gap
from ai_engine import get_categorizer
from roadmap_generator import generate_roadmap, mark_completed, recalculate_match, _load_resources

st.set_page_config(page_title="Skill-Bridge Career Navigator", page_icon="🎯", layout="wide")
st.title("🎯 Skill-Bridge Career Navigator")
st.caption("Bridge the gap between your skills and your dream role")

# --- Load static data ---
@st.cache_data
def cached_taxonomy():
    return load_taxonomy(os.path.join(os.path.dirname(__file__), "data", "skill_taxonomy.json"))

@st.cache_data
def cached_jobs():
    try:
        return load_jobs(os.path.join(os.path.dirname(__file__), "data", "jobs.json"))
    except FileNotFoundError:
        return None

@st.cache_data
def cached_resources():
    return _load_resources(os.path.join(os.path.dirname(__file__), "data", "learning_resources.json"))

taxonomy = cached_taxonomy()
all_jobs = cached_jobs()
all_resources = cached_resources()

# ============================================================
# SECTION 1: Profile Creation & Resume Parsing
# ============================================================
st.header("📝 Your Profile")

if all_jobs is None:
    st.error("Job data is currently unavailable. Please contact support.")

# Resume parsing
with st.expander("📄 Paste Resume Text (optional)", expanded=False):
    resume_text = st.text_area("Paste your resume here:", height=150, key="resume_input")
    if st.button("Extract Skills"):
        extracted = parse_resume(resume_text, taxonomy)
        if extracted:
            st.session_state["extracted_skills"] = extracted
            st.success(f"Extracted {len(extracted)} skills: {', '.join(extracted)}")
        else:
            st.warning("No skills could be extracted. Please enter your skills manually.")

# Profile form
with st.form("profile_form"):
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Name", value=st.session_state.get("profile_name", ""))
        experience = st.number_input("Years of Experience", min_value=0, max_value=50, value=0)
    with col2:
        education = st.selectbox("Education Level", ["High School", "Associate", "Bachelor's", "Master's", "PhD"])
        target_role = st.text_input("Target Job Role", value=st.session_state.get("profile_target", ""))

    # Skills input
    default_skills = st.session_state.get("extracted_skills", [])
    skills_input = st.multiselect(
        "Your Skills",
        options=taxonomy,
        default=[s for s in default_skills if s in taxonomy],
        help="Select from taxonomy or type to search"
    )

    submitted = st.form_submit_button("Create / Update Profile")
    if submitted:
        try:
            profile, notification = create_profile(name, skills_input, experience, education, target_role)
            save_profile(profile)
            st.session_state["profile_name"] = name
            st.session_state["profile_target"] = target_role
            if notification:
                st.info(notification)
            st.success(f"Profile created with {len(profile.skills)} skills!")
        except ValueError as e:
            st.error(str(e))

# Show current profile
profile = load_profile()
if profile:
    with st.expander("👤 Current Profile", expanded=True):
        col1, col2, col3 = st.columns(3)
        col1.metric("Skills", len(profile.skills))
        col2.metric("Experience", f"{profile.experience_years} yrs")
        col3.metric("Target", profile.target_role)
        st.write("**Skills:**", ", ".join(profile.skills))

# ============================================================
# SECTION 2: Job Catalog & Gap Analysis
# ============================================================
if profile and all_jobs is not None:
    st.header("🔍 Job Catalog & Gap Analysis")

    col1, col2 = st.columns(2)
    with col1:
        keyword_filter = st.text_input("Search by job title keyword", key="kw_filter")
    with col2:
        skill_filter = st.selectbox("Filter by required skill", [""] + taxonomy, key="sk_filter")

    filtered_jobs = search_jobs(all_jobs, keyword=keyword_filter, skill=skill_filter)

    if filtered_jobs:
        job_titles = [f"{j.title} ({j.experience_level})" for j in filtered_jobs]
        selected_idx = st.selectbox("Select a job to analyze", range(len(job_titles)),
                                     format_func=lambda i: job_titles[i])
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

            # AI categorization
            categorizer = get_categorizer()
            cat_result = categorizer.categorize(gap.missing_required + gap.missing_preferred,
                                                 gap.matched_required + gap.matched_preferred)
            st.session_state["categorization"] = cat_result

    # Display gap results
    if "gap_result" in st.session_state:
        gap = st.session_state["gap_result"]
        cat = st.session_state.get("categorization")

        st.subheader("📊 Gap Analysis Results")

        # Match percentage
        col1, col2, col3 = st.columns(3)
        col1.metric("Match", f"{gap.match_percentage}%")
        col2.metric("Missing Required", len(gap.missing_required))
        col3.metric("Missing Preferred", len(gap.missing_preferred))

        if gap.match_percentage == 100 and not gap.missing_required:
            st.success("🎉 You meet all required skills for this role!")

        # Matched / Missing breakdown
        col1, col2 = st.columns(2)
        with col1:
            st.write("✅ **Matched Required:**", ", ".join(gap.matched_required) or "None")
            st.write("✅ **Matched Preferred:**", ", ".join(gap.matched_preferred) or "None")
        with col2:
            st.write("❌ **Missing Required:**", ", ".join(gap.missing_required) or "None")
            st.write("⚠️ **Missing Preferred:**", ", ".join(gap.missing_preferred) or "None")

        # AI Categorization
        if cat:
            st.subheader("🤖 AI Skill Categorization")
            if cat.is_fallback:
                st.info("AI categorization unavailable — showing raw results")
            st.write(cat.summary)
            if cat.groups:
                for category, skills in cat.groups.items():
                    st.write(f"**{category}:** {', '.join(skills)}")

# ============================================================
# SECTION 3: Learning Roadmap & Profile Updates
# ============================================================
if "gap_result" in st.session_state and profile:
    gap = st.session_state["gap_result"]
    selected_job = st.session_state.get("selected_job")

    if gap.missing_required or gap.missing_preferred:
        st.header("🗺️ Learning Roadmap")

        # Generate or load roadmap
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
                                new_match = recalculate_match(profile, selected_job, roadmap)
                                st.session_state["gap_result"].match_percentage = new_match
                            st.rerun()
                    else:
                        col4.write("Done")

        # Recalculated match
        if selected_job:
            current_match = recalculate_match(profile, selected_job, roadmap)
            prev_match = st.session_state.get("prev_match", current_match)
            if current_match != prev_match:
                st.metric("Updated Match", f"{current_match}%", delta=f"+{current_match - prev_match}%")

    # Profile Update Section
    st.header("🔄 Update Your Profile")
    with st.form("update_form"):
        new_skills = st.multiselect("Add Skills", options=[s for s in taxonomy if s not in profile.skills],
                                     key="add_skills_select")
        remove_skills = st.multiselect("Remove Skills", options=profile.skills, key="remove_skills_select")
        update_submitted = st.form_submit_button("Update & Re-Analyze")

        if update_submitted and (new_skills or remove_skills):
            try:
                updated = update_profile(profile, added_skills=new_skills, removed_skills=remove_skills)
                save_profile(updated)
                # Re-run gap analysis
                if selected_job:
                    old_match = gap.match_percentage
                    new_gap = analyze_gap(updated, selected_job)
                    st.session_state["gap_result"] = new_gap
                    st.session_state["roadmap_stale"] = True

                    categorizer = get_categorizer()
                    cat_result = categorizer.categorize(
                        new_gap.missing_required + new_gap.missing_preferred,
                        new_gap.matched_required + new_gap.matched_preferred
                    )
                    st.session_state["categorization"] = cat_result

                    st.success(f"Profile updated! Match: {old_match}% → {new_gap.match_percentage}%")
                else:
                    st.success("Profile updated!")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
