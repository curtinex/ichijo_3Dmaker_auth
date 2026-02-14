from pathlib import Path
p=Path('streamlit_app_v4.py')
lines=p.read_text(encoding='utf-8').splitlines()
lineno=1740
# find last try before lineno
last_try=None
for i in range(lineno-1, -1, -1):
    if lines[i].lstrip().startswith('try:'):
        last_try=(i+1, lines[i])
        break
print('last try before', lineno, ':', last_try)
# print from try line to next 100 lines
start = last_try[0]-1 if last_try else max(0, lineno-20)
end = min(len(lines), start+200)
for idx in range(start, end):
    print(f"{idx+1:5d}: {lines[idx]}")
