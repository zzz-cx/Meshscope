"""Safety regressions for resource planning, worker admission and wait recovery."""
import threading
import os
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from istio_Dynamic_Test.internal.models.testcase import TestCase, PolicyType
from istio_Dynamic_Test.internal.pipeline.scheduling.locks import (
    LockManager, plan_case_resources, tag_case_locks, run_safely_in_parallel,
)
from istio_Dynamic_Test.internal.pipeline.scheduling.queue import ObservationWait
from istio_Dynamic_Test.internal.models.testcase import (
    TestSuite, ExecutionResult, CollectionResult, ValidationResult, ValidationStatus,
)


def case(name, host='reviews', **kw):
    return TestCase(case_id=name, name=name, host=host, **kw)


class ResourcePlanTests(unittest.TestCase):
    def test_policy_label_alone_is_not_a_write(self):
        tc = case('a', policy_types=[PolicyType.CIRCUIT_BREAKER],
                  test_strategies=['circuit_breaker'])
        plan_case_resources(tc, 'demo', [])
        keys = tag_case_locks(tc, 'demo')
        self.assertIn('observation:demo:reviews', keys)
        self.assertFalse(any(k.startswith('resource:') for k in keys))

    def test_fqdn_and_short_service_share_observation(self):
        keys = []
        for host in ['reviews', 'reviews.demo', 'reviews.demo.svc.cluster.local']:
            tc = case(host, host=host)
            plan_case_resources(tc, 'demo', [])
            keys.append({k for k in tag_case_locks(tc, 'demo') if k.startswith('observation:')})
        self.assertEqual(keys[0], keys[1])
        self.assertEqual(keys[0], keys[2])
        other = case('other', host='reviews.other.svc.cluster.local')
        plan_case_resources(other, 'demo', [])
        self.assertNotEqual(keys[0], {k for k in tag_case_locks(other, 'demo') if k.startswith('observation:')})

    def test_ingress_writer_conflicts_with_reader_of_another_service(self):
        inventory = [{'metadata': {'name':'meshscope-synth-ingress','namespace':'demo'},
                      'spec': {'hosts':['*'], 'http':[{'route':[
                          {'destination':{'host':'meshscope-svc-0000'}},
                          {'destination':{'host':'meshscope-svc-0001'}}]}]}}]
        writer = case('writer', host='meshscope-svc-0000', trigger_condition='simulate_503_error')
        reader = case('reader', host='meshscope-svc-0001')
        for tc in (writer, reader): plan_case_resources(tc, 'demo', inventory)
        locks = LockManager()
        held = locks.try_reserve(tag_case_locks(writer,'demo'))
        self.assertIsNotNone(held)
        self.assertIsNone(locks.try_reserve(tag_case_locks(reader,'demo')))
        held.release()
        reservation = locks.try_reserve(tag_case_locks(reader,'demo'))
        self.assertIsNotNone(reservation)
        reservation.release()

    def test_only_actual_injection_is_a_write_not_outlier_validation(self):
        delay = case('delay', fault_params={'simulate_slow_response':True,'response_delay':'1s'})
        plan_case_resources(delay,'demo',[])
        self.assertIn('resource:VirtualService:demo:reviews',tag_case_locks(delay,'demo'))
        outlier = case('outlier', policy_types=[PolicyType.CONNECTION_POOL_OUTLIER])
        plan_case_resources(outlier,'demo',[])
        self.assertFalse(any(k.startswith('resource:') for k in tag_case_locks(outlier,'demo')))

    def test_headers_do_not_claim_metric_isolation(self):
        a,b = case('a',headers={'x-configpilot-case-id':'a'}),case('b',headers={'x-configpilot-case-id':'b'})
        for tc in (a,b): plan_case_resources(tc,'demo',[])
        locks=LockManager(); held=locks.try_reserve(tag_case_locks(a,'demo'))
        self.assertIsNone(locks.try_reserve(tag_case_locks(b,'demo')))
        held.release()

    def test_missing_inventory_is_conservative(self):
        writer=case('w',trigger_condition='simulate_high_load_with_errors')
        reader=case('r',host='catalog')
        locks=LockManager(); held=locks.try_reserve(tag_case_locks(writer,'demo'))
        self.assertIsNone(locks.try_reserve(tag_case_locks(reader,'demo')))
        held.release()

    def test_declared_downstream_observation_conflicts_are_reserved(self):
        tc=case('productpage',host='productpage',metadata={'observation_services':['reviews.demo.svc.cluster.local']})
        plan_case_resources(tc,'demo',[])
        self.assertIn('observation:demo:reviews',tag_case_locks(tc,'demo'))


