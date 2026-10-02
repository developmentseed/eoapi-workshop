"""Browser checks for one participant stack, in a real headless Chromium.

Runs in a container that shares the Lab's network namespace (run.sh), so
http://localhost:18888 is the URL a participant's browser uses, and a secure
context (PKCE needs crypto.subtle).

Prints one line per check: PASS|FAIL|BLOCKED <name> — <detail>
Writes screenshots and the console/network log to /screens (spike/evidence/screens).

Data it creates (and deletes again at the end):
  - spike-browser-apps-test               stac-manager create/edit
  - private-spike-browser-apps-notes      the row-level filter only hides `private-<owner>-*`,
                                          so this one needs that prefix; owner = this topic,
                                          so it never collides with notebook 08's ids
  - /home/jovyan/spike-browser-apps-iframe.ipynb, its kernel and Lab workspace

stac-manager checks drive the stack as deployed: create, edit and delete one
collection through its UI. They need stac-fastapi --root-path /stac and the stac:write
scope sed in compose (evidence/browser-apps.md F1/F2, applied in evidence/fix.md).
"""

import json
import re
import statistics
import time
import urllib.parse

from playwright.sync_api import sync_playwright

LAB = "http://localhost:18888"
SCREENS = "/screens"
TOPIC = "spike-browser-apps"
GLAD = "glad-global-forest-change-1.11"
OWNER = TOPIC
PRIVATE_ID = f"private-{OWNER}-notes"
MGR_ID = f"{TOPIC}-test"
NB = f"{TOPIC}-iframe.ipynb"


ENV = dict(
    line.strip().partition("=")[::2] for line in open("/run/spike.env") if "=" in line
)
PW, TOKEN = ENV["LAB_PASSWORD"], ENV["LAB_TOKEN"]
SECRET_Q = re.compile(
    r"((?:code|state|token|access_token|id_token|session_state|code_challenge|_xsrf)=)[^&\s\"']+"
)


def redact(s):
    return (
        SECRET_Q.sub(r"\1<redacted>", str(s))
        .replace(PW, "<LAB_PASSWORD>")
        .replace(TOKEN, "<LAB_TOKEN>")
    )


def report(status, name, detail):
    print(f"{status} {name} — {redact(detail)}", flush=True)


def check(name, fn, needs=True):
    """fn() -> (ok: bool | 'BLOCKED', detail). A crash is a FAIL with the reason."""
    if needs is not True:
        report("BLOCKED", name, needs)
        return False
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"{type(e).__name__}: {str(e).splitlines()[0]}"[:300]
        try:  # what the page looked like when it failed
            browser.contexts[-1].pages[-1].screenshot(
                path=f"{SCREENS}/browser-apps-fail-{name}.png"
            )
        except Exception:  # noqa: BLE001
            pass
    status = ok if isinstance(ok, str) else ("PASS" if ok else "FAIL")
    report(status, name, detail)
    return status == "PASS"


# ---------------- console errors and failed requests, per step ----------------
LOG = []
STEP = ["setup"]


def watch(ctx):
    def console(m):
        if m.type == "error":
            LOG.append(
                {
                    "step": STEP[0],
                    "kind": "console",
                    "text": redact(m.text)[:300],
                    "where": redact(m.location.get("url", ""))[:160],
                }
            )

    def failed(r):
        LOG.append(
            {
                "step": STEP[0],
                "kind": "requestfailed",
                "method": r.method,
                "url": redact(r.url)[:200],
                "error": r.failure,
            }
        )

    def response(r):
        if r.status >= 400:
            LOG.append(
                {
                    "step": STEP[0],
                    "kind": "http",
                    "status": r.status,
                    "method": r.request.method,
                    "url": redact(r.url)[:200],
                }
            )

    ctx.on("console", console)
    ctx.on("requestfailed", failed)
    ctx.on("response", response)


