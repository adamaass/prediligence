import base64,sys,pathlib
files=sys.argv[1:]
rows=[]
for f in files:
    s=pathlib.Path(f).read_text()
    u="data:image/svg+xml;base64,"+base64.b64encode(s.encode()).decode()
    w=s.replace('#000','#fff').replace('fill="#fff"','fill="#FFFX"') # placeholder
    inv=s.replace('#fff','#0f1424').replace('#000','#fff')
    ui="data:image/svg+xml;base64,"+base64.b64encode(inv.encode()).decode()
    rows.append(f'''<div style="display:flex;align-items:center;gap:22px;margin-bottom:14px"><b style="width:120px">{f}</b>
<img src="{u}" width="200"><img src="{u}" width="64"><img src="{u}" width="28"><img src="{u}" width="16">
<div style="background:#0f1424;padding:10px 14px;border-radius:8px;display:flex;align-items:center;gap:8px"><img src="{ui}" width="28"><span style="color:#fff;font-weight:600;font-family:Helvetica">PreDiligence</span></div></div>''')
pathlib.Path('look.html').write_text('<!doctype html><body style="margin:0;padding:16px;font-family:sans-serif;font-size:12px">'+''.join(rows)+'</body>')
