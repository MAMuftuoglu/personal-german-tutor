import os
import os.path
import time
import tempfile
import uuid
from dotenv import load_dotenv
import re
import csv
from google import genai
from google.genai import types
from rich.console import Console
from rich.markdown import Markdown

# --- 1. Configuration ---

load_dotenv() 
API_KEY = os.environ.get("GOOGLE_API_KEY")

if not API_KEY:
    raise ValueError("Error: GOOGLE_API_KEY not set. Make sure you have a .env file with the key.")

# Initialize the client (used for services like file_search)
try:
    client = genai.Client(api_key=API_KEY)
except Exception as e:
    print("Error initializing Google GenAI Client.")
    print("This can be due to an invalid API key or network issues.")
    raise e


# --- File and Store Names ---
LOCAL_NOTES_FILE = "my_german_notes.md" 
STORE_DISPLAY_NAME = "My German Notes Store"
NOTES_FILE_DISPLAY_NAME = "master_notes_file"
RETRY_COUNT = 3

# Initialize Rich Console
console = Console()

# --- SYSTEM INSTRUCTION (No change) ---
SYSTEM_INSTRUCTION = """
You are a helpful German Language Tutor. Your primary goal is to help me learn 
and expand my personal 'My German Notes' knowledge base. You have to explain 
all grammar and vocabulary in English.

When I ask a question:
1.  FIRST, you MUST search my 'My German Notes' store to find the answer.
2.  If you find the answer in my notes, please use it and let me know.
    - If you find partial information, use what you found and supplement with your 
      general knowledge as needed.
    - If the search fails or returns no results, proceed with your general knowledge.
3.  If you do NOT find the answer in my notes, use your own general 
    knowledge to answer me in English.
4.  **CRITICAL:** After your complete answer, identify ALL new vocabulary words 
    and ALL new grammar concepts that were not in my personal 'My German Notes'.
    - Proposals MUST appear at the END of your response, after your answer.
    - Distinguish between vocabulary (individual words/phrases) and grammar 
      (rules, patterns, structures) - create separate proposals for each type.
    - Add Präsens, Präteritum and Partizip II for verbs
    - Add gender, and plural for nouns
    - If any explanation is needed, add before examples
    - Add examples for each item
5.  You MUST create a separate proposal for EACH new item.
6.  You MUST format EACH proposal on its OWN new line, starting
    with the exact tag `[PROPOSED_NOTE]:`.
7.  **IMPORTANT:** All proposals MUST be formatted in proper Markdown syntax:
    - Use `**bold**` for German words and grammar terms
    - Use `*italic*` for examples and emphasis
    - Use proper markdown lists with `-` or `*`
    - Use `##` for section headers if needed

Example of a correct response with multiple proposals in Markdown:
<The model's answer to the user's question>

[PROPOSED_NOTE]:
- **die Ankunft** (fem.): arrival
- Example: *Die Ankunft des Zuges ist um 14:30 Uhr.*

[PROPOSED_NOTE]:
- wissen;(reg. verb): to know (a fact, information)
- Conjugation (present tense):
    - ich weiß
    - du weißt
    - er/sie/es weiß
    - wir wissen
    - ihr wisst
    - sie/Sie wissen
- Past tense (Präteritum): wusste
- Partizip II: gewusst
- Explanation: The past tense of 'wissen' is 'wusste' and the partizip II is 'gewusst'.
- Example: Ich weiß die Antwort. (I know the answer.)


[PROPOSED_NOTE]:
- ### Grammar: 'zu' Preposition
- 'zu' is a dative-only preposition, meaning the noun that follows it will always be in the dative case.
- Example: *Ich gehe zu dem Bahnhof.* (I go to the train station.)

Never propose grammar or vocabulary notes that are already in my personal 'My German Notes'.
Moreover, if the user's question or the notes found are missing an explanation of the grammar or vocabulary, you must explain it in English.
"""

# --- 2. Helper Functions (Now fully corrected) ---

def _wait_for_operation(operation):
    """Waits for a file processing operation to complete."""
    print("Processing file... (this may take a minute on first upload)")
    # Use operation.done attribute to check completion status
    while not operation.done:
        time.sleep(5)
        # Refresh the operation status
        operation = client.operations.get(operation)
    # Check for errors after operation is done
    if hasattr(operation, 'error') and operation.error:
        raise Exception(f"Operation failed: {operation.error}")
    print("File processing Succeeded.")

def render_note_to_console(title, content, style="bold green"):
    """
    Renders a note to the console using Rich.
    Args:
        title: The title of the note (e.g., "Existing Note", "New Note").
        content: The content of the note (markdown).
        style: The style for the title.
    """
    console.print(f"\n--- {title} ---", style=style)
    console.print(Markdown(content))
    console.print("-" * 20, style="dim")

