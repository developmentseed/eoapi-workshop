"""Browser apps behind the hub, in headless Chromium: the mock-oidc issuer and
redirect URIs under the two-level prefix /user/<name>/<app>/.

Runs in the browser-apps Playwright image with hub.spike.local -> host-gateway
(run.sh). http://hub.spike.local is not a secure context, and oidc-client-ts needs
crypto.subtle for PKCE, so Chromium is told to treat that one origin as secure
(on labs the hub is https). Prints: PASS|FAIL <name> — <detail>
Screenshots: /screens/frontdoor-hub-*.png. Creates and deletes one collection.
"""

import json
import os
import re
import urllib.parse

from playwright.sync_api import sync_playwright

ORIGIN = "http://hub.spike.local:18080"
U = "u01"
BASE = f"{ORIGIN}/user/{U}"
PW = os.environ["U01_PASSWORD"]
CID = "spike-frontdoor-hub-manager"
QS = re.compile(r"((?:code|state|token|_xsrf|code_challenge)=)[^&\s\"']+")


def report(ok, name, detail):
    print(QS.sub(r"\1<redacted>", f"{'PASS' if ok else 'FAIL'} {name} — {detail}").replace(PW, "<password>"),
          flush=True)


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"{type(e).__name__}: {str(e).splitlines()[0]}"[:300]
        try:
            page.screenshot(path=f"/screens/frontdoor-hub-fail-{name}.png")
        except Exception:  # noqa: BLE001
            pass
    report(ok, name, detail)
    return ok


def oidc_submit(page, user):
    page.fill("#username", user)
    with page.expect_navigation():
        page.click("button[type=submit]")


def authorize_query(page):
    page.wait_for_url("**/oidc/authorize**")
    return urllib.parse.parse_qs(urllib.parse.urlsplit(page.url).query)


