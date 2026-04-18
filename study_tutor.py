import time
import re
import json
import urllib.request
from google import genai
from google.genai import types
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.markup import escape
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from typing import List

# --- 1. Configuration ---

from config import API_KEY, ANKI_CONNECT_URL, ANKI_DECK_NAME, ANKI_MODEL_NAME, RETRY_COUNT, MODEL_NAME

if not API_KEY:
    raise ValueError("Error: GOOGLE_API_KEY not set. Make sure you have a .env file with the key.")

# Initialize the client (used for services like file_search)
try:
    client = genai.Client(api_key=API_KEY)
except Exception as e:
    print("Error initializing Google GenAI Client.")
    print("This can be due to an invalid API key or network issues.")
    raise e

# Initialize Rich Console
console = Console()

# --- SYSTEM INSTRUCTION (No change) ---
def get_system_instruction(is_check_yomitan: bool):
    return f"""
You are a helpful German Language Tutor. Your primary goal is to help me learn 
and expand my personal 'My German Notes' knowledge base. You have to explain 
all grammar and vocabulary in English.

When I ask a question:
1.  Use your own general knowledge to answer me in English.
2.  **CRITICAL:** After your complete answer, identify ALL new vocabulary words.
    - Proposals MUST appear at the END of your response, after your answer.
    - Add Präsens, Präteritum and Partizip II for verbs
    - Add gender, and plural for nouns
    - If any explanation is needed, add before examples
    - Add examples for each item
    - **CONSTRAINT**: You MUST NOT prepare a proposal for grammar rules, only make explanations for grammar rules in the answer.
3.  You MUST create a separate proposal for EACH new item.
4.  You MUST format EACH proposal on its OWN new line, starting
    with the exact tag "{ "[CARD_FEEDBACK]:" if is_check_yomitan else "[PROPOSED_NOTE]:" }".
5.  **IMPORTANT:** All proposals MUST be formatted in proper Markdown syntax:
    - Use `**bold**` for German words and grammar terms
    - Use `*italic*` for examples and emphasis
    - Use proper markdown lists with `-` or `*`
    - Use `##` for section headers if needed
6. Add explanation only when a clear explanation is needed. Don't add explanation for every item if the explanation is basic.

Example of a correct response with multiple proposals in Markdown:
<The model's answer to the user's question>

{"[CARD_FEEDBACK]:" if is_check_yomitan else "[PROPOSED_NOTE]:"}
- **die Ankunft** (fem.): arrival
- Example: *Die Ankunft des Zuges ist um 14:30 Uhr.*

{"[CARD_FEEDBACK]:" if is_check_yomitan else "[PROPOSED_NOTE]:"}
(reg. verb): to believe

<div style="text-align: left;">Conjugation (Präsens - present tense):
    ich glaube (I believe)
    du glaubst (you believe)
    er/sie/es glaubt (he/she/it believes)
    wir glauben (we believe)
    ihr glaubt (you all believe)
    sie/Sie glauben (they/you (formal) believe)

Präteritum (simple past): glaubte
Partizip II (past participle): geglaubt (haben)

Explanation: This verb is used to express belief, opinion, or faith.

Examples:
    Ich glaube, dass es morgen regnen wird. (I believe that it will rain tomorrow.)
    Er glaubt an Gott. (He believes in God.)
    Hast du mir geglaubt? (Did you believe me?)
</div>"""

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
    if hasattr(operation, "error") and operation.error:
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
    lines = text.split("\n")
    html_lines: List[str] = []

    for line in lines:
        if not line.strip():
            html_lines.append("<br>")
            continue

        # Store original line for indentation calculation (before removing list markers)
        original_line = line

        # Convert **bold** to <b>bold</b> first (before processing italic)
        line = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", line)
        # Convert *italic* to <i>italic</i> (single asterisks that aren't part of **bold**)
        # This pattern matches single * that aren't preceded or followed by another *
        line = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", line)

        # Handle list markers and indentation
        # Count leading spaces/tabs for indentation (use original line before list marker removal)
        indent_match = re.match(r"^(\s*)", original_line)
        indent_level = len(indent_match.group(1)) if indent_match else 0

        # Remove list markers (- or *) but preserve the rest of the line
        # Only remove if it's at the start (after whitespace)
        line = re.sub(r"^\s*[\*-]\s+", "", line)

        # Add indentation as non-breaking spaces (2 spaces = 1 level of indentation)
        if indent_level > 0:
            indent_spaces = "&nbsp;" * min(indent_level, 8)  # Cap at reasonable level
            line = indent_spaces + line

        html_lines.append(line)

    # Join with <br> and clean up multiple consecutive <br> tags
    result = "<br>".join(html_lines)
    result = re.sub(r"(<br>){3,}", "<br><br>", result)  # Max 2 consecutive breaks

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
    text = html_text.replace("<br>", "\n")

    # Replace &nbsp; with spaces
    text = text.replace("&nbsp;", " ")

    # Replace <b> and </b> with ** (or just remove if we want plain text, but ** is better for Rich)
    text = text.replace("<b>", "**").replace("</b>", "**")

    # Replace <i> and </i> with *
    text = text.replace("<i>", "*").replace("</i>", "*")

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
    lines = note_content.strip().split("\n")
    if not lines:
        return None, None, None

    # Explicit grammar detection: check if note starts with "### Grammar:" or contains "Grammar:" header
    first_line_lower = lines[0].strip().lower()
    if "### grammar:" in first_line_lower or first_line_lower.startswith("### grammar"):
        return None, None, "grammar"

    # Check if any line contains a grammar header pattern
    for line in lines[:3]:  # Check first 3 lines for grammar indicators
        if re.search(r"###\s*Grammar:", line, re.IGNORECASE):
            return None, None, "grammar"

    # Vocabulary detection: look for bolded German word/phrase
    # Pattern matches: "- **der Wal** (masc.): whale" or "* **wissen** (verb): to know"
    header_match = re.search(r"^\s*[\*-]\s+\*\*(.*?)\*\*(.*)", lines[0])

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


