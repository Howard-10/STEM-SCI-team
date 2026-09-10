from __future__ import annotations

import json, pathlib, urllib.request, urllib.error, uuid

BASE='http://127.0.0.1:8013/api/v1'
ROOT=pathlib.Path(__file__).resolve().parents[1]
PAPER=ROOT/'test_data/public_reanalysis/cgt_physics_education/paper_tschisgale_2023.pdf'
DATA=ROOT/'test_data/public_reanalysis/cgt_physics_education/Textual_descriptions.csv'

def call(method,path,token=None,body=None,file=None):
    headers={'Accept':'application/json'}
    if token: headers['Authorization']=f'Bearer {token}'
    payload=None
    if body is not None:
        payload=json.dumps(body,ensure_ascii=False).encode(); headers['Content-Type']='application/json'
    if file is not None:
        b='----stem-'+uuid.uuid4().hex
        payload=b''.join([f'--{b}\r\n'.encode(),f'Content-Disposition: form-data; name="file"; filename="{file.name}"\r\n'.encode(),b'Content-Type: application/octet-stream\r\n\r\n',file.read_bytes(),f'\r\n--{b}--\r\n'.encode()]); headers['Content-Type']=f'multipart/form-data; boundary={b}'
    req=urllib.request.Request(BASE+path,data=payload,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=180) as r:return json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e: raise RuntimeError(e.read().decode())
def reg(prefix):
    u=prefix+uuid.uuid4().hex[:8]
    x=call('POST','/auth/register',body={'username':u,'email':u+'@example.test','password':'research-pass-123'})
    return x['user'],x['access_token']
def main():
    u,t=reg('qcres'); v,vt=reg('qcrev'); pid='qual-conv-'+uuid.uuid4().hex[:8]
    call('POST','/projects',t,{'project_id':pid,'title':'对话式物理公开语料再分析','research_direction':'公开二手资料再分析：基于学生物理问题解决文本，重新检查物理问题解决主题，并比较有物理奥赛经历与无物理奥赛经历学生的主题构成。'})
    call('PUT',f'/projects/{pid}/members',t,{'username':v['username'],'role':'reviewer'})
    call('POST',f'/projects/{pid}/documents/upload',t,file=PAPER)
    def cmd(msg,token=t,mode='auto'):
        x=call('POST',f'/projects/{pid}/conversation/command',token,{'project_id':pid,'message':msg,'interaction_mode':mode})
        print(json.dumps({'msg':msg,'kind':x.get('kind'),'checkpoint':x.get('checkpoint'),'gate':(x.get('gate') or {}).get('gate_type'),'response':x.get('message')},ensure_ascii=False))
        return x
    cmd('我想先讨论这个公开物理教育语料的研究边界、变量和局限，不要执行分析。',mode='discussion')
    cmd('现在开始建立研究任务：请基于已上传真实论文和公开 OSF 数据形成证据审阅，研究只做公开二手资料的定性主题再分析，不作统计或因果结论。')
    print('PROJECT',pid,'USER',u['username'],'REVIEWER',v['username'])
if __name__=='__main__': main()
