import re
import unittest
from mockaize_api.formulas import evaluate, valid_cpf, valid_cnpj, filename


class FormulaTests(unittest.TestCase):
    def test_compose_has_no_aggregate_output_byte_cap(self):
        class ReportedBytes:
            def __len__(self):
                return 100000001

        class ReportedText(str):
            def __str__(self):
                return self

            def encode(self, *args, **kwargs):
                return ReportedBytes()

        formula = {'type': 'compose', 'parts': [{'type': 'literal', 'value': ReportedText('x')}]}
        self.assertEqual(evaluate(formula, {}), 'x')

    def test_deterministic_formula_types(self):
        context={'configName':'A B','count':3,'recordIndex':2,'fileIndex':4,'sourceValue':lambda p:'7','outputValue':lambda p:'8','groupValues':lambda f:['0.1','0.2'],'profiles':{},'baseDate':'2026-10-23','referenceDateTime':'2026-10-23T12:00:00Z'}
        samples=[({'type':'literal','value':'abc'},'abc'),({'type':'copy','path':'p'},'7'),({'type':'field','path':'p'},'8'),({'type':'groupSum'},'0.3'),({'type':'config'},'AB'),({'type':'count'},'3'),({'type':'list','values':'x\ny','index':1},'y'),({'type':'zeros','length':3},'000'),({'type':'sequence','width':2},'03'),({'type':'sequence','width':2,'scope':'file'},'05'),({'type':'compose','operation':'sum','parts':[{'type':'literal','value':'0.1'},{'type':'literal','value':'0.2'}]},'0.3'),({'type':'date','mode':'business'},'2026-10-26')]
        for formula, expected in samples:
            with self.subTest(formula=formula): self.assertEqual(expected,evaluate(formula,context))

    def test_random_types_and_profiles(self):
        context={'profiles':{}}
        self.assertTrue(valid_cpf(evaluate({'type':'cpf','mask':True},context)))
        for mode in ['N','A']: self.assertTrue(valid_cnpj(evaluate({'type':'cnpj','mode':mode},context)))
        self.assertRegex(evaluate({'type':'hash','length':32},context),r'^[0-9a-f]{32}$')
        self.assertEqual('ZZZ',evaluate({'type':'alpha','alphabet':'Z','length':3},context))
        self.assertEqual('1.25',evaluate({'type':'random','min':1.25,'max':1.25},context))
        self.assertEqual(12,len(evaluate({'type':'id','mode':'common','prefix':'CT'},context)))
        self.assertRegex(evaluate({'type':'id'},context),r'^[0-9a-f-]{36}$')
        for kind,field in [('person','name'),('company','legalName'),('address','full')]:
            f={'type':kind,'field':field,'state':'CE'}
            self.assertEqual(evaluate(f,context),evaluate(f,context))

    def test_safe_filenames(self):
        self.assertEqual('file.xml',filename('file'))
        for value in ['../a','CON','a.','x/y','']:
            with self.subTest(value=value), self.assertRaises(ValueError): filename(value)

    def test_dates_use_reference_clock_base_date_and_custom_utc(self):
        context={'baseDate':'2026-10-23','referenceDateTime':'2026-10-23T02:03:04.123Z','timeZone':'America/Fortaleza'}
        self.assertEqual('2026-10-25 23:03:04.123 -03:00',evaluate({'type':'date','mode':'offset','days':2,'format':'yyyy-MM-dd HH:mm:ss.fff zzz'},context))
        self.assertEqual('2026-10-24T02:03:04.123Z',evaluate({'type':'date','mode':'specific','value':'2026-10-23','format':'custom','custom':{'order':'YMD','dateSeparator':'-','join':'T','milliseconds':True,'timezone':True,'zone':'utc'}},context))
        self.assertEqual('27/10/2026',evaluate({'type':'date','mode':'business','holidays':'2026-10-26','format':'dd/MM/yyyy'},context))
        self.assertEqual('23:03:04',evaluate({'type':'date','mode':'specific','value':'2026-10-23','format':'custom','custom':{'day':False,'month':False,'year':False,'join':'T'}},context))

    def test_length_decimal_and_formula_limits(self):
        from mockaize_api.formulas import check_length, sum_decimals
        self.assertEqual('😀é',check_length('😀éx',2,True))
        self.assertEqual('100000000000000000000000000000000000001',sum_decimals(['100000000000000000000000000000000000000','1']))
        for values in [['1e2'],['0.0000000000001'],['NaN'],['']]:
            with self.subTest(values=values),self.assertRaises(ValueError):sum_decimals(values)
        formula={'type':'literal','value':'x'}
        for _ in range(8):formula={'type':'compose','parts':[formula]}
        with self.assertRaises(ValueError):evaluate(formula,{})
        for formula in [{'type':'evil'},{'type':'random','min':9,'max':1},{'type':'cnpj','establishment':'0000'},{'type':'address','state':'XX'},{'type':'id','mode':'common','prefix':'toolong','length':1},{'type':'sequence','step':0},{'type':'list','values':[]}]:
            with self.subTest(formula=formula),self.assertRaises(ValueError):evaluate(formula,{})
