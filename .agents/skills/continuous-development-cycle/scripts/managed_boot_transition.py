"""Protected local boot history for an already released original failure.

An attestation is historical host evidence, not terminal, lease or send authority.
Only the ordinary native claim/capability/release verifier can compose it.
"""
from __future__ import annotations
import argparse,copy,hashlib,json,os,re,stat,subprocess,time,uuid
from datetime import datetime,timezone
from pathlib import Path

_SEAL=object()
_LIMIT=65536
_MAX_AGE=120


def _digest(value):
    return 'sha256:'+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')


def _date(value):
    if not isinstance(value,str) or not value.endswith('Z'):
        raise ValueError('boot transition requires UTC Z timestamps')
    try:return datetime.fromisoformat(value[:-1]+'+00:00')
    except ValueError:raise ValueError('invalid boot transition timestamp') from None


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate boot transition field')
        result[key]=value
    return result


def _decode(raw):
    if len(raw)>_LIMIT:raise ValueError('boot transition record too large')
    def invalid(value):raise ValueError('nonfinite boot transition value')
    try:return json.loads(raw,object_pairs_hook=_unique,parse_constant=invalid)
    except (ValueError,UnicodeError):raise ValueError('invalid boot transition record') from None


def _current_host():
    return {'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'machine_id':Path('/etc/machine-id').read_text().strip(),
        'pid_namespace':os.readlink('/proc/self/ns/pid'),
        'boot_epoch_us':int((time.time()-time.clock_gettime(time.CLOCK_BOOTTIME))*1000000)}


def _host(value):
    if not isinstance(value,dict) or set(value)!={'boot_id','machine_id','pid_namespace','boot_epoch_us'}:
        raise ValueError('exact current host binding required')
    try:valid=str(uuid.UUID(value['boot_id']))==value['boot_id']
    except (ValueError,TypeError,AttributeError):valid=False
    if (not valid or not isinstance(value['machine_id'],str) or not re.fullmatch('[0-9a-f]{32}',value['machine_id'])
            or not isinstance(value['pid_namespace'],str) or not re.fullmatch(r'pid:\[[0-9]+\]',value['pid_namespace'])
            or type(value['boot_epoch_us']) is not int or value['boot_epoch_us']<=0):
        raise ValueError('invalid current host identity')


def _parent(path):
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts or path.name in ('','.','..'):
        raise ValueError('absolute protected boot record path required')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try:
        for name in path.parts[1:-1]:
            nxt=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
            os.close(fd);fd=nxt
            info=os.fstat(fd)
            if info.st_uid!=0 or stat.S_IMODE(info.st_mode)&0o022:
                raise ValueError('root-owned non-writable boot record ancestors required')
        return fd
    except (OSError,ValueError):
        os.close(fd);raise ValueError('protected boot record ancestry unavailable') from None


