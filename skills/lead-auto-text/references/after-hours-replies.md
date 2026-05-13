# After-hours reply handling

When a lead texts after business hours, the bot should still respond once and acknowledge the time.

## Pattern
- If the inbound message arrives before 8 AM Central or after 8 PM Central, send a short acknowledgment like:
  - "I know it's late, but we can still chat if you'd like."
  - "I know it's early, but we can still chat if you'd like."
- Then continue the conversation normally if the lead wants to keep going.
- Do not send multiple reassurance messages for the same off-hours inbound.

## Goal
- Match the lead's timing.
- Avoid looking like a delayed batch reply.
- Keep the tone natural and contractor-like.