def _markdown_to_html_for_anki(text):
    """
    Converts markdown to HTML for Anki cards.
    Preserves formatting for vocabulary notes including:
    - Bold text (**word** -> <b>word</b>)
    - Italic text (*text* -> <i>text</i>)
    - Nested lists (conjugations, examples)
    - Indentation for structured content
    """
    if not text:
        return ""
    
    # Split into lines to handle indentation and lists properly
    lines = text.split('\n')
    html_lines = []
    
    for line in lines:
        if not line.strip():
            html_lines.append('<br>')
            continue
        
        # Store original line for indentation calculation (before removing list markers)
        original_line = line
        
        # Convert **bold** to <b>bold</b> first (before processing italic)
        line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
        # Convert *italic* to <i>italic</i> (single asterisks that aren't part of **bold**)
        # This pattern matches single * that aren't preceded or followed by another *
        line = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'<i>\1</i>', line)
        
        # Handle list markers and indentation
        # Count leading spaces/tabs for indentation (use original line before list marker removal)
        indent_match = re.match(r'^(\s*)', original_line)
        indent_level = len(indent_match.group(1)) if indent_match else 0
        
        # Remove list markers (- or *) but preserve the rest of the line
        # Only remove if it's at the start (after whitespace)
        line = re.sub(r'^\s*[\*-]\s+', '', line)
        
        # Add indentation as non-breaking spaces (2 spaces = 1 level of indentation)
        if indent_level > 0:
            indent_spaces = '&nbsp;' * min(indent_level, 8)  # Cap at reasonable level
            line = indent_spaces + line
        
        html_lines.append(line)
    
    # Join with <br> and clean up multiple consecutive <br> tags
    result = '<br>'.join(html_lines)
    result = re.sub(r'(<br>){3,}', '<br><br>', result)  # Max 2 consecutive breaks
    
    return result.strip()

def _html_to_markdown_for_console(html_text):
    """
    Converts Anki-formatted HTML back to a readable string for the console.
    This is necessary because the existing notes are stored as HTML in the CSV/cache,
    but Rich Markdown renderer expects Markdown or plain text, not <br> tags.
    """
    if not html_text:
        return ""
    
    # Replace <br> with newlines
    text = html_text.replace('<br>', '\n')
    
    # Replace &nbsp; with spaces
    text = text.replace('&nbsp;', ' ')
    
    # Replace <b> and </b> with ** (or just remove if we want plain text, but ** is better for Rich)
    text = text.replace('<b>', '**').replace('</b>', '**')
    
    # Replace <i> and </i> with *
    text = text.replace('<i>', '*').replace('</i>', '*')
    
    return text

def _parse_note_for_anki(note_content):
    """
    Parses a full note block (which could be multi-line) to extract vocabulary for Anki.
    
    Vocabulary notes should include:
    - Gender (for nouns): (masc.), (fem.), (neut.)
    - Meaning/definition: the English translation
    - Conjugation (for verbs): Präsens, Präteritum, Partizip II
    - Examples: usage examples in German with translations
    
    Returns (front, back) for vocabulary notes, or (None, None) for grammar notes.
    Grammar notes are explicitly detected and skipped.
    """
    lines = note_content.strip().split('\n')
    if not lines:
        return None, None

    # Explicit grammar detection: check if note starts with "### Grammar:" or contains "Grammar:" header
    first_line_lower = lines[0].strip().lower()
    if '### grammar:' in first_line_lower or first_line_lower.startswith('### grammar'):
        return None, None, 'grammar'
    
    # Check if any line contains a grammar header pattern
    for line in lines[:3]:  # Check first 3 lines for grammar indicators
        if re.search(r'###\s*Grammar:', line, re.IGNORECASE):
            return None, None, 'grammar'

    # Vocabulary detection: look for bolded German word/phrase
    # Pattern matches: "- **der Wal** (masc.): whale" or "* **wissen** (verb): to know"
    header_match = re.search(r'^\s*[\*-]\s+\*\*(.*?)\*\*(.*)', lines[0])
    
    if header_match:
        # Front = The bolded German word/phrase (e.g., "der Wal", "wissen")
        front = header_match.group(1).strip()
        
        # Back = ALL content from the note:
        # - First line remainder: gender, type, meaning (e.g., "(masc.): whale")
        # - All subsequent lines: conjugations, examples, additional info
        back_part1 = header_match.group(2).strip()
        back_part2 = "\n".join(lines[1:]).strip()
        
        # Combine all content to ensure nothing is lost
        # This captures: gender, meaning, conjugations (Präsens, Präteritum, Partizip II), examples
        full_back_content = f"{back_part1}\n{back_part2}".strip()
        
        # Convert the complete "back" content to HTML for Anki
        # This preserves all formatting: bold, italic, lists, indentation
        back_html = _markdown_to_html_for_anki(full_back_content)
        
        return front, back_html, None
        
    # If no vocabulary pattern found, it's not a vocabulary note
    return None, None, None