def anki_invoke(action, **params):
    """
    Helper to invoke AnkiConnect actions.
    """
    request_data = {"action": action, "version": 6, "params": params}
    request_json = json.dumps(request_data).encode("utf-8")

    try:
        req = urllib.request.Request(ANKI_CONNECT_URL, request_json)
        with urllib.request.urlopen(req) as response:
            res_content = response.read().decode("utf-8")
            res = json.loads(res_content)
            
            if not isinstance(res, dict):
                raise Exception(f"Unexpected response type: {type(res)}")
            
            if "error" in res and res["error"] is not None:
                raise Exception(res["error"])
            
            if "result" not in res:
                raise Exception("Response is missing 'result' field")
                
            return res["result"]
    except Exception as e:
        print(f"Error invoking AnkiConnect '{action}': {e}")
        return None


def ensure_deck_exists():
    """Checks if the configured deck exists, creates it if not."""
    try:
        decks = anki_invoke("deckNames")
        if decks and ANKI_DECK_NAME not in decks:
            print(f"Deck '{ANKI_DECK_NAME}' not found. Creating it...")
            anki_invoke("createDeck", deck=ANKI_DECK_NAME)
            print(f"Created deck '{ANKI_DECK_NAME}'.")
    except Exception as e:
        print(f"Could not ensure deck exists: {e}")


def load_anki_cache():
    """
    Loads existing Anki notes into a dictionary {front: {'back': back, 'id': noteId}}.
    Using AnkiConnect to fetch notes from the specific deck.
    """
    cache = {}
    try:
        ensure_deck_exists()

        # 1. Find all notes in our deck
        note_ids = anki_invoke("findNotes", query=f'deck:"{ANKI_DECK_NAME}"')

        if not note_ids:
            return cache

        # 2. Get note info for these IDs
        # Chunking requests to avoid timeouts (User request: 100 per chunk, 0.5s buffer)
        chunk_size = 100
        for i in range(0, len(note_ids), chunk_size):
            chunk = note_ids[i : i + chunk_size]
            notes_info = anki_invoke("notesInfo", notes=chunk)

            if notes_info:
                for note in notes_info:
                    # dependent on model having "Front" and "Back" fields
                    fields = note.get("fields", {})
                    front_field = fields.get("Front", {})
                    back_field = fields.get("Back", {})

                    if front_field and back_field:
                        front_val = front_field.get("value", "").strip()
                        back_val = back_field.get("value", "")
                        note_id = note.get("noteId")

                        if front_val:
                            # Store both back content and ID so we can update later
                            cache[front_val] = {"back": back_val, "id": note_id}

            # Tiny buffer between chunks
            time.sleep(0.5)

    except Exception as e:
        print(f"Warning: Could not load Anki cache from AnkiConnect: {e}")
        print("Make sure Anki is running and AnkiConnect is installed.")

    return cache


