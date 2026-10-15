import json
import sys

from ai_mirror.cli import main, submission_body


def test_submission_retry_reuses_closed_issue_without_new_message(monkeypatch, capsys):
    title = 'Learning journal: alex — sprint-3'
    body = submission_body('example/garden','alex','sprint-3','a'*40,
                           'journal/alex/sprint-3/reflection.md','https://example.com/ai-brief',None)
    mutations=[]
    def run(args, **kwargs):
        if args[:2] != ['gh','api']:
            mutations.append(args)
    def output(args, **kwargs):
        assert args[:3] == ['gh','issue','list']
        return json.dumps([{'title':title,'url':'https://github.com/example/garden/issues/7',
                            'body':body,'state':'CLOSED'}])
    monkeypatch.setattr('subprocess.run',run)
    monkeypatch.setattr('subprocess.check_output',output)
    monkeypatch.setattr(sys,'argv',['ai-mirror','submission','--repo','example/garden','--student','alex',
                                    '--sprint','sprint-3','--sha','a'*40,'--journal',
                                    'journal/alex/sprint-3/reflection.md','--brief','https://example.com/ai-brief','--publish'])
    main()
    assert not mutations
    assert '"submitted": true' in capsys.readouterr().out


def test_submission_revision_does_not_duplicate_existing_comment(monkeypatch):
    title = 'Learning journal: alex — sprint-3'
    body = submission_body('example/garden','alex','sprint-3','b'*40,
                           'journal/alex/sprint-3/reflection.md','https://example.com/ai-brief',None)
    mutations=[]
    def run(args, **kwargs):
        if args[:2] != ['gh','api']:
            mutations.append(args)
    def output(args, **kwargs):
        if args[2]=='list':
            return json.dumps([{'title':title,'url':'https://github.com/example/garden/issues/7',
                                'body':'Earlier version','state':'CLOSED'}])
        assert args[2]=='view'
        return json.dumps({'comments':[{'body':body}]})
    monkeypatch.setattr('subprocess.run',run)
    monkeypatch.setattr('subprocess.check_output',output)
    monkeypatch.setattr(sys,'argv',['ai-mirror','submission','--repo','example/garden','--student','alex',
                                    '--sprint','sprint-3','--sha','b'*40,'--journal',
                                    'journal/alex/sprint-3/reflection.md','--brief','https://example.com/ai-brief','--publish'])
    main()
    assert not mutations