def find_or_create_store():
    """Finds the persistent store or creates a new one."""
    if not os.path.exists(LOCAL_NOTES_FILE):
        print(f"Creating new local file: {LOCAL_NOTES_FILE}")
        with open(LOCAL_NOTES_FILE, "w", encoding="utf-8") as f:
            f.write("# My German Notes\n\nThis file is the master copy.\n\n---\n\n")

    print(f"Checking for existing store named '{STORE_DISPLAY_NAME}'...")
    for store in client.file_search_stores.list():
        if store.display_name == STORE_DISPLAY_NAME:
            print(f"Found existing store: {store.name}")
            return store

    print("Store not found. Creating a new one...")
    file_store = client.file_search_stores.create(
        config={'display_name': STORE_DISPLAY_NAME}
    )
    print(f"Store created: {file_store.name}")
    
    print(f"Uploading initial notes file: {LOCAL_NOTES_FILE}...")
    op = client.file_search_stores.upload_to_file_search_store(
        file_search_store_name=file_store.name,
        file=LOCAL_NOTES_FILE,
        config={'display_name': NOTES_FILE_DISPLAY_NAME}
    )
    _wait_for_operation(op)
    print("Initial notes uploaded successfully.")
    return file_store

def update_notes_in_store(file_store, notes_list):
    """
    Updates notes in the store. Uploads new notes as separate documents
    """
    if not notes_list:
        return
    
    print("Appending notes to local file...")
    # Write all notes at once to local file
    with open(LOCAL_NOTES_FILE, "a", encoding="utf-8") as f:
        for note_content in notes_list:
            f.write(note_content)
    print(f"Local file updated with {len(notes_list)} note(s).")
    # All documents in the store are searchable together
    print("Uploading new notes as incremental update...")
    notes_appended = "\n".join(notes_list)
    # Create a temporary file with just the new note
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as tmp_file:
        tmp_file.write(notes_appended)
        tmp_file_path = tmp_file.name
    
    try:
        # Upload as a separate document with unique name
        unique_name = f"{NOTES_FILE_DISPLAY_NAME}_{uuid.uuid4().hex[:8]}"
        op = client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=file_store.name,
            file=tmp_file_path,
            config={'display_name': unique_name}
        )
        _wait_for_operation(op)
        print("✅ Uploaded new note")
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_file_path)
        except OSError:
            pass
    
    print("✅ Your cloud notes are now up-to-date!")
    
def load_anki_cache():
    """Loads existing Anki notes into a dictionary {front: back}."""
    export_file = "anki_export.csv"
    cache = {}
    if not os.path.exists(export_file):
        return cache
    
    try:
        with open(export_file, "r", encoding="utf-8") as csvfile:
            reader = csv.reader(csvfile, delimiter=';')
            for row in reader:
                if len(row) >= 2:
                    cache[row[0]] = row[1]
    except Exception as e:
        print(f"Warning: Could not load Anki cache: {e}")
    return cache

def save_note(note_content, response_notes, anki_notes_cache):
    """
    Parses a single new note and checks for duplicates before saving to Anki CSV.
    """
    export_file = "anki_export.csv"
    
    front, back, reason = _parse_note_for_anki(note_content)
    
    # If parsing failed (e.g., it was a grammar note), just stop.
    if not front:
        if reason == 'grammar':
            print("This note is a grammar note, saving to md file.")
            response_notes.append(f"\n{note_content}\n---")
            return 1
        else:
            print("Not a valid note, skipping.")
        return 0

    # Duplicate Detection
    if front in anki_notes_cache:
        existing_back = anki_notes_cache[front]
        # Prepare content for display
        # Existing note is in HTML (from cache) -> Convert to Markdown for display
        existing_back_md = _html_to_markdown_for_console(existing_back)
        
        # New note back part (back_html) -> Convert that to Markdown for display too, 
        # or we could use the original markdown if we had it easily. 
        # Since _html_to_markdown_for_console is simple, let's use it on the generated HTML 
        # to ensure they look comparable.
        back_md = _html_to_markdown_for_console(back)

        # Render Existing Note
        render_note_to_console("Existing Note", f"{front}\n\n{existing_back_md}", style="bold yellow")
        
        # Render New Note
        render_note_to_console("New Note", f"{front}\n\n{back_md}", style="bold green")
        
        valid_choice = False
        while not valid_choice:
            choice = input("Duplicate! (k)eep existing or (o)verwrite with new? ").lower().strip()
            if choice == 'o':
                valid_choice = True
                # Overwrite Logic
                anki_notes_cache[front] = back
                try:
                    with open(export_file, "w", newline='', encoding="utf-8") as csvfile:
                        writer = csv.writer(csvfile, delimiter=';')
                        writer.writerow(["Front (German)", "Back (English)"])
                        for f, b in anki_notes_cache.items():
                            writer.writerow([f, b])
                    print(f"✅ Updated entry in {export_file}.")
                    return 1
                except Exception as e:
                    print(f"Error rewriting Anki CSV: {e}")
                    return 0
            elif choice == 'k':
                valid_choice = True
                print("Keeping existing note.")
                return 0
            else:
                print("Please enter 'k' or 'o'.")

    # New Note Logic
    # Check if the file exists. If not, write the header row first.
    file_exists = os.path.exists(export_file)
    
    try:
        with open(export_file, "a", newline='', encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile, delimiter=';')
            
            if not file_exists:
                writer.writerow(["Front (German)", "Back (English)"])
            
            writer.writerow([front, back])
            
        print(f"✅ Also appended to {export_file} for Anki.")
        anki_notes_cache[front] = back
        return 1
        
    except Exception as e:
        print(f"Error appending to Anki CSV: {e}")
        return 0

