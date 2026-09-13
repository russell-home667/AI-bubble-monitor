(() => {
  'use strict';

  // Compact ECharts dataZoom slider shared by the main dashboard and backtest page.
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

  function compactSlider() {
    return {
      type: 'slider',
      xAxisIndex: 0,
      filterMode: 'filter',
      start: 0,
      end: 100,
      height: 10,
      bottom: 5,
      left: 50,
      right: 24,
      realtime: true,
      showDetail: false,
      showDataShadow: false,
      brushSelect: false,
      zoomLock: false,
      backgroundColor: 'rgba(91,120,153,.12)',
      dataBackground: {
        lineStyle: { color: 'rgba(120,154,190,.25)', width: 1 },
        areaStyle: { color: 'rgba(88,126,164,.06)' }
      },
      selectedDataBackground: {
        lineStyle: { color: 'rgba(112,183,235,.42)', width: 1 },
        areaStyle: { color: 'rgba(90,168,255,.08)' }
      },
      fillerColor: 'rgba(90,168,255,.20)',
      borderColor: 'rgba(89,118,151,.28)',
      handleSize: '115%',
      handleStyle: {
        color: '#789fc5',
        borderColor: '#9bc5e8',
        borderWidth: 1
      },
      moveHandleSize: 4,
      moveHandleStyle: { color: 'rgba(126,164,199,.72)' },
      emphasis: {
        handleStyle: { color: '#9bcdf3', borderColor: '#c5e8ff' },
        moveHandleStyle: { color: '#9bcdf3' }
      }
    };
  }

  function withSlider(option) {
    if (!option || typeof option !== 'object') return option;
    const out = { ...option };

    // Reserve only a small extra strip below the x-axis so the slider stays slim.
    if (Array.isArray(out.grid)) {
      out.grid = out.grid.map((g, i) => i === 0 ? { ...g, bottom: Math.max(Number(g?.bottom) || 0, 50) } : g);
    } else {
      out.grid = { ...(out.grid || {}), bottom: Math.max(Number(out.grid?.bottom) || 0, 50) };
    }

    out.dataZoom = [compactSlider()];
    return out;
  }

  function patchChart(chart) {
    if (!chart || patched.has(chart)) return;
    const originalSetOption = chart.setOption.bind(chart);

    chart.setOption = function(option, ...args) {
      return originalSetOption(withSlider(option), ...args);
    };

    patched.add(chart);

    // The source-link script is loaded after the page's own chart code. If a chart
    // already rendered, merge the slider into the existing option immediately.
    originalSetOption({
      grid: { bottom: 50 },
      dataZoom: [compactSlider()]
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

  // Charts are created after async CSV/JSON fetches, so watch briefly for them.
  const observer = new MutationObserver(scan);
  observer.observe(document.documentElement, { childList: true, subtree: true });

  let attempts = 0;
  const timer = setInterval(() => {
    scan();
    attempts += 1;
    if (attempts >= 60) {
      clearInterval(timer);
      observer.disconnect();
    }
  }, 250);
})();
