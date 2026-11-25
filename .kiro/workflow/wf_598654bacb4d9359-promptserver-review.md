# PromptServer-compatible AFE route registration

The committed change removes AFE's hard dependency on `PromptServer.instance` and attaches the existing `/afe/` handlers to the ComfyUI-owned route table. The resolver derives the ComfyUI port from runtime objects or `comfy.cli_args`, while package import emits explicit success or failure diagnostics. CPU/aiohttp coverage exercises the no-`instance` path, duplicate registration, failure reporting, and HTML/static/API discovery, and the deployment script checks both the log marker and the live `/afe/` response. **Watch for:** **confirmed** the target-Pod localhost curl, external-browser check, and Linux `bash -n` check remain pending; **confirmed** `origin/main` is still at the pre-fix baseline, so the fixed code is not yet available to the Pod; **possible** the idempotence fallback treats any existing `/afe/` route as proof that all AFE routes are present.

**Verdict**: NEEDS_CHANGES

## High-level view

The resolver checks the existing PromptServer instance, server object, `PromptServer.routes`, and module-level route owner without creating another server. It accepts ComfyUI's aiohttp route table and derives the port instead of embedding a Pod port. The mock test demonstrates the class-level route-table fallback, but the target startup has not been exercised.

`Api.attach()` and the five-step UI surface remain unchanged. A marker plus a `/afe/` route scan prevents repeated registration on one table, while the mock test reaches the index, static JavaScript, and options API. The scan can also skip a partial or foreign registration because it does not verify the complete AFE route set.

Import failures remain non-fatal to node loading but produce a stable diagnostic, and deployment fails unless it sees the success marker and a successful local `/afe/` request. The commit records the CPU, graph, JavaScript, and mock/e2e results as passing, but the target Pod, external browser, and Linux shell-syntax gates remain open. **Confirmed:** the branch has not been pushed to the remote branch used by the documented `git pull` command.

<details>
<summary>Issues (3)</summary>

1. **Target release checks pending (confirmed)** — The commit message says Linux `bash -n`, the target Pod `http://127.0.0.1:18188/afe/` check, and the external same-origin browser check were not run. Execute all three after restarting the real process and record the HTML response and browser result.
2. **Fix not published (confirmed)** — `origin/main` still points to the pre-fix baseline, so a Pod running `git pull --ff-only origin main` cannot receive these changes. Push the reviewed changes to `origin/main` and verify `git ls-remote origin refs/heads/main` equals the local `HEAD`.
3. **Partial-route idempotence ambiguity (possible)** — `_route_table_has_afe_routes()` skips registration when it sees only `/afe/`, even if another plugin owns that path or a prior attach added only the index route. Use an AFE-owned marker/handler check or validate the required AFE route set before skipping `Api.attach()`.

</details>

<details>
<summary>Details</summary>

### PromptServer fallback and current ComfyUI route ownership

`register()` imports the loaded ComfyUI `server` module, resolves a route table from `PromptServer.instance.routes`, the module's server or prompt-server object, `PromptServer.routes`, or module-level `routes`, and passes it to the existing `Api.attach()`. Port lookup checks runtime `port`, `args.port`, and finally `comfy.cli_args.args.port`. This matches the supplied no-`instance` failure without starting another server or listener, and removes the old `8188` API fallback.

The registration test uses a `PromptServer` class with no `instance`, a class-level `RouteTableDef`, and a mocked server port. The **confirmed** limitation is that no live evidence shows which route-table and port candidates resolve in the target `python main.py --enable-manager --listen 127.0.0.1 --port 18188` process. The target check in Issue 1 is required; the mock result cannot substitute for it.

### Idempotent attachment and preserved AFE surface

`Api.attach()` still defines `/afe/`, `/afe/static/{name}`, and the existing `/afe/api/*` handlers. The diff leaves the five-step workflow, batch recovery/cancel behavior, reference uploads, `show_text_party`, and the scene, keyframe, Wan, and movie paths untouched. The new test calls `register()` twice, reloads the module, and adds the table to an aiohttp application before requesting the index, JavaScript, and options endpoint.

The idempotence guard is **possible** to misclassify a route collision or partial attach: it checks the private `_items` list for only `/afe/` and then returns without checking the rest of the AFE surface. A failed or foreign registration could therefore produce the success log while API or static routes remain absent. Make the guard identify an AFE-owned handler or require the full expected route set before skipping.

### Failure diagnostics and deployment gates

Package import still exposes node mappings when registration fails, but now prints `web UI registration FAILED` with an exception type and reason, and flushes both success and failure markers. The deployment script rejects `IMPORT FAILED` and registration-failure markers, requires the success marker, and curls the configured port before reporting success. The coder commit records `compileall`, `node --check`, the registration test, the listed CPU/workflow/graph scripts, and `ui_e2e.py` with 63/63 checks as passing; no suite was rerun during this review.

The **confirmed** remaining gate is that the script's Linux syntax and live Pod curl were not executed, and the external browser page was not checked. These checks distinguish route-table registration from a merely successful package import; recorded local/mock results are not Pod readiness evidence.

### Deployment command, publication, and scope

The documented update-only command reads `/proc/$PID/cmdline`, reuses the running executable and all original arguments, pulls only AFE code, and restarts the same ComfyUI process without model downloads or a second port. The full deployment path reads the active process's `--port` or requires `COMFY_PORT` before restarting, and verifies the same value. The flushed package markers make the log gate observable.

The **confirmed** publication gap means the documented Pod update cannot receive the fix until the remote branch is updated. The working tree also contains pre-existing `.agents/tasks/*`, `logs/app.log`, generated `__pycache__`, and task artifacts. `git diff 6a30a23..HEAD` contains only `webui/server.py`, `__init__.py`, `tests/test_webui_registration.py`, `deploy_pod.sh`, and `DEPLOY.md`; none of the unrelated working-tree files is part of the coder changes.

</details>

<details>
<summary>File map</summary>

- `webui/server.py` — resolves the active ComfyUI route table and port, then attaches AFE routes idempotently.
- `__init__.py` — reports Web UI registration success or failure without blocking node import.
- `tests/test_webui_registration.py` — CPU/aiohttp coverage for fallback registration, duplicate calls, diagnostics, and route discovery.
- `deploy_pod.sh` — runs the recorded regression checks and gates deployment on diagnostics plus local `/afe/` availability.
- `DEPLOY.md` — documents the update-only restart command and full-deployment port handling.

Full committed diff: `git -C e:\MJ\ai_film_editor_nodes diff 6a30a23..HEAD`.

</details>
