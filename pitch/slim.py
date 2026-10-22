import zipfile, re, sys
src, dst = sys.argv[1], sys.argv[2]
zin = zipfile.ZipFile(src)
names = zin.namelist()
keep_layout = 'slideLayout7.xml'
drop = {n for n in names if re.match(r'ppt/slideLayouts/(_rels/)?slideLayout\d+\.xml(\.rels)?$', n) and keep_layout not in n}
drop |= {n for n in names if n.startswith('docProps/thumbnail')}
mrels = zin.read('ppt/slideMasters/_rels/slideMaster1.xml.rels').decode()
keep_rids = set()
def fr(m):
    t = m.group(0)
    if 'slideLayout' in t and keep_layout not in t: return ''
    return t
mrels2 = re.sub(r'<Relationship [^>]*/>', fr, mrels)
rids = set(re.findall(r'Id="(rId\d+)"', mrels2))
master = zin.read('ppt/slideMasters/slideMaster1.xml').decode()
master2 = re.sub(r'<p:sldLayoutId [^>]*r:id="(rId\d+)"[^>]*/>', lambda m: m.group(0) if m.group(1) in rids else '', master)
ct = zin.read('[Content_Types].xml').decode()
ct2 = re.sub(r'<Override PartName="/ppt/slideLayouts/slideLayout\d+\.xml"[^>]*/>', lambda m: m.group(0) if keep_layout in m.group(0) else '', ct)
ct2 = re.sub(r'<Override PartName="/docProps/thumbnail[^>]*/>', '', ct2)
rootrels = zin.read('_rels/.rels').decode()
rootrels2 = re.sub(r'<Relationship [^>]*thumbnail[^>]*/>', '', rootrels)
zout = zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED, compresslevel=9)
for n in names:
    if n in drop: continue
    data = zin.read(n)
    if n == 'ppt/slideMasters/_rels/slideMaster1.xml.rels': data = mrels2.encode()
    elif n == 'ppt/slideMasters/slideMaster1.xml': data = master2.encode()
    elif n == '[Content_Types].xml': data = ct2.encode()
    elif n == '_rels/.rels': data = rootrels2.encode()
    zout.writestr(n, data)
zout.close()
print(len(drop), 'parts dropped')
