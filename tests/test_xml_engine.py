import json
from datetime import datetime, timezone
import unittest
from xml.dom import minidom
from unittest.mock import patch
from mockaize_api.errors import ApiError
from mockaize_api.xml_engine import generate_new, generate_return, validate_return_input
from mockaize_api.policy import ResolvedPolicy


def path(*names):
    return json.dumps([{'ns': '', 'name': name, 'index': 1} for name in names])


def variation():
    return {'name': 'Test Config', 'config': {
        'inputByMode': {'new': {'xml': '<root><header>H</header><r><a>1</a><b>2</b></r></root>', 'group': path('root', 'r')},
                        'return': {'xml': '<root><r><a>1</a></r></root>', 'group': path('root', 'r')}},
        'filenameByMode': {'new': {'type': 'literal', 'value': 'new'}},
        'rulesByMode': {'new': {path('root', 'r', 'a'): {'generator': {'type': 'sequence', 'width': 2}}}},
        'returnModels': [{'id': 'A', 'name': 'Aceito', 'outputXml': '<out><r><a>A</a></r></out>',
                          'outputGroup': path('out', 'r'), 'rules': {path('out', 'r', 'a'): {'generator': {'type': 'copy', 'path': path('root', 'r', 'a')}}},
                          'filename': {'type': 'literal', 'value': 'return'}, 'headers': [], 'presence': {}}]}}