# --- 3. Main Conversation Loop (Corrected) ---

def main():
    try:
        # Configuration and Cache Loading
        file_store = find_or_create_store()
        anki_notes_cache = load_anki_cache()
        print(f"Loaded {len(anki_notes_cache)} notes from Anki cache.")

        print("\n--- 🤖 German Tutor is Ready ---")
        print(f"Your notes are being managed in '{LOCAL_NOTES_FILE}'")
        print("Ask me anything about German. Type 'quit' to exit.")
        print("---------------------------------")

        while True:
            user_question = input("\nYou: ")
            if user_question.lower() in ["quit", "exit"]:
                client.close()
                print("\nAuf Wiedersehen!")
                break

            current_retry_count = 0
            while True:
                try:
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=user_question,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            tools=[
                                types.Tool(
                                    file_search=types.FileSearch(
                                        file_search_store_names=[file_store.name]
                                    )
                                )
                            ]
                        )
                    )
                    if response.text:
                        break
                    else:
                        print("No response from the model. Retrying...")
                        current_retry_count += 1
                        if current_retry_count < RETRY_COUNT:
                            time.sleep(2)
                            continue
                        else:
                            print("Max retries reached. Please try again later.")
                            raise Exception("No response from the model.")
                except Exception as e:
                    # Check if it's a 503 error (service unavailable)
                    error_code = getattr(e, 'code', None)
                    if error_code == 503:
                        current_retry_count += 1
                        if current_retry_count < RETRY_COUNT:
                            wait_time = 2 ** current_retry_count  # Exponential backoff: 2, 4, 8 seconds
                            print(f"Service Unavailable. Retrying in {wait_time} seconds... (Attempt {current_retry_count}/{RETRY_COUNT})")
                            time.sleep(wait_time)
                            continue
                        else:
                            print("Max retries reached. Please try again later.")
                            raise e
                    else:
                        raise e
            response_text = response.text
            
            if "[PROPOSED_NOTE]:" not in response_text:
                print(f"\nTutor:\n{response_text}")
                continue 
            
            parts = response_text.split("[PROPOSED_NOTE]:")
            tutor_answer = parts[0].strip()
            proposed_notes = parts[1:] 

            print(f"\nTutor:\n{tutor_answer}") 

            print("\n---------------------------------")
            print(f"Tutor has {len(proposed_notes)} new note proposal(s) for you:")
            
            # Accumulate notes from this response
            response_notes = []
            notes_saved_count = 0
            for i, note_content in enumerate(proposed_notes, 1):
                note_content = note_content.strip()
                if not note_content: 
                    continue
                print(f"\n--- Proposal {i} of {len(proposed_notes)} ---")
                render_note_to_console(f"Note {i}", note_content, style="bold cyan")
                # print(note_content)
                # print("---------------------")
                
                should_ask_again = True
                while should_ask_again:
                    save_choice = input("Save this note? (y/n): ").lower().strip()
                    
                    if save_choice == 'y' or save_choice == '':
                        should_ask_again = False
                        notes_saved_count += save_note(note_content, response_notes, anki_notes_cache)
                    elif save_choice == 'n':
                        print("Okay, I won't save it.")
                        should_ask_again = False
                    else:
                        print("Please enter 'y' or 'n'.")
            
            # Save all notes from this response at once
            if notes_saved_count > 0:
                print(f"\n✅ Saving {notes_saved_count} new note(s)...")
                update_notes_in_store(file_store, response_notes)
                saved_count = notes_saved_count
                response_notes = []
                notes_saved_count = 0
                print(f"✅ Saved {saved_count} new note(s) to your file!")

    except Exception as e:
        print("\n--- An Error Occurred ---")
        print(e)

if __name__ == "__main__":
    main()