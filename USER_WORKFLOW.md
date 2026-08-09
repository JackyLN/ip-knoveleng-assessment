# StayFlow user workflow

1. Start with `docker compose up -d --build` and open <http://localhost:8000>.
2. Choose a sample shortcut or enter fictional guest feedback.
3. Optionally provide guest, booking, and property identifiers. More identifiers improve grounding; missing records remain explicit.
4. Submit once. OpenAI mode may make several paid requests for classification, tool selection, and report drafting.
5. Review classification separately from sentiment and urgency.
6. Verify guest, booking, and property context plus every workflow/policy ID.
7. Read missing information and contradictions without assuming either source is correct.
8. Resolve every human-review reason before any operational or financial action.
9. Use the execution trace to confirm required tools were validated and attempted.

Try `GST-1003` / `BKG-2005` for a pending refund, `GST-1001` / `BKG-2006` / `HTL-LON-01` for overbooking, or `GST-1002` / `BKG-2002` / `HTL-TOR-01` for a door-lock safety case.

All data is fictional. Never paste real guest data or an API key into the form. Stop locally with `docker compose down`.
