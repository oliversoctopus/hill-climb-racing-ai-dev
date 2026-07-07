import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tune import run_trace
from compare import load

js = load("trace_js.json")
n = len(js)

def lpath(trace, prefix, start=30):
    s, prev = 0, None
    for r in trace[start:n]:
        ca = r["cangle"]; dx = r[prefix+"x"] - r["cx"]; dy = r[prefix+"y"] - r["cy"]
        ly = dx * math.sin(-ca) + dy * math.cos(-ca)
        if prev is not None: s += abs(ly - prev)
        prev = ly
    return s

print(f'JS front-local-y path: {lpath(js, "w1"):.2f}')
print(f'JS back-local-y path:  {lpath(js, "w0"):.2f}')
print()

configs = [
    ("newest tuned (~JS susp_freq, high damp)", 858.5, 393.0, 0.79, 70.1, 39.5, 0.48, 0.39, 1.10),
    ("prev tuned (susp_damp=39)",               834,   419,   0.75, 76.5, 39,   0.50, 0.37, 0.99),
    ("lower susp_damp=25",                      834,   419,   0.75, 76,   25,   0.50, 0.37, 0.99),
    ("soft suspension (freq=25, damp=5)",       834,   419,   0.75, 25,   5,    0.50, 0.37, 0.99),
    ("very stiff (freq=120, damp=80)",          834,   419,   0.75, 120,  80,   0.50, 0.37, 0.99),
]
for label, *p in configs:
    t = run_trace(*p)
    print(f'  {label:<42} front-local-y={lpath(t, "w1"):6.2f}  back-local-y={lpath(t, "w0"):6.2f}  final cx={t[-1]["cx"]:.0f}')
