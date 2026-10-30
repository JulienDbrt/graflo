"""Deterministic file-backed GraFlo workload shared by all engines."""

import csv
import hashlib
import json
import unicodedata
from pathlib import Path


def normalize_title(value):
    return unicodedata.normalize('NFC', value.strip())


def source_record(i, revision):
    return {
        'id':f'urn:item:{i//10}', 'tenant':f'tenant{i%10}', 'seq':str(i),
        'title':f'  E\u0301lément {i} · 東京  ', 'score':str(i%1000+.25+(.5 if revision==2 else 0)),
        'revision':str(revision), 'payload':'x'*100, 'category':str((i//10)%100),
    }


def expected_record(i, revision):
    return [i,f'tenant{i%10}',str(i//10),f'Élément {i} · 東京',
            i%1000+.25+(.5 if revision==2 else 0),revision,'x'*100,str((i//10)%100)]


def generate(root, documents):
    directory=root/f'data-{documents}'
    directory.mkdir(exist_ok=True)
    files=[]
    for phase,start,revision in [('initial',0,1),('delta',documents//2,2)]:
        for fmt,offset in [('csv',0),('jsonl',documents//2)]:
            path=directory/f'{phase}.{fmt}'
            if not path.exists():
                with path.open('w',encoding='utf-8',newline='') as handle:
                    writer=None
                    for i in range(start+offset,start+offset+documents//2):
                        record=source_record(i,revision)
                        if fmt=='csv':
                            if writer is None:
                                writer=csv.DictWriter(handle,fieldnames=list(record))
                                writer.writeheader()
                            writer.writerow(record)
                        else:handle.write(json.dumps(record,ensure_ascii=False)+'\n')
            files.append({'path':str(path.relative_to(root)),'bytes':path.stat().st_size,
                          'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                          'records':documents//2,'phase':phase,'format':fmt})
    (directory/'files.json').write_text(json.dumps(files,indent=2)+'\n')
    return directory


def manifest_config():
    transforms=[{'transform':{'rename':{'tenant':'tenant','payload':'payload','category':'category'}}}]
    for module,foo,field,params in [
        ('graflo.util.transform','remove_prefix','id',{'prefix':'urn:item:'}),
        ('builtins','int','seq',{}),('builtins','float','score',{}),
        ('builtins','int','revision',{}),('scenario','normalize_title','title',{}),
    ]:
        transforms.append({'transform':{'call':{'module':module,'foo':foo,
                           'input':[field],'output':[field],'params':params}}})
    return {
        'schema':{'metadata':{'name':'falkor_etl_benchmark'},
            'graph':{
                'vertex_config':{'vertices':[
                    {'name':'Item','properties':['id','tenant','seq','title','score','revision','payload','category'],
                     'identity':['tenant','id']},
                    {'name':'Category','properties':['tenant','id'],'identity':['tenant','id']},
                ]},
                'edge_config':{'edges':[{'source':'Item','target':'Category','relation':'IN_CATEGORY'}]},
            },
            'db_profile':{'db_flavor':'falkordb','vertex_indexes':{'Item':[{'fields':['score']},{'fields':['seq']}]}}
        },
        'ingestion_model':{'resources':[{'name':'items','pipeline':transforms+[
            {'vertex':'Item','from':{k:k for k in ['id','tenant','seq','title','score','revision','payload','category']}},
            {'vertex':'Category','from':{'tenant':'tenant','id':'category'}},
            {'edge':{'from':'Item','to':'Category','relation':'IN_CATEGORY'}},
        ]}]},
    }


def query_case(worker, iteration, documents):
    kind=['point','one_hop','two_hops','range_sort','group_count'][(worker+iteration)%5]
    i=(iteration*7919+worker*104729)%min(documents//2,10000)
    params={'tenant':f'tenant{i%10}','id':str(i//10)}
    if kind=='point':
        query='MATCH (n:Item {tenant:$tenant,id:$id}) RETURN n.seq,n.revision,n.score'
    elif kind=='one_hop':
        query='MATCH (n:Item {tenant:$tenant,id:$id})-[:IN_CATEGORY]->(g:Category) RETURN g.tenant,g.id'
    elif kind=='two_hops':
        query=('MATCH (n:Item {tenant:$tenant,id:$id})-[:IN_CATEGORY]->(:Category)'
               '<-[:IN_CATEGORY]-(peer:Item) RETURN count(peer)')
    elif kind=='range_sort':
        query=('MATCH (n:Item) WHERE n.tenant=$tenant AND n.score >= 990 '
               'RETURN n.seq,n.score ORDER BY n.score DESC,n.seq LIMIT 10')
    else:
        query=('MATCH (g:Category)<-[:IN_CATEGORY]-(n:Item) WHERE g.tenant=$tenant '
               'RETURN g.id,count(n) AS cnt ORDER BY cnt DESC,g.id LIMIT 10')
    return kind,i,query,params


def check_query(kind,i,rows,documents,phase):
    minimum=documents//1000
    maximum=(documents+documents//2)//1000 if phase in ['mixed','post_idle'] else minimum
    if phase=='post_idle':minimum=maximum
    if kind=='point':return rows==[[i,1,i%1000+.25]]
    if kind=='one_hop':return rows==[[f'tenant{i%10}',str((i//10)%100)]]
    if kind=='two_hops':return len(rows)==1 and minimum<=rows[0][0]<=maximum
    if kind=='range_sort':
        return (min(10,documents//1000)<=len(rows)<=10 and
                len({row[0] for row in rows})==len(rows) and
                all(row[0]%10==i%10 and row[1]>=990 for row in rows) and
                rows==sorted(rows,key=lambda r:(-r[1],r[0])))
    return len(rows)==10 and len({row[0] for row in rows})==10 and all(minimum<=r[1]<=maximum for r in rows)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--documents',type=int,default=100000)
    args=p.parse_args()
    directory=generate(Path(__file__).parent,args.documents)
    (Path(__file__).parent/'manifest.json').write_text(json.dumps(manifest_config(),indent=2)+'\n')
    print(directory)
