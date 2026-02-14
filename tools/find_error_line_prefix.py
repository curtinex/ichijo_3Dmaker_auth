p='streamlit_app_v4.py'
s=open(p,'r',encoding='utf-8').read()
lines=s.splitlines()
for i in range(1, len(lines)+1):
    try:
        compile('\n'.join(lines[:i]), p, 'exec')
    except SyntaxError as e:
        print('Error at prefix ending line', i, '=>', e.msg, 'lineno', e.lineno)
        break
else:
    print('No syntax error in any prefix')