with sync_playwright() as p:
    # channel="chromium" (new headless): the default headless shell ignores this flag.
    browser = p.chromium.launch(channel="chromium", args=[f"--unsafely-treat-insecure-origin-as-secure={ORIGIN}"])
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()
    req = ctx.request
    seen = []  # (method, path, status, bearer?) of the page's /stac requests
    ctx.on("response", lambda r: f"/user/{U}/stac/" in r.url and seen.append(
        (r.request.method, urllib.parse.urlsplit(r.url).path, r.status,
         bool(r.request.headers.get("authorization")))))

    def _():
        page.goto(f"{ORIGIN}/hub/login")
        page.fill("#username_input", U)
        page.fill("#password_input", PW)
        page.click("#login_submit")
        page.wait_for_url(f"{BASE}/**", timeout=120000)
        return True, f"hub login as {U} lands on {page.url.replace(ORIGIN, '')}"

    check("hub.login", _)

    def _():
        page.goto(f"{BASE}/browser/")
        page.get_by_role("link", name=re.compile("GLAD: Global Forest Change")).first.wait_for(timeout=60000)
        page.screenshot(path="/screens/frontdoor-hub-01-browser.png")
        return True, f"{page.url.replace(ORIGIN, '')} lists the glad collection (catalog {BASE}/stac/)"

    check("browser.catalog", _)

    def _():
        page.get_by_role("button", name="Log in").click()
        q = authorize_query(page)
        page.locator("#username").wait_for()
        page.screenshot(path="/screens/frontdoor-hub-02-mock-oidc.png")
        ru = q.get("redirect_uri", [""])[0]
        return ru == f"{BASE}/browser/auth" and "code_challenge" in q, \
            f"authorize at {page.url.split('?')[0].replace(ORIGIN, '')}; redirect_uri={ru}; " \
            f"PKCE={q.get('code_challenge_method')}"

    ok = check("browser.oidc-redirect-uri", _)

    def _():
        with page.expect_response(lambda r: r.url.startswith(f"{BASE}/oidc/token")) as tok:
            oidc_submit(page, "spike-frontdoor-hub")
        page.get_by_role("button", name=re.compile("Log ?out", re.I)).first.wait_for(timeout=30000)
        page.goto(f"{BASE}/browser/")
        page.get_by_role("link", name=re.compile("GLAD: Global Forest Change")).first.wait_for(timeout=60000)
        page.wait_for_timeout(2000)
        page.screenshot(path="/screens/frontdoor-hub-03-browser-logged-in.png")
        authed = [s for s in seen if s[3] and s[0] != "OPTIONS"]
        # STAC Browser's OPTIONS permission probe gets 405 from stac-fastapi, as on
        # the own chart (evidence/browser-apps.md, known noise): counted, not failed.
        opts = sorted({s[2] for s in seen if s[0] == "OPTIONS"})
        return tok.value.status == 200 and authed and all(s[2] == 200 for s in authed), \
            f"POST {BASE.replace(ORIGIN, '')}/oidc/token → {tok.value.status}; back on /browser/auth then " \
            f"/browser/ with Log out; {len(authed)} GET /stac request(s) with Bearer + session cookie, " \
            f"statuses {sorted({s[2] for s in authed})}; OPTIONS permission probes → {opts}"

    if ok:
        check("browser.oidc-login", _)
    else:
        report(False, "browser.oidc-login", "skipped: no OIDC redirect")

    def _():
        page.goto(f"{BASE}/manager/")
        page.get_by_role("link", name=re.compile("GLAD: Global Forest Change")).first.wait_for(timeout=90000)
        page.get_by_text("Login", exact=True).first.click()
        q = authorize_query(page)
        ru = q.get("redirect_uri", [""])[0]
        oidc_submit(page, "spike-frontdoor-hub")
        page.locator("button", has_text="Logout").wait_for(timeout=30000)
        page.screenshot(path="/screens/frontdoor-hub-04-manager-logged-in.png")
        return ru.startswith(f"{BASE}/manager"), f"stac-manager login: redirect_uri={ru}, Logout shown"

    ok = check("manager.oidc-login", _)

    def _():
        tok = req.post(f"{BASE}/oidc/", headers={"Accept": "application/json"},
                       form={"username": "spike-frontdoor-hub", "scopes": "openid stac:read stac:write",
                             "claims": "{}"}).json()["token"]
        auth = {"Authorization": f"Bearer {tok}"}
        req.delete(f"{BASE}/stac/collections/{CID}", headers=auth)  # leftover of an earlier run
        doc = {"type": "Collection", "stac_version": "1.0.0", "id": CID, "title": "frontdoor-hub",
               "description": "created through stac-manager behind the hub", "license": "CC-BY-4.0",
               "links": [], "extent": {"spatial": {"bbox": [[-10, 40, 10, 50]]},
                                       "temporal": {"interval": [["2020-01-01T00:00:00Z", None]]}}}
        page.goto(f"{BASE}/manager/collections/new/")
        page.get_by_role("button", name="Edit JSON").click()
        page.locator(".ace_editor .ace_content").first.click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        page.keyboard.insert_text(json.dumps(doc))
        hops = []
        page.on("response", lambda r: r.request.method == "POST" and "/collections" in r.url and hops.append(
            f"{r.status} {urllib.parse.urlsplit(r.url).path}"
            + (f" → {r.headers.get('location')}" if 300 <= r.status < 400 else "")))
        page.locator("button[type=submit]").click()
        page.wait_for_timeout(8000)
        page.screenshot(path="/screens/frontdoor-hub-05-manager-created.png")
        stored = req.get(f"{BASE}/stac/collections/{CID}")
        dele = req.delete(f"{BASE}/stac/collections/{CID}", headers=auth)
        return stored.status == 200, f"POST chain {hops}; GET created collection → {stored.status}; " \
                                     f"DELETE (notebook-style) → {dele.status}"

    if ok:
        check("manager.create", _)
    else:
        report(False, "manager.create", "skipped: no stac-manager login")
    browser.close()
