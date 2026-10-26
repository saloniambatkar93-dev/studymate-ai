# Demo Script (about 4 minutes) and Honest Submission Guide

**Rule for the video: show real results, including imperfect ones. Don't edit out failures or claim anything you didn't show.**

## Before recording
1. `.env` has working AWS settings; `python check_setup.py --invoke` passes.
2. `streamlit run app.py`. Sidebar → **Load sample notes** (and optionally upload a PDF of your own).
3. Have a second terminal open with `python -m pytest -q` ready.

## Scene 1: The problem (30 s)
"Students have notes, but a normal AI model can't read them. Here's StudyMate's original agent, with no tools."

## Scene 2: Original agent, BEFORE the tool (45 s)
Open **Before vs. After**, keep the default question
*"According to my notes, where in the chloroplast does the Calvin cycle occur?"*, press **Run both agents**,
and point at the **left** column. Expected behavior (read what actually appears): the no-tool agent should
say it can't see your notes and, at best, give labelled general knowledge. Say: "It has no way to open my files."

## Scene 3: Why this tool (30 s)
"The missing capability is *reading the student's own documents*. So I gave the agent one tool,
`search_study_notes`. It splits PDFs into page-level chunks, ranks them with BM25 keyword search, and returns
passages with file name and page number. No extra paid service is needed for retrieval."

## Scene 4: Improved agent, AFTER the tool (45 s)
Point at the **right** column of the same run. Show: the answer, the **Sources retrieved** chips
(file · page), the search queries used, and expand **Show retrieved passages**. Say: "These sources come from what the tool
actually returned, not from what the model claims."

## Scene 5: Study features (45 s)
**Ask StudyMate** tab → *Explain simply* → "photosynthesis". Then *Exam answer* → "Newton's second law".
Then *Multiple-choice quiz* (3 questions) → "Industrial Revolution inventions".

## Scene 6: Honesty and errors (30 s)
Ask something not in the notes (e.g. "Explain quantum chromodynamics"). Show that the app warns it found nothing relevant
and does not invent a citation. Optionally show the **Retrieval test** tab (works without AWS) and the passing tests.

## Scene 7: AWS and wrap-up (15 s)
"Amazon Bedrock powers the model; Amazon S3 can store the documents (switch with `STUDYMATE_STORAGE=s3`). Strands Agents ties it together."
(Only say the S3 line if you actually ran S3 mode in the demo.)

---

## Submission write-up template (fill in with your real results)

**Project:** StudyMate AI. A study assistant that answers from the student's own PDF notes.

**Original agent (before):** A Strands agent on Amazon Bedrock with no tools. When asked about uploaded notes it
[describe what you actually saw].

**Tool added:** `search_study_notes`, a custom Python `@tool` that searches page-level chunks of uploaded PDFs
(BM25 keyword retrieval) and returns passages with document name and page number.

**Why this tool:** [your reason: students need answers grounded in *their* material].

**New capability:** Retrieval from private documents at question time, with source citations; study modes
(simple explanation, exam answer, MCQs).

**AWS services used:** Amazon Bedrock [model ID you used]; Amazon S3 [only if you used it].

**What I verified:** [e.g. "33 local tests pass"; "Before-vs-After demo ran against Bedrock on <date>"; "S3 upload worked in <region>"].

**Known limitations:** keyword (not semantic) search; text PDFs only (no OCR); answers may contain errors.

**Honesty checklist (tick only what's true):**
- [ ] I ran the app against real Bedrock and saw the tool being called.
- [ ] Every claim in my video/write-up was demonstrated.
- [ ] I did not claim document access in any scene where retrieval wasn't shown working.
- [ ] No AWS keys appear in my repo (check `git status`; `.env` is ignored).
- [ ] I listed the limitations above.
