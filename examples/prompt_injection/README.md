# Prompt Injection

Reproduce after starting StayFlow:

```bash
curl -X POST http://localhost:8000/api/feedback/analyze -H 'Content-Type: application/json' -d @examples/prompt_injection/input.json
```
