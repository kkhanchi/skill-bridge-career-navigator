# Skill-Bridge Career Navigator

## Candidate Name
Kartik Khanchi

## Scenario Chosen
**Scenario 2: Skill-Bridge Career Navigator**

## Estimated Time Spent
~5 hours

---

## The Problem

Students and early-career professionals often find a "skills gap" between their academic knowledge and the specific technical requirements of job postings. Navigating multiple job boards and certification sites makes it difficult to see a clear path from their current skill set to their "dream role."

There is no single tool that takes what you know, compares it against what the market demands, and tells you exactly what to learn and in what order. The result is wasted time, scattered effort, and a lack of confidence when applying for roles.

## What We're Solving

We built a career navigation platform that:

1. **Identifies your skills** — paste your resume or manually select from a taxonomy of 60+ skills
2. **Compares against real job requirements** — a catalog of 10 job roles (Backend Dev, Data Scientist, DevOps Engineer, etc.) with required and preferred skills
3. **Shows your exact skill gaps** — a clear dashboard showing what you have, what you're missing, and your match percentage
4. **Uses AI to categorize and summarize gaps** — powered by Groq (Llama 3.3 70B), the AI groups your missing skills into categories (Programming, Cloud, Data & ML, Soft Skills) and gives you a plain-English summary of where you stand
5. **Generates a personalized learning roadmap** — a phased plan (Month 1-2, 3-4, 5-6) with specific courses, projects, and certifications to close each gap
6. **Tracks your progress** — mark resources as completed, add new skills, and re-analyze to see your match percentage improve

## Target Audience

- **Recent Graduates** looking to understand which certifications make them competitive
- **Career Switchers** needing to identify transferable skills between industries
- **Mentors** looking for a data-backed way to guide their mentees' development

## Why This Matters

Without a tool like this, the typical workflow is: browse job postings → feel overwhelmed by requirements → Google random courses → lose motivation. Skill-Bridge replaces that with a structured, AI-assisted path from "where I am" to "where I want to be."

---

## Quick Start

### Prerequisites
- Python 3.10+
- A Groq API key (free at [console.groq.com](https://console.groq.com)) — optional, the app works without it using rule-based fallback

### Run Commands
```bash
cd skill-bridge
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your GROQ_API_KEY (optional)
streamlit run app.py
```

### Test Commands
```bash
cd skill-bridge
pytest tests/ -v
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Frontend/UI | Streamlit |
| AI Engine | Groq API (Llama 3.3 70B) |
| Fallback AI | Rule-based keyword categorizer |
| Language | Python 3.12 |
| Testing | pytest + Hypothesis |
| Data | Synthetic JSON (no real PII) |

## Core Features (MVP)

- **Profile Creation** — manual entry or resume text parsing with skill extraction
- **Job Catalog** — 10 synthetic job postings with search/filter
- **Gap Analysis** — required vs preferred skill matching with match percentage
- **AI Categorization** — Groq-powered skill grouping and summary (with rule-based fallback)
- **Learning Roadmap** — phased plan with courses, projects, certifications
- **Progress Tracking** — mark completed, update skills, re-analyze

## AI Integration & Fallback

The AI engine uses Groq's free-tier Llama 3.3 70B model to:
- Categorize missing skills into meaningful groups
- Generate a natural-language summary of the user's strengths and gaps

**Fallback:** If the API key is missing, the API errors, or the request times out (>5 seconds), the system automatically falls back to a rule-based keyword categorizer that groups skills using a predefined mapping. The UI clearly labels when fallback is active.

## Data Safety
- All data is synthetic — no real personal information
- API keys stored in `.env` (gitignored)
- `.env.example` provided with placeholder values

---

## AI Disclosure

- **Did you use an AI assistant?** Yes (Claude)
- **How did you verify suggestions?** Reviewed all generated code, ran tests, manually tested the UI flow
- **Example of a rejected suggestion:** The AI suggested using a SQLite database for storing user profiles and session data. I rejected this because Streamlit's built-in `st.session_state` was sufficient for a prototype demo, and adding a database layer would have added setup complexity and eaten into the timebox without meaningfully improving the demo experience.

## Tradeoffs & Prioritization

- **What did you cut?** Property-based tests (Hypothesis), visual polish, persistent storage, mock interview feature
- **What would you build next?** Real job board API integration, user accounts with database persistence, mock interview generator, resume PDF upload with OCR
- **Known limitations:** Session-based storage (data lost on refresh), synthetic job data only, Groq free tier rate limits (30 req/min)
