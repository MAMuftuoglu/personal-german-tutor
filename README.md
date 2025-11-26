# German Notes Wrapper

A Python application that helps you learn German by managing vocabulary and grammar notes with AI assistance. The app uses Google's Gemini AI to answer questions, propose new vocabulary and grammar notes, and export them to Anki for spaced repetition learning.

## Features

- Interactive German language tutoring with AI
- Automatic vocabulary and grammar note extraction
- Export to Anki CSV format with complete information (gender, conjugations, examples)
- Persistent note storage in local markdown files
- Cloud-based file search for quick note retrieval
- Differentiates between vocabulary and grammar notes

## Requirements

- Python 3.14.0 (tested version)
- Google AI Studio API key
- Required Python packages (see `requirements.txt`)

## Setup Instructions

### 1. Clone or Download the Repository

```bash
git clone <repository-url>
cd german_notes_wrapper
```

### 2. Set Up Python Environment

#### Option A: Using Conda (Tested)

1. Create a new conda environment:
```bash
conda create -n german_notes_wrapper python=3.14.0
```

2. Activate the environment:
```bash
conda activate german_notes_wrapper
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

#### Option B: Using venv

1. Create a virtual environment:
```bash
python -m venv venv
```

2. Activate the environment:
   - On Windows:
   ```bash
   venv\Scripts\activate
   ```
   - On macOS/Linux:
   ```bash
   source venv/bin/activate
   ```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

### 3. Get Google AI Studio API Key

1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Sign in with your Google account
3. Click on "Get API Key" or navigate to the API keys section
4. Create a new API key (or use an existing one)
5. Copy the API key

### 4. Configure API Key

1. Create a `.env` file in the project root directory:
```bash
touch .env
```

2. Add your API key to the `.env` file:
```
GOOGLE_API_KEY=your_api_key_here
```

**Important:** Never commit the `.env` file to version control. It's already included in `.gitignore`.

### 5. Verify Installation

Run the application to verify everything is set up correctly:

```bash
python study_tutor.py
```

If you see the welcome message, you're ready to go!

## Usage

### Starting the Application

```bash
python study_tutor.py
```

### Basic Commands

- **Ask questions**: Type any question about German grammar or vocabulary
- **Save notes**: When the tutor proposes new notes, type `y` to save or `n` to skip
- **Export to Anki**: Type `export` to generate/refresh the Anki CSV file but this is needed only if you already have notes in similar structure. If the tutor proposes new vocabulary notes, then those are already appended to the csv so no need for export in such case.
- **Exit**: Type `quit` or `exit` to close the application

### Example Session

```
You: What is the difference between "wissen" and "kennen"?

Tutor: [Provides explanation]

Tutor has 2 new note proposal(s) for you:
--- Proposal 1 of 2 ---
- **wissen** (verb): to know (a fact, information)
- Conjugation (present tense):
    - ich weiß
    - du weißt
    ...
Save this note? (y/n): y

--- Proposal 2 of 2 ---
- **kennen** (verb): to know (a person, place, thing)
...
Save this note? (y/n): y

✅ Saved 2 new note(s) to your file and to anki!
```

### Exporting to Anki

1. Run the application
2. Type `export` when prompted
3. The application will scan all notes and create/update `anki_export.csv`
4. Import the CSV file into Anki:
   - Open Anki
   - File → Import
   - Select `anki_export.csv`
   - Configure import settings (delimiter: semicolon `;`)
   - Import

## File Structure

```
german_notes_wrapper/
├── study_tutor.py          # Main application file
├── requirements.txt        # Python dependencies
├── .env                    # API key (create this, not in repo)
├── .gitignore              # Git ignore rules
├── my_german_notes.md      # Your personal notes (auto-generated)
└── anki_export.csv         # Anki import file (auto-generated)
```

## Note Format

The application expects notes in a specific format:

### Vocabulary Notes
```
- **der Wal** (masc.): whale
- Example: *Der Wal ist groß.* (The whale is large.)
```

### Verb Notes
```
- **wissen** (verb): to know
- Conjugation (present tense):
    - ich weiß
    - du weißt
    - er/sie/es weiß
    - wir wissen
    - ihr wisst
    - sie/Sie wissen
- Past tense (Präteritum): wusste
- Partizip II: gewusst
- Example: *Ich weiß die Antwort.* (I know the answer.)
```

### Grammar Notes
```
- ### Grammar: Dative Case
- The dative case is used for indirect objects...
- Example: *Ich gebe dem Mann das Buch.*
```

## Dependencies

Main dependencies:
- `google-genai`: Google Gemini AI client
- `python-dotenv`: Environment variable management
- Standard library: `os`, `csv`, `re`, `tempfile`, `uuid`, `time`

See `requirements.txt` for the complete list.
