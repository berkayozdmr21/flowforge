"""Package source and prebuilt frontend; exclude all private runtime data."""
import os,json,zipfile,hashlib,re
from pathlib import Path
ROOT=Path(__file__).absolute().parents[1]
for name in ['README.md','VERIFICATION.md']:
    f=ROOT/name;s=f.read_text(encoding='utf-8').replace('81 automated checks','82 automated checks').replace('64 backend/domain','65 backend/domain');f.write_text(s,encoding='utf-8')
f=ROOT/'VERIFICATION.md';s=f.read_text(encoding='utf-8');note='The final browser acceptance also imported a delay workflow from JSON, refreshed while it was running, reattached to the same run ID in read-only mode and cancelled it from the UI. The mini map displayed all three nodes and all three report links were visible.'
if note not in s:s+='\n'+note+'\n';f.write_text(s,encoding='utf-8')
target=ROOT.parent/'flowforge.zip'
exclude={'.git','.venv','.runtime','.tools','.tmp','.pytest_cache','node_modules','__pycache__'}
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for base,dirs,files in os.walk(ROOT):
        dirs[:]=[d for d in dirs if d not in exclude]
        for name in files:
            if name=='.env' or name.endswith(('.pyc','.log')):continue
            file=Path(base)/name;archive.write(file,Path('flowforge')/file.relative_to(ROOT))
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    names=archive.namelist()
    for n in names:
        assert not (set(Path(n).parts)&exclude),n
    for required in ['README.md','BASLAT.cmd','run.py','requirements.lock.txt','backend/app/workflow.py','frontend/dist/index.html','docs/studio.jpg']:
        assert 'flowforge/'+required in names
    for n in names:
        if n.endswith(('.py','.md','.ts','.tsx','.json','.yaml','.yml')) and '/dist/' not in n:
            assert not re.search(rb'(?:github_pat_|ghp_|sk-proj-)[A-Za-z0-9_]{20,}',archive.read(n)),n
    print(json.dumps({'archive':str(target),'files':len(names),'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))
