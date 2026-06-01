"""Uptime module — tracks service uptime, health, and resource usage."""

import logging
import os
import time

from core.module import Module

logger = logging.getLogger(__name__)


class UptimeModule(Module):
    name = "uptime"
    description = "Service uptime and resource health checks"
    version = "0.1.0"
    config_defaults = {
        "enabled": True,
    }

    def __init__(self):
        self._start_time = time.time()

    async def on_load(self, app) -> None:
        logger.info("Uptime tracking started")

    async def on_unload(self) -> None:
        pass

    async def on_health(self) -> dict:
        uptime_secs = time.time() - self._start_time
        hours = int(uptime_secs // 3600)
        minutes = int((uptime_secs % 3600) // 60)

        mem_info = {}
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split()
                    if parts[0].rstrip(":") in ("MemTotal", "MemAvailable"):
                        mem_info[parts[0].rstrip(":")] = int(parts[1]) // 1024
        except Exception:
            pass

        proc_mb = 0
        try:
            with open(f"/proc/{os.getpid()}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        proc_mb = int(line.split()[1]) // 1024
                        break
        except Exception:
            pass

        try:
            st = os.statvfs("/")
            disk_total = st.f_blocks * st.f_frsize // (1024 * 1024)
            disk_free = st.f_bfree * st.f_frsize // (1024 * 1024)
            disk_used = disk_total - disk_free
            disk_pct = round(disk_used / disk_total * 100, 1) if disk_total else 0
        except Exception:
            disk_total = disk_used = disk_pct = 0

        return {
            "uptime": f"{hours}h {minutes}m",
            "uptime_seconds": int(uptime_secs),
            "memory_mb": proc_mb,
            "system_memory": mem_info,
            "disk_used_mb": disk_used,
            "disk_total_mb": disk_total,
            "disk_pct": disk_pct,
        }
