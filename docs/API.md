# GenFlow API

JSON requests/responses. HTTPS is terminated by Caddy. All `/api/*` routes except login require `Authorization: Bearer <session>`. Single-owner administrator only. Never put sessions in query strings.

| Method | Path | Body / result |
|---|---|---|
| GET | `/health` | Process health only; public |
| POST | `/api/login` | `{password}` → token, expires |
| POST | `/api/logout` | `{}` → revoke current session |
| GET/POST | `/api/projects` | List / create `{title, characters: [{name,identity,voice,default_clothing}]}` |
| POST | `/api/projects/{id}/characters` | Append a character to future episode bibles |
| POST | `/api/projects/{id}/characters/{index}/reference` | Raw JPEG, Content-Length, max 8 MB |
| GET/POST | `/api/jobs` | Recent 200 jobs / create `{project_id,command,script,settings}` |
| GET | `/api/jobs/{id}` | Complete job, ordered shots, attempts, QA and latest 200 events |
| POST | `/api/jobs/{id}/cancel` | `{}`; stops further work, cannot undo accepted Google generation |
| POST | `/api/jobs/{id}/resume` | `{}`; safe blocked/failed/cancelled job only |
| GET | `/api/jobs/{id}/export` | Completed MP4; byte ranges supported |
| GET/POST | `/api/shots/{id}/clip` | Play current clip / import raw MP4, max 200 MB; job must be paused to import |
| POST | `/api/shots/{id}/approve` | `{note}`; only uncertain review with successful technical QA |
| POST | `/api/shots/{id}/retry` | `{note, acknowledge_duplicate_cost}`; uncertain submission requires explicit true |
| GET | `/api/config` | Non-secret readiness and Flow profile |
| POST | `/api/config/flow` | Allowlisted selector profile; no credentials accepted |

Job creation also accepts `client_request_id` (8–80 characters) for safe network retries; the same key with different inputs returns 409. Settings: `max_attempts` (1–5, default 3), `max_generations` (1–300, default 60), `aspect` (`16:9`/`9:16`), `require_audio` (default true). Character data is snapshotted at job creation. There is no provider-video-generation API route.

JSON body max 2 MB; HTTP connections bounded at 16. Unknown ids return 404. Authentication errors 401; rate limits 429; unsafe state transitions/config prerequisites 409; invalid uploads 422. Request bodies and headers are not logged. Unexpected errors expose only exception type. Operator review notes and production events are durable but must not contain secrets.
