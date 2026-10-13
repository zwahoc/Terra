"""Destructive tests on demo-terra-local only. Use a fresh ephemeral emulator."""
import copy,os,unittest
from terra.local_adapter import LocalDataConnect,variables,equivalent,AdapterError
from terra.seeding import seed_local,verify
from terra.validation import load,validate
from terra.contract import FIELDS,TYPES,camel

@unittest.skipUnless(os.environ.get('TERRA_RUN_EMULATOR_TESTS')=='1','Use npm run test:integration for isolated local emulator tests')
class EmulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter=LocalDataConnect();cls.seed=load()
        seed_local(cls.seed,cls.adapter,reset_confirmation='demo-terra-local')
    def tearDown(self):seed_local(self.seed,self.adapter,reset_confirmation='demo-terra-local')
    def test_all_named_queries(self):
        for entity in FIELDS:
            result=self.adapter.execute('List'+TYPES[entity]+'s')
            self.assertEqual(len(result[camel(entity)]),len(self.seed[entity]),entity)
        verify(self.adapter,self.seed)
        actual=self.adapter.snapshot();actual['metadata']=self.seed['metadata']
        self.assertEqual(validate(actual)['confirmed_reuse_mass_t'],2.375)
    def test_repeat_import(self):
        self.adapter.execute('ImportBaseline',variables(self.seed),write=True)
        self.adapter.execute('ImportBaseline',variables(self.seed),write=True)
        self.assertEqual(seed_local(self.seed,self.adapter)['action'],'unchanged')
        verify(self.adapter,self.seed)
    def test_reset_same_state(self):
        before=self.adapter.snapshot();seed_local(self.seed,self.adapter,reset_confirmation='demo-terra-local')
        self.assertTrue(equivalent(before,self.adapter.snapshot()))
    def test_python_named_write_read_back(self):
        row=variables(self.seed)['projects'][0].copy();row['name']='Elmina Demo Python read/write proof'
        self.adapter.execute('UpsertProjects',{'rows':[row]},write=True)
        data=self.adapter.execute('ListProjects')['projects']
        self.assertEqual(next(x for x in data if x['id']=='PRJ-001')['name'],row['name'])
    def test_runtime_changes_refused(self):
        row=variables(self.seed)['projects'][0].copy();row['name']='Demo runtime edit'
        self.adapter.execute('UpsertProjects',{'rows':[row]},write=True)
        with self.assertRaisesRegex(ValueError,'Refusing overwrite'):seed_local(self.seed,self.adapter)
        self.assertEqual(self.adapter.snapshot()['projects'][0]['name'],row['name'])
    def test_ordinary_query_and_write_denied(self):
        with self.assertRaisesRegex(AdapterError,'403'):self.adapter.execute('SeedSnapshot',admin=False)
        with self.assertRaisesRegex(AdapterError,'403'):self.adapter.execute('UpsertProjects',{'rows':variables(self.seed)['projects']},write=True,admin=False)
    def test_atomic_import_rollback(self):
        before=self.adapter.snapshot();bad=variables(self.seed)
        bad['projects'][0]['name']='Demo mutation that must rollback'
        bad['impactAssessments'][-1]['proposalId']='ALC-999'
        with self.assertRaises(AdapterError):self.adapter.execute('ImportBaseline',bad,write=True)
        self.assertTrue(equivalent(before,self.adapter.snapshot()))
    def test_primary_key_upsert(self):
        rows=variables(self.seed)['materials']
        self.adapter.execute('UpsertMaterials',{'rows':rows},write=True)
        self.adapter.execute('UpsertMaterials',{'rows':rows},write=True)
        self.assertEqual(len(self.adapter.execute('ListMaterials')['materials']),20)
    def test_invalid_fk(self):
        bad=variables(self.seed)['supplyOffers'][0].copy();bad['materialId']='MAT-999'
        with self.assertRaises(AdapterError):self.adapter.execute('UpsertSupplyOffers',{'rows':[bad]},write=True)
        verify(self.adapter,self.seed)
    def test_invalid_enum(self):
        bad=variables(self.seed)['transfers'][0].copy();bad['status']='DONE'
        with self.assertRaises(AdapterError):self.adapter.execute('UpsertTransfers',{'rows':[bad]},write=True)
        verify(self.adapter,self.seed)

if __name__=='__main__':unittest.main()
