"""Reject accidentally bundled per-user state before installer compilation."""
from pathlib import Path
import sys

def audit(root):
    root=Path(root); bad=[]
    forbidden={'.db','.sqlite','.sqlite3','.log','.csv','.cbz','.cbr','.pdf','.mkv','.mp4','.env'}
    names={'release-state.json','settings.json','config.json','credentials.json','downloads.json','doujin_index.db'}
    for path in root.rglob('*'):
        if path.is_file() and (path.suffix.lower() in forbidden or path.name.lower() in names):bad.append(str(path.relative_to(root)))
    if bad:raise RuntimeError('Personal/non-application state in bundle: '+', '.join(bad))
    if not (root/'AniVault.exe').is_file():raise RuntimeError('Missing Windows application binary.')
    print('BundleAudit result=clean personal_state_included=false')
if __name__=='__main__':audit(sys.argv[1])
