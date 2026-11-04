"""Changed decoder risks only; no native/provider or old acceptance execution."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('fastpath_document_store',ROOT/'scripts/git_document_store.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)


class CanonicalDecoderFastpathTests(unittest.TestCase):
    def store(self,payloads):
        store=object.__new__(g.GitDocumentStore);calls=[]
        payloads=list(payloads);position=0
        def batch(specifications,kind,bound):
            nonlocal position
            calls.append((kind,len(specifications),bound))
            if kind=='tree':return [b'100644 document.json\0'+b'x'*20 for _ in specifications]
            result=payloads[position:position+len(specifications)];position+=len(specifications)
            return result
        store._batch_objects=batch
        # Decoder tests own an in-memory transport for both current POSIX
        # sessions and the original non-POSIX fallback. No Git is involved.
        store.repo=Path('decoder-fixture')
        class Session:
            def __enter__(self):return self
            def __exit__(self,*exc):return False
            read=staticmethod(batch)
        session=patch.object(g,'_ObjectBatchSession',return_value=Session())
        session.start();self.addCleanup(session.stop)
        return store,calls

    def test_canonical_history_uses_no_python_key_callbacks_and_keeps_typed_values(self):
        values=[{}, {'text':'é𝄞\n','nested':[{'x':1,'y':None},True,False],
                    'numbers':[-0.0,1.0,1e-200,2**63-1]}, {'escaped':'"\\\t','𝄞':'value'}]
        payloads=[g.canonical(value).encode() for value in values]
        store,_=self.store(payloads)
        with patch.object(g,'unique_object',side_effect=AssertionError('redundant Python key callback')):
            actual=list(store._read_document_objects([f'{i+1:040x}' for i in range(len(values))]))
        self.assertEqual([g.canonical(value) for value in actual],[p.decode() for p in payloads])

    def test_inexact_decoder_keeps_large_integer_through_original_strict_fallback(self):
        value={'large':10**50,'nested':{'negative':-(10**50)}}
        payload=g.canonical(value).encode();store,_=self.store([payload])
        # A supported optional decoder can return a float for an out-of-range
        # integer. Exact canonical inequality must retain the strict fallback.
        inexact={'large':float(10**50),'nested':{'negative':-float(10**50)}}
        with patch.object(g,'_json_loads',return_value=inexact), \
                patch.object(g,'unique_object',wraps=g.unique_object) as strict:
            actual=list(store._read_document_objects(['a'*40]))
        self.assertTrue(strict.called)
        self.assertEqual(actual,[value])
        self.assertIs(type(actual[0]['large']),int)
        self.assertEqual(g.canonical(actual[0]).encode(),payload)

    def test_rejected_payloads_keep_original_duplicate_and_other_error_diagnostics(self):
        cases=[(b'{"a":1,"a":2}\n',ValueError,'duplicate coordination JSON key'),
            (b'{"x":{"a":1,"a":2}}\n',ValueError,'duplicate coordination JSON key'),
            (b'{"x":{"a":1,"a":2},"broken":}\n',ValueError,'duplicate coordination JSON key'),
            (b'{"a":1,"a":2,"nan":NaN}\n',ValueError,'duplicate coordination JSON key'),
            (b'{"nan":NaN,"x":{"a":1,"a":2}}\n',ValueError,'duplicate coordination JSON key'),
            (b'{"a":1,"\\u0061":2}\n',ValueError,'duplicate coordination JSON key'),
            (b'{ "a":1}\n',ValueError,'historical coordination document must have canonical JSON encoding'),
            (b'{"b":2,"a":1}\n',ValueError,'historical coordination document must have canonical JSON encoding'),
            (b'[]\n',ValueError,'coordination document must be an object'),
            (b'{',json.JSONDecodeError,None)]
        for payload,kind,message in cases:
            with self.subTest(payload=payload):
                store,_=self.store([payload])
                with self.assertRaises(kind) as raised:list(store._read_document_objects(['a'*40]))
                if message is not None:self.assertEqual(str(raised.exception),message)

    def test_transport_remains_bounded_lazy_detached_and_does_not_swallow_consumer_errors(self):
        payload=g.canonical({'nested':{'original':True}}).encode()
        store,calls=self.store([payload]*33);revisions=[f'{i+1:040x}' for i in range(33)]
        values=store._read_document_objects(iter(revisions));first=next(values)
        self.assertEqual([n for _,n,_ in calls],[16,16])
        first['nested']['original']=False
        self.assertTrue(next(values)['nested']['original'])
        marker=ValueError('consumer_signal')
        with self.assertRaises(ValueError) as raised:values.throw(marker)
        self.assertIs(raised.exception,marker)
        self.assertEqual(len(calls),2)
        store,calls=self.store([payload]*33)
        self.assertEqual(len(list(store._read_document_objects(revisions))),33)
        self.assertEqual([n for _,n,_ in calls],[16,16,16,16,1,1])


if __name__=='__main__':unittest.main()
