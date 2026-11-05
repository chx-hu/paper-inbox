"""Install opt-in macOS login startup; --dry-run prints the planned launch file."""
import argparse
import os
import plistlib
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
LABEL='org.paperinbox.app'
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    app=ROOT/'Paper Inbox.app'
    log=Path.home()/'Library/Caches/Paper Inbox'
    config={'Label':LABEL,'ProgramArguments':['/usr/bin/open','-W','-g',str(app)],
            'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':30,
            'WorkingDirectory':str(Path.home()),'StandardOutPath':str(log/'launcher.log'),
            'StandardErrorPath':str(log/'launcher.log')}
    path=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
    if args.dry_run:print(plistlib.dumps(config).decode());return
    if not app.is_dir():raise SystemExit('Run ./setup.sh or ./build.sh first.')
    path.parent.mkdir(parents=True,exist_ok=True);log.mkdir(parents=True,exist_ok=True)
    path.write_bytes(plistlib.dumps(config))
    domain=f'gui/{os.getuid()}'
    subprocess.run(['launchctl','bootout',domain+'/'+LABEL],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run(['launchctl','bootstrap',domain,str(path)],check=True)
    print('Paper Inbox will start when you log in. Keep its source folder in place.')
if __name__=='__main__':main()
