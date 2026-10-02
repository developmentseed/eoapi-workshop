"""Report on the executed copies under /tmp/nbrun-notebooks/<phase>/out (run in the Lab).

1. cell.*   every errored cell (index, error type, first line) and every cell that
            prints an API error body without raising, with its class from fixes.CLASSES.
2. url.*    every browser-facing URL the notebooks embed (IFrame src), print (localhost,
            alone or after a label) or render as a link (show_links) must be on the Lab
            origin and answer 200 through the Lab with a logged-in session (token once,
            then the cookie, as a browser does), must not forbid framing, and its HTML
            must not reference localhost outside its own /<prefix>/. Swagger's spec and
            map.html's tilejson are followed one level.
   tile.*   one tile per map at the center, at the zoom a 1200 px map fitted to the
            bounds opens at: the real workload (titiler reads the COGs then).
3. prefix.* every localhost URL in outputs (e.g. API JSON) starts with a contract
            endpoint, so to_browser() can map it.
4. md.*     clickable localhost links in markdown (code spans/blocks excluded) in docs/.
5. BLOCKED  what needs a real browser or TLS.
"""

import glob
import html
import json
import math
import os
import re
import sys
import time
from urllib.parse import urljoin, urlsplit

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixes import CLASSES  # noqa: E402

ROOT = "/tmp/nbrun-notebooks"
LAB = "http://localhost:18888"
CLASS_NAMES = {
    "a": "(a) URL/env contract",
    "b": "(b) path-prefix/proxy",
    "c": "(c) per-user simplification",
    "d": "(d) external data/network",
    "e": "(e) pre-existing bug",
}

IFRAME = re.compile(r'<iframe[^>]*\bsrc="([^"]+)"', re.I)
HREF = re.compile(r'<a href="([^"]+)" target="_blank">', re.I)  # show_links() output
URL = re.compile(r"https?://[^\s'\"<>()\\]+")
PRINTED = re.compile(
    r"^(?:[\w ./{}()-]*:\s*)?(https?://\S+)\s*$"
)  # "url" or "label: url"
MD_LINK = re.compile(r"https?://localhost:\d+[^\s>)\]`\"']*")
CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
ROOT_REL = re.compile(r'(?:src|href|action)="(/[^"/][^"]*)"')  # "/x", not "//cdn"


def say(status, name, detail):
    print(f"{status} {name} — {detail}"[:400], flush=True)


def cells(path):
    return json.load(open(path))["cells"]


def text_of(output):
    if output["output_type"] == "stream":
        return "".join(output["text"])
    data = output.get("data", {})
    return (
        "".join(data.get("text/html", "")) + "\n" + "".join(data.get("text/plain", ""))
    )


def session():
    token = os.environ["LAB_TOKEN"]
    c = httpx.Client(timeout=120, follow_redirects=True)
    r = c.get(f"{LAB}/lab", params={"token": token})
    r.raise_for_status()
    return c


def tile_of(tj):
    """The center tile at roughly the zoom a 1200 px map fitted to the bounds opens at."""
    w, s, e, n = tj.get("bounds") or [-180, -85, 180, 85]
    z = int(math.log2(360 * 1200 / 256 / max(e - w, 1e-6)))
    z = max(tj.get("minzoom", 0), min(tj.get("maxzoom", 22), z))
    lon, lat = (w + e) / 2, (s + n) / 2
    k = 2**z
    x = int((lon + 180) / 360 * k)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * k)
    return (
        tj["tiles"][0]
        .replace("{z}", str(z))
        .replace("{x}", str(x))
        .replace("{y}", str(y))
    )


def get(c, url, timeout=60):
    try:
        return c.get(url, timeout=timeout), None
    except httpx.HTTPError as exc:
        return None, f"{type(exc).__name__} after {timeout}s"


