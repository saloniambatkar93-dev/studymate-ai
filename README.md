# 📚 StudyMate AI

An AI study assistant that answers questions from **your own uploaded PDF notes** and shows
which document and page each answer came from.

Built for the AWS Builder Center challenge **"Give Your Agent a Tool"** with Python, Streamlit,
the **Strands Agents SDK**, **Amazon Bedrock** and **Amazon S3**.

## The idea in one paragraph

A plain AI model knows general facts but **cannot see your lecture notes**. StudyMate first runs
that plain agent (the "before"), then gives the *same* model one custom tool,
`search_study_notes`. The agent now decides when to search your PDFs, reads the returned
passages, and answers with citations like *(Source: biology.pdf, p. 2)*.

```
 You ──question──▶ Streamlit (app.py)
                       │
                       ▼
              Strands Agent (agent.py) ──▶ Amazon Bedrock model
                       │  decides to call the tool
                       ▼
        search_study_notes (tools.py)  ──▶ keyword (BM25) search over page chunks
                       │ reads documents from
                       ▼
        storage.py:  local folder (default)  OR  Amazon S3 bucket
```

## Why this tool, and what it adds

* **Why:** students' real problem is "what do *my* notes say?", and no model can answer that
  from training data alone.
* **New capability:** retrieve passages from private documents at question time, so answers are
  grounded in the student's material and carry document names and page numbers.
* **Honesty built in:** sources shown in the UI come from what the tool *actually returned*,
  not from what the model says. If the tool wasn't called or found nothing, the UI warns you.

## Features

| Feature | Needs AWS? |
|---|---|
| Upload PDFs, library view, sample notes | No (local mode) |
| **Retrieval test tab** (see exactly what the tool finds) | No |
| Ask questions, explain simply, exam answers, MCQs, Before-vs-After demo | **Yes: Amazon Bedrock** (billed per use) |
| Store documents in S3 | **Yes: Amazon S3** (optional; tiny cost) |

## Honest limitations

* Retrieval is **keyword search (BM25)**, not semantic. Questions that share words with the notes
  work best. (A natural upgrade: Amazon Bedrock Knowledge Bases or embeddings.)
* Works with **text-based PDFs**. Scanned/image PDFs have no text and are rejected with a message (no OCR).
* Page numbers are the PDF's physical page order (page 1 = first page), which may differ from
  printed page labels.
* The bundled sample notes are `.txt` files (with page markers) so the project is fully
  readable; run `python make_sample_pdfs.py` to turn them into real PDFs for upload testing.
* AI answers can still contain mistakes. Always check the cited passage.

## Windows setup (step by step)

Use **PowerShell**. Replace `C:\Users\you` with your own folder.

1. **Install Python 3.10+** from <https://www.python.org/downloads/>. On the first installer screen,
   tick **"Add python.exe to PATH"**. Then open a new PowerShell and check:
   ```powershell
   python --version
   ```
2. **Unzip** `studymate-ai.zip` and go into the folder:
   ```powershell
   cd C:\Users\you\studymate-ai
   ```
3. **Create and activate a virtual environment:**
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```
   If PowerShell says scripts are disabled, run this once, then activate again:
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
   ```
   (Using Command Prompt instead? Activate with `.venv\Scripts\activate.bat`.)
   You should see `(.venv)` at the start of the prompt.
4. **Install packages:**
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements-dev.txt
   ```
5. **Create your settings file:**
   ```powershell
   copy .env.example .env
   ```
6. **Run the free tests (no AWS needed):**
   ```powershell
   python -m pytest -q
   ```
7. **Start the app:**
   ```powershell
   streamlit run app.py
   ```
   Your browser opens at <http://localhost:8501>. Click **Load sample notes**, then open the
   **Retrieval test** tab and press **Search**. This proves retrieval works without any AI or AWS.
8. **Turn on the AI:** follow [AWS_SETUP.md](AWS_SETUP.md), then check everything with:
   ```powershell
   python check_setup.py
   python check_setup.py --invoke     # one tiny Bedrock call (small cost)
   ```

Optional: `python make_sample_pdfs.py` creates `sample_pdfs\*.pdf` you can upload in the sidebar.

## Using the app

1. Sidebar: upload PDFs → **Save to library** (or **Load sample notes**).
2. **Ask StudyMate** tab: choose *Explain simply*, *Exam answer*, *Multiple-choice quiz* or
   *Just answer*, type a question, press **Ask StudyMate**.
3. Under each answer you'll see **Sources retrieved from your notes** (file + page) and the
   search queries the agent used.
4. **Before vs. After** tab: runs the no-tool agent and the tool agent side by side.

## Tests

```powershell
python -m pytest -q
```

33 tests cover PDF reading and page numbers, chunking, ranking, the "no documents / no match /
storage error" paths, the Strands tool object, storage (local and a fake S3 client), friendly
AWS error messages, and a headless launch of the real Streamlit app. **None call AWS**, so they
do not prove Bedrock access works. `check_setup.py --invoke` and the Before-vs-After tab do.

## Project layout

| File | Purpose |
|---|---|
| `app.py` | Streamlit interface |
| `agent.py` | Baseline agent, study agent, prompts, error handling |
| `tools.py` | PDF reading, chunking, BM25 search, the `search_study_notes` Strands tool |
| `storage.py` | Local-folder and S3 storage with validation |
| `errors.py` | Friendly messages for AWS errors |
| `check_setup.py` | Setup checker |
| `make_sample_pdfs.py` | Makes real sample PDFs |
| `sample_docs/` | 3 short sample notes |
| `tests/` | pytest tests |
| `AWS_SETUP.md`, `DEMO_SCRIPT.md` | AWS steps; demo and submission guide |

## Security notes

* No credentials appear in code. AWS access comes from the standard credential chain
  (`aws configure`, SSO, or environment variables).
* `.env` is git-ignored; `.env.example` contains no secrets.
* The IAM policy in AWS_SETUP.md is least-privilege (one bucket prefix + model invoke only).
* Uploaded file names are sanitised; size (15 MB) and PDF header are checked.
* S3 uploads request server-side encryption (SSE-S3).