def _read_root_record(path):
    directory=None;fd=None
    try:
        directory=_parent(path)
        fd=os.open(Path(path).name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=directory)
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_nlink!=1
                or stat.S_IMODE(info.st_mode)&0o022 or info.st_size>_LIMIT):
            raise ValueError('protected original root boot record required')
        raw=os.read(fd,_LIMIT+1)
        after=os.fstat(fd)
        stable=('st_dev','st_ino','st_uid','st_gid','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
        if any(getattr(after,key)!=getattr(info,key) for key in stable):
            raise ValueError('boot record changed while reading')
        return _decode(raw)
    except OSError:raise ValueError('protected original root boot record unavailable') from None
    finally:
        if fd is not None:os.close(fd)
        if directory is not None:os.close(directory)


def _validate(record,request,observation,release_receipt):
    fields={'schema','task_id','attempt_id','pool_id','request_ref','release_ref','original_boot_id',
        'current_host','last_original_journal_epoch_us','observed_at_utc'}
    if not isinstance(record,dict) or set(record)!=fields or record['schema']!='managed-original-boot-transition/v1':
        raise ValueError('exact original boot transition record required')
    identity=request.get('identity') or {}
    if (any(record[k]!=identity.get(k) for k in ('pool_id','task_id','attempt_id'))
            or record['request_ref']!=_digest(request) or record['release_ref']!=_digest(release_receipt)):
        raise ValueError('boot transition original task/request/release mismatch')
    if observation.get('status')!='failed' or observation.get('quiescent') is not True:
        raise ValueError('boot reconciliation supports only original quiescent FAILED')
    original=record['original_boot_id']
    try:valid=str(uuid.UUID(original))==original
    except (ValueError,TypeError,AttributeError):valid=False
    if not valid or original!=observation.get('boot_id'):
        raise ValueError('original boot observation mismatch')
    current=_current_host();_host(current);saved=record['current_host'];_host(saved)
    if (original==current['boot_id'] or any(current[k]!=saved[k] for k in ('boot_id','machine_id','pid_namespace'))
            or abs(current['boot_epoch_us']-saved['boot_epoch_us'])>1000000):
        raise ValueError('original host boot transition not currently authenticated')
    age=(_date(_now())-_date(record['observed_at_utc'])).total_seconds()
    if not 0<=age<=_MAX_AGE:raise ValueError('stale or future boot transition record')
    try:
        released=_date(release_receipt['release']['at_utc']).timestamp()*1000000
        quiescent=_date(observation['quiescence_proof']['observed_at_utc']).timestamp()*1000000
    except (KeyError,TypeError):raise ValueError('original dated release and quiescence required') from None
    last=record['last_original_journal_epoch_us']
    if type(last) is not int or not 0<max(released,quiescent)<=last<current['boot_epoch_us']:
        raise ValueError('original release/quiescence must precede authenticated host reboot')
    return {'method':'protected_local_journal_boot_transition','original_boot_id':original,
        'current_boot_id':current['boot_id'],'observed_at_utc':record['observed_at_utc'],
        'request_ref':record['request_ref'],'release_ref':record['release_ref'],
        'authorizes_release':False,'authorizes_start':False}


class _VerifiedBootTransition:
    def __init__(self,seal,path,evidence):
        if seal is not _SEAL:raise ValueError('package-owned boot transition required')
        self._seal=seal;self._path=Path(path);self._evidence=copy.deepcopy(evidence)
    @property
    def evidence(self):return copy.deepcopy(self._evidence)
    def revalidate(self,request,observation,release_receipt):
        if type(self) is not _VerifiedBootTransition or self._seal is not _SEAL:
            raise ValueError('authentic original boot transition required')
        current=_validate(_read_root_record(self._path),request,observation,release_receipt)
        if current!=self._evidence:raise ValueError('original boot transition changed')
        return current


def authenticate(path,request,observation,release_receipt):
    evidence=_validate(_read_root_record(path),request,observation,release_receipt)
    return _VerifiedBootTransition(_SEAL,path,evidence)


def collect(*,request,observation,release_receipt):
    """Root-only independent collection; supplied host facts are never accepted."""
    if os.geteuid()!=0:raise ValueError('root local journal producer required')
    old=observation.get('boot_id')
    try:old=str(uuid.UUID(old))
    except (ValueError,TypeError,AttributeError):raise ValueError('original boot UUID required') from None
    host=_current_host();_host(host)
    result=subprocess.run(['/usr/bin/journalctl','--no-pager','--quiet','--boot='+old.replace('-',''),
        '--lines=1','--output=json','--output-fields=_BOOT_ID,_MACHINE_ID,__REALTIME_TIMESTAMP'],
        capture_output=True,text=True,timeout=30,env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C','SYSTEMD_PAGER':'cat'})
    if result.returncode or len(result.stdout.encode())>_LIMIT:
        raise ValueError('original local journal boot unavailable')
    rows=result.stdout.splitlines()
    if len(rows)!=1:raise ValueError('one original local journal boot record required')
    journal=_decode(rows[0])
    if (not isinstance(journal,dict) or journal.get('_BOOT_ID')!=old.replace('-','')
            or journal.get('_MACHINE_ID')!=host['machine_id']
            or not isinstance(journal.get('__REALTIME_TIMESTAMP'),str)
            or not journal['__REALTIME_TIMESTAMP'].isdigit()):
        raise ValueError('original journal boot/machine binding mismatch')
    record={'schema':'managed-original-boot-transition/v1',
        **{k:request['identity'][k] for k in ('pool_id','task_id','attempt_id')},
        'request_ref':_digest(request),'release_ref':_digest(release_receipt),
        'original_boot_id':old,'current_host':host,
        'last_original_journal_epoch_us':int(journal['__REALTIME_TIMESTAMP']),'observed_at_utc':_now()}
    _validate(record,request,observation,release_receipt)
    return record


def write_record(path,record,*,group_id):
    """Exclusive protected evidence write; no native state/lease mutation."""
    if os.geteuid()!=0 or type(group_id) is not int or group_id<=0:
        raise ValueError('root producer and explicit reader group required')
    directory=_parent(path);fd=None
    try:
        fd=os.open(Path(path).name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o640,dir_fd=directory)
        os.fchmod(fd,0o640);os.fchown(fd,0,group_id)
        raw=json.dumps(record,sort_keys=True,allow_nan=False).encode()+b'\n'
        if len(raw)>_LIMIT:raise ValueError('boot transition record too large')
        with os.fdopen(fd,'wb',closefd=False) as stream:stream.write(raw);stream.flush();os.fsync(fd)
        os.fsync(directory)
    finally:
        if fd is not None:os.close(fd)
        os.close(directory)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('request','observation','release-receipt','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--reader-gid',type=int,required=True);args=parser.parse_args(argv)
    try:
        record=collect(request=_decode(Path(args.request).read_bytes()),
            observation=_decode(Path(args.observation).read_bytes()),
            release_receipt=_decode(Path(args.release_receipt).read_bytes()))
        write_record(args.output,record,group_id=args.reader_gid)
    except (OSError,ValueError,subprocess.SubprocessError,KeyError) as error:
        print('BOOT_TRANSITION_BLOCKED: '+type(error).__name__,file=__import__('sys').stderr);return 1
    print(json.dumps({'schema':'managed-boot-transition-write/v1','path':args.output,
        'authorizes_start':False,'authorizes_release':False,'authorizes_terminal':False}));return 0

if __name__=='__main__':raise SystemExit(main())
