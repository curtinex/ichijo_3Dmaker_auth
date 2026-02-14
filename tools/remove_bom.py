from pathlib import Path
p=Path('streamlit_app_v4.py')
b=p.read_bytes()
if b.startswith(b'\xef\xbb\xbf'):
    p.write_bytes(b[len(b'\xef\xbb\xbf'):])
    print('BOM removed')
else:
    print('No BOM found')