def save_note(note_content, response_notes, anki_notes_cache):
    """
    Parses a single new note and checks for duplicates before saving to Anki via AnkiConnect.
    """

    front, back, reason = _parse_note_for_anki(note_content)

    # If parsing failed (e.g., it was a grammar note), just stop.
    if not front:
        print("Not a valid note, skipping.")
        return 0

    # Duplicate Detection
    if front in anki_notes_cache:
        # Get existing note data (now a dict with back and id)
        existing_data = anki_notes_cache[front]
        existing_back = existing_data.get("back", "")
        note_id = existing_data.get("id")

        # Prepare content for display
        existing_back_md = _html_to_markdown_for_console(existing_back)
        back_md = _html_to_markdown_for_console(back)

        # Render Existing Note
        render_note_to_console("Existing Note", f"{front}\n\n{existing_back_md}", style="bold yellow")

        # Render New Note
        render_note_to_console("New Note", f"{front}\n\n{back_md}", style="bold green")

        valid_choice = False
        while not valid_choice:
            choice = input("Duplicate! (k)eep existing or (o)verwrite with new? ").lower().strip()
            if choice == "o":
                valid_choice = True
                # Overwrite Logic via AnkiConnect
                try:
                    anki_invoke("updateNoteFields", note={"id": note_id, "fields": {"Front": front, "Back": back}})
                    print(f"✅ Updated entry in Anki (ID: {note_id}).")
                    # Update cache
                    anki_notes_cache[front]["back"] = back
                    return 1
                except Exception as e:
                    print(f"Error updating note in Anki: {e}")
                    return 0
            elif choice == "k":
                valid_choice = True
                print("Keeping existing note.")
                return 0
            else:
                print("Please enter 'k' or 'o'.")

    # New Note Logic
    try:
        result = anki_invoke(
            "addNote",
            note={
                "deckName": ANKI_DECK_NAME,
                "modelName": ANKI_MODEL_NAME,
                "fields": {"Front": front, "Back": back},
                "options": {"allowDuplicate": False},
                "tags": ["german_tutor"],
            },
        )

        if result:
            print(f"✅ Added new note to Anki deck '{ANKI_DECK_NAME}' (ID: {result}).")
            anki_notes_cache[front] = {"back": back, "id": result}
            return 1
        else:
            print("Failed to add note (AnkiConnect returned None).")
            return 0

    except Exception as e:
        print(f"Error adding note to Anki: {e}")
        return 0


def get_notes_by_tag(tag):
    """Retrieves all notes with a specific tag."""
    try:
        note_ids = anki_invoke("findNotes", query=f"tag:{tag}")
        if not note_ids:
            return []

        notes_info = anki_invoke("notesInfo", notes=note_ids)
        return notes_info
    except Exception as e:
        print(f"Error fetching notes by tag '{tag}': {e}")
        return []


def _format_html_for_display(html_content):
    """Formats raw HTML for readable display in the Rich console."""
    text = re.sub(r'(<br\s*/?>)', r'\1\n', html_content)
    text = re.sub(r'(</div>)', r'\1\n', text)
    text = escape(text)
    return text.strip()


