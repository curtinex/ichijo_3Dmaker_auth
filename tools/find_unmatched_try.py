import sys
from pathlib import Path
p=Path(r"c:\Users\curtin\Documents\DX\3_DMM生成AI\自由課題\deploy\会員登録検証\ichijo_3Dmaker_auth\streamlit_app_v4.py")
lines=p.read_text(encoding='utf-8').splitlines()
stack=[]
for i,l in enumerate(lines, start=1):
    stripped=l.lstrip('\t ')
    indent=len(l)-len(stripped)
    s=stripped
    # ignore comments
    if s.startswith('#'):
        continue
    if s.startswith('try:'):
        stack.append((i, indent))
    elif s.startswith('except') or s.startswith('finally'):
        # find last try with indent <= this indent
        for j in range(len(stack)-1, -1, -1):
            if stack[j][1]==indent:
                stack.pop(j)
                break
        else:
            print(f"Unmatched {s.split()[0]} at line {i} (no matching try found)")

if stack:
    print('Unmatched try(s) found:')
    for ln,ind in stack:
        print(f'  try at line {ln} (indent={ind})')
else:
    print('All try/except/finally balanced (by indent heuristic)')
