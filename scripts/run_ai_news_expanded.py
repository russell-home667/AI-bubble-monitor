#!/usr/bin/env python3
'''Launch the resilient AI news pipeline with expanded discovery installed.'''
import news_discovery_expanded as expanded
import run_ai_news_resilient as resilient

expanded.install(resilient.core)

if __name__ == "__main__":
    raise SystemExit(resilient.core.main())
