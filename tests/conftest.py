import os

# Local .env may enable paid providers; automated tests must remain deterministic.
os.environ["LLM_PROVIDER"] = "mock"
os.environ.pop("OPENAI_API_KEY", None)