def get_yomitan_system_prompt():
    """Returns the system prompt for checking/reformatting Yomitan cards."""
    return """
You are a German language assistant. Your task is to review and reformat Anki card content.

INPUT: You will receive the Front (word) and Back (explanation) of an Anki card.
OUTPUT: You must return the corrected/reformatted Front and Back fields using the markers below.

You MUST output your result in this exact format:
[FRONT]: <the corrected front value>
[BACK]: <the corrected back value as a single line of HTML>

Structure for the Back field:
1. Meaning (and grammatical info if applicable) - This should be at the top, standard alignment (usually centered by Anki styling, so just plain text).
2. Plural (if it's a noun and exists) - Plain text.
3. Conjugation (if it's a verb) - LEFT ALIGNED.
   - Conjugation of a verb MUST include the auxiliary verbs used for it in Partizip II. In some cases where both used, include an explanation under the EXPLANATION section.
   - For Präteritum, only include the 1st person singular form.
4. Explanations (if present) - LEFT ALIGNED.
5. Examples - LEFT ALIGNED.

HTML Structure Rule:
- For the top part (Meaning, Plural), use plain text or simple <div> if needed, but DO NOT force left alignment.
- For ALL subsequent sections (Conjugation, Explanation, Examples), you MUST wrap them in `<div style="text-align: left;">...</div>` blocks.
- Use `<br>` for line breaks.
- Use `&nbsp;` for indentation in lists/tables if needed.

Example of the REQUIRED Output Format:
[FRONT]: sich (Dat.) etwas vorstellen
[BACK]: (verb, weak, reflexive with dative object): to imagine something<br><br><div style="text-align: left;">Präsens:</div><div style="text-align: left;">&nbsp; &nbsp; ich stelle mir vor</div><div style="text-align: left;">&nbsp; &nbsp; du stellst dir vor</div><div style="text-align: left;">&nbsp; &nbsp; er/sie/es stellt sich vor</div><div style="text-align: left;">&nbsp; &nbsp; wir stellen uns vor</div><div style="text-align: left;">&nbsp; &nbsp; ihr stellt euch vor</div><div style="text-align: left;">&nbsp; &nbsp; sie/Sie stellen sich vor</div><div style="text-align: left;"><br></div><div style="text-align: left;">Präteritum: stellte sich vor</div><div style="text-align: left;">Partizip II: sich vorgestellt (haben)</div><div style="text-align: left;"><br></div><div style="text-align: left;">Explanation: This reflexive verb is used when you imagine something in your mind.</div><div style="text-align: left;"><br></div><div style="text-align: left;">Example: <i>Ich kann mir ein Leben ohne Musik nicht vorstellen.</i> (I cannot imagine a life without music.)</div>

CRITICAL:
- Do NOT wrap the output in markdown code blocks (```html ... ```). Output the raw values directly after the markers.
- The [BACK] value MUST be a single line of HTML — use <br> instead of actual newlines.
- Ensure the conjugation list is complete for the requested tense if available.
- If the original card doesn't have certain info (like examples), do not invent it unless it's obviously missing and you can confidently provide it (but prefer sticking to the original content's intent, just reformatting).
- However, if the input card IS missing standard conjugations for a verb, PLEASE ADD THEM in the correct format.
- If the input card IS missing gender/plural for a noun, PLEASE ADD THEM.
- If the input card IS missing auxiliary verb for partizip II for a verb, PLEASE ADD THEM.
- The [FRONT] should be the clean German word/phrase (with article for nouns, reflexive pronouns for reflexive verbs, etc.).
"""


def _parse_yomitan_response(response_text):
    """
    Parses the LLM response to extract [FRONT] and [BACK] values.
    Returns (front, back) or (None, None) if parsing fails.
    """
    front_match = re.search(r'\[FRONT\]:\s*(.+?)(?=\n\[BACK\]:|$)', response_text, re.DOTALL)
    back_match = re.search(r'\[BACK\]:\s*(.+)', response_text, re.DOTALL)

    if not front_match or not back_match:
        return None, None

    front = front_match.group(1).strip()
    back = back_match.group(1).strip()

    # Clean up any markdown code block wrappers the LLM might add despite instructions
    back = re.sub(r'^```html\s*', '', back)
    back = re.sub(r'\s*```$', '', back)

    return front, back


