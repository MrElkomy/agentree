"""Run untrusted parsing or queries in a limited child process (Tasks 17 and 18).

The child is a fresh Python running one of our modules (`python -m <module>`), with hard limits
on address space and CPU time, no file writes, a wall-clock timeout and a minimal environment
(no secrets: no vault key, no database URLs). Input goes on stdin, the result comes back on
stdout. One child at a time per server process keeps memory bounded next to the API.
"""

import asyncio
import resource
import sys
from dataclasses import dataclass

# What Python needs, nothing else. No bytecode writes: the child may not write files at all.
CHILD_ENV = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "LANG": "C.UTF-8"}

_slot = asyncio.Semaphore(1)


@dataclass(frozen=True)
class ChildResult:
    ok: bool  # exited normally within its limits
    stdout: bytes


async def run_limited(
    module: str, args: list[str], data: bytes, *, memory_bytes: int, cpu_seconds: int,
    timeout_seconds: float,
) -> ChildResult:  # fmt: skip
    def limits() -> None:  # runs in the child before exec
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))

    async with _slot:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", module, *args, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            preexec_fn=limits, env=CHILD_ENV,
        )  # fmt: skip
        try:
            out, _ = await asyncio.wait_for(proc.communicate(data), timeout_seconds)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ChildResult(False, b"")
    return ChildResult(proc.returncode == 0, out)