# (label, regex on "<step> <kind> <status> <method> <url> <text> <where> <error>").
# First match wins; anything unmatched fails browser.console-and-network.
KNOWN = [
    (
        "expected: wrong-password probe",
        r"^lab\.wrong-password .*(http 401 POST .*/login|status of 401)",
    ),
    (
        "harmless: JupyterLab workspace PUT gets its 204, then Chromium reports the unread body as aborted",
        r"requestfailed\s+PUT http://localhost:18888/lab/api/workspaces/\S+\s+net::ERR_ABORTED$",
    ),
    (
        "expected: request cancelled by a page navigation or a map pan/zoom",
        r"requestfailed\s+(GET|POST|OPTIONS) \S+\s+net::ERR_ABORTED$",
    ),
    (
        "upstream: STAC Browser's OPTIONS permission probe gets 405 from stac-fastapi itself (probe browser.options-405-is-upstream)",
        r"^browser\.\S+ (http 405 OPTIONS http://localhost:18888/stac"
        r"|console .*(Failed to check permissions for http://localhost:18888/stac"
        r"|status of 405 \(Method Not Allowed\) http://localhost:18888/stac))",
    ),
    (
        "data: the baked glad collection keeps 5 MAAP queryables links; STAC Browser follows one and hits a broken $ref",
        r"^browser\.\S+ console MissingPointerError",
    ),
    (
        "known: stac-manager deep links are served by http-server's 404.html fallback (the app renders)",
        r"^manager\.\S+ (http 404 GET http://localhost:18888/manager/"
        r"|console .*status of 404 \(Not Found\) http://localhost:18888/manager/)",
    ),
    (
        "external: stac-manager avatar lookup (gravatar d=404)",
        r"^manager\.\S+ .*gravatar\.com/avatar",
    ),
    (
        "external: map.html viewers ask OSM for out-of-range tiles (x or y outside 0..2^z-1) at low zoom",
        r"^iframe (http 400 GET|console .*status of 400 \(\)) https://([abc]\.)?tile\.openstreetmap\.org/",
    ),
    (
        "expected: anonymous deep link to a private collection",
        r"^browser\.private-hidden-anon .*(private-spike-browser-apps-notes|status code 404)",
    ),
    (
        "expected: stac-manager's own fetches (map tiles) aborted by the reload",
        r"^manager\.deep-link-reload console Error: Failed to fetch at http://localhost:18888/manager/client\.[0-9a-f]+\.js",
    ),
]


def classify(e):
    flat = (
        f"{e['step']} {e['kind']} {e.get('status', '')} {e.get('method', '')} {e.get('url', '')} "
        f"{e.get('text', '')} {e.get('where', '')} {e.get('error', '')}"
    )
    flat = re.sub(r"\s+", " ", flat).strip()
    for label, pattern in KNOWN:
        if re.search(pattern, flat):
            return label
    return None


# ---------------- helpers ----------------
TOKEN_SHOWN = []  # screenshots where the page displayed the Lab token (masked in the PNG)


def shot(page, n, name):
    leak = page.get_by_text(TOKEN[:12])  # never commit the token, even as pixels
    k = leak.count()
    if k:
        TOKEN_SHOWN.append(f"{n:02d}-{name}: {k} element(s)")
    page.screenshot(
        path=f"{SCREENS}/browser-apps-{n:02d}-{name}.png", mask=[leak] if k else []
    )


def lab_login(page, next_path):
    page.goto(f"{LAB}/login?next={urllib.parse.quote(next_path)}")
    page.fill("#password_input", PW)
    with page.expect_navigation():
        page.click("#login_submit")


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def mint(req, user, claims=None, scopes="openid profile stac:read stac:write"):
    """Mint a token the way notebooks 06-08 do (mock-oidc POST /), through the Lab proxy."""
    r = req.post(
        f"{LAB}/oidc/",
        headers={"Accept": "application/json"},
        form={"username": user, "scopes": scopes, "claims": json.dumps(claims or {})},
    )
    assert r.ok, f"mint {r.status}"
    return r.json()["token"]


def collection(cid, title):
    return {
        "type": "Collection",
        "stac_version": "1.0.0",
        "id": cid,
        "title": title,
        "description": f"Created by the {TOPIC} spike check; deleted at the end of the run.",
        "license": "CC-BY-4.0",
        "keywords": [],
        "providers": [],
        "stac_extensions": [],
        "extent": {
            "spatial": {"bbox": [[-10.0, 40.0, 10.0, 50.0]]},
            "temporal": {"interval": [["2020-01-01T00:00:00Z", None]]},
        },
        "links": [
            {
                "href": "https://creativecommons.org/licenses/by/4.0/",
                "rel": "license",
                "type": "text/html",
                "title": "CC-BY-4.0",
            }
        ],
    }