def check_yomitan_cards(client, anki_notes_cache):
    """
    Fetches cards tagged 'yomitan', processes them one-by-one,
    asks the LLM to review/reformat, and lets the user confirm
    before updating the card in Anki.
    """
    print("Fetching notes with tag 'yomitan'...")
    notes = get_notes_by_tag("yomitan")

    if not notes:
        print("No notes found with tag 'yomitan'.")
        return

    print(f"Found {len(notes)} notes. Processing one by one...")
    processed_note_ids = []

    for i, note in enumerate(notes):
        note_id = note.get("noteId")
        fields = note.get("fields", {})
        front = fields.get("Front", {}).get("value") or fields.get("Word", {}).get("value", "")
        back = fields.get("Back", {}).get("value") or fields.get("Glossary", {}).get("value", "")

        if not front:
            console.print(f"[yellow]Skipping card {i+1}/{len(notes)} — no front value.[/yellow]")
            continue

        # Display current card
        console.rule(f"Card {i+1}/{len(notes)}")
        console.print(f"[bold]Front:[/bold] {front}")
        console.print(Panel(_format_html_for_display(back), title="Current Back", style="yellow"))

        # Send to LLM
        back_plain = _html_to_markdown_for_console(back)
        prompt = f"Front: {front}\nBack (Current Content):\n{back_plain}"

        console.print("[dim]Asking Gemini to review...[/dim]")
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=get_yomitan_system_prompt(),
                    temperature=0.1,
                ),
            )

            if not response.text:
                console.print("[red]No response from the model. Skipping.[/red]")
                continue

            new_front, new_back = _parse_yomitan_response(response.text)

            if not new_front or not new_back:
                console.print("[red]Could not parse model response. Raw output:[/red]")
                console.print(response.text)
                continue

            # Show proposed changes
            existing_info = " [yellow](Exists in cache!)[/yellow]" if new_front in anki_notes_cache else ""
            console.print(f"\n[bold]Proposed Front:[/bold] {new_front}{existing_info}")
            console.print(Panel(_format_html_for_display(new_back), title="Proposed Back", style="green"))

            # Confirmation loop
            while True:
                choice = console.input("[bold cyan]Apply this change? (y)es / (n)o / (q)uit: [/bold cyan]").lower().strip()

                if choice in ('y', 'yes', ''):
                    try:
                        anki_invoke("updateNoteFields", note={"id": note_id, "fields": {"Front": new_front, "Back": new_back}})
                        console.print("[bold green]✅ Updated.[/bold green]")
                        processed_note_ids.append(note_id)
                    except Exception as e:
                        console.print(f"[bold red]❌ Update failed: {e}[/bold red]")
                    break
                elif choice in ('n', 'no'):
                    console.print("[yellow]Skipped.[/yellow]")
                    processed_note_ids.append(note_id)
                    break
                elif choice in ('q', 'quit'):
                    console.print("[bold red]Exiting Yomitan check.[/bold red]")
                    # Remove tag from cards processed so far before quitting
                    if processed_note_ids:
                        anki_invoke("removeTags", notes=processed_note_ids, tags="yomitan")
                        console.print(f"[dim]Removed 'yomitan' tag from {len(processed_note_ids)} processed card(s).[/dim]")
                    return
                else:
                    console.print("Invalid choice. Please enter y, n, or q.")

        except Exception as e:
            console.print(f"[red]Error processing card: {e}[/red]")
            continue

    # Remove 'yomitan' tag from all processed notes
    if processed_note_ids:
        anki_invoke("removeTags", notes=processed_note_ids, tags="yomitan")
        console.print(f"\n[bold green]Done! Removed 'yomitan' tag from {len(processed_note_ids)} processed card(s).[/bold green]")
    else:
        console.print("\n[yellow]No cards were processed.[/yellow]")


# --- 3. Main Conversation Loop (Corrected) ---


# ... imports ...


def main():
    try:
        # Configuration and Cache Loading
        anki_notes_cache = load_anki_cache()
        print(f"Loaded {len(anki_notes_cache)} notes from Anki cache.")

        print("\n--- 🤖 German Tutor is Ready ---")
        print("Ask me anything about German. Type 'quit' to exit.")
        print("---------------------------------")

        # Create a PromptSession
        session = PromptSession(history=InMemoryHistory())

        while True:
            try:
                user_question = session.prompt("\nYou: ")
            except KeyboardInterrupt:
                continue
            except EOFError:
                break

            if user_question.lower() in ["quit", "exit"]:
                client.close()
                print("\nAuf Wiedersehen!")
                break

            if user_question.lower() == "check yomitan":
                check_yomitan_cards(client, anki_notes_cache)
                continue

            current_retry_count = 0
            while True:
                try:
                    response = client.models.generate_content(
                        model=MODEL_NAME,
                        contents=user_question,
                        config=types.GenerateContentConfig(
                            system_instruction=get_system_instruction(is_check_yomitan=False),
                        ),
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
                    error_code = getattr(e, "code", None)
                    if error_code == 503:
                        current_retry_count += 1
                        if current_retry_count < RETRY_COUNT:
                            wait_time = 2**current_retry_count  # Exponential backoff: 2, 4, 8 seconds
                            print(
                                f"Service Unavailable. Retrying in {wait_time} seconds... (Attempt {current_retry_count}/{RETRY_COUNT})"
                            )
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

                # Check for existence to add indicator
                front_check, _, _ = _parse_note_for_anki(note_content)
                title_suffix = ""
                if front_check and front_check in anki_notes_cache:
                    title_suffix = " [EXISTING]"

                render_note_to_console(f"Note {i}{title_suffix}", note_content, style="bold cyan")

                should_ask_again = True
                while should_ask_again:
                    save_choice = input("Save this note? (y/n): ").lower().strip()

                    if save_choice == "y" or save_choice == "":
                        should_ask_again = False
                        notes_saved_count += save_note(note_content, response_notes, anki_notes_cache)
                    elif save_choice == "n":
                        should_ask_again = False
                    else:
                        print("Please enter 'y' or 'n'.")

            # Save all notes from this response at once
            if notes_saved_count > 0:
                saved_count = notes_saved_count
                response_notes = []
                notes_saved_count = 0
                print(f"✅ Saved {saved_count} new note(s) to your file!")

    except Exception as e:
        print("\n--- An Error Occurred ---")
        print(e)


if __name__ == "__main__":
    main()
