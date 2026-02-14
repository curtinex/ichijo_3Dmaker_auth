import tokenize, io
p='streamlit_app_v4.py'
s=open(p,'rb').read()
try:
    g=tokenize.tokenize(io.BytesIO(s).readline)
except Exception as e:
    print('tokenize error', e)
    raise
stack=[]
for tok in g:
    ttype, tstr, start, end, line = tok
    lineno, col = start
    if ttype==tokenize.NAME and tstr=='try':
        # lookahead for ':' token
        stack.append((lineno, col))
    elif ttype==tokenize.NAME and (tstr=='except' or tstr=='finally'):
        # find nearest try with same indent
        if stack:
            # naive pop last
            stack.pop()
        else:
            print('Unmatched', tstr, 'at', lineno)

print('Remaining try stack:', stack)
