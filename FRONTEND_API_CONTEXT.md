# Frontend API context: auth + chat

Everything a frontend needs to model the **auth** and **chat** surface of this API:
paths, request/response shapes, error shapes, and the SSE protocol for `/chat/`.
Flights/hotels/buses search are out of scope here — this is only login, register,
chat, conversations, and messages.

Base URL in local dev: `http://127.0.0.1:8000`.

## Auth model: httponly cookie, not a bearer token

Login and register set a session cookie (`access_token` by default, see
`COOKIE_NAME`); it is `httponly`, so **no JS on the frontend can read it** and none
should try to. There is no token in any JSON response body to store in
`localStorage`/`sessionStorage` — the cookie *is* the session.

Practically, this means every request that needs auth must be made **with
credentials**:

```ts
fetch("http://127.0.0.1:8000/auth/me", { credentials: "include" });
```

```ts
axios.defaults.withCredentials = true;
```

If the frontend and API are on different origins in dev (e.g. `localhost:5173` vs
`127.0.0.1:8000`), the API's `CORS_ALLOWED_ORIGINS` env var must include your
frontend's exact origin (scheme + host + port) — it defaults to
`http://localhost:5173,http://localhost:3000` (Vite/CRA), so most setups need no
change. If `/auth/me` 401s despite a successful login in the network tab, or the
browser console shows a CORS error on the *login* request itself, that's this
setting, not auth logic — ask backend to add your origin.

One more cookie subtlety worth knowing: if the frontend is opened via `http://127.0.0.1:...`
while the API is configured for `http://localhost:...` (or vice versa), the browser
treats those as **different origins** even though they resolve to the same machine —
match whichever one is in `CORS_ALLOWED_ORIGINS` exactly.

In local dev the cookie is **not** `secure` (`COOKIE_SECURE=false`), so it works over
plain `http://127.0.0.1`. In a real deployment it will be `secure=true`, which
requires HTTPS on both frontend and API origins.

## Error shape (applies to every endpoint below)

All handled errors return JSON in one of two shapes.

Most errors:

```json
{ "detail": "Human-readable message" }
```

Request validation errors (bad/missing JSON fields) — `422`:

```json
{
  "detail": "Validation error",
  "errors": [
    {
      "type": "string_too_short",
      "loc": ["body", "password"],
      "msg": "String should have at least 8 characters",
      "input": "abc"
    }
  ]
}
```

`errors` is FastAPI/Pydantic's native error list — safe to walk for
per-field messages if you want inline form errors.

Status codes used across auth + chat:

