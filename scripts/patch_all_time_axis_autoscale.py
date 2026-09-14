from pathlib import Path

# 1) Shared navigator: filter out-of-window points so ECharts recalculates Y axes
slider_path = Path('assets/chart-time-slider.js')
slider = slider_path.read_text(encoding='utf-8')
old = "filterMode: 'none'"
new = "filterMode: 'filter'"
count = slider.count(old)
if count:
    if count != 1:
        raise SystemExit(f'Unexpected filterMode none count: {count}')
    slider = slider.replace(old, new)
elif new not in slider:
    raise SystemExit('Shared chart slider filterMode not found')
slider_path.write_text(slider, encoding='utf-8')

# 2) Live score history: dynamically scale within the semantic 0-100 bounds
index_path = Path('index.html')
index = index_path.read_text(encoding='utf-8')
old_score_axis = "yAxis:{...chartBase.yAxis,min:0,max:100}"
new_score_axis = "yAxis:{...chartBase.yAxis,scale:true,min:v=>{const s=v.max-v.min,p=s>0?s*.08:Math.max(Math.abs(v.min)*.05,1);return Math.max(0,v.min-p)},max:v=>{const s=v.max-v.min,p=s>0?s*.08:Math.max(Math.abs(v.max)*.05,1);return Math.min(100,v.max+p)}}"
if old_score_axis in index:
    index = index.replace(old_score_axis, new_score_axis, 1)
elif new_score_axis not in index:
    raise SystemExit('Score history axis pattern not found')
index_path.write_text(index, encoding='utf-8')

# 3) Historical backtest score chart: same dynamic scaling, still capped at 0-100
backtest_path = Path('backtest.html')
backtest = backtest_path.read_text(encoding='utf-8')
old_backtest_axis = "yAxis:{type:'value',min:0,max:100,splitLine:{lineStyle:{color:'rgba(54,79,108,.24)'}},axisLabel:{color:'#7389a3'}}"
new_backtest_axis = "yAxis:{type:'value',scale:true,min:v=>{const s=v.max-v.min,p=s>0?s*.08:Math.max(Math.abs(v.min)*.05,1);return Math.max(0,v.min-p)},max:v=>{const s=v.max-v.min,p=s>0?s*.08:Math.max(Math.abs(v.max)*.05,1);return Math.min(100,v.max+p)},splitLine:{lineStyle:{color:'rgba(54,79,108,.24)'}},axisLabel:{color:'#7389a3'}}"
if old_backtest_axis in backtest:
    backtest = backtest.replace(old_backtest_axis, new_backtest_axis, 1)
elif new_backtest_axis not in backtest:
    raise SystemExit('Backtest axis pattern not found')
backtest_path.write_text(backtest, encoding='utf-8')

print('AI Bubble Monitor time-series charts now autoscale Y axes to visible ranges; score axes remain capped at 0-100.')
