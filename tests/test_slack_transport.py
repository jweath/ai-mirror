import httpx

from ai_mirror.slack import Slack


def test_metadata_uses_query_parameters_and_messages_stay_json(monkeypatch):
    seen = []
    def get(url, **kwargs):
        seen.append(('GET',url,kwargs))
        assert kwargs['params']['channel'] == 'CTEST' and 'json' not in kwargs
        return httpx.Response(200,json={'ok':True})
    def post(url, **kwargs):
        seen.append(('POST',url,kwargs))
        assert kwargs['json']['channel'] == 'CTEST' and 'params' not in kwargs
        return httpx.Response(200,json={'ok':True,'ts':'1.0001'})
    monkeypatch.setattr(httpx,'get',get)
    monkeypatch.setattr(httpx,'post',post)
    client=Slack('test-token')
    client.call('conversations.info',{'channel':'CTEST'})
    client.call('conversations.members',{'channel':'CTEST','limit':100})
    client.post({'channel':'CTEST','text':'Test'})
    assert [row[0] for row in seen] == ['GET','GET','POST']
