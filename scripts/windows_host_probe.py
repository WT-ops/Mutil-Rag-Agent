
"""Read-only Windows host telemetry probe."""

import json
import platform
from datetime import datetime, timezone

import psutil


def collect_windows_host_metrics() -> dict:
    if platform.system() != "Windows":
        raise RuntimeError(
            "This collector must run on the Windows host."
        )

    memory = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=1)

    processes = []
    for process in psutil.process_iter(
        ["pid", "name", "memory_info"]
    ):
        try:
            info = process.info
            mem_info = info["memory_info"]

            processes.append({
                "pid": info["pid"],
                "name": info["name"],
                "memory_mb": round(
                    mem_info.rss / 1024**2, 1
                ) if mem_info else 0,
            })
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):
            continue

    processes.sort(
        key=lambda item: item["memory_mb"],
        reverse=True,
    )

    return {
        "source": "windows_host",
        "os": platform.system(),
        "collected_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "cpu_percent": cpu,
        "memory": {
            "total_gb": round(
                memory.total / 1024**3, 2
            ),
            "available_gb": round(
                memory.available / 1024**3, 2
            ),
            "used_percent": memory.percent,
        },
        "top_processes": processes[:5],
    }


if __name__ == "__main__":
    print(json.dumps(
        collect_windows_host_metrics(),
        indent=2,
        ensure_ascii=True,
    ))