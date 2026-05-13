# Conversation audit / transcript retrieval

Use this when the user asks for the *full transcript* of a lead conversation or when you need to verify exactly what was sent.

## Source of truth
- `lead_state.py get --phone <E.164>` returns the canonical conversation history.
- The `conversation` array is the best source for exact outbound/inbound SMS bodies and timestamps.
- If the lead is also referenced in a webhook/session context, `session_search` can find the session ID, but `lead_state.py` is the record to quote.

## Recommended workflow
1. Retrieve the lead by phone:
   - `python3 ~/.hermes/skills/lead-auto-text/lead_state.py get --phone +1XXXXXXXXXX`
2. Quote the `conversation` entries verbatim, preserving direction and body.
3. Include timestamps only if the user asked for them or if they help resolve ordering.
4. If the user asked for the *whole thread*, do **not** summarize away message bodies — show the actual text.
5. If multiple leads or threads are involved, list them separately and label the phone/name.

## Pitfalls
- Do not rely on memory or a previous summary when the user asks for a transcript.
- Do not merge messages from different sessions unless the lead-state record explicitly contains them.
- If the lead is missing from state, say so plainly instead of reconstructing from partial context.

## Example presentation
- `Richard → Devin: ...`
- `Devin → Richard: ...`
- `Richard → Devin: ...`