def fetch(c, url, depth=0):
    """(ok, detail, tiles) for one browser-facing URL, following sub-resources one level."""
    if not url.startswith(LAB + "/"):
        where = (
            "another localhost port: not published, only the Lab is"
            if "localhost" in url
            else "outside this participant's stack"
        )
        return False, f"not on the Lab origin ({where})", []
    r, err = get(c, url.split("#")[0])
    if err:
        return False, err, []
    final = str(r.url)
    if r.status_code != 200 or "/login" in urlsplit(final).path:
        return False, f"{r.status_code} final={final[:120]}", []
    notes = [f"200 {r.headers.get('content-type', '').split(';')[0]}"]
    if depth:
        return True, notes[0], []
    body = r.text
    ok = True
    xfo = r.headers.get("x-frame-options", "").upper()
    fa = re.search(
        r"frame-ancestors([^;]*)", r.headers.get("content-security-policy", "")
    )
    if xfo == "DENY" or (fa and "'none'" in fa.group(1)):  # the IFrame would stay blank
        ok = False
        notes.append(
            f"framing blocked: X-Frame-Options={xfo or '-'} frame-ancestors={fa.group(1).strip() if fa else '-'}"
        )
    if "html" in r.headers.get("content-type", ""):  # (b): refs that escape the prefix
        prefix = "/" + urlsplit(final).path.split("/")[1] + "/"
        off = sorted(
            {
                u
                for u in URL.findall(body)
                if urlsplit(u).hostname == "localhost"
                and not (u + "/").startswith(LAB + prefix)
            }
        )
        rootrel = sorted(
            {u for u in ROOT_REL.findall(body) if not u.startswith(prefix)}
        )
        if off or rootrel:
            ok = False
            notes.append(f"escapes {prefix}: {(off + rootrel)[:4]}")
    subs = []
    m = re.search(r"""url:\s*['"]([^'"]+)['"]""", body)  # Swagger UI spec
    if "swagger" in body.lower() and m:
        subs.append(("openapi", urljoin(final, m.group(1))))
    for u in sorted(set(URL.findall(body))):
        if "tilejson.json" in u:
            subs.append(("tilejson", html.unescape(u)))
    tiles = []
    for kind, u in subs:
        sub_ok, d, _ = fetch(c, u, depth + 1)
        notes.append(f"{kind} {d}")
        ok &= sub_ok
        if kind == "tilejson" and sub_ok:
            tj = c.get(u).json()
            on_lab = bool(tj.get("tiles")) and all(
                t.startswith(LAB + "/") for t in tj["tiles"]
            )
            notes.append(f"tiles on Lab origin={on_lab}")
            ok &= on_lab
            if on_lab:
                tiles.append(tile_of(tj))
    return ok, "; ".join(notes), tiles


def check_tile(c, where, url):
    """A tile is the browser's real workload: titiler reads the COGs (S3) right then."""
    name = f"tile.{where[0]}.{where[1]}[{where[2]}]"
    r, err = get(c, url, timeout=90)
    if err:
        say(
            "FAIL",
            name,
            f"{url[len(LAB) :][:110]} -> {err} (a browser map would sit blank)",
        )
        return
    secs = r.elapsed.total_seconds()
    ok = r.status_code in (200, 204, 404)  # 204/404: no data under that tile
    say(
        "PASS" if ok else "FAIL",
        name,
        f"{url[len(LAB) :][:110]} -> {r.status_code} {r.headers.get('content-type', '')} in {secs:.1f}s"
        + ("" if ok else class_of(*where)),
    )


SILENT = re.compile(
    r'"detail":\s*"[^"]*"|"code":\s*"\w*Error"'
)  # FastAPI/STAC error bodies


def report_errors(phase, name, nb):
    """Errored cells, plus cells that print an API error body without raising."""
    n_err = 0
    for i, cell in enumerate(nb):
        for o in cell.get("outputs", []):
            if o["output_type"] == "error":
                ename, first = (
                    o["ename"],
                    (o["evalue"].strip().splitlines() or [""])[0][:160],
                )
            elif o["output_type"] == "stream" and SILENT.search("".join(o["text"])):
                ename, first = "silent", SILENT.search("".join(o["text"])).group(0)
            else:
                continue
            n_err += 1
            say(
                "FAIL",
                f"cell.{phase}.{name}[{i}]",
                f"{ename}: {first}{class_of(phase, name, i)}",
            )
    return n_err


def class_of(phase, name, i):
    cls, note = CLASSES.get((phase, name, i)) or CLASSES.get(
        ("*", name, i), ("?", "unclassified")
    )
    return f" | {CLASS_NAMES.get(cls, cls)}: {note}"


