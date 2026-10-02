"""What another pod would see. Runs in a throwaway container on the compose
network but NOT in the participant's netns: host `lab` = the participant pod IP.

Prints one line per check: PASS|FAIL|BLOCKED <name> — <detail>
"""

import os
import socket

import psycopg

HOST = "lab"
PORTS = {
    "postgres": 5432,
    "stac-fastapi": 8081,
    "titiler": 8082,
    "tipg": 8083,
    "stac-auth-proxy": 8084,
    "mock-oidc": 8085,
    "stac-manager": 8086,
    "stac-browser": 8080,
}

open_ports = []
for name, port in PORTS.items():
    with socket.socket() as s:
        s.settimeout(2)
        if s.connect_ex((HOST, port)) == 0:
            open_ports.append(f"{name}:{port}")
print(
    f"{'PASS' if not open_ports else 'FAIL'} isolation.backends-unreachable-off-pod — "
    + (
        f"reachable from another netns: {open_ports}; on k8s a per-participant "
        "NetworkPolicy is required (skeptic finding 1)"
        if open_ports
        else "nothing but the Lab answers"
    )
)


def try_login(password):
    try:
        psycopg.connect(
            host=HOST,
            user="eoapi",
            password=password,
            dbname="postgis",
            connect_timeout=3,
        ).close()
        return "ok"
    except psycopg.OperationalError as e:
        return str(e).strip().splitlines()[-1][-60:]


# Loopback bind: unreachable is the pass. If it ever answers, the password must still hold.
wrong, right = try_login("wrong-password"), try_login(os.environ["PGPASSWORD"])
unreachable = "postgres:5432" not in open_ports
print(
    f"{'PASS' if wrong != 'ok' and (unreachable or right == 'ok') else 'FAIL'} db.off-pod — "
    + ("not reachable from another netns (listen_addresses=127.0.0.1)" if unreachable
       else f"reachable; wrong password: {wrong}; generated password: {right}")
)