| Code | Meaning here |
|---|---|
| `200` | OK |
| `201` | Created (register) |
| `204` | No content (logout) |
| `401` | Not authenticated (no cookie, expired/invalid token, or user no longer exists) |
| `404` | Resource not found, **or found but not yours** (conversations are scoped to the caller — a wrong id and someone else's id look identical: both 404) |
| `409` | Conflict (email already registered) |
| `422` | Request body failed validation |
| `500` | Unhandled server error — body is always `{"detail": "Internal server error"}`, never a stack trace |

---

## Auth

### `POST /auth/register`

Creates a user with the default `user` role, sets the auth cookie, returns the user.

Request body:

```ts
{
  name: string;      // 1-255 chars
  email: string;      // must be a valid email
  password: string;   // 8-128 chars
}
```

Response `201`:

```ts
{
  id: number;
  name: string;
  email: string;
  role: { id: number; name: string }; // always "user" for a fresh registration
}
```

Errors: `409` if the email is already registered, `422` for a bad body.

```bash
curl -i -X POST http://127.0.0.1:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Ada","email":"ada@example.com","password":"password123"}'
```

### `POST /auth/login`

Request body:

```ts
{
  email: string;
  password: string;
}
```

Response `200`: same `UserOut` shape as register. Sets the auth cookie.

Errors: `401` with `{"detail": "Invalid email or password"}` for either a wrong
email or wrong password (deliberately the same message for both, so the frontend
can't be used to enumerate registered emails).

### `POST /auth/logout`

No body. Clears the auth cookie. Response `204` (empty body).

### `GET /auth/me`

No body. Returns the current user, same `UserOut` shape as register/login. This is
the endpoint to call on app load to check "am I logged in" and hydrate user state —
`401` means not logged in, show the login screen.

```ts
type UserOut = {
  id: number;
  name: string;
  email: string;
  role: { id: number; name: string };
};
```

---

## Chat

Three endpoints: list conversations (sidebar), list messages in one conversation
(reopening it), and send a message (streamed reply). All three require the auth
cookie — `401` with no cookie.

### `GET /chat/conversations`

The current user's conversations, **most recent first**. For populating a sidebar.

Response `200`:

```ts
type ConversationOut = {
  id: number;
  title: string | null; // null only if somehow created with no message; see below
};

// response body:
ConversationOut[]
```

```bash
curl http://127.0.0.1:8000/chat/conversations -b 'access_token=<cookie>'
```

`title` is derived once, from the first message of the conversation (whitespace
collapsed, truncated to 60 chars with `...` appended if longer) — it does not
change as the conversation continues, and there is currently no rename endpoint.

### `GET /chat/conversations/{conversation_id}/messages`

That conversation's messages, in chronological order. For reopening a conversation
and rendering its history.

Response `200`:

```ts
type ChatMessageOut = {
  id: number;
  role: "user" | "assistant"; // only these two roles are ever persisted today
  content: string;
  created_at: string; // ISO 8601, e.g. "2026-09-22T10:00:03.123456Z"
};

// response body:
ChatMessageOut[]
```

`404` if `conversation_id` doesn't exist **or belongs to another user** — both look
identical from the outside, on purpose.

```bash
curl http://127.0.0.1:8000/chat/conversations/7/messages -b 'access_token=<cookie>'
```

### `POST /chat/`

Sends one message and streams the assistant's reply back as **Server-Sent Events**
(`text/event-stream`), not a single JSON response.

Request body:

```ts
{
  conversation_id?: number; // omit to start a new conversation
  message: string;          // 1-4000 chars
}
```

If `conversation_id` is given but doesn't exist or belongs to someone else: `404`,
**before** any streaming starts (so this is a normal JSON error response you can
`.catch()`/check `response.ok` on, not something that shows up mid-stream).

If the body passes validation and the conversation resolves, the response is
`200` with `Content-Type: text/event-stream` and a body made of SSE frames, each
shaped:

```
event: <event-name>
data: <JSON>

```

(blank line terminates each frame). Events, **always in this order**:

1. **`conversation`** — always first, exactly once.
   ```ts
   { conversation_id: number; title: string | null }
   ```
   Capture `conversation_id` here if the request omitted one — it's how you learn
   the id of a newly created conversation and how you'd add it to the sidebar list
   without a refetch.

2. **`tool_start`** — zero or more times, whenever the assistant calls a tool
   (bus search, policy lookup) before answering.
   ```ts
   { tool: string; input: unknown } // input is whatever args the tool was called with
   ```

3. **`tool_end`** — paired with each `tool_start`.
   ```ts
   { tool: string }
   ```

4. **`token`** — zero or more times, streamed pieces of the assistant's reply.
   Concatenate `content` across every `token` event in order to reconstruct the
   full answer as it's typed out.
   ```ts
   { content: string }
   ```

5. Exactly one of:
   - **`done`** — success, empty data.
     ```ts
     {}
     ```
   - **`error`** — the agent run failed after streaming had already started
     (so it **cannot** be a normal HTTP error status; the response is already
     `200`). Show this as a chat-bubble-level error, not a page-level one.
     ```ts
     { detail: string } // e.g. "The assistant hit an error. Please try again."
     ```

A typical successful stream for "buses from Mumbai to Pune tomorrow" looks like:

```
event: conversation
data: {"conversation_id": 7, "title": "buses from Mumbai to Pune tomorrow"}

event: tool_start
data: {"tool": "search_buses", "input": {"origin": "Mumbai", "destination": "Pune", "departure_date": "2026-09-23"}}

event: tool_end
data: {"tool": "search_buses"}

event: token
data: {"content": "I found "}

event: token
data: {"content": "3 buses"}

event: done
data: {}

```

**Important — this cannot be consumed with the browser's `EventSource` API.**
`EventSource` only supports `GET` requests with no custom body, and this endpoint is
a `POST` with a JSON body (and needs the auth cookie sent, which `EventSource`
handles fine, but the `POST`+body requirement rules it out entirely). Use `fetch`
with a streamed body reader instead — either roll your own frame parser, or use a
small library built for this (`@microsoft/fetch-event-source` handles POST+SSE
directly). Minimal example with the standard streams API:

```ts
async function streamChat(message: string, conversationId?: number) {
  const response = await fetch("http://127.0.0.1:8000/chat/", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ conversation_id: conversationId, message }),
  });

  if (!response.ok) {
    const err = await response.json(); // { detail: string } or { detail, errors }
    throw new Error(err.detail);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let frameEnd: number;
    while ((frameEnd = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, frameEnd);
      buffer = buffer.slice(frameEnd + 2);

      const eventLine = frame.split("\n").find((l) => l.startsWith("event: "));
      const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
      const event = eventLine?.slice("event: ".length);
      const data = dataLine ? JSON.parse(dataLine.slice("data: ".length)) : {};

      switch (event) {
        case "conversation":
          // data: { conversation_id, title }
          break;
        case "token":
          // data: { content } -- append to the in-progress assistant bubble
          break;
        case "tool_start":
        case "tool_end":
          // data: { tool, input? } -- optional "searching buses..." indicator
          break;
        case "error":
          // data: { detail } -- show as a failed message, stream is over
          break;
        case "done":
          // data: {} -- stream is over, message is complete
          break;
      }
    }
  }
}
```

## Suggested flow for a chat UI

1. On app load, `GET /auth/me`. `401` → show login/register. `200` → hydrate user,
   `GET /chat/conversations` for the sidebar.
2. Clicking a sidebar item → `GET /chat/conversations/{id}/messages`, render as the
   thread, remember `conversationId` for the next send.
3. Sending a message → optimistically render the user's bubble, open a new
   assistant bubble, `POST /chat/` with `{conversation_id, message}` (omit
   `conversation_id` for a brand-new thread), append `token` events into that
   bubble as they arrive, and on the first response add the conversation to the
   sidebar list using the `conversation` event's `conversation_id`/`title` (no
   need to refetch `/chat/conversations`).
4. `tool_start`/`tool_end` are optional to render — a "searching buses..." spinner
   is the obvious use, but the assistant's answer is self-contained without it.