def oidc_submit(page, user, claims=None):
    """Fill mock-oidc's login form (username + custom claims as JSON) and submit."""
    page.fill("#username", user)
    if claims:
        page.click("#claims-mode-toggle")
        page.fill("#claims-raw", json.dumps(claims))
    with page.expect_navigation():
        page.click("button[type=submit]")


def manager_login(page, user):
    page.get_by_text("Login", exact=True).first.click()
    page.wait_for_url("**/oidc/authorize**")
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(page.url).query)
    oidc_submit(page, user)
    # Not get_by_role: the button's aria-label is "undefined undefined" (no given/family name).
    page.locator("button", has_text="Logout").wait_for(timeout=30000)
    return q


def hop(r):
    """'POST /stac/collections/ -> 307 [uvicorn] Location: ...' for one response."""
    loc = f" Location: {r.headers.get('location')}" if 300 <= r.status < 400 else ""
    return f"{r.request.method} {r.url.replace(LAB, '')} -> {r.status} [{r.headers.get('server', '?')}]{loc}"


def manager_create(page, doc):
    """Create a collection in stac-manager's JSON editor; returns the POST/redirect chain."""
    page.goto(f"{LAB}/manager/collections/new/")
    page.get_by_role("button", name="Edit JSON").click()
    page.locator(".ace_editor .ace_content").first.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.keyboard.insert_text(json.dumps(doc))  # one input event, like a paste
    chain = []

    def on_resp(r):
        if r.request.method == "POST" and "/collections" in r.url:
            chain.append(hop(r))

    page.on("response", on_resp)
    page.locator("button[type=submit]").click()
    page.wait_for_timeout(6000)
    page.remove_listener("response", on_resp)
    return chain


def manager_edit(page, req, title):
    """Change the title in stac-manager's form and Save. Returns (PUT hop, Bearer sent, stored title)."""
    page.goto(f"{LAB}/manager/collections/{MGR_ID}/edit/")
    field = page.locator("input[name=title]")
    field.wait_for(timeout=30000)
    field.fill(title)
    with page.expect_response(lambda r: r.request.method == "PUT") as put:
        page.get_by_role("button", name="Save").click()
    page.wait_for_timeout(3000)
    stored = req.get(f"{LAB}/stac/collections/{MGR_ID}").json().get("title")
    return (
        hop(put.value),
        bool(put.value.request.headers.get("authorization")),
        put.value.status,
        stored,
    )


def api_delete(req, cid, token):
    return req.delete(f"{LAB}/stac/collections/{cid}", headers=bearer(token)).status