class SchedulerTests(unittest.TestCase):
    def test_readers_share_but_writer_waits_and_reservation_is_atomic(self):
        locks=LockManager()
        a=locks.try_reserve(['read:vs']); b=locks.try_reserve(['read:vs'])
        self.assertIsNotNone(a); self.assertIsNotNone(b)
        self.assertIsNone(locks.try_reserve(['free','vs']))
        c=locks.try_reserve(['free']); self.assertIsNotNone(c); c.release()
        a.release(); self.assertIsNone(locks.try_reserve(['vs']))
        b.release(); d=locks.try_reserve(['read:vs','vs'])
        self.assertIsNone(locks.try_reserve(['read:vs']))
        d.release(); d.release()

    def test_conflicting_queue_head_does_not_occupy_worker(self):
        independent_started=threading.Event()
        first_done=threading.Event()
        def run(tc):
            if tc.case_id=='a1':
                self.assertTrue(independent_started.wait(2), 'independent case starved behind lock waiter')
                first_done.set()
            elif tc.case_id=='a2':
                self.assertTrue(first_done.is_set())
            else: independent_started.set()
            return tc.case_id
        result=run_safely_in_parallel(cases=[case('a1'),case('a2'),case('b')],run_case=run,
            max_workers=2,lock_manager=LockManager(),tagger=lambda tc:['A' if tc.case_id.startswith('a') else 'B'])
        self.assertCountEqual(result,['a1','a2','b'])

    def test_wait_releases_worker_but_keeps_reservation(self):
        events=[]; stats={}
        def run(tc):
            events.append(tc.case_id+'-start')
            if tc.case_id=='a1': yield ObservationWait(.03)
            events.append(tc.case_id+'-end')
            return tc.case_id
        result=run_safely_in_parallel(cases=[case('a1'),case('a2'),case('b')],run_case=run,
            max_workers=1,lock_manager=LockManager(),max_inflight=3,stats=stats,
            tagger=lambda tc:['A' if tc.case_id.startswith('a') else 'B'])
        self.assertLess(events.index('b-start'),events.index('a1-end'))
        self.assertGreater(events.index('a2-start'),events.index('a1-end'))
        self.assertEqual(stats['completed'],3); self.assertCountEqual(result,['a1','a2','b'])

    def test_waiting_writer_is_not_overtaken_by_later_readers(self):
        events=[]
        def run(tc):
            events.append(tc.case_id)
            if tc.case_id=='reader1': yield ObservationWait(.02)
            return tc.case_id
        run_safely_in_parallel(cases=[case(n) for n in ['reader1','writer','reader2','independent']],
            run_case=run,max_workers=1,max_inflight=4,lock_manager=LockManager(),
            tagger=lambda tc: ['other'] if tc.case_id=='independent' else ['vs' if tc.case_id=='writer' else 'read:vs'])
        self.assertLess(events.index('independent'),events.index('writer'))
        self.assertLess(events.index('writer'),events.index('reader2'))

    def test_exception_closes_waiting_generators_before_releasing(self):
        locks=LockManager(); recovered=[]
        def run(tc):
            try:
                if tc.case_id=='bad': raise ValueError('failed step')
                yield ObservationWait(1)
            finally:
                # Must still hold this case's reservation during recovery.
                recovered.append((tc.case_id, locks.try_reserve([tc.case_id]) is None))
        with self.assertRaises(ValueError):
            run_safely_in_parallel(cases=[case('waiting'),case('bad')],run_case=run,
                max_workers=1,lock_manager=locks,max_inflight=2,tagger=lambda tc:[tc.case_id])
        self.assertCountEqual(recovered,[('waiting',True),('bad',True)])
        held=locks.try_reserve(['waiting','bad']); self.assertIsNotNone(held); held.release()

    def test_all_recovery_blocks_run_even_if_one_recovery_fails(self):
        locks=LockManager(); recovered=[]
        def run(tc):
            try:
                if tc.case_id=='bad': raise ValueError('step')
                yield ObservationWait(1)
            finally:
                recovered.append(tc.case_id)
                if tc.case_id=='one': raise RuntimeError('recovery')
        with self.assertRaises(RuntimeError):
            run_safely_in_parallel(cases=[case('one'),case('two'),case('bad')],run_case=run,
                max_workers=1,max_inflight=3,lock_manager=locks,tagger=lambda tc:[tc.case_id])
        self.assertCountEqual(recovered,['one','two','bad'])
        held=locks.try_reserve(['one','two','bad']); self.assertIsNotNone(held); held.release()