def browser_urls(nb):
    """(cell, kind, url) for what a participant is meant to open in the browser."""
    for i, cell in enumerate(nb):
        for o in cell.get("outputs", []):
            t = text_of(o)
            for u in IFRAME.findall(t):
                yield i, "iframe", html.unescape(u)
            for u in HREF.findall(t):
                yield i, "link", html.unescape(u)
            if (
                o["output_type"] == "stream"
            ):  # stack URLs printed alone or after a label
                for line in t.splitlines():
                    m = PRINTED.match(line.strip())
                    if m and urlsplit(m.group(1)).hostname == "localhost":
                        yield i, "printed", m.group(1)


def contract_prefixes():
    sys.dont_write_bytecode = True  # /home/jovyan/docs is the bind-mounted repo
    sys.path.insert(0, "/home/jovyan/docs")
    from workshop_setup import endpoints

    return [p for e in endpoints().values() for p in e.values() if p]


def main():
    c = session()
    prefixes = contract_prefixes()
    for phase in ("docs", "writes"):
        for path in sorted(glob.glob(f"{ROOT}/{phase}/out/*.ipynb")):
            name = os.path.basename(path)[:-6]
            nb = cells(path)
            n_code = sum(c_["cell_type"] == "code" for c_ in nb)
            n_err = report_errors(phase, name, nb)
            at = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(os.path.getmtime(path)))
            say(
                "PASS" if not n_err else "FAIL",
                f"nb.{phase}.{name}",
                f"{n_code} code cells, {n_err} errored or silently failed (executed {at})",
            )

            for i, kind, url in browser_urls(nb):
                ok, detail, tiles = fetch(c, url)
                say(
                    "PASS" if ok else "FAIL",
                    f"url.{phase}.{name}[{i}].{kind}",
                    f"{url[:140]} -> {detail}"
                    + ("" if ok else class_of(phase, name, i)),
                )
                for t in tiles:
                    check_tile(c, (phase, name, i), t)

            leaked = sorted(
                {
                    u.rstrip(".,")
                    for cell in nb
                    for o in cell.get("outputs", [])
                    for u in URL.findall(text_of(o))
                    if urlsplit(u).hostname == "localhost"
                }
            )
            bad = [
                u
                for u in leaked
                if not any(
                    u == p or u.startswith(p + "/") or u.startswith(p + "?")
                    for p in prefixes
                )
            ]
            kernel = [u for u in leaked if not u.startswith(LAB + "/") and u != LAB]
            say(
                "PASS" if not bad else "FAIL",
                f"prefix.{phase}.{name}",
                f"{len(leaked)} distinct localhost URLs in outputs, {len(kernel)} kernel-side "
                f"(JupyterLab linkifies them; dead in the browser); outside the contract prefixes: {bad[:4]}",
            )

    for name, why in (
        (
            "render.iframes",
            "HTTP 200 + sub-resources only; whether JupyterLab paints each IFrame needs a real browser",
        ),
        (
            "render.stac-browser-deep-link",
            "/browser/collections/<id> returns index.html (200); the SPA route is JS",
        ),
        (
            "login.stac-browser-oidc-in-iframe",
            "ch. 8 PKCE login inside the Lab needs a real browser",
        ),
        (
            "tls.mixed-content",
            "no TLS locally; https Lab + https browser URLs untested",
        ),
    ):
        say("BLOCKED", name, why)

    # static markdown links in the repo's docs
    for label, pattern in (("docs", "/home/jovyan/docs/0*.ipynb"),):
        n_links = n_nb = 0
        for path in sorted(glob.glob(pattern)):
            name = os.path.basename(path)[:-6]
            n_nb += 1
            for i, cell in enumerate(cells(path)):
                if cell["cell_type"] != "markdown":
                    continue
                prose = CODE.sub("", "".join(cell["source"]))  # code is not clickable
                for u in sorted(set(MD_LINK.findall(prose))):
                    n_links += 1
                    ok = u.startswith(LAB + "/")
                    say(
                        "PASS" if ok else "FAIL",
                        f"md.{label}.{name}[{i}]",
                        f"{u} -> {'Lab origin' if ok else 'compose port in static text: not the participant stack'}",
                    )
        say(
            "PASS" if not n_links else "FAIL",
            f"md.{label}",
            f"{n_links} clickable localhost links in the markdown of {n_nb} notebooks",
        )


if __name__ == "__main__":
    main()