# ================================== run ==================================
with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    watch(ctx)
    page = ctx.new_page()
    state = {}

    # ---------- 1. Lab login ----------
    STEP[0] = "lab.login-page"

    def _():
        # Own Lab workspace, so the shared `default` one is left alone (deleted in cleanup).
        r = page.goto(f"{LAB}/lab/workspaces/{TOPIC}")
        ok = "/login?next=" in page.url and page.locator("#password_input").is_visible()
        shot(page, 1, "lab-login-page")
        return (
            ok,
            f"GET /lab/workspaces/{TOPIC} -> {page.url.replace(LAB, '')} ({r.status}), password field visible",
        )

    check("lab.login-page", _)

    STEP[0] = "lab.wrong-password"

    def _():
        page.fill("#password_input", "not-the-password")
        with page.expect_response(
            lambda r: r.request.method == "POST" and "/login" in r.url
        ) as info:
            page.click("#login_submit")
        page.wait_for_load_state()
        status = info.value.status
        cookie = [c["name"] for c in ctx.cookies() if c["name"].startswith("username-")]
        shot(page, 2, "lab-wrong-password")
        ok = status == 401 and "/login" in page.url and not cookie
        return (
            ok,
            f"POST /login -> {status}, still on {page.url.replace(LAB, '')}, login cookie set={bool(cookie)}",
        )

    check("lab.wrong-password", _)

    STEP[0] = "lab.password-login"

    def _():
        page.fill("#password_input", PW)
        page.click("#login_submit")
        page.locator("#jp-main-dock-panel").wait_for(timeout=60000)
        page.locator(".jp-LauncherCard").first.wait_for(timeout=60000)
        page.wait_for_timeout(3000)
        c = next(c for c in ctx.cookies() if c["name"].startswith("username-"))
        shot(page, 3, "lab-after-login")
        state["lab"] = True
        return True, (
            f"lands on {page.url.replace(LAB, '')} with the JupyterLab Launcher; cookie {c['name']} "
            f"path={c['path']} httpOnly={c['httpOnly']} secure={c['secure']} sameSite={c['sameSite']}"
        )

    check("lab.password-login", _)
    need_lab = True if state.get("lab") else "Lab login failed"

    # ---------- setup: a private collection only `owner=spike-browser-apps` can see ----------
    STEP[0] = "setup"
    req = ctx.request

    def _():
        tok = mint(req, OWNER, {"owner": OWNER})
        api_delete(req, PRIVATE_ID, tok)  # leftovers from an earlier run
        api_delete(req, MGR_ID, tok)
        r = req.post(
            f"{LAB}/stac/collections",
            headers=bearer(tok),
            data=collection(PRIVATE_ID, "Spike browser-apps private notes"),
        )
        anon = req.get(f"{LAB}/stac/collections/{PRIVATE_ID}").status
        owner = req.get(
            f"{LAB}/stac/collections/{PRIVATE_ID}", headers=bearer(tok)
        ).status
        state["private"] = r.status == 201 and anon == 404 and owner == 200
        return (
            state["private"],
            f"POST {PRIVATE_ID} as owner={OWNER} -> {r.status}; GET anon -> {anon}, owner -> {owner}",
        )

    check("setup.private-collection", _, need_lab)

    # ---------- 2. STAC Browser ----------
    STEP[0] = "browser.catalog"

    def _():
        page.goto(f"{LAB}/browser/")
        card = page.get_by_role("link", name=re.compile("GLAD: Global Forest Change"))
        card.first.wait_for(timeout=30000)
        shot(page, 4, "browser-catalog")
        return (
            True,
            f"{page.url.replace(LAB, '')} title={page.title()!r}, glad collection card listed",
        )

    check("browser.catalog", _, need_lab)

    STEP[0] = "browser.collection"

    def _():
        page.get_by_role(
            "link", name=re.compile("GLAD: Global Forest Change")
        ).first.click()
        page.wait_for_url(f"**/browser/collections/{GLAD}")
        items = page.locator(f"a[href*='/browser/collections/{GLAD}/items/']")
        items.first.wait_for(timeout=30000)
        shot(page, 5, "browser-collection")
        state["item_href"] = items.first.get_attribute("href")
        return (
            True,
            f"{page.url.replace(LAB, '')} lists {items.count()} item links on the first page",
        )

    check("browser.collection", _, need_lab)

    STEP[0] = "browser.item"
    tiles = []

    def _():
        ctx.on(
            "response",
            lambda r: "tile.openstreetmap.org" in r.url and tiles.append(r.status),
        )
        page.locator(f"a[href='{state['item_href']}']").first.click()
        page.wait_for_url(f"**{state['item_href']}")
        item_id = state["item_href"].rsplit("/", 1)[-1]
        page.get_by_role("heading", name=item_id).wait_for(timeout=30000)
        page.get_by_text("Assets").first.wait_for()
        page.wait_for_load_state("networkidle")
        shot(page, 6, "browser-item")
        state["item_id"] = item_id
        return True, f"{page.url.replace(LAB, '')} heading={item_id}, assets listed"

    check("browser.item", _, need_lab)

    STEP[0] = "browser.map-tiles"

    def _():
        canvases = page.locator("canvas").count()
        ok_tiles = sum(1 for s in tiles if s == 200)
        bad = [s for s in tiles if s != 200]
        return ok_tiles > 0 and not bad and canvases > 0, (
            f"OpenLayers canvas={canvases}, basemap tiles (tile.openstreetmap.org) 200={ok_tiles} other={bad}; "
            "item footprint drawn. No data layer: glad assets are s3:// COGs with no thumbnail, which "
            "STAC Browser cannot draw (same with PR #35 compose)"
        )

    check(
        "browser.map-tiles",
        _,
        True if state.get("item_id") else "item page did not load",
    )

    STEP[0] = "browser.deep-link-reload"

    def _():
        r = page.reload()
        page.get_by_role("heading", name=state["item_id"]).wait_for(timeout=30000)
        fresh = ctx.new_page()
        r2 = fresh.goto(f"{LAB}/browser/collections/{GLAD}")
        fresh.get_by_role("heading", name=re.compile("GLAD")).first.wait_for(
            timeout=30000
        )
        shot(fresh, 7, "browser-deep-link")
        fresh.close()
        return r.status == 200 and r2.status == 200, (
            f"reload of item URL -> {r.status}, heading rendered; fresh tab on /browser/collections/{GLAD} -> {r2.status}"
        )

    check(
        "browser.deep-link-reload",
        _,
        True if state.get("item_id") else "item page did not load",
    )

    STEP[0] = "browser.private-hidden-anon"
    coll_responses = []

    def grab(r):
        if (
            r.request.method == "GET"
            and urllib.parse.urlsplit(r.url).path == "/stac/collections"
            and r.ok
        ):
            try:
                ids = [c["id"] for c in r.json()["collections"]]
            except Exception:  # noqa: BLE001
                return
            coll_responses.append(
                (STEP[0], bool(r.request.headers.get("authorization")), ids)
            )

    ctx.on("response", grab)

    def _():
        page.goto(f"{LAB}/browser/")
        page.get_by_role(
            "link", name=re.compile("GLAD: Global Forest Change")
        ).first.wait_for(timeout=30000)
        listed = [ids for step, _, ids in coll_responses if step == STEP[0]]
        in_list = any(PRIVATE_ID in ids for ids in listed)
        page.goto(f"{LAB}/browser/collections/{PRIVATE_ID}")
        page.wait_for_timeout(4000)
        body = page.inner_text("body")
        shot(page, 8, "browser-private-anon")
        shown = "Spike browser-apps private notes" in body
        return bool(listed) and not in_list and not shown, (
            f"/stac/collections seen by the page: {len(listed)} response(s), private id listed={in_list}; "
            f"deep link /browser/collections/{PRIVATE_ID} shows the private title={shown}"
        )

    check(
        "browser.private-hidden-anon",
        _,
        need_lab if state.get("private") else "setup.private-collection failed",
    )

    STEP[0] = "browser.oidc-redirect-uri"

    def _():
        page.goto(f"{LAB}/browser/")
        page.get_by_role("button", name="Log in").click()
        page.wait_for_url("**/oidc/authorize**")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(page.url).query)
        page.locator("#username").wait_for()
        shot(page, 9, "browser-mock-oidc-login")
        ru = q.get("redirect_uri", [""])[0]
        state["sb_oidc"] = True
        return ru == f"{LAB}/browser/auth" and "code_challenge" in q, (
            f"/oidc/authorize redirect_uri={ru} client_id={q.get('client_id')} scope={q.get('scope')} "
            f"PKCE={q.get('code_challenge_method')}"
        )

    check("browser.oidc-redirect-uri", _, need_lab)

    STEP[0] = "browser.oidc-login"

    def _():
        with page.expect_response(
            lambda r: r.url.startswith(f"{LAB}/oidc/token")
        ) as tok_resp:
            oidc_submit(page, OWNER, {"owner": OWNER})
        page.get_by_role("button", name=re.compile("Log ?out", re.I)).first.wait_for(
            timeout=30000
        )
        state["sb_logged_in"] = True
        return tok_resp.value.status == 200, (
            f"mock-oidc 303 -> /browser/auth?code=...; POST /oidc/token -> {tok_resp.value.status}; "
            f"back on {page.url.replace(LAB, '')} with a Log out button"
        )

    check("browser.oidc-login", _, True if state.get("sb_oidc") else "no OIDC redirect")

    STEP[0] = "browser.private-visible"

    def _():
        page.goto(f"{LAB}/browser/")
        page.get_by_role(
            "link", name=re.compile("GLAD: Global Forest Change")
        ).first.wait_for(timeout=30000)
        page.wait_for_timeout(2000)
        authed = [ids for step, a, ids in coll_responses if step == STEP[0] and a]
        in_list = any(PRIVATE_ID in ids for ids in authed)
        page.goto(f"{LAB}/browser/collections/{PRIVATE_ID}")
        page.get_by_role(
            "heading", name="Spike browser-apps private notes"
        ).first.wait_for(timeout=30000)
        shot(page, 10, "browser-private-after-login")
        return bool(authed), (
            f"{len(authed)} /stac/collections response(s) sent with Bearer, first page lists "
            f"{PRIVATE_ID}={in_list}; deep link renders the private collection"
        )

    check(
        "browser.private-visible",
        _,
        True
        if state.get("sb_logged_in") and state.get("private")
        else "login or setup failed",
    )

    # ---------- 3. stac-manager, as deployed ----------
    STEP[0] = "manager.loads"

    def _():
        page.goto(f"{LAB}/manager/")
        page.get_by_role(
            "link", name=re.compile("GLAD: Global Forest Change")
        ).first.wait_for(timeout=60000)
        shot(page, 11, "manager-home")
        return True, "/manager/ renders the collection list (glad listed)"

    check("manager.loads", _, need_lab)

    STEP[0] = "manager.deep-link-reload"

    def _():
        r = page.goto(f"{LAB}/manager/collections/{GLAD}/")
        page.get_by_text("Viewing Collection").wait_for(timeout=60000)
        r2 = page.reload()
        page.get_by_text("Viewing Collection").wait_for(timeout=60000)
        shot(page, 12, "manager-deep-link")
        return True, (
            f"/manager/collections/{GLAD}/ -> HTTP {r.status}, reload -> HTTP {r2.status}; "
            "the app renders the collection both times (http-server serves 404.html = the app)"
        )

    check("manager.deep-link-reload", _, need_lab)

    STEP[0] = "manager.oidc-login"

    def _():
        q = manager_login(page, f"{TOPIC}-mgr")
        shot(page, 13, "manager-logged-in")
        ru = q.get("redirect_uri", [""])[0]
        state["mgr_scope"] = q.get("scope", [""])[0]
        state["mgr_logged_in"] = True
        return ru.startswith(f"{LAB}/manager/"), (
            f"redirect_uri={ru} scope={state['mgr_scope']!r}; back with a Logout button"
        )

    check("manager.oidc-login", _, need_lab)
    need_mgr = True if state.get("mgr_logged_in") else "manager login failed"

    STEP[0] = "manager.create-as-deployed"

    def _():
        chain = manager_create(page, collection(MGR_ID, "Spike browser-apps test"))
        page.get_by_text("Viewing Collection").wait_for(timeout=30000)
        shot(page, 14, "manager-created")
        state["mgr_created"] = req.get(f"{LAB}/stac/collections/{MGR_ID}").status == 200
        return (
            state["mgr_created"],
            f"scope={state.get('mgr_scope')!r}; {' | '.join(chain) or 'no POST seen'}; "
            f"collection exists={state['mgr_created']}",
        )

    check("manager.create-as-deployed", _, need_mgr)
    need_created = True if state.get("mgr_created") else "create failed"

    STEP[0] = "manager.edit-as-deployed"

    def _():
        h, auth, status, stored = manager_edit(
            page, req, "Spike browser-apps test (edited)"
        )
        page.get_by_role("heading", name="Spike browser-apps test (edited)").wait_for(
            timeout=30000
        )
        shot(page, 15, "manager-edited")
        return status == 200 and stored.endswith(
            "(edited)"
        ), f"{h} (Bearer={auth}); stored title={stored!r}"

    check("manager.edit-as-deployed", _, need_created)

    STEP[0] = "manager.delete"

    def _():
        page.goto(f"{LAB}/manager/collections/{MGR_ID}/")
        page.get_by_text("Viewing Collection").wait_for(timeout=30000)
        deletes = []
        page.on("request", lambda r: r.method == "DELETE" and deletes.append(r.url))
        page.get_by_role("button", name="Options").click()
        page.get_by_role("menuitem", name="Delete").click()
        page.wait_for_timeout(5000)
        shot(page, 16, "manager-delete-clicked")
        still = req.get(f"{LAB}/stac/collections/{MGR_ID}").status
        return bool(deletes) and still == 404, (
            f"clicked Options > Delete: DELETE requests sent={len(deletes)}, collection still there={still == 200}. "
            "stac-manager 1.0.3 renders <DeleteMenuItem /> with no onClick "
            "(packages/client/src/pages/CollectionDetail/index.tsx:188); no newer release"
        )

    check("manager.delete", _, need_created)

    # ---------- 4. notebook IFrames from the Lab origin ----------
    STEP[0] = "iframe"
    cell = "\n".join(
        [
            "import os",
            "from urllib.parse import urlencode",
            "from IPython.display import IFrame, display",
            "raster, vector = os.environ['TITILER_BROWSER_URL'], os.environ['TIPG_BROWSER_URL']",
            f"display(IFrame(raster + '/collections/{GLAD}/WebMercatorQuad/map.html?'",
            "                + urlencode({'assets': 'lossyear', 'colormap_name': 'viridis', 'rescale': '0,23'}), 1100, 420))",
            "display(IFrame(vector + '/collections/features.ecoregions/tiles/WebMercatorQuad/map.html', 1100, 420))",
        ]
    )
    nb = {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "id": "c1",
                "metadata": {},
                "outputs": [],
                "source": cell,
            }
        ],
        "metadata": {
            "kernelspec": {
                "name": "python3",
                "display_name": "Python 3",
                "language": "python",
            }
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    seen = {"raster": [], "vector": [], "frames": []}

    def xsrf():
        return {
            "X-XSRFToken": next(
                c["value"] for c in ctx.cookies() if c["name"] == "_xsrf"
            )
        }

    def on_resp(r):
        path = urllib.parse.urlsplit(r.url).path
        if path.endswith("/map.html"):
            seen["frames"].append(
                (path.split("/")[1], r.status, r.request.resource_type, r.request)
            )
        elif path.startswith(f"/raster/collections/{GLAD}/tiles/"):
            seen["raster"].append((r.status, r.request))
        elif path.startswith("/vector/collections/features.ecoregions/tiles/"):
            seen["vector"].append((r.status, r.request))

    def _():
        ctx.unroute_all()
        put = req.put(
            f"{LAB}/api/contents/{NB}",
            headers=xsrf(),
            data={"type": "notebook", "content": nb},
        )
        assert put.status in (200, 201), f"PUT notebook {put.status}"
        ctx.on("response", on_resp)
        page.goto(f"{LAB}/lab/workspaces/{TOPIC}/tree/{NB}")
        # Run only once the kernel is connected; earlier, Shift+Enter just adds a cell.
        page.locator("#jp-main-statusbar").get_by_text(
            re.compile(r"\|\s*Idle")
        ).wait_for(timeout=90000)
        page.locator(".jp-Notebook .jp-Cell .jp-InputArea-editor").first.click()
        page.keyboard.press("Shift+Enter")
        frames = page.locator(".jp-OutputArea-output iframe")
        frames.nth(1).wait_for(timeout=90000)
        t0 = time.time()

        def ok200(k):
            return any(s == 200 for s, _ in seen[k])

        while time.time() - t0 < 240 and not (ok200("raster") and ok200("vector")):
            page.wait_for_timeout(2000)
        page.wait_for_timeout(3000)
        srcs = [frames.nth(i).get_attribute("src") for i in range(frames.count())]
        inner = [
            frames.nth(i).element_handle().content_frame().url
            for i in range(frames.count())
        ]
        state["iframe_srcs"] = srcs
        state["tile_wait"] = round(time.time() - t0)
        page.locator(".jp-OutputArea-output").first.scroll_into_view_if_needed()
        shot(page, 17, "iframe-notebook")
        docs = [(svc, s) for svc, s, t, _ in seen["frames"] if t == "document"]
        cookie = [
            ("username-localhost-18888=" in (rq.all_headers().get("cookie") or ""))
            for _, _, t, rq in seen["frames"]
            if t == "document"
        ]
        logged_in = all(u.startswith(LAB) and "/login" not in u for u in inner)
        return (
            logged_in
            and len(srcs) == 2
            and len(docs) == 2
            and all(s == 200 for _, s in docs)
            and all(cookie)
        ), (
            f"2 IFrame outputs in the Lab; map.html documents: {docs}, Lab cookie sent on each={cookie}; "
            f"frame URLs stay on {sorted({u.split('?')[0].replace(LAB, '') for u in inner})} (no /login redirect)"
        )

    check("iframe.map-pages-load-with-cookie", _, need_lab)

    def _():
        def stats(k):
            ok = [rq for s, rq in seen[k] if s == 200]
            ms = [
                rq.timing["responseEnd"]
                for rq in ok
                if rq.timing.get("responseEnd", -1) > 0
            ]
            other = sorted({s for s, _ in seen[k] if s != 200})
            t = (
                f", latency median {statistics.median(ms) / 1000:.1f} s max {max(ms) / 1000:.1f} s"
                if ms
                else ""
            )
            return len(ok), f"{len(seen[k])} requested, 200={len(ok)}, other={other}{t}"

        r_ok, r_txt = stats("raster")
        v_ok, v_txt = stats("vector")
        return r_ok > 0 and v_ok > 0, (
            f"within {state.get('tile_wait')} s of the IFrames appearing: titiler tiles {r_txt}; tipg tiles {v_txt}. "
            "Latency measured while other testers loaded the same host"
        )

    check(
        "iframe.tiles-render",
        _,
        True if state.get("iframe_srcs") else "IFrames did not render",
    )

    def _():
        anon = browser.new_context()
        r = anon.request.get(state["iframe_srcs"][0], max_redirects=0)
        anon.close()
        return r.status == 302 and "/login" in r.headers.get("location", ""), (
            f"same map.html URL without the Lab cookie -> {r.status} Location={r.headers.get('location', '')[:60]}"
        )

    check(
        "iframe.cookie-required",
        _,
        True if state.get("iframe_srcs") else "IFrames did not render",
    )

    # ---------- cleanup ----------
    STEP[0] = "cleanup"

    def _():
        out = []
        for s in req.get(f"{LAB}/api/sessions").json():
            if s.get("path", "").endswith(NB):
                out.append(
                    f"session {req.delete(f'{LAB}/api/sessions/{s["id"]}', headers=xsrf()).status}"
                )
        page.goto("about:blank")
        out.append(
            f"notebook {req.delete(f'{LAB}/api/contents/{NB}', headers=xsrf()).status}"
        )
        out.append(
            f"workspace {req.delete(f'{LAB}/lab/api/workspaces/{TOPIC}', headers=xsrf()).status}"
        )
        tok = mint(req, OWNER, {"owner": OWNER})
        for cid in (MGR_ID, PRIVATE_ID):
            out.append(f"{cid} {api_delete(req, cid, tok)}")
        left = [
            cid
            for cid in (MGR_ID, PRIVATE_ID)
            if req.get(f"{LAB}/stac/collections/{cid}", headers=bearer(tok)).status
            != 404
        ]
        return not left, f"{', '.join(out)}; left behind={left}"

    check("cleanup", _, need_lab)

    report(
        "PASS" if not TOKEN_SHOWN else "FAIL",
        "manager.lab-token-not-on-screen",
        "no screenshot showed the Lab token"
        if not TOKEN_SHOWN
        else f"the Lab token was visible on {TOKEN_SHOWN} (masked in the PNG). stac-manager's error toast shows "
        "the raw body of the 403 it got from Jupyter's own /collections, and Jupyter's page.html embeds "
        "data-jupyter-api-token for a logged-in user (jupyter_server templates/page.html:25-26). "
        "Goes away with the root-path fix (the POST no longer reaches Jupyter)",
    )

    # ---------- console errors and failed requests ----------
    for e in LOG:
        e["class"] = classify(e)
    with open(f"{SCREENS}/browser-apps-console.json", "w") as f:
        json.dump(LOG, f, indent=1)
    counts = {}
    for e in LOG:
        counts[e["class"] or "UNEXPECTED"] = (
            counts.get(e["class"] or "UNEXPECTED", 0) + 1
        )
    unexpected = [e for e in LOG if not e["class"]]
    report(
        "PASS" if not unexpected else "FAIL",
        "browser.console-and-network",
        f"{len(LOG)} console errors / failed or >=400 requests; "
        + "; ".join(
            f"{n}x {k}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1])
        )
        + (f"; first unexpected: {unexpected[:3]}" if unexpected else ""),
    )
    browser.close()
