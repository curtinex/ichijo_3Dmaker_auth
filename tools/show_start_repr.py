p='streamlit_app_v4.py'
with open(p,'rb') as f:
    data=f.read()
print('first 100 bytes repr:')
print(repr(data[:200]))
print('\nfirst 20 lines repr:')
text=data.decode('utf-8')
for i,l in enumerate(text.splitlines()[:20], start=1):
    print(i, repr(l))
