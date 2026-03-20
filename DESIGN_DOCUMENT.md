# Design Documentation: Skill-Bridge Career Navigator

## Table of Contents
1. [Tech Stack & Why](#tech-stack--why)
2. [Project Architecture](#project-architecture)
3. [Module Breakdown & Functions](#module-breakdown--functions)
4. [Data Layer](#data-layer)
5. [AI Integration](#ai-integration)
6. [UI Design](#ui-design)
7. [Testing Strategy](#testing-strategy)
8. [Future Enhancements](#future-enhancements)

---

## Tech Stack & Why

| Technology | Role | Why We Chose It |
|---|---|---|
| **Python 3.12** | Core language | Fast prototyping, rich ecosystem for AI/data, widely understood |
| **Streamlit** | Web UI framework | Zero HTML/CSS/JS needed. Built-in session state, reactive widgets, forms — ideal for a 4-6 hour prototype. One file = full web app |
| **Groq API (Llama 3.3 70B)** | AI engine | Free tier (30 req/min), OpenAI-compatible SDK, fast inference (~1s responses), no credit card required |
| **python-dotenv** | Config management | Loads `.env` file for API keys — keeps secrets out of code |
| **pytest** | Unit testing | Industry standard, minimal boilerplate, great fixture system |
| **Hypothesis** | Property-based testing | Generates random inputs to find edge cases humans miss (available but optional for MVP) |
| **JSON** | Data storage | Simple, human-readable, no database setup needed for a prototype |

**Why Streamlit over Flask?**
Flask would require writing HTML templates, CSS, JavaScript, and route handlers. Streamlit gives us an interactive web app with just Python — forms, buttons, metrics, columns, expanders — all built-in. For a timed prototype, this saves 2+ hours.

**Why Groq over OpenAI/Gemini?**
Groq offers a genuinely free tier with no credit card. The SDK is OpenAI-compatible (easy to swap later). Llama 3.3 70B is a strong model for categorization tasks. Response times are under 1 second.

**Why no database?**
Streamlit's `st.session_state` gives us in-memory persistence for the session. For a prototype demo, this is sufficient. A real product would use PostgreSQL or similar.

---

## Project Architecture

```
skill-bridge/
├── app.py                      # Streamlit UI — the entry point
├── models.py                   # Data models (7 dataclasses)
├── profile_manager.py          # Profile CRUD + validation
├── resume_parser.py            # Skill extraction from text
├── profile_printer.py          # Profile → readable text
├── job_catalog.py              # Load, validate, search jobs
├── gap_analyzer.py             # Skill gap comparison engine
├── ai_engine.py                # Groq AI + rule-based fallback
├── roadmap_generator.py        # Learning plan builder
├── data/
│   ├── jobs.json               # 10 synthetic job postings
│   ├── skill_taxonomy.json     # 64 skill entries
│   └── learning_resources.json # 97 learning resources
├── tests/
│   ├── conftest.py             # Shared test fixtures
│   └── test_gap_analysis.py    # Unit tests (happy path + edge case)
├── .env.example                # API key placeholder
├── .gitignore                  # Keeps .env and caches out of git
├── requirements.txt            # Python dependencies
└── README.md                   # Project overview and instructions
```

**Data flow:**
```
User Input → Profile Manager → Session State
                                    ↓
Job Catalog ← search/filter ← User Selection
                                    ↓
Gap Analyzer ← (profile + job) → GapResult
                                    ↓
AI Engine (Groq or Fallback) → CategorizationResult
                                    ↓
Roadmap Generator → Phased Learning Plan
                                    ↓
User marks completed → Recalculate match %
```

---

## Module Breakdown & Functions

### 1. `models.py` — Data Models

Seven Python dataclasses that define the shape of all data in the system:

| Dataclass | Purpose | Key Fields |
|---|---|---|
| `UserProfile` | User's career profile | name, skills (list), experience_years, education, target_role |
| `JobPosting` | A job from the catalog | title, description, required_skills, preferred_skills, experience_level |
| `GapResult` | Output of gap analysis | matched_required, missing_required, matched_preferred, missing_preferred, match_percentage |
| `CategorizationResult` | AI categorization output | groups (dict of category → skills), summary (text), is_fallback (bool) |
| `LearningResource` | A single course/project/cert | name, skill, resource_type, estimated_hours, url, completed |
| `RoadmapPhase` | One time period in the roadmap | label ("Month 1-2"), resources (list) |
| `Roadmap` | The full learning plan | phases (3 RoadmapPhases) |

### 2. `profile_manager.py` — Profile CRUD & Validation

| Function | What It Does |
|---|---|
| `create_profile(name, skills, experience_years, education, target_role)` | Validates all inputs, deduplicates skills, returns `(UserProfile, notification)`. Raises `ValueError` with specific messages for: missing name/target_role, empty skills, skills > 30, skill name > 100 chars |
| `update_profile(profile, added_skills, removed_skills)` | Returns a new UserProfile with skills added/removed. Validates the resulting list |
| `save_profile(profile)` | Stores profile in `st.session_state["user_profile"]` |
| `load_profile()` | Retrieves profile from session state, or `None` |
| `_deduplicate_skills(skills)` | Internal helper — removes case-insensitive duplicates, returns `(deduped_list, had_duplicates)` |

**Validation rules enforced:**
- Name and target_role are required (non-empty)
- Skills list: 1–30 items
- Each skill name: ≤ 100 characters
- Duplicates auto-removed with user notification

### 3. `resume_parser.py` — Skill Extraction

| Function | What It Does |
|---|---|
| `load_taxonomy(path)` | Loads `skill_taxonomy.json` — a flat array of 64 skill strings |
| `parse_resume(text, taxonomy)` | Scans text for skills using case-insensitive word-boundary regex. Multi-word skills (e.g., "Machine Learning") matched as phrases. Returns list of found skills, empty list if none |

**How matching works:**
- Taxonomy sorted longest-first (so "Machine Learning" matches before "Machine")
- Each skill becomes a regex pattern: `\bMachine Learning\b` with `re.IGNORECASE`
- Deduplicates results (case-insensitive)

### 4. `profile_printer.py` — Profile Serialization

| Function | What It Does |
|---|---|
| `format_profile(profile)` | Converts a UserProfile to readable text: "Name: ...\nSkills: Python, SQL, ...\nExperience: 2 years\n..." |

Designed so that `parse_resume(format_profile(profile))` produces a superset of the original skills (round-trip property).

### 5. `job_catalog.py` — Job Data Management

| Function | What It Does |
|---|---|
| `load_jobs(path)` | Loads `jobs.json`, validates each entry has all required fields (title, description, required_skills, preferred_skills, experience_level). Skips malformed entries with a logged warning. Raises `FileNotFoundError` if file missing |
| `search_jobs(jobs, keyword, skill)` | Filters jobs by title keyword OR required skill (case-insensitive). Returns all jobs if both filters empty |

### 6. `gap_analyzer.py` — Skill Gap Comparison

| Function | What It Does |
|---|---|
| `analyze_gap(profile, job)` | Compares user skills against job requirements (case-insensitive). Partitions into matched_required, missing_required, matched_preferred, missing_preferred. Calculates `match_percentage = round(matched_required / total_required × 100)`. Returns 100% if job has 0 required skills |

### 7. `ai_engine.py` — AI Categorization with Fallback

This is the core AI module. It defines an abstract interface with two implementations:

| Class/Function | What It Does |
|---|---|
| `SkillCategorizerInterface` (ABC) | Abstract base — defines `categorize(missing_skills, matched_skills) → CategorizationResult` |
| `GroqCategorizer` | Calls Groq API (Llama 3.3 70B) with a prompt asking it to categorize skills into groups and produce a summary. 5-second timeout. On any error, falls back to `FallbackCategorizer` |
| `FallbackCategorizer` | Rule-based: maps skills to categories using a keyword dictionary (Programming Languages, Cloud & Infrastructure, Data & ML, Soft Skills, etc.). Generates a 2-4 sentence summary from templates |
| `get_categorizer()` | Factory function: returns `GroqCategorizer` if `GROQ_API_KEY` is set, otherwise `FallbackCategorizer` |

**Groq prompt design:**
```
You are a career advisor. Categorize these missing skills into groups
(e.g. Programming Languages, Cloud & Infrastructure, Data & ML, DevOps, Soft Skills, Other).
Also provide a 2-4 sentence summary of the person's skill gaps.

Missing skills: Docker, AWS, REST APIs
Matched skills: Python, SQL, Git

Respond in JSON with keys 'groups' (dict) and 'summary' (string).
```

**Fallback activation triggers:**
- `GROQ_API_KEY` not set → use fallback directly
- API timeout (>5 seconds) → catch, log, use fallback
- Any API error → catch, log with timestamp, use fallback

### 8. `roadmap_generator.py` — Learning Plan Builder

| Function | What It Does |
|---|---|
| `generate_roadmap(gap, resources)` | Maps missing skills to learning resources across 3 phases: "Month 1-2", "Month 3-4", "Month 5-6". Required skills placed in earlier phases, preferred in later. Creates placeholder resources if no match found |
| `mark_completed(roadmap, resource_name)` | Returns new Roadmap with the named resource marked as completed |
| `recalculate_match(profile, job, roadmap)` | Recalculates match % treating completed resources' skills as acquired |
| `_load_resources(path)` | Loads `learning_resources.json` into LearningResource objects |

**Phase distribution logic:**
- Required-missing skills → Phase 0 ("Month 1-2") and Phase 1 ("Month 3-4")
- Preferred-missing skills → Phase 1 ("Month 3-4") and Phase 2 ("Month 5-6")
- Skills split evenly within their priority group

---

## Data Layer

### `skill_taxonomy.json` (64 entries)
A flat array of skill strings covering: programming languages (Python, Java, JavaScript, Go, Rust, etc.), frameworks (React, Django, Flask, FastAPI), cloud (AWS, Azure, GCP), databases (SQL, PostgreSQL, MongoDB, Redis), DevOps (Docker, Kubernetes, Terraform, CI/CD), data science (Pandas, NumPy, TensorFlow, PyTorch), security (Cybersecurity, Penetration Testing, SIEM), and soft skills (Communication, Leadership, Agile, Scrum).

### `jobs.json` (10 postings)
Roles: Backend Developer, Frontend Developer, Full Stack Developer, Data Scientist, DevOps Engineer, Cloud Architect, ML Engineer, Cybersecurity Analyst, Mobile Developer, Project Manager. Each has 3-5 required skills and 3-5 preferred skills from the taxonomy.

### `learning_resources.json` (97 resources)
Each resource has: name, skill, type (course/project/certification), estimated_hours, and a placeholder URL. Covers all skills that appear in job postings.

All data is synthetic — no real personal information, no scraped content.

---

## AI Integration

### How It Works
1. User runs gap analysis → produces lists of missing and matched skills
2. `get_categorizer()` checks if `GROQ_API_KEY` exists in environment
3. If yes → `GroqCategorizer` sends a structured prompt to Llama 3.3 70B asking for JSON output with skill groups and a summary
4. Response is parsed (handles markdown code fences), returned as `CategorizationResult`
5. If anything fails → `FallbackCategorizer` uses keyword mapping to group skills and template-based summary

### Fallback Behavior
The UI clearly shows when fallback is active with an info banner: "AI categorization unavailable — showing raw results". The fallback produces the same data structure so the rest of the app works identically.

---

## UI Design

The Streamlit app is a single-page layout with 3 main sections that appear progressively:

### Section 1: Profile Creation
- **Resume paste** (optional) — expandable text area with "Extract Skills" button
- **Profile form** — name, experience, education dropdown, target role, skill multiselect from taxonomy
- **Current profile display** — metrics (skill count, experience, target) + skill list

### Section 2: Job Catalog & Gap Analysis
*Only appears after profile is created*
- **Search/filter** — keyword text input + skill dropdown filter
- **Job selector** — dropdown of matching jobs with experience level
- **Job details** — expandable section with description and skill lists
- **Gap analysis button** — triggers analysis + AI categorization
- **Results dashboard** — match %, missing/matched counts as metrics, skill breakdown in columns, AI categorization with grouped skills and summary

### Section 3: Learning Roadmap & Updates
*Only appears after gap analysis is run*
- **Phased roadmap** — 3 sections (Month 1-2, 3-4, 5-6) with resource cards showing name, type, hours, and "Mark Done" button
- **Progress tracking** — updated match % with delta indicator
- **Profile update form** — add/remove skills with re-analysis trigger, shows before/after match comparison

---

## Testing Strategy

### Unit Tests (`tests/test_gap_analysis.py`)
| Test | What It Verifies |
|---|---|
| `test_happy_path_gap_analysis` | Profile with Python/SQL/Git against Backend Dev job → correctly identifies REST APIs as missing, 75% match |
| `test_edge_case_zero_skills` | Empty profile → all required skills missing, 0% match |
| `test_full_match` | Profile with all required skills → 100% match, no missing required |

### Test Fixtures (`tests/conftest.py`)
Shared fixtures for: sample UserProfile, sample JobPosting, sample taxonomy, sample LearningResources.

### Running Tests
```bash
cd skill-bridge
pytest tests/ -v
```

---

## Future Enhancements

If given more time, the next priorities would be:

1. **Real job board integration** — pull live postings from LinkedIn/Indeed APIs
2. **Resume PDF upload** — OCR-based parsing instead of text paste
3. **Persistent storage** — SQLite or PostgreSQL for user accounts and progress tracking
4. **Mock interview generator** — AI generates interview questions based on the user's skill gaps
5. **Property-based tests** — Hypothesis tests for all 15 correctness properties defined in the design
6. **Visual charts** — Plotly/Altair charts for skill gap visualization and progress over time
7. **Multi-role comparison** — compare your profile against multiple jobs simultaneously
