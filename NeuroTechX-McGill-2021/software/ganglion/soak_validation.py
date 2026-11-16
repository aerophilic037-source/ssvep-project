"""Optional >10 minute LSL endurance check with ONLY generated signals.

Exercises receiver ring-buffer rollover and repeated raw/session/report writes.
It opens no hardware and displays no flicker. Not part of quick unit tests.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
from uuid import uuid4

import numpy as np

from acquisition import Receiver, lsl
from validation import dumps
from validation_app import create_app


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blocks',type=int,default=22,help='30 seconds/block; 22 blocks exceeds the 120k-sample ring buffer')
    parser.add_argument('--out',type=Path,default=Path(__file__).resolve().parent/'validation_reports/soak')
    args=parser.parse_args()
    if not 1 <= args.blocks <= 120:
        parser.error('--blocks must be 1..120')
    args.out.mkdir(parents=True,exist_ok=True)
    lib=lsl()
    name='SOAK-SYNTHETIC-ONLY-'+uuid4().hex
    outlet=lib.StreamOutlet(lib.StreamInfo(name,'EEG',4,200,'float32',name))
    stop=threading.Event()
    sender_errors=[]
    def send():
        try:
            start=lib.local_clock();i=0
            rng=np.random.default_rng(20261114)
            while not stop.is_set():
                stamp=start+i/200
                if stamp>lib.local_clock():
                    time.sleep(.002);continue
                row=rng.normal(0,2,4)+12*np.sin(2*np.pi*12*i/200+np.arange(4)*.2)
                outlet.push_sample(row.tolist(),timestamp=stamp);i+=1
        except Exception as exc:
            sender_errors.append(str(exc))
    sender=threading.Thread(target=send,daemon=True);sender.start()
    receiver=Receiver()
    started=time.monotonic()
    result={'synthetic_only':True,'started_utc':datetime.now(timezone.utc).isoformat(),'blocks':[]}
    client=None
    failure=None
    try:
        receiver.connect(next(s['uid'] for s in receiver.discover() if s['name']==name))
        time.sleep(.4)
        client=create_app(receiver,args.out/'captures').test_client()
        setup={'channels':[0,1,2,3],'units':'uV','lsl_filters':'off',
               'positions':'SYNTHETIC ONLY','notes':'Long software endurance test. No participant, no physical board, no display stimulus.'}
        session=client.post('/api/session',json={'setup':setup}).json['id']
        result['session']=session
        for block in range(args.blocks):
            r=client.post('/api/block/start',json={'condition':'rest','duration':30})
            if r.status_code!=200:
                raise RuntimeError(r.json)
            time.sleep(30)
            r=client.post('/api/block/finish',json={'id':r.json['id']})
            if r.status_code!=200:
                raise RuntimeError(r.json)
            t=r.json
            file=args.out/'captures'/session/t['recording']
            with np.load(file,allow_pickle=False) as z:
                ordered=bool(np.all(np.diff(z['sequence'])==1))
                count=len(z['samples'])
            record={'block':block+1,'eligible':t['analysis']['eligible'],'ordered':ordered,
                    'raw_count':count,'timing':t['analysis']['timing'],'recording':str(file)}
            result['blocks'].append(record)
            (args.out/'latest.json').write_text(dumps(result),encoding='utf-8')
            print(f"block {block+1}/{args.blocks}: eligible={record['eligible']}, ordered={ordered}, raw={count}, rate={record['timing'].get('capture_rate_hz'):.2f} Hz",flush=True)
        with receiver.lock:
            result['receiver_sequence']=receiver.sequence
            result['retained_records']=len(receiver.records)
            result['oldest_retained_sequence']=receiver.records[0][0]
            result['ring_buffer_rolled_over']=receiver.records[0][0]>1
        result['passed']=all(r['eligible'] and r['ordered'] and 5700<=r['raw_count']<=6300 for r in result['blocks'])
        if args.blocks>=22:
            result['passed'] &= result['ring_buffer_rolled_over']
    except (Exception,KeyboardInterrupt) as exc:
        failure=str(exc) or 'KeyboardInterrupt'
        result['passed']=False
        if client:
            active=client.get('/api/status').json['active_trial']
            if active:
                client.post('/api/block/finish',json={'id':active['id'],'aborted':True,'reason':'soak test interrupted'})
    finally:
        receiver.disconnect();stop.set();sender.join(timeout=3)
        result.update(elapsed_seconds=time.monotonic()-started,failure=failure,sender_errors=sender_errors)
        result['passed']=bool(result.get('passed') and not sender_errors)
        (args.out/'latest.json').write_text(dumps(result),encoding='utf-8')
    print(dumps({k:v for k,v in result.items() if k!='blocks'}),flush=True)
    if not result['passed']:
        raise SystemExit(1)


if __name__=='__main__':
    main()
