import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tune import run_trace, score

target = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'trace_js.json')))

t = run_trace(700, 350, 1.5, 70, 25, 0.1)
print(f'baseline (JS values): score={score(t, target):.1f}  final cx={t[-1]["cx"]:.0f}  angle={t[-1]["cangle"]:.2f}')

for wf in [1.0, 0.7, 0.5, 0.3, 0.1]:
    t = run_trace(700, 350, wf, 70, 25, 0.1)
    print(f'  wf={wf}: score={score(t, target):.1f}  cx={t[-1]["cx"]:.0f}  angle={t[-1]["cangle"]:.2f}')

print('Now also lowering motor torque:')
for (mr, mf) in [(500, 250), (300, 150), (150, 75)]:
    t = run_trace(mr, mf, 1.5, 70, 25, 0.1)
    print(f'  motor=({mr},{mf}): score={score(t, target):.1f}  cx={t[-1]["cx"]:.0f}  angle={t[-1]["cangle"]:.2f}')
