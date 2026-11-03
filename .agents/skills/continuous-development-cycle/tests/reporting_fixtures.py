"""Actual canonical Git reporting inventory for native lifecycle tests only."""
import copy
import reporting_contract as reporting
from git_document_store import GitDocumentStore

def binding(lease_store,invocation_id,checkpoint_ref,*,kind='final'):
 store=GitDocumentStore(lease_store.repo,lease_store.remote,reporting.inventory_ref(invocation_id),lease_store.store_id,protected_refs=[lease_store.ref])
 revision,existing=store.read()
 owned_revision,owned=lease_store.read()
 if existing is None:
  assert owned['owner_id'] is not None and owned['invocation']['invocation_id']==invocation_id
  doc={'schema':'execution-rca-inventory/v1','invocation_id':invocation_id,'owner_id':owned['owner_id'],'generation':owned['generation'],'owned_lease_revision':owned_revision,'checkpoint_ref':checkpoint_ref,'material':[]}
 else:
  doc=copy.deepcopy(existing);doc['checkpoint_ref']=checkpoint_ref
 if existing!=doc:revision=store.compare_and_swap(revision,doc)
 assert store.read_revision(revision)==doc
 import managed_host_bridge as bridge
 request=reporting.capture(invocation_id,kind,'Проверенный результат native исполнителя и открытая очередь сохранены.',clock=lambda:reporting._time(bridge._utc()))
 return {'schema':'execution-reporting-binding/v1','inventory_revision':revision,'report':request,'material_ids':[x['anomaly_id'] for x in doc['material']],'claimed_resolved_ids':[]}

def attach(state,lease_store):
 state['schema']='execution-continuity/v2'
 state['reporting_binding']=binding(lease_store,state['invocation_id'],state['checkpoint_ref'])
 return reporting.authenticate(lease_store,state['reporting_binding'],state['invocation_id'],state['checkpoint_ref'])
