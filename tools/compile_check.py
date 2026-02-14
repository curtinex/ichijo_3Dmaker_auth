import py_compile, traceback
p='streamlit_app_v4.py'
try:
    py_compile.compile(p, doraise=True)
    print('COMPILE_OK')
except Exception as e:
    print('COMPILE_ERROR')
    traceback.print_exc()
