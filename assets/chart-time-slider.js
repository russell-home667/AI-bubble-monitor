(() => {
  'use strict';

  // Shared ECharts time navigation, intentionally matched to the aviation-leasing dashboard.
  // Only true time-series charts are included; cross-sectional charts are excluded.
  const TIME_CHART_IDS = new Set([
    'brentChart',
    'marketChart',
    'liquidityChart',
    'capexFcfChart',
    'tsmcChart',
    'gpuChart',
    'scoreHistoryChart',
    'historyChart'
  ]);

  if (!window.echarts) return;

  const patched = new WeakSet();

  function aviationDataZoom() {
    return [
      {
        type: 'inside',
        xAxisIndex: 0,
        filterMode: 'none',
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: false
      },
      {
        type: 'slider',
        xAxisIndex: 0,
        height: 18,
        bottom: 9,
        left: 50,
        right: 24,
        realtime: true,
        borderColor: 'rgba(70, 193, 255, 0.10)',
        backgroundColor: 'rgba(4, 12, 20, 0.30)',
        fillerColor: 'rgba(70, 193, 255, 0.13)',
        handleStyle: {
          color: '#0d1828',
          borderColor: '#46c1ff',
          borderWidth: 1.4
        },
        moveHandleStyle: {
          color: 'rgba(142, 172, 201, 0.78)'
        },
        textStyle: { color: '#647f92' },
        showDetail: false,
        showDataShadow: true,
        brushSelect: true,
        zoomLock: false
      }
    ];
  }

  function withAviationZoom(option) {
    if (!option || typeof option !== 'object') return option;
    const out = { ...option };

    // Same bottom spacing as the aviation dashboard so the mini-history window is easy to grab.
    if (Array.isArray(out.grid)) {
      out.grid = out.grid.map((g, i) => i === 0 ? { ...g, bottom: Math.max(Number(g?.bottom) || 0, 57) } : g);
    } else {
      out.grid = { ...(out.grid || {}), bottom: Math.max(Number(out.grid?.bottom) || 0, 57) };
    }

    out.dataZoom = aviationDataZoom();
    return out;
  }

  function patchChart(chart) {
    if (!chart || patched.has(chart)) return;
    const originalSetOption = chart.setOption.bind(chart);

    chart.setOption = function(option, ...args) {
      return originalSetOption(withAviationZoom(option), ...args);
    };

    patched.add(chart);

    // If the page rendered before this shared asset loaded, merge the aviation-style navigator now.
    originalSetOption({
      grid: { bottom: 57 },
      dataZoom: aviationDataZoom()
    }, false);
  }

  function scan() {
    TIME_CHART_IDS.forEach(id => {
      const dom = document.getElementById(id);
      if (!dom) return;
      const chart = echarts.getInstanceByDom(dom);
      if (chart) patchChart(chart);
    });
  }

  scan();

  // Most charts are created only after async CSV/JSON loads, so keep scanning briefly.
  const observer = new MutationObserver(scan);
  observer.observe(document.documentElement, { childList: true, subtree: true });

  let attempts = 0;
  const timer = setInterval(() => {
    scan();
    attempts += 1;
    if (attempts >= 80) {
      clearInterval(timer);
      observer.disconnect();
    }
  }, 250);
})();
