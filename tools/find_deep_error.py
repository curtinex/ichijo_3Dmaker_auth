p='streamlit_app_v4.py'
lines=open(p,'r',encoding='utf-8').read().splitlines()
for i in range(60, len(lines)+1):
    try:
        compile('\n'.join(lines[:i]), p, 'exec')
    except SyntaxError as e:
        if e.lineno and e.lineno>50:
            print('prefix_end', i, 'error lineno', e.lineno, 'msg', e.msg)
            break
else:
    print('no deep error in prefixes')
