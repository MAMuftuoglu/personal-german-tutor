
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.environ.get("GOOGLE_API_KEY")

ANKI_CONNECT_URL = "http://localhost:8765"
ANKI_DECK_NAME = "Default"
ANKI_MODEL_NAME = "Basic"
RETRY_COUNT = 3
MODEL_NAME="gemini-3.1-flash-lite-preview"