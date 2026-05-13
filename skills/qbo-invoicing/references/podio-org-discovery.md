# Podio Org Discovery

Compact notes from Podio probing in this workspace.

## Verified endpoints

- `GET https://api.podio.com/org/` returns visible orgs for the authenticated account.
- `GET https://api.podio.com/space/org/{org_id}` returns the spaces in that org.
- `GET https://api.podio.com/app/space/{space_id}` returns the apps in a space.

## What worked here

- The authenticated account can see the **OKC House Buyers** org.
- The org is active and includes the **OKC House Buyers Operations** space.
- The Operations space ID is `3143810`.

## What did not work here

- `GET /workspace` and `GET /workspace/` returned `404 not_found` in testing.
- Do not rely on those paths for discovery in this workspace.

## Practical advice

- Use `/org/` first when you need to confirm which Podio orgs are visible.
- Use `/space/org/{org_id}` to enumerate spaces before guessing at a URL label.
- Use `/app/space/{space_id}` to discover the app IDs you need for item queries.
- Re-fetch the item after any write so you can verify the update landed.