class EngineTests(unittest.TestCase):
    def test_return_requires_explicit_nonempty_input_without_saved_fallback(self):
        for source in (None, '', '  ', False, 2):
            with self.subTest(source=source), self.assertRaises(ApiError) as caught:
                generate_return(variation(), {'type': 'all'}, input_xml=source)
            self.assertEqual(caught.exception.code, 'INVALID_REQUEST')

    def test_custom_and_disabled_record_limits_allow_1000_and_limit_full_source_before_first(self):
        source = '<root>' + '<r><a>9</a></r>' * 1000 + '</root>'
        for maximum in (1000, None):
            policy = ResolvedPolicy(record_count=maximum)
            with self.subTest(maximum=maximum):
                self.assertEqual(generate_new(variation(), 1000, policy=policy)[0]['records'], 1000)
                self.assertEqual(generate_return(variation(), {'type': 'all'}, input_xml=source,
                                                 policy=policy)[0]['records'], 1000)
        with self.assertRaises(ApiError) as caught:
            generate_return(variation(), {'type': 'all'}, input_xml=source, input_records='first')
        self.assertEqual(caught.exception.code, 'RECORD_LIMIT_EXCEEDED')
        with self.assertRaises(ApiError) as caught:
            generate_new(variation(), 1001, policy=ResolvedPolicy(record_count=1000))
        self.assertEqual(caught.exception.code, 'VALIDATION_ERROR')
        with self.assertRaises(ApiError) as caught:
            generate_return(variation(), {'type': 'all'}, input_xml=source, input_records='first',
                            policy=ResolvedPolicy(record_count=999))
        self.assertEqual(caught.exception.code, 'RECORD_LIMIT_EXCEEDED')

    def test_input_policy_counts_utf8_bytes_inclusive_boundary_and_disabled(self):
        source = '<root><r><a>éé</a></r></root>'
        size = len(source.encode('utf-8'))
        for maximum in (size, None):
            policy = ResolvedPolicy(input_xml_bytes=maximum)
            self.assertEqual(generate_return(variation(), {'type': 'all'}, input_xml=source,
                                             input_records='first', policy=policy)[0]['records'], 1)
        with self.assertRaises(ApiError) as caught:
            generate_return(variation(), {'type': 'all'}, input_xml=source,
                            policy=ResolvedPolicy(input_xml_bytes=size - 1))
        self.assertEqual((caught.exception.status, caught.exception.code), (413, 'INPUT_TOO_LARGE'))

    def test_mixed_models_multiply_records_without_new_aggregate_record_limit(self):
        import copy
        v = variation()
        second = copy.deepcopy(v['config']['returnModels'][0])
        second.update(id='B', name='Second')
        v['config']['returnModels'].append(second)
        source = '<root><r><a>1</a></r><r><a>2</a></r></root>'
        result = generate_return(v, {'type': 'all'}, 'mixed', source,
                                 policy=ResolvedPolicy(record_count=2))[0]
        self.assertEqual(result['records'], 4)

    def test_return_captures_one_reference_time_and_uses_preset_timezone_for_all_models(self):
        import copy
        from mockaize_api import xml_engine
        v = variation()
        v['context'] = {'timeZone': 'America/Fortaleza'}
        formula = {'type': 'date', 'mode': 'specific', 'value': '2026-01-01', 'format': 'custom',
                   'custom': {'order': 'YMD', 'yearDigits': '4', 'dateSeparator': '-',
                              'timeSeparator': ':', 'join': ' ', 'day': True, 'month': True,
                              'year': True, 'hour': True, 'minute': True, 'second': True,
                              'milliseconds': False, 'timezone': True, 'zone': 'app'}}
        v['config']['returnModels'][0]['rules'] = {path('out', 'r', 'a'): {'generator': formula}}
        second = copy.deepcopy(v['config']['returnModels'][0])
        second.update(id='B', name='Second')
        v['config']['returnModels'].append(second)
        with patch.object(xml_engine, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 2, 1, 1, 2, 3, tzinfo=timezone.utc)
            results = generate_return(v, {'type': 'all'}, input_xml='<root><r><a>1</a></r></root>')
        self.assertEqual(clock.now.call_count, 1)
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertIn(b'<a>2026-01-01 22:02:03-03:00</a>', result['content'])

    def test_saved_templates_do_not_inherit_request_input_byte_limit(self):
        v = variation()
        v['config']['inputByMode']['new']['xml'] = '<root><header>' + 'x' * 2000000 + '</header><r><a>1</a><b>2</b></r></root>'
        result = generate_new(v, 1, policy=ResolvedPolicy(input_xml_bytes=1))[0]
        self.assertEqual(result['records'], 1)

    def test_disabled_input_size_does_not_disable_safe_parser_or_depth(self):
        policy = ResolvedPolicy(input_xml_bytes=None, record_count=None)
        for source in ('<!DOCTYPE root [<!ENTITY x "value">]><root><r><a>&x;</a></r></root>',
                       '<a>' * 130 + '</a>' * 130, '<root>'):
            with self.subTest(source=source[:40]), self.assertRaises(ApiError) as caught:
                generate_return(variation(), {'type': 'all'}, input_xml=source, policy=policy)
            self.assertEqual(caught.exception.code, 'INPUT_XML_INVALID')

    def test_invalid_unicode_stays_a_controlled_xml_error_with_any_size_policy(self):
        for maximum in (2000000, None):
            with self.subTest(maximum=maximum), self.assertRaises(ApiError) as caught:
                generate_return(variation(), {'type': 'all'}, input_xml='<root>\ud800</root>',
                                policy=ResolvedPolicy(input_xml_bytes=maximum))
            self.assertEqual((caught.exception.status, caught.exception.code), (422, 'INPUT_XML_INVALID'))

    def test_new_uses_requested_count_and_preserves_header(self):
        result = generate_new(variation(), 3)[0]
        doc = minidom.parseString(result['content'])
        self.assertEqual(['01', '02', '03'], [n.firstChild.data for n in doc.getElementsByTagName('a')])
        self.assertEqual(1, len(doc.getElementsByTagName('header')))
        self.assertEqual('new.xml', result['fileName'])

    def test_return_copies_each_input_record(self):
        result = generate_return(variation(), {'type': 'all'}, input_xml='<root><r><a>9</a></r><r><a>8</a></r></root>')[0]
        self.assertEqual(2, result['records'])
        self.assertIn(b'<a>8</a>', result['content'])

    def test_return_first_record_applies_rules_to_only_the_first_input(self):
        v = variation()
        source = '<root><r><a>9</a></r><r><a>8</a></r></root>'
        v['config']['inputByMode']['return']['xml'] = source
        result = generate_return(v, {'type': 'all'}, input_xml=source, input_records='first')[0]
        self.assertEqual(result['records'], 1)
        doc = minidom.parseString(result['content'])
        self.assertEqual([node.firstChild.data for node in doc.getElementsByTagName('a')], ['9'])

    def test_first_record_selection_still_validates_the_whole_input(self):
        with self.assertRaises(ApiError) as caught:
            generate_return(variation(), {'type': 'all'}, input_records='first',
                            input_xml='<root><r><a>9</a></r><r><different/></r></root>')
        self.assertEqual(caught.exception.code, 'INPUT_XML_STRUCTURE_MISMATCH')

    def test_second_divergent_record_is_rejected(self):
        with self.assertRaises(ApiError) as caught:
            validate_return_input('<root><r><a>1</a></r></root>', path('root', 'r'), '<root><r><a>1</a></r><r><b>2</b></r></root>')
        self.assertEqual('INPUT_XML_STRUCTURE_MISMATCH', caught.exception.code)

    def test_dtd_is_rejected(self):
        with self.assertRaises(ApiError):
            validate_return_input('<r/>', path('r'), '<!DOCTYPE r [<!ENTITY a "a">]><r>&a;</r>')

    def test_cycle_is_controlled(self):
        v = variation()
        v['config']['rulesByMode']['new'] = {path('root','r',name): {'generator': {'type': 'field','path': path('root','r',other)}} for name, other in [('a','b'),('b','a')]}
        with self.assertRaises(ApiError): generate_new(v, 1)

    def test_mixed_interleaves_models(self):
        import copy
        v = variation()
        second = copy.deepcopy(v['config']['returnModels'][0])
        second.update(id='B', name='Recusado', rules={path('out','r','a'): {'fixed': 'B'}})
        v['config']['returnModels'].append(second)
        content = generate_return(v, {'type': 'all'}, 'mixed', '<root><r><a>1</a></r><r><a>2</a></r></root>')[0]['content']
        doc = minidom.parseString(content)
        self.assertEqual(['1','B','2','B'], [n.firstChild.data for n in doc.getElementsByTagName('a')])

    def test_mixed_rejects_incompatible_envelope(self):
        import copy
        v=variation(); model=copy.deepcopy(v['config']['returnModels'][0]); model.update(id='B',rules={},outputXml='<different><r><a>A</a></r></different>',outputGroup=path('different','r'));v['config']['returnModels'].append(model)
        with self.assertRaises(ApiError) as caught: generate_return(v, {'type':'all'}, 'mixed', v['config']['inputByMode']['return']['xml'])
        self.assertEqual('RETURN_MODELS_INCOMPATIBLE',caught.exception.code)

    def test_new_count_limits_include_500_and_reject_boolean(self):
        self.assertEqual(500, len(minidom.parseString(generate_new(variation(),500)[0]['content']).getElementsByTagName('r')))
        for count in (0,501,True,1.1,'2'):
            with self.subTest(count=count), self.assertRaises(ApiError): generate_new(variation(),count)

    def test_namespace_prefix_is_irrelevant_but_uri_and_attribute_set_matter(self):
        group=json.dumps([{'ns':'urn:t','name':'root','index':1},{'ns':'urn:t','name':'r','index':1}])
        template='<s:root xmlns:s="urn:t"><s:r id="1"><s:a>1</s:a></s:r></s:root>'
        validate_return_input(template,group,'<x:root xmlns:x="urn:t"><x:r id="2"><x:a>changed</x:a></x:r></x:root>')
        for xml in ['<root><r id="1"><a>1</a></r></root>','<s:root xmlns:s="urn:t"><s:r><s:a>1</s:a></s:r></s:root>']:
            with self.subTest(xml=xml),self.assertRaises(ApiError):validate_return_input(template,group,xml)

    def test_structure_checks_order_attributes_each_record_and_envelope(self):
        template='<root><h x="1" y="2"/><r><a/><b/></r><end/></root>'
        validate_return_input(template,path('root','r'),'<root><h y="9" x="8"/><!-- ignored --><r><a>value</a><b/></r><r><a/><b/></r><end/></root>')
        for xml in ['<root><h x="1" y="2"/><r><b/><a/></r><end/></root>', '<root><h x="1" y="2"/><r><a/><b/></r><r><a/><b z="1"/></r><end/></root>', '<root><h x="1" y="2"/><r><a/><b/></r></root>']:
            with self.subTest(xml=xml),self.assertRaises(ApiError):validate_return_input(template,path('root','r'),xml)

    def test_namespaced_attribute_and_second_sibling_path(self):
        v=variation();group=json.dumps([{'ns':'urn:t','name':'root','index':1},{'ns':'urn:t','name':'r','index':1}])
        v['config']['inputByMode']['new']={'xml':'<t:root xmlns:t="urn:t"><t:r t:id="old"><t:a>first</t:a><t:a><![CDATA[second]]></t:a></t:r></t:root>','group':group}
        attribute=json.dumps(json.loads(group)+[{'ns':'urn:t','name':'id','attribute':True}]);second=json.dumps(json.loads(group)+[{'ns':'urn:t','name':'a','index':2}])
        v['config']['rulesByMode']['new']={attribute:{'generator':{'type':'sequence','width':1}},second:{'fixed':']]> & café'}}
        doc=minidom.parseString(generate_new(v,2)[0]['content'])
        self.assertEqual(['1','2'],[n.getAttributeNS('urn:t','id') for n in doc.getElementsByTagNameNS('urn:t','r')])
        self.assertEqual(']]> & café',doc.getElementsByTagNameNS('urn:t','a')[3].firstChild.data)

    def test_forward_reference_and_global_decimal_sum(self):
        v=variation();v['config']['inputByMode']['new']['xml']='<root><total/><r><a>0</a><b>0</b></r></root>'
        v['config']['rulesByMode']['new']={path('root','total'):{'generator':{'type':'groupSum','source':'output','group':path('root','r'),'path':path('root','r','b'),'allRecords':True}},path('root','r','a'):{'generator':{'type':'field','source':'output','path':path('root','r','b')}},path('root','r','b'):{'generator':{'type':'random','min':0.1,'max':0.1,'decimals':1}}}
        content=generate_new(v,3)[0]['content']
        self.assertIn(b'<total>0.3</total>',content);self.assertEqual(3,content.count(b'<a>0.1</a>'))

    def test_nested_group_sum_per_record_and_all_input_records(self):
        v=variation();group=path('root','r');item=path('root','r','item');field=path('root','r','item','a')
        xml='<root><r><item><a>0.1</a></item><item><a>0.2</a></item></r><r><item><a>0.3</a></item><item><a>0.4</a></item></r></root>'
        v['config']['inputByMode']['return']={'xml':xml,'group':group}
        model=v['config']['returnModels'][0];model['rules']={path('out','r','a'):{'generator':{'type':'groupSum','source':'input','group':item,'path':field}}}
        content=generate_return(v,{'type':'all'},input_xml=xml)[0]['content'];self.assertIn(b'<a>0.3</a>',content);self.assertIn(b'<a>0.7</a>',content)
        model['rules'][path('out','r','a')]['generator']['allRecords']=True
        content=generate_return(v,{'type':'all'},input_xml=xml)[0]['content'];self.assertEqual(2,content.count(b'<a>1</a>'))

    def test_optional_alternate_and_required_empty(self):
        v=variation();v['config']['presenceByMode']={'new':{path('root','r','b'):{'requirement':'optional','include':True,'distribution':'alternate'}}}
        doc=minidom.parseString(generate_new(v,3)[0]['content']);self.assertEqual([1,0,1],[len(n.getElementsByTagName('b')) for n in doc.getElementsByTagName('r')])
        v['config']['rulesByMode']['new'][path('root','r','b')]={'fixed':''}
        v['config']['presenceByMode']['new'][path('root','r','b')]={'requirement':'required','include':True,'distribution':'all'}
        with self.assertRaises(ApiError):generate_new(v,1)

    def test_length_validate_input_and_output(self):
        v=variation();v['config']['rulesByMode']['new']={path('root','r','a'):{'fixed':'é😀abc','exactLength':2,'lengthTarget':'output'}}
        content=generate_new(v,1)[0]['content'];self.assertIn('<a>é😀</a>'.encode(),content)
        rule=v['config']['rulesByMode']['new'][path('root','r','a')];rule['lengthTarget']='validate'
        with self.assertRaises(ApiError):generate_new(v,1)
        rule.update(generator={'type':'copy','path':path('root','r','b')},fixed=None,exactLength=1,lengthTarget='input')
        self.assertIn(b'<a>2</a>',generate_new(v,1)[0]['content'])

    def test_orphan_rule_omitted_dependency_header_and_invalid_character_fail(self):
        v=variation();v['config']['rulesByMode']['new'][path('root','missing')]={'fixed':'x'}
        with self.assertRaises(ApiError):generate_new(v,1)
        v=variation();v['config']['headersByMode']={'new':[path('root','r')]}
        with self.assertRaises(ApiError):generate_new(v,1)
        v=variation();v['config']['rulesByMode']['new'][path('root','r','a')]={'fixed':'\x01'}
        with self.assertRaises(ApiError):generate_new(v,1)
        v=variation();v['config']['presenceByMode']={'new':{path('root','r','b'):{'requirement':'optional','include':False,'distribution':'all'}}};v['config']['rulesByMode']['new'][path('root','r','a')]={'generator':{'type':'field','path':path('root','r','b')}}
        with self.assertRaises(ApiError):generate_new(v,1)

    def test_root_unit_gets_studio_wrapper_for_multiple_new_records(self):
        v=variation();v['config']['inputByMode']['new']={'xml':'<r><a>1</a></r>','group':path('r')};v['config']['rulesByMode']['new']={path('r','a'):{'generator':{'type':'sequence'}}}
        doc=minidom.parseString(generate_new(v,2)[0]['content']);self.assertEqual('MockRegistros',doc.documentElement.tagName);self.assertEqual(2,len(doc.getElementsByTagName('r')))

    def test_selection_duplicates_unknown_and_incomplete_fail(self):
        for selection in [{'type':'ids','ids':['A','A']},{'type':'ids','ids':['B']},{'type':'ids','ids':[]}]:
            with self.subTest(selection=selection),self.assertRaises(ApiError):generate_return(variation(),selection,input_xml=variation()['config']['inputByMode']['return']['xml'])
        v=variation();v['config']['returnModels'][0]['outputXml']=''
        with self.assertRaises(ApiError):generate_return(v,{'type':'all'},input_xml=v['config']['inputByMode']['return']['xml'])

    def test_input_byte_size_depth_and_invalid_xml_fail(self):
        for xml in ['<root>','<root>'+('é'*1_000_000)+'</root>','<a>'*130+'</a>'*130]:
            with self.subTest(size=len(xml)),self.assertRaises(ApiError):validate_return_input('<root><r><a/></r></root>',path('root','r'),xml)

    def test_legacy_output_limit_does_not_apply_to_generation_or_serialization(self):
        from unittest.mock import patch
        actual_len = len
        def measured_size(value):
            return 100000001 if isinstance(value, bytes) and value.startswith(b'<?xml') else actual_len(value)
        with patch('mockaize_api.xml_engine.len',side_effect=measured_size,create=True):
            self.assertEqual(generate_new(variation(),10)[0]['records'],10)
            result=generate_return(variation(),{'type':'all'},input_xml=variation()['config']['inputByMode']['return']['xml'])
            self.assertEqual(result[0]['records'],1)

    def test_selected_order_overrides_saved_order(self):
        import copy
        v=variation();model=copy.deepcopy(v['config']['returnModels'][0]);model.update(id='B',name='B');v['config']['returnModels'].append(model)
        self.assertEqual(['B','A'],[i['returnId'] for i in generate_return(v,{'type':'ids','ids':['B','A']},input_xml=v['config']['inputByMode']['return']['xml'])])

    def test_mixed_rejects_different_header_value_and_record_shape(self):
        import copy
        for output in ['<out><h>B</h><r><a>A</a></r></out>','<out><h>A</h><r><b>A</b></r></out>']:
            v=variation();first=v['config']['returnModels'][0];first['outputXml']='<out><h>A</h><r><a>A</a></r></out>'
            second=copy.deepcopy(first);second.update(id='B',rules={},outputXml=output);v['config']['returnModels'].append(second)
            with self.subTest(output=output),self.assertRaises(ApiError) as caught:generate_return(v,{'type':'all'},'mixed',v['config']['inputByMode']['return']['xml'])
            self.assertEqual('RETURN_MODELS_INCOMPATIBLE',caught.exception.code)

    def test_record_count_cannot_move_units_across_footer(self):
        with self.assertRaises(ApiError):validate_return_input('<root><r><a/></r><footer/></root>',path('root','r'),'<root><r><a/></r><footer/><r><a/></r></root>')

    def test_mixed_preserves_matching_alternate_presence_per_input_record(self):
        import copy
        v=variation();model=v['config']['returnModels'][0];model['outputXml']='<out><r><a>A</a><b>optional</b></r></out>'
        model['presence']={path('out','r','b'):{'requirement':'optional','include':True,'distribution':'alternate'}}
        second=copy.deepcopy(model);second.update(id='B',name='B');v['config']['returnModels'].append(second)
        result=generate_return(v,{'type':'all'},'mixed','<root><r><a>1</a></r><r><a>2</a></r></root>')[0]
        doc=minidom.parseString(result['content']);self.assertEqual([1,1,0,0],[len(r.getElementsByTagName('b')) for r in doc.getElementsByTagName('r')])

    def test_public_errors_do_not_expose_invalid_formula_values(self):
        v=variation();v['config']['rulesByMode']['new'][path('root','r','a')]={'generator':{'type':'sequence','start':'PRIVATE-FORMULA-VALUE'}}
        with self.assertRaises(ApiError) as caught:generate_new(v,1)
        self.assertNotIn('PRIVATE-FORMULA-VALUE',caught.exception.detail)
        model=v['config']['returnModels'][0];model['rules']={path('out','r','a'):{'generator':{'type':'sequence','start':'PRIVATE-RETURN-VALUE'}}}
        with self.assertRaises(ApiError) as caught:generate_return(v,{'type':'all'},input_xml=v['config']['inputByMode']['return']['xml'])
        self.assertNotIn('PRIVATE-RETURN-VALUE',caught.exception.detail)

    def test_default_input_limit_uses_413(self):
        with self.assertRaises(ApiError) as caught:validate_return_input('<root><r><a/></r></root>',path('root','r'),'<root>'+('é'*1_000_000)+'</root>')
        self.assertEqual((413,'INPUT_TOO_LARGE'),(caught.exception.status,caught.exception.code))

    def test_mixed_retains_namespace_bindings_from_each_source_envelope(self):
        import copy
        for prefix in ['b','']:
            v=variation();first=v['config']['returnModels'][0]
            group=json.dumps([{'ns':'urn:o','name':'out','index':1},{'ns':'urn:o','name':'r','index':1}])
            first.update(outputXml='<a:out xmlns:a="urn:o" xmlns:x="urn:attr"><a:r x:id="1"><a:v>A</a:v></a:r></a:out>',outputGroup=group,rules={})
            second=copy.deepcopy(first);second.update(id='B',name='B')
            second['outputXml']='<b:out xmlns:b="urn:o" xmlns:y="urn:attr"><b:r y:id="2"><b:v>B</b:v></b:r></b:out>' if prefix else '<out xmlns="urn:o" xmlns:y="urn:attr"><r y:id="2"><v>B</v></r></out>'
            v['config']['returnModels'].append(second)
            doc=minidom.parseString(generate_return(v,{'type':'all'},'mixed',v['config']['inputByMode']['return']['xml'])[0]['content'])
            units=doc.getElementsByTagNameNS('urn:o','r');self.assertEqual(2,len(units));self.assertEqual('2',units[1].getAttributeNS('urn:attr','id'))
