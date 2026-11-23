#!/usr/bin/env python3
"""Install one MCP server and measure it: size, dependencies, startup to tools/list over stdio, memory, CPU.

Runs inside a throwaway container (see experiments/real_servers/run.py), never on the host: it installs and
starts third-party packages. Prints one JSON object on the last line of stdout.

    python3 probe.py '<server spec JSON>' [--runs 7]
"""
import json
import os
import selectors
import shutil
import subprocess
import sys
import time

TICK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")
TIMEOUT = 120


def du(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def tree(pid):
    """pid and all its descendants (from /proc)."""
    children = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                ppid = int(open(f"/proc/{d}/stat").read().rsplit(")", 1)[1].split()[1])
                children.setdefault(ppid, []).append(int(d))
            except (OSError, IndexError, ValueError):
                pass
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        out.append(p)
        todo += children.get(p, [])
    return out


def usage(pid):
    """(peak RSS summed over the process tree in bytes, CPU seconds of the tree)."""
    hwm, cpu = 0, 0.0
    for p in tree(pid):
        try:
            for line in open(f"/proc/{p}/status"):
                if line.startswith("VmHWM:"):
                    hwm += int(line.split()[1]) * 1024
            f = open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()
            cpu += (int(f[11]) + int(f[12]) + int(f[13]) + int(f[14])) / TICK  # utime stime cutime cstime
        except (OSError, IndexError, ValueError):
            pass
    return hwm, cpu


def start_once(cmd):
    """Spawn the server, run initialize + notifications/initialized + tools/list. Times from spawn, in ms."""
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd="/tmp", env=dict(os.environ, PYTHONUNBUFFERED="1"))
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    buf = b""

    def send(msg):
        proc.stdin.write((json.dumps(msg) + "\n").encode())
        proc.stdin.flush()

    def wait_for(msg_id):
        nonlocal buf
        deadline = time.perf_counter() + TIMEOUT
        while time.perf_counter() < deadline:
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    m = json.loads(line)
                except ValueError:
                    continue  # log output on stdout
                if isinstance(m, dict) and m.get("id") == msg_id:
                    return m
            if not sel.select(timeout=0.5):
                if proc.poll() is not None:
                    raise RuntimeError(f"exited with {proc.returncode}: {proc.stderr.read()[-600:]!r}")
                continue
            chunk = os.read(proc.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError(f"stdout closed: {proc.stderr.read()[-600:]!r}")
            buf += chunk
        raise TimeoutError(f"no response to request {msg_id} within {TIMEOUT} s")

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "mcp-bench-probe", "version": "0"}}})
        init = wait_for(1)
        t_init = time.perf_counter()
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = wait_for(2)
        t_list = time.perf_counter()
        rss, cpu = usage(proc.pid)
        return {"init_ms": (t_init - t0) * 1000, "tools_list_ms": (t_list - t0) * 1000, "peak_rss_mb": rss / 2**20,
                "cpu_s": cpu, "n_tools": len((tools.get("result") or {}).get("tools", [])),
                "server_info": (init.get("result") or {}).get("serverInfo"),
                "protocol": (init.get("result") or {}).get("protocolVersion")}
    finally:
        proc.kill()
        proc.wait()


def baseline(cmd, runs=7):
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        subprocess.run(cmd, check=True)
        times.append((time.perf_counter() - t0) * 1000)
    return sorted(times)[len(times) // 2]


def install(spec):
    t0 = time.perf_counter()
    if spec["language"] == "python" and (spec.get("python") or spec.get("extra")):
        # Newer Python and/or pinned extras: through uv, as uvx would run the server.
        subprocess.run(["uv", "venv", "-q", "/srv/venv", "--python", spec.get("python", "3.11")], check=True)
        base = du("/srv/venv")
        subprocess.run(["uv", "pip", "install", "-q", "--python", "/srv/venv/bin/python", spec["package"]]
                       + spec.get("extra", []), check=True)
        site = next(os.path.join("/srv/venv/lib", d, "site-packages") for d in os.listdir("/srv/venv/lib"))
        dists = [d for d in os.listdir(site) if d.endswith(".dist-info")]
        size = du("/srv/venv") - base
        cmd = [f"/srv/venv/bin/{spec['bin']}"] + spec["args"]
        version = next((d[:-len(".dist-info")] for d in dists
                        if d.lower().replace("_", "-").startswith(spec["package"].split("==")[0].lower().replace("_", "-") + "-")), None)
    elif spec["language"] == "python":
        subprocess.run(["python3", "-m", "venv", "/srv/venv"], check=True)
        base = du("/srv/venv")
        base_dists = set(os.listdir(next(p for p in [os.path.join("/srv/venv/lib", d, "site-packages")
                                                     for d in os.listdir("/srv/venv/lib")])))
        subprocess.run(["/srv/venv/bin/pip", "install", "-q", "--disable-pip-version-check", spec["package"]],
                       check=True, stdout=subprocess.DEVNULL)
        site = next(os.path.join("/srv/venv/lib", d, "site-packages") for d in os.listdir("/srv/venv/lib"))
        dists = [d for d in os.listdir(site) if d.endswith(".dist-info") and d not in base_dists]
        size = du("/srv/venv") - base
        cmd = [f"/srv/venv/bin/{spec['bin']}"] + spec["args"]
        version = next((d[:-len(".dist-info")] for d in dists
                        if d.lower().replace("_", "-").startswith(spec["package"].split("==")[0].lower().replace("_", "-") + "-")), None)
    else:
        os.makedirs("/srv/node", exist_ok=True)
        subprocess.run(["npm", "install", "--prefix", "/srv/node", "--no-audit", "--no-fund", "--loglevel=error",
                        spec["package"]], check=True, stdout=subprocess.DEVNULL)
        size = du("/srv/node/node_modules")
        pkgs = subprocess.run(["npm", "ls", "--prefix", "/srv/node", "--all", "--parseable"],
                              capture_output=True, text=True).stdout.split()
        dists = pkgs[1:]  # first line is the prefix itself
        name = spec["package"].rsplit("@", 1)[0] if spec["package"].count("@") > (1 if spec["package"].startswith("@") else 0) else spec["package"]
        pj = json.load(open(f"/srv/node/node_modules/{name}/package.json"))
        version = f"{name}@{pj['version']}"
        b = pj.get("bin")
        if isinstance(b, str):
            entry = b
        else:
            entry = b.get(name.split("/")[-1]) or next(iter(b.values()))
        cmd = ["node", os.path.join(f"/srv/node/node_modules/{name}", entry)] + spec["args"]
    return {"install_s": time.perf_counter() - t0, "installed_mb": size / 2**20, "n_dependencies": len(dists),
            "version": version, "command": cmd}


def main():
    spec = json.loads(sys.argv[1])
    runs = int(sys.argv[sys.argv.index("--runs") + 1]) if "--runs" in sys.argv else 7
    out = {"spec": spec}
    try:
        out.update(install(spec))
        out["baseline_ms"] = baseline(["/srv/venv/bin/python", "-c", "pass"] if spec["language"] == "python" else ["node", "-e", "0"])
        if spec["language"] == "python":
            out["python"] = subprocess.run(["/srv/venv/bin/python", "-V"], capture_output=True, text=True).stdout.strip()
        out["runs"] = []
        for _ in range(runs):
            try:
                out["runs"].append(start_once(out["command"]))
            except Exception as e:
                out["runs"].append({"error": f"{type(e).__name__}: {e}"[:800]})
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"[:800]
    print(json.dumps(out))


if __name__ == "__main__":
    main()
