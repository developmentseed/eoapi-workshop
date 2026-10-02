"""Count the lines we own per front-door variant: non-blank, non-comment.

Comments: `#` lines (YAML, shell, Dockerfile, Python), Helm `{{/* ... */}}`
blocks, and Python docstrings. Run from anywhere:
    python3 spike/checks/frontdoor-own/loc.py [own|hub]   (default: own)
"""

import io
import pathlib
import sys
import tokenize

SPIKE = pathlib.Path(__file__).resolve().parents[2]
SHARED = {  # the participant pod's DB image and the local cluster, the same for both
    "db image": ["db/Dockerfile", "db/glad_to_sql.py", "db/initdb/zz_00_tuning.sh"],
    "deploy glue (local kind only)": ["kind/cluster.yaml"],
}
VARIANTS = {"own": {
    "chart": ["chart/Chart.yaml", "chart/values.yaml",
              "chart/templates/participant.yaml", "chart/templates/shared.yaml",
              "stac-browser/default.conf.template"],  # chart/files/ symlinks to it
    "lab image + config": ["lab/Dockerfile", "lab/jupyter_server_config.py"],
    **SHARED,
}, "hub": {
    # z2jh 4.4.2 values; the stac-browser conf goes in through --set-file
    "z2jh values": ["hub/values.yaml", "stac-browser/default.conf.template"],
    # hub/Dockerfile builds FROM the lab image and replaces its config
    "lab image + config": ["lab/Dockerfile", "hub/Dockerfile", "hub/jupyter_server_config.py"],
    **SHARED,
    # the password Secret and the pre-spawn (the own chart does both in templates)
    "deploy glue (hub)": ["hub/deploy.sh"],
}}
FILES = VARIANTS[sys.argv[1] if len(sys.argv) > 1 else "own"]


def python_lines(text):
    code = set()
    first = True  # a STRING opening a logical line is a docstring
    for t in tokenize.generate_tokens(io.StringIO(text).readline):
        if t.type in (tokenize.NL, tokenize.NEWLINE):
            first = t.type == tokenize.NEWLINE or first
            continue
        if t.type in (tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
            continue
        if not (first and t.type == tokenize.STRING):
            code.update(range(t.start[0], t.end[0] + 1))
        first = False
    return len(code)


def other_lines(text):
    n, in_tpl_comment = 0, False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("{{/*", "{{- /*")):
            in_tpl_comment = True
        if in_tpl_comment:
            in_tpl_comment = "*/" not in s
            continue
        if s and not s.startswith("#"):
            n += 1
    return n


total = 0
for group, paths in FILES.items():
    for p in paths:
        text = (SPIKE / p).read_text()
        n = python_lines(text) if p.endswith(".py") else other_lines(text)
        total += n
        print(f"{n:5d}  spike/{p}  ({group})")
print(f"{total:5d}  total")
