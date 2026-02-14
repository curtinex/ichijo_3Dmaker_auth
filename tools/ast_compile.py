import traceback
p='streamlit_app_v4.py'
try:
    src=open(p,'r',encoding='utf-8').read()
    compile(src,p,'exec')
    print('COMPILED_OK')
except SyntaxError as e:
    print('SYNTAXERROR')
    print(e.msg)
    print('lineno', e.lineno)
    print('offset', e.offset)
    print('text:', repr(e.text))
    traceback.print_exc()
except Exception:
    print('OTHER ERROR')
    traceback.print_exc()
