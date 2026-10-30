"""Controlled casting workloads; representative and adverse shapes stay separate."""

from copy import deepcopy

from scenario import manifest_config,source_record


def case(name,n):
    config=manifest_config()
    docs=[source_record(i,1) for i in range(n)]
    if name=='flat':
        config['ingestion_model']['resources'][0]['pipeline']=[config['ingestion_model']['resources'][0]['pipeline'][-3]]
        config['schema']['graph']['vertex_config']['vertices']=config['schema']['graph']['vertex_config']['vertices'][:1]
        config['schema']['graph']['edge_config']['edges']=[]
    elif name=='nested':
        config={
            'schema':{'metadata':{'name':'nested'},'graph':{
                'vertex_config':{'vertices':[
                    {'name':'Item','properties':['id','title'],'identity':['id']},
                    {'name':'Tag','properties':['id','value'],'identity':['id']}]},
                'edge_config':{'edges':[{'source':'Item','target':'Tag','relation':'HAS_TAG'}]}},
                'db_profile':{'db_flavor':'falkordb'}},
            'ingestion_model':{'resources':[{'name':'items','pipeline':[
                {'vertex':'Item','from':{'id':'id','title':'title'}},
                {'key':'tags','pipeline':[{'vertex':'Tag','from':{'id':'id','value':'value'}}]},
                {'edge':{'from':'Item','to':'Tag','relation':'HAS_TAG','match_target':'tags'}},
            ]}]},
        }
        docs=[{'id':str(i),'title':f'Élément {i}','tags':[{'id':f'{i}:{j}','value':str(j)} for j in range(3)]} for i in range(n)]
    elif name=='errors':
        config['ingestion_model']['resources'][0]['types']={'seq':'int'}
        for i,doc in enumerate(docs):
            if i%20==0:doc['seq']='not-an-int'
            elif i%23==0:doc['score']='not-a-float'
    elif name=='transform_stress':
        steps=config['ingestion_model']['resources'][0]['pipeline']
        config['ingestion_model']['resources'][0]['pipeline']=steps[:-3]+[deepcopy(steps[-4]) for _ in range(6)]+steps[-3:]
    elif name!='etl':raise ValueError(name)
    return config,docs
