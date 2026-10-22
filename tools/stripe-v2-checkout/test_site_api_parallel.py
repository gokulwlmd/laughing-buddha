"""Payment preparation overlaps reads, never overlaps a financial write."""
import threading
import unittest

from demo.session_api import UpstreamError
import test_site_session_api as session_fixtures


class ParallelPaymentReadsTests(unittest.TestCase):
    setUp=session_fixtures.SessionApiTests.setUp
    tearDown=session_fixtures.SessionApiTests.tearDown
    create=session_fixtures.SessionApiTests.create
    configured=session_fixtures.SessionApiTests.configured
    quoted=session_fixtures.SessionApiTests.quoted
    prepared=session_fixtures.SessionApiTests.prepared

    def check_overlap(self,resume=False):
        if resume:
            path,headers,data,_=self.prepared()
            quote_id=self.store.read(data['session_id'])['quote_id']
        else:
            path,headers,data,quote=self.quoted();quote_id=quote['quote_id']
        original=self.transport.call
        rendezvous=threading.Barrier(3);release_status=threading.Event();config_done=threading.Event()
        completed=set();financial=[];row_objects=[];answers=[];errors=[];guard=threading.Lock()

        def call(row,method,upstream_path,body=None,client_ip=None):
            if method=='GET' and upstream_path in ('/api/config','/api/status'):
                with guard:row_objects.append(row)
                rendezvous.wait(3)  # Both GETs must have started together.
                if upstream_path=='/api/status' and not release_status.wait(3):raise TimeoutError()
                result=original(row,method,upstream_path,body,client_ip)
                with guard:completed.add(upstream_path)
                if upstream_path=='/api/config':config_done.set()
                return result
            if upstream_path in ('/api/authorize','/api/resume'):
                with guard:financial.append((upstream_path,set(completed)))
            return original(row,method,upstream_path,body,client_ip)
        self.transport.call=call

        def prepare():
            try:answers.append(self.client.post(path+'/payment',headers=headers,json={'quote_id':quote_id,'accept_terms':False}))
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=prepare);worker.start()
        try:
            rendezvous.wait(3)
            self.assertTrue(config_done.wait(3))
            self.assertEqual(financial,[])
            self.assertEqual(completed,{'/api/config'})
            self.assertEqual(len(row_objects),2)
            self.assertIsNot(row_objects[0],row_objects[1])
        finally:
            release_status.set();worker.join(5)
        self.assertFalse(worker.is_alive());self.assertEqual(errors,[])
        self.assertEqual(answers[0].status_code,200,answers[0].text)
        expected='/api/resume' if resume else '/api/authorize'
        self.assertEqual(financial,[(expected,{'/api/config','/api/status'})])
        self.assertEqual(self.fake.count('/authorize_payment'),1)

    def test_authorization_waits_for_both_concurrent_reads(self):
        self.check_overlap()

    def test_resume_waits_for_both_concurrent_reads_without_new_authorization(self):
        self.check_overlap(resume=True)

    def test_either_read_failure_prevents_authorization_and_waits_for_other_read(self):
        original=self.transport.call
        for failing in ('/api/config','/api/status'):
            with self.subTest(failing=failing):
                self.transport.call=original
                path,headers,data,quote=self.quoted()
                rendezvous=threading.Barrier(2);finished=set();financial=[];guard=threading.Lock()
                def call(row,method,upstream_path,body=None,client_ip=None):
                    if method=='GET' and upstream_path in ('/api/config','/api/status'):
                        rendezvous.wait(3)
                        try:
                            if upstream_path==failing:raise UpstreamError()
                            return original(row,method,upstream_path,body,client_ip)
                        finally:
                            with guard:finished.add(upstream_path)
                    if upstream_path in ('/api/authorize','/api/resume'):financial.append(upstream_path)
                    return original(row,method,upstream_path,body,client_ip)
                self.transport.call=call
                response=self.client.post(path+'/payment',headers=headers,json={'quote_id':quote['quote_id'],'accept_terms':False})
                self.assertEqual(response.status_code,502,response.text)
                self.assertEqual(finished,{'/api/config','/api/status'})
                self.assertEqual(financial,[])
                self.assertEqual(self.fake.count('/authorize_payment'),0)

    def test_unavailable_config_prevents_authorization_after_both_reads_complete(self):
        path,headers,data,quote=self.quoted();original=self.transport.call
        rendezvous=threading.Barrier(2);finished=set();financial=[];guard=threading.Lock()
        def call(row,method,upstream_path,body=None,client_ip=None):
            if method=='GET' and upstream_path in ('/api/config','/api/status'):
                rendezvous.wait(3)
                result,cookies=original(row,method,upstream_path,body,client_ip)
                if upstream_path=='/api/config':result['ready']=False
                with guard:finished.add(upstream_path)
                return result,cookies
            if upstream_path in ('/api/authorize','/api/resume'):financial.append(upstream_path)
            return original(row,method,upstream_path,body,client_ip)
        self.transport.call=call
        response=self.client.post(path+'/payment',headers=headers,json={'quote_id':quote['quote_id'],'accept_terms':False})
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(finished,{'/api/config','/api/status'});self.assertEqual(financial,[])
        self.assertEqual(self.fake.count('/authorize_payment'),0)


if __name__=='__main__':unittest.main()
