import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from codex_cloud_development import CodexCloudDevelopment, validate_development_request, ContractError

def request():
    return {"schema":"codex-cloud-development-request/v1", "operation_key":"sha256:"+"a"*64, "attempt_id":"dev-a1", "repository":"org/repo", "environment_id":"env-verified", "environment_label":"org/repo", "source_branch":"cdc/development", "base_sha":"b"*40, "allowed_paths":["docs/result.md"], "acceptance_criteria":["Write a bounded result"], "checks":[{"id":"layout", "argv":["python", "-B", "layout.py"], "minimum_test_count":None}], "budget_ref":"git:"+"c"*40}

class TransportTests(unittest.TestCase):
    def test_official_status_exit_semantics_survive_restart(self):
        for status, exit_code, expected in [('READY',0,'waiting_result'),('PENDING',1,'running'),('ERROR',1,'failed'),('PENDING',2,'unknown'),('READY',1,'unknown')]:
            with self.subTest(status=status,exit_code=exit_code), tempfile.TemporaryDirectory() as root:
                calls=[]
                def runner(argv,**kw):
                    calls.append(argv)
                    if argv[2]=='exec':return SimpleNamespace(returncode=0,stdout='https://chatgpt.com/codex/tasks/task_exact',stderr='')
                    return SimpleNamespace(returncode=exit_code,stdout='['+status+']',stderr='')
                r=request();CodexCloudDevelopment(root,runner=runner).submit(r,launch_authorized=lambda:None)
                observed=CodexCloudDevelopment(root,runner=runner).observe(r['operation_key'])
                self.assertEqual(observed['state'],expected)
                if expected=='failed':self.assertEqual(observed['reason'],'provider_error')
                self.assertEqual(sum(argv[2]=='exec' for argv in calls),1)

    def test_unknown_fields_and_invalid_base_rejected(self):
        for field,value in [("extra",True),("base_sha","not-a-sha"),("environment_id",""),("allowed_paths",["../outside"]),("allowed_paths",[])]:
            with self.subTest(field=field,value=value):
                r=request();r[field]=value
                with self.assertRaises(ContractError):validate_development_request(r)

    def test_lost_reply_never_replays_after_restart(self):
        calls=[]
        def runner(argv,**kw):
            calls.append(argv);raise TimeoutError("reply lost")
        with tempfile.TemporaryDirectory() as root:
            r=request();t=CodexCloudDevelopment(root,runner=runner)
            self.assertEqual(t.submit(r,launch_authorized=lambda:None)["state"],"unknown")
            self.assertEqual(CodexCloudDevelopment(root,runner=runner).submit(r,launch_authorized=lambda:self.fail("recreated authority"))["state"],"unknown")
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][1:9],["cloud","exec","--env","env-verified","--branch","cdc/development","--attempts","1"])

    def test_ready_is_waiting_result_and_export_hashes_exact_bytes(self):
        calls=[];diff=b"diff --git a/docs/result.md b/docs/result.md\n+actual result\n"
        def runner(argv,**kw):
            calls.append(argv)
            action=argv[2]
            if action=="exec":return SimpleNamespace(returncode=0,stdout="https://chatgpt.com/codex/tasks/task_exact",stderr="")
            if action=="status":return SimpleNamespace(returncode=0,stdout="[READY]",stderr="")
            if action=="diff":return SimpleNamespace(returncode=0,stdout=diff,stderr=b"")
            self.fail("unexpected CLI effect")
        with tempfile.TemporaryDirectory() as root:
            t=CodexCloudDevelopment(Path(root)/"journal",runner=runner);r=request()
            t.submit(r,launch_authorized=lambda:None)
            self.assertEqual(t.observe(r["operation_key"])["state"],"waiting_result")
            exported=t.export_diff(r["operation_key"],evidence_root=Path(root)/"evidence")
            self.assertEqual(Path(exported["artifact_ref"]["path"]).read_bytes(),diff)
            import hashlib
            self.assertEqual(exported["artifact_ref"]["sha256"],hashlib.sha256(diff).hexdigest())
            self.assertEqual(exported["provider_attempt"],1)
            self.assertFalse(any("apply" in argv or "push" in argv for argv in calls))

    def test_recovery_paginates_and_rejects_wrong_environment(self):
        for environment,expected in [("different-env","unknown"),("env-verified","waiting_result")]:
            calls=[]
            def runner(argv,**kw):
                calls.append(argv)
                if argv[2]=="exec":raise TimeoutError("lost reply")
                if argv[2]=="status":return SimpleNamespace(returncode=0,stdout="[READY]",stderr="")
                if "--cursor" not in argv:page={"tasks":[],"cursor":"page2"}
                else:page={"tasks":[{"id":"task_recovered","title":request()["operation_key"]+" dev-a1","environment_id":environment}],"cursor":None}
                return SimpleNamespace(returncode=0,stdout=json.dumps(page),stderr="")
            with tempfile.TemporaryDirectory() as root:
                t=CodexCloudDevelopment(root,runner=runner);r=request();t.submit(r,launch_authorized=lambda:None)
                self.assertEqual(t.observe(r["operation_key"])["state"],expected)
                self.assertEqual(sum(argv[2]=="exec" for argv in calls),1)
                self.assertEqual(sum(argv[2]=="list" for argv in calls),2)

    def test_export_before_ready_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            t=CodexCloudDevelopment(root,runner=lambda *a,**k:SimpleNamespace(returncode=0,stdout="https://chatgpt.com/codex/tasks/task_exact",stderr=""))
            r=request();t.submit(r,launch_authorized=lambda:None)
            with self.assertRaises(ContractError):t.export_diff(r["operation_key"],evidence_root=Path(root)/"evidence")

    def test_interrupted_export_restarts_without_dispatch(self):
        from unittest import mock
        import codex_cloud_development as module
        calls=[];payload=b'diff --git a/docs/result.md b/docs/result.md\n+result\n'
        def runner(argv,**kw):
            calls.append(argv)
            if argv[2]=='exec':return SimpleNamespace(returncode=0,stdout='https://chatgpt.com/codex/tasks/task_exact',stderr='')
            if argv[2]=='status':return SimpleNamespace(returncode=0,stdout='[READY]',stderr='')
            return SimpleNamespace(returncode=0,stdout=payload,stderr=b'')
        with tempfile.TemporaryDirectory() as root:
            r=request();t=CodexCloudDevelopment(Path(root)/'journal',runner=runner);t.submit(r,launch_authorized=lambda:None);t.observe(r['operation_key'])
            with mock.patch.object(module.os,'link',side_effect=OSError('interrupted install')):
                with self.assertRaises(OSError):t.export_diff(r['operation_key'],evidence_root=Path(root)/'evidence')
            exported=CodexCloudDevelopment(Path(root)/'journal',runner=runner).export_diff(r['operation_key'],evidence_root=Path(root)/'evidence')
            self.assertEqual(Path(exported['artifact_ref']['path']).read_bytes(),payload)
            self.assertEqual(sum(argv[2]=='exec' for argv in calls),1)
    def test_prompt_report_fields_match_strict_bridge_schema(self):
        from codex_cloud_development import prompt
        # Canonical report fields are the approved protocol, not a mirror of parser internals.
        self.assertIn('repository, environment_id, base_sha, head_before',prompt(request()))
        self.assertNotIn('environment_id, environment_label, base_sha',prompt(request()))

    def test_gate_denial_has_no_cli_effect(self):
        with tempfile.TemporaryDirectory() as root:
            def denied():raise PermissionError("budget denied")
            t=CodexCloudDevelopment(root,runner=lambda *a,**k:self.fail("dispatch after denial"))
            self.assertEqual(t.submit(request(),launch_authorized=denied)["state"],"failed")

if __name__=="__main__":unittest.main()
