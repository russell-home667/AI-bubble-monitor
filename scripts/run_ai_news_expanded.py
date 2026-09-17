#!/usr/bin/env python3
'''Launch the resilient AI news pipeline with expanded discovery and deterministic selection.'''
import news_candidate_selection as selection
import news_discovery_expanded as expanded
import news_history_reuse as history_reuse
import news_integrity_guard as integrity_guard
import news_source_policy as source_policy
import news_scan_policy as scan_policy
import run_ai_news_resilient as resilient

expanded.install(resilient.core)
selection.install(resilient.core, expanded)
history_reuse.install(resilient.core, expanded, selection)
integrity_guard.install(resilient.core, expanded, selection, history_reuse)
source_policy.install(resilient.core, selection, history_reuse)
scan_policy.install(resilient.core, expanded, selection)

if __name__ == "__main__":
    raise SystemExit(resilient.core.main())
