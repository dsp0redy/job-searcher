"""Non-blocking smoke checks for the first configured public endpoint per source."""
from __future__ import annotations

import json

from job_searcher.adapters.greenhouse import GreenhouseAdapter
from job_searcher.adapters.lever import LeverAdapter
from job_searcher.adapters.workday import WorkdayAdapter
from job_searcher.config import AppConfig


def main() -> int:
    config = AppConfig.load("config.yml")
    results: dict[str, str] = {}
    adapters = []
    if config.sources.greenhouse:
        adapters.append(GreenhouseAdapter(config.sources.greenhouse[:1], timeout=10))
    if config.sources.lever:
        adapters.append(LeverAdapter(config.sources.lever[:1], timeout=10))
    if config.sources.workday:
        adapters.append(WorkdayAdapter(config.sources.workday[:1], timeout=10, max_pages=1, detail_limit=0))
    for adapter in adapters:
        try:
            adapter.fetch()
            statuses = getattr(adapter, "site_status", {})
            if statuses:
                results[adapter.name] = "; ".join(statuses.values())
                if not any(value.startswith("ok:") for value in statuses.values()):
                    results[adapter.name] = "failed: " + results[adapter.name]
            elif adapter.name == "workday":
                results[adapter.name] = "failed: no site status returned"
            else:
                results[adapter.name] = "unknown: adapter returned no per-site status"
        except Exception as exc:
            results[adapter.name] = f"failed: {type(exc).__name__}"
        finally:
            adapter.close()
    print(json.dumps({"source_contract_smoke_check": results}, indent=2))
    return int(any(value.startswith("failed:") for value in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