class PipelineStageTests(unittest.TestCase):
    def setUp(self):
        from istio_Dynamic_Test.internal.pipeline import cli
        self.cli=cli
        self.ssh=SimpleNamespace(run_command=lambda cmd: ('{"items": []}',''),close=lambda:None)
        self.executor=SimpleNamespace(execute=lambda tc:ExecutionResult(
            case_id=tc.case_id,status_codes={'200':1},total_requests=1,success_rate=100))
        self.collector=SimpleNamespace(collect=lambda tc,**kw:CollectionResult(case_id=tc.case_id))
        self.validator=SimpleNamespace(validate=lambda tc,*args:ValidationResult(
            case_id=tc.case_id,overall_status=ValidationStatus.PASSED))

    def test_real_pipeline_resumes_all_cases_and_keeps_results_complete(self):
        with patch.object(self.cli,'SSHClient',return_value=self.ssh), \
             patch.object(self.cli,'save_execution_result'), \
             patch.object(self.cli,'ReportGenerator') as report, \
             patch.dict(os.environ,{'DYNAMIC_TEST_MAX_WORKERS':'2','DYNAMIC_TEST_SLEEP_SCALE':'0.02','DYNAMIC_TEST_EVENT_WAIT':'1'}):
            tester=self.cli.DynamicTester(executor=self.executor,collector=self.collector,
                validator=self.validator,namespace='demo')
            results=tester.run(TestSuite(cases=[case(str(i),host='svc'+str(i)) for i in range(5)]))
            self.assertCountEqual([r.test_case.case_id for r in results],list('01234'))
            self.assertTrue(all(r.validation.passed for r in results))
            self.assertEqual(tester.scheduler_stats['deferred_waits'],5)
            self.assertGreater(tester.scheduler_stats['max_inflight'],2)
            report.return_value.generate.assert_called_once()

    def test_guarded_load_is_not_dispatched_by_either_scheduler_mode(self):
        from istio_Dynamic_Test.internal.models.testcase import TestType
        from istio_Dynamic_Test.internal.pipeline.guards import DynamicSafetyOptions
        from unittest.mock import Mock
        for event_wait in ('0', '1'):
            with self.subTest(event_wait=event_wait), \
                 patch.object(self.cli, 'SSHClient', return_value=self.ssh), \
                 patch.object(self.cli, 'ReportGenerator'), \
                 patch.dict(os.environ, {'DYNAMIC_TEST_MAX_WORKERS': '2', 'DYNAMIC_TEST_EVENT_WAIT': event_wait}):
                executor = Mock()
                tester = self.cli.DynamicTester(executor=executor, collector=self.collector,
                    safety=DynamicSafetyOptions(allow_load_test=False), namespace='demo')
                tc = case('blocked-load', policy_types=[PolicyType.RATE_LIMIT],
                    test_type=TestType.LOAD_TEST, request_count=100, concurrency=8,
                    rate_limit_expect={'mode': 'should_see_limits'})
                results = tester.run(TestSuite(cases=[tc]))
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].validation.overall_status, ValidationStatus.SKIPPED)
                executor.execute.assert_not_called()

    def test_cancelling_observation_restores_fault(self):
        restored=[]
        with patch.object(self.cli,'SSHClient',return_value=self.ssh), \
             patch.object(self.cli,'save_execution_result'):
            tester=self.cli.DynamicTester(executor=self.executor,collector=self.collector,
                validator=self.validator,namespace='demo')
            tester._inject_fault=lambda tc:SimpleNamespace(clear_faults=lambda:restored.append('restored'))
            steps=tester._run_single_steps(case('fault'))
            self.assertIsInstance(next(steps),ObservationWait)
            self.assertEqual(restored,[])
            steps.close()
            self.assertEqual(restored,['restored'])

    def test_legacy_connection_pool_stages_are_not_used_for_validation(self):
        with patch.object(self.cli,'SSHClient',return_value=self.ssh), \
             patch.object(self.cli,'save_execution_result'):
            tester=self.cli.DynamicTester(executor=self.executor,validator=self.validator,namespace='demo')
            tc=case('cp',trigger_condition='connection_pool_outlier_validation')
            plan_case_resources(tc,'demo',[])
            pending=SimpleNamespace(resume_at=time.time()+.02)
            calls=[]
            tester._cp_outlier_executor=SimpleNamespace(
                execute_phase1_clear=lambda tc:pending,
                execute_phase2_recovery=lambda p:(calls.append('recovery') or self.executor.execute(tc)))
            steps=tester._run_single_steps(tc)
            with self.assertRaises(StopIteration) as done: next(steps)
            self.assertEqual(done.exception.value.validation.overall_status, ValidationStatus.INCONCLUSIVE)
            self.assertEqual(calls,[])

    def test_old_connection_pool_executor_refuses_vs_fault_injection(self):
        from istio_Dynamic_Test.internal.traffic.executors import connection_pool_outlier as cp
        executor=cp.ConnectionPoolOutlierExecutor(ssh_client=self.ssh,namespace='demo')
        with self.assertRaisesRegex(RuntimeError, 'outlier'):
            executor.execute_phase1_clear(case('cp'))


if __name__=='__main__': unittest.main()
